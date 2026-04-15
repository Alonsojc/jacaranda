"""Tests para el módulo de contabilidad."""

from datetime import date
import pytest


class TestContabilidad:
    """Tests de contabilidad y partida doble."""

    def test_seedear_catalogo(self, client, auth_headers):
        """Seedear catálogo de cuentas SAT."""
        resp = client.post("/api/v1/contabilidad/cuentas/seed", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["cuentas_creadas"] > 0

    def test_seedear_catalogo_idempotente(self, client, auth_headers):
        """Segundo seed no crea cuentas duplicadas."""
        client.post("/api/v1/contabilidad/cuentas/seed", headers=auth_headers)
        resp = client.post("/api/v1/contabilidad/cuentas/seed", headers=auth_headers)
        assert resp.json()["cuentas_creadas"] == 0

    def test_listar_cuentas(self, client, auth_headers):
        client.post("/api/v1/contabilidad/cuentas/seed", headers=auth_headers)
        resp = client.get("/api/v1/contabilidad/cuentas", headers=auth_headers)
        assert resp.status_code == 200
        catalogo = resp.json()
        assert len(catalogo) > 0  # Grouped by tipo
        # Flatten all cuentas
        codigos = [c["codigo"] for cuentas in catalogo.values() for c in cuentas]
        assert "1101" in codigos  # Caja
        assert "4101" in codigos  # Ventas de pan

    def test_crear_asiento_partida_doble(self, client, auth_headers):
        """Crear asiento contable con partida doble balanceada."""
        client.post("/api/v1/contabilidad/cuentas/seed", headers=auth_headers)
        resp = client.post("/api/v1/contabilidad/asientos", json={
            "fecha": date.today().isoformat(),
            "concepto": "Venta de pan al contado",
            "tipo": "ingreso",
            "lineas": [
                {"cuenta_codigo": "1101", "debe": "150.00", "haber": "0.00"},
                {"cuenta_codigo": "4101", "debe": "0.00", "haber": "150.00"},
            ],
        }, headers=auth_headers)
        assert resp.status_code == 201
        data = resp.json()
        assert data["concepto"] == "Venta de pan al contado"
        assert data["numero"].startswith("I-")

    def test_asiento_desbalanceado_falla(self, client, auth_headers):
        """Partida doble: debe != haber debe fallar."""
        client.post("/api/v1/contabilidad/cuentas/seed", headers=auth_headers)
        resp = client.post("/api/v1/contabilidad/asientos", json={
            "fecha": date.today().isoformat(),
            "concepto": "Asiento desbalanceado",
            "tipo": "diario",
            "lineas": [
                {"cuenta_codigo": "1101", "debe": "100.00", "haber": "0.00"},
                {"cuenta_codigo": "4101", "debe": "0.00", "haber": "50.00"},
            ],
        }, headers=auth_headers)
        assert resp.status_code == 400
        assert "descuadrado" in resp.json()["detail"].lower()

    def test_balance_general(self, client, auth_headers):
        client.post("/api/v1/contabilidad/cuentas/seed", headers=auth_headers)
        resp = client.get("/api/v1/contabilidad/balance-general", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "activos" in data
        assert "pasivos" in data
        assert "capital" in data

    def test_estado_resultados(self, client, auth_headers):
        client.post("/api/v1/contabilidad/cuentas/seed", headers=auth_headers)
        hoy = date.today()
        inicio = date(hoy.year, hoy.month, 1).isoformat()
        resp = client.get(
            f"/api/v1/contabilidad/estado-resultados?fecha_inicio={inicio}&fecha_fin={hoy.isoformat()}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "ingresos_brutos" in data
        assert "utilidad_neta" in data or "utilidad_antes_isr" in data
