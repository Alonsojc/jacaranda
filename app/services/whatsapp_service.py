"""
Servicio de integración con WhatsApp Business API.
Procesa mensajes entrantes, crea pedidos, y envía respuestas automáticas.
"""

import logging
from datetime import date, timedelta
from decimal import Decimal

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.inventario import Producto
from app.models.pedido import Pedido

logger = logging.getLogger("jacaranda.whatsapp")


def verificar_webhook(mode: str, token: str, challenge: str) -> str | None:
    """Verifica el webhook de WhatsApp Business (handshake GET)."""
    if mode == "subscribe" and token == settings.WA_VERIFY_TOKEN:
        return challenge
    return None


def procesar_webhook(payload: dict, db: Session) -> dict:
    """Procesa un mensaje entrante de WhatsApp Business API."""
    results = []

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            messages = value.get("messages", [])

            for msg in messages:
                telefono = msg.get("from", "")
                tipo = msg.get("type", "")
                texto = ""

                if tipo == "text":
                    texto = msg.get("text", {}).get("body", "")
                elif tipo == "interactive":
                    inter = msg.get("interactive", {})
                    if inter.get("type") == "button_reply":
                        texto = inter.get("button_reply", {}).get("id", "")
                    elif inter.get("type") == "list_reply":
                        texto = inter.get("list_reply", {}).get("id", "")

                if texto:
                    resp = _procesar_mensaje(telefono, texto, db)
                    results.append(resp)

    return {"processed": len(results), "results": results}


def _procesar_mensaje(telefono: str, texto: str, db: Session) -> dict:
    """Procesa un mensaje de texto y determina la respuesta."""
    texto_lower = texto.strip().lower()

    # Comando: catálogo
    if any(k in texto_lower for k in ["catalogo", "catálogo", "menu", "menú", "productos"]):
        catalogo = generar_catalogo(db)
        _enviar_mensaje(telefono, catalogo)
        return {"tipo": "catalogo", "telefono": telefono}

    # Comando: estado del pedido
    if any(k in texto_lower for k in ["estado", "pedido", "seguimiento"]):
        # Try to find recent order by phone
        pedido = db.query(Pedido).filter(
            Pedido.cliente_telefono.contains(telefono[-10:]),
            Pedido.estado.notin_(["entregado", "cancelado"]),
        ).order_by(Pedido.creado_en.desc()).first()

        if pedido:
            estado_nombre = {
                "recibido": "Recibido ✅",
                "confirmado": "Confirmado 📋",
                "en_preparacion": "En preparación 🍞",
                "listo": "¡Listo para recoger! 🎉",
            }
            msg = (
                f"🌸 *Pedido {pedido.folio}*\n\n"
                f"Estado: {estado_nombre.get(pedido.estado.value, pedido.estado.value)}\n"
                f"Entrega: {pedido.fecha_entrega.strftime('%d/%m/%Y') if pedido.fecha_entrega else 'Por confirmar'}\n"
            )
            if pedido.hora_entrega:
                msg += f"Hora: {pedido.hora_entrega}\n"
            if pedido.total:
                msg += f"Total: ${pedido.total}\n"
            _enviar_mensaje(telefono, msg)
            return {"tipo": "estado", "pedido_folio": pedido.folio}
        else:
            _enviar_mensaje(telefono, "No encontré pedidos activos con tu número. Escribe *pedido* para hacer uno nuevo.")
            return {"tipo": "estado", "pedido_folio": None}

    # Comando: horario
    if any(k in texto_lower for k in ["horario", "hora", "abierto", "abren"]):
        _enviar_mensaje(telefono, (
            "🌸 *Jacaranda - Horario*\n\n"
            "Lunes a Sábado: 7:00 AM - 9:00 PM\n"
            "Domingo: 8:00 AM - 3:00 PM\n\n"
            "📍 Visítanos o haz tu pedido aquí."
        ))
        return {"tipo": "horario", "telefono": telefono}

    # Default: saludo y opciones
    _enviar_mensaje(telefono, (
        "🌸 *¡Hola! Bienvenido a Jacaranda*\n\n"
        "¿En qué te puedo ayudar?\n\n"
        "📋 *Catálogo* — Ver nuestros productos\n"
        "📦 *Estado* — Consultar tu pedido\n"
        "🕐 *Horario* — Nuestros horarios\n"
        "🛒 *Pedido* — Hacer un pedido nuevo\n\n"
        "Escribe la opción que desees."
    ))
    return {"tipo": "saludo", "telefono": telefono}


def generar_catalogo(db: Session) -> str:
    """Genera texto del catálogo de productos disponibles."""
    productos = db.query(Producto).filter(
        Producto.activo.is_(True),
        Producto.stock_actual > 0,
    ).order_by(Producto.nombre).all()

    if not productos:
        return "🌸 *Jacaranda*\n\nEl catálogo se está actualizando. ¡Vuelve pronto!"

    msg = "🌸 *Jacaranda - Catálogo*\n\n"
    categoria_actual = None

    for p in productos:
        cat = p.categoria.nombre if p.categoria else "Otros"
        if cat != categoria_actual:
            msg += f"\n*{cat}*\n"
            categoria_actual = cat
        stock_info = f" ({int(p.stock_actual)} disp.)" if p.stock_actual <= 10 else ""
        msg += f"• {p.nombre} — ${p.precio_unitario}{stock_info}\n"

    msg += "\nPara pedir, escribe *pedido* seguido de lo que deseas."
    return msg


def generar_catalogo_json(db: Session) -> list[dict]:
    """Catálogo en formato JSON para compartir."""
    productos = db.query(Producto).filter(
        Producto.activo.is_(True),
    ).order_by(Producto.nombre).all()

    return [
        {
            "id": p.id,
            "nombre": p.nombre,
            "precio": float(p.precio_unitario),
            "categoria": p.categoria.nombre if p.categoria else "Otros",
            "disponible": float(p.stock_actual) > 0,
            "stock": float(p.stock_actual),
        }
        for p in productos
    ]


def _enviar_mensaje(telefono: str, texto: str):
    """Envía un mensaje de texto via WhatsApp Business API."""
    if not settings.WA_API_TOKEN or not settings.WA_PHONE_NUMBER_ID:
        logger.debug("WhatsApp API no configurada, mensaje no enviado a %s", telefono)
        return

    url = f"https://graph.facebook.com/v18.0/{settings.WA_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {settings.WA_API_TOKEN}",
        "Content-Type": "application/json",
    }
    body = {
        "messaging_product": "whatsapp",
        "to": telefono,
        "type": "text",
        "text": {"body": texto},
    }

    try:
        resp = httpx.post(url, json=body, headers=headers, timeout=10)
        if resp.status_code != 200:
            logger.warning("WhatsApp API error %s: %s", resp.status_code, resp.text)
    except Exception as e:
        logger.warning("Error enviando WhatsApp a %s: %s", telefono, e)
