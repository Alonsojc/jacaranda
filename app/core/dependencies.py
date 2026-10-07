"""Dependencias de FastAPI: autenticación, roles, sesión de BD."""

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from app.core.security import JWTError
from sqlalchemy.orm import Session
from urllib.parse import unquote

from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import check_authorization_rate_limit
from app.core.security import decode_access_token, verify_password
from app.models.usuario import Usuario, RolUsuario
from app.services.auditoria_service import registrar_evento
from app.services.autorizacion_service import obtener_clave, verificar_clave

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


def require_admin_financials(
    current_user: Usuario = Depends(get_current_user),
) -> Usuario:
    """Restrict sensitive financial reports to administrators."""
    if current_user.rol != RolUsuario.ADMINISTRADOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Este reporte financiero requiere administrador",
        )
    return current_user


_PERMISSION_LEVELS = {"oculto": 0, "ver": 1, "editar": 2}
_PRODUCTION_DISABLED_MODULES = {
    "compras",
    "proveedores",
    "sucursales",
    "kpis",
    "ejecutivo",
    "fiscal",
}


def disabled_modules() -> set[str]:
    configured = {
        module.strip()
        for module in (settings.DISABLED_MODULES or "").split(",")
        if module.strip()
    }
    if configured:
        return configured
    if settings.is_production:
        return set(_PRODUCTION_DISABLED_MODULES)
    return set()


def require_permission(module: str, level: str = "ver"):
    """Restrict access using server-side module permissions."""
    required = _PERMISSION_LEVELS.get(level)
    if required is None:
        raise ValueError(f"Nivel de permiso inválido: {level}")

    def permission_checker(
        current_user: Usuario = Depends(get_current_user),
    ) -> Usuario:
        if module in disabled_modules():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Módulo '{module}' desactivado",
            )
        permissions = current_user.permisos_modulos or {}
        current = _PERMISSION_LEVELS.get(permissions.get(module, "oculto"), 0)
        if current < required:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permiso insuficiente para módulo '{module}'",
            )
        return current_user

    return permission_checker


def _admin_from_override_password(db: Session, password: str | None) -> Usuario | None:
    if not password or len(password.encode("utf-8")) > 72:
        return None
    admins = (
        db.query(Usuario)
        .filter(
            Usuario.rol == RolUsuario.ADMINISTRADOR,
            Usuario.activo.is_(True),
        )
        .all()
    )
    for admin in admins:
        if verify_password(password, admin.hashed_password):
            return admin
    return None


def require_admin_or_override(module: str, action: str, *, require_password: bool = False):
    """Allow admins directly unless this action explicitly requires a password."""

    def checker(
        current_user: Usuario = Depends(require_permission(module, "editar")),
        db: Session = Depends(get_db),
        admin_password: str | None = Header(
            default=None,
            alias="X-Admin-Override-Password",
        ),
        motivo: str | None = Header(
            default=None,
            alias="X-Admin-Override-Motivo",
        ),
    ) -> Usuario:
        if current_user.rol == RolUsuario.ADMINISTRADOR and not require_password:
            return current_user

        check_authorization_rate_limit(current_user.id)
        config = obtener_clave(db)
        authorizing_admin = None
        # Keep existing approvals working until an admin configures the separate key.
        if config is None:
            authorizing_admin = _admin_from_override_password(db, admin_password)
            authorized = authorizing_admin is not None
        else:
            authorized = verificar_clave(config, admin_password)
        metodo = "clave_autorizacion" if config is not None else "password_admin"
        if not authorized:
            registrar_evento(
                db,
                usuario_id=current_user.id,
                usuario_nombre=current_user.nombre,
                accion="autorizar_fallida",
                modulo=module,
                entidad="admin_override",
                motivo=unquote(motivo or "").strip() or None,
                datos_nuevos={"accion": action, "metodo": metodo},
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Clave de autorizacion incorrecta o faltante"
                    if config is not None
                    else "Esta acción requiere la contraseña de un administrador"
                ),
            )

        motivo_limpio = unquote(motivo or "").strip()
        if not motivo_limpio:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El motivo es obligatorio para autorizar esta acción",
            )

        datos = {"accion": action, "metodo": metodo, "motivo": motivo_limpio}
        if authorizing_admin is not None:
            datos.update({"admin_id": authorizing_admin.id, "admin_nombre": authorizing_admin.nombre})
        registrar_evento(
            db,
            usuario_id=current_user.id,
            usuario_nombre=current_user.nombre,
            accion="autorizar",
            modulo=module,
            entidad="admin_override",
            motivo=motivo_limpio,
            datos_nuevos=datos,
        )
        return current_user

    return checker
