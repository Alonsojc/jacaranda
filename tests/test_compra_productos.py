"""Tests de compra operativa de productos terminados."""

import json
from decimal import Decimal

from app.models.auditoria import LogAuditoria
from app.models.inventario import MovimientoInventario, TipoMovimiento


def _crear_producto(client, auth_headers, codigo: str, nombre: str) -> dict:
    response = client.post(
        "/api/v1/inventario/productos",
        json={
            "codigo": codigo,
            "nombre": nombre,
            "precio_unitario": "100.00",
            "costo_produccion": "35.00",
            "stock_minimo": "2",
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_compra_masiva_requiere_autenticacion(client):
    response = client.post(
        "/api/v1/inventario/productos/compra-masiva",
        json={"items": [{"producto_id": 1, "cantidad": 1}]},
    )

    assert response.status_code == 401


def test_compra_masiva_suma_productos_y_deja_auditoria(
    client, auth_headers, db
):
    brownie = _crear_producto(client, auth_headers, "COMP-001", "Brownie")
    galleta = _crear_producto(client, auth_headers, "COMP-002", "Galleta")

    response = client.post(
        "/api/v1/inventario/productos/compra-masiva",
        json={
            "items": [
                {"producto_id": brownie["id"], "cantidad": 6},
                {"producto_id": galleta["id"], "cantidad": 12},
            ],
            "referencia": "Proveedor semanal 184",
            "notas": "Recepción completa",
        },
        headers=auth_headers,
    )

    assert response.status_code == 201, response.text
    data = response.json()
    assert data["total_productos"] == 2
    assert data["total_piezas"] == 18

    brownie_actual = client.get(
        f"/api/v1/inventario/productos/{brownie['id']}",
        headers=auth_headers,
    ).json()
    galleta_actual = client.get(
        f"/api/v1/inventario/productos/{galleta['id']}",
        headers=auth_headers,
    ).json()
    assert Decimal(brownie_actual["stock_actual"]) == Decimal("6.0000")
    assert Decimal(galleta_actual["stock_actual"]) == Decimal("12.0000")

    movimientos = (
        db.query(MovimientoInventario)
        .filter(
            MovimientoInventario.producto_id.in_([brownie["id"], galleta["id"]]),
            MovimientoInventario.tipo == TipoMovimiento.ENTRADA_COMPRA,
        )
        .all()
    )
    assert len(movimientos) == 2
    assert {movimiento.referencia for movimiento in movimientos} == {
        "Proveedor semanal 184"
    }

    auditoria = (
        db.query(LogAuditoria)
        .filter(
            LogAuditoria.modulo == "inventario",
            LogAuditoria.accion == "registrar_compra_productos",
        )
        .one()
    )
    nuevos = json.loads(auditoria.datos_nuevos)
    assert nuevos["total_productos"] == 2
    assert nuevos["total_piezas"] == 18
    assert auditoria.usuario_nombre == "Admin Test"


def test_compra_masiva_rechaza_fracciones(client, auth_headers):
    producto = _crear_producto(client, auth_headers, "COMP-FRAC", "Panqué")

    response = client.post(
        "/api/v1/inventario/productos/compra-masiva",
        json={"items": [{"producto_id": producto["id"], "cantidad": "1.5"}]},
        headers=auth_headers,
    )

    assert response.status_code == 422
    assert "entero" in response.text.lower()


def test_compra_masiva_no_aplica_parcialmente_si_falta_producto(
    client, auth_headers
):
    producto = _crear_producto(client, auth_headers, "COMP-ROLL", "Apple Crumble")

    response = client.post(
        "/api/v1/inventario/productos/compra-masiva",
        json={
            "items": [
                {"producto_id": producto["id"], "cantidad": 4},
                {"producto_id": 999999, "cantidad": 3},
            ]
        },
        headers=auth_headers,
    )

    assert response.status_code == 400
    actual = client.get(
        f"/api/v1/inventario/productos/{producto['id']}",
        headers=auth_headers,
    )
    assert Decimal(actual.json()["stock_actual"]) == Decimal("0.0000")


def test_compra_masiva_rechaza_producto_duplicado(client, auth_headers):
    producto = _crear_producto(client, auth_headers, "COMP-DUP", "Lemon Pie")

    response = client.post(
        "/api/v1/inventario/productos/compra-masiva",
        json={
            "items": [
                {"producto_id": producto["id"], "cantidad": 2},
                {"producto_id": producto["id"], "cantidad": 3},
            ]
        },
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert "una sola vez" in response.json()["detail"]
