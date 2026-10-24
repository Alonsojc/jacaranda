"""Private standalone order management never reaches a POS or a live Uber host."""

import hashlib
import hmac
import json
import time
from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import inspect

from app import uber_sandbox_runtime as runtime
from app.core.config import settings
from app.models.uber_eats import UberSandboxAction, UberSandboxEvent, UberSandboxOrder
from app.services import uber_eats_service as api
from app.services import uber_order_service as orders
from tests.test_uber_sandbox_runtime import SECRET, isolated  # noqa: F401


PRIVATE = "synthetic-private-sandbox-management-credential-0123456789"
AUTH = {"Authorization": "Bearer " + PRIVATE}


@pytest.fixture
def management(isolated, monkeypatch):
    monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_MANAGEMENT_ENABLED", True)
    monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_ACTIONS_ENABLED", True)
    monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_ADMIN_TOKEN", SecretStr(PRIVATE))
    monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_CLIENT_SECRET", SecretStr("synthetic-OAuth-secret"))
    monkeypatch.setattr(api, "_order_token_cache", None)
    monkeypatch.setattr(api, "_token_cache", None)
    return isolated


def receipt(client):
    event = {
        "event_id": str(uuid4()), "event_type": "orders.notification", "event_time": int(time.time()) * 1000,
        "meta": {"user_id": runtime.TEST_STORE_ID, "resource_id": str(uuid4())},
        "webhook_meta": {"client_id": runtime.TEST_APPLICATION_ID},
    }
    raw = json.dumps(event).encode()
    signature = hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    assert client.post(runtime.WEBHOOK_PATH, content=raw, headers={"X-Uber-Signature": signature}).status_code == 200
    return event


def test_management_requires_its_own_credential_and_no_pos_identity(management):
    engine, _ = management
    with TestClient(runtime.app) as client:
        response = client.get("/")
        assert response.status_code == 200 and "Jacaranda Sandbox" in response.text
        assert response.headers["cache-control"] == "no-store"
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
        assert client.get("/sandbox/estado").status_code == 401
        assert client.get("/sandbox/estado", headers={"Authorization": "Bearer " + SECRET}).status_code == 401
        assert client.get("/sandbox/estado?token=" + PRIVATE).status_code == 401
        assert client.get("/sandbox/estado", headers=AUTH).json()["tienda_real_activada"] is False
        assert client.get("/api/v1/uber-eats/sandbox/eventos").status_code == 401
        for path in ("/api/v1/auth/login", "/api/v1/punto-de-venta/ventas", "/api/v1/clientes", "/api/v1/uber-eats/preparacion"):
            assert client.get(path, headers=AUTH).status_code == 404
        assert client.get("/sandbox.js").status_code == 200
        assert client.get("/sandbox.css").status_code == 200
        assert client.get("/favicon.svg").status_code == 200
        assert runtime.favicon().path == runtime.ASSETS / "favicon.svg"
    assert set(inspect(engine).get_table_names()) == {model.__tablename__ for model in runtime.MODELS}


@pytest.mark.parametrize("change", ["short", "missing_oauth", "shared_webhook", "live_api", "live_auth", "live_store"])
def test_management_refuses_unsafe_configuration_before_database_connect(management, monkeypatch, change):
    if change == "short":
        monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_ADMIN_TOKEN", SecretStr("short"))
    elif change == "missing_oauth":
        monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_CLIENT_SECRET", SecretStr(""))
    elif change == "shared_webhook":
        monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_WEBHOOK_SECRET", SecretStr(PRIVATE))
    elif change == "live_api":
        monkeypatch.setattr(api, "API_URL", "https://api.uber.com")
    elif change == "live_auth":
        monkeypatch.setattr(api, "TOKEN_URL", "https://auth.uber.com/oauth/v2/token")
    else:
        monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_STORE_ID", "d757be8e-a500-5e80-a148-8e7182329641")
    with patch.object(runtime.engine, "begin") as connect, pytest.raises(RuntimeError):
        with TestClient(runtime.app):
            pass
    connect.assert_not_called()


@pytest.mark.parametrize("action,expected", [("aceptar", "ACCEPTED"), ("rechazar", "FAILED"), ("cancelar", "FAILED")])
def test_complete_signed_receipt_details_action_and_replay_use_sandbox_only(management, action, expected):
    engine, sessions = management
    calls = []
    original = httpx.Client
    state = "ACCEPTED" if action == "cancelar" else "OFFERED"
    order_id = None

    def serve(request):
        nonlocal state
        calls.append((request.method, request.url.host, request.url.path))
        if request.url.host == "sandbox-login.uber.com":
            return httpx.Response(200, json={"access_token": "synthetic-token", "expires_in": 3600})
        assert request.url.host == "test-api.uber.com"
        assert request.url.path.startswith("/v1/delivery/order/" + order_id)
        if request.method == "POST":
            state = expected
            return httpx.Response(204 if action == "cancelar" else 200)
        return httpx.Response(200, json={"order": {
            "id": order_id, "display_id": "SANDBOX", "state": state, "store": {"id": runtime.TEST_STORE_ID},
            "store_instructions": "Prueba: alergia a nueces",
            "carts": [{"items": [{"id": "test-item", "title": "Brownie de prueba", "quantity": {"amount": 1},
                                    "special_instructions": "Sin nueces", "allergy": "nueces"}]}],
            "customers": [{"phone": "do-not-retain"}],
        }})

    with TestClient(runtime.app) as client:
        event = receipt(client)
        order_id = event["meta"]["resource_id"]
        rows = client.get("/api/v1/uber-eats/sandbox/eventos", headers=AUTH).json()["eventos"]
        assert len(rows) == 1 and rows[0]["event_id"] == event["event_id"]
        with patch.object(httpx, "Client", side_effect=lambda **kwargs: original(transport=httpx.MockTransport(serve), **kwargs)):
            path = f"/api/v1/uber-eats/sandbox/eventos/{event['event_id']}/consultar"
            response = client.post(path, headers=AUTH, json={})
            assert response.status_code == 200, response.text
            details = response.json()
            assert details["acciones_habilitadas"] and "Prueba: alergia a nueces" in response.text
            assert "do-not-retain" not in response.text
            command = {"request_key": str(uuid4()), "accion": action,
                       "motivo": None if action == "aceptar" else "TECHNICAL_FAILURE",
                       "instrucciones_revisadas": True, "detalle_sha256": details["detalle_sha256"]}
            target = f"/api/v1/uber-eats/sandbox/pedidos/{order_id}/accion"
            assert client.post(target, json=command).status_code == 401
            assert client.post(target, json=command, headers=AUTH).status_code == 200
            repeat = client.post(target, json=command, headers=AUTH)
            assert repeat.status_code == 200 and repeat.json()["repetida"]
            assert client.post(path, headers=AUTH, json={}).json()["pedido"]["state"] == expected
    assert len([call for call in calls if call[0] == "POST" and call[1] == "test-api.uber.com"]) == 1
    with sessions() as db:
        assert db.query(UberSandboxEvent).count() == 1
        assert db.query(UberSandboxOrder).one().state == expected
        assert db.query(UberSandboxAction).one().estado == "confirmada"
    assert set(inspect(engine).get_table_names()) == {model.__tablename__ for model in runtime.MODELS}


def test_management_disabled_cannot_be_opened_with_a_token(isolated):
    with TestClient(runtime.app) as client:
        for path in ("/", "/sandbox.js", "/sandbox/estado", "/api/v1/uber-eats/sandbox/eventos"):
            assert client.get(path, headers=AUTH).status_code == 404


def test_order_client_rejects_live_hosts_without_a_network_call(monkeypatch):
    monkeypatch.setattr(api, "API_URL", "https://api.uber.com")
    with patch("httpx.Client") as network, pytest.raises(orders.SandboxRequestError):
        orders._request("POST", str(uuid4()), {}, "aceptar")
    network.assert_not_called()
