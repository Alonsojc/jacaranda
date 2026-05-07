"""Tests para ventas a cafeterías."""

from decimal import Decimal


def _crear_producto_cafeteria(client, auth_headers, codigo="CAF-001"):
    resp = client.post(
        "/api/v1/inventario/productos",
        json={
            "codigo": codigo,
            "nombre": "Brownie cafetería",
            "precio_unitario": "100.00",
            "precio_cafeteria": "80.00",
            "tasa_iva": "0.16",
            "stock_minimo": "0",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


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
    assert data["estado"] == "pendiente"
    assert data["detalles"][0]["precio_unitario"] == "80.00"

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


def test_cafeteria_pago_y_reportes(client, auth_headers):
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

    pago = client.post(
        f"/api/v1/cafeteria/ventas/{venta['id']}/pagos",
        json={"monto": "92.80", "metodo_pago": "04", "terminal": "clip"},
        headers=auth_headers,
    )
    assert pago.status_code == 200, pago.text
    data = pago.json()
    assert data["estado"] == "pagada"
    assert Decimal(data["saldo_pendiente"]) == Decimal("0.00")

    semanal = client.get("/api/v1/cafeteria/reportes/semanal", headers=auth_headers)
    assert semanal.status_code == 200, semanal.text
    rep = semanal.json()
    assert Decimal(str(rep["total_llevado"])) >= Decimal("92.80")
    assert "Café Semana" in [c["cafeteria"] for c in rep["por_cafeteria"]]
    assert "Brownie cafetería" in [p["nombre"] for p in rep["productos"]]


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
