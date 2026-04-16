"""Tests para delivery tracking."""

from datetime import date


class TestDelivery:

    def _crear_pedido(self, client, auth_headers):
        resp = client.post("/api/v1/pedidos/", json={
            "cliente_nombre": "Cliente Delivery",
            "cliente_telefono": "4421234567",
            "fecha_entrega": date.today().isoformat(),
            "hora_entrega": "14:00",
            "lugar_entrega": "Av. Universidad 100, Querétaro",
            "origen": "whatsapp",
            "detalles": [{"descripcion": "Pastel Chocolate", "cantidad": 1, "precio_unitario": "500.00"}],
        }, headers=auth_headers)
        assert resp.status_code == 200, resp.text
        return resp.json()

    def _preparar_pedido(self, client, auth_headers, pedido_id):
        """Move pedido to LISTO state."""
        client.patch(f"/api/v1/pedidos/{pedido_id}",
                     json={"estado": "confirmado"}, headers=auth_headers)
        client.patch(f"/api/v1/pedidos/{pedido_id}",
                     json={"estado": "en_preparacion"}, headers=auth_headers)
        client.patch(f"/api/v1/pedidos/{pedido_id}",
                     json={"estado": "listo"}, headers=auth_headers)

    def test_marcar_en_ruta(self, client, auth_headers):
        ped = self._crear_pedido(client, auth_headers)
        self._preparar_pedido(client, auth_headers, ped["id"])
        resp = client.post(f"/api/v1/delivery/{ped['id']}/en-ruta", json={
            "repartidor_nombre": "Juan Pérez",
            "repartidor_telefono": "4429876543",
        }, headers=auth_headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["estado"] == "en_ruta"

    def test_marcar_entregado(self, client, auth_headers):
        ped = self._crear_pedido(client, auth_headers)
        self._preparar_pedido(client, auth_headers, ped["id"])
        client.post(f"/api/v1/delivery/{ped['id']}/en-ruta", json={
            "repartidor_nombre": "Juan",
        }, headers=auth_headers)
        resp = client.post(f"/api/v1/delivery/{ped['id']}/entregado",
                           headers=auth_headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["estado"] == "entregado"

    def test_listar_en_ruta(self, client, auth_headers):
        resp = client.get("/api/v1/delivery/en-ruta", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_tracking_publico(self, client, auth_headers):
        ped = self._crear_pedido(client, auth_headers)
        folio = ped["folio"]
        resp = client.get(f"/api/v1/delivery/tracking/{folio}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["folio"] == folio

    def test_tracking_folio_inexistente(self, client):
        resp = client.get("/api/v1/delivery/tracking/NOEXISTE")
        assert resp.status_code == 404

    def test_dashboard_delivery(self, client, auth_headers):
        resp = client.get("/api/v1/delivery/dashboard", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "en_ruta" in data
        assert "entregados_hoy" in data

    def test_en_ruta_pedido_inexistente(self, client, auth_headers):
        resp = client.post("/api/v1/delivery/99999/en-ruta", json={
            "repartidor_nombre": "Test",
        }, headers=auth_headers)
        assert resp.status_code == 404

    def test_sin_autenticacion(self, client):
        resp = client.get("/api/v1/delivery/en-ruta")
        assert resp.status_code in (401, 403)

    def test_pedido_response_incluye_campos_delivery(self, client, auth_headers):
        ped = self._crear_pedido(client, auth_headers)
        resp = client.get(f"/api/v1/pedidos/{ped['id']}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "repartidor_nombre" in data
        assert "en_ruta_en" in data
        assert "costo_envio" in data
