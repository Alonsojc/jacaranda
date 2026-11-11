"""Regressions from the November operational review; no provider calls."""

import csv
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

import pytest
from pydantic import ValidationError
from sqlalchemy import event

from app.core.time_utils import operation_today
from app.models.inventario import Producto
from app.models.pedido import Pedido, DetallePedido, EstadoPedido
from app.models.venta import Venta, CorteCaja, EstadoVenta
from app.schemas.pedido import PedidoResponse
from app.schemas.venta import VentaCreate, CorteCajaCreate
from app.services import pedido_service, venta_service


@pytest.fixture
def product(db):
    row = Producto(codigo="REVIEW", nombre="Prueba", precio_unitario=100,
                   precio_cdmx=140, precio_uber_eats=150, stock_actual=100)
    db.add(row)
    db.commit()
    return row


def payload(product, **extra):
    return {"detalles": [{"producto_id": product.id, "cantidad": 1}],
            "monto_recibido": "100", **extra}


@pytest.mark.parametrize("cash,card,change,applied", [
    ("50", "60", "10", "40"), ("100", "100", "100", "0"),
    ("100", "0", "0", "100"), ("140", "0", "40", "100"),
])
def test_split_change_is_not_revenue(db, admin_user, product, cash, card, change, applied):
    payments = [{"metodo_pago": "01", "terminal": "efectivo", "monto": cash}]
    if Decimal(card):
        payments.append({"metodo_pago": "28", "terminal": "bbva", "monto": card})
    sale = venta_service.procesar_venta(db, VentaCreate(**payload(product, pagos=payments)), admin_user.id)
    summary = venta_service.resumen_corte_caja(db)
    assert sale.total == Decimal("100")
    assert sale.cambio == Decimal(change)
    assert sum(p.monto for p in sale.pagos) == sale.total
    assert summary["total_ventas"] == sale.total
    assert summary["total_ventas_efectivo"] == Decimal(applied)
    assert summary["total_ventas_bbva"] == Decimal(card)


def test_split_rejects_overpaid_card_without_creating_sale(db, admin_user, product):
    with pytest.raises(ValueError, match="sin efectivo"):
        venta_service.procesar_venta(db, VentaCreate(**payload(product, pagos=[
            {"metodo_pago": "28", "terminal": "bbva", "monto": 101},
        ])), admin_user.id)
    db.rollback()
    assert db.query(Venta).count() == 0
    assert db.get(Producto, product.id).stock_actual == 100


def test_split_reports_and_bank_reconcile_only_applied_amount(client, auth_headers, product):
    response = client.post("/api/v1/punto-de-venta/ventas", headers=auth_headers, json=payload(product, pagos=[
        {"metodo_pago": "01", "terminal": "efectivo", "monto": 50},
        {"metodo_pago": "28", "terminal": "bbva", "monto": 60},
    ]))
    assert response.status_code == 201
    today = operation_today()
    report = client.get(f"/api/v1/reportes/ventas?fecha_inicio={today}&fecha_fin={today}", headers=auth_headers).json()
    assert report["por_metodo_pago"]["efectivo"]["total"] == 40
    assert report["por_metodo_pago"]["bbva"]["total"] == 60
    bank = client.get(f"/api/v1/contabilidad/banco/conciliacion?mes={today.month}&anio={today.year}", headers=auth_headers).json()
    assert bank["saldo_sistema"] == 60


def test_history_filters_before_paginating_and_csv_uses_the_same_filter(db, admin_user, client, auth_headers):
    db.add_all([
        Venta(folio="MATCH-1",usuario_id=admin_user.id,subtotal=10,total=10,metodo_pago="01"),
        Venta(folio="OTHER-1",usuario_id=admin_user.id,subtotal=20,total=20,metodo_pago="28"),
        Venta(folio="MATCH-2",usuario_id=admin_user.id,subtotal=30,total=30,metodo_pago="01",estado=EstadoVenta.CANCELADA),
    ])
    db.commit()
    period=f"fecha_inicio={operation_today()}&fecha_fin={operation_today()}&buscar=MATCH&metodo=01"
    base="/api/v1/punto-de-venta/ventas/historial"
    rows=client.get(base+"?"+period,headers=auth_headers).json()
    assert rows["total"] == 2 and rows["total_cobrado"] == "10.00"
    csv_result=client.get(base+"/csv?"+period,headers=auth_headers).text
    assert "MATCH-1" in csv_result and "MATCH-2" in csv_result and "OTHER-1" not in csv_result


def test_offline_canal_expected_total_and_collection_time(db, admin_user, product):
    collected = datetime.now(timezone.utc)
    data = VentaCreate(**payload(product, canal="cdmx", monto_recibido=140,
                                total_esperado=140, fecha_cobro_local=collected,
                                idempotency_key="review-offline"))
    sale = venta_service.procesar_venta(db, data, admin_user.id)
    assert (sale.canal, sale.total) == ("cdmx", Decimal("140"))
    assert sale.fecha_cobro_local.replace(tzinfo=timezone.utc) == collected
    assert sale.fecha >= sale.fecha_cobro_local
    replay = venta_service.procesar_venta(db, data.model_copy(update={
        "fecha_cobro_local": collected - timedelta(days=2),
    }), admin_user.id)
    assert replay.id == sale.id
    assert db.query(Venta).count() == 1


@pytest.mark.parametrize("changes,reason", [
    ({"canal": "cdmx", "total_esperado": 100}, "no coincide"),
    ({"fecha_cobro_local": datetime.now(timezone.utc) - timedelta(days=2)}, "otro dia"),
    ({"fecha_cobro_local": datetime.now(timezone.utc) + timedelta(days=1)}, "futura"),
])
def test_offline_rejection_preserves_inventory_and_does_not_post_to_other_shift(
    db, admin_user, product, changes, reason,
):
    with pytest.raises(venta_service.VentaRequiereRevision, match=reason):
        venta_service.procesar_venta(db, VentaCreate(**payload(product, **changes)), admin_user.id)
    db.rollback()
    assert db.query(Venta).count() == 0
    assert db.get(Producto, product.id).stock_actual == 100


def test_local_collection_after_closed_shift_is_not_backdated(db, admin_user, product):
    now = datetime.now(timezone.utc)
    zero = Decimal("0")
    cut = CorteCaja(usuario_id=admin_user.id, fecha=now, periodo_fin=now,
                    fondo_inicial=zero, total_ventas_efectivo=zero, total_ventas_tarjeta=zero,
                    total_ventas_transferencia=zero, total_ventas=zero, efectivo_esperado=zero,
                    efectivo_real=zero, diferencia=zero, numero_ventas=0)
    db.add(cut)
    db.commit()
    with pytest.raises(venta_service.VentaRequiereRevision, match="ya cerro"):
        venta_service.procesar_venta(db, VentaCreate(**payload(product, fecha_cobro_local=now)), admin_user.id)
    db.rollback()
    assert db.query(Venta).count() == 0
    assert db.get(CorteCaja, cut.id).total_ventas == zero


def test_collection_time_requires_timezone():
    with pytest.raises(ValidationError, match="zona horaria"):
        VentaCreate(detalles=[{"producto_id": 1, "cantidad": 1}], fecha_cobro_local="2026-11-10T12:00:00")


def test_api_returns_conflict_for_price_review(client, auth_headers, product):
    result = client.post("/api/v1/punto-de-venta/ventas", headers=auth_headers,
                         json=payload(product, total_esperado=99))
    assert result.status_code == 409


def test_order_51_stays_visible_and_calendar_is_independent(db, client, auth_headers):
    today = operation_today()
    db.add_all([Pedido(folio=f"OLD-{i}", cliente_nombre="Anterior", fecha_entrega=today-timedelta(days=1),
                       estado=EstadoPedido.ENTREGADO) for i in range(50)])
    db.add_all([Pedido(folio=f"CURRENT-{i}", cliente_nombre="Actual", fecha_entrega=today)
                for i in range(30)])
    db.commit()
    page = client.get("/api/v1/pedidos/bandeja", headers=auth_headers).json()
    assert page["total"] == 30
    assert len(page["items"]) == 25
    assert page["hoy"] == page["semana"] == 30
    second = client.get("/api/v1/pedidos/bandeja?pagina=2", headers=auth_headers).json()
    assert len(second["items"]) == 5
    assert {p["id"] for p in page["items"]}.isdisjoint(p["id"] for p in second["items"])
    search = client.get("/api/v1/pedidos/bandeja?buscar=CURRENT-29", headers=auth_headers).json()
    assert search["total"] == 1
    assert search["items"][0]["folio"] == "CURRENT-29"
    calendar = client.get(f"/api/v1/pedidos/calendario?desde={today}&hasta={today}", headers=auth_headers)
    assert len(calendar.json()) == 30


@pytest.mark.parametrize("count", [1, 50])
def test_order_read_queries_are_batched(db, count):
    for i in range(count):
        pedido = Pedido(folio=f"BATCH-{i}", cliente_nombre="Prueba", fecha_entrega=operation_today())
        pedido.detalles.append(DetallePedido(descripcion="Producto", cantidad=1, precio_unitario=1))
        db.add(pedido)
    db.commit()
    db.expunge_all()
    reads = []
    def record(_conn, _cursor, sql, _params, _context, _many):
        if sql.lstrip().upper().startswith("SELECT"):
            reads.append(sql)
    event.listen(db.get_bind(), "before_cursor_execute", record)
    try:
        rows = pedido_service.listar_pedidos(db)
        assert len([PedidoResponse.model_validate(row) for row in rows]) == count
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", record)
    assert len(reads) == 2


def test_history_paginates_searches_and_exports_all_501(db, admin_user, client, auth_headers):
    now = datetime.now(timezone.utc)
    for i in range(501):
        db.add(Venta(folio=f"H-{i:04}", usuario_id=admin_user.id, subtotal=1, total=1, fecha=now))
    db.add(Venta(folio="UNPAID", usuario_id=admin_user.id, subtotal=80, total=80,
                 fecha=now, estado=EstadoVenta.PENDIENTE))
    db.commit()
    period = f"fecha_inicio={operation_today()}&fecha_fin={operation_today()}"
    url = "/api/v1/punto-de-venta/ventas/historial"
    data = client.get(url+"?"+period, headers=auth_headers).json()
    assert data["total"] == 502 and len(data["items"]) == 25
    assert data["total_cobrado"] == "501.00" and data["completadas"] == 501
    search = client.get(url+"?"+period+"&buscar=H-0000", headers=auth_headers).json()
    assert search["total"] == 1 and search["items"][0]["folio"] == "H-0000"
    exported = client.get(url+"/csv?"+period, headers=auth_headers)
    assert exported.status_code == 200
    lines = list(csv.reader(StringIO(exported.content.decode("utf-8-sig"))))
    assert len(lines) == 503
    assert any(row[0] == "H-0000" for row in lines)
    assert any(row[-1] == "pendiente" for row in lines)


def test_cut_view_calculates_once(db, client, auth_headers):
    with patch.object(venta_service, "_totales_corte", wraps=venta_service._totales_corte) as calculate:
        result = client.get("/api/v1/punto-de-venta/corte-caja/vista", headers=auth_headers)
    assert result.status_code == 200
    assert calculate.call_count == 1
    assert result.json()["ventas"] == []
    assert result.json()["resumen"]["entrega_efectivo_disponible"] is True


def test_cut_cannot_close_over_an_unresolved_clip_attempt(db, admin_user, product):
    venta_service.procesar_venta(db, VentaCreate(**payload(
        product, metodo_pago="28", terminal="clip", pago_integrado=True,
    )), admin_user.id)
    assert venta_service.resumen_corte_caja(db)["cobros_pendientes"] == 1
    with pytest.raises(ValueError, match="CLIP pendientes"):
        venta_service.realizar_corte_caja(db, CorteCajaCreate(fondo_inicial=0, efectivo_real=0), admin_user.id)
    db.rollback()
    assert db.query(CorteCaja).count() == 0


def test_traceability_list_is_available_and_protected(client, auth_headers):
    assert client.get("/api/v1/calidad/trazabilidad").status_code == 401
    response = client.get("/api/v1/calidad/trazabilidad", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_readiness_does_not_claim_ready_when_database_fails(client):
    assert client.get("/ready").json() == {"status": "ready"}
    with patch("main.engine.connect", side_effect=RuntimeError("private connection details")):
        response = client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert client.get("/health").status_code == 200
