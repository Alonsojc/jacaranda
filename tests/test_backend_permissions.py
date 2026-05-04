"""Regression tests for server-side module permissions."""

from decimal import Decimal

from app.core.security import get_password_hash
from app.models.inventario import Producto, TasaIVA, UnidadMedida
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


def _crear_producto(db, codigo: str = "PAN-001") -> Producto:
    producto = Producto(
        codigo=codigo,
        nombre="Concha",
        precio_unitario=Decimal("20.00"),
        costo_produccion=Decimal("8.00"),
        unidad_medida=UnidadMedida.PIEZA,
        stock_actual=Decimal("0"),
        stock_minimo=Decimal("0"),
        tasa_iva=TasaIVA.TASA_0,
    )
    db.add(producto)
    db.commit()
    db.refresh(producto)
    return producto


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


def test_sensitive_edit_allows_admin_without_override(client, db, admin_user):
    producto = _crear_producto(db)
    headers = _login(client, admin_user.email)

    resp = client.put(
        f"/api/v1/inventario/productos/{producto.id}",
        json={"precio_unitario": 22},
        headers=headers,
    )

    assert resp.status_code == 200, resp.text
    assert Decimal(str(resp.json()["precio_unitario"])) == Decimal("22")


def test_sensitive_edit_requires_admin_password_for_non_admin(client, db, admin_user):
    gerente = _crear_usuario(db, RolUsuario.GERENTE, "gerente-override@test.com")
    producto = _crear_producto(db)
    headers = _login(client, gerente.email)

    denied = client.put(
        f"/api/v1/inventario/productos/{producto.id}",
        json={"precio_unitario": 22},
        headers=headers,
    )
    assert denied.status_code == 403

    wrong = client.put(
        f"/api/v1/inventario/productos/{producto.id}",
        json={"precio_unitario": 22},
        headers={**headers, "X-Admin-Override-Password": "incorrecta"},
    )
    assert wrong.status_code == 403

    allowed = client.put(
        f"/api/v1/inventario/productos/{producto.id}",
        json={"precio_unitario": 22},
        headers={**headers, "X-Admin-Override-Password": "test1234"},
    )
    assert allowed.status_code == 200, allowed.text


def test_sensitive_delete_is_soft_delete_with_override(client, db, admin_user):
    gerente = _crear_usuario(db, RolUsuario.GERENTE, "gerente-delete@test.com")
    producto = _crear_producto(db, codigo="PAN-002")
    headers = {
        **_login(client, gerente.email),
        "X-Admin-Override-Password": "test1234",
    }

    resp = client.delete(f"/api/v1/inventario/productos/{producto.id}", headers=headers)

    assert resp.status_code == 200, resp.text
    db.refresh(producto)
    assert producto.activo is False
