"""
Servicio de notificaciones en tiempo real via WebSocket.
Gestiona conexiones activas y despacho de mensajes a usuarios.
"""

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import WebSocket

from app.core.database import SessionLocal
from app.services.alertas_service import alertas_consolidadas

logger = logging.getLogger("jacaranda.notificaciones")


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


def generar_push_config() -> dict:
    """
    Retorna la configuración VAPID para push notifications del service worker.
    Stub: las claves VAPID reales deben configurarse en producción.
    """
    return {
        "vapid_public_key": "PLACEHOLDER_VAPID_PUBLIC_KEY_CONFIGURE_EN_PRODUCCION",
        "enabled": False,
        "nota": "Configure VAPID_PUBLIC_KEY y VAPID_PRIVATE_KEY en variables de entorno para habilitar push notifications.",
    }
