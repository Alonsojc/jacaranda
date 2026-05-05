"""Tests para backup y restauración."""

import time
from unittest.mock import patch

from app.services import backup_service


def _configure_file_backups(monkeypatch, tmp_path, max_files=20):
    db_file = tmp_path / "jacaranda.db"
    db_file.write_bytes(b"sqlite backup source")
    backup_dir = tmp_path / "backups"
    monkeypatch.setattr(backup_service.settings, "DATABASE_URL", f"sqlite:///{db_file}", raising=False)
    monkeypatch.setattr(backup_service.settings, "BACKUP_DIR", str(backup_dir), raising=False)
    monkeypatch.setattr(backup_service.settings, "BACKUP_RETENTION_DAYS", 7, raising=False)
    monkeypatch.setattr(backup_service.settings, "BACKUP_MAX_FILES", max_files, raising=False)
    return backup_dir


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

        protected = client.delete(f"/api/v1/backup/{latest}", headers=auth_headers)
        removed = client.delete(f"/api/v1/backup/{old}", headers=auth_headers)
        items = client.get("/api/v1/backup/listar", headers=auth_headers).json()

        assert protected.status_code == 400
        assert protected.json()["detail"] == "No se puede borrar el backup más reciente"
        assert removed.status_code == 200
        assert [item["filename"] for item in items] == [latest]
        assert items[0]["is_latest"] is True

    def test_crear_backup_respeta_maximo_de_archivos(self, client, auth_headers, monkeypatch, tmp_path):
        _configure_file_backups(monkeypatch, tmp_path, max_files=2)

        for _ in range(4):
            resp = client.post("/api/v1/backup/crear", headers=auth_headers)
            assert resp.status_code == 200
            time.sleep(0.01)

        items = client.get("/api/v1/backup/listar", headers=auth_headers).json()
        estado = client.get("/api/v1/backup/estado", headers=auth_headers).json()

        assert len(items) == 2
        assert estado["max_backups"] == 2
