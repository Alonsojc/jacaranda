"""Tests para ventas a cafeterías."""

from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.models.auditoria import LogAuditoria


def _crear_producto_cafeteria(client, auth_headers, codigo="CAF-001", **extra):
    payload = {
        "codigo": codigo,
        "nombre": "Brownie cafetería",
        "precio_unitario": "100.00",
        "precio_cafeteria": "80.00",
        "tasa_iva": "0.16",
        "stock_minimo": "0",
    }
    payload.update(extra)
    resp = client.post(
        "/api/v1/inventario/productos",
        json=payload,
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _crear_caja(client, auth_headers, nombre="Caja cafetería", stock=10):
    resp = client.post(
        "/api/v1/inventario/ingredientes",
        json={
            "nombre": nombre,
            "unidad_medida": "caja",
            "stock_minimo": "2",
            "costo_unitario": "4.00",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    caja_id = resp.json()["id"]
    mov = client.post(
        "/api/v1/inventario/movimientos",
        json={
            "tipo": "entrada_ajuste",
            "ingrediente_id": caja_id,
            "cantidad": str(stock),
            "referencia": "Stock inicial caja cafetería",
        },
        headers=auth_headers,
    )
    assert mov.status_code == 201, mov.text
    return caja_id


def test_cafeteria_usa_precio_especial_y_credito(client, auth_headers):
    producto = _crear_producto_cafeteria(client, auth_headers)

    resp = client.post(
        "/api/v1/cafeteria/ventas",
        json={
            "idempotency_key": "caf-test-001",
            "cafeteria_nombre": "Café Distrito",
            "contacto_nombre": "María",
            "telefono": "4421234567",
            "dias_credito": 7,
            "pago_inicial": "50.00",
            "metodo_pago": "03",
            "terminal": "bbva",
            "detalles": [{"producto_id": producto["id"], "cantidad": "2"}],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()

    assert data["cafeteria_nombre"] == "Café Distrito"
    assert Decimal(data["subtotal"]) == Decimal("160.00")
    assert Decimal(data["total_impuestos"]) == Decimal("25.60")
    assert Decimal(data["total"]) == Decimal("185.60")
    assert Decimal(data["monto_pagado"]) == Decimal("50.00")
    assert Decimal(data["saldo_pendiente"]) == Decimal("135.60")
    assert data["estado"] == "parcial"
    assert data["cafeteria_id"] is not None
    assert data["dias_credito"] == 7
    assert data["detalles"][0]["precio_unitario"] == "80.00"
    assert data["pagos"][0]["metodo_pago"] == "28"
    assert data["pagos"][0]["terminal"] == "bbva"

    duplicate = client.post(
        "/api/v1/cafeteria/ventas",
        json={
            "idempotency_key": "caf-test-001",
            "cafeteria_nombre": "Café Distrito",
            "detalles": [{"producto_id": producto["id"], "cantidad": "2"}],
        },
        headers=auth_headers,
    )
    assert duplicate.status_code == 201, duplicate.text
    assert duplicate.json()["id"] == data["id"]


def test_cafeteria_catalogo_autoguarda_y_reusa_cliente(client, auth_headers):
    producto = _crear_producto_cafeteria(client, auth_headers, codigo="CAF-CAT")

    creada = client.post(
        "/api/v1/cafeteria/clientes",
        json={
            "nombre": "Café Catálogo",
            "contacto_nombre": "Luisa",
            "telefono": "4420000000",
            "dias_credito": 14,
        },
        headers=auth_headers,
    )
    assert creada.status_code == 201, creada.text
    cliente_id = creada.json()["id"]

    venta = client.post(
        "/api/v1/cafeteria/ventas",
        json={
            "cafeteria_id": cliente_id,
            "cafeteria_nombre": "Café Catálogo",
            "detalles": [{"producto_id": producto["id"], "cantidad": "1"}],
            "dias_credito": 10,
        },
        headers=auth_headers,
    )
    assert venta.status_code == 201, venta.text
    assert venta.json()["cafeteria_id"] == cliente_id
    assert venta.json()["dias_credito"] == 10

    clientes = client.get("/api/v1/cafeteria/clientes", headers=auth_headers)
    assert clientes.status_code == 200, clientes.text
    assert any(c["id"] == cliente_id and c["dias_credito"] == 10 for c in clientes.json())


def test_cafeteria_rechaza_cantidad_fraccionaria(client, auth_headers):
    producto = _crear_producto_cafeteria(client, auth_headers, codigo="CAF-FRAC")
    resp = client.post(
        "/api/v1/cafeteria/ventas",
        json={
            "cafeteria_nombre": "Café Fracción",
            "detalles": [{"producto_id": producto["id"], "cantidad": "1.5"}],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422


def test_cafeteria_pago_y_reportes(client, auth_headers, db):
    producto = _crear_producto_cafeteria(client, auth_headers, codigo="CAF-002")
    venta = client.post(
        "/api/v1/cafeteria/ventas",
        json={
            "cafeteria_nombre": "Café Semana",
            "pago_inicial": "0",
            "detalles": [{"producto_id": producto["id"], "cantidad": "1"}],
        },
        headers=auth_headers,
    ).json()

    pago_parcial = client.post(
        f"/api/v1/cafeteria/ventas/{venta['id']}/pagos",
        json={
            "monto": "40.00",
            "metodo_pago": "04",
            "terminal": "clip",
            "motivo": "Abono semanal",
        },
        headers=auth_headers,
    )
    assert pago_parcial.status_code == 200, pago_parcial.text
    parcial = pago_parcial.json()
    assert parcial["estado"] == "parcial"
    assert Decimal(parcial["saldo_pendiente"]) == Decimal("52.80")

    pago = client.post(
        f"/api/v1/cafeteria/ventas/{venta['id']}/pagos",
        json={"monto": "52.80", "metodo_pago": "04", "terminal": "clip"},
        headers=auth_headers,
    )
    assert pago.status_code == 200, pago.text
    data = pago.json()
    assert data["estado"] == "pagada"
    assert Decimal(data["saldo_pendiente"]) == Decimal("0.00")

    eventos = (
        db.query(LogAuditoria)
        .filter(
            LogAuditoria.modulo == "cafeteria",
            LogAuditoria.accion == "pago",
            LogAuditoria.entidad_id == venta["id"],
        )
        .all()
    )
    assert len(eventos) == 2

    semanal = client.get("/api/v1/cafeteria/reportes/semanal", headers=auth_headers)
    assert semanal.status_code == 200, semanal.text
    rep = semanal.json()
    assert Decimal(str(rep["total_llevado"])) >= Decimal("92.80")
    assert Decimal(str(rep["total_pagado"])) >= Decimal("92.80")
    assert "corte_mensual" in rep
    assert "Café Semana" in [c["cafeteria"] for c in rep["por_cafeteria"]]
    assert "Brownie cafetería" in [p["nombre"] for p in rep["productos"]]


def test_cafeteria_corte_diario_no_incluye_cafeteria_y_mensual_si(client, auth_headers):
    producto = _crear_producto_cafeteria(client, auth_headers, codigo="CAF-CORTE")
    venta = client.post(
        "/api/v1/cafeteria/ventas",
        json={
            "cafeteria_nombre": "Café Corte",
            "pago_inicial": "20.00",
            "detalles": [{"producto_id": producto["id"], "cantidad": "1"}],
        },
        headers=auth_headers,
    )
    assert venta.status_code == 201, venta.text
    venta_data = venta.json()

    fecha_venta = datetime.fromisoformat(venta_data["fecha"].replace("Z", "+00:00"))
    if fecha_venta.tzinfo is None:
        fecha_venta = fecha_venta.replace(tzinfo=timezone.utc)
    fecha_operacion = fecha_venta.astimezone(ZoneInfo("America/Mexico_City")).date().isoformat()
    corte = client.get(
        f"/api/v1/punto-de-venta/corte-caja/resumen?fecha={fecha_operacion}",
        headers=auth_headers,
    )
    assert corte.status_code == 200, corte.text
    assert Decimal(str(corte.json()["total_ventas"])) == Decimal("0")
    assert corte.json()["numero_ventas"] == 0

    estado = client.get(
        "/api/v1/contabilidad/estado-resultados"
        f"?fecha_inicio={fecha_operacion}&fecha_fin={fecha_operacion}",
        headers=auth_headers,
    )
    assert estado.status_code == 200, estado.text
    data = estado.json()
    assert Decimal(str(data["ingresos_cafeteria"])) == Decimal("92.8")
    assert data["numero_entregas_cafeteria"] == 1
    assert data["cafeteria_b2b"]["separado_corte_diario_mostrador"] is True


def test_cafeteria_cancelar_devuelve_stock(client, auth_headers):
    producto = _crear_producto_cafeteria(client, auth_headers, codigo="CAF-003")
    venta = client.post(
        "/api/v1/cafeteria/ventas",
        json={
            "cafeteria_nombre": "Café Cancelar",
            "detalles": [{"producto_id": producto["id"], "cantidad": "1"}],
        },
        headers=auth_headers,
    )
    assert venta.status_code == 201, venta.text

    after_sale = client.get(f"/api/v1/inventario/productos/{producto['id']}", headers=auth_headers)
    assert Decimal(after_sale.json()["stock_actual"]) == Decimal("-1.0000")

    cancel = client.post(
        f"/api/v1/cafeteria/ventas/{venta.json()['id']}/cancelar",
            headers={**auth_headers, "X-Admin-Override-Motivo": "Prueba cancelacion"},
    )
    assert cancel.status_code == 200, cancel.text
    assert cancel.json()["estado"] == "cancelada"

    after_cancel = client.get(f"/api/v1/inventario/productos/{producto['id']}", headers=auth_headers)
    assert Decimal(after_cancel.json()["stock_actual"]) == Decimal("0.0000")


def test_cafeteria_descuenta_y_cancela_empaque(client, auth_headers):
    caja_id = _crear_caja(client, auth_headers)
    producto = _crear_producto_cafeteria(
        client,
        auth_headers,
        codigo="CAF-CAJA",
        caja_ingrediente_id=caja_id,
        caja_cantidad="1",
    )
    venta = client.post(
        "/api/v1/cafeteria/ventas",
        json={
            "cafeteria_nombre": "Café Empaque",
            "detalles": [{"producto_id": producto["id"], "cantidad": "2"}],
        },
        headers=auth_headers,
    )
    assert venta.status_code == 201, venta.text
    caja = client.get(f"/api/v1/inventario/ingredientes/{caja_id}", headers=auth_headers)
    assert Decimal(caja.json()["stock_actual"]) == Decimal("8.0000")

    cancel = client.post(
        f"/api/v1/cafeteria/ventas/{venta.json()['id']}/cancelar",
        headers={**auth_headers, "X-Admin-Override-Motivo": "Prueba empaque"},
    )
    assert cancel.status_code == 200, cancel.text
    caja = client.get(f"/api/v1/inventario/ingredientes/{caja_id}", headers=auth_headers)
    assert Decimal(caja.json()["stock_actual"]) == Decimal("10.0000")


def test_frontend_cafeteria_b2b_surface():
    html = open("docs/index.html", encoding="utf-8").read()
    assert "caf-k-llevado" in html
    assert "cargarCafeteriaClientes" in html
    assert "editarPrecioCafeRapido" in html
    assert "Pago parcial" in html
    assert "Liquidar" in html
    assert "#cafeteria .caf-account{position:static;bottom:auto;z-index:auto}" in html
    caf_slice = html.split("// ─── Cafetería POS", 1)[1].split("// ─── Pedidos", 1)[0]
    assert "alert(" not in caf_slice
    assert "confirm(" not in caf_slice
