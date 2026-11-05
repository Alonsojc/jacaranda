"""Sandbox push never depends on a live store, a live key, or browser polling."""

import base64
import hashlib
import hmac
import json
import time
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
import requests
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import inspect

from app import uber_sandbox_runtime as runtime
from app.core.config import settings
from app.models.uber_eats import UberSandboxEvent
from app.models.uber_sandbox_push import SandboxPushDelivery, SandboxPushSubscription
from app.services import uber_sandbox_push as push
from tests.test_uber_sandbox_management import AUTH, PRIVATE, management  # noqa: F401
from tests.test_uber_sandbox_runtime import SECRET, isolated  # noqa: F401


def b64(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


@pytest.fixture
def enabled(management, monkeypatch):
    private = ec.generate_private_key(ec.SECP256R1())
    scalar = private.private_numbers().private_value.to_bytes(32, "big")
    monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_PUSH_ENABLED", True)
    monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_PUSH_VAPID_PRIVATE_KEY", SecretStr(b64(scalar)))
    monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_PUSH_STORAGE_KEY", SecretStr(Fernet.generate_key().decode()))
    # The worker is exercised explicitly below, against this isolated session.
    monkeypatch.setattr(runtime, "push_tick", lambda: None)
    return management


def subscription(endpoint="https://web.push.apple.com/QK5-fictitious-token"):
    public = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint,
    )
    return {"endpoint": endpoint, "keys": {"p256dh": b64(public), "auth": b64(b"synthetic-auth!!")}, "expirationTime": None}


def signed_receipt(client, kind="orders.notification", order_id=None):
    event = {"event_id": str(uuid4()), "event_type": kind, "event_time": int(time.time()),
             "meta": {"user_id": runtime.TEST_STORE_ID, "resource_id": order_id or str(uuid4())},
             "webhook_meta": {"client_id": runtime.TEST_APPLICATION_ID}}
    body = json.dumps(event).encode()
    signature = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    assert client.post(runtime.WEBHOOK_PATH, content=body, headers={"X-Uber-Signature": signature}).status_code == 200
    return event, body, signature


def test_feature_is_off_by_default_and_no_push_tables_are_created(management):
    engine, _ = management
    with TestClient(runtime.app) as client:
        assert client.get("/api/v1/uber-eats/sandbox/push/config").status_code == 401
        assert client.get("/api/v1/uber-eats/sandbox/push/config", headers=AUTH).status_code == 404
        assert client.get("/sandbox/estado", headers=AUTH).json()["push_habilitado"] is False
    assert not {m.__tablename__ for m in runtime.PUSH_MODELS} & set(inspect(engine).get_table_names())


@pytest.mark.parametrize("invalid", ["missing", "short", "shared"])
def test_bad_or_shared_keys_fail_before_connecting(enabled, monkeypatch, invalid):
    if invalid == "missing":
        monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_PUSH_STORAGE_KEY", SecretStr(""))
    elif invalid == "short":
        monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_PUSH_VAPID_PRIVATE_KEY", SecretStr("too-short"))
    else:
        monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_ADMIN_TOKEN", settings.UBER_EATS_SANDBOX_PUSH_STORAGE_KEY)
    with patch.object(runtime.engine, "begin") as connection, pytest.raises(RuntimeError):
        with TestClient(runtime.app):
            pass
    connection.assert_not_called()


def test_guarded_subscription_encrypts_and_deactivates_device(enabled):
    engine, sessions = enabled
    data = subscription()
    with TestClient(runtime.app) as client:
        config = client.get("/api/v1/uber-eats/sandbox/push/config", headers=AUTH).json()
        assert config["entorno"] == "sandbox" and len(config["clave_publica"]) == 87
        url = "/api/v1/uber-eats/sandbox/push/subscription"
        assert client.post(url, json=data).status_code == 401
        assert client.post(url, json=data, headers=AUTH).json()["activa"] is True
        assert client.post(url, json=data, headers=AUTH).status_code == 200
        status = client.post("/api/v1/uber-eats/sandbox/push/status", json={"endpoint": data["endpoint"]}, headers=AUTH)
        assert status.json() == {"entorno": "sandbox", "activa": True, "ultimo_envio": None}
        with sessions() as db:
            row = db.query(SandboxPushSubscription).one()
            assert data["endpoint"] not in row.subscription_encrypted
            assert data["keys"]["auth"] not in row.subscription_encrypted
            assert row.endpoint_hash == hashlib.sha256(data["endpoint"].encode()).hexdigest()
        assert client.post("/api/v1/uber-eats/sandbox/push/unsubscribe", json={"endpoint": data["endpoint"]}, headers=AUTH).status_code == 200
        with sessions() as db:
            row = db.query(SandboxPushSubscription).one()
            assert not row.active and row.subscription_encrypted == ""
    assert {m.__tablename__ for m in runtime.PUSH_MODELS}.issubset(inspect(engine).get_table_names())


@pytest.mark.parametrize("endpoint", [
    "http://web.push.apple.com/id", "https://web.push.apple.com.evil.test/id",
    "https://user@web.push.apple.com/id", "https://web.push.apple.com:8443/id",
    "https://127.0.0.1/id", "https://169.254.169.254/latest/meta-data", "https://fcm.googleapis.com/",
    "https://web.push.apple.com/id#fragment", "https://web.push.apple.com/id\n?bad=yes",
])
def test_subscription_rejects_untrusted_destinations(enabled, endpoint):
    with TestClient(runtime.app) as client:
        assert client.post("/api/v1/uber-eats/sandbox/push/subscription", json=subscription(endpoint), headers=AUTH).status_code == 422


def test_invalid_subscription_key_and_extra_fields_are_rejected(enabled):
    data = subscription()
    data["keys"]["p256dh"] = "invalid"
    with TestClient(runtime.app) as client:
        url = "/api/v1/uber-eats/sandbox/push/subscription"
        assert client.post(url, json=data, headers=AUTH).status_code == 422
        data = subscription()
        data["user_id"] = "unexpected"
        assert client.post(url, json=data, headers=AUTH).status_code == 422


def test_verified_event_queued_once_without_browser_and_sent_generic_payload(enabled, monkeypatch):
    _, sessions = enabled
    deliveries = []
    monkeypatch.setattr(push, "_send", lambda sub, event_id, event_type, ttl: deliveries.append((sub, event_id, event_type)) or 201)
    with TestClient(runtime.app) as client:
        data = subscription()
        client.post("/api/v1/uber-eats/sandbox/push/subscription", json=data, headers=AUTH)
        event, raw, signature = signed_receipt(client)
        assert client.post(runtime.WEBHOOK_PATH, content=raw, headers={"X-Uber-Signature": signature}).status_code == 200
        with sessions() as db:
            assert push.enqueue(db) == 1
            assert push.enqueue(db) == 0
            assert push.deliver_one(db)
            assert not push.deliver_one(db)
            assert db.query(SandboxPushDelivery).one().state == "sent"
            assert db.query(UberSandboxEvent).count() == 1
        assert len(deliveries) == 1 and deliveries[0][1:] == (event["event_id"], "orders.notification")
        state = client.post("/api/v1/uber-eats/sandbox/push/status", json={"endpoint": data["endpoint"]}, headers=AUTH).json()
        assert state["ultimo_envio"] == "sent"  # accepted by the push service, not proof of device delivery


def test_no_backfill_and_no_delivery_for_expired_or_deactivated_subscription(enabled, monkeypatch):
    _, sessions = enabled
    send = []
    monkeypatch.setattr(push, "_send", lambda *args: send.append(True) or 201)
    with TestClient(runtime.app) as client:
        signed_receipt(client)
        data = subscription()
        client.post("/api/v1/uber-eats/sandbox/push/subscription", json=data, headers=AUTH)
        with sessions() as db:
            assert push.enqueue(db) == 0
        signed_receipt(client)
        with sessions() as db:
            assert push.enqueue(db) == 1
            push.unsubscribe(db, data["endpoint"])
            assert push.deliver_one(db)
            assert db.query(SandboxPushDelivery).one().state == "expired"
        assert not send


def test_temporary_failure_retries_same_delivery_and_invalid_device_is_removed(enabled, monkeypatch):
    _, sessions = enabled
    calls = []

    def send(*args):
        calls.append(args[1])
        if len(calls) == 1:
            raise requests.Timeout()
        return 410

    monkeypatch.setattr(push, "_send", send)
    with TestClient(runtime.app) as client:
        data = subscription()
        client.post("/api/v1/uber-eats/sandbox/push/subscription", json=data, headers=AUTH)
        signed_receipt(client)
        with sessions() as db:
            push.enqueue(db)
            assert push.deliver_one(db)
            job = db.query(SandboxPushDelivery).one()
            assert job.state == "pending" and job.attempts == 1
            job.next_attempt_at = push._now() - timedelta(seconds=1)
            db.commit()
            assert push.deliver_one(db)
            assert db.query(SandboxPushDelivery).one().state == "expired"
            device = db.query(SandboxPushSubscription).one()
            assert not device.active and not device.subscription_encrypted
        assert len(calls) == 2 and calls[0] == calls[1]


def test_terminal_notice_suppresses_stale_new_order_but_not_cancel_notice(enabled, monkeypatch):
    _, sessions = enabled
    calls = []
    monkeypatch.setattr(push, "_send", lambda sub, event_id, kind, ttl: calls.append(kind) or 201)
    with TestClient(runtime.app) as client:
        client.post("/api/v1/uber-eats/sandbox/push/subscription", json=subscription(), headers=AUTH)
        new, _, _ = signed_receipt(client)
        signed_receipt(client, "orders.cancel", new["meta"]["resource_id"])
        with sessions() as db:
            assert push.enqueue(db) == 2
            assert push.deliver_one(db) and push.deliver_one(db)
            assert [j.state for j in db.query(SandboxPushDelivery).order_by(SandboxPushDelivery.id)] == ["expired", "sent"]
        assert calls == ["orders.cancel"]


def test_payload_is_generic_and_transport_refuses_redirects(enabled, monkeypatch):
    captured = {}

    def provider(**kwargs):
        captured.update(kwargs)
        return type("Response", (), {"status_code": 201})()

    monkeypatch.setattr(push, "webpush", provider)
    event_id = str(uuid4())
    assert push._send(subscription(), event_id, "orders.notification") == 201
    payload = json.loads(captured["data"])
    assert payload["title"] == "Jacaranda Sandbox" and payload["tag"] == "sandbox-" + event_id
    assert "cliente" not in captured["data"].lower() and captured["ttl"] == 900
    assert captured["headers"]["Urgency"] == "high"
    with patch.object(requests.Session, "request") as request:
        push._NoRedirectSession().request("POST", "https://web.push.apple.com/test", allow_redirects=True)
        assert request.call_args.kwargs["allow_redirects"] is False


def test_real_webpush_encrypts_and_signs_without_network(enabled, monkeypatch):
    captured = {}

    def fake_post(self, endpoint, **kwargs):
        captured.update(endpoint=endpoint, **kwargs)
        return type("Response", (), {"status_code": 201, "text": "", "headers": {}})()

    monkeypatch.setattr(push._NoRedirectSession, "post", fake_post)
    assert push._send(subscription(), str(uuid4()), "orders.notification", 70) == 201
    assert captured["endpoint"].startswith("https://web.push.apple.com/")
    assert captured["headers"]["TTL"] == "70"
    assert captured["headers"]["Content-Encoding"] == "aes128gcm"
    assert captured["headers"]["Authorization"].startswith("vapid ")
    assert b"Jacaranda" not in captured["data"]


def test_push_ttl_never_outlives_the_original_event(enabled, monkeypatch):
    _, sessions = enabled
    values = []
    monkeypatch.setattr(push, "_send", lambda sub, event_id, kind, ttl: values.append(ttl) or 201)
    with TestClient(runtime.app) as client:
        client.post("/api/v1/uber-eats/sandbox/push/subscription", json=subscription(), headers=AUTH)
        signed_receipt(client)
        with sessions() as db:
            push.enqueue(db)
            job = db.query(SandboxPushDelivery).one()
            job.received_at = push._now() - timedelta(seconds=850)
            db.commit()
            assert push.deliver_one(db)
    assert len(values) == 1 and 1 <= values[0] <= 50
