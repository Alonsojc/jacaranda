"""Cash custody is a distribution after counting, not a deduction from sales."""

from decimal import Decimal

import pytest

from app.models.auditoria import LogAuditoria
from app.models.venta import CorteCaja


def _payload(**changes):
    payload = {
        "fondo_inicial": "2000.00",
        "efectivo_real": "5000.00",
        "retiros": "3000.00",
        "fondo_entregado": "2000.00",
        "recibido_por": "  Alonso  ",
        "notas": "Conteo de prueba con diferencia documentada",
    }
    payload.update(changes)
    return payload


def test_resguardo_persists_and_does_not_reduce_cash_count(client, auth_headers, db):
    product_response = client.post("/api/v1/inventario/productos", headers=auth_headers, json={
        "codigo": "RESGUARDO-1", "nombre": "Producto prueba", "precio_unitario": "3000.00",
        "tasa_iva": "0.00",
    })
    assert product_response.status_code == 201, product_response.text
    product = product_response.json()
    stock = client.post("/api/v1/inventario/movimientos", headers=auth_headers, json={
        "tipo": "entrada_ajuste", "producto_id": product["id"], "cantidad": "1",
    })
    assert stock.status_code == 201, stock.text
    sale = client.post("/api/v1/punto-de-venta/ventas", headers=auth_headers, json={
        "metodo_pago": "01", "monto_recibido": "3000.00",
        "detalles": [{"producto_id": product["id"], "cantidad": "1"}],
    })
    assert sale.status_code == 201, sale.text
    response = client.post("/api/v1/punto-de-venta/corte-caja", headers=auth_headers,
                           json=_payload(notas=None))
    assert response.status_code == 201, response.text
    cut = response.json()
    assert cut["efectivo_esperado"] == "5000.00"
    assert cut["efectivo_real"] == "5000.00"
    assert cut["total_ventas"] == "3000.00"
    assert cut["diferencia"] == "0.00"
    assert cut["retiros"] == "3000.00"
    assert cut["fondo_entregado"] == "2000.00"
    assert cut["recibido_por"] == "Alonso"
    stored = db.get(CorteCaja, cut["id"])
    assert stored.retiros == Decimal("3000.00")
    event = db.query(LogAuditoria).filter_by(entidad="corte_caja", entidad_id=cut["id"],
                                           accion="crear").one()
    assert "recibido_por" in event.datos_nuevos
    history = client.get("/api/v1/punto-de-venta/cortes-caja", headers=auth_headers).json()
    assert history[0]["recibido_por"] == "Alonso"
    summary = client.get("/api/v1/punto-de-venta/corte-caja/resumen", headers=auth_headers).json()
    assert summary["entrega_efectivo_disponible"] is True
    assert summary["corte"]["fondo_entregado"] == "2000.00"
    assert summary["total_ventas"] == "0"


@pytest.mark.parametrize("changes,status", [
    ({"fondo_entregado": "2500.00"}, 400),
    ({"recibido_por": "   "}, 400),
    ({"fondo_entregado": None}, 400),
    ({"retiros": "-1.00"}, 422),
    ({"fondo_entregado": "-1.00"}, 422),
    ({"recibido_por": "A" * 151}, 422),
    ({"retiros": "3000.001"}, 422),
])
def test_invalid_resguardo_does_not_create_cut(client, auth_headers, db, changes, status):
    response = client.post("/api/v1/punto-de-venta/corte-caja", headers=auth_headers,
                           json=_payload(**changes))
    assert response.status_code == status, response.text
    assert db.query(CorteCaja).count() == 0


def test_no_withdrawal_and_legacy_cuts_are_supported(client, auth_headers):
    response = client.post("/api/v1/punto-de-venta/corte-caja", headers=auth_headers,
                           json=_payload(efectivo_real="2000.00", retiros="0", recibido_por=None))
    assert response.status_code == 201, response.text
    assert response.json()["recibido_por"] is None
    legacy = client.post("/api/v1/punto-de-venta/corte-caja", headers=auth_headers, json={
        "fondo_inicial": "2000", "efectivo_real": "2000",
    })
    assert legacy.status_code == 201, legacy.text
    assert legacy.json()["fondo_entregado"] is None


def test_edit_resguardo_requires_admin_password_and_audits_changes(client, auth_headers, db):
    response = client.post("/api/v1/punto-de-venta/corte-caja", headers=auth_headers, json=_payload())
    assert response.status_code == 201, response.text
    cut_id = response.json()["id"]
    payload = _payload(retiros="2500", fondo_entregado="2500", recibido_por="Mariana",
                       motivo="Correccion de la entrega")
    url = f"/api/v1/punto-de-venta/cortes-caja/{cut_id}"
    assert client.put(url, headers=auth_headers, json=payload).status_code == 403
    headers = {**auth_headers, "X-Admin-Override-Password": "test1234",
               "X-Admin-Override-Motivo": "Correccion de entrega autorizada"}
    changed = client.put(url, headers=headers, json=payload)
    assert changed.status_code == 200, changed.text
    assert changed.json()["total_ventas"] == response.json()["total_ventas"]
    assert changed.json()["diferencia"] == response.json()["diferencia"]
    assert changed.json()["recibido_por"] == "Mariana"
    event = db.query(LogAuditoria).filter_by(entidad="corte_caja", entidad_id=cut_id,
                                           accion="actualizar").one()
    assert "Alonso" in event.datos_anteriores
    assert "Mariana" in event.datos_nuevos
    # An older client must not silently clear the new handover fields.
    old_client = client.put(url, headers=headers, json={
        "fondo_inicial": "2000", "efectivo_real": "5000",
        "notas": "Nota corregida", "motivo": "Correccion de notas solamente",
    })
    assert old_client.status_code == 200, old_client.text
    assert old_client.json()["fondo_entregado"] == "2500.00"
    assert old_client.json()["recibido_por"] == "Mariana"
    invalid = client.put(url, headers=headers, json={**payload, "fondo_entregado": "3000"})
    assert invalid.status_code == 400
    cleared = client.put(url, headers=headers, json={
        **payload, "fondo_entregado": None, "retiros": "0", "recibido_por": None,
    })
    assert cleared.status_code == 400
    assert db.get(CorteCaja, cut_id).fondo_entregado == Decimal("2500.00")


def test_pdf_includes_delivery_amounts_and_escapes_recipient(monkeypatch):
    from app.services import pdf_service

    rows = []
    original = pdf_service._tabla

    def capture(data, col_widths=None):
        rows.extend(data)
        return original(data, col_widths)

    monkeypatch.setattr(pdf_service, "_tabla", capture)
    pdf = pdf_service.generar_corte_caja_pdf({
        "retiros": Decimal("3000"), "fondo_entregado": Decimal("2000"),
        "recibido_por": "Alonso <custodia> & caja",
    })
    assert pdf.getvalue().startswith(b"%PDF")
    assert ["Retiro a resguardo", "$3,000.00"] in rows
    assert ["Fondo entregado al siguiente turno", "$2,000.00"] in rows
