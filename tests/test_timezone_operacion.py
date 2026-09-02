"""Regresiones para el día operativo de Ciudad de México."""

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.core.config import settings
from app.core.time_utils import (
    operation_datetime,
    operation_day_bounds,
)
from app.models.inventario import Producto
from app.models.venta import DetalleVenta, EstadoVenta, MetodoPago, Venta
from app.services.reportes_service import comparativo_anual, dashboard_resumen
from app.services.venta_service import generar_ticket


ROOT = Path(__file__).resolve().parents[1]


def _crear_venta_nocturna(db, usuario_id: int, fecha_utc: datetime) -> Venta:
    producto = Producto(
        codigo=f"TZ-{fecha_utc:%H%M%S}",
        nombre="Producto nocturno",
        precio_unitario=Decimal("100.00"),
    )
    db.add(producto)
    db.flush()

    venta = Venta(
        folio=f"TZ-{fecha_utc:%Y%m%d%H%M%S}",
        usuario_id=usuario_id,
        subtotal=Decimal("100.00"),
        iva_0=Decimal("100.00"),
        total=Decimal("100.00"),
        metodo_pago=MetodoPago.EFECTIVO,
        estado=EstadoVenta.COMPLETADA,
        monto_recibido=Decimal("100.00"),
        fecha=fecha_utc,
    )
    db.add(venta)
    db.flush()
    db.add(DetalleVenta(
        venta_id=venta.id,
        producto_id=producto.id,
        cantidad=Decimal("1"),
        precio_unitario=Decimal("100.00"),
        subtotal=Decimal("100.00"),
        clave_prod_serv_sat="50181900",
        clave_unidad_sat="H87",
    ))
    db.commit()
    db.refresh(venta)
    return venta


def test_hora_utc_se_convierte_al_dia_anterior_en_cdmx(monkeypatch):
    monkeypatch.setattr(settings, "APP_TIMEZONE", "America/Mexico_City")
    monkeypatch.setattr(settings, "DATABASE_URL", "sqlite:///./test.db")

    fecha_utc = datetime(2026, 9, 2, 1, 30, tzinfo=timezone.utc)
    fecha_local = operation_datetime(fecha_utc)
    inicio, fin = operation_day_bounds(date(2026, 9, 1))

    assert fecha_local.isoformat() == "2026-09-01T19:30:00-06:00"
    assert inicio == datetime(2026, 9, 1, 6, 0)
    assert fin == datetime(2026, 9, 2, 5, 59, 59, 999999)


def test_ticket_y_dashboard_usan_el_dia_operativo_cdmx(
    db,
    admin_user,
    monkeypatch,
):
    monkeypatch.setattr(settings, "APP_TIMEZONE", "America/Mexico_City")
    monkeypatch.setattr(settings, "DATABASE_URL", "sqlite:///./test.db")
    monkeypatch.setattr(
        "app.services.reportes_service._hoy_operacion",
        lambda: date(2026, 9, 1),
    )
    venta = _crear_venta_nocturna(
        db,
        admin_user.id,
        datetime(2026, 9, 2, 1, 30, tzinfo=timezone.utc),
    )

    ticket = generar_ticket(db, venta.id)
    dashboard = dashboard_resumen(db)

    assert ticket["fecha"] == "01/09/2026 19:30:00"
    assert dashboard["fecha"] == "2026-09-01"
    assert dashboard["ventas_hoy"] == {"total": 100.0, "numero_ventas": 1}


def test_reporte_mensual_asigna_venta_nocturna_al_mes_local(
    db,
    admin_user,
    monkeypatch,
):
    monkeypatch.setattr(settings, "APP_TIMEZONE", "America/Mexico_City")
    monkeypatch.setattr(settings, "DATABASE_URL", "sqlite:///./test.db")
    _crear_venta_nocturna(
        db,
        admin_user.id,
        datetime(2026, 9, 1, 1, 30, tzinfo=timezone.utc),
    )

    reporte = comparativo_anual(db, 2026)

    assert reporte[7]["ventas_actual"] == 100.0
    assert reporte[8]["ventas_actual"] == 0.0


def test_pwa_calcula_fechas_con_zona_operativa_y_renueva_cache():
    html = (ROOT / "docs/index.html").read_text(encoding="utf-8")
    sw = (ROOT / "docs/sw.js").read_text(encoding="utf-8")

    assert "var APP_TIMEZONE = 'America/Mexico_City'" in html
    assert "function fechaISOOperacion(value)" in html
    assert "timeZone: APP_TIMEZONE" in html
    assert "function instanteUTC(value)" in html
    assert "actualizarFechaDashboard(d.fecha || fechaHoyISO())" in html
    assert "new Date().toISOString().split('T')[0]" not in html
    assert "jacaranda-v98" in html
    assert "jacaranda-v98" in sw
