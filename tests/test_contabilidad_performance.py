"""Accounting totals must keep a bounded query count as tickets accumulate."""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import event

from app.core.time_utils import operation_today
from app.models.cafeteria import CafeteriaVenta, DetalleCafeteriaVenta, EstadoCuentaCafeteria
from app.models.inventario import Producto
from app.models.venta import Venta, DetalleVenta, EstadoVenta
from app.services.contabilidad_service import estado_resultados


def test_results_aggregate_many_details_and_keep_canceled_orders_out(db, admin_user):
    product = Producto(codigo="PERF-ER", nombre="Producto prueba", precio_unitario="100",
                       costo_produccion="12.50")
    db.add(product)
    db.flush()
    for i in range(100):
        sale = Venta(folio=f"T-PERF-{i}", usuario_id=admin_user.id, subtotal="200", total="200",
                     iva_16="10", estado=EstadoVenta.COMPLETADA,
                     fecha=datetime.now(timezone.utc))
        sale.detalles = [DetalleVenta(producto_id=product.id, cantidad="2", precio_unitario="100",
                                     subtotal="200", clave_prod_serv_sat="50181900", clave_unidad_sat="H87")]
        db.add(sale)
    for i, state in enumerate([EstadoCuentaCafeteria.PARCIAL, EstadoCuentaCafeteria.CANCELADA]):
        sale = CafeteriaVenta(folio=f"CAF-PERF-{i}", usuario_id=admin_user.id,
                             cafeteria_nombre="Cafe de prueba", total="300", subtotal="300",
                             monto_pagado="100", iva_16="0", estado=state,
                             fecha=datetime.now(timezone.utc))
        sale.detalles = [DetalleCafeteriaVenta(producto_id=product.id, cantidad="3",
                                             precio_unitario="100", subtotal="300")]
        db.add(sale)
    db.commit()
    db.expire_all()
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(db.bind, "before_cursor_execute", record)
    try:
        result = estado_resultados(db, operation_today(), operation_today())
    finally:
        event.remove(db.bind, "before_cursor_execute", record)
    assert len(statements) <= 10, statements
    assert result["numero_ventas"] == 100
    assert result["numero_entregas_cafeteria"] == 1
    assert result["ingresos_mostrador"] == 20000
    assert result["ingresos_cafeteria"] == 300
    assert result["iva_cobrado"] == 1000
    assert result["costo_ventas"] == float(Decimal("203") * Decimal("12.50"))
    assert result["cafeteria_b2b"]["cobrado"] == 100
    assert result["cafeteria_b2b"]["cuentas_por_cobrar"] == 200


def test_empty_period_has_numeric_zero_and_no_false_income(db):
    result = estado_resultados(db, operation_today(), operation_today())
    assert result["costo_ventas"] == 0
    assert result["ingresos_netos"] == 0
    assert result["margen_neto_pct"] == 0
