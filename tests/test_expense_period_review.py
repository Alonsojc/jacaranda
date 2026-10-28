"""Period-scoped expenses and evidence-bounded accounting, without source edits."""

from datetime import date, datetime, timezone
from decimal import Decimal

from openpyxl import load_workbook
import pytest

from app.models.egreso import Egreso
from app.models.gasto_fijo import GastoFijo
from app.models.inventario import Producto
from app.models.venta import DetalleVenta, EstadoVenta, Venta
from app.services.contabilidad_service import estado_resultados
from app.services.excel_service import exportar_estado_resultados, exportar_reporte_mensual


def expense(db, **overrides):
    values = dict(concepto="Insumo de prueba", monto=Decimal("10.25"), categoria="insumos",
                  metodo_pago="tarjeta", proveedor="Proveedor prueba", fecha=date(2026, 9, 1), activo=True)
    values.update(overrides)
    item = Egreso(**values)
    db.add(item)
    db.flush()
    return item


def test_query_totals_cover_all_pages_and_only_selected_period(client, auth_headers, db):
    ids = [expense(db).id for _ in range(31)]
    expense(db, fecha=date(2026, 8, 31), monto=999)
    expense(db, fecha=date(2026, 10, 1), monto=999)
    expense(db, activo=False, monto=999)
    db.commit()
    query = "/api/v1/egresos/consulta?fecha_inicio=2026-09-01&fecha_fin=2026-09-30"
    first = client.get(query, headers=auth_headers).json()
    assert first["cantidad"] == 31 and Decimal(first["total"]) == Decimal("317.75")
    assert [i["id"] for i in first["items"]] == list(reversed(ids))[:25]
    second = client.get(query + "&skip=25", headers=auth_headers).json()
    assert len(second["items"]) == 6 and second["total"] == first["total"]
    assert not {i["id"] for i in first["items"]} & {i["id"] for i in second["items"]}
    assert client.get(query).status_code == 401


def test_search_filters_combine_and_wildcards_are_literal(client, auth_headers, db):
    match = expense(db, concepto="Flete 10%_local", categoria="flete", metodo_pago="efectivo", proveedor="CENTRO")
    expense(db, concepto="Otro", categoria="flete", metodo_pago="tarjeta", proveedor="CENTRO")
    db.commit()
    query = "/api/v1/egresos/consulta"
    params = dict(fecha_inicio="2026-09-01", fecha_fin="2026-09-30", buscar=" centro ", categoria="flete", metodo_pago="efectivo")
    data = client.get(query, params=params, headers=auth_headers).json()
    assert [i["id"] for i in data["items"]] == [match.id]
    params["buscar"] = "%_"
    assert client.get(query, params=params, headers=auth_headers).json()["cantidad"] == 1
    params["buscar"] = "desconocido"
    data = client.get(query, params=params, headers=auth_headers).json()
    assert data["items"] == [] and Decimal(data["total"]) == 0 and data["cantidad"] == 0


@pytest.mark.parametrize("extra,code", [("&categoria=xyz", 400), ("&metodo_pago=xyz", 400), ("&skip=-1", 422), ("&limit=101", 422)])
def test_query_rejects_invalid_filters(client, auth_headers, extra, code):
    assert client.get("/api/v1/egresos/consulta?fecha_inicio=2026-09-01&fecha_fin=2026-09-30" + extra, headers=auth_headers).status_code == code


def test_query_rejects_reversed_dates(client, auth_headers):
    assert client.get("/api/v1/egresos/consulta?fecha_inicio=2026-10-01&fecha_fin=2026-09-30", headers=auth_headers).status_code == 400


def test_accounting_sources_missing_cost_and_exports_preserve_records(db, admin_user):
    item = expense(db, proveedor="=TEST()", monto=Decimal("100.50"))
    expense(db, categoria="servicio", proveedor="Proveedor dos", monto=Decimal("40.25"))
    expense(db, activo=False, monto=999)
    db.add(GastoFijo(concepto="Renta", monto=Decimal("3000"), periodicidad="mensual", activo=True))
    product = Producto(codigo="REVIEW-ZERO", nombre="Sin costo", precio_unitario=100, costo_produccion=0)
    db.add(product)
    db.flush()
    for i, state in enumerate((EstadoVenta.COMPLETADA, EstadoVenta.CANCELADA)):
        sale = Venta(folio=f"REVIEW-{i}", usuario_id=admin_user.id, subtotal=100, total=100, iva_16=0,
                     estado=state, fecha=datetime(2026, 9, 1, 18, tzinfo=timezone.utc))
        sale.detalles = [DetalleVenta(producto_id=product.id, cantidad=1, precio_unitario=100, subtotal=100,
                                     clave_prod_serv_sat="50181900", clave_unidad_sat="H87")]
        db.add(sale)
    db.commit()
    data = estado_resultados(db, date(2026, 9, 1), date(2026, 9, 1))
    assert data["composicion_gastos"] == dict(egresos_registrados=140.75, cantidad_egresos=2, recurrentes_estimados=100, nomina_registrada=0)
    assert data["total_gastos_operacion"] == 240.75
    assert data["calidad_datos"]["lineas_sin_costo"] == 1
    assert data["calidad_datos"]["lineas_vendidas"] == 1
    assert data["calidad_datos"]["resultado_estimado"]
    assert sum(data["egresos_por_categoria"].values()) == 140.75
    assert sum(data["egresos_por_proveedor"].values()) == 140.75
    assert any("insumos" in n for n in data["calidad_datos"]["notas"])
    for buffer in (exportar_estado_resultados(db, date(2026, 9, 1), date(2026, 9, 1)), exportar_reporte_mensual(db, mes=9, anio=2026)):
        sheet = load_workbook(buffer)["Base y revisión"]
        cell = next(c for row in sheet for c in row if c.value == "=TEST()")
        assert cell.data_type == "s"
        assert sheet["A1"].value == "RESULTADO ESTIMADO"
    db.refresh(item)
    assert item.monto == Decimal("100.50") and item.categoria == "insumos"
