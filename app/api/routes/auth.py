"""Rutas de autenticación y gestión de usuarios."""

import json
import time
from collections import defaultdict
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, SecretStr
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.core.rate_limit import check_authorization_rate_limit
from app.core.security import get_password_hash, decode_access_token, JWTError, create_access_token, verify_password
from app.models.usuario import Usuario, RolUsuario
from app.schemas.usuario import (
    UsuarioCreate, UsuarioUpdate, UsuarioResponse, Token, LoginRequest,
)
from app.services.auth_service import (
    crear_usuario, autenticar_usuario, generar_tokens, bloquear_gestion_usuarios, validar_cambio_acceso,
)
from app.services.auditoria_service import registrar_evento
from app.services.autorizacion_service import estado_clave, guardar_clave

router = APIRouter()

# Rate limiting: max 5 intentos por IP cada 60 segundos
_login_attempts: dict[str, list[float]] = defaultdict(list)
_MAX_ATTEMPTS = 5
_WINDOW_SECONDS = 60


def _check_rate_limit(ip: str):
    """Verifica que no se exceda el límite de intentos de login."""
    now = time.time()
    # Limpiar intentos viejos
    _login_attempts[ip] = [t for t in _login_attempts[ip] if now - t < _WINDOW_SECONDS]
    if len(_login_attempts[ip]) >= _MAX_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiados intentos. Espere un minuto.",
        )
    _login_attempts[ip].append(now)


@router.post("/login", response_model=Token)
def login(data: LoginRequest, request: Request, db: Session = Depends(get_db)):
    _check_rate_limit(request.client.host if request.client else "unknown")
    usuario = autenticar_usuario(db, data.email, data.password)
    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas",
        )
    tokens = generar_tokens(usuario)
    return Token(access_token=tokens["access_token"], refresh_token=tokens["refresh_token"])


class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/refresh", response_model=Token)
def refresh_token(data: RefreshRequest, db: Session = Depends(get_db)):
    """Renueva access_token usando un refresh_token válido."""
    try:
        payload = decode_access_token(data.refresh_token)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token inválido o expirado",
        )
    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token no es de tipo refresh",
        )
    user_id = payload.get("sub")
    usuario = db.query(Usuario).filter(Usuario.id == user_id, Usuario.activo.is_(True)).first()
    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario no encontrado o inactivo",
        )
    new_access = create_access_token(data={
        "sub": usuario.id,
        "rol": usuario.rol.value,
        "nombre": usuario.nombre,
        "email": usuario.email,
    })
    return Token(access_token=new_access)


@router.get("/me", response_model=UsuarioResponse)
def perfil(current_user: Usuario = Depends(get_current_user)):
    return current_user


# ── Admin: gestión de usuarios ──────────────────────────────────

@router.get("/clave-autorizacion")
def consultar_clave_autorizacion(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    return estado_clave(db)


class ClaveAutorizacionRequest(BaseModel):
    password_actual: SecretStr
    nueva_clave: SecretStr
    confirmacion: SecretStr


@router.put("/clave-autorizacion")
def configurar_clave_autorizacion(
    data: ClaveAutorizacionRequest,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR)),
):
    check_authorization_rate_limit(user.id)
    bloquear_gestion_usuarios(db, user)
    password = data.password_actual.get_secret_value()
    if len(password.encode("utf-8")) > 72 or not verify_password(password, user.hashed_password):
        registrar_evento(
            db, usuario_id=user.id, usuario_nombre=user.nombre,
            accion="autorizar_fallida", modulo="usuarios", entidad="clave_autorizacion",
            motivo="Configurar clave de autorizacion",
        )
        raise HTTPException(status_code=403, detail="Contraseña actual incorrecta")
    nueva_clave = data.nueva_clave.get_secret_value()
    if len(nueva_clave) < 8 or len(nueva_clave.encode("utf-8")) > 72:
        raise HTTPException(status_code=400, detail="La clave debe tener al menos 8 caracteres y como maximo 72 bytes")
    if nueva_clave != data.confirmacion.get_secret_value():
        raise HTTPException(status_code=400, detail="La confirmacion de la clave no coincide")
    if nueva_clave == password:
        raise HTTPException(status_code=400, detail="Usa una clave distinta de tu contraseña de inicio de sesion")
    return guardar_clave(db, nueva_clave, user)


@router.get("/usuarios", response_model=list[UsuarioResponse])
def listar_usuarios(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, le=500),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR)),
):
    return db.query(Usuario).order_by(Usuario.nombre).offset(skip).limit(limit).all()


@router.post("/usuarios", response_model=UsuarioResponse, status_code=201)
def crear_usuario_admin(
    data: UsuarioCreate,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR)),
):
    bloquear_gestion_usuarios(db, _user)
    try:
        return crear_usuario(db, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/usuarios/{id}", response_model=UsuarioResponse)
def actualizar_usuario(
    id: int,
    data: UsuarioUpdate,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR)),
):
    bloquear_gestion_usuarios(db, _user)
    usuario = db.query(Usuario).filter(Usuario.id == id).populate_existing().first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    validar_cambio_acceso(db, usuario, data.rol or usuario.rol,
                         usuario.activo if data.activo is None else data.activo, _user)
    if data.restablecer_permisos and data.rol is None:
        raise HTTPException(status_code=400, detail="Selecciona el rol para restablecer sus permisos")
    if data.email and data.email != usuario.email:
        existente = db.query(Usuario).filter(
            Usuario.email == data.email, Usuario.id != id
        ).first()
        if existente:
            raise HTTPException(status_code=400, detail="Ese email ya está en uso")
    _ALLOWED_FIELDS = {"nombre", "email", "rol", "activo"}
    anteriores = _datos_usuario(usuario)
    for key, value in data.model_dump(exclude_unset=True).items():
        if key not in _ALLOWED_FIELDS:
            continue
        setattr(usuario, key, value)
    if data.restablecer_permisos:
        usuario._permisos_modulos = None
    registrar_evento(
        db, usuario_id=_user.id, usuario_nombre=_user.nombre,
        accion="actualizar", modulo="usuarios", entidad="usuario", entidad_id=usuario.id,
        datos_anteriores=anteriores, datos_nuevos=_datos_usuario(usuario),
        motivo="Editar usuario", commit=False,
    )
    db.commit()
    db.refresh(usuario)
    return usuario


def _datos_usuario(usuario: Usuario) -> dict:
    return {"nombre": usuario.nombre, "email": usuario.email, "rol": usuario.rol.value,
            "activo": usuario.activo, "permisos_modulos": usuario.permisos_modulos}


class CambiarPasswordRequest(BaseModel):
    password: str


@router.put("/usuarios/{id}/password")
def cambiar_password(
    id: int,
    data: CambiarPasswordRequest,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR)),
):
    bloquear_gestion_usuarios(db, _user)
    usuario = db.query(Usuario).filter(Usuario.id == id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if len(data.password) < 8:
        raise HTTPException(status_code=400, detail="La contraseña debe tener al menos 8 caracteres")
    usuario.hashed_password = get_password_hash(data.password)
    db.commit()
    return {"ok": True}


class PermisosRequest(BaseModel):
    permisos: dict


@router.put("/usuarios/{id}/permisos")
def actualizar_permisos(
    id: int,
    data: PermisosRequest,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR)),
):
    bloquear_gestion_usuarios(db, _user)
    usuario = db.query(Usuario).filter(Usuario.id == id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    usuario._permisos_modulos = json.dumps(data.permisos)
    db.commit()
    db.refresh(usuario)
    return {"ok": True, "permisos": usuario.permisos_modulos}


@router.delete("/usuarios/{id}")
def desactivar_usuario(
    id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR)),
):
    bloquear_gestion_usuarios(db, _user)
    usuario = db.query(Usuario).filter(Usuario.id == id).populate_existing().first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if usuario.id == _user.id:
        raise HTTPException(status_code=400, detail="No puedes desactivarte a ti mismo")
    validar_cambio_acceso(db, usuario, usuario.rol, not usuario.activo, _user)
    anteriores = _datos_usuario(usuario)
    usuario.activo = not usuario.activo
    registrar_evento(
        db, usuario_id=_user.id, usuario_nombre=_user.nombre,
        accion="actualizar", modulo="usuarios", entidad="usuario", entidad_id=usuario.id,
        datos_anteriores=anteriores, datos_nuevos=_datos_usuario(usuario),
        motivo="Cambiar estado de usuario", commit=False,
    )
    db.commit()
    return {"ok": True, "activo": usuario.activo}
