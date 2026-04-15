"""Tests para el módulo de KPIs y gráficas."""

from datetime import date


class TestKPIs:
    """Tests de endpoints KPI para dashboard con gráficas."""

    # ── Dashboard consolidado ──

    def test_dashboard_kpis(self, client, auth_headers):
        resp = client.get("/api/v1/kpis/dashboard", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "ventas_hoy" in data
        assert "ventas_mes" in data
        assert "inventario" in data
        assert "clientes" in data

    def test_dashboard_kpis_estructura_ventas_hoy(self, client, auth_headers):
        resp = client.get("/api/v1/kpis/dashboard", headers=auth_headers)
        data = resp.json()
        vh = data["ventas_hoy"]
        assert "total" in vh
        assert "cantidad" in vh
        assert "ticket_promedio" in vh
        assert "cambio_vs_ayer_pct" in vh

    def test_dashboard_kpis_estructura_inventario(self, client, auth_headers):
        resp = client.get("/api/v1/kpis/dashboard", headers=auth_headers)
        data = resp.json()
        inv = data["inventario"]
        assert "productos_stock_bajo" in inv
        assert "ingredientes_stock_bajo" in inv
        assert "valor_inventario_productos" in inv

    # ── Ventas por hora ──

    def test_ventas_por_hora(self, client, auth_headers):
        resp = client.get("/api/v1/kpis/ventas-por-hora", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_ventas_por_hora_con_fecha(self, client, auth_headers):
        hoy = date.today().isoformat()
        resp = client.get(f"/api/v1/kpis/ventas-por-hora?fecha={hoy}", headers=auth_headers)
        assert resp.status_code == 200

    # ── Ventas por día de la semana ──

    def test_ventas_por_dia_semana(self, client, auth_headers):
        resp = client.get("/api/v1/kpis/ventas-por-dia-semana", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_ventas_por_dia_semana_con_semanas(self, client, auth_headers):
        resp = client.get("/api/v1/kpis/ventas-por-dia-semana?semanas=8", headers=auth_headers)
        assert resp.status_code == 200

    # ── Top productos ──

    def test_top_productos(self, client, auth_headers):
        resp = client.get("/api/v1/kpis/top-productos", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_top_productos_con_parametros(self, client, auth_headers):
        resp = client.get("/api/v1/kpis/top-productos?dias=7&limite=5", headers=auth_headers)
        assert resp.status_code == 200

    # ── Tendencia de ventas ──

    def test_tendencia_ventas(self, client, auth_headers):
        resp = client.get("/api/v1/kpis/tendencia-ventas", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 30  # default 30 días

    def test_tendencia_ventas_7_dias(self, client, auth_headers):
        resp = client.get("/api/v1/kpis/tendencia-ventas?dias=7", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 7

    def test_tendencia_ventas_estructura(self, client, auth_headers):
        resp = client.get("/api/v1/kpis/tendencia-ventas?dias=1", headers=auth_headers)
        data = resp.json()
        assert len(data) == 1
        assert "fecha" in data[0]
        assert "total" in data[0]
        assert "cantidad" in data[0]

    # ── Ticket promedio ──

    def test_ticket_promedio(self, client, auth_headers):
        resp = client.get("/api/v1/kpis/ticket-promedio", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 30

    def test_ticket_promedio_estructura(self, client, auth_headers):
        resp = client.get("/api/v1/kpis/ticket-promedio?dias=1", headers=auth_headers)
        data = resp.json()
        assert "fecha" in data[0]
        assert "ticket_promedio" in data[0]
        assert "num_ventas" in data[0]

    # ── KPIs de inventario ──

    def test_kpi_inventario(self, client, auth_headers):
        resp = client.get("/api/v1/kpis/inventario", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "productos_stock_bajo" in data
        assert "ingredientes_stock_bajo" in data
        assert "valor_inventario_productos" in data
        assert "lotes_por_vencer_7d" in data

    # ── KPIs de clientes ──

    def test_kpi_clientes(self, client, auth_headers):
        resp = client.get("/api/v1/kpis/clientes", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "total_clientes" in data
        assert "nuevos_mes" in data
        assert "distribucion_niveles" in data

    # ── Métodos de pago ──

    def test_metodos_pago(self, client, auth_headers):
        resp = client.get("/api/v1/kpis/metodos-pago", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_metodos_pago_con_dias(self, client, auth_headers):
        resp = client.get("/api/v1/kpis/metodos-pago?dias=7", headers=auth_headers)
        assert resp.status_code == 200

    # ── Sin autenticación ──

    def test_sin_autenticacion(self, client):
        resp = client.get("/api/v1/kpis/dashboard")
        assert resp.status_code in (401, 403)

    def test_parametros_invalidos(self, client, auth_headers):
        resp = client.get("/api/v1/kpis/tendencia-ventas?dias=0", headers=auth_headers)
        assert resp.status_code == 422

        resp = client.get("/api/v1/kpis/top-productos?limite=0", headers=auth_headers)
        assert resp.status_code == 422
