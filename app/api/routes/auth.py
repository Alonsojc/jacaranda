"""Rutas de autenticación y gestión de usuarios."""

import json
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.core.security import get_password_hash
from app.models.usuario import Usuario, RolUsuario
from app.schemas.usuario import (
    UsuarioCreate, UsuarioUpdate, UsuarioResponse, Token, LoginRequest,
)
from app.services.auth_service import crear_usuario, autenticar_usuario, generar_token

router = APIRouter()


@router.post("/registro", response_model=UsuarioResponse, status_code=status.HTTP_201_CREATED)
def registro(data: UsuarioCreate, db: Session = Depends(get_db)):
    try:
        return crear_usuario(db, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/login", response_model=Token)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    usuario = autenticar_usuario(db, data.email, data.password)
    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas",
        )
    token = generar_token(usuario)
    return Token(access_token=token)


@router.get("/me", response_model=UsuarioResponse)
def perfil(current_user: Usuario = Depends(get_current_user)):
    return current_user


# ── Admin: gestión de usuarios ──────────────────────────────────

@router.get("/usuarios", response_model=list[UsuarioResponse])
def listar_usuarios(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR)),
):
    return db.query(Usuario).order_by(Usuario.nombre).all()


@router.post("/usuarios", response_model=UsuarioResponse, status_code=201)
def crear_usuario_admin(
    data: UsuarioCreate,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR)),
):
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
    usuario = db.query(Usuario).filter(Usuario.id == id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(usuario, key, value)
    db.commit()
    db.refresh(usuario)
    return usuario


class CambiarPasswordRequest(BaseModel):
    password: str


@router.put("/usuarios/{id}/password")
def cambiar_password(
    id: int,
    data: CambiarPasswordRequest,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR)),
):
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
    usuario = db.query(Usuario).filter(Usuario.id == id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if usuario.id == _user.id:
        raise HTTPException(status_code=400, detail="No puedes desactivarte a ti mismo")
    usuario.activo = not usuario.activo
    db.commit()
    return {"ok": True, "activo": usuario.activo}
