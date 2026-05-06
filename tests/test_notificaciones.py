"""Tests para el módulo de notificaciones WebSocket y alertas push."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.models.notificacion import FCMToken
from app.services.notificacion_service import ConnectionManager


class TestNotificaciones:
    """Tests del sistema de notificaciones."""

    def test_alertas_push_endpoint(self, client, auth_headers):
        resp = client.get("/api/v1/notificaciones/alertas-push", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "alertas" in data
        assert "push_config" in data
        assert "vapid_public_key" in data["push_config"]

    def test_fcm_config_default_disabled(self, client, auth_headers):
        resp = client.get("/api/v1/notificaciones/fcm-config", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is False
        assert data["provider"] == "local"

    def test_registrar_y_revocar_fcm_token(self, client, auth_headers, db, admin_user):
        token = "fcm-token-" + ("x" * 80)

        resp = client.post(
            "/api/v1/notificaciones/fcm-token",
            json={"token": token, "plataforma": "pytest"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["activo"] is True

        stored = db.query(FCMToken).filter(FCMToken.token == token).one()
        assert stored.usuario_id == admin_user.id
        assert stored.activo is True
        assert stored.plataforma == "pytest"

        resp = client.post(
            "/api/v1/notificaciones/fcm-token/revocar",
            json={"token": token},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["revocado"] is True
        db.refresh(stored)
        assert stored.activo is False

    def test_enviar_fcm_sin_credenciales_no_falla(self, monkeypatch):
        from app.core.config import settings
        from app.services.notificacion_service import enviar_fcm_pedido_nuevo

        monkeypatch.setattr(settings, "FIREBASE_SERVICE_ACCOUNT_JSON", "")
        monkeypatch.setattr(settings, "FIREBASE_SERVICE_ACCOUNT_FILE", "")

        result = enviar_fcm_pedido_nuevo({"folio": "P-1", "cliente": "Test"})
        assert result["enabled"] is False

    def test_fcm_status(self, client, auth_headers):
        resp = client.get("/api/v1/notificaciones/fcm-status", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "tokens_activos_usuario" in data
        assert "server_enabled" in data

    def test_fcm_test_sin_credenciales_no_falla(self, client, auth_headers, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "FIREBASE_SERVICE_ACCOUNT_JSON", "")
        monkeypatch.setattr(settings, "FIREBASE_SERVICE_ACCOUNT_FILE", "")

        resp = client.post("/api/v1/notificaciones/fcm-test", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

    def test_enviar_multicast_usa_app_inicializada(self, monkeypatch):
        from app.services import notificacion_service

        app = object()
        calls = {}

        class FakeMessaging:
            @staticmethod
            def send_each_for_multicast(message, app=None):
                calls["message"] = message
                calls["app"] = app
                return "ok"

        monkeypatch.setattr(notificacion_service, "_firebase_app", app)

        result = notificacion_service._enviar_multicast(FakeMessaging, "mensaje")

        assert result == "ok"
        assert calls["message"] == "mensaje"
        assert calls["app"] is app

    def test_test_notificacion_admin(self, client, auth_headers):
        resp = client.post("/api/v1/notificaciones/test", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "conexiones_activas" in data
        assert "usuarios_conectados" in data
        assert "fcm" in data

    def test_websocket_sin_token(self, client):
        from starlette.websockets import WebSocketDisconnect
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/api/v1/notificaciones/ws") as ws:
                pass

    def test_websocket_con_token_invalido(self, client):
        from starlette.websockets import WebSocketDisconnect
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/api/v1/notificaciones/ws?token=invalid") as ws:
                pass


class TestConnectionManager:
    """Unit tests del ConnectionManager."""

    def test_manager_init(self):
        mgr = ConnectionManager()
        assert mgr.active_connections == {}

    @pytest.mark.asyncio
    async def test_connect_disconnect(self):
        mgr = ConnectionManager()
        ws = AsyncMock()
        await mgr.connect(1, ws)
        assert 1 in mgr.active_connections
        assert ws in mgr.active_connections[1]
        ws.accept.assert_called_once()

        mgr.disconnect(1, ws)
        assert 1 not in mgr.active_connections

    @pytest.mark.asyncio
    async def test_send_to_user(self):
        mgr = ConnectionManager()
        ws = AsyncMock()
        await mgr.connect(1, ws)

        await mgr.send_to_user(1, {"tipo": "test"})
        ws.send_json.assert_called_with({"tipo": "test"})

    @pytest.mark.asyncio
    async def test_send_to_nonexistent_user(self):
        mgr = ConnectionManager()
        # Should not raise
        await mgr.send_to_user(999, {"tipo": "test"})

    @pytest.mark.asyncio
    async def test_broadcast(self):
        mgr = ConnectionManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        await mgr.connect(1, ws1)
        await mgr.connect(2, ws2)

        await mgr.broadcast({"tipo": "global"})
        ws1.send_json.assert_called_with({"tipo": "global"})
        ws2.send_json.assert_called_with({"tipo": "global"})

    @pytest.mark.asyncio
    async def test_broadcast_removes_stale_connections(self):
        mgr = ConnectionManager()
        ws_good = AsyncMock()
        ws_stale = AsyncMock()
        ws_stale.send_json.side_effect = Exception("connection lost")

        await mgr.connect(1, ws_good)
        await mgr.connect(2, ws_stale)

        await mgr.broadcast({"tipo": "test"})
        # Stale connection should be removed
        assert 2 not in mgr.active_connections
        # Good connection still there
        assert 1 in mgr.active_connections
