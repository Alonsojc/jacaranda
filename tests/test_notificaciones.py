"""Tests para el módulo de notificaciones WebSocket y alertas push."""

import pytest
from unittest.mock import AsyncMock, MagicMock

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

    def test_test_notificacion_admin(self, client, auth_headers):
        resp = client.post("/api/v1/notificaciones/test", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "conexiones_activas" in data
        assert "usuarios_conectados" in data

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
