"""Pending-order alerts use durable, scoped receipts without sending Uber actions."""

import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app import uber_sandbox_runtime as runtime
from app.models.uber_eats import UberSandboxAction, UberSandboxEvent, UberSandboxOrder
from app.services import uber_order_service as orders
from tests.test_uber_sandbox_management import AUTH, management  # noqa: F401
from tests.test_uber_sandbox_runtime import SECRET, isolated  # noqa: F401

BASE = "/api/v1/uber-eats/sandbox"


def notify(client, order_id=None, kind="orders.notification", timestamp=None):
    event = {
        "event_id": str(uuid4()), "event_type": kind,
        "event_time": timestamp if timestamp is not None else int(time.time()),
        "meta": {"user_id": runtime.TEST_STORE_ID, "resource_id": order_id or str(uuid4())},
        "webhook_meta": {"client_id": runtime.TEST_APPLICATION_ID},
    }
    raw = json.dumps(event).encode()
    headers = {"X-Uber-Signature": hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()}
    for _ in range(2):
        response = client.post(runtime.WEBHOOK_PATH, content=raw, headers=headers)
        assert response.status_code == 200 and response.content == b""
    return event


def save_order(db, event, state, updated=None):
    row = UberSandboxOrder(
        client_id=runtime.TEST_APPLICATION_ID, store_id=runtime.TEST_STORE_ID,
        order_id=event["meta"]["resource_id"], state=state,
        snapshot_json=json.dumps({"id": event["meta"]["resource_id"], "state": state}),
        actualizado_en=updated or datetime.now(timezone.utc),
    )
    db.add(row)
    db.commit()
    return row


def test_attention_is_private_deduplicated_and_independent_of_history_page(management):
    with TestClient(runtime.app) as client, patch("httpx.Client") as network:
        assert client.get(BASE + "/atencion").status_code == 401
        assert client.get(BASE + "/atencion?token=synthetic", headers={}).status_code == 401
        assert client.get("/attention.js").status_code == 200
        for _ in range(14):
            notify(client)
        data = client.get(BASE + "/atencion", headers=AUTH).json()
        assert data["total"] == data["conteos"]["nuevo"] == len(data["pedidos"]) == 14
        assert len({row["pedido_id"] for row in data["pedidos"]}) == 14
        assert len(client.get(BASE + "/eventos?limit=10", headers=AUTH).json()["eventos"]) == 10
        network.assert_not_called()
    with management[1]() as db:
        assert db.query(UberSandboxEvent).count() == 14
        assert db.query(UberSandboxOrder).count() == db.query(UberSandboxAction).count() == 0


def test_attention_counts_full_queue_but_returns_a_bounded_list(management):
    with TestClient(runtime.app) as client:
        with management[1]() as db:
            for _ in range(110):
                db.add(UberSandboxEvent(
                    client_id=runtime.TEST_APPLICATION_ID, store_id=runtime.TEST_STORE_ID,
                    event_id=str(uuid4()), event_type="orders.notification", order_id=str(uuid4()),
                    event_time=int(time.time()), fingerprint="synthetic",
                ))
            db.commit()
        data = client.get(BASE + "/atencion", headers=AUTH).json()
        assert data["total"] == 110 and len(data["pedidos"]) == 100


def test_attention_uses_event_time_and_retains_cancellation_until_canonical_resolution(management):
    with TestClient(runtime.app) as client:
        event = notify(client, timestamp=int(time.time()) - 20)
        order_id = event["meta"]["resource_id"]
        cancel = notify(client, order_id, "orders.cancel", int(time.time()) - 10)
        notify(client, order_id, timestamp=int(time.time()) - 20)
        with management[1]() as db:
            save_order(db, event, "ACCEPTED")
        data = client.get(BASE + "/atencion", headers=AUTH).json()
        assert data["total"] == data["conteos"]["verificar"] == 1
        assert data["pedidos"][0]["event_id"] == cancel["event_id"]
        notify(client, order_id, "delivery.state_changed")
        assert client.get(BASE + "/atencion", headers=AUTH).json()["conteos"]["verificar"] == 1
        with management[1]() as db:
            row = db.query(UberSandboxOrder).one()
            row.state = "FAILED"
            row.actualizado_en = datetime.now(timezone.utc)
            db.commit()
        assert client.get(BASE + "/atencion", headers=AUTH).json()["total"] == 0


def test_attention_keeps_uncertain_commands_and_hides_resolved_orders(management):
    with TestClient(runtime.app) as client:
        completed = notify(client)
        preparing = notify(client)
        ready = notify(client)
        uncertain = notify(client)
        scheduled = notify(client, kind="orders.scheduled.notification")
        with management[1]() as db:
            save_order(db, completed, "SUCCEEDED")
            save_order(db, preparing, "ACCEPTED")
            ready_row = save_order(db, ready, "ACCEPTED")
            uncertain_row = save_order(db, uncertain, "SUCCEEDED")
            for row, action, state in ((ready_row, "listo", "confirmada"), (uncertain_row, "cancelar", "incierta")):
                db.add(UberSandboxAction(
                    client_id=runtime.TEST_APPLICATION_ID, store_id=runtime.TEST_STORE_ID,
                    order_id=row.order_id, request_key=str(uuid4()), fingerprint="synthetic",
                    action=action, estado=state, creado_en=datetime.now(timezone.utc),
                ))
            db.commit()
        data = client.get(BASE + "/atencion", headers=AUTH).json()
        assert data["total"] == 3
        assert data["conteos"] == {"nuevo": 0, "verificar": 1, "preparacion": 1, "programado": 1}
        assert data["pedidos"][0]["pedido_id"] == uncertain["meta"]["resource_id"]
        assert scheduled["meta"]["resource_id"] in {row["pedido_id"] for row in data["pedidos"]}


def test_attention_does_not_include_other_clients_or_stores_and_survives_restart(management):
    with TestClient(runtime.app) as client:
        event = notify(client)
        with management[1]() as db:
            for foreign in ({"client_id": "different-client"}, {"store_id": str(uuid4())}):
                db.add(UberSandboxEvent(**{
                    "client_id": runtime.TEST_APPLICATION_ID, "store_id": runtime.TEST_STORE_ID,
                    "event_id": str(uuid4()), "event_type": "orders.notification", "order_id": str(uuid4()),
                    "event_time": int(time.time()), "fingerprint": "synthetic", **foreign,
                }))
            db.commit()
        assert client.get(BASE + "/atencion", headers=AUTH).json()["total"] == 1
    with TestClient(runtime.app) as client, patch("httpx.Client") as network:
        data = client.get(BASE + "/atencion", headers=AUTH).json()
        assert data["total"] == 1 and data["pedidos"][0]["event_id"] == event["event_id"]
        network.assert_not_called()


def test_unreviewed_edit_blocks_actions_before_any_uber_request(management):
    with TestClient(runtime.app) as client:
        event = notify(client)
        with management[1]() as db:
            save_order(db, event, "OFFERED", datetime.now(timezone.utc) - timedelta(seconds=10))
        notify(client, event["meta"]["resource_id"], "orders.customer_order_edit")
        with patch("httpx.Client") as network:
            response = client.post(BASE + "/pedidos/" + event["meta"]["resource_id"] + "/accion", headers=AUTH, json={
                "request_key": str(uuid4()), "accion": "aceptar", "instrucciones_revisadas": True,
                "detalle_sha256": "0" * 64,
            })
            assert response.status_code == 409 and "Actualiza" in response.text
            network.assert_not_called()
        with management[1]() as db:
            assert db.query(UberSandboxAction).count() == 0


def test_edit_during_detail_fetch_requires_another_read(management, monkeypatch):
    with TestClient(runtime.app) as client:
        event = notify(client)
        with management[1]() as db:
            def fetch(*args, **kwargs):
                db.add(UberSandboxEvent(
                    client_id=runtime.TEST_APPLICATION_ID, store_id=runtime.TEST_STORE_ID,
                    event_id=str(uuid4()), order_id=event["meta"]["resource_id"],
                    event_type="orders.customer_order_edit", event_time=int(time.time()), fingerprint="synthetic",
                ))
                db.commit()
                return {"order": {"id": event["meta"]["resource_id"], "store": {"id": runtime.TEST_STORE_ID},
                                  "state": "OFFERED", "carts": []}}

            monkeypatch.setattr(orders, "_request", fetch)
            result = orders.inspect_order(db, UUID(event["event_id"]))
            assert result["requiere_conciliacion"] and not result["acciones_habilitadas"]


def test_edit_during_action_confirmation_remains_in_attention_queue(management, monkeypatch):
    with TestClient(runtime.app) as client:
        event = notify(client)
        with management[1]() as db:
            row = save_order(db, event, "OFFERED")
            row.snapshot_json = json.dumps({"carts": [{"items": [{
                "id": "fictional-brownie", "title": "Fixture", "quantity": {"amount": 1},
            }]}]})
            db.commit()
            digest = hashlib.sha256(row.snapshot_json.encode()).hexdigest()
            calls = []

            def confirm(method, order_id, payload, action):
                calls.append((method, action))
                db.add(UberSandboxEvent(
                    client_id=runtime.TEST_APPLICATION_ID, store_id=runtime.TEST_STORE_ID,
                    event_id=str(uuid4()), order_id=order_id, event_type="orders.customer_order_edit",
                    event_time=int(time.time()), fingerprint="synthetic",
                ))
                db.commit()
                return {}

            monkeypatch.setattr(orders, "_request", confirm)
            result = orders.submit_action(db, UUID(row.order_id), uuid4(), "aceptar", None, True, digest)
            assert result["estado"] == "confirmada"
            assert orders.attention_orders(db)["conteos"]["verificar"] == 1
            assert calls == [("POST", "aceptar")]
