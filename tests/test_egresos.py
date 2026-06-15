"""Tests for operational expense routes."""

from datetime import date
from pathlib import Path
from unittest.mock import patch

from app.models.auditoria import LogAuditoria


PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00"


def test_crear_resumir_editar_y_anular_egreso(client, auth_headers, db):
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
    assert egreso["proveedor_id"] is not None

    proveedores = client.get("/api/v1/egresos/proveedores", headers=auth_headers)
    assert proveedores.status_code == 200
    assert any(p["nombre"] == "Proveedor prueba" for p in proveedores.json())

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

    actualizado = client.put(
        f"/api/v1/egresos/{egreso['id']}",
        headers=auth_headers,
        json={
            "concepto": "Gas LP ajustado",
            "monto": "130.75",
            "categoria": "servicio",
            "metodo_pago": "bbva",
            "fecha": hoy,
            "proveedor": "Proveedor prueba",
            "notas": "Factura corregida",
            "motivo": "Corrección de ticket",
        },
    )
    assert actualizado.status_code == 200, actualizado.text
    assert actualizado.json()["concepto"] == "Gas LP ajustado"
    assert float(actualizado.json()["monto"]) == 130.75

    deleted = client.post(
        f"/api/v1/egresos/{egreso['id']}/anular",
        headers=auth_headers,
        json={"motivo": "Captura duplicada"},
    )
    assert deleted.status_code == 200
    assert deleted.json()["ok"] is True

    listado = client.get("/api/v1/egresos/", headers=auth_headers)
    assert listado.status_code == 200
    assert all(item["id"] != egreso["id"] for item in listado.json())

    eventos = (
        db.query(LogAuditoria)
        .filter(LogAuditoria.modulo == "egresos", LogAuditoria.entidad == "egreso")
        .all()
    )
    acciones = {evento.accion for evento in eventos}
    assert {"crear", "actualizar", "anular"}.issubset(acciones)
    assert any("Captura duplicada" in (evento.datos_nuevos or "") for evento in eventos)


def test_resumen_recurrentes_y_ocr_sugerido(client, auth_headers):
    fijo = client.post(
        "/api/v1/egresos/gastos-fijos",
        headers=auth_headers,
        json={
            "concepto": "Renta local",
            "monto": "9000",
            "categoria": "renta",
            "metodo_pago": "transferencia",
            "proveedor": "Arrendador Centro",
            "periodicidad": "mensual",
            "dia_pago": 5,
        },
    )
    assert fijo.status_code == 201, fijo.text
    assert fijo.json()["proveedor_id"] is not None

    resumen = client.get("/api/v1/egresos/resumen", headers=auth_headers)
    assert resumen.status_code == 200
    data = resumen.json()
    assert data["recurrentes"]["cantidad"] == 1
    assert data["recurrentes"]["total_mensual"] == 9000
    assert data["recurrentes"]["gastos"][0]["concepto"] == "Renta local"

    ocr_payload = {
        "proveedor": "Papelería Centro",
        "fecha": date.today().isoformat(),
        "items": [
            {"nombre": "Bolsas kraft", "cantidad": 2, "unidad": "pz", "total": 80},
            {"nombre": "Etiquetas", "cantidad": 1, "unidad": "pz", "total": 45.5},
        ],
        "total": 125.5,
    }
    with patch("app.api.routes.egresos.extraer_datos_ticket", return_value=ocr_payload):
        ocr = client.post(
            "/api/v1/egresos/ocr-ticket",
            headers=auth_headers,
            files={"archivo": ("ticket.png", PNG_BYTES, "image/png")},
        )

    assert ocr.status_code == 200, ocr.text
    sugerido = ocr.json()["suggested_egreso"]
    assert sugerido["proveedor"] == "Papelería Centro"
    assert sugerido["monto"] == 125.5
    assert sugerido["categoria"] == "empaque"
    assert "Bolsas kraft" in sugerido["notas"]


def test_validaciones_egresos(client, auth_headers):
    invalido = client.post(
        "/api/v1/egresos/",
        headers=auth_headers,
        json={
            "concepto": "X",
            "monto": "0",
            "categoria": "no-existe",
            "metodo_pago": "trueque",
            "fecha": date.today().isoformat(),
        },
    )
    assert invalido.status_code == 422

    sin_motivo = client.post(
        "/api/v1/egresos/",
        headers=auth_headers,
        json={
            "concepto": "Flete",
            "monto": "50",
            "categoria": "flete",
            "metodo_pago": "efectivo",
            "proveedor": "Repartidor",
        },
    )
    assert sin_motivo.status_code == 201
    egreso_id = sin_motivo.json()["id"]

    edit = client.put(
        f"/api/v1/egresos/{egreso_id}",
        headers=auth_headers,
        json={"concepto": "Flete corregido"},
    )
    assert edit.status_code == 422

    anular = client.post(
        f"/api/v1/egresos/{egreso_id}/anular",
        headers=auth_headers,
        json={"motivo": "dup"},
    )
    assert anular.status_code == 422


def test_frontend_egresos_usa_modales_y_no_confirm_nativo():
    html = Path("docs/index.html").read_text()
    egresos_slice = html[html.index("<!-- EGRESOS -->"):html.index("<!-- LISTAS")]

    assert "modal-egreso-editar" in html
    assert "guardarEdicionEgreso" in html
    assert "anularEgreso" in html
    assert "escanearTicketEgreso" in html
    assert "confirm(" not in egresos_slice
    assert "alert(" not in egresos_slice
