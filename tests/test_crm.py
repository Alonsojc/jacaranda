"""Tests para el módulo de CRM/Marketing."""

from datetime import date, timedelta
import pytest


class TestCRM:
    """Tests de CRM: segmentación, campañas, encuestas, interacciones, churn y dashboard."""

    def _crear_cliente(self, client, auth_headers, nombre="Cliente CRM"):
        resp = client.post("/api/v1/clientes/", json={"nombre": nombre}, headers=auth_headers)
        assert resp.status_code == 201
        return resp.json()["id"]

    def _crear_campana(self, client, auth_headers, **kwargs):
        hoy = date.today()
        payload = {
            "nombre": "Campaña Test",
            "tipo": "email",
            "mensaje": "Mensaje de prueba para campaña.",
            "fecha_inicio": hoy.isoformat(),
        }
        payload.update(kwargs)
        resp = client.post("/api/v1/crm/campanas", json=payload, headers=auth_headers)
        assert resp.status_code == 201, f"Crear campaña falló: {resp.json()}"
        return resp.json()

    # ── Segmentación ──

    def test_segmentacion(self, client, auth_headers):
        """GET /segmentacion devuelve resumen de segmentación."""
        resp = client.get("/api/v1/crm/segmentacion", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_segmentacion_detalle(self, client, auth_headers):
        """GET /segmentacion/detalle devuelve segmentación detallada."""
        resp = client.get("/api/v1/crm/segmentacion/detalle", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (dict, list))

    # ── Clientes en riesgo ──

    def test_clientes_en_riesgo(self, client, auth_headers):
        """GET /clientes-en-riesgo devuelve una lista."""
        resp = client.get("/api/v1/crm/clientes-en-riesgo", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    # ── Campañas ──

    def test_crear_campana(self, client, auth_headers):
        """POST /campanas crea una campaña y retorna 201."""
        hoy = date.today()
        campana = self._crear_campana(client, auth_headers)
        assert "id" in campana
        assert campana["nombre"] == "Campaña Test"
        assert campana["tipo"] == "email"

    def test_listar_campanas(self, client, auth_headers):
        """GET /campanas lista las campañas existentes."""
        self._crear_campana(client, auth_headers)
        resp = client.get("/api/v1/crm/campanas", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_ejecutar_campana(self, client, auth_headers):
        """POST /campanas/{id}/ejecutar ejecuta la campaña."""
        campana = self._crear_campana(client, auth_headers)
        cid = campana["id"]
        resp = client.post(f"/api/v1/crm/campanas/{cid}/ejecutar", headers=auth_headers)
        assert resp.status_code in (200, 202)
        data = resp.json()
        assert isinstance(data, dict)

    # ── Encuestas ──

    def test_registrar_encuesta(self, client, auth_headers):
        """POST /encuestas registra una encuesta de satisfacción."""
        cliente_id = self._crear_cliente(client, auth_headers, nombre="Cliente Encuesta")
        payload = {
            "cliente_id": cliente_id,
            "calificacion": 5,
            "categoria": "servicio",
        }
        resp = client.post("/api/v1/crm/encuestas", json=payload, headers=auth_headers)
        assert resp.status_code in (200, 201)
        data = resp.json()
        assert isinstance(data, dict)

    def test_resumen_encuestas(self, client, auth_headers):
        """GET /encuestas/resumen devuelve resumen de encuestas."""
        resp = client.get("/api/v1/crm/encuestas/resumen", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    # ── Interacciones ──

    def test_registrar_interaccion(self, client, auth_headers):
        """POST /interacciones registra una interacción con el cliente."""
        cliente_id = self._crear_cliente(client, auth_headers, nombre="Cliente Interacción")
        payload = {
            "cliente_id": cliente_id,
            "tipo": "seguimiento",
            "canal": "telefono",
            "descripcion": "Llamada de seguimiento post-venta.",
        }
        resp = client.post("/api/v1/crm/interacciones", json=payload, headers=auth_headers)
        assert resp.status_code in (200, 201)
        data = resp.json()
        assert isinstance(data, dict)

    def test_listar_interacciones_cliente(self, client, auth_headers):
        """GET /interacciones/{cliente_id} lista interacciones del cliente."""
        cliente_id = self._crear_cliente(client, auth_headers, nombre="Cliente Interacciones")
        # Registrar al menos una interacción primero
        client.post("/api/v1/crm/interacciones", json={
            "cliente_id": cliente_id,
            "tipo": "consulta",
            "canal": "presencial",
            "descripcion": "Visita a la tienda.",
        }, headers=auth_headers)

        resp = client.get(f"/api/v1/crm/interacciones/{cliente_id}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    # ── Predicción churn ──

    def test_prediccion_churn(self, client, auth_headers):
        """GET /prediccion-churn devuelve resultados de predicción."""
        resp = client.get("/api/v1/crm/prediccion-churn", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (dict, list))

    # ── Dashboard ──

    def test_dashboard_crm(self, client, auth_headers):
        """GET /dashboard devuelve el dashboard del CRM."""
        resp = client.get("/api/v1/crm/dashboard", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
