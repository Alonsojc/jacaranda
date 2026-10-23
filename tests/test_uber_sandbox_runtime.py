"""The public test receiver cannot start on the POS database or expose POS APIs."""

import hashlib
import hmac
import json
import time
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import uber_sandbox_runtime as runtime
from app.core.config import settings
from app.core.database import get_db
from app.models.uber_eats import UberSandboxEvent


SECRET = "synthetic-standalone-webhook-secret"
SANDBOX_DATABASE_URL = (
    "postgresql://jacaranda_sandbox:synthetic@uber-sandbox-db.railway.internal/"
    "jacaranda_uber_sandbox"
)


@pytest.fixture
def isolated(monkeypatch):
    monkeypatch.setenv("JACARANDA_RUNTIME", "uber-sandbox")
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "uber-sandbox")
    monkeypatch.setenv("JACARANDA_SANDBOX_DATABASE_HOST", "uber-sandbox-db.railway.internal")
    monkeypatch.setattr(settings, "DATABASE_URL", SANDBOX_DATABASE_URL)
    monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_ENABLED", True)
    monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_WEBHOOK_ENABLED", True)
    monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_ACTIONS_ENABLED", False)
    monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_CLIENT_ID", runtime.TEST_APPLICATION_ID)
    monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_STORE_ID", runtime.TEST_STORE_ID)
    monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_CLIENT_SECRET", SecretStr(""))
    monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_WEBHOOK_SECRET", SecretStr(SECRET))
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(runtime, "engine", engine)

    def get_session():
        with sessions() as db:
            yield db

    runtime.app.dependency_overrides[get_db] = get_session
    try:
        yield engine, sessions
    finally:
        runtime.app.dependency_overrides.clear()
        engine.dispose()


def test_bootstrap_and_restart_create_only_the_receipt_table(isolated):
    engine, _ = isolated
    for _ in range(2):
        with TestClient(runtime.app) as client:
            assert client.get("/health").json() == {
                "status": "ok", "environment": "uber-sandbox", "real_store_enabled": False,
            }
        assert inspect(engine).get_table_names() == ["uber_sandbox_events"]


@pytest.mark.parametrize("path", [
    "/api/v1/auth/login", "/api/v1/punto-de-venta/ventas", "/api/v1/clientes",
    "/api/v1/inventario/productos", "/api/v1/uber-eats/preparacion",
    "/api/v1/uber-eats/sandbox/eventos", "/docs", "/openapi.json",
])
def test_no_auth_business_catalog_or_admin_surface_is_published(isolated, path):
    with TestClient(runtime.app) as client:
        assert client.get(path).status_code == 404
        assert client.post(path, json={}).status_code == 404


@pytest.mark.parametrize("name,value", [
    ("JACARANDA_RUNTIME", ""), ("RAILWAY_ENVIRONMENT_NAME", "production"),
    ("JACARANDA_SANDBOX_DATABASE_HOST", "untrusted.example"),
])
def test_environment_guard_rejects_before_any_database_connection(isolated, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with patch.object(runtime.engine, "begin") as connect:
        with pytest.raises(RuntimeError):
            with TestClient(runtime.app):
                pass
        connect.assert_not_called()


@pytest.mark.parametrize("name,value", [
    ("UBER_EATS_SANDBOX_ENABLED", False),
    ("UBER_EATS_SANDBOX_WEBHOOK_ENABLED", False),
    ("UBER_EATS_SANDBOX_ACTIONS_ENABLED", True),
    ("UBER_EATS_SANDBOX_CLIENT_ID", "another-app"),
    ("UBER_EATS_SANDBOX_STORE_ID", "d757be8e-a500-5e80-a148-8e7182329641"),
    ("UBER_EATS_SANDBOX_WEBHOOK_SECRET", SecretStr("")),
    ("DATABASE_URL", "not-a-database-url"),
    ("DATABASE_URL", "sqlite:///./jacaranda.db"),
    ("DATABASE_URL", "postgresql://postgres:synthetic@postgres.railway.internal/railway"),
    ("DATABASE_URL", SANDBOX_DATABASE_URL.replace("jacaranda_uber_sandbox", "railway")),
    ("DATABASE_URL", SANDBOX_DATABASE_URL.replace("jacaranda_sandbox:", "postgres:")),
    ("DATABASE_URL", SANDBOX_DATABASE_URL.replace("uber-sandbox-db.railway.internal", "other.railway.internal")),
])
def test_settings_guard_rejects_before_any_database_connection(isolated, monkeypatch, name, value):
    monkeypatch.setattr(settings, name, value)
    with patch.object(runtime.engine, "begin") as connect:
        with pytest.raises(RuntimeError):
            with TestClient(runtime.app):
                pass
        connect.assert_not_called()


def test_existing_business_tables_are_not_modified(isolated):
    engine, _ = isolated
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE ventas (id integer PRIMARY KEY)"))
        connection.execute(text("INSERT INTO ventas VALUES (1)"))
    with pytest.raises(RuntimeError, match="non-sandbox"):
        with TestClient(runtime.app):
            pass
    with engine.connect() as connection:
        assert connection.execute(text("SELECT id FROM ventas")).all() == [(1,)]
    assert inspect(engine).get_table_names() == ["ventas"]


def test_public_signed_replay_is_durable_across_app_restarts(isolated):
    engine, sessions = isolated
    payload = {
        "event_id": str(uuid4()), "event_type": "orders.notification",
        "event_time": int(time.time()) * 1000,
        "meta": {"user_id": runtime.TEST_STORE_ID, "resource_id": str(uuid4())},
        "webhook_meta": {"client_id": runtime.TEST_APPLICATION_ID},
    }
    body = json.dumps(payload).encode()
    headers = {"X-Uber-Signature": hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()}
    with patch("httpx.Client") as provider:
        for _ in range(2):
            with TestClient(runtime.app) as client:
                assert client.post(runtime.WEBHOOK_PATH, content=body).status_code == 401
                response = client.post(runtime.WEBHOOK_PATH, content=body, headers=headers)
                assert response.status_code == 200 and response.content == b""
        provider.assert_not_called()
    with sessions() as db:
        assert db.query(UberSandboxEvent).count() == 1
    assert inspect(engine).get_table_names() == ["uber_sandbox_events"]


def test_storage_failure_does_not_report_ready(isolated):
    with TestClient(runtime.app) as client:
        with runtime.engine.begin() as connection:
            connection.execute(text("DROP TABLE uber_sandbox_events"))
        assert client.get("/health").status_code == 503
