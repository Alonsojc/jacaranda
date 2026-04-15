"""Tests para el módulo de reportes e impuestos."""

from datetime import date, datetime, timedelta
import pytest


class TestReportes:
    """Tests de reportes financieros e impuestos."""

    def _crear_venta(self, client, auth_headers, precio="100.00"):
        """Helper: crea producto + stock + venta."""
        import random
        codigo = f"REP-{random.randint(1000, 9999)}"
        resp = client.post("/api/v1/inventario/productos", json={
            "codigo": codigo,
            "nombre": f"Producto {codigo}",
            "precio_unitario": precio,
            "tasa_iva": "0.16",
        }, headers=auth_headers)
        pid = resp.json()["id"]
        client.post("/api/v1/inventario/movimientos", json={
            "tipo": "entrada_ajuste",
            "producto_id": pid,
            "cantidad": "100",
            "referencia": "Stock test",
        }, headers=auth_headers)
        return client.post("/api/v1/punto-de-venta/ventas", json={
            "metodo_pago": "01",
            "monto_recibido": "500.00",
            "detalles": [{"producto_id": pid, "cantidad": "2"}],
        }, headers=auth_headers)

    def test_dashboard(self, client, auth_headers):
        resp = client.get("/api/v1/reportes/dashboard", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "ventas_hoy" in data
        assert "ventas_mes" in data

    def test_reporte_ventas_periodo(self, client, auth_headers):
        self._crear_venta(client, auth_headers)
        hoy = date.today()
        inicio = (hoy - timedelta(days=7)).isoformat()
        fin = hoy.isoformat()
        resp = client.get(
            f"/api/v1/reportes/ventas?fecha_inicio={inicio}&fecha_fin={fin}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "resumen" in data
        assert "por_metodo_pago" in data

    def test_reporte_iva_mensual(self, client, auth_headers):
        self._crear_venta(client, auth_headers)
        hoy = date.today()
        resp = client.get(
            f"/api/v1/reportes/impuestos/iva-mensual?mes={hoy.month}&anio={hoy.year}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "iva_trasladado" in data
        assert "iva_por_pagar" in data

    def test_reporte_isr_provisional(self, client, auth_headers):
        self._crear_venta(client, auth_headers)
        hoy = date.today()
        resp = client.get(
            f"/api/v1/reportes/impuestos/isr-provisional?mes={hoy.month}&anio={hoy.year}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        # Verificar que es Persona Moral
        assert "regimen" in data
        assert "601" in data["regimen"]
        assert "coeficiente_utilidad" in data
        assert "base_provisional" in data
        assert data["tasa_provisional"] == 0.30

    def test_productos_mas_vendidos(self, client, auth_headers):
        self._crear_venta(client, auth_headers)
        hoy = date.today()
        inicio = (hoy - timedelta(days=30)).isoformat()
        resp = client.get(
            f"/api/v1/reportes/productos-mas-vendidos?fecha_inicio={inicio}&fecha_fin={hoy.isoformat()}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_gastos_hoy(self, client, auth_headers):
        resp = client.get("/api/v1/reportes/gastos-hoy", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "total_gastos" in data
        assert "desglose" in data

    def test_ventas_por_dia(self, client, auth_headers):
        resp = client.get("/api/v1/reportes/ventas-por-dia?dias=7", headers=auth_headers)
        assert resp.status_code == 200

    def test_reporte_pdf_ventas(self, client, auth_headers):
        self._crear_venta(client, auth_headers)
        hoy = date.today()
        inicio = (hoy - timedelta(days=7)).isoformat()
        resp = client.get(
            f"/api/v1/reportes/ventas/pdf?fecha_inicio={inicio}&fecha_fin={hoy.isoformat()}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
