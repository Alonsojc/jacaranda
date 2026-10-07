"""Approval keys and user roles use only fictional in-memory accounts."""

import json

import pytest
from fastapi import HTTPException

from app.core.dependencies import require_admin_or_override
from app.core.rate_limit import _requests, AUTH_RATE_LIMIT
from app.core.security import create_access_token, get_password_hash, verify_password
from app.models.auditoria import ConfiguracionSeguridad, LogAuditoria
from app.models.usuario import Usuario, RolUsuario
from app.services.auth_service import bloquear_gestion_usuarios
from app.services.autorizacion_service import CLAVE_CONFIG

TEST_KEY = "approval-test-only"


def user(db, rol=RolUsuario.CAJERO, nombre="Cajero prueba", email="cashier@test.invalid"):
    usuario = Usuario(nombre=nombre, email=email, rol=rol, hashed_password=get_password_hash("login-test-only"))
    db.add(usuario)
    db.commit()
    db.refresh(usuario)
    return usuario


def headers(usuario):
    return {"Authorization": "Bearer " + create_access_token({"sub": usuario.id, "rol": usuario.rol.value})}


def key_body(**changes):
    return {"password_actual": "test1234", "nueva_clave": TEST_KEY, "confirmacion": TEST_KEY, **changes}


@pytest.fixture
def configured_key(client, auth_headers):
    response = client.put("/api/v1/auth/clave-autorizacion", headers=auth_headers, json=key_body())
    assert response.status_code == 200, response.text
    return TEST_KEY


def test_key_status_never_returns_key_or_hash(client, auth_headers, configured_key, db):
    response = client.get("/api/v1/auth/clave-autorizacion", headers=auth_headers)
    assert response.json() == {"configurada": True}
    config = db.query(ConfiguracionSeguridad).filter_by(clave=CLAVE_CONFIG).one()
    assert config.valor != TEST_KEY
    assert verify_password(TEST_KEY, config.valor)
    event = db.query(LogAuditoria).filter_by(entidad="clave_autorizacion", accion="crear").one()
    assert event.usuario_nombre == "Admin Test"
    assert TEST_KEY not in (event.datos_nuevos + event.datos_anteriores)
    assert config.valor not in (event.datos_nuevos + event.datos_anteriores)
    users = client.get("/api/v1/auth/usuarios", headers=auth_headers).text
    assert TEST_KEY not in users and config.valor not in users


def test_key_does_not_change_login_password(client, auth_headers, configured_key):
    good = client.post("/api/v1/auth/login", json={"email": "admin@test.com", "password": "test1234"})
    assert good.status_code == 200
    wrong = client.post("/api/v1/auth/login", json={"email": "admin@test.com", "password": configured_key})
    assert wrong.status_code == 401


def test_unconfigured_key_preserves_existing_approvals(client, auth_headers, admin_user, db):
    assert client.get("/api/v1/auth/clave-autorizacion", headers=auth_headers).json() == {"configurada": False}
    checker = require_admin_or_override("corte", "editar corte", require_password=True)
    assert checker(admin_user, db, "test1234", "Correccion de prueba") is admin_user


@pytest.mark.parametrize("attempt", [None, "incorrecta", "test1234", "x" * 73])
def test_configured_key_rejects_admin_login_password_even_for_admin(client, configured_key, admin_user, db, attempt):
    checker = require_admin_or_override("pos", "editar ticket", require_password=True)
    with pytest.raises(HTTPException) as err:
        checker(admin_user, db, attempt, "Correccion de prueba")
    assert err.value.status_code == 403
    assert "Clave" in err.value.detail
    event = db.query(LogAuditoria).filter_by(accion="autorizar_fallida").one()
    assert json.loads(event.datos_nuevos) == {"accion": "editar ticket", "metodo": "clave_autorizacion"}


def test_shared_key_audit_records_actual_user_not_an_invented_admin(client, configured_key, db):
    cashier = user(db)
    checker = require_admin_or_override("pos", "editar ticket", require_password=True)
    assert checker(cashier, db, configured_key, "Correccion%20autorizada") is cashier
    event = db.query(LogAuditoria).filter_by(accion="autorizar").one()
    assert event.usuario_id == cashier.id
    assert event.motivo == "Correccion autorizada"
    assert json.loads(event.datos_nuevos) == {
        "accion": "editar ticket", "metodo": "clave_autorizacion", "motivo": "Correccion autorizada",
    }


def test_key_still_requires_motive(client, configured_key, admin_user, db):
    checker = require_admin_or_override("corte", "cancelar corte", require_password=True)
    with pytest.raises(HTTPException) as err:
        checker(admin_user, db, configured_key, "   ")
    assert err.value.status_code == 400
    assert db.query(LogAuditoria).filter_by(accion="autorizar").count() == 0


def test_invalid_stored_hash_fails_closed_without_admin_fallback(client, configured_key, admin_user, db):
    config = db.query(ConfiguracionSeguridad).filter_by(clave=CLAVE_CONFIG).one()
    config.valor = "$2b$invalid-hash"
    db.commit()
    with pytest.raises(HTTPException) as err:
        require_admin_or_override("pos", "editar ticket", require_password=True)(admin_user, db, "test1234", "Prueba")
    assert err.value.status_code == 403


def test_key_does_not_grant_module_permissions_or_user_management(client, configured_key, db):
    consulta = user(db, RolUsuario.CONSULTA)
    credential_headers = {**headers(consulta), "X-Admin-Override-Password": configured_key,
                          "X-Admin-Override-Motivo": "Prueba"}
    assert client.patch("/api/v1/punto-de-venta/ventas/999", headers=credential_headers, json={
        "modo": "productos", "revision": 0, "motivo": "Prueba", "detalles": [{"id": 1, "producto_id": 2}],
    }).status_code == 403
    assert client.put(f"/api/v1/auth/usuarios/{consulta.id}", headers=credential_headers,
                      json={"rol": "administrador"}).status_code == 403
    assert client.put("/api/v1/auth/clave-autorizacion", headers=credential_headers, json=key_body()).status_code == 403
    assert client.get("/api/v1/auth/clave-autorizacion", headers=credential_headers).json() == {"configurada": True}


@pytest.mark.parametrize("change", [
    {"password_actual": "incorrecta"},
    {"nueva_clave": "short", "confirmacion": "short"},
    {"nueva_clave": "test1234", "confirmacion": "test1234"},
    {"confirmacion": "does-not-match"},
    {"nueva_clave": "x" * 73, "confirmacion": "x" * 73},
    {"nueva_clave": "\u00e1" * 37, "confirmacion": "\u00e1" * 37},
])
def test_invalid_setup_never_replaces_key_or_returns_secrets(client, auth_headers, configured_key, db, change):
    original = db.query(ConfiguracionSeguridad).filter_by(clave=CLAVE_CONFIG).one().valor
    response = client.put("/api/v1/auth/clave-autorizacion", headers=auth_headers, json=key_body(**change))
    assert response.status_code in (400, 403)
    assert TEST_KEY not in response.text
    db.expire_all()
    assert db.query(ConfiguracionSeguridad).filter_by(clave=CLAVE_CONFIG).one().valor == original


def test_rotation_invalidates_previous_key(client, auth_headers, configured_key, db, admin_user):
    response = client.put("/api/v1/auth/clave-autorizacion", headers=auth_headers,
                          json=key_body(nueva_clave="second-test-key", confirmacion="second-test-key"))
    assert response.status_code == 200
    checker = require_admin_or_override("corte", "reabrir corte", require_password=True)
    with pytest.raises(HTTPException):
        checker(admin_user, db, TEST_KEY, "Prueba de rotacion")
    assert checker(admin_user, db, "second-test-key", "Prueba de rotacion") is admin_user


def test_approval_attempts_are_limited_across_actions(client, configured_key, db, admin_user):
    _requests.clear()
    for _ in range(AUTH_RATE_LIMIT):
        with pytest.raises(HTTPException) as err:
            require_admin_or_override("pos", "editar ticket", require_password=True)(admin_user, db, "wrong", "Prueba")
        assert err.value.status_code == 403
    with pytest.raises(HTTPException) as err:
        require_admin_or_override("corte", "reabrir corte", require_password=True)(admin_user, db, TEST_KEY, "Prueba")
    assert err.value.status_code == 429
    assert err.value.headers["Retry-After"] == "60"


def test_setup_requires_login_and_current_admin_password(client, auth_headers):
    assert client.get("/api/v1/auth/clave-autorizacion").status_code == 401
    assert client.put("/api/v1/auth/clave-autorizacion", json=key_body()).status_code == 401
    wrong = client.put("/api/v1/auth/clave-autorizacion", headers=auth_headers,
                       json=key_body(password_actual="wrong"))
    assert wrong.status_code == 403
    assert client.get("/api/v1/auth/clave-autorizacion", headers=auth_headers).json() == {"configurada": False}


@pytest.mark.parametrize("body", [
    {"password_actual": "test1234", "nueva_clave": TEST_KEY},
    {"password_actual": "test1234", "nueva_clave": [TEST_KEY], "confirmacion": TEST_KEY},
    '{"password_actual":"test1234","nueva_clave":"' + TEST_KEY + '",',
])
def test_malformed_key_setup_redacts_validation_errors(client, auth_headers, body, caplog):
    if isinstance(body, str):
        response = client.put("/api/v1/auth/clave-autorizacion", content=body,
                              headers={**auth_headers, "Content-Type": "application/json"})
    else:
        response = client.put("/api/v1/auth/clave-autorizacion", headers=auth_headers, json=body)
    assert response.status_code == 422
    assert TEST_KEY not in response.text and "test1234" not in response.text
    assert TEST_KEY not in caplog.text
    assert client.get("/api/v1/auth/clave-autorizacion", headers=auth_headers).json() == {"configurada": False}


def test_cash_cut_edit_reopen_and_cancel_accept_separate_key(client, auth_headers, configured_key):
    cut = client.post("/api/v1/punto-de-venta/corte-caja", headers=auth_headers,
                      json={"fondo_inicial": "2000", "efectivo_real": "2000"})
    assert cut.status_code == 201, cut.text
    url = f"/api/v1/punto-de-venta/cortes-caja/{cut.json()['id']}"
    protected = {**auth_headers, "X-Admin-Override-Password": configured_key,
                 "X-Admin-Override-Motivo": "Correccion autorizada de prueba"}
    response = client.put(url, headers=protected, json={"fondo_inicial": "2000", "efectivo_real": "2000",
                                                      "motivo": "Correccion autorizada de prueba"})
    assert response.status_code == 200, response.text
    reopened = client.post(url + "/reabrir", headers=protected, json={"motivo": "Correccion autorizada de prueba"})
    assert reopened.status_code == 200, reopened.text
    cut = client.post("/api/v1/punto-de-venta/corte-caja", headers=auth_headers,
                      json={"fondo_inicial": "2000", "efectivo_real": "2000"})
    assert cut.status_code == 201, cut.text
    url = f"/api/v1/punto-de-venta/cortes-caja/{cut.json()['id']}"
    cancelled = client.post(url + "/cancelar", headers=protected, json={"motivo": "Correccion autorizada de prueba"})
    assert cancelled.status_code == 200, cancelled.text


def test_user_role_edit_reuses_route_and_audits_before_after(client, auth_headers, db, admin_user):
    cashier = user(db)
    old_hash = cashier.hashed_password
    response = client.put(f"/api/v1/auth/usuarios/{cashier.id}", headers=auth_headers,
                          json={"nombre": "  Sofia prueba  ", "email": "sofia@example.com", "rol": "gerente"})
    assert response.status_code == 200, response.text
    assert response.json()["nombre"] == "Sofia prueba"
    assert response.json()["rol"] == "gerente"
    assert response.json()["permisos_modulos"]["inv"] == "editar"
    assert "hashed_password" not in response.json()
    db.refresh(cashier)
    assert cashier.hashed_password == old_hash
    event = db.query(LogAuditoria).filter_by(entidad="usuario", entidad_id=cashier.id, accion="actualizar").one()
    assert json.loads(event.datos_anteriores)["rol"] == "cajero"
    assert json.loads(event.datos_nuevos)["rol"] == "gerente"
    assert event.usuario_id == admin_user.id
    assert old_hash not in event.datos_anteriores + event.datos_nuevos


@pytest.mark.parametrize("reset", [False, True])
def test_role_permission_reset_is_explicit(client, auth_headers, db, reset):
    cashier = user(db)
    cashier.permisos_modulos = {"inv": "editar", "pos": "editar"}
    db.commit()
    response = client.put(f"/api/v1/auth/usuarios/{cashier.id}", headers=auth_headers,
                          json={"rol": "consulta", "restablecer_permisos": reset})
    assert response.status_code == 200, response.text
    assert response.json()["permisos_modulos"]["inv"] == ("ver" if reset else "editar")
    assert response.json()["permisos_modulos"]["pos"] == ("ver" if reset else "editar")


def test_non_admin_cannot_edit_roles_using_old_admin_token_claim(client, auth_headers, db):
    cashier = user(db)
    forged_claim = create_access_token({"sub": cashier.id, "rol": "administrador"})
    response = client.put(f"/api/v1/auth/usuarios/{cashier.id}", headers={"Authorization": "Bearer " + forged_claim},
                          json={"rol": "administrador"})
    assert response.status_code == 403
    db.refresh(cashier)
    assert cashier.rol == RolUsuario.CAJERO


def test_last_active_admin_cannot_be_demoted_or_deactivated(client, auth_headers, admin_user, db):
    other = user(db, RolUsuario.ADMINISTRADOR, email="inactive@test.invalid")
    other.activo = False
    db.commit()
    for change in [{"rol": "gerente"}, {"activo": False}]:
        response = client.put(f"/api/v1/auth/usuarios/{admin_user.id}", headers=auth_headers, json=change)
        assert response.status_code == 400
        db.refresh(admin_user)
        assert admin_user.rol == RolUsuario.ADMINISTRADOR and admin_user.activo
    assert client.delete(f"/api/v1/auth/usuarios/{admin_user.id}", headers=auth_headers).status_code == 400


def test_self_demotion_with_other_admin_revokes_admin_access_immediately(client, auth_headers, admin_user, db):
    user(db, RolUsuario.ADMINISTRADOR, email="other-admin@test.invalid")
    response = client.put(f"/api/v1/auth/usuarios/{admin_user.id}", headers=auth_headers,
                          json={"rol": "gerente", "restablecer_permisos": True})
    assert response.status_code == 200, response.text
    assert client.get("/api/v1/auth/usuarios", headers=auth_headers).status_code == 403
    assert client.get("/api/v1/auth/me", headers=auth_headers).json()["rol"] == "gerente"


@pytest.mark.parametrize("change", [{"rol": "none"}, {"rol": None}, {"activo": None}, {"nombre": None},
                                     {"nombre": " "}, {"email": "invalid"}, {"email": None}])
def test_invalid_user_edits_are_rejected(client, auth_headers, db, change):
    cashier = user(db)
    response = client.put(f"/api/v1/auth/usuarios/{cashier.id}", headers=auth_headers, json=change)
    assert response.status_code == 422
    db.refresh(cashier)
    assert cashier.rol == RolUsuario.CAJERO and cashier.activo


def test_duplicate_email_does_not_partially_change_role(client, auth_headers, db, admin_user):
    cashier = user(db)
    response = client.put(f"/api/v1/auth/usuarios/{cashier.id}", headers=auth_headers,
                          json={"email": admin_user.email, "rol": "gerente"})
    assert response.status_code == 400
    assert cashier.rol == RolUsuario.CAJERO


def test_admin_management_rechecks_actor_after_lock(db, admin_user):
    admin_user.rol = RolUsuario.CAJERO
    db.commit()
    with pytest.raises(HTTPException) as err:
        bloquear_gestion_usuarios(db, admin_user)
    assert err.value.status_code == 403
