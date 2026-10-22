"""Verificacion e inbox sandbox; nunca sigue URLs ni crea ventas reales."""

import hashlib
import hmac
import json
import re
import time
from datetime import timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.uber_eats import UberSandboxEvent

MAX_BODY_BYTES = 64 * 1024
MAX_EVENT_AGE_SECONDS = 24 * 60 * 60
EVENT_TYPES = frozenset({
    "orders.notification", "orders.scheduled.notification", "orders.failure",
    "orders.cancel", "orders.release", "orders.fulfillment_issues.resolved",
    "order.fulfillment_issues.resolved", "delivery.state_changed", "orders.customer_order_edit",
})


class WebhookError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


class _Meta(BaseModel):
    model_config = ConfigDict(extra="ignore")
    user_id: UUID
    resource_id: UUID


class _WebhookMeta(BaseModel):
    model_config = ConfigDict(extra="ignore")
    client_id: str | None = Field(default=None, max_length=160)


class _Event(BaseModel):
    model_config = ConfigDict(extra="ignore")
    event_id: UUID
    event_type: str = Field(max_length=80)
    event_time: StrictInt
    meta: _Meta
    webhook_meta: _WebhookMeta | None = None


def sandbox_identity() -> tuple[str, str]:
    client_id = settings.UBER_EATS_SANDBOX_CLIENT_ID.strip()
    try:
        store_id = str(UUID(settings.UBER_EATS_SANDBOX_STORE_ID.strip()))
    except (ValueError, AttributeError):
        raise WebhookError(503, "Falta configurar la tienda de pruebas.") from None
    if not settings.UBER_EATS_SANDBOX_ENABLED or not client_id or len(client_id) > 160:
        raise WebhookError(503, "La conexion de pruebas no esta habilitada.")
    return client_id, store_id


def verify_signature(body: bytes, signature: str | None) -> None:
    sandbox_identity()
    secret = settings.UBER_EATS_SANDBOX_CLIENT_SECRET.get_secret_value()
    if not settings.UBER_EATS_SANDBOX_WEBHOOK_ENABLED or not secret:
        raise WebhookError(503, "La recepcion de pruebas no esta habilitada.")
    if not signature or not re.fullmatch(r"[0-9a-f]{64}", signature):
        raise WebhookError(401, "Firma de Uber no valida.")
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise WebhookError(401, "Firma de Uber no valida.")


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _same_event(existing: UberSandboxEvent, fingerprint: str) -> None:
    if not hmac.compare_digest(existing.fingerprint, fingerprint):
        raise WebhookError(409, "La identidad del evento ya tiene otros datos.")


def receive_event(db: Session, body: bytes, signature: str | None) -> bool:
    if not body or len(body) > MAX_BODY_BYTES:
        raise WebhookError(413 if body else 400, "Tamano de notificacion no permitido.")
    verify_signature(body, signature)
    client_id, store_id = sandbox_identity()
    try:
        event = _Event.model_validate(json.loads(body, object_pairs_hook=_unique_keys))
    except (ValueError, ValidationError, UnicodeDecodeError, RecursionError):
        raise WebhookError(400, "Notificacion de Uber no valida.") from None
    if str(event.meta.user_id) != store_id:
        raise WebhookError(403, "El evento no corresponde a la tienda de pruebas.")
    if event.webhook_meta and event.webhook_meta.client_id not in {None, client_id}:
        raise WebhookError(403, "El evento no corresponde a la aplicacion de pruebas.")
    if event.event_type not in EVENT_TYPES:
        raise WebhookError(400, "Tipo de notificacion no soportado.")
    # Uber documents milliseconds in event_time; store canonical seconds.
    timestamp = event.event_time // 1000 if event.event_time >= 10**12 else event.event_time
    identity = {
        "event_id": str(event.event_id), "event_type": event.event_type,
        "event_time": timestamp, "store_id": store_id,
        "order_id": str(event.meta.resource_id), "client_id": client_id,
    }
    fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    existing = db.query(UberSandboxEvent).filter_by(client_id=client_id, event_id=identity["event_id"]).first()
    if existing:
        _same_event(existing, fingerprint)
        return False
    now = int(time.time())
    if timestamp < now - MAX_EVENT_AGE_SECONDS or timestamp > now + 300:
        raise WebhookError(400, "La fecha del evento esta fuera del intervalo permitido.")
    # A duplicate insert race must not undo a separately committed receipt.
    try:
        with db.begin_nested():
            db.add(UberSandboxEvent(
                client_id=client_id, store_id=store_id, event_id=identity["event_id"],
                event_type=event.event_type, order_id=identity["order_id"],
                event_time=timestamp, fingerprint=fingerprint,
            ))
            db.flush()
    except IntegrityError:
        existing = db.query(UberSandboxEvent).filter_by(client_id=client_id, event_id=identity["event_id"]).first()
        if existing is None:
            raise
        _same_event(existing, fingerprint)
        return False
    db.commit()
    return True


def list_events(db: Session, limit: int = 30, before_id: int | None = None) -> list[dict]:
    client_id, store_id = sandbox_identity()
    query = db.query(UberSandboxEvent).filter_by(client_id=client_id, store_id=store_id)
    if before_id is not None:
        query = query.filter(UberSandboxEvent.id < before_id)
    return [{
        "id": row.id, "event_id": row.event_id, "tipo": row.event_type,
        "pedido_id": row.order_id, "estado": row.estado,
        "recibido_en": row.recibido_en.replace(tzinfo=timezone.utc).isoformat() if row.recibido_en.tzinfo is None else row.recibido_en.isoformat(),
    } for row in query.order_by(UberSandboxEvent.id.desc()).limit(limit).all()]
