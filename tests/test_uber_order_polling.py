"""Automatic GET-only follow-up with synthetic orders and no operational database."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import UUID, uuid4

import httpx
import pytest

from app.core.config import settings
from app.models.uber_eats import UberSandboxAction, UberSandboxEvent, UberSandboxOrder, UberSandboxOrderCheck
from app.models.venta import Venta
from app.services import uber_order_polling as polling
from app.services import uber_order_service as orders
from app.services.uber_webhook_service import WebhookError
from tests.test_uber_orders import ORDER, STORE, details, inspect, receipt, sandbox, submit, transport  # noqa: F401


@pytest.fixture(autouse=True)
def enabled(sandbox, monkeypatch):
    monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_MANAGEMENT_ENABLED", True)
    monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_ORDER_POLLING_ENABLED", True)


def test_ready_order_still_polled_failure_reappears_until_manual_review(db, receipt):
    original = inspect(db, receipt, state="ACCEPTED")
    with transport(lambda r: httpx.Response(200, json={})):
        submit(db, "listo")
    assert orders.attention_orders(db)["total"] == 0
    calls = []
    with transport(lambda r: httpx.Response(200, json=details(state="FAILED")), calls):
        assert polling.process_check(db)
    assert all(call.method == "GET" for call in calls)
    assert db.query(UberSandboxOrder).one().state == "FAILED"
    assert db.query(UberSandboxOrderCheck).one().needs_review
    assert orders.attention_orders(db)["conteos"]["verificar"] == 1
    db.expire_all()
    with patch.object(orders, "_request") as network:
        assert not polling.process_check(db, now=datetime.now(timezone.utc) + timedelta(hours=2))
        with pytest.raises(WebhookError):
            orders.submit_action(db, UUID(ORDER), uuid4(), "listo", None, True, original["detalle_sha256"])
    network.assert_not_called()
    result = inspect(db, receipt, state="FAILED")
    assert result["evento_final"] is None
    assert not result["acciones_habilitadas"]
    assert orders.attention_orders(db)["total"] == 0
    assert db.query(UberSandboxAction).count() == 1
    assert db.query(Venta).count() == 0


def test_pending_cancel_is_not_confirmed_by_automatic_failed_get(db, receipt):
    inspect(db, receipt, state="ACCEPTED")
    with transport(lambda r: httpx.Response(200, json={})):
        submit(db, "cancelar", reason="OTHER")
    key = db.query(UberSandboxOrder).one().pending_request_key
    with transport(lambda r: httpx.Response(200, json=details(state="FAILED"))):
        assert polling.process_check(db)
    result = inspect(db, receipt, state="FAILED")
    assert result["pedido"]["state"] == "FAILED"
    assert result["requiere_conciliacion"] and result["evento_final"] is None
    assert db.query(UberSandboxAction).one().estado == "pendiente_aviso"
    assert db.query(UberSandboxOrder).one().pending_request_key == key
    assert orders.attention_orders(db)["conteos"]["verificar"] == 1


def test_background_check_never_reviews_or_refreshes_operator_authorization(db, receipt):
    with transport(lambda r: httpx.Response(200, json=details())):
        assert polling.process_check(db)
    row = db.query(UberSandboxOrder).one()
    assert row.actualizado_en.year == 1970
    assert receipt.estado == "recibido"
    with patch.object(orders, "_request") as network, pytest.raises(WebhookError, match="Actualiza"):
        submit(db)
    network.assert_not_called()
    inspect(db, receipt)
    original_time, original_snapshot = row.actualizado_en, row.snapshot_json
    change = UberSandboxEvent(
        client_id="fictional-client", store_id=STORE, order_id=ORDER, event_id=str(uuid4()),
        event_type="orders.customer_order_edit", event_time=int(datetime.now(timezone.utc).timestamp()),
        fingerprint="1" * 64, recibido_en=datetime.now(timezone.utc) + timedelta(seconds=1),
    )
    db.add(change)
    db.commit()
    with transport(lambda r: httpx.Response(200, json=details(store_instructions="Changed allergy"))):
        assert polling.process_check(db, now=datetime.now(timezone.utc) + timedelta(minutes=1))
    assert row.actualizado_en == original_time and row.snapshot_json == original_snapshot
    assert change.estado == "recibido" and orders.attention_orders(db)["conteos"]["verificar"] == 1


@pytest.mark.parametrize("status,delay", [(404, 3600), (429, 60), (500, 60)])
def test_errors_backoff_and_review_survive_restart(db, receipt, status, delay):
    now = datetime.now(timezone.utc)
    with transport(lambda r: httpx.Response(status)):
        assert polling.process_check(db, now=now)
    db.expire_all()
    job = db.query(UberSandboxOrderCheck).one()
    assert job.last_error == status and job.failures == 1 and job.needs_review
    assert job.next_check_at.replace(tzinfo=timezone.utc) == now + timedelta(seconds=delay)
    with patch.object(orders, "_request") as network:
        assert not polling.process_check(db, now=now + timedelta(seconds=delay - 1))
    network.assert_not_called()
    with transport(lambda r: httpx.Response(200, json=details())):
        assert polling.process_check(db, now=now + timedelta(seconds=delay))
    db.refresh(job)
    assert job.failures == 0 and job.last_error is None
    assert job.needs_review  # A successful background read is not an operator acknowledgement.


def test_lease_and_fairness_do_not_repeat_or_starve_other_orders(db, receipt):
    now = datetime.now(timezone.utc)
    job = UberSandboxOrderCheck(client_id="fictional-client", store_id=STORE, order_id=ORDER,
                                next_check_at=now + timedelta(seconds=120), lease_key=str(uuid4()))
    other_id = str(uuid4())
    other = UberSandboxEvent(client_id="fictional-client", store_id=STORE, order_id=other_id,
                            event_id=str(uuid4()), event_type="orders.notification", event_time=1, fingerprint="2" * 64)
    db.add_all([job, other])
    db.commit()
    calls = []
    with transport(lambda r: httpx.Response(200, json=details(id=other_id)), calls):
        assert polling.process_check(db, now=now)
        assert not polling.process_check(db, now=now)
    assert len([r for r in calls if r.method == "GET"]) == 1
    assert db.query(UberSandboxOrder).one().order_id == other_id
    with transport(lambda r: httpx.Response(200, json=details())):
        # Move the other due date forward to test recovery of the expired lease.
        db.query(UberSandboxOrderCheck).filter_by(order_id=other_id).update({"next_check_at": now + timedelta(hours=1)})
        db.commit()
        assert polling.process_check(db, now=now + timedelta(seconds=120))
    db.refresh(job)
    assert job.lease_key is None and job.checked_at is not None


def test_polling_is_opt_in_and_rejects_non_test_host(db, receipt, monkeypatch):
    monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_ORDER_POLLING_ENABLED", False)
    with patch.object(orders, "_request") as network:
        assert not polling.process_check(db)
    network.assert_not_called()
    monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_ORDER_POLLING_ENABLED", True)
    monkeypatch.setattr(orders.api, "API_URL", "https://api.uber.com")
    with patch.object(httpx, "Client") as network:
        assert polling.process_check(db)
    network.assert_not_called()
    assert db.query(UberSandboxOrder).count() == 0


def test_mismatched_order_identity_cannot_be_accepted_by_background_check(db, receipt):
    with transport(lambda r: httpx.Response(200, json=details(store={"id": str(uuid4())}))):
        assert polling.process_check(db)
    assert db.query(UberSandboxOrder).count() == 0
    assert db.query(UberSandboxOrderCheck).one().needs_review
