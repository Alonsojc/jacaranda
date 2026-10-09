"""Bounded analytics queries and conservative recommendations on synthetic data."""

from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import event

from app.core.config import settings
from app.models.cliente import Cliente
from app.models.gasto_fijo import GastoFijo
from app.models.inventario import Producto, HistorialPrecio, CategoriaProducto, CategoriaProductoEnum
from app.models.venta import Venta, DetalleVenta, EstadoVenta, MetodoPago
from app.services import ia_service as ia, crm_service as crm, reportes_service as reportes


@pytest.fixture(autouse=True)
def reloj(monkeypatch):
    monkeypatch.setattr(settings, "APP_TIMEZONE", "America/Mexico_City")
    monkeypatch.setattr(ia, "operation_today", lambda: date(2026, 10, 9))
    monkeypatch.setattr(crm, "operation_today", lambda: date(2026, 10, 9))
    monkeypatch.setattr(reportes, "_hoy_operacion", lambda: date(2026, 10, 9))


def producto(db, codigo="PAN", **kwargs):
    data = {"codigo": codigo, "nombre": codigo, "precio_unitario": Decimal("40"),
            "costo_produccion": Decimal("20"), "stock_actual": Decimal("0")}
    data.update(kwargs)
    p = Producto(**data)
    db.add(p)
    db.flush()
    return p


def venta(db, user, prod, dia, *, cantidad=1, cliente=None, estado=EstadoVenta.COMPLETADA):
    total = Decimal(str(cantidad)) * prod.precio_unitario
    v = Venta(folio=f"TEST-{db.query(Venta).count()}", usuario_id=user.id,
              fecha=datetime.combine(dia, datetime.min.time()).replace(hour=12, tzinfo=timezone.utc),
              estado=estado, subtotal=total, total=total, metodo_pago=MetodoPago.EFECTIVO,
              cliente_id=cliente.id if cliente else None)
    db.add(v)
    db.flush()
    db.add(DetalleVenta(venta_id=v.id, producto_id=prod.id, cantidad=cantidad,
                        precio_unitario=prod.precio_unitario, subtotal=total,
                        clave_prod_serv_sat="50181900", clave_unidad_sat="H87"))
    db.flush()
    return v


@contextmanager
def sql(db):
    sentencias = []

    def capturar(_conn, _cursor, statement, _parameters, _context, _many):
        sentencias.append(statement)

    event.listen(db.bind, "before_cursor_execute", capturar)
    try:
        yield sentencias
    finally:
        event.remove(db.bind, "before_cursor_execute", capturar)


def test_dashboard_uses_six_queries_even_with_many_sale_lines(db, admin_user):
    cliente = Cliente(nombre="Cliente mensual")
    db.add(cliente)
    db.flush()
    pan = producto(db, imagen="VERY_LARGE_IMAGE")
    sin_costo = producto(db, "SIN-COSTO", costo_produccion=0)
    for i in range(40):
        venta(db, admin_user, pan, date(2026, 10, 1), cliente=cliente)
    venta(db, admin_user, sin_costo, date(2026, 10, 9), cliente=cliente)
    venta(db, admin_user, pan, date(2026, 10, 10), cantidad=999, cliente=cliente)
    venta(db, admin_user, pan, date(2026, 10, 2), cantidad=999, estado=EstadoVenta.CANCELADA)
    db.add(GastoFijo(concepto="Renta", monto=Decimal("100"), periodicidad="mensual"))
    db.commit()
    with sql(db) as queries:
        data = reportes.dashboard_avanzado(db)
    assert len(queries) == 6
    assert not any("productos.imagen" in q for q in queries)
    assert data["meses"][-1] == {"mes": "Oct 2026", "total": 1640}
    assert data["utilidad"] == {"ingresos": 1640, "costo_ventas": 800, "utilidad_bruta": 840,
                                "gastos_fijos": 100, "utilidad_neta": 740, "partidas_sin_costo": 1}
    assert data["clientes_vip"][0]["visitas"] == 41
    assert data["proyeccion"]["ventas_base"] == 1600


def test_monthly_aggregation_keeps_local_midnight_and_year_boundary(db, admin_user, monkeypatch):
    monkeypatch.setattr(reportes, "_hoy_operacion", lambda: date(2026, 1, 2))
    pan = producto(db)
    old = venta(db, admin_user, pan, date(2026, 1, 1))
    old.fecha = datetime(2026, 1, 1, 5, 59, tzinfo=timezone.utc)
    venta(db, admin_user, pan, date(2026, 1, 1), cantidad=2)
    db.commit()
    data = reportes.dashboard_avanzado(db)
    assert data["meses"][0]["mes"] == "Feb 2025"
    assert data["meses"][-2] == {"mes": "Dic 2025", "total": 40}
    assert data["meses"][-1] == {"mes": "Ene 2026", "total": 80}


def test_forecast_includes_zero_days_and_excludes_today_future_and_cancelled(db, admin_user):
    pan = producto(db)
    venta(db, admin_user, pan, date(2026, 10, 1), cantidad=8)
    venta(db, admin_user, pan, date(2026, 10, 9), cantidad=999)
    venta(db, admin_user, pan, date(2026, 10, 10), cantidad=999)
    venta(db, admin_user, pan, date(2026, 10, 8), cantidad=999, estado=EstadoVenta.CANCELADA)
    db.commit()
    result = ia.pronostico_demanda(db)[0]
    assert result["promedio_diario"] == 1
    assert result["dias_con_venta"] == 1
    assert not any(s["sugerido_hornear"] for s in ia.pronostico_produccion_ia(db))
    assert ia._series_diarias({date(2026, 10, 1): 8}, date(2026, 10, 1), date(2026, 10, 8))[3] == [(0, 8), (1, 0)]


def test_production_never_bakes_accessories_or_adds_stock_deficit_to_demand(db, admin_user):
    pan = producto(db, stock_actual=-10)
    vela = producto(db, "Vela")
    for dia in (date(2026, 9, 26), date(2026, 10, 3)):
        venta(db, admin_user, pan, dia, cantidad=1)
        venta(db, admin_user, vela, dia, cantidad=10)
    db.commit()
    result = ia.pronostico_produccion_ia(db)
    assert len(result) == 1
    assert result[0]["advertencias"]
    cantidad = result[0]["sugerido_hornear"]
    pan.stock_actual = 0
    db.commit()
    assert ia.pronostico_produccion_ia(db)[0]["sugerido_hornear"] == cantidad
    assert cantidad < 10


def test_dashboard_prediction_query_count_does_not_grow_with_catalog(db, admin_user):
    for i in range(25):
        pan = producto(db, str(i), imagen="DO_NOT_LOAD")
        venta(db, admin_user, pan, date(2026, 9, 15))
    db.commit()
    with sql(db) as queries:
        data = ia.dashboard_ia(db)
    assert len(queries) == 5
    assert not any("productos.imagen" in q for q in queries)
    assert data["fecha_base"] == "2026-10-08"
    with sql(db) as queries:
        ia.precision_modelo(db, dias_atras=30)
    assert len(queries) == 1


def test_pricing_with_history_is_bounded_and_categories_exclude_non_baked_goods(db, admin_user):
    otros = CategoriaProducto(nombre="Accesorios", tipo=CategoriaProductoEnum.OTROS)
    db.add(otros)
    db.flush()
    for i in range(12):
        p = producto(db, str(i), categoria_id=otros.id)
        venta(db, admin_user, p, date(2026, 9, 15))
        db.add(HistorialPrecio(producto_id=p.id, precio_anterior=35, precio_nuevo=40,
                              fecha=datetime(2026, 9, 20, 12, tzinfo=timezone.utc)))
    db.commit()
    with sql(db) as queries:
        data = ia.dashboard_ia(db)
    assert len(queries) == 6
    assert data["total_productos_hornear"] == 0
    assert data["sugerencias_produccion"] == []


def test_backtest_counts_unpredicted_sales_and_no_future_leakage(db):
    historial = {1: {date(2026, 10, 8): 10, date(2026, 10, 9): 999}}
    data = ia.precision_modelo(db, dias_atras=1, historial=historial)
    assert data["muestras"] == 1
    assert data["comparaciones"][0]["predicho"] == 0
    assert data["comparaciones"][0]["real"] == 10
    assert data["precision_promedio"] == 0
    assert data["error_normalizado_pct"] == 100


def test_backtest_replays_tomorrow_forecast_with_the_same_closed_day_cutoff(db):
    pan = producto(db)
    historial = {pan.id: {date(2026, 9, 26): 4, date(2026, 10, 3): 2,
                         date(2026, 10, 8): 1, date(2026, 10, 9): 999}}
    live = ia.pronostico_demanda(db, dias_futuro=1, historial=historial)[0]
    replay = ia._predecir_dia_historico(db, date(2026, 10, 10), historial=historial)
    assert replay[pan.id] == live["predicciones"][0]["cantidad"]


@pytest.mark.parametrize("precio,costo", [(40, 300), (40, 0), (40, 40)])
def test_inconsistent_costs_never_become_discount_increases(precio, costo):
    sugerencia = ia._sugerir_precio(precio, costo, -10, None, 0, 30, 10)
    assert sugerencia["accion"] == "revisar"
    assert sugerencia["precio_sugerido"] == precio


def test_price_margin_and_discount_floor_are_mathematically_consistent():
    suggestion = ia._sugerir_precio(35, 30, 14.3, None, 3, 1, 10)
    assert suggestion["precio_sugerido"] == 40
    suggestion = ia._sugerir_precio(40, 38, 5, None, 0, 30, 10)
    assert suggestion["accion"] == "mantener"
    assert suggestion["precio_sugerido"] == 40


def test_elasticity_waits_for_complete_comparable_windows():
    cambio = HistorialPrecio(fecha=datetime(2026, 10, 1, 12, tzinfo=timezone.utc),
                             precio_anterior=40, precio_nuevo=44)
    historial = {date(2026, 9, 20): 10, date(2026, 10, 2): 10}
    assert ia._elasticidad_historica([cambio], historial, date(2026, 10, 9)) is None
    assert ia._elasticidad_historica([cambio], historial, date(2026, 10, 16))["valor"] == 0


def test_crm_totals_points_and_segments_in_one_read_only_query(db, admin_user):
    cliente = Cliente(nombre="Comprador", puntos_acumulados=12, nivel_lealtad="plata")
    nuevo = Cliente(nombre="Nuevo sin compras")
    db.add_all([cliente, nuevo])
    db.flush()
    pan = producto(db)
    venta(db, admin_user, pan, date(2026, 6, 1), cliente=cliente)
    venta(db, admin_user, pan, date(2026, 10, 8), cantidad=3, cliente=cliente)
    venta(db, admin_user, pan, date(2026, 10, 10), cantidad=999, cliente=cliente)
    venta(db, admin_user, pan, date(2026, 10, 7), cantidad=999, cliente=cliente, estado=EstadoVenta.CANCELADA)
    db.commit()
    with sql(db) as queries:
        data = crm.segmentar_clientes(db)
    assert len(queries) == 1
    assert data[0]["total_compras"] == 160
    assert data[0]["compras"] == 2
    assert data[0]["frecuencia"] == 1
    assert data[0]["monto_total"] == 120
    assert data[0]["ticket_promedio"] == 80
    assert data[0]["puntos"] == 12
    assert data[0]["ultima_compra"] == "2026-10-08"
    assert data[1]["segmento"] == "nuevo"
    summary = crm.obtener_segmentacion(db)
    assert summary["activos"] == 1
    assert summary["sin_compras"] == 1
    assert summary["segmentos"]["perdido"] == 0
    with sql(db) as queries:
        detalle = crm.compras_cliente(db, cliente.id, limit=1)
    assert detalle["hay_mas"] is True
    assert detalle["compras"][0]["total"] == 120
    assert detalle["compras"][0]["fecha"].endswith("-06:00")
    assert detalle["compras"][0]["detalles"][0]["producto"] == "PAN"
    assert not any(q.lstrip().upper().startswith(("UPDATE", "INSERT", "DELETE")) for q in queries)


def test_crm_pagination_literal_search_and_permission(client, auth_headers, db, admin_user):
    db.add_all([Cliente(nombre="Uno"), Cliente(nombre="Dos%"), Cliente(nombre="Inactivo", activo=False)])
    db.commit()
    result = client.get("/api/v1/crm/clientes?limit=1", headers=auth_headers).json()
    assert result["hay_mas"] is True
    assert result["clientes"][0]["nombre"] == "Dos%"
    result = client.get("/api/v1/crm/clientes?q=%25", headers=auth_headers).json()
    assert len(result["clientes"]) == 1
    assert client.get("/api/v1/crm/clientes/999/compras", headers=auth_headers).status_code == 404
    admin_user.permisos_modulos = {"crm": "oculto", "listas": "editar"}
    db.commit()
    assert client.get("/api/v1/crm/clientes", headers=auth_headers).status_code == 403
    assert client.get("/api/v1/crm/clientes/1/compras", headers=auth_headers).status_code == 403


@pytest.mark.parametrize("path", ["pronostico-demanda?dias=0", "pronostico-demanda?semanas=0", "pricing?dias=0", "precision?dias=0"])
def test_prediction_rejects_zero_windows(client, auth_headers, path):
    assert client.get("/api/v1/ia/" + path, headers=auth_headers).status_code == 422
