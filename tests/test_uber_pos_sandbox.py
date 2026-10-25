"""A disposable POS ledger; no production routes, OAuth or real payments."""

import copy
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.auditoria import LogAuditoria
from app.models.inventario import Ingrediente, MovimientoInventario, Producto, UnidadMedida
from app.models.venta import DetalleVenta, EstadoVenta, MetodoPago, PagoVenta, Venta
from app.services import uber_order_service as orders
from app.services import uber_pos_sandbox_service as pos
from app.services.venta_service import resumen_corte_caja


FIXTURE = Path(__file__).parents[1] / "scripts/fixtures/uber_pos_order.json"


@pytest.fixture(autouse=True)
def rehearsal_mode(monkeypatch):
    monkeypatch.setenv("JACARANDA_RUNTIME", "uber-pos-rehearsal")


@pytest.fixture
def payload():
    return json.loads(FIXTURE.read_text())


@pytest.fixture
def catalog(db, admin_user):
    box = Ingrediente(nombre="Caja ficticia", unidad_medida=UnidadMedida.CAJA, es_empaque=True,
                      stock_actual=Decimal(20), stock_minimo=Decimal(0), costo_unitario=Decimal(1))
    db.add(box)
    db.flush()
    products = [Producto(codigo="UBER-FICTICIO-" + str(index), nombre=name,
                         precio_unitario=Decimal(99), precio_uber_eats=Decimal(88), stock_actual=Decimal(10),
                         caja_ingrediente_id=box.id, caja_cantidad=Decimal(1))
                for index, name in enumerate(("Brownie de ensayo", "Galleta de ensayo"))]
    db.add_all(products)
    db.commit()
    return {"jacaranda-sandbox-brownie": products[0].id, "jacaranda-sandbox-cookie": products[1].id}


def import_sale(db, payload, catalog, admin_user, **kwargs):
    return pos.import_order(db, payload, catalog, admin_user.id, client_id=pos.TEST_CLIENT_ID,
                            retrieved_at=kwargs.pop("retrieved_at", datetime.now(timezone.utc)),
                            reviewed=kwargs.pop("reviewed", True), **kwargs)


def counts(db):
    return tuple(db.query(model).count() for model in (Venta, DetalleVenta, PagoVenta, MovimientoInventario, LogAuditoria))


def money(net, tax=0):
    return {"net": {"amount_e5": net, "currency_code": "MXN"},
            "tax": {"amount_e5": tax, "currency_code": "MXN"},
            "gross": {"amount_e5": net + tax, "currency_code": "MXN"}}


def test_one_pending_sale_reuses_stock_packaging_ticket_and_audit(db, payload, catalog, admin_user):
    result = import_sale(db, payload, catalog, admin_user)
    sale = db.get(Venta, result["venta_id"])
    assert result["repetida"] is False and sale.serie == "US"
    assert sale.total == Decimal("4.00") and sale.subtotal == Decimal("4.00")
    assert sale.estado == EstadoVenta.PENDIENTE and sale.metodo_pago == MetodoPago.POR_DEFINIR
    assert sale.monto_recibido == 0 and sale.cambio == 0 and sale.facturada is False
    assert sale.pago_integrado is False and sale.pago_proveedor == pos.PROVIDER
    assert [detail.precio_unitario for detail in sale.detalles] == [Decimal("1.00"), Decimal("2.00")]
    assert [db.get(Producto, product_id).stock_actual for product_id in catalog.values()] == [8, 9]
    assert db.query(Ingrediente).one().stock_actual == 17
    assert db.query(MovimientoInventario).count() == 4
    assert db.query(LogAuditoria).filter_by(accion="importar_uber_sandbox").count() == 1
    assert db.query(PagoVenta).one().estado == "por_conciliar"
    assert db.query(PagoVenta).one().terminal is None
    assert json.loads(sale.pago_externo_payload)["order"]["cash_due"] is None
    ticket = pos.rehearsal_ticket(db, sale.id)
    assert ticket["total"] == "$4.00" and "Sin cobro real" in ticket["leyenda_fiscal"]
    assert "Sin nueces" in ticket["instrucciones_articulos"][0]
    assert "Revisar etiqueta" in ticket["instrucciones"]
    cut = resumen_corte_caja(db)
    assert cut["numero_ventas"] == 0
    assert cut["total_ventas"] == 0 and cut["efectivo_esperado_base"] == 0


def test_replay_in_another_session_never_repeats_stock_sale_or_payment(db, payload, catalog, admin_user):
    first = import_sale(db, payload, catalog, admin_user)
    before = counts(db)
    with Session(bind=db.get_bind()) as other:
        result = pos.import_order(other, payload, catalog, admin_user.id, client_id=pos.TEST_CLIENT_ID,
                                  retrieved_at=datetime.now(timezone.utc) - timedelta(days=2), reviewed=True)
    assert result == first | {"repetida": True}
    assert counts(db) == before
    assert db.get(Producto, catalog["jacaranda-sandbox-brownie"]).stock_actual == 8
    assert db.query(Ingrediente).one().stock_actual == 17


def test_replay_after_uncertain_commit_returns_same_sale(db, payload, catalog, admin_user):
    original = db.commit

    def committed_but_connection_lost():
        original()
        raise RuntimeError("synthetic lost acknowledgement")

    with patch.object(db, "commit", side_effect=committed_but_connection_lost), pytest.raises(RuntimeError):
        import_sale(db, payload, catalog, admin_user)
    assert db.query(Venta).count() == 1
    result = import_sale(db, payload, catalog, admin_user)
    assert result["repetida"] is True and db.query(MovimientoInventario).count() == 4


@pytest.mark.parametrize("change", ["title", "allergy", "mapping"])
def test_changed_order_or_mapping_requires_review_without_second_movement(db, payload, catalog, admin_user, change):
    import_sale(db, payload, catalog, admin_user)
    before = counts(db)
    if change == "title":
        payload["order"]["carts"][0]["items"][0]["title"] = "Cambio de articulo"
    elif change == "allergy":
        payload["order"]["carts"][0]["items"][0]["customer_request"]["allergy"] = "Nueva alergia"
    else:
        catalog["jacaranda-sandbox-brownie"] = catalog["jacaranda-sandbox-cookie"]
    with pytest.raises(pos.RehearsalError, match="revision"):
        import_sale(db, payload, catalog, admin_user)
    assert counts(db) == before


def test_state_progress_does_not_reimport_or_claim_cash_settlement(db, payload, catalog, admin_user):
    first = import_sale(db, payload, catalog, admin_user)
    payload["order"]["state"] = "SUCCEEDED"
    assert import_sale(db, payload, catalog, admin_user)["repetida"] is True
    sale = db.get(Venta, first["venta_id"])
    assert sale.estado == EstadoVenta.PENDIENTE and sale.monto_recibido == 0
    assert db.query(PagoVenta).one().estado == "por_conciliar"


def test_cancellation_never_automatically_returns_food_or_packaging(db, payload, catalog, admin_user):
    import_sale(db, payload, catalog, admin_user)
    before = counts(db)
    payload["order"]["state"] = "FAILED"
    with pytest.raises(pos.RehearsalError, match="fallido"):
        import_sale(db, payload, catalog, admin_user)
    assert counts(db) == before and db.query(Ingrediente).one().stock_actual == 17


@pytest.mark.parametrize("mode", ["stock", "packaging", "inactive", "missing", "mapping"])
def test_unavailable_catalog_rolls_back_everything(db, payload, catalog, admin_user, mode):
    product = db.get(Producto, catalog["jacaranda-sandbox-cookie"])
    if mode == "stock":
        product.stock_actual = 0
    elif mode == "packaging":
        db.query(Ingrediente).one().stock_actual = 2
    elif mode == "inactive":
        product.activo = False
    elif mode == "missing":
        catalog["jacaranda-sandbox-cookie"] = 999999
    else:
        del catalog["jacaranda-sandbox-cookie"]
    db.commit()
    before = counts(db)
    with pytest.raises((pos.RehearsalError, ValueError)):
        import_sale(db, payload, catalog, admin_user)
    assert counts(db) == before
    assert db.get(Producto, catalog["jacaranda-sandbox-brownie"]).stock_actual == 10


def test_failure_after_first_stock_write_is_atomic(db, payload, catalog, admin_user):
    before = counts(db)
    with patch.object(pos, "registrar_empaque_producto", side_effect=RuntimeError("synthetic failure")), pytest.raises(RuntimeError):
        import_sale(db, payload, catalog, admin_user)
    assert counts(db) == before
    assert [db.get(Producto, product_id).stock_actual for product_id in catalog.values()] == [10, 10]
    assert db.query(Ingrediente).one().stock_actual == 20


def test_contacts_and_payment_credentials_are_not_retained(db, payload, catalog, admin_user):
    payload["order"]["customers"] = [{"phone": "do-not-retain-contact"}]
    payload["order"]["support_contact"] = {"email": "do-not-retain-support"}
    payload["order"]["payment"]["token"] = "do-not-retain-token"
    import_sale(db, payload, catalog, admin_user)
    sale = db.query(Venta).one()
    assert "do-not-retain" not in sale.pago_externo_payload
    assert "do-not-retain" not in sale.notas


def test_explicit_line_discounts_preserve_uber_totals_and_inventory(db, payload, catalog, admin_user):
    payment = payload["order"]["payment"]["payment_detail"]
    payment["item_charges"]["price_breakdown"][0]["discount"] = {"total": money(100000)}
    payment["item_charges"]["subtotal_including_promos"] = money(300000)
    payment["order_total"] = money(300000)
    payment["promotions"]["total"] = money(100000)
    import_sale(db, payload, catalog, admin_user)
    sale = db.query(Venta).one()
    assert sale.total == Decimal("3.00") and sale.descuento == Decimal("1.00")
    assert sale.detalles[0].precio_unitario == 1 and sale.detalles[0].subtotal == 1
    assert sale.detalles[0].descuento == 1
    assert db.get(Producto, catalog["jacaranda-sandbox-brownie"]).stock_actual == 8


def test_explicit_tax_is_preserved_not_recalculated_from_current_catalog(db, payload, catalog, admin_user):
    payment = payload["order"]["payment"]["payment_detail"]
    payment["item_charges"]["total"] = money(400000, 64000)
    payment["order_total"] = money(400000, 64000)
    for price in payment["item_charges"]["price_breakdown"]:
        price["total"] = money(200000, 32000)
        price["unit"] = money(100000, 16000) if price["quantity"]["amount"] == 2 else money(200000, 32000)
    import_sale(db, payload, catalog, admin_user)
    sale = db.query(Venta).one()
    assert sale.total == Decimal("4.64") and sale.total_impuestos == Decimal("0.64")
    assert all(detail.tasa_iva == Decimal("0.16") for detail in sale.detalles)
    assert sale.estado == EstadoVenta.PENDIENTE and sale.facturada is False


def test_two_source_items_mapped_to_one_product_consume_combined_quantity_once(db, payload, catalog, admin_user):
    catalog["jacaranda-sandbox-cookie"] = catalog["jacaranda-sandbox-brownie"]
    import_sale(db, payload, catalog, admin_user)
    assert db.get(Producto, catalog["jacaranda-sandbox-brownie"]).stock_actual == 7
    assert db.query(MovimientoInventario).count() == 2
    assert db.query(Ingrediente).one().stock_actual == 17


@pytest.mark.parametrize("path,value", [
    (("payment",), None), (("payment", "payment_detail"), []),
    (("payment", "payment_detail", "item_charges"), None),
    (("payment", "payment_detail", "fees"), None),
    (("payment", "payment_detail", "promotions"), []),
])
def test_malformed_financial_shapes_have_controlled_errors(payload, path, value):
    target = payload["order"]
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    with pytest.raises(pos.RehearsalError):
        pos.plan_order(payload, client_id=pos.TEST_CLIENT_ID)


@pytest.mark.parametrize("state", ["OFFERED", "CREATED", "FAILED", "UNKNOWN", None, [], {}])
def test_unaccepted_or_failed_orders_are_blocked(db, payload, catalog, admin_user, state):
    payload["order"]["state"] = state
    with pytest.raises(pos.RehearsalError):
        import_sale(db, payload, catalog, admin_user)
    assert db.query(Venta).count() == 0


@pytest.mark.parametrize("age", [timedelta(minutes=3), timedelta(seconds=-10)])
def test_new_sale_requires_fresh_details(db, payload, catalog, admin_user, age):
    with pytest.raises(pos.RehearsalError, match="reciente"):
        import_sale(db, payload, catalog, admin_user, retrieved_at=datetime.now(timezone.utc) - age)
    assert db.query(Venta).count() == 0


def test_explicit_review_required(db, payload, catalog, admin_user):
    with pytest.raises(pos.RehearsalError, match="Revisa"):
        import_sale(db, payload, catalog, admin_user, reviewed=False)
    assert db.query(MovimientoInventario).count() == 0


@pytest.mark.parametrize("runtime", ["uber-sandbox", "production", "", "pos"])
def test_deployed_runtimes_cannot_import(db, payload, catalog, admin_user, monkeypatch, runtime):
    monkeypatch.setenv("JACARANDA_RUNTIME", runtime)
    with pytest.raises(pos.RehearsalError, match="desplegados"):
        import_sale(db, payload, catalog, admin_user)
    assert db.query(Venta).count() == 0


def test_file_database_is_refused_before_connecting(tmp_path):
    path = tmp_path / "must-not-exist.db"
    engine = create_engine("sqlite:///" + str(path))
    try:
        with Session(bind=engine) as db, pytest.raises(pos.RehearsalError, match="desechable"):
            pos.validate_database(db)
        assert not path.exists()
    finally:
        engine.dispose()


def test_alternate_model_bind_is_refused(db):
    other_engine = create_engine("sqlite://")
    try:
        with Session(bind=db.get_bind(), binds={Producto: other_engine}) as mixed, pytest.raises(pos.RehearsalError, match="misma base"):
            pos.validate_database(mixed)
    finally:
        other_engine.dispose()


def test_pending_caller_changes_are_not_committed(db, payload, catalog, admin_user):
    product = db.get(Producto, catalog["jacaranda-sandbox-brownie"])
    product.nombre = "Cambio ajeno pendiente"
    with pytest.raises(pos.RehearsalError, match="cambios pendientes"):
        import_sale(db, payload, catalog, admin_user)
    assert db.is_modified(product)
    db.rollback()
    assert product.nombre == "Brownie de ensayo"


@pytest.mark.parametrize("value", [True, "100000", float("nan"), float("inf"), -100000, 1, 10**30])
def test_invalid_or_subcent_money_is_never_rounded_into_a_sale(payload, value):
    payload["order"]["payment"]["payment_detail"]["item_charges"]["total"]["gross"]["amount_e5"] = value
    with pytest.raises(pos.RehearsalError):
        pos.plan_order(payload, client_id=pos.TEST_CLIENT_ID)


@pytest.mark.parametrize("change", ["currency", "total", "duplicate", "missing_price", "modifier", "weight", "cash", "fee", "global_promo"])
def test_ambiguous_data_is_blocked_instead_of_guessed(payload, change):
    order = payload["order"]
    payment = order["payment"]["payment_detail"]
    item = order["carts"][0]["items"][0]
    prices = payment["item_charges"]["price_breakdown"]
    if change == "currency":
        payment["currency_code"] = "USD"
    elif change == "total":
        payment["order_total"]["gross"]["amount_e5"] += 100000
    elif change == "duplicate":
        prices.append(copy.deepcopy(prices[0]))
    elif change == "missing_price":
        prices.pop()
    elif change == "modifier":
        item["selected_modifier_groups"] = [{"id": "extra", "selected_items": [{"id": "extra-item"}]}]
    elif change == "weight":
        item["quantity"] = {"amount": 2, "unit": "KILOGRAM"}
    elif change == "cash":
        payment["cash_amount_due"] = copy.deepcopy(payment["order_total"])
    elif change == "fee":
        payment["fees"]["total"] = copy.deepcopy(payment["order_total"])
    else:
        payment["promotions"]["total"] = copy.deepcopy(payment["order_total"])
    with pytest.raises(pos.RehearsalError):
        pos.plan_order(payload, client_id=pos.TEST_CLIENT_ID)


@pytest.mark.parametrize("store", [None, [], {"id": "d757be8e-a500-5e80-a148-8e7182329641"}])
def test_live_or_malformed_store_cannot_be_imported(payload, store):
    payload["order"]["store"] = store
    with pytest.raises(pos.RehearsalError):
        pos.plan_order(payload, client_id=pos.TEST_CLIENT_ID)


def test_only_canonical_test_get_is_requested_after_local_isolation_check(db, payload, monkeypatch):
    monkeypatch.setattr(orders, "sandbox_identity", lambda: (pos.TEST_CLIENT_ID, pos.TEST_STORE_ID))
    with patch.object(orders, "_request", return_value=payload) as network:
        result, observed = pos.read_test_order(db, UUID(payload["order"]["id"]))
    network.assert_called_once_with("GET", payload["order"]["id"], include_payment=True)
    assert result == payload and observed.tzinfo is not None


def test_remote_reader_never_runs_in_a_deployed_runtime(db, monkeypatch):
    monkeypatch.setenv("JACARANDA_RUNTIME", "uber-sandbox")
    with patch.object(orders, "_request") as network, pytest.raises(pos.RehearsalError):
        pos.read_test_order(db, UUID("6bb26a4a-0c21-4554-8d94-cbf248884bdb"))
    network.assert_not_called()


def test_remote_reader_checks_order_store_before_returning_data(db, payload, monkeypatch):
    monkeypatch.setattr(orders, "sandbox_identity", lambda: (pos.TEST_CLIENT_ID, pos.TEST_STORE_ID))
    order_id = UUID(payload["order"]["id"])
    payload["order"]["store"]["id"] = "d757be8e-a500-5e80-a148-8e7182329641"
    with patch.object(orders, "_request", return_value=payload), pytest.raises(pos.RehearsalError):
        pos.read_test_order(db, order_id)


def test_equivalent_explicit_zero_discount_is_an_idempotent_replay(db, payload, catalog, admin_user):
    import_sale(db, payload, catalog, admin_user)
    payload["order"]["payment"]["payment_detail"]["item_charges"]["price_breakdown"][0]["discount"] = {"total": money(0)}
    assert import_sale(db, payload, catalog, admin_user)["repetida"] is True
    assert db.query(Venta).count() == 1 and db.query(MovimientoInventario).count() == 4


def test_inactive_operator_cannot_replay_a_sale(db, payload, catalog, admin_user):
    import_sale(db, payload, catalog, admin_user)
    admin_user.activo = False
    db.commit()
    with pytest.raises(pos.RehearsalError, match="operador"):
        import_sale(db, payload, catalog, admin_user)
    assert db.query(Venta).count() == 1
