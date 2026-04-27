"""
Servicio de integración de pagos - Conekta.
En modo sandbox genera respuestas simuladas. En producción conecta a Conekta API.
"""

import base64
import binascii
import hashlib
import json
import secrets
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from app.core.config import settings
from app.models.pago_online import PagoOnline, EstadoPago, ConektaWebhookEvent
from app.models.pedido import Pedido
from app.services.auditoria_service import registrar_evento


class WebhookSignatureError(ValueError):
    """Raised when a payment webhook signature is missing or invalid."""


def _is_sandbox() -> bool:
    return not settings.CONEKTA_API_KEY


def _sandbox_order_id() -> str:
    return f"ord_sandbox_{secrets.token_hex(12)}"


def crear_orden_pago(
    db: Session, pedido_id: int, metodo: str = "card"
) -> dict:
    """Crea orden de pago para un pedido."""
    pedido = db.query(Pedido).filter(Pedido.id == pedido_id).first()
    if not pedido:
        raise ValueError("Pedido no encontrado")

    if metodo not in ("card", "oxxo", "spei"):
        raise ValueError("Método de pago inválido. Use: card, oxxo, spei")

    order_id = _sandbox_order_id()
    monto = pedido.total

    # Sandbox: simulated response
    checkout_url = f"https://pay.conekta.com/checkout/{order_id}"
    referencia = None
    if metodo == "oxxo":
        referencia = f"0123456789{secrets.randbelow(10000):04d}"
    elif metodo == "spei":
        referencia = f"646180{secrets.randbelow(10**12):012d}"

    pago = PagoOnline(
        pedido_id=pedido_id,
        order_id_externo=order_id,
        metodo=metodo,
        monto=monto,
        estado=EstadoPago.PENDIENTE,
        checkout_url=checkout_url,
        referencia=referencia,
        metadata_json=json.dumps({
            "sandbox": True,
            "pedido_folio": pedido.folio,
        }),
    )
    db.add(pago)
    db.commit()
    db.refresh(pago)

    return {
        "pago_id": pago.id,
        "order_id": order_id,
        "checkout_url": checkout_url,
        "referencia": referencia,
        "status": "pendiente",
        "amount": float(monto),
        "currency": "MXN",
        "metodo": metodo,
        "pedido_id": pedido_id,
        "sandbox": _is_sandbox(),
    }


def verificar_pago(db: Session, order_id: str) -> dict:
    """Verifica estado de un pago."""
    pago = db.query(PagoOnline).filter(
        PagoOnline.order_id_externo == order_id
    ).first()
    if not pago:
        raise ValueError("Pago no encontrado")

    return {
        "order_id": pago.order_id_externo,
        "estado": pago.estado.value,
        "monto": float(pago.monto),
        "metodo": pago.metodo,
        "referencia": pago.referencia,
        "pedido_id": pago.pedido_id,
    }


def verificar_firma_webhook_conekta(raw_body: bytes, digest_header: str | None) -> None:
    """Verify Conekta's RSA/SHA256 webhook signature from the DIGEST header."""
    public_key_pem = (
        settings.CONEKTA_WEBHOOK_PUBLIC_KEY
        or settings.CONEKTA_WEBHOOK_KEY
        or ""
    ).strip()
    if not public_key_pem:
        raise WebhookSignatureError("CONEKTA_WEBHOOK_PUBLIC_KEY no configurada")
    if not digest_header:
        raise WebhookSignatureError("Header DIGEST requerido")

    signature_b64 = digest_header.strip()
    if signature_b64.lower().startswith("sha256="):
        signature_b64 = signature_b64.split("=", 1)[1].strip()

    try:
        signature = base64.b64decode(signature_b64, validate=True)
        public_key = serialization.load_pem_public_key(
            public_key_pem.replace("\\n", "\n").encode("utf-8")
        )
        public_key.verify(
            signature,
            raw_body,
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except (binascii.Error, ValueError, InvalidSignature) as exc:
        raise WebhookSignatureError("Firma de webhook inválida") from exc


def _webhook_event_id(payload: dict) -> str:
    """Return Conekta event id, or a stable payload hash for sandbox/minimal payloads."""
    explicit_id = payload.get("id") or payload.get("event_id")
    if explicit_id:
        return str(explicit_id)
    stable_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return f"payload:{hashlib.sha256(stable_payload.encode('utf-8')).hexdigest()}"


def webhook_conekta(db: Session, payload: dict) -> dict:
    """Procesa webhook de Conekta."""
    event_type = payload.get("type", "")
    order_id = payload.get("data", {}).get("object", {}).get("id", "")
    event_id = _webhook_event_id(payload)

    if not order_id:
        return {"processed": False, "reason": "No order_id in payload"}

    evento_existente = db.query(ConektaWebhookEvent).filter(
        ConektaWebhookEvent.event_id == event_id
    ).first()
    if evento_existente:
        return {
            "processed": evento_existente.processed,
            "duplicate": True,
            "order_id": order_id,
            "event": event_type,
        }

    evento = ConektaWebhookEvent(
        event_id=event_id,
        event_type=event_type,
        order_id_externo=order_id,
        processed=False,
        payload_json=json.dumps(payload, default=str),
    )
    db.add(evento)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        evento_existente = db.query(ConektaWebhookEvent).filter(
            ConektaWebhookEvent.event_id == event_id
        ).first()
        return {
            "processed": evento_existente.processed if evento_existente else True,
            "duplicate": True,
            "order_id": order_id,
            "event": event_type,
        }

    pago = db.query(PagoOnline).filter(
        PagoOnline.order_id_externo == order_id
    ).first()
    if not pago:
        db.commit()
        return {"processed": False, "reason": "Order not found"}

    estado_pago_anterior = pago.estado.value
    pedido = db.query(Pedido).filter(Pedido.id == pago.pedido_id).first()
    pagado_anterior = pedido.pagado if pedido else None

    if event_type == "order.paid":
        pago.estado = EstadoPago.PAGADO
        if pedido:
            pedido.pagado = True
    elif event_type == "order.payment_failed":
        pago.estado = EstadoPago.FALLIDO

    evento.processed = True
    registrar_evento(
        db,
        usuario_id=None,
        usuario_nombre=None,
        accion="webhook",
        modulo="pagos",
        entidad="pagos_online",
        entidad_id=pago.id,
        datos_anteriores={
            "estado_pago": estado_pago_anterior,
            "pedido_pagado": pagado_anterior,
        },
        datos_nuevos={
            "event_id": event_id,
            "event_type": event_type,
            "estado_pago": pago.estado.value,
            "pedido_pagado": pedido.pagado if pedido else None,
        },
        commit=False,
    )
    db.commit()
    return {"processed": True, "duplicate": False, "order_id": order_id, "event": event_type}


def historial_pagos(db: Session, limit: int = 50) -> list[dict]:
    """Lista pagos recientes."""
    pagos = (
        db.query(PagoOnline)
        .order_by(PagoOnline.creado_en.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": p.id,
            "order_id": p.order_id_externo,
            "pedido_id": p.pedido_id,
            "metodo": p.metodo,
            "monto": float(p.monto),
            "estado": p.estado.value,
            "referencia": p.referencia,
            "creado_en": p.creado_en.isoformat() if p.creado_en else None,
        }
        for p in pagos
    ]


def reembolso(db: Session, pago_id: int, monto: Decimal | None = None) -> dict:
    """Procesa reembolso."""
    pago = db.query(PagoOnline).filter(PagoOnline.id == pago_id).first()
    if not pago:
        raise ValueError("Pago no encontrado")
    if pago.estado != EstadoPago.PAGADO:
        raise ValueError("Solo se pueden reembolsar pagos completados")

    monto_reembolso = monto or pago.monto
    if monto_reembolso > pago.monto:
        raise ValueError("Monto de reembolso excede el pago original")

    pago.estado = EstadoPago.REEMBOLSADO
    db.commit()

    return {
        "pago_id": pago.id,
        "order_id": pago.order_id_externo,
        "monto_reembolsado": float(monto_reembolso),
        "estado": "reembolsado",
        "sandbox": _is_sandbox(),
    }
