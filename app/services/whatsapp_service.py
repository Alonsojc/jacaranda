"""
Servicio de integración con WhatsApp Business API.
Procesa mensajes entrantes, crea pedidos, y envía respuestas automáticas.
"""

import logging
import re
from datetime import date, timedelta
from decimal import Decimal

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.inventario import Producto
from app.models.pedido import (
    DetallePedido,
    EstadoPedido,
    OrigenPedido,
    Pedido,
)
from app.services.pedido_service import _generar_folio_pedido

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

    # Comando: crear pedido (e.g. "pedido 2 conchas, 1 pastel chocolate")
    if texto_lower.startswith("pedido ") and len(texto_lower) > len("pedido "):
        return _crear_pedido_desde_mensaje(telefono, texto, db)

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


# ---------------------------------------------------------------------------
# Order creation via WhatsApp message
# ---------------------------------------------------------------------------

_CANTIDAD_PATTERN = re.compile(r"^\s*(\d+)\s+(.+)$")


def _parsear_items_pedido(texto_items: str) -> list[dict]:
    """Parse comma-separated items like '2 conchas, 1 pastel chocolate'.

    Returns a list of dicts with keys ``cantidad`` (int) and ``nombre`` (str).
    Items that cannot be parsed are silently skipped.
    """
    items: list[dict] = []
    for fragmento in texto_items.split(","):
        fragmento = fragmento.strip()
        if not fragmento:
            continue
        match = _CANTIDAD_PATTERN.match(fragmento)
        if match:
            items.append({
                "cantidad": int(match.group(1)),
                "nombre": match.group(2).strip(),
            })
        else:
            # Assume quantity = 1 when no number is given
            items.append({"cantidad": 1, "nombre": fragmento})
    return items


def _buscar_producto(nombre: str, db: Session) -> Producto | None:
    """Find a product by approximate name match (case-insensitive, contains)."""
    nombre_lower = nombre.lower().strip()

    # Try exact-ish match first (name equals, ignoring case)
    producto = db.query(Producto).filter(
        Producto.activo.is_(True),
        Producto.nombre.ilike(nombre_lower),
    ).first()
    if producto:
        return producto

    # Fallback: contains match
    producto = db.query(Producto).filter(
        Producto.activo.is_(True),
        Producto.nombre.ilike(f"%{nombre_lower}%"),
    ).first()
    return producto


def _crear_pedido_desde_mensaje(
    telefono: str, texto: str, db: Session,
) -> dict:
    """Create an order from a WhatsApp message like 'pedido 2 conchas, 1 pastel chocolate'."""
    # Strip the leading "pedido" keyword
    texto_items = texto.strip()
    texto_items = re.sub(r"^pedido\s+", "", texto_items, flags=re.IGNORECASE)

    items_parseados = _parsear_items_pedido(texto_items)
    if not items_parseados:
        _enviar_mensaje(
            telefono,
            (
                "No pude entender tu pedido. 😅\n\n"
                "Escribe *pedido* seguido de los productos, por ejemplo:\n"
                "_pedido 2 conchas, 1 pastel chocolate_"
            ),
        )
        return {"tipo": "pedido_error", "telefono": telefono, "error": "sin_items"}

    detalles: list[DetallePedido] = []
    no_encontrados: list[str] = []
    total = Decimal("0")

    for item in items_parseados:
        producto = _buscar_producto(item["nombre"], db)
        if not producto:
            no_encontrados.append(item["nombre"])
            continue

        cantidad = item["cantidad"]
        subtotal = producto.precio_unitario * cantidad
        total += subtotal

        detalles.append(
            DetallePedido(
                producto_id=producto.id,
                descripcion=producto.nombre,
                cantidad=cantidad,
                precio_unitario=producto.precio_unitario,
            )
        )

    if not detalles:
        nombres = ", ".join(no_encontrados)
        _enviar_mensaje(
            telefono,
            (
                f"No encontré estos productos: {nombres}.\n\n"
                "Escribe *catálogo* para ver los productos disponibles."
            ),
        )
        return {"tipo": "pedido_error", "telefono": telefono, "error": "productos_no_encontrados"}

    # Create the order
    folio = _generar_folio_pedido(db)
    pedido = Pedido(
        folio=folio,
        cliente_nombre=telefono,  # Best we have from a WhatsApp message
        cliente_telefono=telefono,
        fecha_entrega=date.today() + timedelta(days=1),
        estado=EstadoPedido.RECIBIDO,
        origen=OrigenPedido.WHATSAPP,
        total=total,
        detalles=detalles,
    )
    db.add(pedido)
    db.commit()
    db.refresh(pedido)

    # Build confirmation message
    msg = f"🌸 *Pedido recibido — {pedido.folio}*\n\n"
    for det in pedido.detalles:
        msg += f"• {det.cantidad}x {det.descripcion} — ${det.precio_unitario * det.cantidad}\n"
    msg += f"\n*Total: ${pedido.total}*\n"
    msg += f"Entrega estimada: {pedido.fecha_entrega.strftime('%d/%m/%Y')}\n\n"

    if no_encontrados:
        nombres = ", ".join(no_encontrados)
        msg += f"⚠️ No encontré: {nombres}. Puedes agregarlos después.\n\n"

    msg += "Te confirmaremos tu pedido pronto. ¡Gracias! 🙏"

    _enviar_mensaje(telefono, msg)
    logger.info("Pedido %s creado vía WhatsApp para %s — total $%s", folio, telefono, total)

    return {
        "tipo": "pedido_creado",
        "telefono": telefono,
        "pedido_folio": pedido.folio,
        "total": str(total),
        "items_no_encontrados": no_encontrados,
    }


# ---------------------------------------------------------------------------
# Delivery reminder
# ---------------------------------------------------------------------------

def enviar_recordatorio_entrega(db: Session, pedido: Pedido) -> bool:
    """Send a WhatsApp delivery reminder to the customer.

    Returns True if the message was dispatched, False if the order lacks a
    phone number or is in a terminal state.
    """
    if not pedido.cliente_telefono:
        logger.warning("Pedido %s sin teléfono, no se envía recordatorio", pedido.folio)
        return False

    if pedido.estado in (EstadoPedido.ENTREGADO, EstadoPedido.CANCELADO):
        logger.info("Pedido %s en estado %s, recordatorio omitido", pedido.folio, pedido.estado.value)
        return False

    fecha_str = pedido.fecha_entrega.strftime("%d/%m/%Y") if pedido.fecha_entrega else "por confirmar"
    hora_str = pedido.hora_entrega or "por confirmar"

    if pedido.estado == EstadoPedido.LISTO:
        msg = (
            f"🌸 *Jacaranda — Tu pedido está listo*\n\n"
            f"Pedido *{pedido.folio}* está listo para entrega/recolección.\n\n"
            f"📅 Fecha: {fecha_str}\n"
            f"🕐 Hora: {hora_str}\n"
        )
        if pedido.lugar_entrega:
            msg += f"📍 Lugar: {pedido.lugar_entrega}\n"
        if pedido.total and not pedido.pagado:
            msg += f"\n💰 Total pendiente: ${pedido.total}\n"
        msg += "\n¡Te esperamos! 🙏"
    else:
        msg = (
            f"🌸 *Jacaranda — Recordatorio de pedido*\n\n"
            f"Te recordamos que tu pedido *{pedido.folio}* está programado para:\n\n"
            f"📅 Fecha: {fecha_str}\n"
            f"🕐 Hora: {hora_str}\n"
        )
        if pedido.lugar_entrega:
            msg += f"📍 Lugar: {pedido.lugar_entrega}\n"
        if pedido.total and not pedido.pagado:
            msg += f"\n💰 Total pendiente: ${pedido.total}\n"
        msg += "\nEscribe *estado* para consultar el avance de tu pedido."

    _enviar_mensaje(pedido.cliente_telefono, msg)
    logger.info("Recordatorio de entrega enviado para pedido %s", pedido.folio)
    return True


# ---------------------------------------------------------------------------
# Order status change notification
# ---------------------------------------------------------------------------

_ESTADO_MENSAJES: dict[str, str] = {
    "confirmado": (
        "🌸 *Jacaranda — Pedido confirmado*\n\n"
        "Tu pedido *{folio}* ha sido *confirmado* ✅\n\n"
        "Fecha de entrega: {fecha}\n"
        "Total: ${total}\n\n"
        "Te avisaremos cuando esté en preparación."
    ),
    "en_preparacion": (
        "🌸 *Jacaranda — En preparación*\n\n"
        "¡Tu pedido *{folio}* ya se está preparando! 🍞\n\n"
        "Te notificaremos cuando esté listo."
    ),
    "listo": (
        "🌸 *Jacaranda — ¡Pedido listo!*\n\n"
        "Tu pedido *{folio}* está *listo* 🎉\n\n"
        "Fecha: {fecha}\n"
        "Hora: {hora}\n"
        "{lugar}"
        "{pago}"
        "\n¡Te esperamos!"
    ),
}


def notificar_cambio_estado(db: Session, pedido: Pedido) -> bool:
    """Send a WhatsApp notification when the order state changes.

    Notifications are sent for: confirmado, en_preparacion, listo.
    Returns True if a message was dispatched, False otherwise.
    """
    if not pedido.cliente_telefono:
        logger.warning("Pedido %s sin teléfono, no se envía notificación", pedido.folio)
        return False

    estado_valor = pedido.estado.value if hasattr(pedido.estado, "value") else str(pedido.estado)

    plantilla = _ESTADO_MENSAJES.get(estado_valor)
    if not plantilla:
        logger.debug("Sin plantilla de notificación para estado '%s'", estado_valor)
        return False

    fecha_str = pedido.fecha_entrega.strftime("%d/%m/%Y") if pedido.fecha_entrega else "por confirmar"
    hora_str = pedido.hora_entrega or "por confirmar"
    lugar_str = f"📍 Lugar: {pedido.lugar_entrega}\n" if pedido.lugar_entrega else ""
    pago_str = f"💰 Total pendiente: ${pedido.total}\n" if (pedido.total and not pedido.pagado) else ""

    msg = plantilla.format(
        folio=pedido.folio,
        fecha=fecha_str,
        hora=hora_str,
        total=pedido.total or "0.00",
        lugar=lugar_str,
        pago=pago_str,
    )

    _enviar_mensaje(pedido.cliente_telefono, msg)
    logger.info("Notificación de estado '%s' enviada para pedido %s", estado_valor, pedido.folio)
    return True
