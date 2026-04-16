"""Tests para el dashboard ejecutivo."""


class TestEjecutivo:

    def test_dashboard(self, client, auth_headers):
        resp = client.get("/api/v1/ejecutivo/dashboard", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "fecha" in data
        assert "ventas" in data
        assert "pedidos" in data
        assert "inventario" in data
        assert "finanzas" in data
        assert "clientes" in data
        assert "empleados" in data
        assert "alertas" in data

    def test_dashboard_ventas_structure(self, client, auth_headers):
        resp = client.get("/api/v1/ejecutivo/dashboard", headers=auth_headers)
        ventas = resp.json()["ventas"]
        assert "hoy" in ventas
        assert "ayer" in ventas
        assert "semana" in ventas
        assert "mes" in ventas
        assert "tickets_hoy" in ventas

    def test_dashboard_pedidos_structure(self, client, auth_headers):
        resp = client.get("/api/v1/ejecutivo/dashboard", headers=auth_headers)
        pedidos = resp.json()["pedidos"]
        assert "pendientes" in pedidos
        assert "en_preparacion" in pedidos
        assert "listos" in pedidos

    def test_resumen_semanal(self, client, auth_headers):
        resp = client.get("/api/v1/ejecutivo/resumen-semanal", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 7
        for dia in data:
            assert "fecha" in dia
            assert "ventas" in dia
            assert "tickets" in dia

    def test_comparativo(self, client, auth_headers):
        resp = client.get("/api/v1/ejecutivo/comparativo", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "actual" in data
        assert "anterior" in data
        assert "cambio_pct" in data

    def test_comparativo_con_dias(self, client, auth_headers):
        resp = client.get("/api/v1/ejecutivo/comparativo?dias=7",
                          headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["dias"] == 7

    def test_sin_autenticacion(self, client):
        resp = client.get("/api/v1/ejecutivo/dashboard")
        assert resp.status_code in (401, 403)
