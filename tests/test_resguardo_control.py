"""Physical cash opening, spending, retries and cut corrections use test data only."""

from datetime import timedelta
from decimal import Decimal

import pytest

from app.core.time_utils import operation_today
from app.models.auditoria import LogAuditoria
from app.models.egreso import Egreso
from app.models.resguardo import ResguardoControl
from app.models.usuario import RolUsuario


def _inicio(client, headers, saldo="0"):
    response = client.post("/api/v1/egresos/resguardo/iniciar", headers=headers,
                           json={"saldo_inicial": saldo})
    assert response.status_code == 200, response.text
    return response.json()


def _saldo(client, headers):
    response = client.get("/api/v1/egresos/resguardo", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _retiro(client, headers, monto="100"):
    response = client.post("/api/v1/punto-de-venta/corte-caja", headers=headers, json={
        "fondo_inicial": "2000", "efectivo_real": str(Decimal("2000") + Decimal(monto)),
        "retiros": monto, "fondo_entregado": "2000", "recibido_por": "Persona prueba",
        "notas": "Conteo de prueba, diferencia documentada",
    })
    assert response.status_code == 201, response.text
    return response.json()


def _egreso(client, headers, **changes):
    data = {"concepto": "Compra de empaques", "proveedor": "Proveedor de prueba",
            "monto": "40", "metodo_pago": "resguardo", "fecha": operation_today().isoformat(),
            "idempotency_key": "resguardo-egreso-001"}
    data.update(changes)
    return client.post("/api/v1/egresos/", headers=headers, json=data)


def test_opening_zero_excludes_history_and_is_not_resettable(client, auth_headers, db):
    old = _retiro(client, auth_headers, "502.50")
    assert _saldo(client, auth_headers)["saldo"] is None
    first = _inicio(client, auth_headers)
    assert first["saldo"] == first["entradas"] == 0
    assert first["movimientos"] == []
    assert db.get(ResguardoControl, 1).ultimo_corte_id == old["id"]
    new = _retiro(client, auth_headers, "85.75")
    assert _saldo(client, auth_headers)["saldo"] == 85.75
    assert _inicio(client, auth_headers)["saldo"] == 85.75
    assert db.query(LogAuditoria).filter_by(entidad="resguardo_control").count() == 1
    reset = client.post("/api/v1/egresos/resguardo/iniciar", headers=auth_headers,
                        json={"saldo_inicial": "400"})
    assert reset.status_code == 409
    assert _saldo(client, auth_headers)["movimientos"][0]["id"] == new["id"]


def test_spending_retry_edit_and_void_restore_exact_cash(client, auth_headers, db):
    _inicio(client, auth_headers)
    _retiro(client, auth_headers)
    one = _egreso(client, auth_headers)
    assert one.status_code == 201, one.text
    repeated = _egreso(client, auth_headers)
    assert repeated.status_code == 201 and repeated.json()["id"] == one.json()["id"]
    assert db.query(Egreso).count() == 1
    assert _saldo(client, auth_headers)["saldo"] == 60
    assert _egreso(client, auth_headers, monto="41").status_code == 409
    url = f"/api/v1/egresos/{one.json()['id']}"
    update = client.put(url, headers=auth_headers, json={"monto": "55.50", "motivo": "Corregir monto"})
    assert update.status_code == 200, update.text
    assert _saldo(client, auth_headers)["saldo"] == 44.5
    bad = client.put(url, headers=auth_headers, json={"monto": "100.01", "motivo": "Corregir monto"})
    assert bad.status_code == 400
    assert _saldo(client, auth_headers)["saldo"] == 44.5
    db.rollback()
    void = client.post(url + "/anular", headers=auth_headers, json={"motivo": "Compra cancelada"})
    assert void.status_code == 200, void.text
    assert _saldo(client, auth_headers)["saldo"] == 100
    assert _saldo(client, auth_headers)["salidas"] == 0
    assert len(_saldo(client, auth_headers)["movimientos"]) == 1


def test_other_method_does_not_spend_resguardo_and_switching_method_refunds(client, auth_headers):
    _inicio(client, auth_headers, "100")
    cash = _egreso(client, auth_headers, metodo_pago="efectivo")
    assert cash.status_code == 201
    assert _saldo(client, auth_headers)["saldo"] == 100
    url = f"/api/v1/egresos/{cash.json()['id']}"
    changed = client.put(url, headers=auth_headers, json={"metodo_pago": "resguardo", "motivo": "Metodo corregido"})
    assert changed.status_code == 200, changed.text
    assert _saldo(client, auth_headers)["saldo"] == 60
    assert client.put(url, headers=auth_headers, json={"metodo_pago": "bbva", "motivo": "Metodo corregido"}).status_code == 200
    assert _saldo(client, auth_headers)["saldo"] == 100


def test_zero_and_uninitialized_balances_reject_expenses_without_side_effects(client, auth_headers, db):
    assert _egreso(client, auth_headers).status_code == 400
    db.rollback()
    _inicio(client, auth_headers)
    assert _egreso(client, auth_headers).status_code == 400
    assert db.query(Egreso).count() == 0


@pytest.mark.parametrize("changes,status", [
    ({"idempotency_key": None}, 422), ({"fecha": None}, 422),
    ({"monto": "1.001"}, 422), ({"monto": "NaN"}, 422),
    ({"fecha": (operation_today() + timedelta(days=1)).isoformat()}, 400),
    ({"fecha": (operation_today() - timedelta(days=1)).isoformat()}, 400),
])
def test_invalid_spending_dates_and_amounts(client, auth_headers, changes, status):
    _inicio(client, auth_headers, "100")
    assert _egreso(client, auth_headers, **changes).status_code == status
    assert _saldo(client, auth_headers)["saldo"] == 100


def test_old_expense_cannot_be_reclassified_as_new_cash_spending(client, auth_headers, db):
    old = _egreso(client, auth_headers, metodo_pago="efectivo")
    assert old.status_code == 201
    _inicio(client, auth_headers, "100")
    response = client.put(f"/api/v1/egresos/{old.json()['id']}", headers=auth_headers,
                          json={"metodo_pago": "resguardo", "motivo": "Cambio de metodo"})
    assert response.status_code == 400
    db.rollback()
    assert _saldo(client, auth_headers)["saldo"] == 100


@pytest.mark.parametrize("accion", ["cancelar", "reabrir", "editar"])
def test_spent_cut_cannot_be_removed_but_can_be_corrected_after_refund(client, auth_headers, db, accion):
    _inicio(client, auth_headers)
    cut = _retiro(client, auth_headers)
    spent = _egreso(client, auth_headers)
    assert spent.status_code == 201
    headers = {**auth_headers, "X-Admin-Override-Password": "test1234",
               "X-Admin-Override-Motivo": "Correccion autorizada de prueba"}
    url = f"/api/v1/punto-de-venta/cortes-caja/{cut['id']}"
    data = {"motivo": "Correccion autorizada de prueba"}
    if accion == "editar":
        data.update(fondo_inicial="2000", efectivo_real="2000", retiros="0",
                    fondo_entregado="2000", recibido_por=None)
        request = lambda: client.put(url, headers=headers, json=data)
    else:
        request = lambda: client.post(url + "/" + accion, headers=headers, json=data)
    assert request().status_code == 400
    db.rollback()
    assert _saldo(client, auth_headers)["saldo"] == 60
    assert client.post(f"/api/v1/egresos/{spent.json()['id']}/anular", headers=auth_headers,
                       json={"motivo": "Revertir gasto de prueba"}).status_code == 200
    assert request().status_code == 200
    assert _saldo(client, auth_headers)["saldo"] == 0


def test_balance_is_not_limited_to_twenty_movements(client, auth_headers, db):
    _inicio(client, auth_headers, "100")
    for n in range(25):
        db.add(Egreso(concepto=f"Gasto prueba {n}", proveedor="Prueba", monto="1",
                      metodo_pago="resguardo", fecha=operation_today()))
    db.commit()
    data = _saldo(client, auth_headers)
    assert data["saldo"] == 75 and data["salidas"] == 25
    assert len(data["movimientos"]) == 20


@pytest.mark.parametrize("permiso,lectura", [("oculto", 403), ("ver", 200), ("editar", 200)])
def test_cash_opening_requires_approval_and_summary_requires_permission(
    client, auth_headers, admin_user, db, permiso, lectura,
):
    admin_user.rol = RolUsuario.CAJERO
    admin_user.permisos_modulos = {"egresos": permiso}
    db.commit()
    assert client.get("/api/v1/egresos/resguardo", headers=auth_headers).status_code == lectura
    denied = client.post("/api/v1/egresos/resguardo/iniciar", headers=auth_headers,
                         json={"saldo_inicial": "0"})
    assert denied.status_code == 403
    assert db.get(ResguardoControl, 1) is None
