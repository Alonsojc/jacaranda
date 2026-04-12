"""Servicio de autenticación."""

from sqlalchemy.orm import Session

from app.models.usuario import Usuario, RolUsuario
from app.schemas.usuario import UsuarioCreate
from app.core.security import verify_password, get_password_hash, create_access_token


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
    return usuario


def generar_token(usuario: Usuario) -> str:
    return create_access_token(data={"sub": usuario.id, "rol": usuario.rol.value})
