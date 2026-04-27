"""Tests de integración para el módulo de ventas."""

import pytest


class TestVentas:
    """Tests para el flujo completo de ventas."""

    def _crear_producto(self, client, auth_headers, codigo="PAN-001", precio="15.00"):
        """Helper: crea un producto y devuelve su ID."""
        resp = client.post("/api/v1/inventario/productos", json={
            "codigo": codigo,
            "nombre": f"Producto {codigo}",
            "precio_unitario": precio,
            "tasa_iva": "0.00",
        }, headers=auth_headers)
        assert resp.status_code == 201
        return resp.json()["id"]

    def _agregar_stock(self, client, auth_headers, producto_id, cantidad=50):
        """Helper: registra entrada de inventario."""
        resp = client.post("/api/v1/inventario/movimientos", json={
            "tipo": "entrada_ajuste",
            "producto_id": producto_id,
            "cantidad": str(cantidad),
            "referencia": "Stock inicial test",
        }, headers=auth_headers)
        assert resp.status_code == 201

    def test_venta_exitosa(self, client, auth_headers):
        pid = self._crear_producto(client, auth_headers)
        self._agregar_stock(client, auth_headers, pid)
        resp = client.post("/api/v1/punto-de-venta/ventas", json={
            "metodo_pago": "01",
            "monto_recibido": "100.00",
            "detalles": [{"producto_id": pid, "cantidad": "2"}],
        }, headers=auth_headers)
        assert resp.status_code == 201
        data = resp.json()
        assert data["total"] == "30.00"
        assert data["estado"] == "completada"
        assert data["folio"].startswith("T-")

    def test_venta_idempotente_no_duplica_stock(self, client, auth_headers):
        pid = self._crear_producto(client, auth_headers, "PAN-IDEMP")
        self._agregar_stock(client, auth_headers, pid, 10)
        payload = {
            "idempotency_key": "venta-test-idempotente-1",
            "metodo_pago": "01",
            "monto_recibido": "100.00",
            "detalles": [{"producto_id": pid, "cantidad": "2"}],
        }
        resp1 = client.post("/api/v1/punto-de-venta/ventas", json=payload, headers=auth_headers)
        resp2 = client.post("/api/v1/punto-de-venta/ventas", json=payload, headers=auth_headers)
        assert resp1.status_code == 201
        assert resp2.status_code == 201
        assert resp2.json()["id"] == resp1.json()["id"]

        prod = client.get(f"/api/v1/inventario/productos/{pid}", headers=auth_headers)
        assert float(prod.json()["stock_actual"]) == 8.0

    def test_venta_descuenta_stock(self, client, auth_headers):
        pid = self._crear_producto(client, auth_headers, "PAN-002")
        self._agregar_stock(client, auth_headers, pid, 10)
        client.post("/api/v1/punto-de-venta/ventas", json={
            "metodo_pago": "01",
            "monto_recibido": "100.00",
            "detalles": [{"producto_id": pid, "cantidad": "3"}],
        }, headers=auth_headers)
        prod = client.get(f"/api/v1/inventario/productos/{pid}", headers=auth_headers)
        assert float(prod.json()["stock_actual"]) == 7.0

    def test_venta_stock_insuficiente(self, client, auth_headers):
        pid = self._crear_producto(client, auth_headers, "PAN-003")
        self._agregar_stock(client, auth_headers, pid, 2)
        resp = client.post("/api/v1/punto-de-venta/ventas", json={
            "metodo_pago": "01",
            "monto_recibido": "500.00",
            "detalles": [{"producto_id": pid, "cantidad": "5"}],
        }, headers=auth_headers)
        assert resp.status_code == 400

    def test_venta_producto_inexistente(self, client, auth_headers):
        resp = client.post("/api/v1/punto-de-venta/ventas", json={
            "metodo_pago": "01",
            "monto_recibido": "100.00",
            "detalles": [{"producto_id": 9999, "cantidad": "1"}],
        }, headers=auth_headers)
        assert resp.status_code == 400

    def test_cancelar_venta(self, client, auth_headers):
        pid = self._crear_producto(client, auth_headers, "PAN-004")
        self._agregar_stock(client, auth_headers, pid, 20)
        venta = client.post("/api/v1/punto-de-venta/ventas", json={
            "metodo_pago": "01",
            "monto_recibido": "100.00",
            "detalles": [{"producto_id": pid, "cantidad": "5"}],
        }, headers=auth_headers).json()
        # Stock should be 15 now
        prod = client.get(f"/api/v1/inventario/productos/{pid}", headers=auth_headers).json()
        assert float(prod["stock_actual"]) == 15.0
        # Cancel
        resp = client.post(
            f"/api/v1/punto-de-venta/ventas/{venta['id']}/cancelar",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["estado"] == "cancelada"
        # Stock should be restored to 20
        prod = client.get(f"/api/v1/inventario/productos/{pid}", headers=auth_headers).json()
        assert float(prod["stock_actual"]) == 20.0

    def test_cancelar_venta_revierte_puntos_y_audita(self, client, auth_headers, db):
        from app.models.auditoria import LogAuditoria

        cliente = client.post("/api/v1/clientes/", json={
            "nombre": "Cliente Puntos",
            "telefono": "4420000000",
            "email": "puntos@example.com",
        }, headers=auth_headers).json()
        pid = self._crear_producto(client, auth_headers, "PAN-PUNTOS", "100.00")
        self._agregar_stock(client, auth_headers, pid, 10)

        venta = client.post("/api/v1/punto-de-venta/ventas", json={
            "metodo_pago": "01",
            "monto_recibido": "100.00",
            "cliente_id": cliente["id"],
            "detalles": [{"producto_id": pid, "cantidad": "1"}],
        }, headers=auth_headers).json()
        puntos = client.get(f"/api/v1/clientes/{cliente['id']}/puntos", headers=auth_headers).json()
        assert puntos["puntos"] == 10

        resp = client.post(
            f"/api/v1/punto-de-venta/ventas/{venta['id']}/cancelar",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        puntos = client.get(f"/api/v1/clientes/{cliente['id']}/puntos", headers=auth_headers).json()
        assert puntos["puntos"] == 0

        evento = db.query(LogAuditoria).filter(
            LogAuditoria.accion == "cancelar",
            LogAuditoria.modulo == "ventas",
            LogAuditoria.entidad_id == venta["id"],
        ).first()
        assert evento is not None
        assert "puntos_revertidos" in evento.datos_nuevos

    def test_cancelar_venta_ya_cancelada(self, client, auth_headers):
        pid = self._crear_producto(client, auth_headers, "PAN-005")
        self._agregar_stock(client, auth_headers, pid, 10)
        venta = client.post("/api/v1/punto-de-venta/ventas", json={
            "metodo_pago": "01",
            "monto_recibido": "100.00",
            "detalles": [{"producto_id": pid, "cantidad": "1"}],
        }, headers=auth_headers).json()
        client.post(f"/api/v1/punto-de-venta/ventas/{venta['id']}/cancelar", headers=auth_headers)
        resp = client.post(f"/api/v1/punto-de-venta/ventas/{venta['id']}/cancelar", headers=auth_headers)
        assert resp.status_code == 400

    def test_ticket_venta(self, client, auth_headers):
        pid = self._crear_producto(client, auth_headers, "PAN-006")
        self._agregar_stock(client, auth_headers, pid, 10)
        venta = client.post("/api/v1/punto-de-venta/ventas", json={
            "metodo_pago": "01",
            "monto_recibido": "50.00",
            "detalles": [{"producto_id": pid, "cantidad": "2"}],
        }, headers=auth_headers).json()
        resp = client.get(f"/api/v1/punto-de-venta/ventas/{venta['id']}/ticket", headers=auth_headers)
        assert resp.status_code == 200
        ticket = resp.json()
        assert ticket["folio"] == venta["folio"]
        assert len(ticket["productos"]) == 1

    def test_venta_con_iva(self, client, auth_headers):
        pid = self._crear_producto(client, auth_headers, "PASTEL-001", "100.00")
        # Update to 16% IVA
        client.put(f"/api/v1/inventario/productos/{pid}", json={
            "tasa_iva": "0.16",
        }, headers=auth_headers)
        self._agregar_stock(client, auth_headers, pid, 10)
        resp = client.post("/api/v1/punto-de-venta/ventas", json={
            "metodo_pago": "01",
            "monto_recibido": "200.00",
            "detalles": [{"producto_id": pid, "cantidad": "1"}],
        }, headers=auth_headers)
        assert resp.status_code == 201
        data = resp.json()
        assert float(data["total"]) == 116.00
        assert float(data["iva_16"]) == 16.00


class TestInventarioMovimientos:
    """Tests para movimientos de inventario."""

    def test_entrada_compra(self, client, auth_headers):
        # Create ingredient
        resp = client.post("/api/v1/inventario/ingredientes", json={
            "nombre": "Harina",
            "unidad_medida": "kg",
            "stock_minimo": "5",
            "costo_unitario": "15.00",
        }, headers=auth_headers)
        assert resp.status_code == 201
        ing_id = resp.json()["id"]
        # Register purchase
        resp = client.post("/api/v1/inventario/movimientos", json={
            "tipo": "entrada_compra",
            "ingrediente_id": ing_id,
            "cantidad": "25",
            "costo_unitario": "14.50",
        }, headers=auth_headers)
        assert resp.status_code == 201
        # Verify stock
        ing = client.get(f"/api/v1/inventario/ingredientes/{ing_id}", headers=auth_headers).json()
        assert float(ing["stock_actual"]) == 25.0

    def test_merma_producto(self, client, auth_headers):
        resp = client.post("/api/v1/inventario/productos", json={
            "codigo": "MERMA-001",
            "nombre": "Pan para merma",
            "precio_unitario": "10.00",
            "tasa_iva": "0.00",
        }, headers=auth_headers)
        pid = resp.json()["id"]
        # Add stock
        client.post("/api/v1/inventario/movimientos", json={
            "tipo": "entrada_ajuste",
            "producto_id": pid,
            "cantidad": "20",
        }, headers=auth_headers)
        # Register merma
        resp = client.post(
            f"/api/v1/inventario/productos/{pid}/merma?cantidad=3&motivo=Caducado",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        # Verify stock decreased
        prod = client.get(f"/api/v1/inventario/productos/{pid}", headers=auth_headers).json()
        assert float(prod["stock_actual"]) == 17.0

    def test_movimientos_listado(self, client, auth_headers):
        resp = client.post("/api/v1/inventario/ingredientes", json={
            "nombre": "Azúcar",
            "unidad_medida": "kg",
            "costo_unitario": "20.00",
        }, headers=auth_headers)
        ing_id = resp.json()["id"]
        client.post("/api/v1/inventario/movimientos", json={
            "tipo": "entrada_compra",
            "ingrediente_id": ing_id,
            "cantidad": "10",
            "costo_unitario": "20.00",
        }, headers=auth_headers)
        resp = client.get(f"/api/v1/inventario/movimientos?ingrediente_id={ing_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) >= 1


class TestReportes:
    """Tests para endpoints de reportes."""

    def test_dashboard(self, client, auth_headers):
        resp = client.get("/api/v1/reportes/dashboard", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "ventas_hoy" in data
        assert "ventas_mes" in data

    def test_ventas_por_dia(self, client, auth_headers):
        resp = client.get("/api/v1/reportes/ventas-por-dia?dias=7", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 7

    def test_pronostico_produccion(self, client, auth_headers):
        resp = client.get("/api/v1/reportes/pronostico-produccion", headers=auth_headers)
        assert resp.status_code == 200

    def test_gastos_hoy(self, client, auth_headers):
        resp = client.get("/api/v1/reportes/gastos-hoy", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "total_gastos" in data
        assert "desglose" in data
