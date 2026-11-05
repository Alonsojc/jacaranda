"""Durable, private Web Push delivery for the isolated Uber TEST receiver."""

import base64
import binascii
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from uuid import uuid4

import requests
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from pywebpush import WebPushException, webpush
from sqlalchemy import and_, or_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.uber_eats import UberSandboxEvent, UberSandboxOrder
from app.models.uber_sandbox_push import SandboxPushDelivery, SandboxPushSubscription


MAX_DEVICES = 10
MAX_AGE_SECONDS = 15 * 60
MAX_ATTEMPTS = 5
LEASE_SECONDS = 60
TEST_SUBJECT = "https://uber-sandbox-webhook-uber-sandbox.up.railway.app"
ALERT_TYPES = {
    "orders.notification": "Nuevo pedido de prueba",
    "orders.scheduled.notification": "Pedido programado de prueba",
    "orders.cancel": "Cancelacion de pedido de prueba",
    "orders.failure": "Pedido de prueba por revisar",
    "orders.customer_order_edit": "Cambio en pedido de prueba",
    "orders.release": "Pedido de prueba disponible",
    "orders.fulfillment_issues.resolved": "Pedido de prueba actualizado",
    "order.fulfillment_issues.resolved": "Pedido de prueba actualizado",
}


class PushError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _decode(value: str, length: int) -> bytes:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("Invalid base64url value")
    try:
        result = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("Invalid base64url value") from None
    if len(result) != length:
        raise ValueError("Unexpected key length")
    return result


def _private_key():
    encoded = settings.UBER_EATS_SANDBOX_PUSH_VAPID_PRIVATE_KEY.get_secret_value()
    return ec.derive_private_key(int.from_bytes(_decode(encoded, 32), "big"), ec.SECP256R1())


def _storage():
    return Fernet(settings.UBER_EATS_SANDBOX_PUSH_STORAGE_KEY.get_secret_value().encode())


def validate_configuration() -> None:
    try:
        _private_key()
        _storage()
    except (ValueError, TypeError, UnicodeError):
        raise RuntimeError("Dedicated sandbox push keys are invalid or missing.") from None
    private_keys = [
        settings.UBER_EATS_SANDBOX_PUSH_VAPID_PRIVATE_KEY.get_secret_value(),
        settings.UBER_EATS_SANDBOX_PUSH_STORAGE_KEY.get_secret_value(),
    ]
    existing_keys = [
        settings.UBER_EATS_SANDBOX_ADMIN_TOKEN.get_secret_value(),
        settings.UBER_EATS_SANDBOX_CLIENT_SECRET.get_secret_value(),
        settings.UBER_EATS_SANDBOX_WEBHOOK_SECRET.get_secret_value(),
    ]
    if (not all(private_keys) or not all(existing_keys) or private_keys[0] == private_keys[1]
            or any(key in existing_keys for key in private_keys)):
        raise RuntimeError("Sandbox push requires independent private keys.")


def public_key() -> str:
    public = _private_key().public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(public).rstrip(b"=").decode("ascii")


def validate_endpoint(endpoint: str) -> str:
    if (not isinstance(endpoint, str) or len(endpoint) > 2048 or not endpoint.isascii()
            or any(ord(char) < 33 or ord(char) == 127 for char in endpoint)):
        raise PushError(422, "La direccion de notificaciones no es valida.")
    try:
        url = urlsplit(endpoint)
        host = (url.hostname or "").lower()
        allowed = host == "fcm.googleapis.com" or host.endswith(".push.apple.com")
        if (url.scheme != "https" or not allowed or url.username or url.password or url.port not in {None, 443}
                or not url.path.startswith("/") or url.path == "/" or url.fragment):
            raise ValueError()
    except (ValueError, UnicodeError):
        raise PushError(422, "La direccion de notificaciones no es valida.") from None
    return endpoint


def validate_subscription(value: dict) -> dict:
    try:
        endpoint = validate_endpoint(value["endpoint"])
        keys = value["keys"]
        public = _decode(keys["p256dh"], 65)
        _decode(keys["auth"], 16)
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), public)
    except (KeyError, TypeError, ValueError):
        raise PushError(422, "La suscripcion de notificaciones no es valida.") from None
    return {"endpoint": endpoint, "keys": {"p256dh": keys["p256dh"], "auth": keys["auth"]}}


def subscribe(db: Session, value: dict) -> None:
    value = validate_subscription(value)
    if db.bind.dialect.name == "postgresql":
        # Serialize the device cap and same-endpoint insert across replicas.
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": 0x4A4350555348})
    digest = hashlib.sha256(value["endpoint"].encode()).hexdigest()
    row = db.query(SandboxPushSubscription).filter_by(endpoint_hash=digest).with_for_update().first()
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    now = _now()
    if row is None:
        if db.query(SandboxPushSubscription).filter_by(active=True).count() >= MAX_DEVICES:
            raise PushError(409, "Se alcanzo el limite de dispositivos de prueba.")
        row = SandboxPushSubscription(endpoint_hash=digest, created_at=now)
        db.add(row)
    else:
        try:
            same = row.active and _storage().decrypt(row.subscription_encrypted.encode()) == encoded
        except (InvalidToken, ValueError):
            same = False
        if not same:
            row.created_at = now
    row.subscription_encrypted = _storage().encrypt(encoded).decode()
    row.active = True
    row.updated_at = now
    db.commit()


def unsubscribe(db: Session, endpoint: str) -> None:
    digest = hashlib.sha256(validate_endpoint(endpoint).encode()).hexdigest()
    row = db.query(SandboxPushSubscription).filter_by(endpoint_hash=digest).with_for_update().first()
    if row is not None:
        row.active = False
        row.subscription_encrypted = ""
        row.updated_at = _now()
        db.commit()


def subscription_status(db: Session, endpoint: str) -> dict:
    digest = hashlib.sha256(validate_endpoint(endpoint).encode()).hexdigest()
    row = db.query(SandboxPushSubscription).filter_by(endpoint_hash=digest).first()
    if row is None or not row.active:
        return {"activa": False, "ultimo_envio": None}
    last = db.query(SandboxPushDelivery).filter_by(subscription_id=row.id).order_by(
        SandboxPushDelivery.id.desc(),
    ).first()
    return {"activa": True, "ultimo_envio": last.state if last else None}


def enqueue(db: Session) -> int:
    """Scan durable verified receipts; a worker crash cannot lose the receipt."""
    cutoff = _now() - timedelta(seconds=MAX_AGE_SECONDS)
    created = 0
    devices = db.query(SandboxPushSubscription).filter_by(active=True).all()
    for device in devices:
        already = db.query(SandboxPushDelivery.id).filter(
            SandboxPushDelivery.subscription_id == device.id,
            SandboxPushDelivery.event_id == UberSandboxEvent.event_id,
        ).exists()
        events = db.query(UberSandboxEvent).filter(
            UberSandboxEvent.client_id == settings.UBER_EATS_SANDBOX_CLIENT_ID,
            UberSandboxEvent.store_id == settings.UBER_EATS_SANDBOX_STORE_ID,
            UberSandboxEvent.event_type.in_(ALERT_TYPES),
            UberSandboxEvent.recibido_en >= device.created_at,
            UberSandboxEvent.recibido_en >= cutoff,
            ~already,
        ).order_by(UberSandboxEvent.id).limit(20).all()
        for event in events:
            try:
                with db.begin_nested():
                    db.add(SandboxPushDelivery(
                        subscription_id=device.id, event_id=event.event_id, event_type=event.event_type,
                        received_at=event.recibido_en,
                    ))
                    db.flush()
                created += 1
            except IntegrityError:
                continue
    db.commit()
    return created


class _NoRedirectSession(requests.Session):
    def request(self, method, url, **kwargs):
        kwargs["allow_redirects"] = False
        return super().request(method, url, **kwargs)


def _send(subscription: dict, event_id: str, event_type: str, ttl: int = MAX_AGE_SECONDS) -> int:
    payload = json.dumps({
        "title": "Jacaranda Sandbox",
        "body": ALERT_TYPES[event_type] + ". Abre la app de pruebas.",
        "tag": "sandbox-" + event_id,
    }, separators=(",", ":"))
    with _NoRedirectSession() as session:
        response = webpush(
            subscription_info=subscription, data=payload,
            vapid_private_key=settings.UBER_EATS_SANDBOX_PUSH_VAPID_PRIVATE_KEY.get_secret_value(),
            vapid_claims={"sub": TEST_SUBJECT}, ttl=ttl, timeout=8,
            headers={"Urgency": "high", "Topic": hashlib.sha256(event_id.encode()).hexdigest()[:32]},
            requests_session=session,
        )
        return response.status_code


def deliver_one(db: Session) -> bool:
    now = _now()
    job = db.query(SandboxPushDelivery).filter(or_(
        and_(SandboxPushDelivery.state == "pending", SandboxPushDelivery.next_attempt_at <= now),
        and_(SandboxPushDelivery.state == "sending", SandboxPushDelivery.lease_until <= now),
    )).order_by(SandboxPushDelivery.id).with_for_update(skip_locked=True).first()
    if job is None:
        db.rollback()
        return False
    device = db.query(SandboxPushSubscription).filter_by(id=job.subscription_id).first()
    if not device or not device.active or _aware(job.received_at) < now - timedelta(seconds=MAX_AGE_SECONDS):
        job.state = "expired"
        db.commit()
        return True
    if job.event_type in {"orders.notification", "orders.scheduled.notification", "orders.release"}:
        event = db.query(UberSandboxEvent).filter_by(event_id=job.event_id).first()
        terminal = event and db.query(UberSandboxEvent.id).filter(
            UberSandboxEvent.client_id == event.client_id, UberSandboxEvent.store_id == event.store_id,
            UberSandboxEvent.order_id == event.order_id,
            UberSandboxEvent.event_type.in_({"orders.cancel", "orders.failure"}),
        ).first()
        order = event and db.query(UberSandboxOrder).filter_by(
            client_id=event.client_id, store_id=event.store_id, order_id=event.order_id,
        ).first()
        already_attended = order and (
            order.state in {"FAILED", "SUCCEEDED"}
            or (job.event_type in {"orders.notification", "orders.scheduled.notification"}
                and order.state in {"ACCEPTED", "HANDED_OFF"})
        )
        if not event or terminal or already_attended:
            job.state = "expired"
            db.commit()
            return True
    lease = str(uuid4())
    job.state = "sending"
    job.lease_id = lease
    job.lease_until = now + timedelta(seconds=LEASE_SECONDS)
    job.attempts += 1
    job_id, ciphertext, event_id, event_type = job.id, device.subscription_encrypted, job.event_id, job.event_type
    ttl = max(1, int((_aware(job.received_at) + timedelta(seconds=MAX_AGE_SECONDS) - now).total_seconds()))
    db.commit()
    status = None
    try:
        subscription = json.loads(_storage().decrypt(ciphertext.encode()))
        subscription = validate_subscription(subscription)
        status = _send(subscription, event_id, event_type, ttl)
    except WebPushException as exc:
        status = exc.response.status_code if exc.response is not None else None
    except (requests.RequestException, InvalidToken, ValueError, TypeError, PushError):
        status = None
    current = db.query(SandboxPushDelivery).filter_by(id=job_id, lease_id=lease, state="sending").with_for_update().first()
    if current is None:
        db.rollback()
        return True
    current.provider_status = status
    current.lease_id = None
    current.lease_until = None
    if status is not None and 200 <= status < 300:
        current.state = "sent"
    elif status in {404, 410}:
        current.state = "expired"
        device = db.query(SandboxPushSubscription).filter_by(id=current.subscription_id).with_for_update().first()
        if device:
            device.active = False
            device.subscription_encrypted = ""
            device.updated_at = _now()
    elif (status is None or status == 429 or status >= 500) and current.attempts < MAX_ATTEMPTS:
        current.state = "pending"
        current.next_attempt_at = _now() + timedelta(seconds=min(15 * 2 ** (current.attempts - 1), 120))
    else:
        current.state = "failed"
    db.commit()
    return True
