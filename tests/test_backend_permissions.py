"""Regression tests for server-side module permissions."""

from app.core.security import get_password_hash
from app.models.usuario import RolUsuario, Usuario


def _login(client, email: str, password: str = "test1234") -> dict:
    from app.api.routes.auth import _login_attempts
    from app.core.rate_limit import _requests

    _login_attempts.clear()
    _requests.clear()
    resp = client.post("/api/v1/auth/login", json={
        "email": email,
        "password": password,
    })
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _crear_usuario(db, rol: RolUsuario, email: str) -> Usuario:
    user = Usuario(
        nombre=f"Usuario {rol.value}",
        email=email,
        hashed_password=get_password_hash("test1234"),
        rol=rol,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_operational_history_requires_auth(client):
    assert client.get("/api/v1/punto-de-venta/ventas").status_code == 401
    assert client.get("/api/v1/inventario/movimientos").status_code == 401


def test_cashier_can_use_pos_but_not_inventory_or_fiscal_reports(client, db):
    _crear_usuario(db, RolUsuario.CAJERO, "cajero-permisos@test.com")
    headers = _login(client, "cajero-permisos@test.com")

    resp_pos = client.get("/api/v1/punto-de-venta/ventas", headers=headers)
    assert resp_pos.status_code == 200

    resp_inventory = client.get("/api/v1/inventario/movimientos", headers=headers)
    assert resp_inventory.status_code == 403

    resp_fiscal = client.get(
        "/api/v1/reportes/impuestos/iva-mensual?mes=1&anio=2026",
        headers=headers,
    )
    assert resp_fiscal.status_code == 403
