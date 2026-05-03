"""Tests para el módulo de clientes."""

import pytest


class TestClientes:
    """Tests de gestión de clientes."""

    def _crear_cliente(self, client, auth_headers, **kwargs):
        payload = {
            "nombre": "Juan Pérez",
            "telefono": "4429876543",
            "email": "juan@example.com",
        }
        payload.update(kwargs)
        return client.post("/api/v1/clientes/", json=payload, headers=auth_headers)

    def test_crear_cliente(self, client, auth_headers):
        resp = self._crear_cliente(client, auth_headers)
        assert resp.status_code == 201
        assert resp.json()["nombre"] == "Juan Pérez"

    def test_listar_clientes(self, client, auth_headers):
        self._crear_cliente(client, auth_headers)
        resp = client.get("/api/v1/clientes/", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_buscar_cliente_por_nombre(self, client, auth_headers):
        self._crear_cliente(client, auth_headers)
        resp = client.get("/api/v1/clientes/?q=Juan", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_buscar_cliente_sin_resultados(self, client, auth_headers):
        resp = client.get("/api/v1/clientes/?q=ZZZZNOEXISTE", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) == 0

    def test_obtener_cliente(self, client, auth_headers):
        resp = self._crear_cliente(client, auth_headers)
        cid = resp.json()["id"]
        resp2 = client.get(f"/api/v1/clientes/{cid}", headers=auth_headers)
        assert resp2.status_code == 200
        assert resp2.json()["id"] == cid

    def test_actualizar_cliente(self, client, auth_headers):
        resp = self._crear_cliente(client, auth_headers)
        cid = resp.json()["id"]
        resp2 = client.put(f"/api/v1/clientes/{cid}", json={
            "nombre": "Juan Actualizado",
        }, headers=auth_headers)
        assert resp2.status_code == 200
        assert resp2.json()["nombre"] == "Juan Actualizado"

    def test_actualizar_no_permite_campos_prohibidos(self, client, auth_headers):
        """Verificar que el whitelist de setattr funciona."""
        resp = self._crear_cliente(client, auth_headers)
        cid = resp.json()["id"]
        # Intentar inyectar campo no permitido
        resp2 = client.put(f"/api/v1/clientes/{cid}", json={
            "nombre": "Test",
            "puntos_acumulados": 999999,
        }, headers=auth_headers)
        assert resp2.status_code == 200
        # Verificar que puntos no se modificaron
        resp3 = client.get(f"/api/v1/clientes/{cid}/puntos", headers=auth_headers)
        assert resp3.json()["puntos"] == 0

    def test_consultar_puntos(self, client, auth_headers):
        resp = self._crear_cliente(client, auth_headers)
        cid = resp.json()["id"]
        resp2 = client.get(f"/api/v1/clientes/{cid}/puntos", headers=auth_headers)
        assert resp2.status_code == 200
        assert resp2.json()["puntos"] == 0
        assert "valor_punto" in resp2.json()

    def test_canjear_puntos_insuficientes(self, client, auth_headers):
        resp = self._crear_cliente(client, auth_headers)
        cid = resp.json()["id"]
        resp2 = client.post(
            f"/api/v1/clientes/{cid}/canjear-puntos?puntos=100",
            headers=auth_headers,
        )
        assert resp2.status_code == 400
        assert "insuficientes" in resp2.json()["detail"].lower()

    def test_canjear_puntos_solo_cotiza_no_descuenta(self, client, auth_headers, db):
        from app.models.cliente import Cliente

        resp = self._crear_cliente(client, auth_headers)
        cid = resp.json()["id"]
        cliente = db.query(Cliente).filter(Cliente.id == cid).first()
        cliente.puntos_acumulados = 50
        db.commit()

        resp2 = client.post(
            f"/api/v1/clientes/{cid}/canjear-puntos?puntos=10",
            headers=auth_headers,
        )
        assert resp2.status_code == 200
        assert resp2.json()["descuento"] == 5.0
        assert resp2.json()["puntos_restantes"] == 40
        assert resp2.json()["requiere_venta"] is True

        puntos = client.get(f"/api/v1/clientes/{cid}/puntos", headers=auth_headers)
        assert puntos.json()["puntos"] == 50

    def test_cliente_con_datos_fiscales(self, client, auth_headers):
        resp = self._crear_cliente(client, auth_headers,
            rfc="XAXX010101000",
            razon_social="PÚBLICO EN GENERAL",
            regimen_fiscal="616",
            domicilio_fiscal_cp="76146",
            uso_cfdi="S01",
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["rfc"] == "XAXX010101000"
