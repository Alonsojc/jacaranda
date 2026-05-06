"""
Servicio de notificaciones en tiempo real via WebSocket.
Gestiona conexiones activas y despacho de mensajes a usuarios.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import WebSocket
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.notificacion import FCMToken
from app.services.alertas_service import alertas_consolidadas

logger = logging.getLogger("jacaranda.notificaciones")
_firebase_app = None
_firebase_init_failed = False


class ConnectionManager:
    """Administrador de conexiones WebSocket en memoria."""

    def __init__(self):
        self.active_connections: dict[int, list[WebSocket]] = {}

    async def connect(self, user_id: int, websocket: WebSocket):
        """Acepta y registra una conexión WebSocket para un usuario."""
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)
        logger.info("WebSocket conectado: usuario_id=%d (total=%d)", user_id, len(self.active_connections[user_id]))

    def disconnect(self, user_id: int, websocket: WebSocket):
        """Elimina una conexión WebSocket del registro."""
        if user_id in self.active_connections:
            try:
                self.active_connections[user_id].remove(websocket)
            except ValueError:
                pass
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
        logger.info("WebSocket desconectado: usuario_id=%d", user_id)

    async def send_to_user(self, user_id: int, message: dict):
        """Envía un mensaje JSON a todas las conexiones de un usuario."""
        if user_id not in self.active_connections:
            return
        stale = []
        for ws in self.active_connections[user_id]:
            try:
                await ws.send_json(message)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self.disconnect(user_id, ws)

    async def broadcast(self, message: dict):
        """Envía un mensaje JSON a todos los usuarios conectados."""
        stale: list[tuple[int, WebSocket]] = []
        for user_id, connections in self.active_connections.items():
            for ws in connections:
                try:
                    await ws.send_json(message)
                except Exception:
                    stale.append((user_id, ws))
        for user_id, ws in stale:
            self.disconnect(user_id, ws)


# Singleton del manager
manager = ConnectionManager()


async def notificar_nueva_venta(venta_data: dict):
    """Notifica a todos los usuarios conectados sobre una nueva venta."""
    mensaje = {
        "tipo": "nueva_venta",
        "datos": {
            "total": venta_data.get("total"),
            "folio": venta_data.get("folio"),
            "timestamp": venta_data.get("timestamp", datetime.now(timezone.utc).isoformat()),
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await manager.broadcast(mensaje)
    logger.info("Notificación nueva_venta enviada: folio=%s", venta_data.get("folio"))


async def notificar_stock_bajo(producto_nombre: str, stock_actual: float, stock_minimo: float):
    """Alerta cuando el stock de un producto cae por debajo del mínimo."""
    mensaje = {
        "tipo": "stock_bajo",
        "datos": {
            "producto": producto_nombre,
            "stock_actual": stock_actual,
            "stock_minimo": stock_minimo,
        },
        "severidad": "alta",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await manager.broadcast(mensaje)
    logger.info("Notificación stock_bajo: %s (%s/%s)", producto_nombre, stock_actual, stock_minimo)


async def notificar_pedido_nuevo(pedido_data: dict):
    """Notifica a todos los usuarios conectados sobre un nuevo pedido."""
    mensaje = {
        "tipo": "nuevo_pedido",
        "datos": {
            "pedido_id": pedido_data.get("pedido_id"),
            "folio": pedido_data.get("folio"),
            "cliente": pedido_data.get("cliente"),
            "fecha_entrega": pedido_data.get("fecha_entrega"),
            "total": pedido_data.get("total"),
            "origen": pedido_data.get("origen"),
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await manager.broadcast(mensaje)
    await asyncio.to_thread(enviar_fcm_pedido_nuevo, mensaje["datos"])
    logger.info("Notificación nuevo_pedido: id=%s", pedido_data.get("pedido_id"))


async def notificar_alerta(tipo: str, mensaje_texto: str, severidad: str = "media"):
    """Envía una alerta genérica a todos los usuarios conectados."""
    mensaje = {
        "tipo": "alerta",
        "datos": {
            "tipo_alerta": tipo,
            "mensaje": mensaje_texto,
        },
        "severidad": severidad,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await manager.broadcast(mensaje)
    logger.info("Alerta genérica enviada: tipo=%s severidad=%s", tipo, severidad)


def obtener_notificaciones_pendientes(db, usuario_id: int) -> dict:
    """
    Retorna las alertas activas del sistema usando alertas_service.
    No se almacenan en BD; se calculan en tiempo real.
    """
    alertas = alertas_consolidadas(db)

    # Contar totales por severidad
    total_criticas = 0
    total_altas = 0

    for item in alertas.get("stock_bajo", []):
        if item.get("severidad") == "critica":
            total_criticas += 1
        elif item.get("severidad") == "alta":
            total_altas += 1

    for item in alertas.get("caducidades", []):
        if item.get("severidad") == "critica":
            total_criticas += 1
        elif item.get("severidad") == "alta":
            total_altas += 1

    for item in alertas.get("pedidos_pendientes", []):
        if item.get("severidad") == "critica":
            total_criticas += 1
        elif item.get("severidad") == "alta":
            total_altas += 1

    merma = alertas.get("merma_hoy", {})
    if merma.get("severidad") == "alta":
        total_altas += 1

    alertas["resumen"] = {
        "total_criticas": total_criticas,
        "total_altas": total_altas,
        "total_stock_bajo": len(alertas.get("stock_bajo", [])),
        "total_caducidades": len(alertas.get("caducidades", [])),
        "total_pedidos_pendientes": len(alertas.get("pedidos_pendientes", [])),
    }

    return alertas


def _parse_web_config() -> dict:
    if not settings.FIREBASE_WEB_CONFIG_JSON:
        return {}
    try:
        data = json.loads(settings.FIREBASE_WEB_CONFIG_JSON)
    except json.JSONDecodeError:
        logger.warning("FIREBASE_WEB_CONFIG_JSON no es JSON válido")
        return {}
    return data if isinstance(data, dict) else {}


def generar_push_config() -> dict:
    """
    Retorna la configuración pública para Firebase Cloud Messaging.
    La configuración web y la VAPID public key no son secretos.
    """
    web_config = _parse_web_config()
    enabled = bool(web_config and settings.FIREBASE_VAPID_PUBLIC_KEY)
    return {
        "enabled": enabled,
        "provider": "firebase" if enabled else "local",
        "vapid_public_key": settings.FIREBASE_VAPID_PUBLIC_KEY,
        "firebase_config": web_config,
        "server_enabled": bool(
            settings.FIREBASE_SERVICE_ACCOUNT_JSON or settings.FIREBASE_SERVICE_ACCOUNT_FILE
        ),
        "nota": (
            "FCM listo para registrar este navegador."
            if enabled
            else "Configure FIREBASE_WEB_CONFIG_JSON y FIREBASE_VAPID_PUBLIC_KEY para activar push real."
        ),
    }


def registrar_fcm_token(
    db: Session,
    usuario_id: int,
    token: str,
    plataforma: str | None = None,
    user_agent: str | None = None,
) -> FCMToken:
    """Guarda o reactiva el token FCM del navegador actual."""
    now = datetime.now(timezone.utc)
    item = db.query(FCMToken).filter(FCMToken.token == token).first()
    if item:
        item.usuario_id = usuario_id
        item.plataforma = plataforma
        item.user_agent = user_agent
        item.activo = True
        item.ultimo_error = None
        item.actualizado_en = now
    else:
        item = FCMToken(
            usuario_id=usuario_id,
            token=token,
            plataforma=plataforma,
            user_agent=user_agent,
            activo=True,
            registrado_en=now,
            actualizado_en=now,
        )
        db.add(item)
    db.commit()
    db.refresh(item)
    return item


def revocar_fcm_token(db: Session, usuario_id: int, token: str) -> bool:
    """Desactiva un token FCM del usuario actual."""
    item = (
        db.query(FCMToken)
        .filter(FCMToken.usuario_id == usuario_id, FCMToken.token == token)
        .first()
    )
    if not item:
        return False
    item.activo = False
    item.actualizado_en = datetime.now(timezone.utc)
    db.commit()
    return True


def _credencial_firebase():
    if not (settings.FIREBASE_SERVICE_ACCOUNT_JSON or settings.FIREBASE_SERVICE_ACCOUNT_FILE):
        return None
    try:
        from firebase_admin import credentials
    except ImportError:
        logger.warning("firebase-admin no está instalado; FCM backend deshabilitado")
        return None

    if settings.FIREBASE_SERVICE_ACCOUNT_JSON:
        try:
            data = json.loads(settings.FIREBASE_SERVICE_ACCOUNT_JSON)
        except json.JSONDecodeError:
            logger.warning("FIREBASE_SERVICE_ACCOUNT_JSON no es JSON válido")
            return None
        if isinstance(data, dict) and data.get("private_key"):
            data["private_key"] = data["private_key"].replace("\\n", "\n")
        return credentials.Certificate(data)
    return credentials.Certificate(settings.FIREBASE_SERVICE_ACCOUNT_FILE)


def _firebase_messaging():
    """Inicializa Firebase Admin de forma perezosa."""
    global _firebase_app, _firebase_init_failed
    if _firebase_init_failed:
        return None
    try:
        import firebase_admin
        from firebase_admin import messaging
    except ImportError:
        _firebase_init_failed = True
        logger.warning("firebase-admin no está instalado; FCM backend deshabilitado")
        return None

    if _firebase_app is None:
        cred = _credencial_firebase()
        if cred is None:
            return None
        try:
            _firebase_app = firebase_admin.initialize_app(cred, name="jacaranda-fcm")
        except ValueError:
            try:
                _firebase_app = firebase_admin.get_app("jacaranda-fcm")
            except ValueError:
                _firebase_init_failed = True
                logger.exception("No se pudo inicializar Firebase Admin")
                return None
        except Exception:
            _firebase_init_failed = True
            logger.exception("No se pudo inicializar Firebase Admin")
            return None
    return messaging


def _token_error_es_permanente(error_text: str) -> bool:
    lowered = (error_text or "").lower()
    return any(
        marker in lowered
        for marker in (
            "registration-token-not-registered",
            "requested entity was not found",
            "invalid-registration-token",
            "sender id mismatch",
        )
    )


def _chunks(items: list[FCMToken], size: int = 500):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def enviar_fcm_pedido_nuevo(pedido_data: dict) -> dict:
    """Envía push FCM a navegadores registrados para pedidos nuevos."""
    messaging = _firebase_messaging()
    if messaging is None:
        return {"enabled": False, "sent": 0, "failed": 0}

    db = SessionLocal()
    try:
        tokens = (
            db.query(FCMToken)
            .filter(FCMToken.activo.is_(True))
            .order_by(FCMToken.actualizado_en.desc())
            .all()
        )
        if not tokens:
            return {"enabled": True, "sent": 0, "failed": 0}

        folio = str(pedido_data.get("folio") or "nuevo pedido")
        cliente = str(pedido_data.get("cliente") or "Cliente")
        total = pedido_data.get("total")
        total_txt = f" · ${total}" if total not in (None, "") else ""
        body = f"{folio} · {cliente}{total_txt}"
        target = settings.FRONTEND_URL.rstrip("/") + "/#ped"
        sent = 0
        failed = 0
        now = datetime.now(timezone.utc)

        for token_group in _chunks(tokens):
            multicast = messaging.MulticastMessage(
                tokens=[item.token for item in token_group],
                notification=messaging.Notification(
                    title="Nuevo pedido Jacaranda",
                    body=body,
                ),
                data={
                    "tipo": "nuevo_pedido",
                    "pedido_id": str(pedido_data.get("pedido_id") or ""),
                    "folio": folio,
                    "url": target,
                },
                webpush=messaging.WebpushConfig(
                    fcm_options=messaging.WebpushFCMOptions(link=target),
                    notification=messaging.WebpushNotification(
                        icon=settings.FRONTEND_URL.rstrip("/") + "/favicon.svg",
                        badge=settings.FRONTEND_URL.rstrip("/") + "/favicon.svg",
                        tag="jacaranda-nuevo-pedido",
                        require_interaction=True,
                    ),
                ),
            )
            sender = getattr(messaging, "send_each_for_multicast", None) or messaging.send_multicast
            response = sender(multicast)
            for idx, resp in enumerate(response.responses):
                item = token_group[idx]
                item.ultimo_envio_en = now
                if resp.success:
                    sent += 1
                    item.ultimo_error = None
                else:
                    failed += 1
                    err = str(resp.exception or "Error FCM")
                    item.ultimo_error = err[:1000]
                    if _token_error_es_permanente(err):
                        item.activo = False
        db.commit()
        logger.info("FCM nuevo_pedido enviado: sent=%d failed=%d", sent, failed)
        return {"enabled": True, "sent": sent, "failed": failed}
    except Exception:
        logger.exception("Error enviando FCM nuevo_pedido")
        return {"enabled": True, "sent": 0, "failed": 0}
    finally:
        db.close()
