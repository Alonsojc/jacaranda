"""Dependencias de FastAPI: autenticación, roles, sesión de BD."""

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from app.core.security import JWTError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.usuario import Usuario, RolUsuario

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> Usuario:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No se pudieron validar las credenciales",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(token)
        if payload.get("type") != "access":
            raise credentials_exception
        user_id: int = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(Usuario).filter(Usuario.id == user_id).first()
    if user is None or not user.activo:
        raise credentials_exception
    return user


def require_role(*roles: RolUsuario):
    """Dependency factory para restringir acceso por rol."""
    def role_checker(current_user: Usuario = Depends(get_current_user)) -> Usuario:
        if current_user.rol not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Se requiere rol: {', '.join(r.value for r in roles)}",
            )
        return current_user
    return role_checker


_PERMISSION_LEVELS = {"oculto": 0, "ver": 1, "editar": 2}


def require_permission(module: str, level: str = "ver"):
    """Restrict access using server-side module permissions."""
    required = _PERMISSION_LEVELS.get(level)
    if required is None:
        raise ValueError(f"Nivel de permiso inválido: {level}")

    def permission_checker(
        current_user: Usuario = Depends(get_current_user),
    ) -> Usuario:
        permissions = current_user.permisos_modulos or {}
        current = _PERMISSION_LEVELS.get(permissions.get(module, "oculto"), 0)
        if current < required:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permiso insuficiente para módulo '{module}'",
            )
        return current_user

    return permission_checker
