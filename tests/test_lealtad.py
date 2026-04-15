"""Tests para el sistema de lealtad avanzado."""

from datetime import date, timedelta
from decimal import Decimal
import pytest


class TestLealtad:
    """Tests de niveles, cupones, tarjeta QR, cumpleaños."""

    def _crear_cliente(self, client, auth_headers, **kwargs):
        """Helper: crea un cliente."""
        payload = {
            "nombre": "María García",
            "telefono": "4421234567",
            "email": "maria@test.com",
        }
        payload.update(kwargs)
        resp = client.post("/api/v1/clientes/", json=payload, headers=auth_headers)
        assert resp.status_code == 201, f"Crear cliente falló: {resp.json()}"
        return resp.json()["id"]

    def _crear_cupon(self, client, auth_headers, **kwargs):
        """Helper: crea un cupón activo."""
        hoy = date.today()
        payload = {
            "codigo": "DESC10",
            "nombre": "10% descuento",
            "tipo": "porcentaje",
            "valor": "10",
            "fecha_inicio": (hoy - timedelta(days=1)).isoformat(),
            "fecha_fin": (hoy + timedelta(days=30)).isoformat(),
            "max_usos": 100,
        }
        payload.update(kwargs)
        resp = client.post("/api/v1/lealtad/cupones", json=payload, headers=auth_headers)
        assert resp.status_code == 201, f"Crear cupón falló: {resp.json()}"
        return resp.json()

    # ── Niveles ──

    def test_obtener_niveles(self, client, auth_headers):
        resp = client.get("/api/v1/lealtad/niveles", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "niveles" in data
        assert len(data["niveles"]) == 3
        nombres = [n["nivel"] for n in data["niveles"]]
        assert "bronce" in nombres
        assert "plata" in nombres
        assert "oro" in nombres

    def test_niveles_multiplicadores(self, client, auth_headers):
        resp = client.get("/api/v1/lealtad/niveles", headers=auth_headers)
        niveles = resp.json()["niveles"]
        for n in niveles:
            if n["nivel"] == "bronce":
                assert n["multiplicador"] == 1.0
            elif n["nivel"] == "plata":
                assert n["multiplicador"] == 1.5
            elif n["nivel"] == "oro":
                assert n["multiplicador"] == 2.0

    # ── Tarjeta digital QR ──

    def test_obtener_tarjeta_genera_qr(self, client, auth_headers):
        cid = self._crear_cliente(client, auth_headers)
        resp = client.get(f"/api/v1/lealtad/tarjeta/{cid}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["cliente_id"] == cid
        assert data["tarjeta_qr"] is not None
        assert data["nivel"] == "bronce"

    def test_buscar_por_qr(self, client, auth_headers):
        cid = self._crear_cliente(client, auth_headers)
        # Obtener tarjeta (genera QR)
        resp = client.get(f"/api/v1/lealtad/tarjeta/{cid}", headers=auth_headers)
        qr_code = resp.json()["tarjeta_qr"]

        # Buscar por QR
        resp2 = client.get(f"/api/v1/lealtad/tarjeta-qr/{qr_code}", headers=auth_headers)
        assert resp2.status_code == 200
        assert resp2.json()["cliente_id"] == cid

    def test_buscar_qr_inexistente(self, client, auth_headers):
        resp = client.get("/api/v1/lealtad/tarjeta-qr/no-existe-qr", headers=auth_headers)
        assert resp.status_code == 404

    # ── Cupones ──

    def test_crear_cupon(self, client, auth_headers):
        cupon = self._crear_cupon(client, auth_headers)
        assert cupon["codigo"] == "DESC10"
        assert cupon["tipo"] == "porcentaje"
        assert cupon["valor"] == 10.0

    def test_listar_cupones(self, client, auth_headers):
        self._crear_cupon(client, auth_headers)
        resp = client.get("/api/v1/lealtad/cupones", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_validar_cupon_valido(self, client, auth_headers):
        self._crear_cupon(client, auth_headers)
        resp = client.post("/api/v1/lealtad/cupones/validar", json={
            "codigo": "DESC10",
            "monto_compra": "200.00",
        }, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["valid"] is True

    def test_validar_cupon_inexistente(self, client, auth_headers):
        resp = client.post("/api/v1/lealtad/cupones/validar", json={
            "codigo": "NOEXISTE",
        }, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["valid"] is False

    def test_validar_cupon_expirado(self, client, auth_headers):
        hoy = date.today()
        self._crear_cupon(
            client, auth_headers,
            codigo="EXPIRADO",
            nombre="Cupón expirado",
            fecha_inicio=(hoy - timedelta(days=60)).isoformat(),
            fecha_fin=(hoy - timedelta(days=30)).isoformat(),
        )
        resp = client.post("/api/v1/lealtad/cupones/validar", json={
            "codigo": "EXPIRADO",
        }, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["valid"] is False

    def test_validar_cupon_compra_minima(self, client, auth_headers):
        self._crear_cupon(
            client, auth_headers,
            codigo="MIN500",
            nombre="Cupón con mínimo",
            compra_minima="500.00",
        )
        resp = client.post("/api/v1/lealtad/cupones/validar", json={
            "codigo": "MIN500",
            "monto_compra": "100.00",
        }, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["valid"] is False
        assert "minima" in resp.json()["reason"].lower()

    def test_canjear_cupon(self, client, auth_headers):
        cid = self._crear_cliente(client, auth_headers)
        self._crear_cupon(client, auth_headers)

        # Crear una venta para el canje
        resp = client.post("/api/v1/punto-de-venta/venta", json={
            "metodo_pago": "efectivo",
            "items": [{"producto_id": None, "nombre": "Pan", "cantidad": 1,
                        "precio_unitario": "20.00", "tasa_iva": "0.00"}],
        }, headers=auth_headers)
        # May or may not create a venta depending on implementation
        # Use venta_id=1 as fallback
        venta_id = resp.json().get("id", 1) if resp.status_code in (200, 201) else 1

        resp2 = client.post("/api/v1/lealtad/cupones/canjear", json={
            "codigo": "DESC10",
            "cliente_id": cid,
            "venta_id": venta_id,
        }, headers=auth_headers)
        assert resp2.status_code == 200
        assert "canjeado" in resp2.json()["mensaje"].lower()

    # ── Cumpleaños ──

    def test_cumpleanos_del_mes(self, client, auth_headers):
        # Crear cliente con cumpleaños este mes
        hoy = date.today()
        self._crear_cliente(
            client, auth_headers,
            nombre="Cumpleañero",
            fecha_cumpleanos=hoy.replace(day=15).isoformat(),
        )
        resp = client.get("/api/v1/lealtad/cumpleanos", headers=auth_headers)
        assert resp.status_code == 200
        nombres = [c["nombre"] for c in resp.json()]
        assert "Cumpleañero" in nombres

    def test_enviar_ofertas_cumpleanos(self, client, auth_headers):
        hoy = date.today()
        self._crear_cliente(
            client, auth_headers,
            nombre="Cumple Test",
            fecha_cumpleanos=hoy.replace(day=10).isoformat(),
        )
        resp = client.post("/api/v1/lealtad/cumpleanos/enviar-ofertas", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "cupones" in data
        assert data["cupones"][0]["nombre"] == "Cumple Test"

    # ── Historial ──

    def test_historial_puntos_vacio(self, client, auth_headers):
        cid = self._crear_cliente(client, auth_headers)
        resp = client.get(f"/api/v1/lealtad/historial/{cid}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    # ── Dashboard ──

    def test_dashboard_lealtad(self, client, auth_headers):
        resp = client.get("/api/v1/lealtad/dashboard", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "clientes_por_nivel" in data
        assert "total_puntos_circulacion" in data
        assert "cupones_activos" in data

    # ── Unit tests del servicio ──

    def test_calcular_nivel(self):
        from app.services.lealtad_service import calcular_nivel
        from app.models.lealtad import NivelLealtad

        assert calcular_nivel(0) == NivelLealtad.BRONCE
        assert calcular_nivel(499) == NivelLealtad.BRONCE
        assert calcular_nivel(500) == NivelLealtad.PLATA
        assert calcular_nivel(1499) == NivelLealtad.PLATA
        assert calcular_nivel(1500) == NivelLealtad.ORO
        assert calcular_nivel(5000) == NivelLealtad.ORO

    def test_multiplicador_puntos(self):
        from app.services.lealtad_service import multiplicador_puntos
        from app.models.lealtad import NivelLealtad

        assert multiplicador_puntos(NivelLealtad.BRONCE) == 1.0
        assert multiplicador_puntos(NivelLealtad.PLATA) == 1.5
        assert multiplicador_puntos(NivelLealtad.ORO) == 2.0
