"""Tests para el módulo multi-sucursal."""

from datetime import date
from decimal import Decimal
import pytest


class TestSucursales:
    """Tests de sucursales, inventario por sucursal, traspasos."""

    def _crear_sucursal(self, client, auth_headers, codigo="SUC01", nombre="Sucursal Centro"):
        resp = client.post("/api/v1/sucursales/", json={
            "codigo": codigo,
            "nombre": nombre,
            "direccion": "Av. Principal 100",
            "telefono": "4421112233",
        }, headers=auth_headers)
        assert resp.status_code == 201, f"Crear sucursal falló: {resp.json()}"
        return resp.json()["id"]

    def _crear_producto(self, client, auth_headers, codigo="PROD-001"):
        resp = client.post("/api/v1/inventario/productos", json={
            "codigo": codigo,
            "nombre": f"Producto {codigo}",
            "precio_unitario": "25.00",
            "tasa_iva": "0.00",
        }, headers=auth_headers)
        assert resp.status_code == 201
        return resp.json()["id"]

    # ── CRUD Sucursales ──

    def test_crear_sucursal(self, client, auth_headers):
        sid = self._crear_sucursal(client, auth_headers)
        assert sid is not None

    def test_primera_sucursal_es_matriz(self, client, auth_headers):
        sid = self._crear_sucursal(client, auth_headers)
        resp = client.get(f"/api/v1/sucursales/{sid}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["es_matriz"] is True

    def test_crear_sucursal_duplicada_falla(self, client, auth_headers):
        self._crear_sucursal(client, auth_headers, codigo="DUP01")
        resp = client.post("/api/v1/sucursales/", json={
            "codigo": "DUP01",
            "nombre": "Duplicada",
        }, headers=auth_headers)
        assert resp.status_code == 400

    def test_listar_sucursales(self, client, auth_headers):
        self._crear_sucursal(client, auth_headers)
        resp = client.get("/api/v1/sucursales/", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_obtener_sucursal(self, client, auth_headers):
        sid = self._crear_sucursal(client, auth_headers)
        resp = client.get(f"/api/v1/sucursales/{sid}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["codigo"] == "SUC01"
        assert "inventario_resumen" in data

    def test_actualizar_sucursal(self, client, auth_headers):
        sid = self._crear_sucursal(client, auth_headers)
        resp = client.put(f"/api/v1/sucursales/{sid}", json={
            "nombre": "Sucursal Centro Actualizada",
        }, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["nombre"] == "Sucursal Centro Actualizada"

    def test_sucursal_no_existente(self, client, auth_headers):
        resp = client.get("/api/v1/sucursales/99999", headers=auth_headers)
        assert resp.status_code == 404

    # ── Inventario por sucursal ──

    def test_inicializar_inventario(self, client, auth_headers):
        sid = self._crear_sucursal(client, auth_headers)
        self._crear_producto(client, auth_headers)
        resp = client.post(f"/api/v1/sucursales/{sid}/inventario/inicializar", headers=auth_headers)
        assert resp.status_code == 201
        assert resp.json()["registros_creados"] >= 1

    def test_obtener_inventario_sucursal(self, client, auth_headers):
        sid = self._crear_sucursal(client, auth_headers)
        self._crear_producto(client, auth_headers)
        client.post(f"/api/v1/sucursales/{sid}/inventario/inicializar", headers=auth_headers)

        resp = client.get(f"/api/v1/sucursales/{sid}/inventario", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) >= 1
        assert resp.json()[0]["stock_actual"] == 0.0

    def test_ajustar_stock_sucursal(self, client, auth_headers):
        sid = self._crear_sucursal(client, auth_headers)
        pid = self._crear_producto(client, auth_headers)
        client.post(f"/api/v1/sucursales/{sid}/inventario/inicializar", headers=auth_headers)

        resp = client.post(f"/api/v1/sucursales/{sid}/inventario/ajuste", json={
            "producto_id": pid,
            "cantidad": "100",
            "operacion": "sumar",
        }, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["stock_actual"] == 100.0

    def test_restar_stock_insuficiente_falla(self, client, auth_headers):
        sid = self._crear_sucursal(client, auth_headers)
        pid = self._crear_producto(client, auth_headers)
        client.post(f"/api/v1/sucursales/{sid}/inventario/inicializar", headers=auth_headers)

        resp = client.post(f"/api/v1/sucursales/{sid}/inventario/ajuste", json={
            "producto_id": pid,
            "cantidad": "50",
            "operacion": "restar",
        }, headers=auth_headers)
        assert resp.status_code == 400

    # ── Traspasos ──

    def _setup_traspaso(self, client, auth_headers):
        """Helper: crea 2 sucursales con un producto y stock en origen."""
        sid1 = self._crear_sucursal(client, auth_headers, "ORG01", "Sucursal Origen")
        sid2 = self._crear_sucursal(client, auth_headers, "DST01", "Sucursal Destino")
        pid = self._crear_producto(client, auth_headers)

        # Inicializar inventario en ambas sucursales
        client.post(f"/api/v1/sucursales/{sid1}/inventario/inicializar", headers=auth_headers)
        client.post(f"/api/v1/sucursales/{sid2}/inventario/inicializar", headers=auth_headers)

        # Agregar stock al origen
        client.post(f"/api/v1/sucursales/{sid1}/inventario/ajuste", json={
            "producto_id": pid, "cantidad": "200", "operacion": "sumar",
        }, headers=auth_headers)

        return sid1, sid2, pid

    def test_crear_traspaso(self, client, auth_headers):
        sid1, sid2, pid = self._setup_traspaso(client, auth_headers)
        resp = client.post("/api/v1/sucursales/traspasos", json={
            "sucursal_origen_id": sid1,
            "sucursal_destino_id": sid2,
            "detalles": [{"producto_id": pid, "cantidad_enviada": "50"}],
        }, headers=auth_headers)
        assert resp.status_code == 201
        data = resp.json()
        assert data["folio"].startswith("TR-")
        assert data["estado"] == "solicitado"
        assert len(data["detalles"]) == 1

    def test_traspaso_misma_sucursal_falla(self, client, auth_headers):
        sid = self._crear_sucursal(client, auth_headers)
        pid = self._crear_producto(client, auth_headers)
        resp = client.post("/api/v1/sucursales/traspasos", json={
            "sucursal_origen_id": sid,
            "sucursal_destino_id": sid,
            "detalles": [{"producto_id": pid, "cantidad_enviada": "10"}],
        }, headers=auth_headers)
        assert resp.status_code == 400

    def test_listar_traspasos(self, client, auth_headers):
        resp = client.get("/api/v1/sucursales/traspasos", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_flujo_traspaso_completo(self, client, auth_headers):
        """SOLICITADO → EN_TRANSITO → RECIBIDO, verificando stock."""
        sid1, sid2, pid = self._setup_traspaso(client, auth_headers)

        # 1. Crear traspaso
        resp = client.post("/api/v1/sucursales/traspasos", json={
            "sucursal_origen_id": sid1,
            "sucursal_destino_id": sid2,
            "detalles": [{"producto_id": pid, "cantidad_enviada": "50"}],
        }, headers=auth_headers)
        tid = resp.json()["id"]

        # 2. Enviar (descuenta stock origen)
        resp2 = client.post(f"/api/v1/sucursales/traspasos/{tid}/enviar", headers=auth_headers)
        assert resp2.status_code == 200
        assert resp2.json()["estado"] == "en_transito"

        # Verificar stock origen descendió
        inv_origen = client.get(f"/api/v1/sucursales/{sid1}/inventario", headers=auth_headers).json()
        producto_origen = [p for p in inv_origen if p["producto_id"] == pid][0]
        assert producto_origen["stock_actual"] == 150.0  # 200 - 50

        # 3. Recibir (agrega stock destino)
        resp3 = client.post(f"/api/v1/sucursales/traspasos/{tid}/recibir", json={
            "items_recibidos": [{"producto_id": pid, "cantidad_recibida": "50"}],
        }, headers=auth_headers)
        assert resp3.status_code == 200
        assert resp3.json()["estado"] == "recibido"

        # Verificar stock destino aumentó
        inv_destino = client.get(f"/api/v1/sucursales/{sid2}/inventario", headers=auth_headers).json()
        producto_destino = [p for p in inv_destino if p["producto_id"] == pid][0]
        assert producto_destino["stock_actual"] == 50.0

    def test_cancelar_traspaso_solicitado(self, client, auth_headers):
        sid1, sid2, pid = self._setup_traspaso(client, auth_headers)
        resp = client.post("/api/v1/sucursales/traspasos", json={
            "sucursal_origen_id": sid1,
            "sucursal_destino_id": sid2,
            "detalles": [{"producto_id": pid, "cantidad_enviada": "20"}],
        }, headers=auth_headers)
        tid = resp.json()["id"]

        resp2 = client.post(f"/api/v1/sucursales/traspasos/{tid}/cancelar", headers=auth_headers)
        assert resp2.status_code == 200
        assert resp2.json()["estado"] == "cancelado"

    def test_cancelar_traspaso_en_transito_restaura_stock(self, client, auth_headers):
        sid1, sid2, pid = self._setup_traspaso(client, auth_headers)

        resp = client.post("/api/v1/sucursales/traspasos", json={
            "sucursal_origen_id": sid1,
            "sucursal_destino_id": sid2,
            "detalles": [{"producto_id": pid, "cantidad_enviada": "30"}],
        }, headers=auth_headers)
        tid = resp.json()["id"]

        # Enviar
        client.post(f"/api/v1/sucursales/traspasos/{tid}/enviar", headers=auth_headers)

        # Cancelar (debe restaurar stock al origen)
        resp3 = client.post(f"/api/v1/sucursales/traspasos/{tid}/cancelar", headers=auth_headers)
        assert resp3.status_code == 200
        assert resp3.json()["estado"] == "cancelado"

        inv_origen = client.get(f"/api/v1/sucursales/{sid1}/inventario", headers=auth_headers).json()
        producto_origen = [p for p in inv_origen if p["producto_id"] == pid][0]
        assert producto_origen["stock_actual"] == 200.0  # Restored

    # ── Reportes ──

    def test_comparativo(self, client, auth_headers):
        self._crear_sucursal(client, auth_headers)
        resp = client.get("/api/v1/sucursales/comparativo", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_dashboard_sucursales(self, client, auth_headers):
        self._crear_sucursal(client, auth_headers)
        resp = client.get("/api/v1/sucursales/dashboard", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "total_sucursales" in data
        assert "traspasos_pendientes" in data
        assert "sucursales" in data
