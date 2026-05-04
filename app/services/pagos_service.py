"""
Servicio de integración de pagos - Conekta.
En modo sandbox genera respuestas simuladas. En producción conecta a Conekta API.
"""

import base64
import binascii
import hashlib
import json
import secrets
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
    return settings.CONEKTA_SANDBOX_MODE or not settings.CONEKTA_API_KEY


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

    if pedido.total <= Decimal("0"):
        raise ValueError("El pedido no tiene total por cobrar")
    if pedido.pagado:
        raise ValueError("El pedido ya está marcado como pagado")
    if not _is_sandbox():
        raise ValueError(
            "Pagos Conekta en producción aún no están habilitados. "
            "Active CONEKTA_SANDBOX_MODE=true o implemente la llamada real a Conekta."
        )

    order_id = _sandbox_order_id()
    monto = pedido.total

    # Sandbox/manual: simulated response. Never present it as a real provider order.
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
            "modo": "sandbox_manual",
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


def _decimal_from_minor_units(value) -> Decimal | None:
    if value is None:
        return None
    try:
        return (Decimal(str(value)) / Decimal("100")).quantize(Decimal("0.01"))
    except Exception:
        return None


def _extract_order_amount(order_obj: dict) -> Decimal | None:
    """Extract a paid amount from common Conekta order payload shapes."""
    for key in ("amount", "amount_paid", "total"):
        amount = _decimal_from_minor_units(order_obj.get(key))
        if amount is not None:
            return amount

    charges = order_obj.get("charges", {})
    if isinstance(charges, dict):
        data = charges.get("data") or []
        for charge in data:
            if not isinstance(charge, dict):
                continue
            amount = _decimal_from_minor_units(charge.get("amount"))
            if amount is not None:
                return amount
    return None


def _extract_order_currency(order_obj: dict) -> str | None:
    currency = order_obj.get("currency")
    if currency:
        return str(currency).upper()
    charges = order_obj.get("charges", {})
    if isinstance(charges, dict):
        for charge in charges.get("data") or []:
            if isinstance(charge, dict) and charge.get("currency"):
                return str(charge["currency"]).upper()
    return None


def _validate_paid_payload(db: Session, evento: ConektaWebhookEvent, pago: PagoOnline, order_obj: dict) -> bool:
    payload_amount = _extract_order_amount(order_obj)
    payload_currency = _extract_order_currency(order_obj)

    if payload_amount is not None and payload_amount != pago.monto:
        evento.processed = False
        db.commit()
        return False
    if payload_currency is not None and payload_currency != (pago.moneda or "MXN").upper():
        evento.processed = False
        db.commit()
        return False
    if not _is_sandbox() and (payload_amount is None or payload_currency is None):
        evento.processed = False
        db.commit()
        return False
    return True


def webhook_conekta(db: Session, payload: dict) -> dict:
    """Procesa webhook de Conekta."""
    event_type = payload.get("type", "")
    order_obj = payload.get("data", {}).get("object", {})
    order_id = order_obj.get("id", "")
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
        if not _validate_paid_payload(db, evento, pago, order_obj):
            return {
                "processed": False,
                "duplicate": False,
                "order_id": order_id,
                "event": event_type,
                "reason": "amount_or_currency_mismatch",
            }
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
    if monto_reembolso <= Decimal("0"):
        raise ValueError("El monto de reembolso debe ser mayor a cero")
    if monto_reembolso > pago.monto:
        raise ValueError("Monto de reembolso excede el pago original")
    if not _is_sandbox():
        raise ValueError(
            "Reembolsos Conekta en producción aún no están habilitados. "
            "Use el panel/proveedor o implemente la llamada real antes de marcarlo en Jacaranda."
        )

    pago.estado = EstadoPago.REEMBOLSADO
    db.commit()

    return {
        "pago_id": pago.id,
        "order_id": pago.order_id_externo,
        "monto_reembolsado": float(monto_reembolso),
        "estado": "reembolsado",
        "sandbox": _is_sandbox(),
    }
