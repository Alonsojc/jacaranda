"""Tests para el módulo de recetas y producción."""

import pytest


class TestRecetas:
    """Tests del flujo de recetas."""

    def _crear_ingrediente(self, client, auth_headers, nombre="Harina", unidad="kg"):
        resp = client.post("/api/v1/inventario/ingredientes", json={
            "nombre": nombre,
            "unidad_medida": unidad,
            "stock_actual": "50.0",
            "stock_minimo": "5.0",
            "costo_unitario": "25.00",
        }, headers=auth_headers)
        assert resp.status_code == 201
        return resp.json()["id"]

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
