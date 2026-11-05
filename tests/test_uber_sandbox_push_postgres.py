"""Concurrency checks use only the explicitly disposable local PostgreSQL fixture."""

import base64
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier, Event
from uuid import uuid4

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import ec
from pydantic import SecretStr

from app.core.config import settings
from app.models.uber_eats import UberSandboxEvent
from app.models.uber_sandbox_push import SandboxPushDelivery, SandboxPushSubscription
from app.services import uber_sandbox_push as push
from tests.test_uber_postgres import ORDER, STORE, pg_sessions  # noqa: F401
from tests.test_uber_sandbox_push import subscription


def configure(pg_sessions, monkeypatch):
    key = ec.generate_private_key(ec.SECP256R1()).private_numbers().private_value.to_bytes(32, "big")
    monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_PUSH_ENABLED", True)
    monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_PUSH_VAPID_PRIVATE_KEY", SecretStr(base64.urlsafe_b64encode(key).rstrip(b"=").decode()))
    monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_PUSH_STORAGE_KEY", SecretStr(Fernet.generate_key().decode()))
    with pg_sessions() as db:
        SandboxPushSubscription.__table__.create(db.bind)
        SandboxPushDelivery.__table__.create(db.bind)


def test_concurrent_device_registration_respects_limit(pg_sessions, monkeypatch):
    configure(pg_sessions, monkeypatch)
    gate = Barrier(12)

    def register(number):
        gate.wait(timeout=10)
        with pg_sessions() as db:
            try:
                push.subscribe(db, subscription(f"https://web.push.apple.com/fake-{number}"))
                return True
            except push.PushError as exc:
                assert exc.status_code == 409
                return False

    with ThreadPoolExecutor(max_workers=12) as pool:
        assert sum(pool.map(register, range(12))) == 10
    with pg_sessions() as db:
        assert db.query(SandboxPushSubscription).filter_by(active=True).count() == 10


def test_concurrent_queue_and_sender_have_one_delivery_lease(pg_sessions, monkeypatch):
    configure(pg_sessions, monkeypatch)
    event_id = str(uuid4())
    with pg_sessions() as db:
        push.subscribe(db, subscription())
        db.add(UberSandboxEvent(client_id="fictional-client", store_id=STORE, order_id=ORDER,
                                event_id=event_id, event_type="orders.notification", event_time=int(time.time()),
                                fingerprint="0" * 64, recibido_en=datetime.now(timezone.utc)))
        db.commit()
    gate = Barrier(2)

    def queue():
        gate.wait(timeout=10)
        with pg_sessions() as db:
            return push.enqueue(db)

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(lambda _: queue(), range(2))) == 1
    entered, release = Event(), Event()
    calls = []

    def send(*args):
        calls.append(args[1])
        entered.set()
        assert release.wait(10)
        return 201

    monkeypatch.setattr(push, "_send", send)

    def deliver():
        with pg_sessions() as db:
            return push.deliver_one(db)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(deliver)
        try:
            assert entered.wait(5)
            assert pool.submit(deliver).result(timeout=5) is False
        finally:
            release.set()
        assert first.result(timeout=5) is True
    assert calls == [event_id]
    with pg_sessions() as db:
        assert db.query(SandboxPushDelivery).one().state == "sent"
