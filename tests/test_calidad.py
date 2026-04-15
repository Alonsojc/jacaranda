"""Tests para el módulo de control de calidad y trazabilidad."""

from datetime import date, datetime, timedelta

import pytest


class TestCalidad:
    """Tests del módulo de calidad: checklists, trazabilidad, recalls e indicadores."""

    # ------------------------------------------------------------------
    # Helpers de creación de datos
    # ------------------------------------------------------------------

    def _crear_ingrediente(self, client, auth_headers, nombre="HarinaCalidad", unidad="kg"):
        resp = client.post(
            "/api/v1/inventario/ingredientes",
            json={
                "nombre": nombre,
                "unidad_medida": unidad,
                "stock_actual": "100.0",
                "stock_minimo": "5.0",
                "costo_unitario": "20.00",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201, f"Crear ingrediente falló: {resp.text}"
        return resp.json()["id"]

    def _crear_lote(self, client, auth_headers, ingrediente_id, numero_lote="LOTE-CAL-001"):
        hoy = date.today().isoformat()
        caducidad = (date.today() + timedelta(days=60)).isoformat()
        resp = client.post(
            "/api/v1/inventario/lotes",
            json={
                "ingrediente_id": ingrediente_id,
                "numero_lote": numero_lote,
                "fecha_recepcion": hoy,
                "fecha_caducidad": caducidad,
                "cantidad": "50.0",
                "costo_unitario": "20.00",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201, f"Crear lote falló: {resp.text}"
        return resp.json()["id"]

    def _crear_producto(self, client, auth_headers, codigo="CAL-P001"):
        resp = client.post(
            "/api/v1/inventario/productos",
            json={
                "codigo": codigo,
                "nombre": f"Producto {codigo}",
                "precio_unitario": "40.00",
                "tasa_iva": "0.00",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201, f"Crear producto falló: {resp.text}"
        return resp.json()["id"]

    def _crear_receta(self, client, auth_headers, producto_id, ingrediente_id, nombre="Receta Calidad"):
        resp = client.post(
            "/api/v1/recetas/",
            json={
                "producto_id": producto_id,
                "nombre": nombre,
                "rendimiento": 12,
                "ingredientes": [
                    {"ingrediente_id": ingrediente_id, "cantidad": "0.500"},
                ],
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201, f"Crear receta falló: {resp.text}"
        return resp.json()["id"]

    def _crear_orden_produccion(self, client, auth_headers, receta_id):
        fecha = (datetime.now() + timedelta(hours=1)).isoformat()
        resp = client.post(
            "/api/v1/recetas/produccion",
            json={
                "receta_id": receta_id,
                "cantidad_lotes": "1",
                "fecha_programada": fecha,
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201, f"Crear orden producción falló: {resp.text}"
        return resp.json()["id"]

    def _setup_completo(self, client, auth_headers, suffix="01"):
        """Crea la cadena completa: ingrediente -> lote -> producto -> receta -> orden."""
        ing_id = self._crear_ingrediente(client, auth_headers, nombre=f"Harina-{suffix}")
        lote_id = self._crear_lote(client, auth_headers, ing_id, numero_lote=f"LOTE-{suffix}")
        prod_id = self._crear_producto(client, auth_headers, codigo=f"CAL-{suffix}")
        receta_id = self._crear_receta(client, auth_headers, prod_id, ing_id, nombre=f"Receta-{suffix}")
        orden_id = self._crear_orden_produccion(client, auth_headers, receta_id)
        return {
            "ingrediente_id": ing_id,
            "lote_id": lote_id,
            "producto_id": prod_id,
            "receta_id": receta_id,
            "orden_id": orden_id,
        }

    # ------------------------------------------------------------------
    # 1. Crear checklist exitoso
    # ------------------------------------------------------------------

    def test_crear_checklist_exitoso(self, client, auth_headers, admin_user):
        datos = self._setup_completo(client, auth_headers, suffix="CK01")
        hoy = date.today().isoformat()
        resp = client.post(
            "/api/v1/calidad/checklists",
            json={
                "orden_produccion_id": datos["orden_id"],
                "producto_id": datos["producto_id"],
                "fecha_inspeccion": hoy,
                "inspector_id": admin_user.id,
                "estado": "pendiente",
                "apariencia": 4,
                "textura": 5,
                "sabor": 4,
                "peso_correcto": True,
                "empaque_correcto": True,
                "temperatura_correcta": False,
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["orden_produccion_id"] == datos["orden_id"]
        assert data["producto_id"] == datos["producto_id"]
        assert data["apariencia"] == 4
        assert data["peso_correcto"] is True
        assert "calificacion_global" in data

    # ------------------------------------------------------------------
    # 2. Listar checklists
    # ------------------------------------------------------------------

    def test_listar_checklists(self, client, auth_headers):
        resp = client.get("/api/v1/calidad/checklists", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        assert isinstance(resp.json(), list)

    def test_listar_checklists_con_datos(self, client, auth_headers, admin_user):
        datos = self._setup_completo(client, auth_headers, suffix="CK02")
        hoy = date.today().isoformat()
        client.post(
            "/api/v1/calidad/checklists",
            json={
                "orden_produccion_id": datos["orden_id"],
                "producto_id": datos["producto_id"],
                "fecha_inspeccion": hoy,
                "inspector_id": admin_user.id,
                "estado": "aprobado",
                "apariencia": 5,
                "textura": 5,
                "sabor": 5,
                "peso_correcto": True,
                "empaque_correcto": True,
                "temperatura_correcta": True,
            },
            headers=auth_headers,
        )
        resp = client.get("/api/v1/calidad/checklists", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        items = resp.json()
        assert isinstance(items, list)
        assert len(items) >= 1

    # ------------------------------------------------------------------
    # 3. Obtener checklist por ID
    # ------------------------------------------------------------------

    def test_obtener_checklist_por_id(self, client, auth_headers, admin_user):
        datos = self._setup_completo(client, auth_headers, suffix="CK03")
        hoy = date.today().isoformat()
        crear_resp = client.post(
            "/api/v1/calidad/checklists",
            json={
                "orden_produccion_id": datos["orden_id"],
                "producto_id": datos["producto_id"],
                "fecha_inspeccion": hoy,
                "inspector_id": admin_user.id,
                "estado": "pendiente",
                "apariencia": 3,
                "textura": 3,
                "sabor": 3,
                "peso_correcto": False,
                "empaque_correcto": False,
                "temperatura_correcta": False,
            },
            headers=auth_headers,
        )
        assert crear_resp.status_code == 201, crear_resp.text
        checklist_id = crear_resp.json()["id"]

        resp = client.get(f"/api/v1/calidad/checklists/{checklist_id}", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["id"] == checklist_id
        assert data["producto_id"] == datos["producto_id"]

    def test_obtener_checklist_inexistente(self, client, auth_headers):
        resp = client.get("/api/v1/calidad/checklists/99999", headers=auth_headers)
        assert resp.status_code == 404, resp.text

    # ------------------------------------------------------------------
    # 4. Registrar trazabilidad
    # ------------------------------------------------------------------

    def test_registrar_trazabilidad(self, client, auth_headers):
        datos = self._setup_completo(client, auth_headers, suffix="TR01")
        resp = client.post(
            "/api/v1/calidad/trazabilidad",
            json={
                "lote_ingrediente_id": datos["lote_id"],
                "producto_id": datos["producto_id"],
                "cantidad_usada": "10.5",
                "notas": "Uso en prueba de trazabilidad",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["lote_ingrediente_id"] == datos["lote_id"]
        assert data["producto_id"] == datos["producto_id"]
        assert float(data["cantidad_usada"]) == 10.5

    def test_registrar_trazabilidad_lote_inexistente(self, client, auth_headers):
        resp = client.post(
            "/api/v1/calidad/trazabilidad",
            json={
                "lote_ingrediente_id": 99999,
                "cantidad_usada": "5.0",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 404, resp.text

    # ------------------------------------------------------------------
    # 5. Trazabilidad por producto (forward)
    # ------------------------------------------------------------------

    def test_trazabilidad_producto_forward(self, client, auth_headers):
        datos = self._setup_completo(client, auth_headers, suffix="TR02")
        # Registrar trazabilidad para el producto
        client.post(
            "/api/v1/calidad/trazabilidad",
            json={
                "lote_ingrediente_id": datos["lote_id"],
                "producto_id": datos["producto_id"],
                "cantidad_usada": "5.0",
            },
            headers=auth_headers,
        )
        resp = client.get(
            f"/api/v1/calidad/trazabilidad/producto/{datos['producto_id']}",
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert data[0]["lote_ingrediente_id"] == datos["lote_id"]

    def test_trazabilidad_producto_sin_registros(self, client, auth_headers):
        prod_id = self._crear_producto(client, auth_headers, codigo="CAL-EMPTY01")
        resp = client.get(
            f"/api/v1/calidad/trazabilidad/producto/{prod_id}",
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == []

    # ------------------------------------------------------------------
    # 6. Trazabilidad por lote (reverse)
    # ------------------------------------------------------------------

    def test_trazabilidad_lote_reverse(self, client, auth_headers):
        datos = self._setup_completo(client, auth_headers, suffix="TR03")
        # Registrar trazabilidad vinculando lote al producto
        client.post(
            "/api/v1/calidad/trazabilidad",
            json={
                "lote_ingrediente_id": datos["lote_id"],
                "producto_id": datos["producto_id"],
                "cantidad_usada": "8.0",
                "notas": "Test trazabilidad inversa",
            },
            headers=auth_headers,
        )
        resp = client.get(
            f"/api/v1/calidad/trazabilidad/lote/{datos['lote_id']}",
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert data[0]["producto_id"] == datos["producto_id"]

    def test_trazabilidad_lote_sin_registros(self, client, auth_headers):
        ing_id = self._crear_ingrediente(client, auth_headers, nombre="HarinaVacia")
        lote_id = self._crear_lote(client, auth_headers, ing_id, numero_lote="LOTE-VACIO")
        resp = client.get(
            f"/api/v1/calidad/trazabilidad/lote/{lote_id}",
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == []

    # ------------------------------------------------------------------
    # 7. Crear alerta recall
    # ------------------------------------------------------------------

    def test_crear_alerta_recall(self, client, auth_headers):
        ing_id = self._crear_ingrediente(client, auth_headers, nombre="HarinaRecall")
        lote_id = self._crear_lote(client, auth_headers, ing_id, numero_lote="LOTE-RECALL-01")
        resp = client.post(
            "/api/v1/calidad/recalls",
            json={
                "lote_ingrediente_id": lote_id,
                "motivo": "Contaminación detectada en análisis microbiológico",
                "severidad": "alta",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["lote_ingrediente_id"] == lote_id
        assert data["severidad"] == "alta"
        assert data["estado"] == "abierta"
        assert "motivo" in data

    def test_crear_recall_severidad_invalida(self, client, auth_headers):
        ing_id = self._crear_ingrediente(client, auth_headers, nombre="HarinaInv")
        lote_id = self._crear_lote(client, auth_headers, ing_id, numero_lote="LOTE-INV-01")
        resp = client.post(
            "/api/v1/calidad/recalls",
            json={
                "lote_ingrediente_id": lote_id,
                "motivo": "Problema",
                "severidad": "extrema",  # no válida
            },
            headers=auth_headers,
        )
        assert resp.status_code == 422, resp.text

    # ------------------------------------------------------------------
    # 8. Listar recalls
    # ------------------------------------------------------------------

    def test_listar_recalls_vacia(self, client, auth_headers):
        resp = client.get("/api/v1/calidad/recalls", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        assert isinstance(resp.json(), list)

    def test_listar_recalls_con_datos(self, client, auth_headers):
        ing_id = self._crear_ingrediente(client, auth_headers, nombre="HarinaList")
        lote_id = self._crear_lote(client, auth_headers, ing_id, numero_lote="LOTE-LIST-01")
        client.post(
            "/api/v1/calidad/recalls",
            json={
                "lote_ingrediente_id": lote_id,
                "motivo": "Presencia de cuerpos extraños",
                "severidad": "media",
            },
            headers=auth_headers,
        )
        resp = client.get("/api/v1/calidad/recalls", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        items = resp.json()
        assert isinstance(items, list)
        assert len(items) >= 1

    def test_listar_recalls_filtro_estado(self, client, auth_headers):
        resp = client.get("/api/v1/calidad/recalls?estado=abierta", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        for item in resp.json():
            assert item["estado"] == "abierta"

    # ------------------------------------------------------------------
    # 9. Resolver recall
    # ------------------------------------------------------------------

    def test_resolver_recall(self, client, auth_headers):
        ing_id = self._crear_ingrediente(client, auth_headers, nombre="HarinaResolver")
        lote_id = self._crear_lote(client, auth_headers, ing_id, numero_lote="LOTE-RES-01")
        crear_resp = client.post(
            "/api/v1/calidad/recalls",
            json={
                "lote_ingrediente_id": lote_id,
                "motivo": "Nivel de humedad fuera de especificaciones",
                "severidad": "baja",
            },
            headers=auth_headers,
        )
        assert crear_resp.status_code == 201, crear_resp.text
        recall_id = crear_resp.json()["id"]

        resp = client.post(
            f"/api/v1/calidad/recalls/{recall_id}/resolver",
            json={"acciones_tomadas": "Lote retirado y destruido. Proveedor notificado."},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["estado"] == "resuelta"
        assert data["acciones_tomadas"] is not None
        assert data["resuelto_en"] is not None

    def test_resolver_recall_inexistente(self, client, auth_headers):
        resp = client.post(
            "/api/v1/calidad/recalls/99999/resolver",
            json={"acciones_tomadas": "Acción sobre recall inexistente"},
            headers=auth_headers,
        )
        assert resp.status_code == 400, resp.text

    # ------------------------------------------------------------------
    # 10. Indicadores de calidad
    # ------------------------------------------------------------------

    def test_indicadores_calidad(self, client, auth_headers):
        resp = client.get("/api/v1/calidad/indicadores", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert isinstance(data, dict)
        assert "total_inspecciones" in data
        assert "aprobados" in data
        assert "rechazados" in data
        assert "porcentaje_aprobados" in data
        assert "dias" in data

    def test_indicadores_calidad_con_dias(self, client, auth_headers):
        resp = client.get("/api/v1/calidad/indicadores?dias=7", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["dias"] == 7

    # ------------------------------------------------------------------
    # 11. Dashboard de calidad
    # ------------------------------------------------------------------

    def test_dashboard_calidad(self, client, auth_headers):
        resp = client.get("/api/v1/calidad/dashboard", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert isinstance(data, dict)
        assert "indicadores" in data
        assert "alertas_activas" in data
        assert "ultimos_checklists" in data
        assert "productos_sin_inspeccion_reciente" in data

    def test_dashboard_alertas_activas_incluye_recall(self, client, auth_headers):
        ing_id = self._crear_ingrediente(client, auth_headers, nombre="HarinaDash")
        lote_id = self._crear_lote(client, auth_headers, ing_id, numero_lote="LOTE-DASH-01")
        client.post(
            "/api/v1/calidad/recalls",
            json={
                "lote_ingrediente_id": lote_id,
                "motivo": "Prueba de dashboard",
                "severidad": "critica",
            },
            headers=auth_headers,
        )
        resp = client.get("/api/v1/calidad/dashboard", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert isinstance(data["alertas_activas"], list)
        assert len(data["alertas_activas"]) >= 1

    # ------------------------------------------------------------------
    # 12. Sin autenticación (401/403)
    # ------------------------------------------------------------------

    def test_listar_checklists_sin_autenticacion(self, client):
        resp = client.get("/api/v1/calidad/checklists")
        assert resp.status_code in (401, 403), resp.text

    def test_crear_checklist_sin_autenticacion(self, client):
        resp = client.post(
            "/api/v1/calidad/checklists",
            json={
                "orden_produccion_id": 1,
                "producto_id": 1,
                "fecha_inspeccion": date.today().isoformat(),
                "inspector_id": 1,
                "estado": "pendiente",
                "peso_correcto": False,
                "empaque_correcto": False,
                "temperatura_correcta": False,
            },
        )
        assert resp.status_code in (401, 403), resp.text

    def test_crear_recall_sin_autenticacion(self, client):
        resp = client.post(
            "/api/v1/calidad/recalls",
            json={
                "lote_ingrediente_id": 1,
                "motivo": "Test sin auth",
                "severidad": "baja",
            },
        )
        assert resp.status_code in (401, 403), resp.text

    def test_indicadores_sin_autenticacion(self, client):
        resp = client.get("/api/v1/calidad/indicadores")
        assert resp.status_code in (401, 403), resp.text

    def test_dashboard_sin_autenticacion(self, client):
        resp = client.get("/api/v1/calidad/dashboard")
        assert resp.status_code in (401, 403), resp.text

    def test_trazabilidad_sin_autenticacion(self, client):
        resp = client.post(
            "/api/v1/calidad/trazabilidad",
            json={
                "lote_ingrediente_id": 1,
                "cantidad_usada": "1.0",
            },
        )
        assert resp.status_code in (401, 403), resp.text
