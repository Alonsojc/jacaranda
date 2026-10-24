"""Concurrency on an explicitly designated disposable PostgreSQL database."""

import hashlib
import hmac
import json
import os
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier, Event
from types import SimpleNamespace
from uuid import UUID, uuid4
from urllib.parse import urlparse

import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema

from app.core.config import settings
from app.models.uber_eats import UberSandboxEvent, UberSandboxOrder, UberSandboxAction
from app.services import uber_order_service as orders
from app.services import uber_webhook_service as inbox
from app.services import backup_service

STORE = "5d8714ab-07bc-4b7f-a0ee-5cbeb9c31594"
ORDER = "7871d55c-2460-484d-9f24-239416d1d2aa"


@pytest.fixture
def pg_sessions(monkeypatch):
    target = os.getenv("JACARANDA_TEST_POSTGRES_URL")
    if not target:
        pytest.skip("Explicit disposable PostgreSQL URL required")
    url = make_url(target)
    if url.host not in {"127.0.0.1", "localhost"} or url.database != "jacaranda_synthetic":
        pytest.fail("PostgreSQL test URL must name local jacaranda_synthetic, never an operational database")
    schema = "uber_test_" + uuid4().hex
    control = create_engine(url)
    with control.begin() as conn:
        conn.execute(CreateSchema(schema))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        for model in (UberSandboxEvent, UberSandboxOrder, UberSandboxAction):
            model.__table__.create(engine)
        monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_ENABLED", True)
        monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_WEBHOOK_ENABLED", True)
        monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_ACTIONS_ENABLED", True)
        monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_CLIENT_ID", "fictional-client")
        monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_STORE_ID", STORE)
        monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_CLIENT_SECRET", SecretStr("synthetic-pg-secret"))
        yield sessionmaker(bind=engine)
    finally:
        engine.dispose()
        with control.begin() as conn:
            conn.execute(DropSchema(schema, cascade=True))
        control.dispose()


def test_concurrent_signed_receipts_commit_only_one_identity(pg_sessions, monkeypatch):
    payload = {
        "event_id": str(uuid4()), "event_type": "orders.notification", "event_time": int(time.time()),
        "meta": {"user_id": STORE, "resource_id": ORDER},
    }
    raw = json.dumps(payload).encode()
    signature = hmac.new(b"synthetic-pg-secret", raw, hashlib.sha256).hexdigest()
    barrier = Barrier(2)
    timestamp = int(time.time())

    def simultaneous_time():
        barrier.wait(timeout=10)
        return timestamp

    monkeypatch.setattr(inbox, "time", SimpleNamespace(time=simultaneous_time))

    def receive():
        with pg_sessions() as db:
            return inbox.receive_event(db, raw, signature)

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: receive(), range(2)))
    assert sorted(results) == [False, True]
    with pg_sessions() as db:
        assert db.query(UberSandboxEvent).count() == 1


def test_concurrent_actions_and_fresh_sessions_cannot_send_twice(pg_sessions, monkeypatch):
    snapshot = json.dumps({"carts": [{"items": [{"id": "test", "title": "Fixture", "quantity": {"amount": 1}}]}]})
    digest = hashlib.sha256(snapshot.encode()).hexdigest()
    with pg_sessions() as db:
        db.add(UberSandboxOrder(
            client_id="fictional-client", store_id=STORE, order_id=ORDER, state="OFFERED",
            snapshot_json=snapshot, actualizado_en=datetime.now(timezone.utc),
        ))
        db.commit()
    started, release = Event(), Event()
    calls = []

    def network(method, order_id, payload=None, action=None):
        calls.append((method, order_id))
        started.set()
        assert release.wait(timeout=10)
        return {}

    monkeypatch.setattr(orders, "_request", network)

    def submit():
        with pg_sessions() as db:
            return orders.submit_action(db, UUID(ORDER), uuid4(), "aceptar", None, True, digest)

    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(submit)
        try:
            assert started.wait(timeout=10)
            second = workers.submit(submit)
            with pytest.raises(inbox.WebhookError, match="sin confirmar"):
                second.result(timeout=10)
        finally:
            release.set()
        assert first.result(timeout=10)["estado"] == "confirmada"
    assert len(calls) == 1
    with pg_sessions() as db:
        assert db.query(UberSandboxAction).count() == 1
        assert db.query(UberSandboxOrder).one().state == "ACCEPTED"


def test_concurrent_terminal_reads_reconcile_one_uncertain_cancellation(pg_sessions, monkeypatch):
    event_id, request_key = str(uuid4()), str(uuid4())
    created = datetime.now(timezone.utc) - timedelta(seconds=2)
    with pg_sessions() as db:
        db.add(UberSandboxOrder(
            client_id="fictional-client", store_id=STORE, order_id=ORDER, state="ACCEPTED",
            snapshot_json=json.dumps({"state": "ACCEPTED"}), pending_request_key=request_key,
            actualizado_en=created,
        ))
        db.add(UberSandboxAction(
            client_id="fictional-client", store_id=STORE, order_id=ORDER, request_key=request_key,
            fingerprint="0" * 64, action="cancelar", estado="incierta", creado_en=created,
        ))
        db.add(UberSandboxEvent(
            client_id="fictional-client", store_id=STORE, order_id=ORDER, event_id=event_id,
            event_type="orders.cancel", event_time=int(time.time()), fingerprint="1" * 64,
        ))
        db.commit()
    barrier = Barrier(2)
    calls = []

    def network(method, order_id, payload=None, action=None):
        calls.append(method)
        assert method == "GET"
        barrier.wait(timeout=10)
        return {"order": {"id": ORDER, "store": {"id": STORE}, "state": "FAILED", "status": "COMPLETED"}}

    monkeypatch.setattr(orders, "_request", network)

    def inspect_order():
        with pg_sessions() as db:
            return orders.inspect_order(db, UUID(event_id))

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: inspect_order(), range(2)))
    assert calls == ["GET", "GET"]
    assert all(result["pedido"]["state"] == "FAILED" for result in results)
    assert all(not result["requiere_conciliacion"] for result in results)
    with pg_sessions() as db:
        assert db.query(UberSandboxAction).one().estado == "conciliada"
        assert db.query(UberSandboxOrder).one().pending_request_key is None


def test_real_postgres_capture_restores_only_into_owned_synthetic_database(pg_sessions, monkeypatch, tmp_path):
    if not shutil.which("pg_dump") or not shutil.which("psql"):
        pytest.fail("PostgreSQL backup rehearsal requires pg_dump and psql")
    # pg_sessions has already enforced a loopback-only, explicitly synthetic target.
    url = make_url(os.environ["JACARANDA_TEST_POSTGRES_URL"])
    names = ["backup_test_" + uuid4().hex for _ in range(2)]
    control = create_engine(url, isolation_level="AUTOCOMMIT")
    created, engines = [], []
    try:
        with control.connect() as conn:
            for name in names:
                conn.execute(text(f'CREATE DATABASE "{name}"'))
                created.append(name)
        source_url, target_url = [url.set(database=name) for name in names]
        source, target = [create_engine(item) for item in (source_url, target_url)]
        engines.extend([source, target])
        with source.begin() as conn:
            conn.execute(text("CREATE TABLE backup_proof (id integer PRIMARY KEY, marker text NOT NULL)"))
            conn.execute(text("INSERT INTO backup_proof VALUES (1, :marker)"), {"marker": "synthetic-only"})
        monkeypatch.setattr(settings, "DATABASE_URL", source_url.render_as_string(hide_password=False))
        monkeypatch.setattr(settings, "BACKUP_DIR", str(tmp_path / "private-capture"))
        monkeypatch.setattr(settings, "BACKUP_AUTO_CLEANUP", False)
        captured = backup_service.crear_backup()
        with open(captured["path"], "rb") as stream:
            assert hashlib.file_digest(stream, "sha256").hexdigest() == captured["sha256"]
        parsed = urlparse(target_url.render_as_string(hide_password=False))
        result = subprocess.run([
            "psql", *backup_service._postgres_cmd_base(parsed), "--no-password", "--set=ON_ERROR_STOP=1", "-f", captured["path"],
        ], env=backup_service._postgres_env(parsed), capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, "Synthetic PostgreSQL restore failed"
        with target.connect() as conn:
            assert conn.execute(text("SELECT id, marker FROM backup_proof")).all() == [(1, "synthetic-only")]
        with source.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM backup_proof")).scalar_one() == 1
    finally:
        for engine in engines:
            engine.dispose()
        with control.connect() as conn:
            for name in created:
                conn.execute(text(f'DROP DATABASE "{name}"'))
        control.dispose()
