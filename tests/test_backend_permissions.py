"""Regression tests for server-side module permissions."""

from decimal import Decimal

from app.core.security import get_password_hash
from app.models.auditoria import LogAuditoria
from app.models.gasto_fijo import GastoFijo
from app.models.inventario import Ingrediente, Producto, TasaIVA, UnidadMedida
from app.models.receta import Receta
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


def _crear_gasto(db) -> GastoFijo:
    gasto = GastoFijo(
        concepto="Renta",
        monto=Decimal("12000.00"),
        periodicidad="mensual",
        activo=True,
    )
    db.add(gasto)
    db.commit()
    db.refresh(gasto)
    return gasto


def _crear_ingrediente(db, nombre: str = "Harina") -> Ingrediente:
    ingrediente = Ingrediente(
        nombre=nombre,
        unidad_medida=UnidadMedida.KILOGRAMO,
        stock_actual=Decimal("0"),
        stock_minimo=Decimal("0"),
        costo_unitario=Decimal("12.00"),
    )
    db.add(ingrediente)
    db.commit()
    db.refresh(ingrediente)
    return ingrediente


def _crear_receta(db, producto: Producto) -> Receta:
    receta = Receta(
        producto_id=producto.id,
        nombre=f"Receta {producto.codigo}",
        descripcion=None,
        instrucciones="Mezclar y hornear",
        rendimiento=Decimal("12"),
        tiempo_preparacion_min=20,
        tiempo_horneado_min=15,
        temperatura_horneado_c=180,
    )
    db.add(receta)
    db.commit()
    db.refresh(receta)
    return receta


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


def test_legacy_admin_permissions_get_new_modules_backfilled(client, db):
    admin = _crear_usuario(db, RolUsuario.ADMINISTRADOR, "admin-legacy-perms@test.com")
    admin.permisos_modulos = {
        "dash": "editar",
        "rep": "editar",
        "listas": "editar",
    }
    db.commit()
    db.refresh(admin)

    headers = _login(client, admin.email)
    me = client.get("/api/v1/auth/me", headers=headers)

    assert me.status_code == 200
    permisos = me.json()["permisos_modulos"]
    assert permisos["papelera"] == "editar"
    assert permisos["usuarios"] == "editar"
    assert permisos["dash"] == "editar"


def test_explicit_hidden_permission_is_preserved(client, db):
    gerente = _crear_usuario(db, RolUsuario.GERENTE, "gerente-hidden-perms@test.com")
    gerente.permisos_modulos = {
        "dash": "editar",
        "papelera": "oculto",
    }
    db.commit()
    db.refresh(gerente)

    headers = _login(client, gerente.email)
    me = client.get("/api/v1/auth/me", headers=headers)

    assert me.status_code == 200
    permisos = me.json()["permisos_modulos"]
    assert permisos["papelera"] == "oculto"
    assert permisos["compras"] == "editar"


def test_disabled_module_blocks_even_admin(client, admin_user, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "DISABLED_MODULES", "compras")
    headers = _login(client, admin_user.email)

    resp = client.get("/api/v1/compras/proveedores", headers=headers)

    assert resp.status_code == 403
    assert "desactivado" in resp.json()["detail"]


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

    sin_motivo = client.put(
        f"/api/v1/inventario/productos/{producto.id}",
        json={"precio_unitario": 22},
        headers={**headers, "X-Admin-Override-Password": "test1234"},
    )
    assert sin_motivo.status_code == 400

    allowed = client.put(
        f"/api/v1/inventario/productos/{producto.id}",
        json={"precio_unitario": 22},
        headers={
            **headers,
            "X-Admin-Override-Password": "test1234",
            "X-Admin-Override-Motivo": "Correcci%C3%B3n de prueba",
        },
    )
    assert allowed.status_code == 200, allowed.text


def test_sensitive_delete_is_soft_delete_with_override(client, db, admin_user):
    gerente = _crear_usuario(db, RolUsuario.GERENTE, "gerente-delete@test.com")
    producto = _crear_producto(db, codigo="PAN-002")
    headers = {
        **_login(client, gerente.email),
        "X-Admin-Override-Password": "test1234",
        "X-Admin-Override-Motivo": "Producto duplicado",
    }

    resp = client.delete(f"/api/v1/inventario/productos/{producto.id}", headers=headers)

    assert resp.status_code == 200, resp.text
    db.refresh(producto)
    assert producto.activo is False


def test_trash_lists_and_reactivates_soft_deleted_product(client, db, admin_user):
    gerente = _crear_usuario(db, RolUsuario.GERENTE, "gerente-trash@test.com")
    producto = _crear_producto(db, codigo="PAN-003")
    producto.activo = False
    db.commit()

    headers = _login(client, gerente.email)
    listado = client.get("/api/v1/inventario/productos/inactivos", headers=headers)
    assert listado.status_code == 200, listado.text
    assert any(item["id"] == producto.id for item in listado.json())

    denied = client.post(f"/api/v1/inventario/productos/{producto.id}/reactivar", headers=headers)
    assert denied.status_code == 403

    allowed = client.post(
        f"/api/v1/inventario/productos/{producto.id}/reactivar",
        headers={
            **headers,
            "X-Admin-Override-Password": "test1234",
            "X-Admin-Override-Motivo": "Reactivacion de prueba",
        },
    )
    assert allowed.status_code == 200, allowed.text
    db.refresh(producto)
    assert producto.activo is True
    evento = db.query(LogAuditoria).filter(
        LogAuditoria.modulo == "papelera",
        LogAuditoria.entidad == "producto",
        LogAuditoria.entidad_id == producto.id,
        LogAuditoria.accion == "actualizar",
    ).first()
    assert evento is not None
    assert '"activo": false' in evento.datos_anteriores
    assert '"accion": "reactivar producto"' in evento.datos_nuevos


def test_trash_lists_and_reactivates_soft_deleted_ingredient(client, db, admin_user):
    gerente = _crear_usuario(db, RolUsuario.GERENTE, "gerente-ing-trash@test.com")
    ingrediente = _crear_ingrediente(db)
    ingrediente.activo = False
    db.commit()

    headers = _login(client, gerente.email)
    listado = client.get("/api/v1/inventario/ingredientes/inactivos", headers=headers)
    assert listado.status_code == 200, listado.text
    assert any(item["id"] == ingrediente.id for item in listado.json())

    allowed = client.post(
        f"/api/v1/inventario/ingredientes/{ingrediente.id}/reactivar",
        headers={
            **headers,
            "X-Admin-Override-Password": "test1234",
            "X-Admin-Override-Motivo": "Reactivacion de prueba",
        },
    )
    assert allowed.status_code == 200, allowed.text
    db.refresh(ingrediente)
    assert ingrediente.activo is True


def test_trash_lists_and_reactivates_soft_deleted_recipe(client, db, admin_user):
    gerente = _crear_usuario(db, RolUsuario.GERENTE, "gerente-rec-trash@test.com")
    producto = _crear_producto(db, codigo="PAN-004")
    receta = _crear_receta(db, producto)
    receta.activo = False
    db.commit()

    headers = _login(client, gerente.email)
    listado = client.get("/api/v1/recetas/inactivas", headers=headers)
    assert listado.status_code == 200, listado.text
    assert any(item["id"] == receta.id for item in listado.json())

    allowed = client.post(
        f"/api/v1/recetas/{receta.id}/reactivar",
        headers={
            **headers,
            "X-Admin-Override-Password": "test1234",
            "X-Admin-Override-Motivo": "Reactivacion de prueba",
        },
    )
    assert allowed.status_code == 200, allowed.text
    db.refresh(receta)
    assert receta.activo is True


def test_trash_lists_and_reactivates_fixed_expense(client, db, admin_user):
    gerente = _crear_usuario(db, RolUsuario.GERENTE, "gerente-gasto-trash@test.com")
    gasto = _crear_gasto(db)
    gasto.activo = False
    db.commit()

    headers = _login(client, gerente.email)
    listado = client.get("/api/v1/punto-de-venta/gastos-fijos/inactivos", headers=headers)
    assert listado.status_code == 200, listado.text
    assert any(item["id"] == gasto.id for item in listado.json())

    allowed = client.post(
        f"/api/v1/punto-de-venta/gastos-fijos/{gasto.id}/reactivar",
        headers={
            **headers,
            "X-Admin-Override-Password": "test1234",
            "X-Admin-Override-Motivo": "Reactivacion de prueba",
        },
    )
    assert allowed.status_code == 200, allowed.text
    db.refresh(gasto)
    assert gasto.activo is True
