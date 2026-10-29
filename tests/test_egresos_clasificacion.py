"""Classification and accounting checks with fictional expenses only."""

from datetime import date
from decimal import Decimal
from hashlib import sha256
from io import BytesIO
import json

from openpyxl import load_workbook
import pytest
from sqlalchemy.exc import IntegrityError

from app.api.routes.egresos import EgresoCreate
from app.models.auditoria import LogAuditoria
from app.models.egreso import Egreso
from app.services.venta_service import _hoy_operacion


def _body(concepto, monto, clasificacion=None):
    return {
        "concepto": concepto, "monto": str(monto), "categoria": "insumos",
        "metodo_pago": "tarjeta", "fecha": _hoy_operacion().isoformat(),
        "proveedor": "Proveedor de prueba", "clasificacion": clasificacion,
    }


def test_create_edit_filter_and_audit_classification(client, auth_headers, db):
    ids = {}
    for tipo, amount in [("costo", 100), ("gasto", 40), (None, 10)]:
        response = client.post("/api/v1/egresos/", headers=auth_headers,
                               json=_body("Egreso " + (tipo or "anterior"), amount, tipo))
        assert response.status_code == 201, response.text
        assert response.json()["clasificacion"] == tipo
        ids[tipo] = response.json()["id"]

    day = _hoy_operacion().isoformat()
    for tipo, amount in [("costo", 100), ("gasto", 40), ("sin_clasificar", 10)]:
        result = client.get("/api/v1/egresos/consulta", headers=auth_headers, params={
            "fecha_inicio": day, "fecha_fin": day, "clasificacion": tipo, "limit": 1,
        })
        assert result.status_code == 200, result.text
        assert result.json()["cantidad"] == 1
        assert Decimal(result.json()["total"]) == amount
    assert client.get("/api/v1/egresos/consulta", headers=auth_headers, params={
        "fecha_inicio": day, "fecha_fin": day, "clasificacion": "otro",
    }).status_code == 422

    edited = client.put(f"/api/v1/egresos/{ids[None]}", headers=auth_headers,
                        json={"clasificacion": "costo", "motivo": "Clasificacion revisada"})
    assert edited.status_code == 200, edited.text
    assert edited.json()["clasificacion"] == "costo"
    event = db.query(LogAuditoria).filter_by(entidad="egreso", entidad_id=ids[None], accion="actualizar").one()
    assert json.loads(event.datos_anteriores)["clasificacion"] is None
    assert json.loads(event.datos_nuevos)["clasificacion"] == "costo"
    costs = client.get("/api/v1/egresos/consulta", headers=auth_headers, params={
        "fecha_inicio": day, "fecha_fin": day, "clasificacion": "costo", "limit": 1,
    }).json()
    assert costs["cantidad"] == 2 and len(costs["items"]) == 1
    assert Decimal(costs["total"]) == 110
    cleared = client.put(f"/api/v1/egresos/{ids[None]}", headers=auth_headers,
                         json={"clasificacion": None, "motivo": "Revisar clasificacion"})
    assert cleared.status_code == 200 and cleared.json()["clasificacion"] is None
    invalid = client.post("/api/v1/egresos/", headers=auth_headers,
                          json=_body("Clasificacion invalida", 2, "inventado"))
    assert invalid.status_code == 422


def test_old_idempotency_fingerprint_remains_compatible(client, auth_headers, db):
    body = _body("Captura previa", 20)
    body.pop("clasificacion")
    body["idempotency_key"] = "egreso-legacy-001"
    old_values = EgresoCreate(**body).model_dump(mode="json", exclude={"idempotency_key", "clasificacion"})
    old_fingerprint = sha256(json.dumps(old_values, sort_keys=True, ensure_ascii=True,
                                      separators=(",", ":")).encode()).hexdigest()
    first = client.post("/api/v1/egresos/", headers=auth_headers, json=body)
    assert first.status_code == 201, first.text
    assert db.get(Egreso, first.json()["id"]).request_fingerprint == old_fingerprint
    retry = client.post("/api/v1/egresos/", headers=auth_headers, json=body)
    assert retry.status_code == 201 and retry.json()["id"] == first.json()["id"]
    changed = client.post("/api/v1/egresos/", headers=auth_headers, json={**body, "clasificacion": "costo"})
    assert changed.status_code == 409
    assert db.query(Egreso).count() == 1


def test_database_rejects_unknown_classification(db):
    db.add(Egreso(concepto="Invalido", monto=1, categoria="otro", metodo_pago="efectivo",
                  fecha=date.today(), clasificacion="desconocido"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_resultados_do_not_double_count_cost_purchases(client, auth_headers, db):
    product = client.post("/api/v1/inventario/productos", headers=auth_headers, json={
        "codigo": "CLAS-01", "nombre": "Producto ficticio", "precio_unitario": "100.00",
        "costo_produccion": "30.00", "tasa_iva": "0.00",
    })
    assert product.status_code == 201, product.text
    product_id = product.json()["id"]
    stock = client.post("/api/v1/inventario/movimientos", headers=auth_headers, json={
        "tipo": "entrada_ajuste", "producto_id": product_id, "cantidad": "2",
    })
    assert stock.status_code == 201, stock.text
    sale = client.post("/api/v1/punto-de-venta/ventas", headers=auth_headers, json={
        "metodo_pago": "01", "monto_recibido": "100.00",
        "detalles": [{"producto_id": product_id, "cantidad": "1"}],
    })
    assert sale.status_code == 201, sale.text
    for body in [_body("Compra materia prima", 120, "costo"),
                 _body("Servicio", 40, "gasto"), _body("Anterior", 10)]:
        result = client.post("/api/v1/egresos/", headers=auth_headers, json=body)
        assert result.status_code == 201, result.text
    day = _hoy_operacion().isoformat()
    params = {"fecha_inicio": day, "fecha_fin": day}
    result = client.get("/api/v1/contabilidad/estado-resultados", headers=auth_headers, params=params)
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["ingresos_netos"] == 100
    assert data["costo_ventas"] == 30
    assert data["total_gastos_operacion"] == 50
    assert data["utilidad_neta"] == 20
    assert data["composicion_gastos"]["costos_capturados"] == 120
    assert data["composicion_gastos"]["cantidad_costos"] == 1
    assert data["composicion_gastos"]["egresos_sin_clasificar"] == 10
    assert data["composicion_gastos"]["cantidad_sin_clasificar"] == 1
    assert data["egresos_por_proveedor"]["Proveedor de prueba"] == 50
    assert any("no se suman al costo de ventas" in note for note in data["calidad_datos"]["notas"])
    assert any("sin clasificar" in note for note in data["calidad_datos"]["notas"])

    exported = client.get("/api/v1/contabilidad/estado-resultados/excel", headers=auth_headers, params=params)
    assert exported.status_code == 200
    workbook = load_workbook(BytesIO(exported.content), data_only=True)
    review = list(workbook["Base y revisión"].values)
    assert ("Costos capturados (referencia)", 120) in review
    assert ("Sin clasificar incluidos en gastos", 10) in review
