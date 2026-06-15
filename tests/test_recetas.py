"""Tests para el módulo de recetas y producción."""

import json
from pathlib import Path

import pytest


class TestRecetas:
    """Tests del flujo de recetas."""

    def _crear_ingrediente(self, client, auth_headers, nombre="Harina", unidad="kg"):
        resp = client.post("/api/v1/inventario/ingredientes", json={
            "nombre": nombre,
            "unidad_medida": unidad,
            "stock_minimo": "5.0",
            "costo_unitario": "25.00",
        }, headers=auth_headers)
        assert resp.status_code == 201
        return resp.json()["id"]

    def _comprar_ingrediente(self, client, auth_headers, ingrediente_id, cantidad=50):
        resp = client.post(
            f"/api/v1/inventario/ingredientes/{ingrediente_id}/compra?cantidad={cantidad}&costo=25",
            headers=auth_headers,
        )
        assert resp.status_code == 200

    def _crear_producto(self, client, auth_headers, codigo="REC-001"):
        resp = client.post("/api/v1/inventario/productos", json={
            "codigo": codigo,
            "nombre": f"Producto {codigo}",
            "precio_unitario": "35.00",
            "tasa_iva": "0.00",
        }, headers=auth_headers)
        assert resp.status_code == 201
        return resp.json()["id"]

    def test_crear_receta(self, client, auth_headers):
        prod_id = self._crear_producto(client, auth_headers)
        ing_id = self._crear_ingrediente(client, auth_headers)
        resp = client.post("/api/v1/recetas/", json={
            "producto_id": prod_id,
            "nombre": "Receta Concha",
            "rendimiento": 12,
            "tiempo_preparacion": 30,
            "tiempo_horneado": 25,
            "temperatura_horneado": 180,
            "ingredientes": [
                {"ingrediente_id": ing_id, "cantidad": "0.500"},
            ],
        }, headers=auth_headers)
        assert resp.status_code == 201
        data = resp.json()
        assert data["nombre"] == "Receta Concha"
        assert int(float(data["rendimiento"])) == 12

    def test_listar_recetas(self, client, auth_headers):
        resp = client.get("/api/v1/recetas/", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_costo_receta(self, client, auth_headers):
        prod_id = self._crear_producto(client, auth_headers, "REC-002")
        ing_id = self._crear_ingrediente(client, auth_headers, "Azúcar", "kg")
        # Crear receta
        resp = client.post("/api/v1/recetas/", json={
            "producto_id": prod_id,
            "nombre": "Receta Polvorón",
            "rendimiento": 24,
            "ingredientes": [
                {"ingrediente_id": ing_id, "cantidad": "1.000"},
            ],
        }, headers=auth_headers)
        receta_id = resp.json()["id"]
        # Obtener costo
        resp2 = client.get(f"/api/v1/recetas/{receta_id}/costo", headers=auth_headers)
        assert resp2.status_code == 200
        data = resp2.json()
        assert "costo_total_ingredientes" in data
        assert "costo_por_pieza" in data

    def test_disponibilidad_receta(self, client, auth_headers):
        prod_id = self._crear_producto(client, auth_headers, "REC-003")
        ing_id = self._crear_ingrediente(client, auth_headers, "Mantequilla", "kg")
        resp = client.post("/api/v1/recetas/", json={
            "producto_id": prod_id,
            "nombre": "Receta Cuerno",
            "rendimiento": 10,
            "ingredientes": [
                {"ingrediente_id": ing_id, "cantidad": "0.200"},
            ],
        }, headers=auth_headers)
        receta_id = resp.json()["id"]
        resp2 = client.get(f"/api/v1/recetas/{receta_id}/disponibilidad", headers=auth_headers)
        assert resp2.status_code == 200
        data = resp2.json()
        assert "disponible" in data

    def test_horneado_masivo_registra_varias_recetas(self, client, auth_headers, db):
        from app.models.auditoria import LogAuditoria

        prod_1 = self._crear_producto(client, auth_headers, "REC-BATCH-1")
        prod_2 = self._crear_producto(client, auth_headers, "REC-BATCH-2")
        ing_id = self._crear_ingrediente(client, auth_headers, "Harina batch", "kg")
        self._comprar_ingrediente(client, auth_headers, ing_id)

        receta_1 = client.post("/api/v1/recetas/", json={
            "producto_id": prod_1,
            "nombre": "Batch Brownie",
            "rendimiento": 10,
            "ingredientes": [{"ingrediente_id": ing_id, "cantidad": "1.000"}],
        }, headers=auth_headers).json()["id"]
        receta_2 = client.post("/api/v1/recetas/", json={
            "producto_id": prod_2,
            "nombre": "Batch Galleta",
            "rendimiento": 8,
            "ingredientes": [{"ingrediente_id": ing_id, "cantidad": "2.000"}],
        }, headers=auth_headers).json()["id"]

        resp = client.post("/api/v1/recetas/hornear-masivo", json={
            "items": [
                {"receta_id": receta_1, "cantidad": 2},
                {"receta_id": receta_2, "cantidad": 3},
            ],
        }, headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_recetas"] == 2
        assert data["total_tandas"] == 5
        assert data["total_piezas"] == 44

        prod_1_data = client.get(f"/api/v1/inventario/productos/{prod_1}", headers=auth_headers).json()
        prod_2_data = client.get(f"/api/v1/inventario/productos/{prod_2}", headers=auth_headers).json()
        ing_data = client.get(f"/api/v1/inventario/ingredientes/{ing_id}", headers=auth_headers).json()
        assert float(prod_1_data["stock_actual"]) == 20
        assert float(prod_2_data["stock_actual"]) == 24
        assert float(ing_data["stock_actual"]) == 42

        evento = db.query(LogAuditoria).filter(
            LogAuditoria.modulo == "produccion",
            LogAuditoria.entidad == "horneado_masivo",
        ).first()
        assert evento is not None
        datos = json.loads(evento.datos_nuevos)
        assert datos["total_recetas"] == 2
        assert datos["total_tandas"] == 5
        assert datos["total_piezas"] == 44

    def test_horneado_masivo_no_deja_produccion_parcial_si_faltan_ingredientes(self, client, auth_headers):
        prod_1 = self._crear_producto(client, auth_headers, "REC-BATCH-3")
        prod_2 = self._crear_producto(client, auth_headers, "REC-BATCH-4")
        ing_id = self._crear_ingrediente(client, auth_headers, "Mantequilla batch", "kg")
        self._comprar_ingrediente(client, auth_headers, ing_id)

        receta_1 = client.post("/api/v1/recetas/", json={
            "producto_id": prod_1,
            "nombre": "Batch Pay",
            "rendimiento": 10,
            "ingredientes": [{"ingrediente_id": ing_id, "cantidad": "20.000"}],
        }, headers=auth_headers).json()["id"]
        receta_2 = client.post("/api/v1/recetas/", json={
            "producto_id": prod_2,
            "nombre": "Batch Panque",
            "rendimiento": 8,
            "ingredientes": [{"ingrediente_id": ing_id, "cantidad": "20.000"}],
        }, headers=auth_headers).json()["id"]

        resp = client.post("/api/v1/recetas/hornear-masivo", json={
            "items": [
                {"receta_id": receta_1, "cantidad": 2},
                {"receta_id": receta_2, "cantidad": 2},
            ],
        }, headers=auth_headers)

        assert resp.status_code == 400
        assert resp.json()["detail"]["faltantes"][0]["ingrediente"] == "Mantequilla batch"

        prod_1_data = client.get(f"/api/v1/inventario/productos/{prod_1}", headers=auth_headers).json()
        prod_2_data = client.get(f"/api/v1/inventario/productos/{prod_2}", headers=auth_headers).json()
        ing_data = client.get(f"/api/v1/inventario/ingredientes/{ing_id}", headers=auth_headers).json()
        assert float(prod_1_data["stock_actual"]) == 0
        assert float(prod_2_data["stock_actual"]) == 0
        assert float(ing_data["stock_actual"]) == 50

    def test_horneado_rechaza_receta_sin_ingredientes(self, client, auth_headers):
        prod_id = self._crear_producto(client, auth_headers, "REC-SIN-ING")
        receta_id = client.post("/api/v1/recetas/", json={
            "producto_id": prod_id,
            "nombre": "Receta incompleta",
            "rendimiento": 6,
            "ingredientes": [],
        }, headers=auth_headers).json()["id"]

        individual = client.post(
            f"/api/v1/recetas/{receta_id}/hornear?cantidad=1",
            headers=auth_headers,
        )
        assert individual.status_code == 400
        assert "no tiene ingredientes" in individual.json()["detail"].lower()

        masivo = client.post("/api/v1/recetas/hornear-masivo", json={
            "items": [{"receta_id": receta_id, "cantidad": 1}],
        }, headers=auth_headers)
        assert masivo.status_code == 400
        assert "sin ingredientes" in masivo.json()["detail"].lower()

        prod = client.get(f"/api/v1/inventario/productos/{prod_id}", headers=auth_headers)
        assert float(prod.json()["stock_actual"]) == 0


def test_inventario_sprint5_frontend_contract():
    html_path = Path(__file__).resolve().parents[1] / "docs" / "index.html"
    with html_path.open(encoding="utf-8") as fh:
        html = fh.read()

    assert "inv-empaque-alertas" in html
    assert "/inventario/alertas/empaques" in html
    assert "function cargarAlertasEmpaques" in html
    assert "function sugerirCajaParaProducto" in html
    assert "@media(pointer:coarse)" in html
    assert '<option value="caja">caja</option>' in html
    assert '<option value="bolsa">bolsa</option>' in html
    assert 'id="d-ai-card" data-module="prod"' not in html
    assert 'id="d-ai-card" style="display:none"' in html
    assert "deferDashboard(cargarPronosticoHero" not in html
