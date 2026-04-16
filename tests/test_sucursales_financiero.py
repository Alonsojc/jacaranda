"""Tests para el reporte financiero consolidado de sucursales."""

import pytest
from decimal import Decimal

from app.models.sucursal import Sucursal, InventarioSucursal
from app.models.inventario import Producto, UnidadMedida

_sf_counter = 0

def _crear_sucursal(db, codigo, nombre, es_matriz=False):
    suc = Sucursal(
        codigo=codigo,
        nombre=nombre,
        es_matriz=es_matriz,
        activo=True,
    )
    db.add(suc)
    db.commit()
    db.refresh(suc)
    return suc


def _crear_producto(db, nombre="Pan Blanco"):
    global _sf_counter
    _sf_counter += 1
    prod = Producto(
        codigo=f"P-SF-{_sf_counter:04d}",
        nombre=nombre,
        unidad_medida=UnidadMedida.PIEZA,
        precio_unitario=Decimal("10.00"),
        costo_produccion=Decimal("4.00"),
        stock_actual=Decimal("100"),
        stock_minimo=Decimal("10"),
        activo=True,
    )
    db.add(prod)
    db.commit()
    db.refresh(prod)
    return prod


class TestReporteFinancieroConsolidado:
    def test_reporte_vacio(self, db):
        """Sin sucursales retorna estructura vacía."""
        from app.services.sucursal_service import reporte_financiero_consolidado

        resultado = reporte_financiero_consolidado(db)
        assert resultado["total_sucursales"] == 0
        assert resultado["sucursales"] == []

    def test_reporte_con_sucursales(self, db):
        """Reporte incluye inventario por sucursal."""
        from app.services.sucursal_service import reporte_financiero_consolidado

        suc1 = _crear_sucursal(db, "MTZ", "Matriz", es_matriz=True)
        suc2 = _crear_sucursal(db, "SUC1", "Sucursal Norte")
        prod = _crear_producto(db)

        # Agregar inventario
        inv1 = InventarioSucursal(
            sucursal_id=suc1.id, producto_id=prod.id,
            stock_actual=Decimal("50"), stock_minimo=Decimal("10"),
        )
        inv2 = InventarioSucursal(
            sucursal_id=suc2.id, producto_id=prod.id,
            stock_actual=Decimal("30"), stock_minimo=Decimal("10"),
        )
        db.add_all([inv1, inv2])
        db.commit()

        resultado = reporte_financiero_consolidado(db)
        assert resultado["total_sucursales"] == 2
        assert resultado["total_valor_inventario"] > 0
        assert len(resultado["sucursales"]) == 2

        # Verificar que tienen datos de inventario
        for suc in resultado["sucursales"]:
            assert "valor_inventario" in suc
            assert "total_productos" in suc
            assert "participacion_inventario_pct" in suc

    def test_reporte_detecta_bajo_minimo(self, db):
        """Detecta productos bajo mínimo en cada sucursal."""
        from app.services.sucursal_service import reporte_financiero_consolidado

        suc = _crear_sucursal(db, "MTZ", "Matriz", es_matriz=True)
        prod = _crear_producto(db)

        inv = InventarioSucursal(
            sucursal_id=suc.id, producto_id=prod.id,
            stock_actual=Decimal("2"),  # bajo mínimo de 10
            stock_minimo=Decimal("10"),
        )
        db.add(inv)
        db.commit()

        resultado = reporte_financiero_consolidado(db)
        suc_data = resultado["sucursales"][0]
        assert suc_data["productos_bajo_minimo"] == 1


class TestAPIEndpoints:
    def test_financiero_consolidado_api(self, client, auth_headers):
        """GET /sucursales/financiero requiere admin/gerente."""
        resp = client.get("/api/v1/sucursales/financiero", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "total_sucursales" in data
        assert "sucursales" in data
