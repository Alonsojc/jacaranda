"""Servicio de backup/restore. Soporta SQLite y PostgreSQL."""

import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from app.core.config import settings

BACKUP_DIR = Path("/tmp/jacaranda_backups")


def _ensure_backup_dir():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def _is_sqlite() -> bool:
    return settings.DATABASE_URL.startswith("sqlite")


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def crear_backup() -> dict:
    """Crea backup de la base de datos."""
    _ensure_backup_dir()
    ts = _timestamp()

    if _is_sqlite():
        db_path = settings.DATABASE_URL.replace("sqlite:///", "")
        src = Path(db_path)
        if not src.exists():
            raise FileNotFoundError("Base de datos SQLite no encontrada")
        filename = f"jacaranda_{ts}.db"
        dest = BACKUP_DIR / filename
        shutil.copy2(str(src), str(dest))
    else:
        parsed = urlparse(settings.DATABASE_URL)
        filename = f"jacaranda_{ts}.sql"
        dest = BACKUP_DIR / filename
        env = {**os.environ, "PGPASSWORD": parsed.password or ""}
        cmd = [
            "pg_dump",
            "-h", parsed.hostname or "localhost",
            "-p", str(parsed.port or 5432),
            "-U", parsed.username or "postgres",
            "-d", parsed.path[1:],
            "-f", str(dest),
        ]
        result = subprocess.run(cmd, env=env, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"pg_dump failed: {result.stderr}")

    size = dest.stat().st_size
    return {
        "filename": filename,
        "path": str(dest),
        "size_bytes": size,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "db_type": "sqlite" if _is_sqlite() else "postgresql",
    }


def restaurar_backup(file_content: bytes, filename: str) -> dict:
    """Restaura backup desde archivo subido."""
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
        tmp_file = BACKUP_DIR / f"restore_{_timestamp()}.sql"
        _ensure_backup_dir()
        with open(tmp_file, "wb") as f:
            f.write(file_content)
        env = {**os.environ, "PGPASSWORD": parsed.password or ""}
        cmd = [
            "psql",
            "-h", parsed.hostname or "localhost",
            "-p", str(parsed.port or 5432),
            "-U", parsed.username or "postgres",
            "-d", parsed.path[1:],
            "-f", str(tmp_file),
        ]
        result = subprocess.run(cmd, env=env, capture_output=True, text=True)
        tmp_file.unlink(missing_ok=True)
        if result.returncode != 0:
            raise RuntimeError(f"psql restore failed: {result.stderr}")
        return {"ok": True, "message": "Backup PostgreSQL restaurado"}


def listar_backups() -> list[dict]:
    """Lista backups disponibles."""
    _ensure_backup_dir()
    backups = []
    for f in sorted(BACKUP_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if f.name.startswith("jacaranda_") and f.suffix in (".db", ".sql"):
            stat = f.stat()
            backups.append({
                "filename": f.name,
                "size_bytes": stat.st_size,
                "created_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            })
    return backups


def backup_programado() -> dict:
    """Backup con auto-limpieza de archivos > 7 días."""
    _ensure_backup_dir()
    # Cleanup old backups
    cutoff = datetime.now(timezone.utc).timestamp() - (7 * 86400)
    for f in BACKUP_DIR.iterdir():
        if f.name.startswith("jacaranda_") and f.stat().st_mtime < cutoff:
            f.unlink()
    return crear_backup()
