"""Tests para backup y restauración."""

from unittest.mock import patch


class TestBackup:

    def test_crear_backup_in_memory_returns_error(self, client, auth_headers):
        """In-memory SQLite can't be backed up - expect 500."""
        with patch("app.services.backup_service.settings") as mock_settings:
            mock_settings.DATABASE_URL = "sqlite://"
            resp = client.post("/api/v1/backup/crear", headers=auth_headers)
        # In-memory SQLite has no file, so backup fails with 500
        assert resp.status_code == 500

    def test_descargar_backup_in_memory_returns_error(self, client, auth_headers):
        """In-memory SQLite can't be downloaded."""
        with patch("app.services.backup_service.settings") as mock_settings:
            mock_settings.DATABASE_URL = "sqlite://"
            resp = client.get("/api/v1/backup/descargar", headers=auth_headers)
        assert resp.status_code == 500

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
