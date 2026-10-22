"""Tests para backup y restauración."""

import hashlib
import importlib
import os
import sqlite3
import stat
import subprocess
import sys
import time
from types import SimpleNamespace
from urllib.parse import urlparse
from pathlib import Path
from unittest.mock import patch

import pytest
from psycopg2.extensions import parse_dsn
from sqlalchemy.dialects.postgresql.psycopg2 import PGDialect_psycopg2
from sqlalchemy.engine import make_url

from app.services import backup_service


def test_download_audit_failure_removes_private_temporary_copy(client, auth_headers, monkeypatch, tmp_path):
    _, directory = _configure_sqlite_backups(monkeypatch, tmp_path)
    backup = backup_service.crear_backup()
    with patch("app.api.routes.backup.registrar_evento", side_effect=RuntimeError("Audit unavailable")):
        response = client.get("/api/v1/backup/descargar", headers=auth_headers)
    assert response.status_code == 500
    assert list(directory.glob(".download_*")) == []
    assert Path(backup["path"]).is_file()


def test_download_cleanup_also_runs_when_streaming_fails(tmp_path):
    import asyncio
    from app.api.file_responses import PrivateDownloadResponse

    copied = tmp_path / ".download_test"
    copied.write_bytes(b"synthetic-database")

    async def fail_send(_message):
        raise RuntimeError("Disconnected")

    async def receive():
        return {"type": "http.disconnect"}

    with pytest.raises(RuntimeError, match="Disconnected"):
        asyncio.run(PrivateDownloadResponse(copied)(
            {"type": "http", "method": "GET", "headers": [], "asgi": {"spec_version": "2.3"}},
            receive, fail_send,
        ))
    assert not copied.exists()


def test_capture_and_download_refuse_insufficient_space_without_deleting(monkeypatch, tmp_path):
    _, directory = _configure_sqlite_backups(monkeypatch, tmp_path)
    backup = backup_service.crear_backup()
    with patch.object(backup_service.shutil, "disk_usage", return_value=SimpleNamespace(free=0)):
        with pytest.raises(RuntimeError, match="Espacio insuficiente"):
            backup_service.crear_backup()
        with pytest.raises(RuntimeError, match="Espacio insuficiente"):
            backup_service.preparar_descarga_backup()
    assert list(directory.glob(".pending")) == []
    assert list(directory.glob(".download_*")) == []
    assert Path(backup["path"]).is_file()


def test_default_capture_limit_preserves_every_existing_recovery_point(monkeypatch, tmp_path):
    _configure_file_backups(monkeypatch, tmp_path, max_files=1)
    backup = backup_service.crear_backup()
    with pytest.raises(RuntimeError, match="Limite de respaldos"):
        backup_service.crear_backup()
    assert [item["filename"] for item in backup_service.listar_backups()] == [backup["filename"]]


def test_postgres_connection_preserves_encoding_and_tls_policy():
    parsed = urlparse("postgresql://test%40user:fictional%3Apass%2Bword@localhost:5433/test%20db?sslmode=verify-full&sslrootcert=%2Ftmp%2Ftest-ca.pem&connect_timeout=8")
    args = backup_service._postgres_cmd_base(parsed)
    env = backup_service._postgres_env(parsed)
    options = parse_dsn(args[1])
    _args, runtime = PGDialect_psycopg2().create_connect_args(make_url(parsed.geturl()))
    assert options == {key: str(value) for key, value in runtime.items() if key != "password"}
    assert options["dbname"] == "test%20db"
    assert env["PGPASSWORD"] == "fictional:pass+word"
    assert options["sslmode"] == "verify-full" and options["sslrootcert"] == "/tmp/test-ca.pem"
    assert options["connect_timeout"] == "8"
    assert env["PGPASSWORD"] not in str(args)
    with pytest.raises(RuntimeError, match="repetidos"):
        backup_service._postgres_env(urlparse("postgresql://localhost/test?sslmode=require&sslmode=disable"))


@pytest.mark.parametrize("database", ["test%20db", "dbname%3Ddifferent%20sslmode%3Ddisable", "contains=literal", "has'quote"])
def test_postgres_database_name_is_literal_and_matches_runtime(database):
    parsed = urlparse("postgresql://test:synthetic@localhost/" + database + "?sslmode=require")
    options = parse_dsn(backup_service._postgres_cmd_base(parsed)[1])
    assert options["dbname"] == make_url(parsed.geturl()).database
    assert options["sslmode"] == "require"


def test_download_can_select_exact_capture_and_matches_checksum(client, auth_headers, monkeypatch, tmp_path):
    _configure_sqlite_backups(monkeypatch, tmp_path)
    first = backup_service.crear_backup()
    backup_service.crear_backup()
    response = client.get("/api/v1/backup/descargar", params={"filename": first["filename"]}, headers=auth_headers)
    assert response.status_code == 200 and first["filename"] in response.headers["content-disposition"]
    assert hashlib.sha256(response.content).hexdigest() == first["sha256"]
    assert client.get("/api/v1/backup/descargar?filename=../file.db", headers=auth_headers).status_code == 400


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
    monkeypatch.setattr(backup_service.settings, "BACKUP_MAX_FILES", 4)
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
    monkeypatch.setattr(backup_service.settings, "BACKUP_TIMEOUT_SECONDS", 1)
    original_popen = subprocess.Popen

    def dump(cmd, **kwargs):
        assert "--no-password" in cmd
        assert "--lock-wait-timeout=5s" in cmd
        assert not any("private-fake-password" in arg for arg in cmd)
        assert [row["filename"] for row in backup_service.listar_backups()] == [old.name]
        pending = next(directory.glob("*.pending"))
        assert stat.S_IMODE(pending.stat().st_mode) == 0o600
        code = {"error": "import sys;sys.exit(1)", "empty": "pass", "timeout": "import time;time.sleep(10)"}[failure]
        return original_popen([sys.executable, "-c", code], **kwargs)

    with patch.object(backup_service.subprocess, "Popen", side_effect=dump):
        with pytest.raises(RuntimeError) as error:
            capture()
    assert "private-fake-password" not in str(error.value)
    assert list(directory.iterdir()) == [old]


def test_postgres_success_is_published_only_when_complete(monkeypatch, tmp_path):
    directory = _configure_file_backups(monkeypatch, tmp_path)
    directory.mkdir()
    monkeypatch.setattr(backup_service.settings, "DATABASE_URL", "postgresql://test:fake@localhost/test")
    original_popen = subprocess.Popen

    def dump(cmd, **kwargs):
        assert backup_service.listar_backups() == []
        return original_popen([sys.executable, "-c", "print('CREATE TABLE products (id integer);')"], **kwargs)

    with patch.object(backup_service.subprocess, "Popen", side_effect=dump):
        created = backup_service.crear_backup()
    assert created["db_type"] == "postgresql"
    assert Path(created["path"]).read_text().startswith("CREATE TABLE")
    assert len(backup_service.listar_backups()) == 1
    assert not list(directory.glob("*.pending"))


def test_postgres_stream_stops_before_free_space_reserve(monkeypatch, tmp_path):
    directory = _configure_file_backups(monkeypatch, tmp_path)
    old = _aged_backup(directory)
    initial_size = old.stat().st_size
    monkeypatch.setattr(backup_service.settings, "DATABASE_URL", "postgresql://test:fake@localhost/test")
    monkeypatch.setattr(backup_service.settings, "BACKUP_MIN_FREE_BYTES", 64 * 1024 * 1024)
    original_popen = subprocess.Popen
    processes = []

    def dump(cmd, **kwargs):
        process = original_popen([sys.executable, "-c", "import sys;sys.stdout.buffer.write(b'x'*(2*1024*1024))"], **kwargs)
        processes.append(process)
        return process

    def remaining(_path):
        used = sum(path.stat().st_size for path in directory.iterdir()) - initial_size
        return SimpleNamespace(free=65 * 1024 * 1024 - used)

    with patch.object(backup_service.subprocess, "Popen", side_effect=dump), \
            patch.object(backup_service.shutil, "disk_usage", side_effect=remaining):
        with pytest.raises(RuntimeError, match="reserva"):
            backup_service.crear_backup()
    assert list(directory.iterdir()) == [old]
    assert all(process.poll() is not None for process in processes)


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


def test_sqlite_uri_excludes_the_real_source(monkeypatch, tmp_path):
    from sqlalchemy import create_engine, text

    source, directory = _configure_sqlite_backups(monkeypatch, tmp_path)
    directory.mkdir()
    source = source.rename(directory / "jacaranda_live #.db")
    uri = f"sqlite:///{source.as_uri()}?mode=rw&uri=true"
    engine = create_engine(uri)
    try:
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM productos")).scalar() == 1
    finally:
        engine.dispose()
    monkeypatch.setattr(backup_service.settings, "DATABASE_URL", uri)
    assert backup_service._sqlite_source().samefile(source)
    assert backup_service.listar_backups() == []
    backup_service.crear_backup()
    with pytest.raises(FileNotFoundError):
        backup_service.eliminar_backup(source.name)
    assert source.exists()


def test_default_sqlite_destination_stays_next_to_source(monkeypatch, tmp_path):
    source, _directory = _configure_sqlite_backups(monkeypatch, tmp_path)
    persistent = tmp_path / "persistent-volume"
    persistent.mkdir()
    source = source.rename(persistent / source.name)
    monkeypatch.setattr(backup_service.settings, "DATABASE_URL", f"sqlite:///{source}")
    monkeypatch.setattr(backup_service.settings, "BACKUP_DIR", "")
    assert backup_service._backup_dir() == persistent / "backups"
    assert Path(backup_service.crear_backup()["path"]).parent == persistent / "backups"


@pytest.mark.parametrize("endpoint,module", [
    ("/api/v1/reportes/backup", "app.api.routes.reportes"),
    ("/api/v1/backup/descargar", "app.api.routes.backup"),
])
def test_download_survives_retention_before_stream_opens(client, auth_headers, monkeypatch, tmp_path, endpoint, module):
    _configure_sqlite_backups(monkeypatch, tmp_path)
    monkeypatch.setattr(backup_service.settings, "BACKUP_AUTO_CLEANUP", True)
    monkeypatch.setattr(backup_service.settings, "BACKUP_MAX_FILES", 1)
    backup_service.crear_backup()
    routes = importlib.import_module(module)
    original_response = routes.PrivateDownloadResponse

    def before_stream(*args, **kwargs):
        backup_service.crear_backup()
        return original_response(*args, **kwargs)

    monkeypatch.setattr(routes, "PrivateDownloadResponse", before_stream)
    response = client.get(endpoint, headers=auth_headers)
    assert response.status_code == 200
    assert response.content.startswith(b"SQLite format 3")
    assert response.headers["cache-control"] == "no-store"
    assert len(backup_service.listar_backups()) == 1
    assert not list(backup_service._backup_dir().glob(".download_*"))


@pytest.mark.parametrize("module", ["app.api.routes.reportes", "app.api.routes.backup"])
def test_all_backup_routes_cleanup_after_response_creation_failure(client, auth_headers, monkeypatch, tmp_path, module):
    _, directory = _configure_sqlite_backups(monkeypatch, tmp_path)
    backup_service.crear_backup()
    routes = importlib.import_module(module)
    monkeypatch.setattr(routes, "PrivateDownloadResponse", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("response failure")))
    endpoint = "/api/v1/reportes/backup" if module.endswith("reportes") else "/api/v1/backup/descargar"
    try:
        response = client.get(endpoint, headers=auth_headers)
        assert response.status_code == 500
    except RuntimeError as exc:
        assert str(exc) == "response failure"
    assert list(directory.glob(".download_*")) == []
