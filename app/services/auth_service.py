"""Servicio de autenticación."""

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.usuario import Usuario, RolUsuario
from app.schemas.usuario import UsuarioCreate
from app.core.security import (
    verify_password,
    get_password_hash,
    create_access_token,
    create_refresh_token,
    needs_rehash,
)


def bloquear_gestion_usuarios(db: Session, actor: Usuario) -> None:
    """Serialize admin changes and recheck the actor after taking the lock."""
    connection = db.connection()
    if connection.dialect.name == "postgresql":
        db.execute(func.pg_advisory_xact_lock(674322, 1).select())
    elif connection.dialect.name == "sqlite":
        if not connection.connection.driver_connection.in_transaction:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
    db.refresh(actor)
    if not actor.activo or actor.rol != RolUsuario.ADMINISTRADOR:
        raise HTTPException(status_code=403, detail="Se requiere un administrador activo")


def validar_cambio_acceso(db: Session, usuario: Usuario, rol: RolUsuario, activo: bool, actor: Usuario) -> None:
    if usuario.id == actor.id and not activo:
        raise HTTPException(status_code=400, detail="No puedes desactivarte a ti mismo")
    if usuario.rol == RolUsuario.ADMINISTRADOR and usuario.activo and not (rol == RolUsuario.ADMINISTRADOR and activo):
        otro_admin = db.query(Usuario.id).filter(
            Usuario.id != usuario.id,
            Usuario.rol == RolUsuario.ADMINISTRADOR,
            Usuario.activo.is_(True),
        ).first()
        if otro_admin is None:
            raise HTTPException(status_code=400, detail="Debe quedar al menos un administrador activo")


def crear_usuario(db: Session, data: UsuarioCreate) -> Usuario:
    if db.query(Usuario).filter(Usuario.email == data.email).first():
        raise ValueError("Ya existe un usuario con ese email")
    usuario = Usuario(
        nombre=data.nombre,
        email=data.email,
        hashed_password=get_password_hash(data.password),
        rol=data.rol,
    )
    db.add(usuario)
    db.commit()
    db.refresh(usuario)
    return usuario


def autenticar_usuario(db: Session, email: str, password: str) -> Usuario | None:
    usuario = db.query(Usuario).filter(Usuario.email == email).first()
    if not usuario or not verify_password(password, usuario.hashed_password):
        return None
    if not usuario.activo:
        return None
    # Migración transparente: rehash legacy SHA-256 → bcrypt
    if needs_rehash(usuario.hashed_password):
        usuario.hashed_password = get_password_hash(password)
        db.commit()
    return usuario


def generar_tokens(usuario: Usuario) -> dict:
    """Genera access_token y refresh_token para el usuario."""
    token_data = {
        "sub": usuario.id,
        "rol": usuario.rol.value,
        "nombre": usuario.nombre,
        "email": usuario.email,
    }
    return {
        "access_token": create_access_token(data=token_data),
        "refresh_token": create_refresh_token(data=token_data),
    }


# Backward compat alias
def generar_token(usuario: Usuario) -> str:
    return create_access_token(data={
        "sub": usuario.id,
        "rol": usuario.rol.value,
        "nombre": usuario.nombre,
        "email": usuario.email,
    })
