"""Servicio de backup/restore. Soporta SQLite y PostgreSQL."""

import os
import shutil
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

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
    value = getattr(settings, "BACKUP_DIR", "/tmp/jacaranda_backups")
    if not isinstance(value, str):
        value = "/tmp/jacaranda_backups"
    return Path(value)


def _ensure_backup_dir():
    backup_dir = _backup_dir()
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
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


def _backup_files() -> list[Path]:
    backup_dir = _backup_dir()
    if not backup_dir.exists():
        return []
    return [
        f for f in backup_dir.iterdir()
        if f.name.startswith("jacaranda_") and f.suffix in (".db", ".sql")
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
    """Elimina respaldos fuera de retención y por arriba del máximo permitido."""
    retention_days = max(_setting_int("BACKUP_RETENTION_DAYS", 7), 1)
    cutoff = datetime.now(timezone.utc).timestamp() - (retention_days * 86400)
    removed = 0
    for f in list(_backup_files()):
        if f.exists() and f.stat().st_mtime < cutoff:
            f.unlink()
            removed += 1
    for f in _sorted_backup_files()[_max_backup_files():]:
        if f.exists():
            f.unlink()
            removed += 1
    return removed


def crear_backup() -> dict:
    """Crea backup de la base de datos."""
    _ensure_backup_dir()
    limpiar_backups_antiguos()
    ts = _timestamp()
    backup_dir = _backup_dir()

    if _is_sqlite():
        db_url = settings.DATABASE_URL
        if db_url in ("sqlite://", "sqlite:///"):
            raise FileNotFoundError("Base de datos in-memory no se puede respaldar")
        db_path = db_url.replace("sqlite:///", "")
        src = Path(db_path)
        if not src.exists() or src.stat().st_size == 0:
            raise FileNotFoundError("Base de datos SQLite no encontrada")
        filename = f"jacaranda_{ts}.db"
        dest = backup_dir / filename
        shutil.copyfile(str(src), str(dest))
        os.utime(dest, None)
    else:
        parsed = urlparse(settings.DATABASE_URL)
        filename = f"jacaranda_{ts}.sql"
        dest = backup_dir / filename
        env = _postgres_env(parsed)
        cmd = ["pg_dump", *_postgres_cmd_base(parsed), "-f", str(dest)]
        result = subprocess.run(cmd, env=env, capture_output=True, text=True)
        if result.returncode != 0:
            dest.unlink(missing_ok=True)
            raise RuntimeError(f"pg_dump failed: {result.stderr}")

    size = dest.stat().st_size
    removed = limpiar_backups_antiguos()
    return {
        "filename": filename,
        "path": str(dest),
        "size_bytes": size,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "db_type": "sqlite" if _is_sqlite() else "postgresql",
        "removed_old_backups": removed,
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
        "has_schema": has_schema,
        "has_data": has_data,
        "key_tables": key_tables,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "warning": (
            "Se validó que el SQL sea legible y tenga estructura. Para una prueba "
            "de restauración completa, configure BACKUP_VERIFY_DATABASE_URL con "
            "una base temporal."
        ),
    }


def _verificar_postgres_backup_en_base_temporal(path: Path, database_url: str) -> dict:
    parsed = urlparse(database_url)
    db_name = parsed.path[1:]
    if not db_name:
        raise ValueError("BACKUP_VERIFY_DATABASE_URL no tiene nombre de base de datos")
    if not any(token in db_name.lower() for token in ("verify", "restore", "test", "backup")):
        raise ValueError(
            "BACKUP_VERIFY_DATABASE_URL debe apuntar a una base temporal cuyo "
            "nombre contenga verify, restore, test o backup"
        )
    env = _postgres_env(parsed)
    base = _postgres_cmd_base(parsed)
    reset = subprocess.run(
        [
            "psql",
            *base,
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            "DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;",
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    if reset.returncode != 0:
        raise RuntimeError(f"No se pudo preparar la base temporal: {reset.stderr}")

    restore = subprocess.run(
        ["psql", *base, "-v", "ON_ERROR_STOP=1", "-f", str(path)],
        env=env,
        capture_output=True,
        text=True,
    )
    if restore.returncode != 0:
        raise RuntimeError(f"Restore de prueba falló: {restore.stderr}")

    count = subprocess.run(
        [
            "psql",
            *base,
            "-At",
            "-c",
            "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';",
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    table_count = int((count.stdout or "0").strip() or "0") if count.returncode == 0 else 0
    if table_count <= 0:
        raise RuntimeError("La restauración de prueba no creó tablas")

    return {
        "ok": True,
        "filename": path.name,
        "db_type": "postgresql",
        "restore_mode": "postgres_verify_database",
        "verify_database": db_name,
        "table_count": table_count,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def verificar_restauracion_backup(filename: str | None = None) -> dict:
    """Prueba un respaldo en una copia/ambiente seguro, sin tocar producción."""
    path = _resolver_backup_path(filename)
    if path.stat().st_size == 0:
        raise ValueError("Backup vacío")
    if path.suffix == ".db":
        return _verificar_sqlite_backup(path)
    if path.suffix == ".sql":
        verify_url = getattr(settings, "BACKUP_VERIFY_DATABASE_URL", "") or ""
        if verify_url:
            return _verificar_postgres_backup_en_base_temporal(path, verify_url)
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
        "restore_enabled": (not _is_production()) or _setting_bool("ALLOW_DB_RESTORE", False),
        "pg_dump_available": shutil.which("pg_dump") is not None if db_type == "postgresql" else None,
        "psql_available": shutil.which("psql") is not None if db_type == "postgresql" else None,
    }


def backup_programado() -> dict:
    """Backup con auto-limpieza según BACKUP_RETENTION_DAYS."""
    _ensure_backup_dir()
    limpiar_backups_antiguos()
    return crear_backup()
