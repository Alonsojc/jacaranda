"""Tests de integración para el módulo de ventas."""

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from app.services.venta_service import _zona_operacion


class TestVentas:
    """Tests para el flujo completo de ventas."""

    def _crear_producto(self, client, auth_headers, codigo="PAN-001", precio="15.00", **extra):
        """Helper: crea un producto y devuelve su ID."""
        payload = {
            "codigo": codigo,
            "nombre": f"Producto {codigo}",
            "precio_unitario": precio,
            "tasa_iva": "0.00",
        }
        payload.update(extra)
        resp = client.post("/api/v1/inventario/productos", json=payload, headers=auth_headers)
        assert resp.status_code == 201
        return resp.json()["id"]

    def _crear_caja(self, client, auth_headers, nombre="Caja grande", stock=20, minimo=3):
        resp = client.post("/api/v1/inventario/ingredientes", json={
            "nombre": nombre,
            "unidad_medida": "caja",
            "stock_minimo": str(minimo),
            "costo_unitario": "5.00",
        }, headers=auth_headers)
        assert resp.status_code == 201, resp.text
        caja_id = resp.json()["id"]
        mov = client.post("/api/v1/inventario/movimientos", json={
            "tipo": "entrada_ajuste",
            "ingrediente_id": caja_id,
            "cantidad": str(stock),
            "referencia": "Stock inicial cajas test",
        }, headers=auth_headers)
        assert mov.status_code == 201, mov.text
        return caja_id

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

    def test_venta_bbva_guarda_referencia_para_conciliacion(self, client, auth_headers, db):
        from app.models.venta import PagoVenta

        pid = self._crear_producto(client, auth_headers, "PAN-BBVA", "40.00")
        self._agregar_stock(client, auth_headers, pid)
        resp = client.post("/api/v1/punto-de-venta/ventas", json={
            "metodo_pago": "03",
            "terminal": "bbva",
            "monto_recibido": "80.00",
            "referencia_pago": "AUTH-1234",
            "detalles": [{"producto_id": pid, "cantidad": "2"}],
        }, headers=auth_headers)
        assert resp.status_code == 201, resp.text
        venta = resp.json()
        assert venta["terminal"] == "bbva"
        assert venta["metodo_pago"] == "28"
        assert venta["pagos"][0]["referencia"] == "AUTH-1234"
        assert venta["pagos"][0]["metodo_pago"] == "28"
        assert venta["pagos"][0]["terminal"] == "bbva"
        assert venta["pagos"][0]["proveedor"] == "bbva"
        assert venta["pagos"][0]["estado"] == "pagado"

        pago = db.query(PagoVenta).filter(PagoVenta.venta_id == venta["id"]).one()
        assert pago.referencia == "AUTH-1234"
        assert pago.metodo_pago.value == "28"
        assert pago.terminal.value == "bbva"
        assert pago.proveedor == "bbva"

        ticket = client.get(
            f"/api/v1/punto-de-venta/ventas/{venta['id']}/ticket",
            headers=auth_headers,
        )
        assert ticket.status_code == 200
        assert "AUTH-1234" in ticket.json()["metodo_pago"]

    def test_pago_dividido_separa_canales_y_corte_conciliacion(self, client, auth_headers):
        pid = self._crear_producto(client, auth_headers, "PAN-SPLIT-PAY", "100.00")
        self._agregar_stock(client, auth_headers, pid)

        resp = client.post("/api/v1/punto-de-venta/ventas", json={
            "metodo_pago": "01",
            "monto_recibido": "100.00",
            "detalles": [{"producto_id": pid, "cantidad": "1"}],
            "pagos": [
                {"metodo_pago": "01", "terminal": "efectivo", "monto": "10.00"},
                {"metodo_pago": "04", "terminal": "clip", "monto": "20.00"},
                {"metodo_pago": "28", "terminal": "bbva", "monto": "30.00"},
                {"metodo_pago": "03", "terminal": "efectivo", "monto": "40.00"},
            ],
        }, headers=auth_headers)
        assert resp.status_code == 201, resp.text
        venta = resp.json()
        pagos = {(p["metodo_pago"], p["terminal"]): p for p in venta["pagos"]}
        assert pagos[("01", "efectivo")]["monto"] == "10.00"
        assert pagos[("04", "clip")]["proveedor"] == "clip"
        assert pagos[("28", "bbva")]["proveedor"] == "bbva"
        assert pagos[("03", "efectivo")]["monto"] == "40.00"

        resumen = client.get("/api/v1/punto-de-venta/corte-caja/resumen", headers=auth_headers)
        assert resumen.status_code == 200
        corte = resumen.json()
        assert corte["total_ventas_efectivo"] == "10.00"
        assert corte["total_ventas_clip"] == "20.00"
        assert corte["total_ventas_bbva"] == "30.00"
        assert corte["total_ventas_transferencia"] == "40.00"
        assert Decimal(str(corte["total_ventas_tarjeta"])) == Decimal("0.00")

        hoy = datetime.now(_zona_operacion()).date()
        reporte = client.get(
            f"/api/v1/reportes/ventas?fecha_inicio={hoy.isoformat()}&fecha_fin={hoy.isoformat()}",
            headers=auth_headers,
        )
        assert reporte.status_code == 200
        por_metodo = reporte.json()["por_metodo_pago"]
        assert por_metodo["efectivo"]["total"] == 10.0
        assert por_metodo["clip"]["label"] == "CLIP"
        assert por_metodo["bbva"]["total"] == 30.0
        assert por_metodo["transferencia"]["total"] == 40.0

        kpis = client.get("/api/v1/kpis/metodos-pago?dias=7", headers=auth_headers)
        assert kpis.status_code == 200
        labels = {item["metodo"]: item for item in kpis.json()}
        assert labels["clip"]["label"] == "CLIP"
        assert labels["bbva"]["total"] == 30.0

        conciliacion = client.get(
            f"/api/v1/contabilidad/banco/conciliacion?mes={hoy.month}&anio={hoy.year}",
            headers=auth_headers,
        )
        assert conciliacion.status_code == 200
        assert conciliacion.json()["saldo_sistema"] == 90.0

    def test_rechaza_terminal_tarjeta_con_forma_sat_incorrecta(self, client, auth_headers):
        pid = self._crear_producto(client, auth_headers, "PAN-PAY-INVALID", "20.00")
        self._agregar_stock(client, auth_headers, pid)

        resp = client.post("/api/v1/punto-de-venta/ventas", json={
            "metodo_pago": "01",
            "terminal": "clip",
            "monto_recibido": "20.00",
            "detalles": [{"producto_id": pid, "cantidad": "1"}],
        }, headers=auth_headers)
        assert resp.status_code == 400
        assert "CLIP/BBVA" in resp.json()["detail"]

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

    def test_venta_permite_stock_insuficiente_y_audita(self, client, auth_headers, db):
        from app.models.auditoria import LogAuditoria

        pid = self._crear_producto(client, auth_headers, "PAN-003")
        self._agregar_stock(client, auth_headers, pid, 2)
        resp = client.post("/api/v1/punto-de-venta/ventas", json={
            "metodo_pago": "01",
            "monto_recibido": "500.00",
            "detalles": [{"producto_id": pid, "cantidad": "5"}],
        }, headers=auth_headers)
        assert resp.status_code == 201, resp.text
        venta = resp.json()
        assert venta["total"] == "75.00"

        prod = client.get(f"/api/v1/inventario/productos/{pid}", headers=auth_headers)
        assert float(prod.json()["stock_actual"]) == -3.0

        evento = db.query(LogAuditoria).filter(
            LogAuditoria.accion == "venta_stock_negativo",
            LogAuditoria.modulo == "ventas",
            LogAuditoria.entidad_id == venta["id"],
        ).first()
        assert evento is not None
        assert "stock_despues" in evento.datos_nuevos

    def test_venta_rechaza_cantidad_fraccionaria(self, client, auth_headers):
        pid = self._crear_producto(client, auth_headers, "PAN-FRAC")
        self._agregar_stock(client, auth_headers, pid, 10)
        resp = client.post("/api/v1/punto-de-venta/ventas", json={
            "metodo_pago": "01",
            "monto_recibido": "100.00",
            "detalles": [{"producto_id": pid, "cantidad": "1.5"}],
        }, headers=auth_headers)
        assert resp.status_code == 422

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
            json={"motivo": "Cancelacion de prueba"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["estado"] == "cancelada"
        # Stock should be restored to 20
        prod = client.get(f"/api/v1/inventario/productos/{pid}", headers=auth_headers).json()
        assert float(prod["stock_actual"]) == 20.0

    def test_cancelar_venta_requiere_motivo(self, client, auth_headers):
        pid = self._crear_producto(client, auth_headers, "PAN-MOTIVO")
        self._agregar_stock(client, auth_headers, pid, 5)
        venta = client.post("/api/v1/punto-de-venta/ventas", json={
            "metodo_pago": "01",
            "monto_recibido": "100.00",
            "detalles": [{"producto_id": pid, "cantidad": "1"}],
        }, headers=auth_headers).json()

        sin_body = client.post(
            f"/api/v1/punto-de-venta/ventas/{venta['id']}/cancelar",
            headers=auth_headers,
        )
        motivo_corto = client.post(
            f"/api/v1/punto-de-venta/ventas/{venta['id']}/cancelar",
            json={"motivo": "dup"},
            headers=auth_headers,
        )

        assert sin_body.status_code == 422
        assert motivo_corto.status_code == 422

    def test_venta_descuenta_y_cancela_empaque(self, client, auth_headers, db):
        from app.models.auditoria import LogAuditoria
        from app.models.inventario import MovimientoInventario, TipoMovimiento

        caja_id = self._crear_caja(client, auth_headers, "Caja POS")
        pid = self._crear_producto(
            client,
            auth_headers,
            "PAN-CAJA",
            caja_ingrediente_id=caja_id,
            caja_cantidad="1",
        )
        self._agregar_stock(client, auth_headers, pid, 10)
        venta = client.post("/api/v1/punto-de-venta/ventas", json={
            "metodo_pago": "01",
            "monto_recibido": "100.00",
            "detalles": [{"producto_id": pid, "cantidad": "3"}],
        }, headers=auth_headers)
        assert venta.status_code == 201, venta.text

        caja = client.get(f"/api/v1/inventario/ingredientes/{caja_id}", headers=auth_headers)
        assert float(caja.json()["stock_actual"]) == 17.0
        salida_empaque = db.query(MovimientoInventario).filter(
            MovimientoInventario.ingrediente_id == caja_id,
            MovimientoInventario.tipo == TipoMovimiento.SALIDA_VENTA,
            MovimientoInventario.referencia == f"Venta {venta.json()['folio']}",
        ).first()
        assert salida_empaque is not None
        assert float(salida_empaque.cantidad) == 3.0
        audit_salida = db.query(LogAuditoria).filter(
            LogAuditoria.modulo == "inventario",
            LogAuditoria.accion == "salida_venta",
            LogAuditoria.entidad_id == salida_empaque.id,
        ).first()
        assert audit_salida is not None

        cancel = client.post(
            f"/api/v1/punto-de-venta/ventas/{venta.json()['id']}/cancelar",
            json={"motivo": "Cancelacion de empaque"},
            headers=auth_headers,
        )
        assert cancel.status_code == 200, cancel.text
        caja = client.get(f"/api/v1/inventario/ingredientes/{caja_id}", headers=auth_headers)
        assert float(caja.json()["stock_actual"]) == 20.0
        entrada_empaque = db.query(MovimientoInventario).filter(
            MovimientoInventario.ingrediente_id == caja_id,
            MovimientoInventario.tipo == TipoMovimiento.ENTRADA_DEVOLUCION,
            MovimientoInventario.referencia == f"Cancelación venta {venta.json()['folio']}",
        ).first()
        assert entrada_empaque is not None

    def test_producto_valida_empaque_compatible_y_en_uso(self, client, auth_headers):
        kg_resp = client.post("/api/v1/inventario/ingredientes", json={
            "nombre": "Harina no empaque",
            "unidad_medida": "kg",
            "stock_minimo": "0",
            "costo_unitario": "10.00",
        }, headers=auth_headers)
        assert kg_resp.status_code == 201
        invalido = client.post("/api/v1/inventario/productos", json={
            "codigo": "PACK-KG",
            "nombre": "Pastel con empaque invalido",
            "precio_unitario": "100.00",
            "tasa_iva": "0.00",
            "caja_ingrediente_id": kg_resp.json()["id"],
            "caja_cantidad": "1",
        }, headers=auth_headers)
        assert invalido.status_code == 400
        assert "caja, bolsa o pieza" in invalido.json()["detail"]

        caja_id = self._crear_caja(client, auth_headers, "Caja chica validacion")
        cantidad_cero = client.post("/api/v1/inventario/productos", json={
            "codigo": "PACK-CERO",
            "nombre": "Pastel caja cero",
            "precio_unitario": "100.00",
            "tasa_iva": "0.00",
            "caja_ingrediente_id": caja_id,
            "caja_cantidad": "0",
        }, headers=auth_headers)
        assert cantidad_cero.status_code == 400
        assert "mayor a cero" in cantidad_cero.json()["detail"]

        pid = self._crear_producto(
            client,
            auth_headers,
            "PACK-OK",
            caja_ingrediente_id=caja_id,
            caja_cantidad="1",
        )
        assert pid
        borrar = client.delete(f"/api/v1/inventario/ingredientes/{caja_id}", headers=auth_headers)
        assert borrar.status_code == 400
        assert "caja/empaque" in borrar.json()["detail"]

    def test_alertas_empaques(self, client, auth_headers):
        caja_id = self._crear_caja(client, auth_headers, "Caja mediana alerta", stock=1, minimo=3)
        pid = self._crear_producto(
            client,
            auth_headers,
            "PACK-ALERTA",
            caja_ingrediente_id=caja_id,
            caja_cantidad="1",
        )
        assert pid

        empaques = client.get("/api/v1/inventario/alertas/empaques", headers=auth_headers)
        assert empaques.status_code == 200
        alerta = [item for item in empaques.json() if item["id"] == caja_id][0]
        assert alerta["tipo"] == "empaque"
        assert alerta["severidad"] == "bajo"
        assert alerta["productos"][0]["nombre"] == "Producto PACK-ALERTA"

        stock_bajo = client.get("/api/v1/inventario/alertas/stock-bajo", headers=auth_headers)
        assert stock_bajo.status_code == 200
        assert any(item["id"] == caja_id and item["tipo"] == "empaque" for item in stock_bajo.json())

    def test_cancelar_venta_revierte_puntos_y_audita(self, client, auth_headers, db):
        from app.models.auditoria import LogAuditoria
        from app.models.cliente import Cliente
        from app.models.lealtad import HistorialPuntos

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
        cliente_db = db.query(Cliente).filter(Cliente.id == cliente["id"]).first()
        assert float(cliente_db.monto_lealtad_acumulado) == float(venta["total"])

        resp = client.post(
            f"/api/v1/punto-de-venta/ventas/{venta['id']}/cancelar",
            json={"motivo": "Cancelacion lealtad"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        puntos = client.get(f"/api/v1/clientes/{cliente['id']}/puntos", headers=auth_headers).json()
        assert puntos["puntos"] == 0
        db.refresh(cliente_db)
        assert float(cliente_db.monto_lealtad_acumulado) == 0.0
        historial = db.query(HistorialPuntos).filter(
            HistorialPuntos.cliente_id == cliente["id"],
            HistorialPuntos.venta_id == venta["id"],
        ).order_by(HistorialPuntos.id.asc()).all()
        assert [h.puntos for h in historial] == [10, -10]

        evento = db.query(LogAuditoria).filter(
            LogAuditoria.accion == "cancelar",
            LogAuditoria.modulo == "ventas",
            LogAuditoria.entidad_id == venta["id"],
        ).first()
        assert evento is not None
        assert "puntos_revertidos" in evento.datos_nuevos
        assert evento.motivo == "Cancelacion lealtad"

    def test_venta_canjea_recompensa_pastel_chico_y_cancelacion_la_restaura(
        self,
        client,
        auth_headers,
        db,
    ):
        from decimal import Decimal

        from app.models.auditoria import LogAuditoria
        from app.models.cliente import Cliente
        from app.models.lealtad import HistorialPuntos

        cliente = client.post("/api/v1/clientes/", json={
            "nombre": "Cliente Recompensa",
            "telefono": "4420001111",
            "email": "reward@example.com",
            "cliente_frecuente": True,
        }, headers=auth_headers).json()
        cliente_db = db.query(Cliente).filter(Cliente.id == cliente["id"]).first()
        cliente_db.monto_lealtad_acumulado = Decimal("10000.00")
        db.commit()

        pid = self._crear_producto(client, auth_headers, "PASTEL-CHICO", "500.00")
        self._agregar_stock(client, auth_headers, pid, 3)

        resp = client.post("/api/v1/punto-de-venta/ventas", json={
            "metodo_pago": "01",
            "monto_recibido": "0.00",
            "cliente_id": cliente["id"],
            "canjear_recompensa_lealtad": True,
            "recompensa_lealtad_motivo": "Test canje",
            "detalles": [{"producto_id": pid, "cantidad": "1"}],
        }, headers=auth_headers)
        assert resp.status_code == 201, resp.text
        venta = resp.json()
        assert venta["total"] == "0.00"
        assert venta["descuento"] == "500.00"
        assert venta["recompensa_lealtad_canjeada"] is True
        assert venta["recompensa_lealtad_nombre"] == "Pastel chico gratis"
        assert venta["recompensa_lealtad_monto"] == "500.00"

        db.refresh(cliente_db)
        assert cliente_db.recompensas_lealtad_canjeadas == 1

        evento = db.query(LogAuditoria).filter(
            LogAuditoria.accion == "canjear_recompensa_lealtad",
            LogAuditoria.modulo == "ventas",
            LogAuditoria.entidad_id == venta["id"],
        ).first()
        assert evento is not None
        datos_nuevos = json.loads(evento.datos_nuevos)
        assert datos_nuevos["producto"] == "Producto PASTEL-CHICO"
        assert datos_nuevos["motivo"] == "Test canje"
        movimiento = db.query(HistorialPuntos).filter(
            HistorialPuntos.cliente_id == cliente["id"],
            HistorialPuntos.venta_id == venta["id"],
            HistorialPuntos.puntos == 0,
            HistorialPuntos.concepto.like("Recompensa canjeada:%"),
        ).first()
        assert movimiento is not None
        assert "Test canje" in movimiento.concepto

        cancel = client.post(
            f"/api/v1/punto-de-venta/ventas/{venta['id']}/cancelar",
            json={"motivo": "Restaurar recompensa"},
            headers=auth_headers,
        )
        assert cancel.status_code == 200, cancel.text
        db.refresh(cliente_db)
        assert cliente_db.recompensas_lealtad_canjeadas == 0
        restauracion = db.query(HistorialPuntos).filter(
            HistorialPuntos.cliente_id == cliente["id"],
            HistorialPuntos.venta_id == venta["id"],
            HistorialPuntos.concepto.like("Recompensa restaurada%"),
        ).first()
        assert restauracion is not None

    def test_venta_rechaza_recompensa_sin_motivo(self, client, auth_headers, db):
        from decimal import Decimal

        from app.models.cliente import Cliente

        cliente = client.post("/api/v1/clientes/", json={
            "nombre": "Cliente Sin Motivo",
            "telefono": "4420001212",
            "cliente_frecuente": True,
        }, headers=auth_headers).json()
        cliente_db = db.query(Cliente).filter(Cliente.id == cliente["id"]).first()
        cliente_db.monto_lealtad_acumulado = Decimal("10000.00")
        db.commit()

        pid = self._crear_producto(client, auth_headers, "PASTEL-MOTIVO-CHICO", "400.00")
        self._agregar_stock(client, auth_headers, pid, 2)

        resp = client.post("/api/v1/punto-de-venta/ventas", json={
            "metodo_pago": "01",
            "monto_recibido": "0.00",
            "cliente_id": cliente["id"],
            "canjear_recompensa_lealtad": True,
            "detalles": [{"producto_id": pid, "cantidad": "1"}],
        }, headers=auth_headers)
        assert resp.status_code == 400
        assert "motivo" in resp.json()["detail"].lower()

    def test_venta_rechaza_recompensa_sin_saldo(self, client, auth_headers):
        cliente = client.post("/api/v1/clientes/", json={
            "nombre": "Cliente Sin Saldo",
            "telefono": "4420001313",
            "cliente_frecuente": True,
        }, headers=auth_headers).json()
        pid = self._crear_producto(client, auth_headers, "PASTEL-SALDO-CHICO", "400.00")
        self._agregar_stock(client, auth_headers, pid, 2)

        resp = client.post("/api/v1/punto-de-venta/ventas", json={
            "metodo_pago": "01",
            "monto_recibido": "400.00",
            "cliente_id": cliente["id"],
            "canjear_recompensa_lealtad": True,
            "recompensa_lealtad_motivo": "Cliente solicita premio",
            "detalles": [{"producto_id": pid, "cantidad": "1"}],
        }, headers=auth_headers)
        assert resp.status_code == 400
        assert "no tiene recompensas" in resp.json()["detail"].lower()

    def test_venta_rechaza_recompensa_sin_producto_chico(self, client, auth_headers, db):
        from decimal import Decimal

        from app.models.cliente import Cliente

        cliente = client.post("/api/v1/clientes/", json={
            "nombre": "Cliente Recompensa 2",
            "telefono": "4420002222",
            "email": "reward2@example.com",
            "cliente_frecuente": True,
        }, headers=auth_headers).json()
        cliente_db = db.query(Cliente).filter(Cliente.id == cliente["id"]).first()
        cliente_db.monto_lealtad_acumulado = Decimal("10000.00")
        db.commit()

        pid = self._crear_producto(client, auth_headers, "BROWNIE-REG", "70.00")
        self._agregar_stock(client, auth_headers, pid, 3)

        resp = client.post("/api/v1/punto-de-venta/ventas", json={
            "metodo_pago": "01",
            "monto_recibido": "70.00",
            "cliente_id": cliente["id"],
            "canjear_recompensa_lealtad": True,
            "recompensa_lealtad_motivo": "Test sin pastel chico",
            "detalles": [{"producto_id": pid, "cantidad": "1"}],
        }, headers=auth_headers)
        assert resp.status_code == 400
        assert "pastel chico" in resp.json()["detail"]

    def test_cancelar_venta_ya_cancelada(self, client, auth_headers):
        pid = self._crear_producto(client, auth_headers, "PAN-005")
        self._agregar_stock(client, auth_headers, pid, 10)
        venta = client.post("/api/v1/punto-de-venta/ventas", json={
            "metodo_pago": "01",
            "monto_recibido": "100.00",
            "detalles": [{"producto_id": pid, "cantidad": "1"}],
        }, headers=auth_headers).json()
        client.post(
            f"/api/v1/punto-de-venta/ventas/{venta['id']}/cancelar",
            json={"motivo": "Primer cancelacion"},
            headers=auth_headers,
        )
        resp = client.post(
            f"/api/v1/punto-de-venta/ventas/{venta['id']}/cancelar",
            json={"motivo": "Segunda cancelacion"},
            headers=auth_headers,
        )
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

    def test_pos_no_cobra_iva_por_default_y_agrega_8_para_factura(self, client, auth_headers):
        pid = self._crear_producto(client, auth_headers, "PASTEL-001", "100.00")
        self._agregar_stock(client, auth_headers, pid, 10)
        resp = client.post("/api/v1/punto-de-venta/ventas", json={
            "metodo_pago": "01",
            "monto_recibido": "200.00",
            "detalles": [{"producto_id": pid, "cantidad": "1"}],
        }, headers=auth_headers)
        assert resp.status_code == 201
        data = resp.json()
        assert data["total"] == "100.00"
        assert data["total_impuestos"] == "0.00"
        assert data["iva_16"] == "0.00"
        assert Decimal(data["detalles"][0]["tasa_iva"]) == Decimal("0.0000")

        resp = client.post("/api/v1/punto-de-venta/ventas", json={
            "metodo_pago": "01",
            "monto_recibido": "200.00",
            "iva_factura_tasa": "0.08",
            "detalles": [{"producto_id": pid, "cantidad": "1"}],
        }, headers=auth_headers)
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["total"] == "108.00"
        assert data["total_impuestos"] == "8.00"
        assert data["iva_16"] == "8.00"
        assert Decimal(data["detalles"][0]["tasa_iva"]) == Decimal("0.0800")

    def test_pos_rechaza_tasa_iva_factura_distinta_a_8(self, client, auth_headers):
        pid = self._crear_producto(client, auth_headers, "PASTEL-IVA-INVALIDO", "100.00")
        self._agregar_stock(client, auth_headers, pid, 10)
        resp = client.post("/api/v1/punto-de-venta/ventas", json={
            "metodo_pago": "01",
            "monto_recibido": "200.00",
            "iva_factura_tasa": "0.16",
            "detalles": [{"producto_id": pid, "cantidad": "1"}],
        }, headers=auth_headers)
        assert resp.status_code == 422

    def test_venta_canjea_puntos_en_misma_transaccion(self, client, auth_headers):
        cliente = client.post("/api/v1/clientes/", json={
            "nombre": "Cliente Canje",
            "telefono": "4421111111",
        }, headers=auth_headers).json()
        pid = self._crear_producto(client, auth_headers, "PAN-CANJE", "100.00")
        self._agregar_stock(client, auth_headers, pid, 10)

        primera = client.post("/api/v1/punto-de-venta/ventas", json={
            "metodo_pago": "01",
            "monto_recibido": "100.00",
            "cliente_id": cliente["id"],
            "detalles": [{"producto_id": pid, "cantidad": "1"}],
        }, headers=auth_headers)
        assert primera.status_code == 201
        assert client.get(
            f"/api/v1/clientes/{cliente['id']}/puntos",
            headers=auth_headers,
        ).json()["puntos"] == 10

        segunda = client.post("/api/v1/punto-de-venta/ventas", json={
            "metodo_pago": "01",
            "monto_recibido": "100.00",
            "cliente_id": cliente["id"],
            "puntos_canjeados": 10,
            "detalles": [{"producto_id": pid, "cantidad": "1"}],
        }, headers=auth_headers)
        assert segunda.status_code == 201, segunda.text
        assert segunda.json()["total"] == "95.00"
        assert segunda.json()["descuento"] == "5.00"
        puntos = client.get(
            f"/api/v1/clientes/{cliente['id']}/puntos",
            headers=auth_headers,
        ).json()
        assert puntos["puntos"] == 9

        cancelada = client.post(
            f"/api/v1/punto-de-venta/ventas/{segunda.json()['id']}/cancelar",
            json={"motivo": "Cancelar canje puntos"},
            headers=auth_headers,
        )
        assert cancelada.status_code == 200
        puntos = client.get(
            f"/api/v1/clientes/{cliente['id']}/puntos",
            headers=auth_headers,
        ).json()
        assert puntos["puntos"] == 10

    def test_corte_resumen_y_no_permite_duplicado(self, client, auth_headers):
        pid = self._crear_producto(client, auth_headers, "CORTE-001", "30.00")
        self._agregar_stock(client, auth_headers, pid, 5)
        venta = client.post("/api/v1/punto-de-venta/ventas", json={
            "metodo_pago": "01",
            "monto_recibido": "100.00",
            "detalles": [{"producto_id": pid, "cantidad": "1"}],
        }, headers=auth_headers)
        assert venta.status_code == 201

        resumen = client.get("/api/v1/punto-de-venta/corte-caja/resumen", headers=auth_headers)
        assert resumen.status_code == 200
        assert resumen.json()["total_ventas_efectivo"] == "30.00"
        assert resumen.json()["corte_existente"] is False

        corte = client.post("/api/v1/punto-de-venta/corte-caja", json={
            "fondo_inicial": "2000.00",
            "efectivo_real": "2030.00",
        }, headers=auth_headers)
        assert corte.status_code == 201, corte.text

        duplicado = client.post("/api/v1/punto-de-venta/corte-caja", json={
            "fondo_inicial": "2000.00",
            "efectivo_real": "2030.00",
        }, headers=auth_headers)
        assert duplicado.status_code == 400
        assert "ya existe" in duplicado.json()["detail"].lower()

    def test_venta_clip_integrada_queda_pendiente_y_no_entra_corte(self, client, auth_headers):
        pid = self._crear_producto(client, auth_headers, "CLIP-PEND", "30.00")
        self._agregar_stock(client, auth_headers, pid, 5)

        venta = client.post("/api/v1/punto-de-venta/ventas", json={
            "metodo_pago": "04",
            "terminal": "clip",
            "pago_integrado": True,
            "monto_recibido": "0.00",
            "detalles": [{"producto_id": pid, "cantidad": "1"}],
        }, headers=auth_headers)
        assert venta.status_code == 201, venta.text
        data = venta.json()
        assert data["estado"] == "pendiente"
        assert data["pago_integrado"] is True
        assert data["pago_proveedor"] == "clip"
        assert data["pago_externo_estado"] == "pendiente"

        resumen = client.get("/api/v1/punto-de-venta/corte-caja/resumen", headers=auth_headers)
        assert resumen.status_code == 200
        assert Decimal(str(resumen.json()["total_ventas_clip"])) == Decimal("0.00")
        assert Decimal(str(resumen.json()["total_ventas"])) == Decimal("0.00")

    def test_clip_pinpad_y_webhook_confirmado_cierra_venta(
        self,
        client,
        auth_headers,
        monkeypatch,
        db,
    ):
        from app.core.config import settings
        from app.models.auditoria import LogAuditoria

        monkeypatch.setattr(settings, "CLIP_PINPAD_SERIAL_NUMBER", "SN-TEST")
        monkeypatch.setattr(settings, "BACKEND_PUBLIC_URL", "https://web-production-b51486.up.railway.app")
        monkeypatch.setattr(settings, "CLIP_WEBHOOK_SECRET", "test-secret")
        monkeypatch.setattr(settings, "CLIP_ALLOW_UNSIGNED_WEBHOOKS", False)

        pid = self._crear_producto(client, auth_headers, "CLIP-OK", "30.00")
        self._agregar_stock(client, auth_headers, pid, 5)

        venta = client.post("/api/v1/punto-de-venta/ventas", json={
            "metodo_pago": "04",
            "terminal": "clip",
            "pago_integrado": True,
            "monto_recibido": "0.00",
            "detalles": [{"producto_id": pid, "cantidad": "1"}],
        }, headers=auth_headers)
        assert venta.status_code == 201, venta.text
        venta_data = venta.json()

        def fake_pinpad(monto, referencia, descripcion="", serial_number_pos=None, webhook_url=None):
            assert str(monto) == "30.00"
            assert referencia == venta_data["folio"]
            assert serial_number_pos is None
            return {
                "pinpad_request_id": "clip-pay-1",
                "status": "pending",
                "reference": referencia,
            }

        monkeypatch.setattr("app.services.clip_service.enviar_cobro_pinpad", fake_pinpad)

        pinpad = client.post(
            "/api/v1/pagos/clip/pinpad",
            json={"venta_id": venta_data["id"]},
            headers=auth_headers,
        )
        assert pinpad.status_code == 200, pinpad.text
        assert pinpad.json()["payment_id"] == "clip-pay-1"
        assert pinpad.json()["estado"] == "pendiente"

        webhook_payload = {
            "id": "evt_clip_1",
            "type": "payment.approved",
            "data": {
                "id": "clip-pay-1",
                "reference": venta_data["folio"],
                "status": "approved",
                "amount": "30.00",
            },
        }
        webhook = client.post(
            "/api/v1/pagos/clip/webhook",
            json=webhook_payload,
            headers={"x-clip-webhook-secret": "test-secret"},
        )
        assert webhook.status_code == 200, webhook.text
        assert webhook.json()["processed"] is True

        replay = client.post(
            "/api/v1/pagos/clip/webhook",
            json=webhook_payload,
            headers={"x-clip-webhook-secret": "test-secret"},
        )
        assert replay.status_code == 200
        assert replay.json()["duplicate"] is True

        venta_confirmada = client.get(
            f"/api/v1/punto-de-venta/ventas/{venta_data['id']}",
            headers=auth_headers,
        )
        assert venta_confirmada.status_code == 200
        venta_confirmada_data = venta_confirmada.json()
        assert venta_confirmada_data["estado"] == "completada"
        assert venta_confirmada_data["pago_externo_id"] == "clip-pay-1"
        assert venta_confirmada_data["pago_externo_estado"] == "pagado"
        assert len(venta_confirmada_data["pagos"]) == 1
        assert venta_confirmada_data["pagos"][0]["terminal"] == "clip"
        assert venta_confirmada_data["pagos"][0]["proveedor"] == "clip"
        assert venta_confirmada_data["pagos"][0]["estado"] == "pagado"
        assert venta_confirmada_data["pagos"][0]["pago_externo_id"] == "clip-pay-1"

        resumen = client.get("/api/v1/punto-de-venta/corte-caja/resumen", headers=auth_headers)
        assert resumen.status_code == 200
        assert resumen.json()["total_ventas_clip"] == "30.00"
        assert resumen.json()["total_ventas"] == "30.00"
        acciones = {
            row.accion
            for row in db.query(LogAuditoria).filter(LogAuditoria.modulo == "pagos").all()
        }
        assert "crear_intento_pago" in acciones
        assert "confirmar_pago_integrado" in acciones

    def test_clip_pinpad_idempotente_no_crea_doble_intento(
        self,
        client,
        auth_headers,
        monkeypatch,
    ):
        from app.core.config import settings

        monkeypatch.setattr(settings, "CLIP_PINPAD_SERIAL_NUMBER", "SN-IDEMP")
        monkeypatch.setattr(settings, "CLIP_WEBHOOK_SECRET", "test-secret")
        monkeypatch.setattr(settings, "CLIP_ALLOW_UNSIGNED_WEBHOOKS", False)

        pid = self._crear_producto(client, auth_headers, "CLIP-IDEMP", "30.00")
        self._agregar_stock(client, auth_headers, pid, 5)
        venta = client.post("/api/v1/punto-de-venta/ventas", json={
            "metodo_pago": "04",
            "terminal": "clip",
            "pago_integrado": True,
            "monto_recibido": "0.00",
            "detalles": [{"producto_id": pid, "cantidad": "1"}],
        }, headers=auth_headers)
        assert venta.status_code == 201, venta.text
        venta_data = venta.json()

        llamadas = []

        def fake_pinpad(monto, referencia, descripcion="", serial_number_pos=None, webhook_url=None):
            llamadas.append(referencia)
            return {
                "pinpad_request_id": "clip-idempotente-1",
                "status": "pending",
                "reference": referencia,
            }

        monkeypatch.setattr("app.services.clip_service.enviar_cobro_pinpad", fake_pinpad)

        primero = client.post(
            "/api/v1/pagos/clip/pinpad",
            json={"venta_id": venta_data["id"]},
            headers=auth_headers,
        )
        segundo = client.post(
            "/api/v1/pagos/clip/pinpad",
            json={"venta_id": venta_data["id"]},
            headers=auth_headers,
        )
        assert primero.status_code == 200, primero.text
        assert segundo.status_code == 200, segundo.text
        assert primero.json()["payment_id"] == "clip-idempotente-1"
        assert segundo.json()["idempotent"] is True
        assert segundo.json()["payment_id"] == "clip-idempotente-1"
        assert llamadas == [venta_data["folio"]]

    def test_clip_pinpad_mock_sin_credenciales_no_marca_pagado(
        self,
        client,
        auth_headers,
        monkeypatch,
    ):
        from app.core.config import settings

        monkeypatch.setattr(settings, "CLIP_PINPAD_MOCK_MODE", True)
        monkeypatch.setattr(settings, "CLIP_PINPAD_SERIAL_NUMBER", "")
        monkeypatch.setattr(settings, "CLIP_PINPAD_AUTHORIZATION", "")
        monkeypatch.setattr(settings, "CLIP_API_KEY", "")
        monkeypatch.setattr(settings, "CLIP_API_SECRET", "")
        monkeypatch.setattr(settings, "BACKEND_PUBLIC_URL", "")

        pid = self._crear_producto(client, auth_headers, "CLIP-MOCK", "30.00")
        self._agregar_stock(client, auth_headers, pid, 5)
        venta = client.post("/api/v1/punto-de-venta/ventas", json={
            "metodo_pago": "28",
            "terminal": "clip",
            "pago_integrado": True,
            "monto_recibido": "0.00",
            "detalles": [{"producto_id": pid, "cantidad": "1"}],
        }, headers=auth_headers)
        assert venta.status_code == 201, venta.text
        venta_data = venta.json()

        pinpad = client.post(
            "/api/v1/pagos/clip/pinpad",
            json={"venta_id": venta_data["id"]},
            headers=auth_headers,
        )
        assert pinpad.status_code == 200, pinpad.text
        data = pinpad.json()
        assert data["payment_id"].startswith("mock-pinpad-")
        assert data["estado"] == "pendiente"
        assert data["respuesta"]["mock"] is True

        pendiente = client.get(
            f"/api/v1/punto-de-venta/ventas/{venta_data['id']}",
            headers=auth_headers,
        )
        assert pendiente.status_code == 200
        assert pendiente.json()["estado"] == "pendiente"
        assert pendiente.json()["pagos"] == []

        resumen = client.get("/api/v1/punto-de-venta/corte-caja/resumen", headers=auth_headers)
        assert resumen.status_code == 200
        assert Decimal(str(resumen.json()["total_ventas_clip"])) == Decimal("0.00")

    def test_clip_webhook_fallido_audita_y_no_entra_corte(
        self,
        client,
        auth_headers,
        monkeypatch,
        db,
    ):
        from app.core.config import settings
        from app.models.auditoria import LogAuditoria

        monkeypatch.setattr(settings, "CLIP_PINPAD_SERIAL_NUMBER", "SN-FAIL")
        monkeypatch.setattr(settings, "CLIP_WEBHOOK_SECRET", "test-secret")
        monkeypatch.setattr(settings, "CLIP_ALLOW_UNSIGNED_WEBHOOKS", False)

        pid = self._crear_producto(client, auth_headers, "CLIP-FAIL", "30.00")
        self._agregar_stock(client, auth_headers, pid, 5)
        venta = client.post("/api/v1/punto-de-venta/ventas", json={
            "metodo_pago": "04",
            "terminal": "clip",
            "pago_integrado": True,
            "monto_recibido": "0.00",
            "detalles": [{"producto_id": pid, "cantidad": "1"}],
        }, headers=auth_headers)
        assert venta.status_code == 201, venta.text
        venta_data = venta.json()

        monkeypatch.setattr(
            "app.services.clip_service.enviar_cobro_pinpad",
            lambda *args, **kwargs: {
                "pinpad_request_id": "clip-fail-1",
                "status": "pending",
                "reference": venta_data["folio"],
            },
        )
        pinpad = client.post(
            "/api/v1/pagos/clip/pinpad",
            json={"venta_id": venta_data["id"]},
            headers=auth_headers,
        )
        assert pinpad.status_code == 200, pinpad.text

        webhook = client.post(
            "/api/v1/pagos/clip/webhook",
            json={
                "id": "evt_clip_fail_1",
                "type": "payment.declined",
                "data": {
                    "id": "clip-fail-1",
                    "reference": venta_data["folio"],
                    "status": "declined",
                    "amount": "30.00",
                },
            },
            headers={"x-clip-webhook-secret": "test-secret"},
        )
        assert webhook.status_code == 200, webhook.text
        assert webhook.json()["processed"] is True

        pendiente = client.get(
            f"/api/v1/punto-de-venta/ventas/{venta_data['id']}",
            headers=auth_headers,
        )
        assert pendiente.status_code == 200
        venta_fallida = pendiente.json()
        assert venta_fallida["estado"] == "pendiente"
        assert venta_fallida["pago_externo_estado"] == "fallido"
        assert venta_fallida["pagos"] == []

        resumen = client.get("/api/v1/punto-de-venta/corte-caja/resumen", headers=auth_headers)
        assert resumen.status_code == 200
        assert Decimal(str(resumen.json()["total_ventas"])) == Decimal("0.00")

        auditoria = db.query(LogAuditoria).filter(
            LogAuditoria.modulo == "pagos",
            LogAuditoria.accion == "fallar_pago_integrado",
        ).first()
        assert auditoria is not None

    def test_cancelar_venta_clip_pendiente_cancela_terminal(
        self,
        client,
        auth_headers,
        monkeypatch,
    ):
        pid = self._crear_producto(client, auth_headers, "CLIP-CANCEL", "30.00")
        self._agregar_stock(client, auth_headers, pid, 5)

        venta = client.post("/api/v1/punto-de-venta/ventas", json={
            "metodo_pago": "04",
            "terminal": "clip",
            "pago_integrado": True,
            "monto_recibido": "0.00",
            "detalles": [{"producto_id": pid, "cantidad": "1"}],
        }, headers=auth_headers)
        assert venta.status_code == 201, venta.text
        venta_data = venta.json()

        monkeypatch.setattr(
            "app.services.clip_service.enviar_cobro_pinpad",
            lambda *args, **kwargs: {
                "pinpad_request_id": "clip-cancel-1",
                "status": "pending",
                "reference": venta_data["folio"],
            },
        )
        pinpad = client.post(
            "/api/v1/pagos/clip/pinpad",
            json={"venta_id": venta_data["id"]},
            headers=auth_headers,
        )
        assert pinpad.status_code == 200, pinpad.text

        cancelados = []

        def fake_cancelar(pinpad_request_id):
            cancelados.append(pinpad_request_id)
            return {"status": "cancelled"}

        monkeypatch.setattr("app.services.clip_service.cancelar_pago_pinpad", fake_cancelar)

        cancel = client.post(
            f"/api/v1/punto-de-venta/ventas/{venta_data['id']}/cancelar",
            json={"motivo": "Cancelar cobro CLIP pendiente"},
            headers=auth_headers,
        )
        assert cancel.status_code == 200, cancel.text
        assert cancel.json()["estado"] == "cancelada"
        assert cancel.json()["pago_externo_estado"] == "cancelado"
        assert cancelados == ["clip-cancel-1"]

    def test_corte_con_diferencia_requiere_nota(self, client, auth_headers):
        pid = self._crear_producto(client, auth_headers, "CORTE-DIF", "30.00")
        self._agregar_stock(client, auth_headers, pid, 5)
        client.post("/api/v1/punto-de-venta/ventas", json={
            "metodo_pago": "01",
            "monto_recibido": "100.00",
            "detalles": [{"producto_id": pid, "cantidad": "1"}],
        }, headers=auth_headers)

        sin_nota = client.post("/api/v1/punto-de-venta/corte-caja", json={
            "fondo_inicial": "2000.00",
            "efectivo_real": "2020.00",
        }, headers=auth_headers)
        assert sin_nota.status_code == 400
        assert "nota" in sin_nota.json()["detail"].lower()

        con_nota = client.post("/api/v1/punto-de-venta/corte-caja", json={
            "fondo_inicial": "2000.00",
            "efectivo_real": "2020.00",
            "notas": "Faltante revisado en caja",
        }, headers=auth_headers)
        assert con_nota.status_code == 201, con_nota.text


def test_frontend_pagos_sprint6_surface():
    html = Path("docs/index.html").read_text(encoding="utf-8")

    assert 'id="mc-clip-tipo"' in html
    assert 'id="mc-sp-bbva"' in html
    assert 'id="mc-sp-clip-tipo"' in html
    assert "pagos.push({metodo_pago:clipTipo, terminal:'clip'" in html
    assert "pagos.push({metodo_pago:bbvaTipoSplit, terminal:'bbva'" in html
    assert "var labelMetodo = m.label || k" in html
    assert "d.label||d.metodo" in html
    assert "confirm(" not in html
    assert "alert(" not in html


class TestInventarioMovimientos:
    """Tests para movimientos de inventario."""

    def test_entrada_compra(self, client, auth_headers, db):
        from app.models.auditoria import LogAuditoria

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
        evento = db.query(LogAuditoria).filter(
            LogAuditoria.modulo == "inventario",
            LogAuditoria.accion == "entrada_compra",
        ).first()
        assert evento is not None

    def test_merma_producto(self, client, auth_headers, db):
        from app.models.auditoria import LogAuditoria

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
        evento = db.query(LogAuditoria).filter(
            LogAuditoria.modulo == "inventario",
            LogAuditoria.accion == "salida_merma",
        ).first()
        assert evento is not None

    def test_merma_no_permite_stock_negativo(self, client, auth_headers):
        resp = client.post("/api/v1/inventario/productos", json={
            "codigo": "MERMA-NEG",
            "nombre": "Pan merma negativa",
            "precio_unitario": "10.00",
            "tasa_iva": "0.00",
        }, headers=auth_headers)
        pid = resp.json()["id"]
        client.post("/api/v1/inventario/movimientos", json={
            "tipo": "entrada_ajuste",
            "producto_id": pid,
            "cantidad": "2",
        }, headers=auth_headers)
        resp = client.post(
            f"/api/v1/inventario/productos/{pid}/merma?cantidad=5&motivo=Caducado",
            headers=auth_headers,
        )
        assert resp.status_code == 400
        prod = client.get(f"/api/v1/inventario/productos/{pid}", headers=auth_headers).json()
        assert float(prod["stock_actual"]) == 2.0

    def test_ajuste_stock_rechaza_negativo_y_registra_movimiento(self, client, auth_headers, db):
        from app.models.auditoria import LogAuditoria

        resp = client.post("/api/v1/inventario/productos", json={
            "codigo": "AJUSTE-001",
            "nombre": "Pan ajuste",
            "precio_unitario": "10.00",
            "tasa_iva": "0.00",
        }, headers=auth_headers)
        pid = resp.json()["id"]

        negativo = client.post(
            f"/api/v1/inventario/productos/{pid}/ajuste-stock?cantidad=-1",
            headers=auth_headers,
        )
        assert negativo.status_code == 422

        ajuste = client.post(
            f"/api/v1/inventario/productos/{pid}/ajuste-stock?cantidad=5&motivo=Inicial",
            headers=auth_headers,
        )
        assert ajuste.status_code == 200
        movimientos = client.get(
            f"/api/v1/inventario/movimientos?producto_id={pid}",
            headers=auth_headers,
        ).json()
        assert movimientos[0]["tipo"] == "entrada_ajuste"
        evento = db.query(LogAuditoria).filter(
            LogAuditoria.modulo == "inventario",
            LogAuditoria.accion == "entrada_ajuste",
        ).first()
        assert evento is not None

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
