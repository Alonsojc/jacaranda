"""Tests para pagos online (Conekta sandbox)."""

import base64
import json
from datetime import date

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.core.config import settings


class TestPagos:

    def _post_signed_webhook(self, client, monkeypatch, payload):
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_key = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()
        monkeypatch.setattr(settings, "CONEKTA_WEBHOOK_PUBLIC_KEY", public_key)

        raw_body = json.dumps(payload, separators=(",", ":")).encode()
        signature = private_key.sign(raw_body, padding.PKCS1v15(), hashes.SHA256())
        return client.post(
            "/api/v1/pagos/webhook",
            content=raw_body,
            headers={
                "Content-Type": "application/json",
                "DIGEST": base64.b64encode(signature).decode(),
            },
        )

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

    def test_crear_orden_produccion_no_usa_checkout_fake(self, client, auth_headers, monkeypatch):
        ped = self._crear_pedido(client, auth_headers)
        monkeypatch.setattr(settings, "CONEKTA_SANDBOX_MODE", False)
        monkeypatch.setattr(settings, "CONEKTA_API_KEY", "key_prod_test")
        resp = client.post("/api/v1/pagos/crear-orden", json={
            "pedido_id": ped["id"],
            "metodo": "card",
        }, headers=auth_headers)
        assert resp.status_code == 400
        assert "producción" in resp.json()["detail"]

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

    def test_webhook(self, client, auth_headers, monkeypatch):
        ped = self._crear_pedido(client, auth_headers)
        orden = client.post("/api/v1/pagos/crear-orden", json={
            "pedido_id": ped["id"], "metodo": "card",
        }, headers=auth_headers).json()
        resp = self._post_signed_webhook(client, monkeypatch, {
            "type": "order.paid",
            "data": {"object": {"id": orden["order_id"]}},
        })
        assert resp.status_code == 200
        assert resp.json()["processed"] is True

    def test_webhook_repetido_no_se_reprocesa(self, client, auth_headers, monkeypatch):
        ped = self._crear_pedido(client, auth_headers)
        orden = client.post("/api/v1/pagos/crear-orden", json={
            "pedido_id": ped["id"], "metodo": "card",
        }, headers=auth_headers).json()
        payload = {
            "id": "evt_test_replay_1",
            "type": "order.paid",
            "data": {"object": {"id": orden["order_id"]}},
        }
        resp1 = self._post_signed_webhook(client, monkeypatch, payload)
        resp2 = self._post_signed_webhook(client, monkeypatch, payload)
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert resp1.json()["duplicate"] is False
        assert resp2.json()["duplicate"] is True

    def test_webhook_rechaza_payload_sin_firma(self, client, auth_headers):
        ped = self._crear_pedido(client, auth_headers)
        orden = client.post("/api/v1/pagos/crear-orden", json={
            "pedido_id": ped["id"], "metodo": "card",
        }, headers=auth_headers).json()
        resp = client.post("/api/v1/pagos/webhook", json={
            "type": "order.paid",
            "data": {"object": {"id": orden["order_id"]}},
        })
        assert resp.status_code == 401

    def test_webhook_no_marca_pagado_si_monto_no_coincide(self, client, auth_headers, monkeypatch):
        ped = self._crear_pedido(client, auth_headers)
        orden = client.post("/api/v1/pagos/crear-orden", json={
            "pedido_id": ped["id"], "metodo": "card",
        }, headers=auth_headers).json()
        resp = self._post_signed_webhook(client, monkeypatch, {
            "id": "evt_mismatch_amount",
            "type": "order.paid",
            "data": {"object": {"id": orden["order_id"], "amount": 100, "currency": "MXN"}},
        })
        assert resp.status_code == 200
        assert resp.json()["processed"] is False
        ver = client.get(f"/api/v1/pagos/verificar/{orden['order_id']}", headers=auth_headers)
        assert ver.json()["estado"] == "pendiente"

    def test_historial(self, client, auth_headers):
        resp = client.get("/api/v1/pagos/historial", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_reembolso(self, client, auth_headers, monkeypatch):
        ped = self._crear_pedido(client, auth_headers)
        orden = client.post("/api/v1/pagos/crear-orden", json={
            "pedido_id": ped["id"], "metodo": "card",
        }, headers=auth_headers).json()
        # Pay first via webhook
        self._post_signed_webhook(client, monkeypatch, {
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
