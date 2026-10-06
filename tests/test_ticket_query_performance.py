"""Ticket reads should not query each already-loaded product again."""

from decimal import Decimal

import pytest
from sqlalchemy import event

from app.models.inventario import Producto
from app.models.venta import DetalleVenta, Venta
from app.services.venta_service import generar_ticket


@pytest.mark.parametrize("product_count", [1, 5])
def test_ticket_query_count_does_not_grow_with_product_count(db, admin_user, product_count):
    sale = Venta(
        folio="T-QUERY-TEST", usuario_id=admin_user.id,
        subtotal=Decimal("50"), total=Decimal("50"),
    )
    for index in range(product_count):
        product = Producto(
            codigo=f"QUERY-{index}", nombre=f"Test product {index}",
            precio_unitario=Decimal("10"),
        )
        sale.detalles.append(DetalleVenta(
            producto=product, cantidad=Decimal("1"), precio_unitario=Decimal("10"),
            subtotal=Decimal("10"), clave_prod_serv_sat="50181900", clave_unidad_sat="H87",
        ))
    db.add(sale)
    db.commit()
    sale_id = sale.id
    db.expunge_all()
    statements = []

    def record_select(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    bind = db.get_bind()
    event.listen(bind, "before_cursor_execute", record_select)
    try:
        ticket = generar_ticket(db, sale_id)
    finally:
        event.remove(bind, "before_cursor_execute", record_select)

    assert len(ticket["productos"]) == product_count
    assert len(statements) == 1
    assert ticket["productos"][0]["nombre"] == "Test product 0"
