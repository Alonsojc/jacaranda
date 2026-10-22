"""Servicio de backup/restore. Soporta SQLite y PostgreSQL."""

import hashlib
import os
import shutil
import sqlite3
import subprocess
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from urllib.parse import unquote, urlparse, urlsplit

from sqlalchemy.engine import make_url

from app.core.config import settings


def _setting_int(name: str, default: int) -> int:
    value = getattr(settings, name, default)
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _setting_bool(name: str, default: bool = False) -> bool:
    value = getattr(settings, name, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return default


def _is_production() -> bool:
    value = getattr(settings, "is_production", False)
    return value if isinstance(value, bool) else False


def _backup_dir() -> Path:
    value = getattr(settings, "BACKUP_DIR", "")
    if isinstance(value, str) and value:
        return Path(value)
    source = _sqlite_source()
    return source.parent / "backups" if source is not None else Path("/tmp/jacaranda_backups")


def _ensure_backup_dir():
    backup_dir = _backup_dir()
    try:
        if backup_dir.is_symlink():
            raise RuntimeError("BACKUP_DIR no puede ser un enlace simbolico")
        backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        backup_dir.chmod(0o700)
    except OSError as exc:
        raise RuntimeError(
            f"No se pudo crear BACKUP_DIR={backup_dir}. "
            "Verifique que el volume esté montado y tenga permisos de escritura."
        ) from exc
    if not os.access(backup_dir, os.W_OK):
        raise RuntimeError(
            f"BACKUP_DIR={backup_dir} no tiene permisos de escritura."
        )


def _is_sqlite() -> bool:
    return settings.DATABASE_URL.startswith("sqlite")


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")


def _sqlite_source() -> Path | None:
    if not _is_sqlite():
        return None
    url = make_url(settings.DATABASE_URL)
    database = url.database
    if database and database.startswith("file:") and str(url.query.get("uri", "")).lower() in {"true", "1"}:
        uri = urlsplit(database)
        if uri.netloc not in {"", "localhost"}:
            raise RuntimeError("El URI SQLite debe apuntar a un archivo local")
        database = unquote(uri.path)
        if url.query.get("mode") == "memory":
            return None
    if not database or database == ":memory:":
        return None
    return Path(database)


def _is_live_source(path: Path) -> bool:
    source = _sqlite_source()
    return source is not None and source.exists() and path.samefile(source)


def _backup_files() -> list[Path]:
    backup_dir = _backup_dir()
    if not backup_dir.exists():
        return []
    return [
        f for f in backup_dir.iterdir()
        if f.name.startswith("jacaranda_") and f.suffix in (".db", ".sql")
        and not f.is_symlink() and f.is_file() and not _is_live_source(f)
    ]


def _sorted_backup_files() -> list[Path]:
    return sorted(_backup_files(), key=lambda x: x.stat().st_mtime, reverse=True)


def _max_backup_files() -> int:
    return max(_setting_int("BACKUP_MAX_FILES", 20), 1)


def _backup_info(path: Path) -> dict:
    stat = path.stat()
    return {
        "filename": path.name,
        "path": str(path),
        "size_bytes": stat.st_size,
        "created_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    }


def _resolver_backup_path(filename: str | None = None) -> Path:
    _ensure_backup_dir()
    if filename:
        clean_name = Path(filename).name
        if clean_name != filename or not clean_name.startswith("jacaranda_"):
            raise ValueError("Nombre de backup inválido")
        if Path(clean_name).suffix not in (".db", ".sql"):
            raise ValueError("Extensión de backup inválida")
        target = _backup_dir() / clean_name
        if not target.exists():
            raise FileNotFoundError("Backup no encontrado")
        if target not in _backup_files():
            raise ValueError("El respaldo debe ser un archivo regular, no la base activa ni un enlace")
        return target

    backups = _sorted_backup_files()
    if not backups:
        raise FileNotFoundError("No hay backups guardados. Cree un backup primero.")
    return backups[0]


def _postgres_env(parsed):
    return {**os.environ, "PGPASSWORD": parsed.password or ""}


def _postgres_cmd_base(parsed) -> list[str]:
    return [
        "-h", parsed.hostname or "localhost",
        "-p", str(parsed.port or 5432),
        "-U", parsed.username or "postgres",
        "-d", parsed.path[1:],
    ]


def limpiar_backups_antiguos() -> int:
    """Limpieza explicita; siempre conserva al menos el respaldo mas reciente."""
    retention_days = max(_setting_int("BACKUP_RETENTION_DAYS", 7), 1)
    cutoff = datetime.now(timezone.utc).timestamp() - (retention_days * 86400)
    removed = 0
    backups = _sorted_backup_files()
    for f in backups[1:]:
        if f.exists() and f.stat().st_mtime < cutoff:
            f.unlink()
            removed += 1
    for f in _sorted_backup_files()[_max_backup_files():]:
        if f.exists():
            f.unlink()
            removed += 1
    return removed


def crear_backup() -> dict:
    """Publica una copia consistente y privada sin eliminar respaldos por defecto."""
    _ensure_backup_dir()
    ts = _timestamp()
    backup_dir = _backup_dir()
    fd, pending_name = tempfile.mkstemp(prefix=f".jacaranda_{ts}_", suffix=".pending", dir=backup_dir)
    os.close(fd)
    pending = Path(pending_name)
    suffix = ".db" if _is_sqlite() else ".sql"
    filename = pending.name[1:-len(".pending")] + suffix
    dest = backup_dir / filename
    timeout = max(_setting_int("BACKUP_TIMEOUT_SECONDS", 300), 1)
    try:
        if _is_sqlite():
            src = _sqlite_source()
            if src is None or not src.is_file() or src.stat().st_size == 0:
                raise FileNotFoundError("Base de datos SQLite no encontrada")
            deadline = monotonic() + timeout

            def progress(_status, _remaining, _total):
                if monotonic() > deadline:
                    raise RuntimeError("El respaldo excedio el tiempo permitido; no se borraron copias anteriores")

            with closing(sqlite3.connect(src.resolve().as_uri() + "?mode=ro", uri=True)) as source, \
                    closing(sqlite3.connect(pending)) as target:
                source.backup(target, pages=256, progress=progress)
                if target.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise RuntimeError("La copia SQLite no paso la verificacion de integridad")
        else:
            parsed = urlparse(settings.DATABASE_URL)
            cmd = ["pg_dump", *_postgres_cmd_base(parsed), "--no-password",
                   "--lock-wait-timeout=5s", "-f", str(pending)]
            result = subprocess.run(cmd, env=_postgres_env(parsed), capture_output=True,
                                    text=True, timeout=timeout)
            if result.returncode != 0:
                raise RuntimeError("No se pudo crear el respaldo PostgreSQL; revise acceso y version de pg_dump")
        if pending.stat().st_size == 0:
            raise RuntimeError("El respaldo generado esta vacio")
        with pending.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
            os.fsync(stream.fileno())
        # Enlace atomico: nunca sobrescribe otra copia ni publica un archivo parcial.
        os.link(pending, dest)
    except sqlite3.Error:
        raise RuntimeError("No se pudo crear una copia SQLite consistente") from None
    except subprocess.TimeoutExpired:
        raise RuntimeError("pg_dump excedio el tiempo permitido; se conservaron los respaldos anteriores") from None
    finally:
        pending.unlink(missing_ok=True)
    size = dest.stat().st_size
    removed = limpiar_backups_antiguos() if _setting_bool("BACKUP_AUTO_CLEANUP") else 0
    return {
        "filename": filename,
        "path": str(dest),
        "size_bytes": size,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "db_type": "sqlite" if _is_sqlite() else "postgresql",
        "removed_old_backups": removed,
        "sha256": checksum,
    }


def obtener_ultimo_backup() -> dict:
    """Regresa el respaldo más reciente sin crear uno nuevo."""
    _ensure_backup_dir()
    backups = _sorted_backup_files()
    if not backups:
        raise FileNotFoundError("No hay backups guardados. Cree un backup primero.")
    info = _backup_info(backups[0])
    info["db_type"] = "sqlite" if _is_sqlite() else "postgresql"
    return info


def preparar_descarga_backup(filename: str | None = None) -> dict:
    """Copia privada de un respaldo completo, fuera de la retencion durante el envio."""
    source = _resolver_backup_path(filename)
    info = _backup_info(source)
    fd, temporary = tempfile.mkstemp(prefix=".download_", dir=_backup_dir())
    try:
        with os.fdopen(fd, "wb") as target, source.open("rb") as stream:
            shutil.copyfileobj(stream, target)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise
    info["path"] = temporary
    return info


def eliminar_backup(filename: str) -> dict:
    """Elimina un respaldo manual, excepto el más reciente."""
    _ensure_backup_dir()
    clean_name = Path(filename).name
    if clean_name != filename or not clean_name.startswith("jacaranda_"):
        raise ValueError("Nombre de backup inválido")
    if Path(clean_name).suffix not in (".db", ".sql"):
        raise ValueError("Extensión de backup inválida")

    backups = _sorted_backup_files()
    if not backups:
        raise FileNotFoundError("No hay backups guardados")
    if backups[0].name == clean_name:
        raise ValueError("No se puede borrar el backup más reciente")

    target = next((f for f in backups if f.name == clean_name), None)
    if target is None:
        raise FileNotFoundError("Backup no encontrado")

    info = _backup_info(target)
    target.unlink()
    return info


def restaurar_backup(file_content: bytes, filename: str) -> dict:
    """Restaura backup desde archivo subido."""
    if _is_production() and not _setting_bool("ALLOW_DB_RESTORE", False):
        raise ValueError(
            "Restauración de base de datos deshabilitada en producción. "
            "Active ALLOW_DB_RESTORE=true solo durante una ventana controlada."
        )

    if _is_sqlite():
        if not filename.endswith(".db"):
            raise ValueError("Para SQLite, suba un archivo .db")
        db_path = settings.DATABASE_URL.replace("sqlite:///", "")
        # Create safety backup first
        safety = Path(f"{db_path}.safety_{_timestamp()}")
        src = Path(db_path)
        if src.exists():
            shutil.copy2(str(src), str(safety))
        with open(db_path, "wb") as f:
            f.write(file_content)
        return {"ok": True, "message": "Backup SQLite restaurado", "safety_backup": str(safety)}
    else:
        if not filename.endswith(".sql"):
            raise ValueError("Para PostgreSQL, suba un archivo .sql")
        parsed = urlparse(settings.DATABASE_URL)
        _ensure_backup_dir()
        tmp_file = _backup_dir() / f"restore_{_timestamp()}.sql"
        with open(tmp_file, "wb") as f:
            f.write(file_content)
        env = _postgres_env(parsed)
        cmd = ["psql", *_postgres_cmd_base(parsed), "-f", str(tmp_file)]
        result = subprocess.run(cmd, env=env, capture_output=True, text=True)
        tmp_file.unlink(missing_ok=True)
        if result.returncode != 0:
            raise RuntimeError(f"psql restore failed: {result.stderr}")
        return {"ok": True, "message": "Backup PostgreSQL restaurado"}


def _verificar_sqlite_backup(path: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix="jacaranda_restore_check_") as tmp_dir:
        copy_path = Path(tmp_dir) / path.name
        shutil.copy2(str(path), str(copy_path))
        conn = sqlite3.connect(copy_path)
        try:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            table_rows = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
            tables = [row[0] for row in table_rows]
            counts = {}
            for table in tables:
                safe_table = table.replace('"', '""')
                counts[table] = conn.execute(
                    f'SELECT COUNT(*) FROM "{safe_table}"'
                ).fetchone()[0]
        finally:
            conn.close()

    if str(integrity).lower() != "ok":
        raise RuntimeError(f"El backup SQLite no pasó integrity_check: {integrity}")
    if not tables:
        raise RuntimeError("El backup SQLite no contiene tablas restaurables")

    return {
        "ok": True,
        "filename": path.name,
        "db_type": "sqlite",
        "restore_mode": "sqlite_copy",
        "restored": True,
        "integrity_check": integrity,
        "table_count": len(tables),
        "tables": counts,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def _verificar_postgres_dump_por_inspeccion(path: Path) -> dict:
    key_tables = {
        name: False
        for name in ("ventas", "pedidos", "productos", "clientes", "usuarios")
    }
    has_schema = False
    has_data = False
    with path.open("r", encoding="utf-8", errors="replace") as dump_file:
        for line in dump_file:
            if not has_schema and ("CREATE TABLE" in line or "CREATE SCHEMA" in line):
                has_schema = True
            if not has_data and (line.startswith("COPY ") or line.startswith("INSERT INTO ")):
                has_data = True
            for name in key_tables:
                if name in line:
                    key_tables[name] = True
            if has_schema and has_data and all(key_tables.values()):
                break
    if not has_schema:
        raise RuntimeError("El archivo SQL no parece contener esquema restaurable")

    return {
        "ok": True,
        "filename": path.name,
        "db_type": "postgresql",
        "restore_mode": "sql_inspection",
        "restored": False,
        "has_schema": has_schema,
        "has_data": has_data,
        "key_tables": key_tables,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "warning": (
            "Solo se inspecciono el SQL; no se comprobo su restauracion. "
            "La restauracion completa requiere un entorno aislado fuera de la "
            "aplicacion, sin credenciales ni acceso a la base operativa."
        ),
    }


def verificar_restauracion_backup(filename: str | None = None) -> dict:
    """SQLite se prueba en copia; PostgreSQL solo se inspecciona, nunca se ejecuta."""
    path = _resolver_backup_path(filename)
    if path.stat().st_size == 0:
        raise ValueError("Backup vacío")
    if path.suffix == ".db":
        return _verificar_sqlite_backup(path)
    if path.suffix == ".sql":
        return _verificar_postgres_dump_por_inspeccion(path)
    raise ValueError("Extensión de backup inválida")


def listar_backups() -> list[dict]:
    """Lista backups disponibles."""
    _ensure_backup_dir()
    backups = []
    for index, f in enumerate(_sorted_backup_files()):
        info = _backup_info(f)
        info.pop("path", None)
        info["is_latest"] = index == 0
        backups.append(info)
    return backups


def estado_backup() -> dict:
    """Estado operativo de respaldos para que el admin sepa si está protegido."""
    backup_dir_error = None
    backups = []
    try:
        backups = listar_backups()
    except (OSError, RuntimeError) as exc:
        backup_dir_error = str(exc)
    db_type = "sqlite" if _is_sqlite() else "postgresql"
    return {
        "db_type": db_type,
        "backup_dir": str(_backup_dir()),
        "backup_dir_exists": _backup_dir().exists(),
        "backup_dir_writable": backup_dir_error is None,
        "backup_dir_error": backup_dir_error,
        "backup_count": len(backups),
        "last_backup": backups[0] if backups else None,
        "retention_days": max(_setting_int("BACKUP_RETENTION_DAYS", 7), 1),
        "max_backups": _max_backup_files(),
        "auto_cleanup_enabled": _setting_bool("BACKUP_AUTO_CLEANUP"),
        "restore_enabled": (not _is_production()) or _setting_bool("ALLOW_DB_RESTORE", False),
        "pg_dump_available": shutil.which("pg_dump") is not None if db_type == "postgresql" else None,
        "psql_available": shutil.which("psql") is not None if db_type == "postgresql" else None,
    }


def backup_programado() -> dict:
    """Usa las mismas garantias de publicacion y retencion que el respaldo manual."""
    return crear_backup()
