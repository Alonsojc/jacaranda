"""Hosted financial contracts without touching a provider or operating DB."""

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from app.core.config import settings
from app.models.inventario import MovimientoInventario, Producto
from app.models.uber_eats import UberSandboxAction, UberSandboxEvent
from app.models.venta import PagoVenta, Venta
from app.services import uber_finance_storage as storage
from app.services import uber_hosted_finance as finance
from app.services import uber_order_service as orders
from app.services import uber_pos_sandbox_service as pos


@pytest.fixture
def financial(db, monkeypatch):
    monkeypatch.setenv("JACARANDA_RUNTIME", "uber-pos-rehearsal")
    storage.seed(db)
    payload = json.loads(Path("scripts/fixtures/uber_pos_order.json").read_text())
    payload["order"]["carts"][0]["items"][1]["id"] = "jacaranda-sandbox-galleta"
    order_id = payload["order"]["id"]
    notice(db, order_id)
    requests = []

    def canonical(method, requested, **kwargs):
        requests.append((method, requested, kwargs))
        assert method == "GET" and requested == order_id and kwargs == {"include_payment": True}
        return copy.deepcopy(payload)

    monkeypatch.setattr(orders, "_request", canonical)
    return db, payload, requests


def notice(db, order_id, kind="orders.notification"):
    db.add(UberSandboxEvent(client_id=pos.TEST_CLIENT_ID, store_id=pos.TEST_STORE_ID,
        event_id=str(uuid4()), event_type=kind, order_id=order_id, event_time=int(datetime.now(timezone.utc).timestamp()),
        fingerprint="a" * 64, recibido_en=datetime.now(timezone.utc)))
    db.commit()


def submit(db, payload, action, **kwargs):
    oid = payload["order"]["id"]
    preview = finance.inspect_order(db, db, oid)[0]
    return finance.perform(db, db, oid, action=action, digest=preview["detalle_sha256"],
                           revision=preview["revision"], reviewed=True, **kwargs)


def test_canonical_import_replay_inventory_and_late_cancel_are_separate_from_cash(financial):
    db, payload, requests = financial
    first = submit(db, payload, "registrar")
    assert submit(db, payload, "registrar") == first | {"repetida": True}
    assert db.query(Venta).count() == db.query(PagoVenta).count() == 1
    assert db.query(MovimientoInventario).count() == 4
    assert [p.stock_actual for p in db.query(Producto).order_by(Producto.id)] == [98, 99]
    payload["order"]["state"] = "SUCCEEDED"
    result = submit(db, payload, "conciliar", reference="TEST-fictitious", gross="4.00", deductions="1.00", net="3.00")
    assert result["estado_externo"] == "ensayo_conciliado"
    data = finance.report(db, db)
    assert data["totales"]["neto_test"] == "3.00" and data["efectivo_caja"] == "0.00"
    assert data["pedidos"][0]["fuente"] == "Uber TEST"
    assert submit(db, payload, "conciliar", reference="TEST-fictitious", gross="4.00", deductions="1.00", net="3.00")["repetida"]
    notice(db, payload["order"]["id"], "orders.cancel")
    data = finance.report(db, db)
    assert data["totales"]["neto_test"] == "0.00" and data["totales"]["bruto_en_revision"] == "4.00"
    with pytest.raises(pos.RehearsalError):
        finance.ticket(db, db, first["venta_id"])
    submit(db, payload, "actualizar")
    assert db.query(MovimientoInventario).count() == 4
    assert db.query(PagoVenta).one().estado == "revision_pendiente"
    assert all(method == "GET" for method, *_ in requests)


@pytest.mark.parametrize("change", ["event", "price", "state", "foreign_store"])
def test_changed_preview_never_writes(financial, change):
    db, payload, _ = financial
    oid = payload["order"]["id"]
    preview = finance.inspect_order(db, db, oid)[0]
    if change == "event":
        notice(db, oid, "orders.customer_order_edit")
    elif change == "price":
        payload["order"]["payment"]["payment_detail"]["order_total"]["gross"]["amount_e5"] += 100000
    elif change == "state":
        payload["order"]["state"] = "FAILED"
    else:
        payload["order"]["store"]["id"] = str(uuid4())
    with pytest.raises(pos.RehearsalError):
        finance.perform(db, db, oid, action="registrar", digest=preview["detalle_sha256"], revision=0, reviewed=True)
    assert db.query(Venta).count() == db.query(MovimientoInventario).count() == 0


def test_unsigned_unknown_order_cannot_be_queried(financial):
    db, _, calls = financial
    with pytest.raises(pos.RehearsalError, match="autentica"):
        finance.inspect_order(db, db, str(uuid4()))
    assert calls == []


@pytest.mark.parametrize("state", ["enviando", "incierta"])
@pytest.mark.parametrize("settled", [False, True])
def test_pending_uber_action_blocks_ticket_and_moves_finances_to_review_without_writes(financial, state, settled):
    db, payload, _ = financial
    first = submit(db, payload, "registrar")
    if settled:
        payload["order"]["state"] = "SUCCEEDED"
        submit(db, payload, "conciliar", reference="TEST-pending", gross="4.00", deductions="1.00", net="3.00")
    sale = db.get(Venta, first["venta_id"])
    original = sale.pago_externo_payload
    db.add(UberSandboxAction(client_id=pos.TEST_CLIENT_ID, store_id=pos.TEST_STORE_ID,
        order_id=payload["order"]["id"], request_key=str(uuid4()), fingerprint="a" * 64,
        action="cancelar", estado=state, creado_en=datetime.now(timezone.utc)))
    db.commit()
    with pytest.raises(pos.RehearsalError, match="pendiente"):
        finance.inspect_order(db, db, sale.pago_externo_id)
    with pytest.raises(pos.RehearsalError, match="revisar"):
        finance.ticket(db, db, sale.id)
    report = finance.report(db, db)
    assert report["pedidos"][0]["estado"] == "revision_pendiente"
    assert report["pedidos"][0]["motivos"] == ["accion_uber_por_confirmar"]
    assert report["totales"]["bruto_en_revision"] == "4.00"
    for key in ("bruto_por_conciliar", "bruto_conciliado_test", "deducciones_test", "neto_test"):
        assert report["totales"][key] == "0.00"
    assert report["efectivo_caja"] == "0.00"
    assert sale.pago_externo_payload == original
    assert db.query(MovimientoInventario).count() == 4
    assert db.query(PagoVenta).count() == 1


def test_explicit_synthetic_exercise_has_no_provider_request_and_survives_replay(financial):
    db, _, calls = financial
    key = uuid4()
    result = finance.exercise(db, key, True)
    assert result["completa"] and calls == []
    repeated = finance.exercise(db, key, True)
    assert repeated["repetida"] and repeated["completa"]
    data = finance.report(db, db)
    assert data["pedidos"][0]["fuente"] == "Simulacion interna"
    assert data["totales"]["bruto_en_revision"] == "4.00" and data["movimientos"] == 4
    before = [item.stock_actual for item in db.query(Producto).order_by(Producto.id)]
    storage.seed(db)
    assert before == [item.stock_actual for item in db.query(Producto).order_by(Producto.id)]


def configure(monkeypatch):
    monkeypatch.setenv("JACARANDA_RUNTIME", "uber-sandbox")
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "uber-sandbox")
    monkeypatch.setenv("JACARANDA_SANDBOX_DATABASE_HOST", "test-db.railway.internal")
    for flag in ("UBER_EATS_SANDBOX_FINANCE_ENABLED", "UBER_EATS_SANDBOX_ENABLED", "UBER_EATS_SANDBOX_MANAGEMENT_ENABLED"):
        monkeypatch.setattr(settings, flag, True)
    monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_CLIENT_ID", pos.TEST_CLIENT_ID)
    monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_STORE_ID", pos.TEST_STORE_ID)
    monkeypatch.setattr(settings, "DATABASE_URL", "postgresql://jacaranda_sandbox:test@test-db.railway.internal/jacaranda_uber_sandbox")


@pytest.mark.parametrize("unsafe", ["runtime", "environment", "host", "database", "user", "query", "flag", "store", "app"])
def test_configuration_rejects_every_escape_before_connecting(monkeypatch, unsafe):
    configure(monkeypatch)
    storage.validate_configuration()
    if unsafe == "runtime":
        monkeypatch.setenv("JACARANDA_RUNTIME", "production")
    elif unsafe == "environment":
        monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")
    elif unsafe in {"host", "database", "user", "query"}:
        replacements = {"host": ("test-db.railway.internal", "production.railway.internal"),
                        "database": ("/jacaranda_uber_sandbox", "/railway"),
                        "user": ("jacaranda_sandbox:", "postgres:"), "query": ("/jacaranda_uber_sandbox", "/jacaranda_uber_sandbox?options=-csearch_path=public")}
        a, b = replacements[unsafe]
        monkeypatch.setattr(settings, "DATABASE_URL", settings.DATABASE_URL.replace(a, b))
    elif unsafe == "flag":
        monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_FINANCE_ENABLED", False)
    else:
        monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_" + ("STORE_ID" if unsafe == "store" else "CLIENT_ID"), "real-not-allowed")
    with pytest.raises(pos.RehearsalError):
        storage.validate_configuration()


def test_sqlite_cannot_masquerade_as_hosted_finance(db, monkeypatch):
    configure(monkeypatch)
    with pytest.raises(pos.RehearsalError):
        pos.validate_database(db)


def test_unknown_action_never_queries_provider(financial):
    db, payload, calls = financial
    with pytest.raises(pos.RehearsalError, match="no permitida"):
        finance.perform(db, db, payload["order"]["id"], action="delete", digest="a" * 64,
                        revision=0, reviewed=True)
    assert calls == [] and db.query(Venta).count() == 0


def test_route_validates_exact_confirmation_and_decimal_contract(financial, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes import uber_sandbox_finance as routes

    db, payload, _ = financial
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes.enabled] = lambda: None
    app.dependency_overrides[routes.get_db] = lambda: db
    app.dependency_overrides[storage.get_db] = lambda: db
    client = TestClient(app)
    base = "/api/v1/uber-eats/sandbox/finanzas"
    oid = payload["order"]["id"]
    preview = client.post(f"{base}/pedidos/{oid}/consultar").json()
    body = {"accion": "registrar", "detalle_sha256": preview["detalle_sha256"], "revision": 0,
            "solo_sandbox_confirmado": True}
    for change in ({"solo_sandbox_confirmado": "true"}, {"revision": "0"}, {"bruto": 4.0},
                   {"bruto": "4.001"}, {"accion": "delete"}, {"store_id": "production"}):
        assert client.post(f"{base}/pedidos/{oid}/accion", json=body | change).status_code == 422
    assert client.post(f"{base}/pedidos/{oid}/accion", json=body | {"solo_sandbox_confirmado": False}).status_code == 409
    assert db.query(Venta).count() == 0
    result = client.post(f"{base}/pedidos/{oid}/accion", json=body)
    assert result.status_code == 200
    assert client.get(f"{base}/ventas/{result.json()['venta_id']}/ticket").status_code == 200
    assert client.get(base).json()["efectivo_caja"] == "0.00"
