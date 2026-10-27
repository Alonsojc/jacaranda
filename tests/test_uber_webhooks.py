"""Synthetic, signed sandbox receipts; no real store or provider calls."""

import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.core.dependencies import get_current_user
from app.models.inventario import Producto
from app.models.uber_eats import UberSandboxAction, UberSandboxEvent, UberSandboxOrder
from app.models.usuario import Usuario, RolUsuario
from app.models.venta import Venta
from app.services import uber_webhook_service as inbox

STORE = "5d8714ab-07bc-4b7f-a0ee-5cbeb9c31594"
ORDER = "7871d55c-2460-484d-9f24-239416d1d2aa"
SECRET = "synthetic-webhook-secret-not-a-provider-key"
PATH = "/api/v1/uber-eats/sandbox/webhook"
REFERENCE_TIME = int(time.time())


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setattr(inbox, "time", SimpleNamespace(time=lambda: REFERENCE_TIME))
    monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_ENABLED", True)
    monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_WEBHOOK_ENABLED", True)
    monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_CLIENT_ID", "fictional-client")
    monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_CLIENT_SECRET", SecretStr(SECRET))
    monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_WEBHOOK_SECRET", SecretStr(""))
    monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_STORE_ID", STORE)


def event(**changes):
    payload = {
        "event_id": str(uuid4()), "event_type": "orders.notification",
        "event_time": REFERENCE_TIME * 1000,
        "meta": {"user_id": STORE, "resource_id": ORDER, "status": "pos"},
        "webhook_meta": {"client_id": "fictional-client"},
        "resource_href": "https://attacker.invalid/never-follow-this",
    }
    payload.update(changes)
    return payload


def signed(payload):
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    signature = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    return body, {"X-Uber-Signature": signature, "Content-Type": "application/json"}


def send(client, payload):
    body, headers = signed(payload)
    return client.post(PATH, content=body, headers=headers)


def test_receipt_is_durable_bounded_and_has_no_business_side_effects(client, db):
    product = Producto(codigo="UB-SYNTH", nombre="Fixture", precio_unitario=10, stock_actual=7)
    db.add(product)
    db.commit()
    payload = event(customer={"phone": "never-store-personal-data"}, token="never-store-token")
    with patch("httpx.Client") as network:
        response = send(client, payload)
        network.assert_not_called()
    assert response.status_code == 200
    assert response.content == b""
    db.expire_all()
    row = db.query(UberSandboxEvent).one()
    assert row.event_id == payload["event_id"] and row.order_id == ORDER
    assert row.estado == "recibido" and row.event_time == payload["event_time"] // 1000
    assert db.query(Venta).count() == 0
    assert db.get(Producto, product.id).stock_actual == 7
    assert "never-store" not in str(row.__dict__)
    assert "attacker.invalid" not in str(row.__dict__)


def test_replays_do_not_insert_twice_even_if_json_format_changes(client, db):
    payload = event()
    assert send(client, payload).status_code == 200
    assert send(client, json.dumps(payload, indent=4).encode()).status_code == 200
    assert db.query(UberSandboxEvent).count() == 1


@pytest.mark.parametrize("kind", ["orders.cancel", "orders.failure"])
@pytest.mark.parametrize("state", ["ACCEPTED", "SUCCEEDED"])
def test_signed_terminal_notice_stops_fulfillment_without_business_mutations(client, db, kind, state, monkeypatch):
    monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_ACTIONS_ENABLED", True)
    row = UberSandboxOrder(client_id="fictional-client", store_id=STORE, order_id=ORDER,
                           state=state, snapshot_json='{"carts":[]}', revision=4,
                           actualizado_en=datetime.now(timezone.utc))
    product = Producto(codigo="CANCEL-SYNTH", nombre="Fixture", precio_unitario=10, stock_actual=7)
    db.add_all([row, product])
    db.commit()
    payload = event(event_type=kind)
    with patch("httpx.Client") as network:
        assert send(client, payload).status_code == 200
        assert send(client, payload).status_code == 200
    network.assert_not_called()
    db.refresh(row)
    assert row.state == "FAILED" and row.revision == 5
    assert db.query(UberSandboxEvent).one().estado == "recibido"
    assert db.query(Venta).count() == 0 and db.get(Producto, product.id).stock_actual == 7


@pytest.mark.parametrize("pending_state", ["enviando", "incierta", "pendiente_aviso"])
def test_terminal_notice_reconciles_only_the_scoped_pending_cancel(client, db, pending_state, monkeypatch):
    monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_ACTIONS_ENABLED", True)
    key = str(uuid4())
    created = datetime.fromtimestamp(REFERENCE_TIME, timezone.utc) - timedelta(seconds=5)
    row = UberSandboxOrder(client_id="fictional-client", store_id=STORE, order_id=ORDER,
                           state="ACCEPTED", snapshot_json="{}", pending_request_key=key, actualizado_en=created)
    command = UberSandboxAction(client_id="fictional-client", store_id=STORE, order_id=ORDER,
                                request_key=key, action="cancelar", estado=pending_state,
                                fingerprint="1" * 64, creado_en=created)
    db.add_all([row, command])
    db.commit()
    payload = event(event_type="orders.cancel")
    body, headers = signed(payload)
    assert client.post(PATH, content=body, headers={**headers, "X-Uber-Signature": "0" * 64}).status_code == 401
    db.refresh(row)
    assert row.state == "ACCEPTED" and row.pending_request_key == key
    assert send(client, payload).status_code == 200
    db.refresh(row)
    db.refresh(command)
    assert row.state == "FAILED" and row.pending_request_key is None and command.estado == "conciliada"


def test_conflicting_event_identity_cannot_overwrite_receipt(client, db):
    payload = event()
    assert send(client, payload).status_code == 200
    payload["meta"]["resource_id"] = str(uuid4())
    assert send(client, payload).status_code == 409
    assert db.query(UberSandboxEvent).one().order_id == ORDER


@pytest.mark.parametrize("signature", [None, "", "0" * 64, "A" * 64, "sha256=" + "0" * 64, "wrong"])
def test_invalid_or_missing_signature_never_writes(client, db, signature):
    headers = {"X-Uber-Signature": signature} if signature is not None else {}
    assert client.post(PATH, json=event(), headers=headers).status_code == 401
    assert db.query(UberSandboxEvent).count() == 0


def test_modified_body_and_multiple_signatures_rejected(client, db):
    body, headers = signed(event())
    assert client.post(PATH, content=body + b" ", headers=headers).status_code == 401
    assert client.post(PATH, content=body, headers=[
        ("X-Uber-Signature", headers["X-Uber-Signature"]),
        ("X-Uber-Signature", headers["X-Uber-Signature"]),
    ]).status_code == 401
    assert db.query(UberSandboxEvent).count() == 0


def test_dedicated_signing_key_replaces_oauth_secret_for_signature_validation(client, db, monkeypatch):
    signing_key = "synthetic-dedicated-signing-key"
    monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_WEBHOOK_SECRET", SecretStr(signing_key))
    body, headers = signed(event())
    assert client.post(PATH, content=body, headers=headers).status_code == 401
    headers["X-Uber-Signature"] = hmac.new(signing_key.encode(), body, hashlib.sha256).hexdigest()
    monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_CLIENT_SECRET", SecretStr(""))
    assert client.post(PATH, content=body, headers=headers).status_code == 200
    assert db.query(UberSandboxEvent).count() == 1


@pytest.mark.parametrize("setting,value", [
    ("UBER_EATS_SANDBOX_ENABLED", False), ("UBER_EATS_SANDBOX_WEBHOOK_ENABLED", False),
    ("UBER_EATS_SANDBOX_CLIENT_SECRET", SecretStr("")),
    ("UBER_EATS_SANDBOX_CLIENT_ID", ""), ("UBER_EATS_SANDBOX_STORE_ID", "invalid-store"),
])
def test_disabled_or_incomplete_configuration_fails_closed(client, db, monkeypatch, setting, value):
    monkeypatch.setattr(settings, setting, value)
    assert send(client, event()).status_code == 503
    assert db.query(UberSandboxEvent).count() == 0


@pytest.mark.parametrize("payload", [
    event(meta={"user_id": str(uuid4()), "resource_id": ORDER}),
    event(webhook_meta={"client_id": "different-app"}),
])
def test_other_store_or_application_cannot_enter_inbox(client, db, payload):
    assert send(client, payload).status_code == 403
    assert db.query(UberSandboxEvent).count() == 0


@pytest.mark.parametrize("payload", [
    b"not-json", b"\xff", b"[]", b"null", b'{"event_id":"one","event_id":"two"}',
    b"[" * 1500, event(event_id="invalid"), event(event_type="unknown.event"),
    event(event_time=True), event(event_time="123"), event(event_time=1),
    event(event_time=REFERENCE_TIME + 600),
    event(meta={"user_id": STORE, "resource_id": "../../other"}),
    event(meta={"user_id": STORE}),
])
def test_malformed_or_stale_events_are_not_acknowledged(client, db, payload):
    assert send(client, payload).status_code == 400
    assert db.query(UberSandboxEvent).count() == 0


def test_body_limit_and_content_encoding(client, db):
    assert send(client, b" " * (inbox.MAX_BODY_BYTES + 1)).status_code == 413
    body, headers = signed(event())
    headers["Content-Encoding"] = "gzip"
    assert client.post(PATH, content=body, headers=headers).status_code == 415
    assert db.query(UberSandboxEvent).count() == 0


def test_chunked_body_limit_is_enforced(client, db):
    headers = {"X-Uber-Signature": "0" * 64}
    body = (b" " * 32768 for _ in range(3))
    assert client.post(PATH, content=body, headers=headers).status_code == 413
    assert db.query(UberSandboxEvent).count() == 0


def test_storage_failure_returns_retryable_error_not_ack(client, db):
    with patch.object(db, "commit", side_effect=OperationalError("SQL-secret", {}, Exception("secret"))):
        response = send(client, event())
    assert response.status_code == 503
    assert "secret" not in response.text


def test_known_replay_after_freshness_window_is_still_acknowledged(client, db, monkeypatch):
    payload = event()
    assert send(client, payload).status_code == 200
    now = int(time.time())
    monkeypatch.setattr(inbox.time, "time", lambda: now + 2 * 86400)
    assert send(client, payload).status_code == 200
    assert db.query(UberSandboxEvent).count() == 1


@pytest.mark.parametrize("kind", sorted(inbox.EVENT_TYPES))
def test_documented_order_notifications_are_preserved(client, db, kind):
    assert send(client, event(event_type=kind)).status_code == 200
    assert db.query(UberSandboxEvent).one().event_type == kind


def test_inbox_is_admin_only_paginated_and_scoped(client, db):
    from main import app
    assert client.get("/api/v1/uber-eats/sandbox/eventos").status_code == 401
    user = Usuario(rol=RolUsuario.CAJERO)
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        assert client.get("/api/v1/uber-eats/sandbox/eventos").status_code == 403
        user.rol = RolUsuario.ADMINISTRADOR
        for _ in range(3):
            assert send(client, event()).status_code == 200
        response = client.get("/api/v1/uber-eats/sandbox/eventos?limit=2")
        assert response.status_code == 200
        assert response.json()["aceptacion_automatica"] is False
        events = response.json()["eventos"]
        assert len(events) == 2 and events[0]["id"] > events[1]["id"]
        older = client.get(f'/api/v1/uber-eats/sandbox/eventos?before_id={events[-1]["id"]}')
        assert len(older.json()["eventos"]) == 1
        assert SECRET not in response.text and "fingerprint" not in response.text
        assert client.get("/api/v1/uber-eats/sandbox/eventos?limit=101").status_code == 422
        db.query(UberSandboxEvent).update({"store_id": str(uuid4())})
        db.commit()
        assert client.get("/api/v1/uber-eats/sandbox/eventos").json()["eventos"] == []
    finally:
        app.dependency_overrides.pop(get_current_user, None)
