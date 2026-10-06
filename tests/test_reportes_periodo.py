"""Periodos operativos, egresos registrados y costo de consultas."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import event

from app.core.config import settings
from app.models.egreso import Egreso
from app.models.gasto_fijo import GastoFijo
from app.models.venta import EstadoVenta, MetodoPago, PagoVenta, TerminalPago, Venta
from app.services.reportes_service import reporte_egresos_periodo, reporte_ventas_periodo


def _venta(db, usuario_id, folio, fecha, total="100", estado=EstadoVenta.COMPLETADA):
    venta = Venta(
        usuario_id=usuario_id, folio=folio, fecha=fecha, estado=estado,
        subtotal=Decimal(total), total=Decimal(total), metodo_pago=MetodoPago.EFECTIVO,
    )
    db.add(venta)
    db.flush()
    return venta


def test_periodo_septiembre_respeta_cdmx_pagos_y_estados(db, admin_user, monkeypatch):
    monkeypatch.setattr(settings, "APP_TIMEZONE", "America/Mexico_City")
    _venta(db, admin_user.id, "ANTES", datetime(2026, 9, 1, 5, 59, 59, tzinfo=timezone.utc))
    primero = _venta(db, admin_user.id, "PRIMERO", datetime(2026, 9, 1, 6, tzinfo=timezone.utc))
    ultimo = _venta(db, admin_user.id, "ULTIMO", datetime(2026, 10, 1, 5, 59, 59, tzinfo=timezone.utc), "300")
    _venta(db, admin_user.id, "DESPUES", datetime(2026, 10, 1, 6, tzinfo=timezone.utc))
    _venta(db, admin_user.id, "CANCELADA", datetime(2026, 9, 2, 12, tzinfo=timezone.utc), estado=EstadoVenta.CANCELADA)
    _venta(db, admin_user.id, "PENDIENTE", datetime(2026, 9, 2, 12, tzinfo=timezone.utc), estado=EstadoVenta.PENDIENTE)
    db.add_all([
        PagoVenta(venta_id=primero.id, metodo_pago=MetodoPago.EFECTIVO, monto=Decimal("100")),
        PagoVenta(venta_id=ultimo.id, metodo_pago=MetodoPago.EFECTIVO, monto=Decimal("50")),
        PagoVenta(venta_id=ultimo.id, metodo_pago=MetodoPago.TARJETA_CREDITO, terminal=TerminalPago.BBVA, monto=Decimal("250")),
    ])
    db.commit()
    r = reporte_ventas_periodo(db, date(2026, 9, 1), date(2026, 9, 30))
    assert r["resumen"]["numero_ventas"] == 2
    assert r["resumen"]["total"] == 400
    assert r["resumen"]["ticket_promedio"] == 200
    assert r["por_metodo_pago"]["efectivo"]["total"] == 150
    assert r["por_metodo_pago"]["bbva"]["total"] == 250
    assert r["por_dia"] == {
        "2026-09-01": {"cantidad": 1, "total": 100},
        "2026-09-30": {"cantidad": 1, "total": 300},
    }


def test_reporte_ventas_evitar_n_mas_uno(db, admin_user):
    for indice in range(120):
        venta = _venta(db, admin_user.id, f"PERF-{indice}", datetime(2026, 9, 2, 12, tzinfo=timezone.utc))
        db.add(PagoVenta(venta_id=venta.id, metodo_pago=MetodoPago.EFECTIVO, monto=Decimal("100")))
    db.commit()
    db.expunge_all()
    sentencias = []

    def capturar(_conn, _cursor, statement, _parameters, _context, _executemany):
        sentencias.append(statement)

    event.listen(db.bind, "before_cursor_execute", capturar)
    try:
        r = reporte_ventas_periodo(db, date(2026, 9, 1), date(2026, 9, 30))
    finally:
        event.remove(db.bind, "before_cursor_execute", capturar)
    assert r["resumen"]["total"] == 12000
    assert r["resumen"]["numero_ventas"] == 120
    assert len(sentencias) == 1
    assert "pagos_venta" in sentencias[0]
    assert "pago_externo_payload" not in sentencias[0]
    assert "detalles_venta" not in sentencias[0]


def test_egresos_incluye_limites_y_excluye_anulados_y_presupuestos(db):
    for dia, monto, activo in [
        (date(2026, 8, 31), "999", True), (date(2026, 9, 1), "100.50", True),
        (date(2026, 9, 30), "200", True), (date(2026, 10, 1), "999", True),
        (date(2026, 9, 15), "999", False),
    ]:
        db.add(Egreso(concepto="Empaque", monto=Decimal(monto), fecha=dia, activo=activo,
                      categoria="empaque", metodo_pago="efectivo", proveedor="Proveedor"))
    db.add(GastoFijo(concepto="Presupuesto de renta", monto=Decimal("12000")))
    db.commit()
    r = reporte_egresos_periodo(db, date(2026, 9, 1), date(2026, 9, 30))
    assert r["resumen"] == {"total": 300.5, "numero_egresos": 2, "egreso_promedio": 150.25}
    assert r["por_categoria"]["empaque"] == {"cantidad": 2, "total": 300.5}
    assert r["por_metodo_pago"]["efectivo"]["total"] == 300.5
    assert [e["fecha"] for e in r["detalle"]] == ["2026-09-30", "2026-09-01"]


def test_egresos_no_trunca_mas_de_500_movimientos(db):
    db.add_all([Egreso(concepto=f"Gasto {i}", monto=Decimal("1.25"), fecha=date(2026, 9, 10)) for i in range(501)])
    db.commit()
    r = reporte_egresos_periodo(db, date(2026, 9, 1), date(2026, 9, 30))
    assert len(r["detalle"]) == r["resumen"]["numero_egresos"] == 501
    assert r["resumen"]["total"] == 626.25


@pytest.mark.parametrize("endpoint", ["ventas", "ventas/pdf", "egresos"])
@pytest.mark.parametrize("inicio,fin", [("2026-10-02", "2026-10-01"), ("2024-01-01", "2026-01-01")])
def test_rechaza_periodos_invalidos(client, auth_headers, endpoint, inicio, fin):
    r = client.get(f"/api/v1/reportes/{endpoint}?fecha_inicio={inicio}&fecha_fin={fin}", headers=auth_headers)
    assert r.status_code == 400


def test_egresos_endpoint_permisos_y_periodo_vacio(client, auth_headers, admin_user, db):
    ruta = "/api/v1/reportes/egresos?fecha_inicio=2026-09-01&fecha_fin=2026-09-30"
    r = client.get(ruta, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["resumen"]["total"] == 0
    assert r.json()["detalle"] == []
    admin_user.permisos_modulos = {"egresos": "oculto"}
    db.commit()
    assert client.get(ruta, headers=auth_headers).status_code == 403
    admin_user.permisos_modulos = {"egresos": "ver", "rep": "oculto"}
    db.commit()
    assert client.get(ruta, headers=auth_headers).status_code == 403
    assert client.get(ruta).status_code == 401


def test_ventas_periodo_vacio_no_divide_por_cero(db):
    hoy = date.today()
    r = reporte_ventas_periodo(db, hoy - timedelta(days=1), hoy)
    assert r["resumen"]["total"] == 0
    assert r["resumen"]["ticket_promedio"] == 0
    assert r["por_dia"] == {}
