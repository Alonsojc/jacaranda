"""Verificacion e inbox sandbox; nunca sigue URLs ni crea ventas reales."""

import hashlib
import hmac
import json
import logging
import re
import time
from datetime import timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.uber_eats import UberSandboxEvent, UberSandboxStore, UberSandboxStoreJob

MAX_BODY_BYTES = 64 * 1024
MAX_EVENT_AGE_SECONDS = 24 * 60 * 60
logger = logging.getLogger(__name__)
EVENT_TYPES = frozenset({
    "orders.notification", "orders.scheduled.notification", "orders.failure",
    "orders.cancel", "orders.release", "orders.fulfillment_issues.resolved",
    "order.fulfillment_issues.resolved", "delivery.state_changed", "orders.customer_order_edit",
})
STORE_EVENT_TYPES = frozenset({
    "store.provisioned", "store.deprovisioned", "store.menu_refresh_request", "store.status.changed",
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


class _StoreWebhookMeta(BaseModel):
    model_config = ConfigDict(extra="ignore")
    client_id: str = Field(min_length=1, max_length=160)
    webhook_msg_timestamp: StrictInt
    webhook_msg_uuid: UUID


class _StoreEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")
    event_type: str = Field(max_length=80)
    store_id: UUID
    perform_refresh_menu: StrictBool = False
    webhook_meta: _StoreWebhookMeta


class _StoreStatusMeta(BaseModel):
    model_config = ConfigDict(extra="ignore")
    store_id: UUID


class _StoreStatusEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")
    event_id: UUID
    event_type: Literal["store.status.changed"]
    event_time: StrictInt
    meta: _StoreStatusMeta
    webhook_meta: _WebhookMeta | None = None


def store_state(db: Session, client_id: str, store_id: str, lock: bool = False) -> UberSandboxStore:
    query = db.query(UberSandboxStore).filter_by(client_id=client_id, store_id=store_id)
    row = (query.populate_existing().with_for_update() if lock else query).first()
    if row is None:
        try:
            with db.begin_nested():
                row = UberSandboxStore(client_id=client_id, store_id=store_id)
                db.add(row)
                db.flush()
        except IntegrityError:
            row = (query.populate_existing().with_for_update() if lock else query).one()
    return row


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
    secret = (
        settings.UBER_EATS_SANDBOX_WEBHOOK_SECRET.get_secret_value()
        or settings.UBER_EATS_SANDBOX_CLIENT_SECRET.get_secret_value()
    )
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


def _log_schema_mismatch(data: object, error: ValidationError) -> None:
    # Only fixed field names and types; never log provider values or error input.
    fields = {"event_id", "event_type", "event_time", "store_id", "meta", "webhook_meta",
              "user_id", "resource_id", "client_id", "webhook_msg_timestamp", "webhook_msg_uuid",
              "perform_refresh_menu", "status"}
    shape = {}
    if isinstance(data, dict):
        for parent, value in (("root", data), ("meta", data.get("meta")), ("webhook_meta", data.get("webhook_meta"))):
            if isinstance(value, dict):
                shape[parent] = {key: type(value[key]).__name__ for key in sorted(fields & value.keys())}
    errors = [{"field": ".".join(str(key) if key in fields else "?" for key in item["loc"]),
               "type": item["type"]} for item in error.errors(include_input=False, include_context=False, include_url=False)]
    logger.warning("Sandbox schema rejected shape=%s errors=%s", json.dumps(shape, sort_keys=True), json.dumps(errors))


def receive_event(db: Session, body: bytes, signature: str | None) -> bool:
    if not body or len(body) > MAX_BODY_BYTES:
        raise WebhookError(413 if body else 400, "Tamano de notificacion no permitido.")
    verify_signature(body, signature)
    client_id, store_id = sandbox_identity()
    try:
        data = json.loads(body, object_pairs_hook=_unique_keys)
        is_store = isinstance(data, dict) and data.get("event_type") in STORE_EVENT_TYPES
        if is_store and data["event_type"] == "store.status.changed" and "meta" in data:
            # Uber's status notifications use the order-style envelope but
            # identify the store in meta.store_id, without an order resource_id.
            event = _StoreStatusEvent.model_validate(data)
            incoming_store = str(event.meta.store_id)
            incoming_client = event.webhook_meta.client_id if event.webhook_meta else None
            event_id = str(event.event_id)
            event_time = event.event_time
            resource_id = incoming_store
            if "store_id" in data and data["store_id"] != incoming_store:
                raise WebhookError(403, "Identificadores de tienda contradictorios.")
        elif is_store:
            event = _StoreEvent.model_validate(data)
            incoming_store = str(event.store_id)
            incoming_client = event.webhook_meta.client_id
            event_id = str(event.webhook_meta.webhook_msg_uuid)
            event_time = event.webhook_meta.webhook_msg_timestamp
            resource_id = incoming_store
        else:
            event = _Event.model_validate(data)
            incoming_store = str(event.meta.user_id)
            incoming_client = event.webhook_meta.client_id if event.webhook_meta else None
            event_id = str(event.event_id)
            event_time = event.event_time
            resource_id = str(event.meta.resource_id)
    except ValidationError as exc:
        _log_schema_mismatch(data, exc)
        raise WebhookError(400, "Notificacion de Uber no valida.") from None
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise WebhookError(400, "Notificacion de Uber no valida.") from None
    if incoming_store != store_id:
        raise WebhookError(403, "El evento no corresponde a la tienda de pruebas.")
    if incoming_client not in {None, client_id}:
        raise WebhookError(403, "El evento no corresponde a la aplicacion de pruebas.")
    if event.event_type not in EVENT_TYPES | STORE_EVENT_TYPES:
        raise WebhookError(400, "Tipo de notificacion no soportado.")
    # Uber documents milliseconds in event_time; store canonical seconds.
    timestamp = event_time // 1000 if event_time >= 10**12 else event_time
    identity = {
        "event_id": event_id, "event_type": event.event_type,
        "event_time": timestamp, "store_id": store_id,
        "order_id": resource_id, "client_id": client_id,
    }
    if is_store:
        identity["perform_refresh_menu"] = getattr(event, "perform_refresh_menu", False)
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
            receipt = UberSandboxEvent(
                client_id=client_id, store_id=store_id, event_id=identity["event_id"],
                event_type=event.event_type, order_id=identity["order_id"],
                event_time=timestamp, fingerprint=fingerprint,
            )
            db.add(receipt)
            db.flush()
    except IntegrityError:
        existing = db.query(UberSandboxEvent).filter_by(client_id=client_id, event_id=identity["event_id"]).first()
        if existing is None:
            raise
        _same_event(existing, fingerprint)
        return False
    if is_store:
        row = store_state(db, client_id, store_id, lock=True)
        if event.event_type == "store.deprovisioned" and timestamp >= row.lifecycle_event_time:
            row.revoked = True
            row.integration_enabled = False
            row.lifecycle_event_time = timestamp
            row.revision += 1
        db.add(UberSandboxStoreJob(
            client_id=client_id, store_id=store_id, event_id=event_id,
            needs_menu=event.event_type == "store.menu_refresh_request" or identity["perform_refresh_menu"],
        ))
    db.commit()
    return True


def list_events(db: Session, limit: int = 30, before_id: int | None = None, store_events: bool = False) -> list[dict]:
    client_id, store_id = sandbox_identity()
    query = db.query(UberSandboxEvent).filter_by(client_id=client_id, store_id=store_id)
    query = query.filter(UberSandboxEvent.event_type.in_(STORE_EVENT_TYPES if store_events else EVENT_TYPES))
    if before_id is not None:
        query = query.filter(UberSandboxEvent.id < before_id)
    return [{
        "id": row.id, "event_id": row.event_id, "tipo": row.event_type,
        "pedido_id": row.order_id, "estado": row.estado,
        "recibido_en": row.recibido_en.replace(tzinfo=timezone.utc).isoformat() if row.recibido_en.tzinfo is None else row.recibido_en.isoformat(),
    } for row in query.order_by(UberSandboxEvent.id.desc()).limit(limit).all()]
