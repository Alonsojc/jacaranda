"""Tests para el módulo de pedidos."""

from datetime import date, timedelta
import pytest


class TestPedidos:
    """Tests del flujo de pedidos especiales."""

    def _crear_producto(self, client, auth_headers, codigo="PED-001", stock=0):
        resp = client.post("/api/v1/inventario/productos", json={
            "codigo": codigo,
            "nombre": f"Producto {codigo}",
            "precio_unitario": "100.00",
            "costo_produccion": "40.00",
            "tasa_iva": "0.00",
        }, headers=auth_headers)
        assert resp.status_code == 201, resp.text
        pid = resp.json()["id"]
        if stock:
            mov = client.post("/api/v1/inventario/movimientos", json={
                "tipo": "entrada_ajuste",
                "producto_id": pid,
                "cantidad": str(stock),
                "referencia": "Stock inicial pedidos",
            }, headers=auth_headers)
            assert mov.status_code == 201, mov.text
        return pid

    def _crear_pedido(self, client, auth_headers, **kwargs):
        payload = {
            "cliente_nombre": "María López",
            "cliente_telefono": "4421234567",
            "fecha_entrega": (date.today() + timedelta(days=2)).isoformat(),
            "hora_entrega": "14:00",
            "origen": "whatsapp",
            "detalles": [
                {"descripcion": "Pastel 3 leches", "cantidad": 1, "precio_unitario": "350.00"},
                {"descripcion": "Pan de muerto x6", "cantidad": 6, "precio_unitario": "45.00"},
            ],
        }
        payload.update(kwargs)
        return client.post("/api/v1/pedidos/", json=payload, headers=auth_headers)

    def test_crear_pedido(self, client, auth_headers):
        resp = self._crear_pedido(client, auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["cliente_nombre"] == "María López"
        assert len(data["detalles"]) == 2
        assert data["estado"] == "recibido"

    def test_crear_pedido_idempotente(self, client, auth_headers):
        key = "pedido-test-idempotente-1"
        resp1 = self._crear_pedido(client, auth_headers, idempotency_key=key)
        resp2 = self._crear_pedido(client, auth_headers, idempotency_key=key)
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert resp2.json()["id"] == resp1.json()["id"]
        assert resp2.json()["folio"] == resp1.json()["folio"]

    def test_listar_pedidos(self, client, auth_headers):
        self._crear_pedido(client, auth_headers)
        resp = client.get("/api/v1/pedidos/", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_pedidos_hoy(self, client, auth_headers):
        # Crear pedido para hoy
        self._crear_pedido(
            client, auth_headers,
            fecha_entrega=date.today().isoformat(),
        )
        resp = client.get("/api/v1/pedidos/hoy", headers=auth_headers)
        assert resp.status_code == 200

    def test_obtener_pedido(self, client, auth_headers):
        resp = self._crear_pedido(client, auth_headers)
        pid = resp.json()["id"]
        resp2 = client.get(f"/api/v1/pedidos/{pid}", headers=auth_headers)
        assert resp2.status_code == 200
        assert resp2.json()["id"] == pid

    def test_obtener_pedido_inexistente(self, client, auth_headers):
        resp = client.get("/api/v1/pedidos/99999", headers=auth_headers)
        assert resp.status_code == 404

    def test_actualizar_estado_pedido(self, client, auth_headers):
        resp = self._crear_pedido(client, auth_headers)
        pid = resp.json()["id"]
        resp2 = client.patch(
            f"/api/v1/pedidos/{pid}/estado",
            json={"estado": "confirmado"},
            headers=auth_headers,
        )
        assert resp2.status_code == 200
        assert resp2.json()["estado"] == "confirmado"

    def test_no_permite_saltar_estado_pedido(self, client, auth_headers):
        resp = self._crear_pedido(client, auth_headers)
        pid = resp.json()["id"]
        resp2 = client.patch(
            f"/api/v1/pedidos/{pid}/estado",
            json={"estado": "entregado"},
            headers=auth_headers,
        )
        assert resp2.status_code == 400
        assert "transición inválida" in resp2.json()["detail"].lower()

    def test_no_permite_marcar_pagado_en_edicion_general(self, client, auth_headers):
        resp = self._crear_pedido(client, auth_headers)
        pid = resp.json()["id"]
        resp2 = client.patch(
            f"/api/v1/pedidos/{pid}",
            json={"pagado": True},
            headers=auth_headers,
        )
        assert resp2.status_code == 400

    def test_pedido_con_anticipo(self, client, auth_headers):
        resp = self._crear_pedido(client, auth_headers, anticipo="200.00")
        assert resp.status_code == 200
        data = resp.json()
        assert float(data["anticipo"]) == 200.00

    def test_pedido_con_notas(self, client, auth_headers):
        resp = self._crear_pedido(
            client, auth_headers,
            notas="Sin azúcar",
            notas_internas="Cliente frecuente",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["notas"] == "Sin azúcar"

    def test_pedido_permite_producto_agotado_para_producir_despues(self, client, auth_headers):
        pid = self._crear_producto(client, auth_headers, "PED-RES", stock=0)
        resp = self._crear_pedido(
            client,
            auth_headers,
            detalles=[{
                "producto_id": pid,
                "descripcion": "Pastel reservado",
                "cantidad": 2,
                "precio_unitario": "100.00",
            }],
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["detalles"][0]["producto_id"] == pid
        assert data["detalles"][0]["cantidad"] == 2

    def test_capacidad_diaria_de_pedidos(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr(
            "app.services.pedido_service.settings.PEDIDOS_CAPACIDAD_DIARIA", 1
        )
        fecha = (date.today() + timedelta(days=3)).isoformat()
        primero = self._crear_pedido(client, auth_headers, fecha_entrega=fecha)
        segundo = self._crear_pedido(
            client,
            auth_headers,
            fecha_entrega=fecha,
            cliente_nombre="Cliente excedente",
        )
        assert primero.status_code == 200
        assert segundo.status_code == 400
        assert "capacidad diaria llena" in segundo.json()["detail"].lower()
