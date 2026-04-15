"""Tests para el módulo de gestión de proveedores y compras."""

from datetime import date, timedelta
import pytest


class TestCompras:
    """Tests de órdenes de compra, recepción, cuentas por pagar, pagos."""

    def _crear_proveedor(self, client, auth_headers):
        """Helper: crea un proveedor y un ingrediente asociado."""
        # Crear proveedor
        resp = client.post("/api/v1/inventario/proveedores", json={
            "nombre": "Harinas del Centro",
            "rfc": "HCE010101AAA",
            "contacto": "Juan Pérez",
            "telefono": "4421234567",
            "email": "ventas@harinas.com",
        }, headers=auth_headers)
        assert resp.status_code == 201, f"Crear proveedor falló: {resp.json()}"
        prov_id = resp.json()["id"]

        # Crear ingrediente asociado al proveedor
        resp2 = client.post("/api/v1/inventario/ingredientes", json={
            "nombre": "Harina de trigo",
            "unidad_medida": "kg",
            "stock_actual": "100",
            "stock_minimo": "20",
            "costo_unitario": "15.50",
            "proveedor_id": prov_id,
        }, headers=auth_headers)
        assert resp2.status_code == 201
        ing_id = resp2.json()["id"]
        return prov_id, ing_id

    def _crear_orden(self, client, auth_headers, prov_id, ing_id, **kwargs):
        """Helper: crea una orden de compra."""
        payload = {
            "proveedor_id": prov_id,
            "fecha_entrega_esperada": (date.today() + timedelta(days=5)).isoformat(),
            "items": [
                {"ingrediente_id": ing_id, "cantidad": "50", "precio_unitario": "15.50"},
            ],
        }
        payload.update(kwargs)
        return client.post("/api/v1/compras/ordenes", json=payload, headers=auth_headers)

    # ── Proveedores ──

    def test_listar_proveedores(self, client, auth_headers):
        self._crear_proveedor(client, auth_headers)
        resp = client.get("/api/v1/compras/proveedores", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_obtener_proveedor_detalle(self, client, auth_headers):
        prov_id, _ = self._crear_proveedor(client, auth_headers)
        resp = client.get(f"/api/v1/compras/proveedores/{prov_id}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["nombre"] == "Harinas del Centro"
        assert "ingredientes" in data

    def test_proveedor_no_existente(self, client, auth_headers):
        resp = client.get("/api/v1/compras/proveedores/99999", headers=auth_headers)
        assert resp.status_code == 404

    # ── Órdenes de compra ──

    def test_crear_orden_compra(self, client, auth_headers):
        prov_id, ing_id = self._crear_proveedor(client, auth_headers)
        resp = self._crear_orden(client, auth_headers, prov_id, ing_id)
        assert resp.status_code == 201
        data = resp.json()
        assert data["estado"] == "borrador"
        assert data["folio"].startswith("OC-")
        assert len(data["detalles"]) == 1
        assert data["subtotal"] == 775.0  # 50 * 15.50
        assert data["total"] == 899.0  # 775 + 124 IVA

    def test_listar_ordenes(self, client, auth_headers):
        prov_id, ing_id = self._crear_proveedor(client, auth_headers)
        self._crear_orden(client, auth_headers, prov_id, ing_id)
        resp = client.get("/api/v1/compras/ordenes", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_obtener_orden_detalle(self, client, auth_headers):
        prov_id, ing_id = self._crear_proveedor(client, auth_headers)
        resp = self._crear_orden(client, auth_headers, prov_id, ing_id)
        oid = resp.json()["id"]
        resp2 = client.get(f"/api/v1/compras/ordenes/{oid}", headers=auth_headers)
        assert resp2.status_code == 200
        assert resp2.json()["id"] == oid

    def test_orden_sin_items_falla(self, client, auth_headers):
        prov_id, _ = self._crear_proveedor(client, auth_headers)
        resp = client.post("/api/v1/compras/ordenes", json={
            "proveedor_id": prov_id,
            "items": [],
        }, headers=auth_headers)
        assert resp.status_code == 400

    # ── Recepción de mercancía ──

    def test_recibir_orden_completa(self, client, auth_headers):
        prov_id, ing_id = self._crear_proveedor(client, auth_headers)
        resp = self._crear_orden(client, auth_headers, prov_id, ing_id)
        orden = resp.json()
        detalle_id = orden["detalles"][0]["id"]

        resp2 = client.post(f"/api/v1/compras/ordenes/{orden['id']}/recibir", json={
            "items": [{"detalle_id": detalle_id, "cantidad_recibida": "50"}],
        }, headers=auth_headers)
        assert resp2.status_code == 200
        data = resp2.json()
        assert data["estado"] == "recibida"

    def test_recibir_orden_parcial(self, client, auth_headers):
        prov_id, ing_id = self._crear_proveedor(client, auth_headers)
        resp = self._crear_orden(client, auth_headers, prov_id, ing_id)
        orden = resp.json()
        detalle_id = orden["detalles"][0]["id"]

        resp2 = client.post(f"/api/v1/compras/ordenes/{orden['id']}/recibir", json={
            "items": [{"detalle_id": detalle_id, "cantidad_recibida": "30"}],
        }, headers=auth_headers)
        assert resp2.status_code == 200
        assert resp2.json()["estado"] == "parcial"

    # ── Cuentas por pagar ──

    def test_crear_cuenta_pagar(self, client, auth_headers):
        prov_id, _ = self._crear_proveedor(client, auth_headers)
        resp = client.post("/api/v1/compras/cuentas-pagar", json={
            "proveedor_id": prov_id,
            "concepto": "Factura harina marzo",
            "monto_total": "5000.00",
            "fecha_factura": date.today().isoformat(),
            "fecha_vencimiento": (date.today() + timedelta(days=30)).isoformat(),
            "numero_factura": "F-001",
        }, headers=auth_headers)
        assert resp.status_code == 201
        data = resp.json()
        assert data["monto_total"] == 5000.0
        assert data["saldo_pendiente"] == 5000.0
        assert data["estado"] == "pendiente"

    def test_listar_cuentas_pagar(self, client, auth_headers):
        prov_id, _ = self._crear_proveedor(client, auth_headers)
        client.post("/api/v1/compras/cuentas-pagar", json={
            "proveedor_id": prov_id,
            "concepto": "Factura",
            "monto_total": "1000.00",
            "fecha_factura": date.today().isoformat(),
            "fecha_vencimiento": (date.today() + timedelta(days=15)).isoformat(),
        }, headers=auth_headers)
        resp = client.get("/api/v1/compras/cuentas-pagar", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    # ── Pagos ──

    def test_pago_total(self, client, auth_headers):
        prov_id, _ = self._crear_proveedor(client, auth_headers)
        resp = client.post("/api/v1/compras/cuentas-pagar", json={
            "proveedor_id": prov_id,
            "concepto": "Factura test",
            "monto_total": "1000.00",
            "fecha_factura": date.today().isoformat(),
            "fecha_vencimiento": (date.today() + timedelta(days=30)).isoformat(),
        }, headers=auth_headers)
        cuenta_id = resp.json()["id"]

        resp2 = client.post(f"/api/v1/compras/cuentas-pagar/{cuenta_id}/pago", json={
            "monto": "1000.00",
            "metodo_pago": "transferencia",
            "fecha_pago": date.today().isoformat(),
        }, headers=auth_headers)
        assert resp2.status_code == 201
        data = resp2.json()
        assert data["cuenta"]["estado"] == "pagada"
        assert data["cuenta"]["saldo_pendiente"] == 0.0

    def test_pago_parcial(self, client, auth_headers):
        prov_id, _ = self._crear_proveedor(client, auth_headers)
        resp = client.post("/api/v1/compras/cuentas-pagar", json={
            "proveedor_id": prov_id,
            "concepto": "Factura parcial",
            "monto_total": "2000.00",
            "fecha_factura": date.today().isoformat(),
            "fecha_vencimiento": (date.today() + timedelta(days=30)).isoformat(),
        }, headers=auth_headers)
        cuenta_id = resp.json()["id"]

        resp2 = client.post(f"/api/v1/compras/cuentas-pagar/{cuenta_id}/pago", json={
            "monto": "500.00",
            "metodo_pago": "efectivo",
            "fecha_pago": date.today().isoformat(),
        }, headers=auth_headers)
        assert resp2.status_code == 201
        data = resp2.json()
        assert data["cuenta"]["estado"] == "parcial"
        assert data["cuenta"]["saldo_pendiente"] == 1500.0

    def test_pago_excede_saldo_falla(self, client, auth_headers):
        prov_id, _ = self._crear_proveedor(client, auth_headers)
        resp = client.post("/api/v1/compras/cuentas-pagar", json={
            "proveedor_id": prov_id,
            "concepto": "Factura exceso",
            "monto_total": "500.00",
            "fecha_factura": date.today().isoformat(),
            "fecha_vencimiento": (date.today() + timedelta(days=30)).isoformat(),
        }, headers=auth_headers)
        cuenta_id = resp.json()["id"]

        resp2 = client.post(f"/api/v1/compras/cuentas-pagar/{cuenta_id}/pago", json={
            "monto": "600.00",
            "metodo_pago": "transferencia",
            "fecha_pago": date.today().isoformat(),
        }, headers=auth_headers)
        assert resp2.status_code == 400

    # ── Calendario ──

    def test_calendario_pagos(self, client, auth_headers):
        resp = client.get("/api/v1/compras/calendario-pagos", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    # ── Dashboard ──

    def test_dashboard_compras(self, client, auth_headers):
        resp = client.get("/api/v1/compras/dashboard", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "total_por_pagar" in data
        assert "ordenes_en_progreso" in data
        assert "top_proveedores" in data
