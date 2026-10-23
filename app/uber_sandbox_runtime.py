"""Standalone webhook receiver for the approved Jacaranda test store only."""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from sqlalchemy import inspect, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from app.api.routes.uber_eats import receive_webhook
from app.core.config import settings
from app.core.database import engine
from app.models.uber_eats import UberSandboxEvent


TEST_APPLICATION_ID = "I2pbZ-jD6Qa7FQzhLUbX3Y5gN12EasPL"
TEST_STORE_ID = "b412bb20-cf36-4ada-ba77-fdda96ce8a9e"
DATABASE_NAME = "jacaranda_uber_sandbox"
DATABASE_USER = "jacaranda_sandbox"
WEBHOOK_PATH = "/api/v1/uber-eats/sandbox/webhook"


def validate_isolation() -> None:
    if os.environ.get("JACARANDA_RUNTIME") != "uber-sandbox":
        raise RuntimeError("The dedicated sandbox runtime must be explicitly selected.")
    if os.environ.get("RAILWAY_ENVIRONMENT_NAME") != "uber-sandbox":
        raise RuntimeError("Only the separate uber-sandbox environment is allowed.")
    if not settings.UBER_EATS_SANDBOX_ENABLED or not settings.UBER_EATS_SANDBOX_WEBHOOK_ENABLED:
        raise RuntimeError("Sandbox reception is not enabled.")
    if settings.UBER_EATS_SANDBOX_ACTIONS_ENABLED:
        raise RuntimeError("This receiver cannot enable order actions.")
    if (
        settings.UBER_EATS_SANDBOX_CLIENT_ID != TEST_APPLICATION_ID
        or settings.UBER_EATS_SANDBOX_STORE_ID != TEST_STORE_ID
        or not settings.UBER_EATS_SANDBOX_WEBHOOK_SECRET.get_secret_value()
    ):
        raise RuntimeError("The approved test application and store must be configured.")
    try:
        target = make_url(settings.DATABASE_URL)
    except Exception:
        raise RuntimeError("Invalid sandbox database configuration.") from None
    expected_host = os.environ.get("JACARANDA_SANDBOX_DATABASE_HOST", "")
    if (
        target.drivername != "postgresql"
        or not expected_host.endswith(".railway.internal")
        or target.host != expected_host
        or target.database != DATABASE_NAME
        or target.username != DATABASE_USER
    ):
        raise RuntimeError("A private, dedicated sandbox PostgreSQL database is required.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_isolation()
    # Never run the POS lifespan, migrations, seeds, or business background tasks.
    with engine.begin() as connection:
        tables = set(inspect(connection).get_table_names())
        if tables - {UberSandboxEvent.__tablename__}:
            raise RuntimeError("Refusing a database containing non-sandbox tables.")
        UberSandboxEvent.__table__.create(connection, checkfirst=True)
        connection.execute(select(UberSandboxEvent).limit(0))
    yield


app = FastAPI(
    title="Jacaranda Sandbox Webhook",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)
app.add_api_route(WEBHOOK_PATH, receive_webhook, methods=["POST"])


@app.get("/health")
def health():
    try:
        with engine.connect() as connection:
            connection.execute(select(UberSandboxEvent.id).limit(0))
    except SQLAlchemyError:
        raise HTTPException(503, "Sandbox storage is not ready.") from None
    return {"status": "ok", "environment": "uber-sandbox", "real_store_enabled": False}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.uber_sandbox_runtime:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        workers=1,
        access_log=False,
    )
