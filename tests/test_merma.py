from datetime import date, timedelta

import pytest


class TestMerma:
    """Tests for the merma (waste) module."""

    def _crear_producto(self, client, auth_headers, codigo="MER-001", stock=100):
        resp = client.post(
            "/api/v1/inventario/productos",
            json={
                "codigo": codigo,
                "nombre": f"Pan {codigo}",
                "precio_unitario": "25.00",
                "tasa_iva": "0.00",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201
        pid = resp.json()["id"]
        if stock > 0:
            client.post(
                f"/api/v1/inventario/productos/{pid}/ajuste-stock?cantidad={stock}&motivo=Stock+inicial",
                headers=auth_headers,
            )
        return pid

    def _crear_ingrediente(self, client, auth_headers, codigo="ING-MER-001", stock=100):
        resp = client.post(
            "/api/v1/inventario/ingredientes",
            json={
                "codigo": codigo,
                "nombre": f"Harina {codigo}",
                "unidad_medida": "kg",
                "costo_unitario": "15.00",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201
        iid = resp.json()["id"]
        if stock > 0:
            client.post(
                f"/api/v1/inventario/ingredientes/{iid}/compra?cantidad={stock}&costo=15",
                headers=auth_headers,
            )
        return iid

    def _registrar_merma(self, client, auth_headers, **kwargs):
        hoy = date.today().isoformat()
        payload = {
            "tipo": "otro",
            "cantidad": 1.0,
            "unidad_medida": "pz",
            "costo_unitario": "25.00",
            "motivo": "Test merma",
            "fecha_merma": hoy,
        }
        payload.update(kwargs)
        return client.post("/api/v1/merma/", json=payload, headers=auth_headers)

    # ------------------------------------------------------------------
    # 1. Registrar merma de producto exitoso
    # ------------------------------------------------------------------
    def test_registrar_merma_producto_exitoso(self, client, auth_headers):
        producto_id = self._crear_producto(client, auth_headers, codigo="MER-P01")
        resp = self._registrar_merma(
            client,
            auth_headers,
            producto_id=producto_id,
            tipo="dano",
            cantidad=3.0,
            unidad_medida="pz",
            costo_unitario="25.00",
            motivo="Producto dañado en almacen",
        )
        assert resp.status_code in (200, 201), resp.text
        data = resp.json()
        assert data["tipo"] == "dano"
        assert float(data["cantidad"]) == 3.0
        assert data["producto_id"] == producto_id

    # ------------------------------------------------------------------
    # 2. Registrar merma de ingrediente
    # ------------------------------------------------------------------
    def test_registrar_merma_ingrediente_exitoso(self, client, auth_headers):
        ingrediente_id = self._crear_ingrediente(client, auth_headers, codigo="ING-MER-02")
        resp = self._registrar_merma(
            client,
            auth_headers,
            ingrediente_id=ingrediente_id,
            tipo="caducidad",
            cantidad=2.5,
            unidad_medida="kg",
            costo_unitario="15.00",
            motivo="Ingrediente caducado",
        )
        assert resp.status_code in (200, 201), resp.text
        data = resp.json()
        assert data["tipo"] == "caducidad"
        assert float(data["cantidad"]) == 2.5
        assert data["ingrediente_id"] == ingrediente_id

    # ------------------------------------------------------------------
    # 3. Registrar merma sin producto ni ingrediente (debe fallar)
    # ------------------------------------------------------------------
    def test_registrar_merma_sin_producto_ni_ingrediente(self, client, auth_headers):
        hoy = date.today().isoformat()
        resp = client.post(
            "/api/v1/merma/",
            json={
                "tipo": "otro",
                "cantidad": 1.0,
                "unidad_medida": "pz",
                "costo_unitario": "10.00",
                "motivo": "Sin referencia",
                "fecha_merma": hoy,
            },
            headers=auth_headers,
        )
        # Either 400 (validation) or 422 (schema) is acceptable
        assert resp.status_code in (400, 422), resp.text

    # ------------------------------------------------------------------
    # 4a. Listar mermas - lista vacía
    # ------------------------------------------------------------------
    def test_listar_mermas_vacia(self, client, auth_headers):
        resp = client.get("/api/v1/merma/", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert isinstance(data, list)

    # ------------------------------------------------------------------
    # 4b. Listar mermas con datos
    # ------------------------------------------------------------------
    def test_listar_mermas_con_datos(self, client, auth_headers):
        producto_id = self._crear_producto(client, auth_headers, codigo="MER-LIST01")
        self._registrar_merma(
            client,
            auth_headers,
            producto_id=producto_id,
            tipo="produccion",
            cantidad=1.0,
        )
        resp = client.get("/api/v1/merma/", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    # ------------------------------------------------------------------
    # 5. Listar mermas con filtro tipo
    # ------------------------------------------------------------------
    def test_listar_mermas_filtro_tipo(self, client, auth_headers):
        producto_id = self._crear_producto(client, auth_headers, codigo="MER-TIPO01")
        self._registrar_merma(
            client,
            auth_headers,
            producto_id=producto_id,
            tipo="devolucion",
            cantidad=2.0,
        )
        resp = client.get("/api/v1/merma/?tipo=devolucion", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert isinstance(data, list)
        for item in data:
            assert item["tipo"] == "devolucion"

    # ------------------------------------------------------------------
    # 6. Resumen de merma (mes actual)
    # ------------------------------------------------------------------
    def test_resumen_merma_mes_actual(self, client, auth_headers):
        hoy = date.today()
        primer_dia = hoy.replace(day=1).isoformat()
        ultimo_dia = hoy.isoformat()
        resp = client.get(
            f"/api/v1/merma/resumen?fecha_inicio={primer_dia}&fecha_fin={ultimo_dia}",
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert isinstance(data, dict)

    # ------------------------------------------------------------------
    # 7. Alertas de caducidad
    # ------------------------------------------------------------------
    def test_alertas_caducidad(self, client, auth_headers):
        resp = client.get("/api/v1/merma/alertas-caducidad", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert isinstance(data, (list, dict))

    def test_alertas_caducidad_con_dias(self, client, auth_headers):
        resp = client.get(
            "/api/v1/merma/alertas-caducidad?dias=30", headers=auth_headers
        )
        assert resp.status_code == 200, resp.text

    # ------------------------------------------------------------------
    # 8. Merma vs producción ratio
    # ------------------------------------------------------------------
    def test_merma_vs_produccion(self, client, auth_headers):
        resp = client.get("/api/v1/merma/merma-vs-produccion", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert isinstance(data, (list, dict))

    def test_merma_vs_produccion_con_dias(self, client, auth_headers):
        resp = client.get(
            "/api/v1/merma/merma-vs-produccion?dias=7", headers=auth_headers
        )
        assert resp.status_code == 200, resp.text

    # ------------------------------------------------------------------
    # 9. Dashboard merma
    # ------------------------------------------------------------------
    def test_dashboard_merma(self, client, auth_headers):
        resp = client.get("/api/v1/merma/dashboard", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert isinstance(data, dict)

    # ------------------------------------------------------------------
    # 10. Registrar merma con tipo inválido debe fallar
    # ------------------------------------------------------------------
    def test_registrar_merma_tipo_invalido(self, client, auth_headers):
        producto_id = self._crear_producto(client, auth_headers, codigo="MER-INVLD01")
        resp = self._registrar_merma(
            client,
            auth_headers,
            producto_id=producto_id,
            tipo="TIPO_QUE_NO_EXISTE",
        )
        assert resp.status_code in (400, 422), resp.text

    # ------------------------------------------------------------------
    # 11. Sin autenticación returns 401 o 403
    # ------------------------------------------------------------------
    def test_listar_mermas_sin_autenticacion(self, client):
        resp = client.get("/api/v1/merma/")
        assert resp.status_code in (401, 403), resp.text

    def test_registrar_merma_sin_autenticacion(self, client):
        hoy = date.today().isoformat()
        resp = client.post(
            "/api/v1/merma/",
            json={
                "tipo": "otro",
                "cantidad": 1.0,
                "unidad_medida": "pz",
                "costo_unitario": "10.00",
                "motivo": "Test sin auth",
                "fecha_merma": hoy,
                "producto_id": 1,
            },
        )
        assert resp.status_code in (401, 403), resp.text

    # ------------------------------------------------------------------
    # 12. Resumen sin fechas debe fallar (400 o 422)
    # ------------------------------------------------------------------
    def test_resumen_sin_fechas_falla(self, client, auth_headers):
        resp = client.get("/api/v1/merma/resumen", headers=auth_headers)
        assert resp.status_code in (400, 422), resp.text
