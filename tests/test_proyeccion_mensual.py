"""Proyecciones con dias completos y datos ficticios en una base aislada."""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import event

from app.core.config import settings
from app.models.venta import EstadoVenta, MetodoPago, Venta
from app.services import reportes_service as svc


def venta(db, usuario_id, folio, fecha, total, estado=EstadoVenta.COMPLETADA):
    db.add(Venta(
        usuario_id=usuario_id, folio=folio, fecha=fecha, estado=estado,
        subtotal=Decimal(total), total=Decimal(total), metodo_pago=MetodoPago.EFECTIVO,
    ))


@pytest.fixture
def mes_actual(db, admin_user, monkeypatch):
    monkeypatch.setattr(settings, "APP_TIMEZONE", "America/Mexico_City")
    monkeypatch.setattr(svc, "_hoy_operacion", lambda: date(2026, 10, 7))
    venta(db, admin_user.id, "MES-ANTES", datetime(2026, 10, 1, 5, 59, 59, tzinfo=timezone.utc), "999")
    venta(db, admin_user.id, "MES-PRIMERO", datetime(2026, 10, 1, 6, tzinfo=timezone.utc), "100")
    venta(db, admin_user.id, "MES-AYER", datetime(2026, 10, 7, 5, 59, 59, tzinfo=timezone.utc), "500")
    venta(db, admin_user.id, "MES-HOY", datetime(2026, 10, 7, 6, tzinfo=timezone.utc), "900")
    venta(db, admin_user.id, "MES-FUTURO", datetime(2026, 10, 8, 12, tzinfo=timezone.utc), "999")
    venta(db, admin_user.id, "MES-CANCELADA", datetime(2026, 10, 2, 12, tzinfo=timezone.utc), "9999", EstadoVenta.CANCELADA)
    venta(db, admin_user.id, "MES-PENDIENTE", datetime(2026, 10, 2, 12, tzinfo=timezone.utc), "9999", EstadoVenta.PENDIENTE)
    db.commit()


def test_mes_incluye_hoy_en_total_pero_no_en_proyeccion(db, mes_actual):
    reporte = svc.reporte_ventas_periodo(db, date(2026, 10, 1), date(2026, 10, 7))
    assert reporte["resumen"]["total"] == 1500
    assert reporte["proyeccion"] == {
        "proyeccion_mes": 3100,
        "ventas_base": 600,
        "dias_transcurridos": 6,
        "dias_del_mes": 31,
        "fecha_inicio": "2026-10-01",
        "fecha_fin": "2026-10-06",
    }
    assert svc.dashboard_avanzado(db)["proyeccion"] == reporte["proyeccion"]


@pytest.mark.parametrize("fin", [date(2026, 10, 6), date(2026, 10, 31)])
def test_reporte_mes_hasta_ayer_o_fin_del_mes_no_incluye_ventas_futuras(db, mes_actual, fin):
    reporte = svc.reporte_ventas_periodo(db, date(2026, 10, 1), fin)
    assert reporte["proyeccion"]["ventas_base"] == 600
    assert reporte["proyeccion"]["proyeccion_mes"] == 3100


@pytest.mark.parametrize("inicio,fin", [
    (date(2026, 10, 2), date(2026, 10, 7)),
    (date(2026, 10, 1), date(2026, 10, 5)),
    (date(2026, 9, 1), date(2026, 9, 30)),
    (date(2026, 9, 1), date(2026, 10, 31)),
])
def test_no_proyecta_periodos_que_no_cubren_el_mes_actual_completo(db, mes_actual, inicio, fin):
    assert svc.reporte_ventas_periodo(db, inicio, fin)["proyeccion"] is None


@pytest.mark.parametrize("hoy,dias,fin,proyeccion", [
    (date(2026, 10, 1), 0, None, None),
    (date(2024, 2, 29), 28, "2024-02-28", 290),
    (date(2026, 4, 30), 29, "2026-04-29", 300),
    (date(2026, 12, 31), 30, "2026-12-30", 310),
])
def test_divisor_y_duracion_real_del_mes(hoy, dias, fin, proyeccion):
    datos = svc._proyeccion_mes_dias_completos(hoy, Decimal(dias * 10))
    assert datos["dias_transcurridos"] == dias
    assert datos["fecha_fin"] == fin
    assert datos["proyeccion_mes"] == proyeccion


def test_primer_dia_no_usa_el_mes_anterior_ni_las_ventas_de_hoy(db, admin_user, monkeypatch):
    monkeypatch.setattr(settings, "APP_TIMEZONE", "America/Mexico_City")
    monkeypatch.setattr(svc, "_hoy_operacion", lambda: date(2026, 10, 1))
    venta(db, admin_user.id, "DIA1-ANTES", datetime(2026, 10, 1, 5, 59, 59, tzinfo=timezone.utc), "800")
    venta(db, admin_user.id, "DIA1-HOY", datetime(2026, 10, 1, 6, tzinfo=timezone.utc), "200")
    db.commit()
    reporte = svc.reporte_ventas_periodo(db, date(2026, 10, 1), date(2026, 10, 1))
    assert reporte["resumen"]["total"] == 200
    assert reporte["proyeccion"]["ventas_base"] == 0
    assert reporte["proyeccion"]["proyeccion_mes"] is None
    assert svc.dashboard_avanzado(db)["proyeccion"] == reporte["proyeccion"]


def test_mes_sin_ventas_si_tiene_dias_completos_proyecta_cero(db, monkeypatch):
    monkeypatch.setattr(svc, "_hoy_operacion", lambda: date(2026, 10, 7))
    datos = svc.reporte_ventas_periodo(db, date(2026, 10, 1), date(2026, 10, 7))["proyeccion"]
    assert datos["dias_transcurridos"] == 6
    assert datos["proyeccion_mes"] == 0


def test_proyeccion_del_reporte_no_agrega_consultas_sql(db, mes_actual):
    sentencias = []

    def capturar(_conn, _cursor, statement, _parameters, _context, _executemany):
        sentencias.append(statement)

    event.listen(db.bind, "before_cursor_execute", capturar)
    try:
        svc.reporte_ventas_periodo(db, date(2026, 10, 1), date(2026, 10, 7))
    finally:
        event.remove(db.bind, "before_cursor_execute", capturar)
    assert len(sentencias) == 1


def test_dashboard_no_expone_el_mes_y_reportes_respeta_permiso(client, auth_headers, admin_user, db, mes_actual):
    admin_user.permisos_modulos = {"dash": "ver", "rep": "oculto"}
    db.commit()
    dashboard = client.get("/api/v1/reportes/dashboard", headers=auth_headers)
    assert dashboard.status_code == 200
    assert "ventas_mes" not in dashboard.json()
    assert "proyeccion" not in dashboard.json()
    ruta = "/api/v1/reportes/ventas?fecha_inicio=2026-10-01&fecha_fin=2026-10-07"
    assert client.get(ruta, headers=auth_headers).status_code == 403
    admin_user.permisos_modulos = {"dash": "ver", "rep": "ver"}
    db.commit()
    respuesta = client.get(ruta, headers=auth_headers)
    assert respuesta.status_code == 200
    assert respuesta.json()["proyeccion"]["proyeccion_mes"] == 3100
