"""Sandbox order lifecycle against a synthetic transport only."""

import hashlib
import json
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.uber_eats import UberSandboxEvent, UberSandboxOrder, UberSandboxAction
from app.models.venta import Venta
from app.services import uber_eats_service as api
from app.services import uber_order_service as orders
from app.services.uber_webhook_service import WebhookError

STORE = "5d8714ab-07bc-4b7f-a0ee-5cbeb9c31594"
ORDER = "7871d55c-2460-484d-9f24-239416d1d2aa"


@pytest.fixture(autouse=True)
def sandbox(monkeypatch):
    monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_ENABLED", True)
    monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_ACTIONS_ENABLED", True)
    monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_CLIENT_ID", "fictional-client")
    monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_CLIENT_SECRET", SecretStr("synthetic-order-secret"))
    monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_STORE_ID", STORE)
    monkeypatch.setattr(api, "_order_token_cache", None)


@pytest.fixture
def receipt(db):
    row = UberSandboxEvent(
        client_id="fictional-client", store_id=STORE, event_id=str(uuid4()),
        order_id=ORDER, event_type="orders.notification", event_time=int(time.time()), fingerprint="0" * 64,
    )
    db.add(row)
    db.commit()
    return row


def details(**overrides):
    order = {
        "id": ORDER, "display_id": "TEST1", "state": "OFFERED", "status": "ACTIVE",
        "store": {"id": STORE}, "store_instructions": "Alergia: sin nueces",
        "carts": [{"id": "cart1", "items": [{
            "id": "product1", "title": "Brownie", "quantity": {"amount": 1},
            "special_instructions": "Sin nueces", "allergy": "nueces",
        }]}],
        "customers": [{"phone": "do-not-retain-contact"}],
        "payment": {"token": "do-not-retain-payment"},
        "support_contact": {"secret": "do-not-retain-support"},
    }
    order.update(overrides)
    return {"order": order}


@contextmanager
def transport(handler, calls=None):
    original = httpx.Client

    def serve(request):
        if calls is not None:
            calls.append(request)
        if str(request.url) == api.TOKEN_URL:
            assert b"eats.order" in request.content
            return httpx.Response(200, json={"access_token": "synthetic-token", "expires_in": 3600})
        assert request.url.host == "test-api.uber.com"
        assert request.headers["Authorization"] == "Bearer synthetic-token"
        return handler(request)

    with patch.object(httpx, "Client", side_effect=lambda **kwargs: original(transport=httpx.MockTransport(serve), **kwargs)):
        yield


def inspect(db, receipt, **changes):
    with transport(lambda r: httpx.Response(200, json=details(**changes))):
        return orders.inspect_order(db, UUID(receipt.event_id))


def submit(db, action="aceptar", key=None, reason=None, reviewed=True):
    row = db.query(UberSandboxOrder).filter_by(order_id=ORDER).first()
    digest = hashlib.sha256(row.snapshot_json.encode()).hexdigest() if row else "0" * 64
    return orders.submit_action(db, UUID(ORDER), key or uuid4(), action, reason, reviewed, digest)


def test_inspection_preserves_all_instructions_omits_contacts_and_never_writes_sales(db, receipt):
    calls = []
    with transport(lambda r: httpx.Response(200, json=details()), calls):
        result = orders.inspect_order(db, UUID(receipt.event_id))
        orders.inspect_order(db, UUID(receipt.event_id))
    assert len(calls) == 3  # One cached token, two GETs.
    assert str(calls[1].url) == f"https://test-api.uber.com/v1/delivery/order/{ORDER}?expand=carts"
    assert result["pedido"]["store_instructions"] == "Alergia: sin nueces"
    assert result["pedido"]["carts"][0]["items"][0]["special_instructions"] == "Sin nueces"
    row = db.query(UberSandboxOrder).one()
    assert "do-not-retain" not in row.snapshot_json
    assert db.query(Venta).count() == 0
    assert db.query(UberSandboxEvent).one().estado == "consultado"


def test_opt_in_financial_expansion_is_still_read_only_and_test_only(db):
    calls = []
    with transport(lambda request: httpx.Response(200, json=details()), calls):
        orders._request("GET", ORDER, include_payment=True)
    assert len(calls) == 2
    assert str(calls[1].url) == f"https://test-api.uber.com/v1/delivery/order/{ORDER}?expand=carts%2Cpayment"
    assert calls[1].method == "GET" and db.query(Venta).count() == 0


@pytest.mark.parametrize("overrides", [{"id": str(uuid4())}, {"store": {"id": str(uuid4())}}, {"store": None}, {"state": []}])
def test_wrong_or_incomplete_order_response_is_not_trusted(db, receipt, overrides):
    with pytest.raises(WebhookError) as failure:
        inspect(db, receipt, **overrides)
    assert failure.value.status_code == 502
    assert db.query(UberSandboxOrder).count() == 0


@pytest.mark.parametrize("action,reason,status,state", [
    ("aceptar", None, 200, "OFFERED"), ("rechazar", "SPECIAL_INSTRUCTIONS", 200, "OFFERED"),
    ("cancelar", "ITEM_ISSUE", 200, "ACCEPTED"),
])
def test_explicit_actions_use_documented_endpoints_once(db, receipt, action, reason, status, state):
    inspect(db, receipt, state=state)
    key = uuid4()
    calls = []

    def handler(request):
        assert request.method == "POST"
        assert request.url.path.endswith("/" + {"aceptar": "accept", "rechazar": "deny", "cancelar": "cancel"}[action])
        data = json.loads(request.content)
        if action == "aceptar":
            assert data["external_reference_id"].endswith(str(key))
        else:
            assert data["deny_reason" if action == "rechazar" else "cancellation_reason"]["type"] == reason
            assert data["deny_reason" if action == "rechazar" else "cancellation_reason"]["info"] == (
                "Jacaranda Sandbox UBER_TEST integration validation."
            )
        return httpx.Response(status, json={})

    with transport(handler, calls):
        assert submit(db, action, key, reason)["repetida"] is False
        assert submit(db, action, key, reason)["repetida"] is True
    assert len(calls) == 1
    assert db.query(UberSandboxAction).one().estado == ("pendiente_aviso" if action == "cancelar" else "confirmada")
    assert bool(db.query(UberSandboxOrder).one().pending_request_key) == (action == "cancelar")
    assert db.query(Venta).count() == 0


@pytest.mark.parametrize("status,uncertain", [(500, True), (502, True), (302, True), (400, False), (401, False), (403, False)])
def test_errors_do_not_claim_success_or_retry_blindly(db, receipt, status, uncertain):
    inspect(db, receipt)
    calls = []
    with transport(lambda r: httpx.Response(status, json={"secret": "never-expose"}), calls):
        with pytest.raises(WebhookError) as error:
            submit(db)
        assert "never-expose" not in str(error.value)
        assert f"HTTP {status}" in str(error.value)
        if uncertain:
            with pytest.raises(WebhookError, match="sin confirmar"):
                submit(db)
    command = db.query(UberSandboxAction).one()
    assert command.estado == ("incierta" if uncertain else "rechazada")
    assert len([r for r in calls if r.url.host == "test-api.uber.com"]) == 1


def test_provider_diagnostics_never_log_response_or_credentials(db, receipt, caplog):
    inspect(db, receipt)
    with caplog.at_level("INFO", logger="app.services.uber_order_service"), transport(lambda r: httpx.Response(
        400, json={"code": "bad_request", "message": "private-response-secret"},
        headers={"x-uber-request-id": "provider-private-token-not-a-uuid"},
    )), pytest.raises(WebhookError):
        submit(db)
    assert "http=400" in caplog.text and "code=bad_request" in caplog.text
    assert "fields=code,message" in caplog.text
    assert "private-response-secret" not in caplog.text
    assert "provider-private-token" not in caplog.text
    assert "synthetic-order-secret" not in caplog.text


def test_error_envelope_in_success_response_stays_uncertain(db, receipt):
    inspect(db, receipt)
    with transport(lambda r: httpx.Response(200, json={"code": "bad_request"})), pytest.raises(WebhookError):
        submit(db)
    assert db.query(UberSandboxAction).one().estado == "incierta"
    with patch.object(orders, "_request") as network, pytest.raises(WebhookError, match="sin confirmar"):
        submit(db)
    network.assert_not_called()


def test_oversized_post_response_is_uncertain_and_bounded(db, receipt):
    inspect(db, receipt)
    with transport(lambda r: httpx.Response(200, content=b" " * (orders.MAX_RESPONSE_BYTES + 1))), pytest.raises(WebhookError):
        submit(db)
    assert db.query(UberSandboxAction).one().estado == "incierta"


def test_timeout_remains_uncertain_across_fresh_session_and_inspection(db, receipt):
    inspect(db, receipt)

    def timeout(request):
        raise httpx.ReadTimeout("do-not-expose", request=request)

    with transport(timeout), pytest.raises(WebhookError, match="No se ha reenviado"):
        submit(db)
    db.expire_all()
    result = inspect(db, receipt)
    assert result["requiere_conciliacion"] and not result["acciones_habilitadas"]
    assert db.query(UberSandboxOrder).one().pending_request_key
    with patch.object(orders, "_request") as network, pytest.raises(WebhookError, match="sin confirmar"):
        submit(db)
    network.assert_not_called()


def test_crash_after_persistent_claim_blocks_another_action(db, receipt):
    inspect(db, receipt)
    with patch.object(orders, "_request", side_effect=RuntimeError("Simulated process crash")):
        with pytest.raises(RuntimeError):
            submit(db)
    assert db.query(UberSandboxAction).one().estado == "enviando"
    with patch.object(orders, "_request") as network, pytest.raises(WebhookError, match="sin confirmar"):
        submit(db)
    network.assert_not_called()


@pytest.mark.parametrize("change,expected", [("disabled", 409), ("unreviewed", 422), ("stale", 409), ("incomplete", 409), ("failed", 409)])
def test_action_safety_gates(db, receipt, monkeypatch, change, expected):
    inspect(db, receipt)
    row = db.query(UberSandboxOrder).one()
    if change == "disabled":
        monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_ACTIONS_ENABLED", False)
    elif change == "stale":
        row.actualizado_en = datetime.now(timezone.utc) - timedelta(minutes=5)
    elif change == "incomplete":
        row.snapshot_json = '{"carts":[{}]}'
    elif change == "failed":
        row.state = "FAILED"
    db.commit()
    with patch.object(orders, "_request") as network, pytest.raises(WebhookError) as error:
        submit(db, reviewed=change != "unreviewed")
    assert error.value.status_code == expected
    network.assert_not_called()


def test_reused_key_with_other_action_is_a_conflict(db, receipt):
    inspect(db, receipt)
    key = uuid4()
    with transport(lambda r: httpx.Response(200)):
        submit(db, key=key)
    with pytest.raises(WebhookError, match="otros datos"):
        submit(db, action="cancelar", key=key, reason="OTHER")


def test_stale_review_cannot_accept_changed_instructions(db, receipt):
    original = inspect(db, receipt)
    inspect(db, receipt, store_instructions="Instruccion nueva: alergia a lacteos")
    with patch.object(orders, "_request") as network, pytest.raises(WebhookError, match="detalle cambio"):
        orders.submit_action(db, UUID(ORDER), uuid4(), "aceptar", None, True, original["detalle_sha256"])
    network.assert_not_called()


def test_stale_remote_order_cannot_reopen_accepted_order(db, receipt):
    inspect(db, receipt)
    with transport(lambda r: httpx.Response(200)):
        submit(db)
    result = inspect(db, receipt, state="OFFERED")
    assert result["pedido"]["state"] == "ACCEPTED"
    assert result["acciones_habilitadas"] is False
    assert result["requiere_conciliacion"] is True
    assert result["estado_remoto"] == "OFFERED"
    with pytest.raises(WebhookError, match="estado"):
        submit(db)


def test_success_response_with_unconfirmed_denial_does_not_reopen_order(db, receipt):
    inspect(db, receipt)
    with transport(lambda r: httpx.Response(200)):
        submit(db, action="rechazar", reason="OTHER")
    result = inspect(db, receipt, state="OFFERED")
    assert result["pedido"]["state"] == "FAILED"
    assert result["estado_remoto"] == "OFFERED"
    assert result["requiere_conciliacion"] and not result["acciones_habilitadas"]
    with patch.object(orders, "_request") as network, pytest.raises(WebhookError, match="estado"):
        submit(db, action="rechazar", reason="OTHER")
    network.assert_not_called()


@pytest.mark.parametrize("status,body", [(204, b""), (200, b""), (200, b"not-json"), (200, b'[]'),
                                         (200, b'{"code":"bad_request"}'), (200, b'{"success":true}')])
def test_unexpected_cancel_response_is_not_claimed_or_resent(db, receipt, status, body):
    inspect(db, receipt, state="ACCEPTED")
    with transport(lambda r: httpx.Response(status, content=body)), pytest.raises(WebhookError, match=f"HTTP {status}"):
        submit(db, action="cancelar", reason="OTHER")
    result = inspect(db, receipt, state="SUCCEEDED")
    assert result["pedido"]["state"] == "ACCEPTED"
    assert result["estado_remoto"] == "SUCCEEDED"
    assert result["requiere_conciliacion"] and not result["acciones_habilitadas"]
    with patch.object(orders, "_request") as network, pytest.raises(WebhookError, match="sin confirmar"):
        submit(db, action="cancelar", reason="OTHER")
    network.assert_not_called()


def test_ready_uses_empty_body_once_and_does_not_claim_delivery_or_failure(db, receipt):
    inspect(db, receipt, state="ACCEPTED")
    key = uuid4()
    calls = []

    def ready(request):
        assert request.method == "POST" and request.url.path.endswith("/ready")
        assert json.loads(request.content) == {}
        return httpx.Response(200)

    with transport(ready, calls):
        assert submit(db, action="listo", key=key)["repetida"] is False
        assert submit(db, action="listo", key=key)["repetida"] is True
        with pytest.raises(WebhookError, match="ya fue marcado"):
            submit(db, action="listo")
    result = inspect(db, receipt, state="ACCEPTED")
    assert result["listo_confirmado"] is True
    assert result["pedido"]["state"] == "ACCEPTED"
    assert len(calls) == 1
    assert db.query(Venta).count() == 0


@pytest.mark.parametrize("state,reviewed", [("OFFERED", True), ("FAILED", True), ("ACCEPTED", False)])
def test_ready_requires_accepted_reviewed_order(db, receipt, state, reviewed):
    inspect(db, receipt, state=state)
    with patch.object(orders, "_request") as network, pytest.raises(WebhookError):
        submit(db, action="listo", reviewed=reviewed)
    network.assert_not_called()


def cancellation_receipt(db, **changes):
    command = db.query(UberSandboxAction).one()
    when = command.creado_en.replace(tzinfo=timezone.utc) + timedelta(seconds=1)
    values = {
        "client_id": "fictional-client", "store_id": STORE, "order_id": ORDER,
        "event_id": str(uuid4()), "event_type": "orders.cancel",
        "event_time": int(when.timestamp()), "recibido_en": when, "fingerprint": "1" * 64,
    }
    values.update(changes)
    db.add(UberSandboxEvent(**values))
    db.commit()


@pytest.mark.parametrize("remote", ["SUCCEEDED", "ACCEPTED", "OFFERED", "FAILED"])
@pytest.mark.parametrize("kind", ["orders.cancel", "orders.failure"])
def test_signed_terminal_notice_wins_over_get_without_another_post(db, receipt, remote, kind):
    original = inspect(db, receipt, state="ACCEPTED")
    key = uuid4()
    with transport(lambda r: httpx.Response(200, json={})):
        assert submit(db, action="cancelar", key=key, reason="ITEM_ISSUE")["estado"] == "pendiente_aviso"
    cancellation_receipt(db, event_type=kind)
    db.expire_all()
    calls = []
    with transport(lambda r: httpx.Response(200, json=details(state=remote, status="COMPLETED")), calls):
        result = orders.inspect_order(db, UUID(receipt.event_id))
        replay = orders.submit_action(
            db, UUID(ORDER), key, "cancelar", "ITEM_ISSUE", True, original["detalle_sha256"],
        )
    assert result["pedido"]["state"] == "FAILED" and result["estado_remoto"] == remote
    assert result["evento_final"]["tipo"] == kind and not result["acciones_habilitadas"]
    assert result["requiere_conciliacion"] is False
    assert db.query(UberSandboxOrder).one().pending_request_key is None
    assert db.query(UberSandboxAction).one().estado == "conciliada"
    assert replay == {"entorno": "sandbox", "estado": "conciliada", "repetida": True}
    assert all(request.method != "POST" for request in calls)
    assert db.query(Venta).count() == 0
    with patch.object(orders, "_request") as network, pytest.raises(WebhookError, match="estado"):
        submit(db, action="cancelar", reason="ITEM_ISSUE")
    network.assert_not_called()


@pytest.mark.parametrize("change", [
    "missing", "other-client", "other-store", "other-order", "wrong-type", "old-event", "old-receipt",
    "acceptance", "wrong-request",
])
def test_cancellation_reconciliation_requires_correlated_final_evidence(db, receipt, change):
    inspect(db, receipt, state="ACCEPTED" if change != "acceptance" else "OFFERED")
    action = "aceptar" if change == "acceptance" else "cancelar"
    with transport(lambda r: httpx.Response(500)), pytest.raises(WebhookError):
        submit(db, action=action, reason=None if action == "aceptar" else "ITEM_ISSUE")
    command = db.query(UberSandboxAction).one()
    before = command.creado_en.replace(tzinfo=timezone.utc) - timedelta(seconds=1)
    if change != "missing":
        overrides = {
            "other-client": {"client_id": "other-client"},
            "other-store": {"store_id": str(uuid4())},
            "other-order": {"order_id": str(uuid4())},
            "wrong-type": {"event_type": "orders.notification"},
            "old-event": {"event_time": int(before.timestamp())},
            "old-receipt": {"recibido_en": before},
        }.get(change, {})
        cancellation_receipt(db, **overrides)
    if change == "wrong-request":
        db.query(UberSandboxOrder).one().pending_request_key = str(uuid4())
    db.commit()
    result = inspect(db, receipt, state="FAILED")
    authoritative = change in {"old-event", "old-receipt", "acceptance", "wrong-request"}
    assert result["pedido"]["state"] == ("FAILED" if authoritative else "ACCEPTED")
    assert result["requiere_conciliacion"] and not result["acciones_habilitadas"]
    assert command.estado == "incierta"
    assert db.query(UberSandboxOrder).one().pending_request_key


def test_cancel_ack_remains_pending_after_restart_and_failed_get_without_notice(db, receipt):
    original = inspect(db, receipt, state="ACCEPTED")
    key = uuid4()
    with transport(lambda r: httpx.Response(200, json={})):
        assert submit(db, "cancelar", key, "OTHER")["estado"] == "pendiente_aviso"
    db.expire_all()
    result = inspect(db, receipt, state="FAILED")
    assert result["requiere_conciliacion"] and not result["acciones_habilitadas"]
    assert result["pedido"]["state"] == "ACCEPTED" and result["evento_final"] is None
    with patch.object(orders, "_request") as network:
        assert orders.submit_action(db, UUID(ORDER), key, "cancelar", "OTHER", True,
                                    original["detalle_sha256"])["repetida"] is True
        with pytest.raises(WebhookError, match="sin confirmar"):
            submit(db, "cancelar", reason="OTHER")
    network.assert_not_called()


@pytest.mark.parametrize("has_snapshot", [True, False])
def test_signed_terminal_notice_remains_authoritative_when_get_is_unavailable(db, receipt, has_snapshot):
    if has_snapshot:
        inspect(db, receipt, state="ACCEPTED")
    notice = UberSandboxEvent(
        client_id="fictional-client", store_id=STORE, order_id=ORDER, event_id=str(uuid4()),
        event_type="orders.cancel", event_time=int(time.time()), fingerprint="1" * 64,
    )
    db.add(notice)
    db.commit()
    with transport(lambda r: httpx.Response(404)):
        result = orders.inspect_order(db, UUID(notice.event_id))
    assert result["pedido"]["state"] == "FAILED" and result["evento_final"]["tipo"] == "orders.cancel"
    assert result["detalle_disponible"] is False and result["estado_remoto"] is None
    assert not result["acciones_habilitadas"] and not result["requiere_conciliacion"]
    assert bool(result["pedido"].get("carts")) == has_snapshot
    assert db.query(Venta).count() == 0


def test_missing_get_without_terminal_notice_is_still_unresolved(db, receipt):
    with transport(lambda r: httpx.Response(404)), pytest.raises(WebhookError, match="No se pudo consultar"):
        orders.inspect_order(db, UUID(receipt.event_id))
    assert db.query(UberSandboxOrder).count() == 0


@pytest.mark.parametrize("action", ["aceptar", "listo", "cancelar"])
@pytest.mark.parametrize("status", [200, 500])
def test_terminal_notice_during_post_never_resurrects_order_or_resends(db, receipt, action, status):
    inspect(db, receipt, state="OFFERED" if action == "aceptar" else "ACCEPTED")

    def response(request):
        cancellation_receipt(db)
        return httpx.Response(status, json={})

    with transport(response):
        if action != "cancelar" and status == 500:
            with pytest.raises(WebhookError):
                submit(db, action, reason="OTHER" if action == "cancelar" else None)
        else:
            result = submit(db, action, reason="OTHER" if action == "cancelar" else None)
            assert result["estado"] == ("conciliada" if action == "cancelar" else "confirmada")
    assert db.query(UberSandboxOrder).one().state == "FAILED"
    assert db.query(UberSandboxAction).one().estado == (
        "conciliada" if action == "cancelar" else "confirmada" if status == 200 else "incierta")
    inspected = inspect(db, receipt, state="SUCCEEDED")
    assert inspected["pedido"]["state"] == "FAILED" and not inspected["acciones_habilitadas"]
    with patch.object(orders, "_request") as network, pytest.raises(WebhookError):
        submit(db, action, reason="OTHER" if action == "cancelar" else None)
    network.assert_not_called()


def test_sqlite_inspection_cannot_overwrite_concurrently_confirmed_acceptance(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + str(tmp_path / "sandbox-only.db"))
    sessions = sessionmaker(bind=engine)
    for model in (UberSandboxEvent, UberSandboxOrder, UberSandboxAction):
        model.__table__.create(engine)
    event_id = uuid4()
    with sessions() as db:
        db.add(UberSandboxEvent(
            client_id="fictional-client", store_id=STORE, event_id=str(event_id), order_id=ORDER,
            event_type="orders.notification", event_time=int(time.time()), fingerprint="0" * 64,
        ))
        snapshot = details(state="CREATED")["order"]
        db.add(UberSandboxOrder(
            client_id="fictional-client", store_id=STORE, order_id=ORDER, state="CREATED",
            snapshot_json=json.dumps(snapshot), actualizado_en=datetime.now(timezone.utc),
        ))
        db.commit()
    accepted = []

    def network(method, order_id, payload=None, action=None):
        if method == "GET":
            return details()
        accepted.append(action)
        return {}

    monkeypatch.setattr(orders, "_request", network)
    interrupted = False

    def accept_before_inspection_write(_conn, _cursor, statement, _parameters, _context, _many):
        nonlocal interrupted
        if not interrupted and statement.startswith("UPDATE uber_sandbox_orders SET state="):
            interrupted = True
            with sessions() as other:
                submit(other)

    event.listen(engine, "before_cursor_execute", accept_before_inspection_write)
    try:
        with sessions() as db:
            result = orders.inspect_order(db, event_id)
        assert interrupted and result["pedido"]["state"] == "ACCEPTED"
        assert not result["acciones_habilitadas"]
        with sessions() as db, pytest.raises(WebhookError, match="estado"):
            submit(db)
        assert accepted == ["aceptar"]
    finally:
        engine.dispose()


def test_missing_secret_cannot_start_external_requests(db, receipt, monkeypatch):
    monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_CLIENT_SECRET", SecretStr(""))
    with patch.object(orders, "_request") as network, pytest.raises(WebhookError) as failure:
        orders.inspect_order(db, UUID(receipt.event_id))
    assert failure.value.status_code == 503
    network.assert_not_called()


def test_only_stored_current_sandbox_orders_can_be_requested(db, receipt, monkeypatch):
    with patch.object(orders, "_request") as network, pytest.raises(WebhookError):
        orders.inspect_order(db, uuid4())
    network.assert_not_called()
    monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_STORE_ID", str(uuid4()))
    with patch.object(orders, "_request") as network, pytest.raises(WebhookError):
        orders.inspect_order(db, UUID(receipt.event_id))
    network.assert_not_called()


def test_oversized_or_non_json_order_responses_are_bounded(db, receipt):
    for response in [httpx.Response(200, content=b" " * (orders.MAX_RESPONSE_BYTES + 1)), httpx.Response(200, content=b"not-json")]:
        with transport(lambda r: response), pytest.raises(WebhookError):
            orders.inspect_order(db, UUID(receipt.event_id))
    assert db.query(UberSandboxOrder).count() == 0


def test_routes_require_admin_and_reject_arbitrary_payloads(client, auth_headers, receipt):
    url = f"/api/v1/uber-eats/sandbox/eventos/{receipt.event_id}/consultar"
    assert client.post(url).status_code == 401
    with transport(lambda r: httpx.Response(200, json=details())):
        response = client.post(url, headers=auth_headers)
    assert response.status_code == 200
    inspection = response.json()
    action_url = f"/api/v1/uber-eats/sandbox/pedidos/{ORDER}/accion"
    data = {"request_key": str(uuid4()), "accion": "aceptar", "instrucciones_revisadas": True,
            "detalle_sha256": inspection["detalle_sha256"]}
    assert client.post(action_url, json=data).status_code == 401
    assert client.post(action_url, headers=auth_headers, json={**data, "resource_href": "https://attacker.invalid"}).status_code == 422
    assert client.post(action_url, headers=auth_headers, json={**data, "instrucciones_revisadas": "true"}).status_code == 422
    with transport(lambda r: httpx.Response(200)):
        assert client.post(action_url, headers=auth_headers, json=data).status_code == 200
