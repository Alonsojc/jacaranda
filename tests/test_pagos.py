"""Tests para pagos online (Conekta sandbox)."""

from datetime import date


class TestPagos:

    def _crear_pedido(self, client, auth_headers):
        resp = client.post("/api/v1/pedidos/", json={
            "cliente_nombre": "Cliente Pago",
            "fecha_entrega": date.today().isoformat(),
            "detalles": [{"descripcion": "Pastel Test", "cantidad": 1, "precio_unitario": "500.00"}],
        }, headers=auth_headers)
        assert resp.status_code == 200, resp.text
        return resp.json()

    def test_crear_orden_card(self, client, auth_headers):
        ped = self._crear_pedido(client, auth_headers)
        resp = client.post("/api/v1/pagos/crear-orden", json={
            "pedido_id": ped["id"],
            "metodo": "card",
        }, headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["sandbox"] is True
        assert "order_id" in data
        assert "checkout_url" in data
        assert data["metodo"] == "card"

    def test_crear_orden_oxxo(self, client, auth_headers):
        ped = self._crear_pedido(client, auth_headers)
        resp = client.post("/api/v1/pagos/crear-orden", json={
            "pedido_id": ped["id"],
            "metodo": "oxxo",
        }, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["referencia"] is not None

    def test_crear_orden_spei(self, client, auth_headers):
        ped = self._crear_pedido(client, auth_headers)
        resp = client.post("/api/v1/pagos/crear-orden", json={
            "pedido_id": ped["id"],
            "metodo": "spei",
        }, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["referencia"] is not None

    def test_crear_orden_metodo_invalido(self, client, auth_headers):
        ped = self._crear_pedido(client, auth_headers)
        resp = client.post("/api/v1/pagos/crear-orden", json={
            "pedido_id": ped["id"],
            "metodo": "bitcoin",
        }, headers=auth_headers)
        assert resp.status_code == 400

    def test_crear_orden_pedido_inexistente(self, client, auth_headers):
        resp = client.post("/api/v1/pagos/crear-orden", json={
            "pedido_id": 99999,
            "metodo": "card",
        }, headers=auth_headers)
        assert resp.status_code == 400

    def test_verificar_pago(self, client, auth_headers):
        ped = self._crear_pedido(client, auth_headers)
        orden = client.post("/api/v1/pagos/crear-orden", json={
            "pedido_id": ped["id"], "metodo": "card",
        }, headers=auth_headers).json()
        resp = client.get(f"/api/v1/pagos/verificar/{orden['order_id']}",
                          headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["estado"] == "pendiente"

    def test_verificar_pago_inexistente(self, client, auth_headers):
        resp = client.get("/api/v1/pagos/verificar/no_existe",
                          headers=auth_headers)
        assert resp.status_code == 404

    def test_webhook(self, client, auth_headers):
        ped = self._crear_pedido(client, auth_headers)
        orden = client.post("/api/v1/pagos/crear-orden", json={
            "pedido_id": ped["id"], "metodo": "card",
        }, headers=auth_headers).json()
        resp = client.post("/api/v1/pagos/webhook", json={
            "type": "order.paid",
            "data": {"object": {"id": orden["order_id"]}},
        })
        assert resp.status_code == 200
        assert resp.json()["processed"] is True

    def test_historial(self, client, auth_headers):
        resp = client.get("/api/v1/pagos/historial", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_reembolso(self, client, auth_headers):
        ped = self._crear_pedido(client, auth_headers)
        orden = client.post("/api/v1/pagos/crear-orden", json={
            "pedido_id": ped["id"], "metodo": "card",
        }, headers=auth_headers).json()
        # Pay first via webhook
        client.post("/api/v1/pagos/webhook", json={
            "type": "order.paid",
            "data": {"object": {"id": orden["order_id"]}},
        })
        # Now refund
        pago_id = client.get(f"/api/v1/pagos/verificar/{orden['order_id']}",
                             headers=auth_headers).json()
        resp = client.post("/api/v1/pagos/reembolso", json={
            "pago_id": 1,
        }, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["estado"] == "reembolsado"

    def test_sin_autenticacion(self, client):
        resp = client.get("/api/v1/pagos/historial")
        assert resp.status_code in (401, 403)
