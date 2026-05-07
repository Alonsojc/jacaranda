"""Tests for operational expense routes."""

from datetime import date


def test_crear_listar_reportar_y_desactivar_egreso(client, auth_headers):
    hoy = date.today().isoformat()

    resp = client.post(
        "/api/v1/egresos/",
        headers=auth_headers,
        json={
            "concepto": "Gas LP",
            "monto": "125.50",
            "categoria": "servicio",
            "metodo_pago": "transferencia",
            "fecha": hoy,
            "proveedor": "Proveedor prueba",
        },
    )
    assert resp.status_code == 201, resp.text
    egreso = resp.json()
    assert egreso["concepto"] == "Gas LP"
    assert egreso["activo"] is True

    listado = client.get("/api/v1/egresos/", headers=auth_headers)
    assert listado.status_code == 200
    assert any(item["id"] == egreso["id"] for item in listado.json())

    gastos = client.get(f"/api/v1/reportes/gastos-hoy?fecha={hoy}", headers=auth_headers)
    assert gastos.status_code == 200
    data = gastos.json()
    assert data["numero_egresos"] == 1
    assert data["numero_movimientos"] == 1
    assert data["total_gastos"] == 125.5
    assert data["desglose"][0]["concepto"] == "Gas LP"
    assert data["desglose"][0]["tipo"] == "egreso"

    deleted = client.delete(f"/api/v1/egresos/{egreso['id']}", headers=auth_headers)
    assert deleted.status_code == 200
    assert deleted.json()["ok"] is True

    listado = client.get("/api/v1/egresos/", headers=auth_headers)
    assert listado.status_code == 200
    assert all(item["id"] != egreso["id"] for item in listado.json())
