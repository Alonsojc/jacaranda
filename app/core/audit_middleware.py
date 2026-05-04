"""
Middleware de auditoría automática.
Registra todas las operaciones de escritura (POST, PUT, PATCH, DELETE)
en el log de auditoría sin intervención manual en cada endpoint.
"""

import json
import logging
import time
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.database import SessionLocal
from app.core.security import decode_access_token, JWTError

logger = logging.getLogger("jacaranda.audit")

# Métodos HTTP que representan mutaciones
MUTATION_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Rutas que no se auditan (health checks, auth, docs)
EXEMPT_PATHS = {"/health", "/", "/docs", "/redoc", "/openapi.json"}

# Mapeo de método HTTP a acción de auditoría
METHOD_ACTION_MAP = {
    "POST": "crear",
    "PUT": "actualizar",
    "PATCH": "actualizar",
    "DELETE": "eliminar",
}


def _extract_module_and_entity(path: str) -> tuple[str, str | None, int | None]:
    """
    Extrae módulo, entidad e ID de la ruta.
    Ej: /api/v1/inventario/productos/5 -> ('inventario', 'productos', 5)
    """
    parts = [p for p in path.split("/") if p]
    # Remove api/v1 prefix
    if len(parts) >= 2 and parts[0] == "api" and parts[1] == "v1":
        parts = parts[2:]

    modulo = parts[0] if parts else "desconocido"
    entidad = parts[1] if len(parts) > 1 else None
    entidad_id = None

    # Try to find numeric ID in the path
    for part in reversed(parts):
        try:
            entidad_id = int(part)
            break
        except ValueError:
            continue

    return modulo, entidad, entidad_id


def _get_user_info(request: Request) -> tuple[int | None, str | None]:
    """Extrae user_id y nombre del token JWT en el header Authorization."""
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        return None, None

    token = auth_header[7:]
    try:
        payload = decode_access_token(token)
        user_id = payload.get("sub")
        nombre = payload.get("nombre", "")
        return user_id, nombre
    except (JWTError, Exception):
        return None, None


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class AuditMiddleware(BaseHTTPMiddleware):
    """Registra automáticamente operaciones de escritura en el log de auditoría."""

    async def dispatch(self, request: Request, call_next):
        method = request.method
        path = request.url.path

        # Solo auditar mutaciones en rutas API
        if method not in MUTATION_METHODS or path in EXEMPT_PATHS:
            return await call_next(request)

        if not path.startswith("/api/"):
            return await call_next(request)

        # Ejecutar la petición
        response = await call_next(request)

        # Solo registrar si la operación fue exitosa (2xx)
        if 200 <= response.status_code < 300:
            try:
                user_id, user_nombre = _get_user_info(request)
                modulo, entidad, entidad_id = _extract_module_and_entity(path)
                accion = METHOD_ACTION_MAP.get(method, method.lower())
                ip = _get_client_ip(request)
                user_agent = request.headers.get("user-agent", "")

                # Registrar en BD en un session aparte (no bloquea la respuesta)
                from app.models.auditoria import LogAuditoria
                db = SessionLocal()
                try:
                    if user_id is not None and not user_nombre:
                        try:
                            from app.models.usuario import Usuario

                            usuario = db.get(Usuario, user_id)
                            if usuario:
                                user_nombre = usuario.nombre
                        except Exception:
                            user_nombre = None
                    evento = LogAuditoria(
                        usuario_id=user_id,
                        usuario_nombre=user_nombre,
                        accion=accion,
                        modulo=modulo,
                        entidad=entidad,
                        entidad_id=entidad_id,
                        ip_address=ip,
                        user_agent=user_agent[:500] if user_agent else None,
                    )
                    db.add(evento)
                    db.commit()
                except Exception as e:
                    db.rollback()
                    logger.warning("Error registrando auditoría: %s", e)
                finally:
                    db.close()
            except Exception as e:
                logger.warning("Error en audit middleware: %s", e)

        return response
