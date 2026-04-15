"""Tests para punto de equilibrio y flujo de efectivo."""

import pytest


class TestPuntoEquilibrio:
    """Tests del endpoint de punto de equilibrio."""

    def test_punto_equilibrio_default(self, client, auth_headers):
        resp = client.get("/api/v1/reportes/punto-equilibrio", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "punto_equilibrio_pesos" in data
        assert "margen_contribucion_pct" in data
        assert "es_rentable" in data
        assert "costos_fijos_mensuales" in data
        assert "ticket_promedio" in data
        assert "excedente_sobre_pe" in data

    def test_punto_equilibrio_custom_dias(self, client, auth_headers):
        resp = client.get("/api/v1/reportes/punto-equilibrio?dias=60", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["dias_analizados"] == 60

    def test_punto_equilibrio_requires_auth(self, client):
        resp = client.get("/api/v1/reportes/punto-equilibrio")
        assert resp.status_code in (401, 403)


class TestFlujoEfectivo:
    """Tests del endpoint de flujo de efectivo proyectado."""

    def test_flujo_efectivo_default(self, client, auth_headers):
        resp = client.get("/api/v1/reportes/flujo-efectivo", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "meses_proyectados" in data
        assert "ingreso_promedio_mensual" in data
        assert "proyeccion" in data
        assert len(data["proyeccion"]) == 3

    def test_flujo_efectivo_custom_meses(self, client, auth_headers):
        resp = client.get("/api/v1/reportes/flujo-efectivo?meses=6", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()["proyeccion"]) == 6

    def test_flujo_efectivo_includes_desglose(self, client, auth_headers):
        resp = client.get("/api/v1/reportes/flujo-efectivo", headers=auth_headers)
        data = resp.json()
        assert "desglose_gastos" in data
        assert "nomina_mensual" in data
        assert "total_egresos_mensuales" in data

    def test_flujo_efectivo_requires_auth(self, client):
        resp = client.get("/api/v1/reportes/flujo-efectivo")
        assert resp.status_code in (401, 403)
