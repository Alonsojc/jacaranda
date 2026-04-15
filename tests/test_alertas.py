"""Tests para el sistema de alertas automáticas."""

import pytest


class TestAlertas:
    """Tests de alertas consolidadas."""

    def test_alertas_endpoint(self, client, auth_headers):
        resp = client.get("/api/v1/reportes/alertas", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "stock_bajo" in data
        assert "caducidades" in data
        assert "pedidos_pendientes" in data
        assert "merma_hoy" in data
        assert "resumen" in data
        assert "total_alertas" in data["resumen"]
        assert "criticas" in data["resumen"]

    def test_alerta_stock_bajo(self, client, auth_headers):
        """Crear producto con stock bajo y verificar alerta."""
        # Crear producto con stock_minimo alto y stock bajo
        resp = client.post("/api/v1/inventario/productos", json={
            "codigo": "ALRT-001",
            "nombre": "Pan con stock bajo",
            "precio_unitario": "15.00",
            "tasa_iva": "0.00",
            "stock_minimo": "50",
        }, headers=auth_headers)
        assert resp.status_code == 201
        # Stock actual = 0, stock_minimo = 50 → debe alertar
        resp2 = client.get("/api/v1/reportes/alertas", headers=auth_headers)
        data = resp2.json()
        nombres = [a["nombre"] for a in data["stock_bajo"]]
        assert "Pan con stock bajo" in nombres

    def test_alerta_ingrediente_stock_bajo(self, client, auth_headers):
        """Crear ingrediente con stock bajo."""
        resp = client.post("/api/v1/inventario/ingredientes", json={
            "nombre": "Harina Alerta",
            "unidad_medida": "kg",
            "stock_actual": "2.0",
            "stock_minimo": "10.0",
            "costo_unitario": "25.00",
        }, headers=auth_headers)
        assert resp.status_code == 201
        resp2 = client.get("/api/v1/reportes/alertas", headers=auth_headers)
        data = resp2.json()
        nombres = [a["nombre"] for a in data["stock_bajo"]]
        assert "Harina Alerta" in nombres

    def test_merma_estructura(self, client, auth_headers):
        resp = client.get("/api/v1/reportes/alertas", headers=auth_headers)
        merma = resp.json()["merma_hoy"]
        assert "total_movimientos" in merma
        assert "total_unidades" in merma
        assert "porcentaje_merma" in merma
        assert "severidad" in merma

    def test_resumen_conteo(self, client, auth_headers):
        resp = client.get("/api/v1/reportes/alertas", headers=auth_headers)
        resumen = resp.json()["resumen"]
        assert resumen["total_alertas"] >= 0
        assert resumen["criticas"] >= 0
        assert resumen["altas"] >= 0
