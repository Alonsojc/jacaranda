"""
Rutas de notificaciones: WebSocket en tiempo real y alertas push.
"""

import logging

from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.core.security import decode_access_token, JWTError
from app.models.usuario import Usuario, RolUsuario
from app.services.notificacion_service import (
    manager,
    obtener_notificaciones_pendientes,
    notificar_alerta,
    generar_push_config,
    registrar_fcm_token,
    revocar_fcm_token,
)

logger = logging.getLogger("jacaranda.notificaciones")

router = APIRouter()


class FCMTokenIn(BaseModel):
    token: str = Field(..., min_length=20, max_length=4096)
    plataforma: str | None = Field(default=None, max_length=80)


class FCMTokenRevokeIn(BaseModel):
    token: str = Field(..., min_length=20, max_length=4096)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = ""):
    """
    Conexión WebSocket para notificaciones en tiempo real.

    Autenticación via query param: ws://host/api/v1/notificaciones/ws?token=JWT_TOKEN
    """
    # Autenticar con JWT
    if not token:
        await websocket.close(code=4001, reason="Token requerido")
        return

    try:
        payload = decode_access_token(token)
        if payload.get("type") != "access":
            await websocket.close(code=4001, reason="Token inválido")
            return
        user_id = payload.get("sub")
        if user_id is None:
            await websocket.close(code=4001, reason="Token inválido")
            return
    except JWTError:
        await websocket.close(code=4001, reason="Token inválido o expirado")
        return

    # Conectar
    await manager.connect(user_id, websocket)

    try:
        # Enviar mensaje de bienvenida
        await websocket.send_json({
            "tipo": "conexion",
            "mensaje": "Conectado al sistema de notificaciones",
            "usuario_id": user_id,
        })

        # Mantener la conexión viva escuchando mensajes (ping/pong)
        while True:
            data = await websocket.receive_text()
            # Responder a pings del cliente para keep-alive
            if data == "ping":
                await websocket.send_json({"tipo": "pong"})
    except WebSocketDisconnect:
        manager.disconnect(user_id, websocket)
        logger.info("Cliente WebSocket desconectado: usuario_id=%d", user_id)
    except Exception as e:
        manager.disconnect(user_id, websocket)
        logger.warning("Error en WebSocket usuario_id=%d: %s", user_id, e)


@router.get("/alertas-push")
def get_alertas_push(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Obtiene el resumen actual de alertas del sistema."""
    alertas = obtener_notificaciones_pendientes(db, current_user.id)
    return {
        "alertas": alertas,
        "push_config": generar_push_config(),
    }


@router.get("/fcm-config")
def get_fcm_config(current_user: Usuario = Depends(get_current_user)):
    """Devuelve configuración pública para registrar este navegador en FCM."""
    return generar_push_config()


@router.post("/fcm-token")
def registrar_token_fcm(
    payload: FCMTokenIn,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Registra o reactiva el token FCM del navegador actual."""
    item = registrar_fcm_token(
        db=db,
        usuario_id=current_user.id,
        token=payload.token,
        plataforma=payload.plataforma,
        user_agent=request.headers.get("user-agent"),
    )
    return {
        "ok": True,
        "id": item.id,
        "activo": item.activo,
        "push_config": generar_push_config(),
    }


@router.post("/fcm-token/revocar")
def revocar_token_fcm(
    payload: FCMTokenRevokeIn,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Desactiva el token FCM de este usuario/dispositivo."""
    removed = revocar_fcm_token(db, current_user.id, payload.token)
    return {"ok": True, "revocado": removed}


@router.post("/test")
async def enviar_notificacion_test(
    current_user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR)),
):
    """
    Envía una notificación de prueba a todos los usuarios conectados.
    Solo disponible para administradores (debugging).
    """
    await notificar_alerta(
        tipo="test",
        mensaje_texto="Notificación de prueba desde el panel de administración",
        severidad="baja",
    )
    conexiones_activas = sum(len(conns) for conns in manager.active_connections.values())
    return {
        "mensaje": "Notificación de prueba enviada",
        "conexiones_activas": conexiones_activas,
        "usuarios_conectados": len(manager.active_connections),
    }
