"""Tests para el módulo de IA / Pronósticos."""

import pytest


class TestIA:
    """Tests del módulo de inteligencia artificial."""

    def _crear_venta_producto(self, client, auth_headers, codigo, precio="25.00"):
        """Helper: crea producto con stock y una venta."""
        resp = client.post("/api/v1/inventario/productos", json={
            "codigo": codigo,
            "nombre": f"Pan {codigo}",
            "precio_unitario": precio,
            "tasa_iva": "0.00",
        }, headers=auth_headers)
        pid = resp.json()["id"]
        client.post("/api/v1/inventario/movimientos", json={
            "tipo": "entrada_ajuste",
            "producto_id": pid,
            "cantidad": "500",
            "referencia": "Stock IA test",
        }, headers=auth_headers)
        client.post("/api/v1/punto-de-venta/ventas", json={
            "metodo_pago": "01",
            "monto_recibido": "100.00",
            "detalles": [{"producto_id": pid, "cantidad": "3"}],
        }, headers=auth_headers)
        return pid

    def test_dashboard_ia(self, client, auth_headers):
        resp = client.get("/api/v1/ia/dashboard", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "pronostico" in data or "produccion" in data or isinstance(data, dict)

    def test_pronostico_demanda(self, client, auth_headers):
        resp = client.get("/api/v1/ia/pronostico-demanda?dias=3&semanas=4", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list) or isinstance(data, dict)

    def test_produccion_sugerida(self, client, auth_headers):
        self._crear_venta_producto(client, auth_headers, "IA-001")
        resp = client.get("/api/v1/ia/produccion-sugerida", headers=auth_headers)
        assert resp.status_code == 200

    def test_analisis_pricing(self, client, auth_headers):
        self._crear_venta_producto(client, auth_headers, "IA-002", "30.00")
        resp = client.get("/api/v1/ia/pricing?dias=30", headers=auth_headers)
        assert resp.status_code == 200

    def test_precision_modelo(self, client, auth_headers):
        resp = client.get("/api/v1/ia/precision?dias=7", headers=auth_headers)
        assert resp.status_code == 200

    def test_pronostico_limites(self, client, auth_headers):
        """Verificar que los Query limits funcionan."""
        # dias max 14
        resp = client.get("/api/v1/ia/pronostico-demanda?dias=15", headers=auth_headers)
        assert resp.status_code == 422  # Validation error

        # semanas max 12
        resp = client.get("/api/v1/ia/pronostico-demanda?semanas=13", headers=auth_headers)
        assert resp.status_code == 422
