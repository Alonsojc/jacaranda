"""Tests para backup y restauración."""

import hashlib
import os
import sqlite3
import stat
import subprocess
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services import backup_service


@pytest.fixture(autouse=True)
def isolated_backup_settings(monkeypatch, tmp_path):
    monkeypatch.setattr(backup_service.settings, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(backup_service.settings, "BACKUP_VERIFY_DATABASE_URL", "")
    monkeypatch.setattr(backup_service.settings, "BACKUP_AUTO_CLEANUP", False)


def _configure_file_backups(monkeypatch, tmp_path, max_files=20):
    _, backup_dir = _configure_sqlite_backups(monkeypatch, tmp_path)
    monkeypatch.setattr(backup_service.settings, "BACKUP_MAX_FILES", max_files, raising=False)
    return backup_dir


def _configure_sqlite_backups(monkeypatch, tmp_path):
    db_file = tmp_path / "jacaranda.db"
    conn = sqlite3.connect(db_file)
    try:
        conn.execute("CREATE TABLE productos (id INTEGER PRIMARY KEY, nombre TEXT)")
        conn.execute("INSERT INTO productos (nombre) VALUES ('Brownie')")
        conn.commit()
    finally:
        conn.close()
    backup_dir = tmp_path / "backups"
    monkeypatch.setattr(backup_service.settings, "DATABASE_URL", f"sqlite:///{db_file}", raising=False)
    monkeypatch.setattr(backup_service.settings, "BACKUP_DIR", str(backup_dir), raising=False)
    monkeypatch.setattr(backup_service.settings, "BACKUP_RETENTION_DAYS", 7, raising=False)
    monkeypatch.setattr(backup_service.settings, "BACKUP_MAX_FILES", 20, raising=False)
    return db_file, backup_dir


class TestBackup:

    def test_crear_backup_in_memory_returns_error(self, client, auth_headers):
        """In-memory SQLite can't be backed up - expect 500."""
        with patch("app.services.backup_service.settings") as mock_settings:
            mock_settings.DATABASE_URL = "sqlite://"
            resp = client.post("/api/v1/backup/crear", headers=auth_headers)
        # In-memory SQLite has no file, so backup fails with 500
        assert resp.status_code == 500

    def test_descargar_backup_sin_archivos_returns_error(self, client, auth_headers, tmp_path):
        """Downloading now uses the latest existing backup instead of creating one."""
        with patch("app.services.backup_service.settings") as mock_settings:
            mock_settings.DATABASE_URL = "sqlite://"
            mock_settings.BACKUP_DIR = str(tmp_path / "empty_backups")
            mock_settings.BACKUP_RETENTION_DAYS = 7
            mock_settings.BACKUP_MAX_FILES = 20
            resp = client.get("/api/v1/backup/descargar", headers=auth_headers)
        assert resp.status_code == 404

    def test_listar_backups(self, client, auth_headers):
        # Create one first
        client.post("/api/v1/backup/crear", headers=auth_headers)
        resp = client.get("/api/v1/backup/listar", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_estado_backup(self, client, auth_headers):
        resp = client.get("/api/v1/backup/estado", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "db_type" in data
        assert "backup_dir" in data
        assert "restore_enabled" in data

    def test_sin_autenticacion(self, client):
        resp = client.post("/api/v1/backup/crear")
        assert resp.status_code in (401, 403)

    def test_restaurar_archivo_vacio(self, client, auth_headers):
        import io
        resp = client.post("/api/v1/backup/restaurar",
                           files={"file": ("empty.db", io.BytesIO(b""), "application/octet-stream")},
                           headers=auth_headers)
        assert resp.status_code == 400

    def test_descargar_backup_no_crea_archivo_extra(self, client, auth_headers, monkeypatch, tmp_path):
        _configure_file_backups(monkeypatch, tmp_path)

        first = client.post("/api/v1/backup/crear", headers=auth_headers).json()["filename"]
        time.sleep(0.01)
        latest = client.post("/api/v1/backup/crear", headers=auth_headers).json()["filename"]

        before = client.get("/api/v1/backup/listar", headers=auth_headers).json()
        resp = client.get("/api/v1/backup/descargar", headers=auth_headers)
        after = client.get("/api/v1/backup/listar", headers=auth_headers).json()

        assert resp.status_code == 200
        assert latest in resp.headers["content-disposition"]
        assert len(after) == len(before) == 2
        assert first in {item["filename"] for item in after}

    def test_eliminar_backup_bloquea_ultimo_y_borra_anterior(self, client, auth_headers, monkeypatch, tmp_path):
        _configure_file_backups(monkeypatch, tmp_path)

        old = client.post("/api/v1/backup/crear", headers=auth_headers).json()["filename"]
        time.sleep(0.01)
        latest = client.post("/api/v1/backup/crear", headers=auth_headers).json()["filename"]

        delete_headers = {
            **auth_headers,
            "X-Admin-Override-Motivo": "Rotacion manual de respaldo",
        }
        protected = client.delete(f"/api/v1/backup/{latest}", headers=delete_headers)
        removed = client.delete(f"/api/v1/backup/{old}", headers=delete_headers)
        items = client.get("/api/v1/backup/listar", headers=auth_headers).json()

        assert protected.status_code == 400
        assert protected.json()["detail"] == "No se puede borrar el backup más reciente"
        assert removed.status_code == 200
        assert [item["filename"] for item in items] == [latest]
        assert items[0]["is_latest"] is True

    def test_crear_backup_respeta_maximo_de_archivos(self, client, auth_headers, monkeypatch, tmp_path):
        _configure_file_backups(monkeypatch, tmp_path, max_files=2)
        monkeypatch.setattr(backup_service.settings, "BACKUP_AUTO_CLEANUP", True)

        for _ in range(4):
            resp = client.post("/api/v1/backup/crear", headers=auth_headers)
            assert resp.status_code == 200
            time.sleep(0.01)

        items = client.get("/api/v1/backup/listar", headers=auth_headers).json()
        estado = client.get("/api/v1/backup/estado", headers=auth_headers).json()

        assert len(items) == 2
        assert estado["max_backups"] == 2

    def test_verificar_restauracion_prueba_sqlite_en_copia(
        self, client, auth_headers, monkeypatch, tmp_path
    ):
        db_file, _backup_dir = _configure_sqlite_backups(monkeypatch, tmp_path)

        created = client.post("/api/v1/backup/crear", headers=auth_headers)
        resp = client.post("/api/v1/backup/verificar", headers=auth_headers)

        assert created.status_code == 200
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["restore_mode"] == "sqlite_copy"
        assert data["integrity_check"] == "ok"
        assert data["tables"]["productos"] == 1

        conn = sqlite3.connect(db_file)
        try:
            assert conn.execute("SELECT COUNT(*) FROM productos").fetchone()[0] == 1
        finally:
            conn.close()

    def test_verificar_restauracion_rechaza_backup_invalido(
        self, client, auth_headers, monkeypatch, tmp_path
    ):
        _configure_sqlite_backups(monkeypatch, tmp_path)

        resp = client.post(
            "/api/v1/backup/verificar",
            json={"filename": "../jacaranda_bad.db"},
            headers=auth_headers,
        )

        assert resp.status_code == 400
        assert resp.json()["detail"] == "Nombre de backup inválido"


def _aged_backup(backup_dir):
    backup_dir.mkdir(exist_ok=True)
    old = backup_dir / "jacaranda_previous.db"
    old.write_bytes(b"previous recovery point")
    os.utime(old, (time.time() - 30 * 86400,) * 2)
    return old


@pytest.mark.parametrize("capture", [backup_service.crear_backup, backup_service.backup_programado])
@pytest.mark.parametrize("invalid_source", ["missing", "invalid_sqlite"])
def test_failed_capture_preserves_previous_backups(monkeypatch, tmp_path, capture, invalid_source):
    source, directory = _configure_sqlite_backups(monkeypatch, tmp_path)
    old = _aged_backup(directory)
    monkeypatch.setattr(backup_service.settings, "BACKUP_AUTO_CLEANUP", True)
    if invalid_source == "missing":
        source.unlink()
    else:
        source.write_bytes(b"not a sqlite database")
    with pytest.raises((FileNotFoundError, RuntimeError)):
        capture()
    assert old.read_bytes() == b"previous recovery point"
    assert list(directory.iterdir()) == [old]


def test_capture_preserves_all_previous_files_by_default(monkeypatch, tmp_path):
    _, directory = _configure_sqlite_backups(monkeypatch, tmp_path)
    old = _aged_backup(directory)
    monkeypatch.setattr(backup_service.settings, "BACKUP_MAX_FILES", 1)
    for _ in range(3):
        assert backup_service.crear_backup()["removed_old_backups"] == 0
    assert old.exists()
    assert len(backup_service.listar_backups()) == 4
    assert backup_service.estado_backup()["auto_cleanup_enabled"] is False


def test_explicit_cleanup_never_removes_the_last_backup(monkeypatch, tmp_path):
    _, directory = _configure_sqlite_backups(monkeypatch, tmp_path)
    old = _aged_backup(directory)
    assert backup_service.limpiar_backups_antiguos() == 0
    assert old.exists()


@pytest.mark.parametrize("endpoint", ["/api/v1/backup/crear", "/api/v1/auditoria/backup", "/api/v1/reportes/backup"])
def test_all_snapshot_routes_include_committed_wal_rows(client, auth_headers, monkeypatch, tmp_path, endpoint):
    source, directory = _configure_sqlite_backups(monkeypatch, tmp_path)
    connection = sqlite3.connect(source)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("INSERT INTO productos (nombre) VALUES ('Committed WAL sentinel')")
        connection.commit()
        assert Path(str(source) + "-wal").stat().st_size > 0
        response = (client.get if endpoint.endswith("reportes/backup") else client.post)(endpoint, headers=auth_headers)
        assert response.status_code == 200
        info = backup_service.obtener_ultimo_backup()
        copied = sqlite3.connect(info["path"])
        try:
            assert copied.execute("SELECT nombre FROM productos ORDER BY id").fetchall() == [
                ("Brownie",), ("Committed WAL sentinel",),
            ]
            assert copied.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            copied.close()
        assert connection.execute("SELECT COUNT(*) FROM productos").fetchone()[0] == 2
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
        assert stat.S_IMODE(Path(info["path"]).stat().st_mode) == 0o600
    finally:
        connection.close()


def test_checksum_and_failure_to_publish_preserve_existing_files(monkeypatch, tmp_path):
    _, directory = _configure_sqlite_backups(monkeypatch, tmp_path)
    created = backup_service.crear_backup()
    path = Path(created["path"])
    assert created["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    with patch.object(backup_service.os, "link", side_effect=OSError("publication failed")):
        with pytest.raises(OSError):
            backup_service.crear_backup()
    assert list(directory.iterdir()) == [path]


@pytest.mark.parametrize("failure", ["error", "timeout", "empty"])
@pytest.mark.parametrize("capture", [backup_service.crear_backup, backup_service.backup_programado])
def test_postgres_failures_do_not_delete_previous_files(monkeypatch, tmp_path, failure, capture):
    directory = _configure_file_backups(monkeypatch, tmp_path)
    old = _aged_backup(directory)
    monkeypatch.setattr(backup_service.settings, "DATABASE_URL", "postgresql://test:private-fake-password@localhost/test")
    monkeypatch.setattr(backup_service.settings, "BACKUP_AUTO_CLEANUP", True)

    def dump(cmd, **kwargs):
        assert "--no-password" in cmd
        assert "--lock-wait-timeout=5s" in cmd
        assert kwargs["timeout"] > 0
        assert not any("private-fake-password" in arg for arg in cmd)
        assert [row["filename"] for row in backup_service.listar_backups()] == [old.name]
        pending = Path(cmd[cmd.index("-f") + 1])
        assert stat.S_IMODE(pending.stat().st_mode) == 0o600
        if failure == "timeout":
            raise subprocess.TimeoutExpired(cmd, 1, stderr="private-fake-password")
        return subprocess.CompletedProcess(cmd, 1 if failure == "error" else 0, stderr="private-fake-password")

    with patch.object(backup_service.subprocess, "run", side_effect=dump):
        with pytest.raises(RuntimeError) as error:
            capture()
    assert "private-fake-password" not in str(error.value)
    assert list(directory.iterdir()) == [old]


def test_postgres_success_is_published_only_when_complete(monkeypatch, tmp_path):
    directory = _configure_file_backups(monkeypatch, tmp_path)
    directory.mkdir()
    monkeypatch.setattr(backup_service.settings, "DATABASE_URL", "postgresql://test:fake@localhost/test")

    def dump(cmd, **kwargs):
        pending = Path(cmd[cmd.index("-f") + 1])
        pending.write_text("CREATE TABLE products (id integer);\n", encoding="utf-8")
        assert backup_service.listar_backups() == []
        return subprocess.CompletedProcess(cmd, 0)

    with patch.object(backup_service.subprocess, "run", side_effect=dump):
        created = backup_service.crear_backup()
    assert created["db_type"] == "postgresql"
    assert Path(created["path"]).read_text().startswith("CREATE TABLE")
    assert len(backup_service.listar_backups()) == 1
    assert not list(directory.glob("*.pending"))


@pytest.mark.parametrize("verify_url", [
    "postgresql://test:fake@localhost/production_backup",
    "postgresql+psycopg2://test:fake@localhost:5432/production_backup",
    "postgresql://test:fake@other-host/occupied_test",
    "invalid-url",
    "",
])
def test_postgres_verification_never_executes_sql(client, auth_headers, monkeypatch, tmp_path, verify_url):
    directory = _configure_file_backups(monkeypatch, tmp_path)
    directory.mkdir()
    dump = directory / "jacaranda_test.sql"
    dump.write_text("CREATE TABLE products (id integer);\nCOPY products FROM stdin;\n", encoding="utf-8")
    monkeypatch.setattr(backup_service.settings, "BACKUP_VERIFY_DATABASE_URL", verify_url)
    monkeypatch.setattr(backup_service.settings, "DATABASE_URL", "postgresql://test:fake@localhost/production_backup")
    with patch.object(backup_service.subprocess, "run") as run:
        result = client.post("/api/v1/backup/verificar", json={"filename": dump.name}, headers=auth_headers)
    assert result.status_code == 200
    assert result.json()["ok"] is True
    assert result.json()["restored"] is False
    assert result.json()["restore_mode"] == "sql_inspection"
    assert "no se comprobo" in result.json()["warning"]
    run.assert_not_called()


def test_backup_candidates_exclude_links_directories_and_live_source(client, auth_headers, monkeypatch, tmp_path):
    source, directory = _configure_sqlite_backups(monkeypatch, tmp_path)
    directory.mkdir()
    moved = source.rename(directory / "jacaranda_live.db")
    monkeypatch.setattr(backup_service.settings, "DATABASE_URL", f"sqlite:///{moved}")
    external = tmp_path / "external.db"
    external.write_bytes(b"private external file")
    (directory / "jacaranda_link.db").symlink_to(external)
    (directory / "jacaranda_directory.db").mkdir()
    os.link(moved, directory / "jacaranda_hardlink.db")
    assert backup_service.listar_backups() == []
    for name in ["jacaranda_live.db", "jacaranda_link.db", "jacaranda_directory.db", "jacaranda_hardlink.db"]:
        result = client.post("/api/v1/backup/verificar", json={"filename": name}, headers=auth_headers)
        assert result.status_code == 400
    assert backup_service.limpiar_backups_antiguos() == 0
    assert moved.exists() and external.exists()


def test_verification_requires_admin(client, db, monkeypatch):
    from app.core.dependencies import get_current_user
    from app.models.usuario import RolUsuario, Usuario
    from main import app

    assert client.post("/api/v1/backup/verificar").status_code == 401
    app.dependency_overrides[get_current_user] = lambda: Usuario(rol=RolUsuario.CAJERO)
    try:
        with patch.object(backup_service, "verificar_restauracion_backup") as verify:
            assert client.post("/api/v1/backup/verificar").status_code == 403
        verify.assert_not_called()
    finally:
        app.dependency_overrides.pop(get_current_user, None)
