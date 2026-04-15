"""Tests para el modulo de reportes fiscales SAT (fiscal_service / rutas /api/v1/fiscal/)."""

from datetime import date

import pytest


CURRENT_MONTH = date.today().month
CURRENT_YEAR = date.today().year


class TestFiscal:
    """Tests de los endpoints de reportes fiscales SAT."""

    # ── DIOT ─────────────────────────────────────────────────────────

    def test_diot_mes_actual(self, client, auth_headers):
        """DIOT del mes y anio actuales devuelve 200 y una lista."""
        resp = client.get(
            f"/api/v1/fiscal/diot?mes={CURRENT_MONTH}&anio={CURRENT_YEAR}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_diot_sin_parametros_falla(self, client, auth_headers):
        """DIOT sin mes ni anio devuelve 422 (parametros requeridos)."""
        resp = client.get("/api/v1/fiscal/diot", headers=auth_headers)
        assert resp.status_code == 422

    def test_diot_sin_autenticacion(self, client):
        """DIOT sin token devuelve 401 o 403."""
        resp = client.get(
            f"/api/v1/fiscal/diot?mes={CURRENT_MONTH}&anio={CURRENT_YEAR}"
        )
        assert resp.status_code in (401, 403)

    # ── IVA mensual ──────────────────────────────────────────────────

    def test_iva_mensual(self, client, auth_headers):
        """Declaracion IVA mensual devuelve 200 con claves iva_causado y iva_acreditable."""
        resp = client.get(
            f"/api/v1/fiscal/iva-mensual?mes={CURRENT_MONTH}&anio={CURRENT_YEAR}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        assert "iva_causado" in data
        assert "iva_acreditable" in data

    def test_iva_mensual_estructura_completa(self, client, auth_headers):
        """La respuesta IVA incluye todas las claves esperadas del calculo."""
        resp = client.get(
            f"/api/v1/fiscal/iva-mensual?mes={CURRENT_MONTH}&anio={CURRENT_YEAR}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        for key in ("iva_causado", "iva_acreditable", "iva_a_pagar", "saldo_a_favor"):
            assert key in data, f"Falta clave '{key}' en respuesta IVA"
        assert data["mes"] == CURRENT_MONTH
        assert data["anio"] == CURRENT_YEAR

    def test_iva_mes_invalido_falla(self, client, auth_headers):
        """IVA con mes fuera de rango (0 o 13) devuelve 422."""
        resp = client.get(
            f"/api/v1/fiscal/iva-mensual?mes=13&anio={CURRENT_YEAR}",
            headers=auth_headers,
        )
        assert resp.status_code == 422

    def test_iva_mes_cero_falla(self, client, auth_headers):
        """IVA con mes=0 devuelve 422."""
        resp = client.get(
            f"/api/v1/fiscal/iva-mensual?mes=0&anio={CURRENT_YEAR}",
            headers=auth_headers,
        )
        assert resp.status_code == 422

    # ── ISR provisional ──────────────────────────────────────────────

    def test_isr_provisional(self, client, auth_headers):
        """ISR provisional devuelve 200 con clave ingresos_acumulados."""
        resp = client.get(
            f"/api/v1/fiscal/isr-provisional?mes={CURRENT_MONTH}&anio={CURRENT_YEAR}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        assert "ingresos_acumulados" in data

    def test_isr_provisional_valores_numericos(self, client, auth_headers):
        """ISR provisional retorna numeros validos (>= 0) en todos los campos monetarios."""
        resp = client.get(
            f"/api/v1/fiscal/isr-provisional?mes={CURRENT_MONTH}&anio={CURRENT_YEAR}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        numeric_keys = (
            "ingresos_acumulados",
            "coeficiente_utilidad",
            "utilidad_fiscal",
            "tasa_isr",
            "isr_causado",
            "pagos_provisionales_anteriores",
            "isr_a_pagar",
        )
        for key in numeric_keys:
            assert key in data, f"Falta clave '{key}' en respuesta ISR"
            assert isinstance(data[key], (int, float)), f"'{key}' no es numerico"
            assert data[key] >= 0, f"'{key}' es negativo"

    # ── Catalogo contabilidad electronica ────────────────────────────

    def test_catalogo_contabilidad_electronica(self, client, auth_headers):
        """Catalogo de contabilidad electronica devuelve 200 y una lista."""
        resp = client.get(
            "/api/v1/fiscal/contabilidad-electronica/catalogo",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_catalogo_sin_autenticacion(self, client):
        """Catalogo sin token devuelve 401 o 403."""
        resp = client.get("/api/v1/fiscal/contabilidad-electronica/catalogo")
        assert resp.status_code in (401, 403)

    # ── Balanza de comprobacion ───────────────────────────────────────

    def test_balanza_comprobacion(self, client, auth_headers):
        """Balanza de comprobacion devuelve 200 y una lista."""
        resp = client.get(
            f"/api/v1/fiscal/contabilidad-electronica/balanza?mes={CURRENT_MONTH}&anio={CURRENT_YEAR}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_balanza_sin_parametros_falla(self, client, auth_headers):
        """Balanza sin mes ni anio devuelve 422."""
        resp = client.get(
            "/api/v1/fiscal/contabilidad-electronica/balanza",
            headers=auth_headers,
        )
        assert resp.status_code == 422

    # ── Reporte completo ─────────────────────────────────────────────

    def test_reporte_completo(self, client, auth_headers):
        """Reporte fiscal completo devuelve 200 y un dict con las secciones esperadas."""
        resp = client.get(
            f"/api/v1/fiscal/reporte-completo?mes={CURRENT_MONTH}&anio={CURRENT_YEAR}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        for section in ("diot", "iva_mensual", "isr_provisional", "contabilidad_electronica"):
            assert section in data, f"Falta seccion '{section}' en reporte completo"

    def test_reporte_completo_contiene_periodo(self, client, auth_headers):
        """Reporte completo incluye el mes y anio solicitados en la respuesta."""
        resp = client.get(
            f"/api/v1/fiscal/reporte-completo?mes={CURRENT_MONTH}&anio={CURRENT_YEAR}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["mes"] == CURRENT_MONTH
        assert data["anio"] == CURRENT_YEAR

    def test_reporte_completo_sin_autenticacion(self, client):
        """Reporte completo sin token devuelve 401 o 403."""
        resp = client.get(
            f"/api/v1/fiscal/reporte-completo?mes={CURRENT_MONTH}&anio={CURRENT_YEAR}"
        )
        assert resp.status_code in (401, 403)
