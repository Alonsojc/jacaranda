"""Standalone webhook receiver for the approved Jacaranda test store only."""

import hashlib
import hmac
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import inspect, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from app.api.routes.uber_eats import (
    inspect_sandbox_order,
    probar_conexion,
    receive_webhook,
    sandbox_events,
    sandbox_order_action,
)
from app.core.config import settings
from app.core.database import engine
from app.models.uber_eats import UberSandboxAction, UberSandboxEvent, UberSandboxOrder
from app.services import uber_eats_service


TEST_APPLICATION_ID = "I2pbZ-jD6Qa7FQzhLUbX3Y5gN12EasPL"
TEST_STORE_ID = "b412bb20-cf36-4ada-ba77-fdda96ce8a9e"
DATABASE_NAME = "jacaranda_uber_sandbox"
DATABASE_USER = "jacaranda_sandbox"
WEBHOOK_PATH = "/api/v1/uber-eats/sandbox/webhook"
ASSETS = Path(__file__).parent / "sandbox_static"
MODELS = (UberSandboxEvent, UberSandboxOrder, UberSandboxAction)


def validate_isolation() -> None:
    if os.environ.get("JACARANDA_RUNTIME") != "uber-sandbox":
        raise RuntimeError("The dedicated sandbox runtime must be explicitly selected.")
    if os.environ.get("RAILWAY_ENVIRONMENT_NAME") != "uber-sandbox":
        raise RuntimeError("Only the separate uber-sandbox environment is allowed.")
    if not settings.UBER_EATS_SANDBOX_ENABLED or not settings.UBER_EATS_SANDBOX_WEBHOOK_ENABLED:
        raise RuntimeError("Sandbox reception is not enabled.")
    if settings.UBER_EATS_SANDBOX_MANAGEMENT_ENABLED:
        token = settings.UBER_EATS_SANDBOX_ADMIN_TOKEN.get_secret_value()
        oauth_secret = settings.UBER_EATS_SANDBOX_CLIENT_SECRET.get_secret_value()
        if len(token) < 48 or not oauth_secret or token in {
            oauth_secret, settings.UBER_EATS_SANDBOX_WEBHOOK_SECRET.get_secret_value(),
        }:
            raise RuntimeError("Dedicated private management and TEST OAuth credentials are required.")
    elif settings.UBER_EATS_SANDBOX_ACTIONS_ENABLED:
        raise RuntimeError("Order actions require explicitly enabled private sandbox management.")
    if (
        uber_eats_service.API_URL != "https://test-api.uber.com"
        or uber_eats_service.TOKEN_URL != "https://sandbox-login.uber.com/oauth/v2/token"
    ):
        raise RuntimeError("Only Uber sandbox API and authentication domains are allowed.")
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
        allowed = {model.__tablename__ for model in MODELS}
        if tables - allowed:
            raise RuntimeError("Refusing a database containing non-sandbox tables.")
        models = MODELS if settings.UBER_EATS_SANDBOX_MANAGEMENT_ENABLED else (UberSandboxEvent,)
        for model in models:
            model.__table__.create(connection, checkfirst=True)
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


@app.middleware("http")
async def private_response_headers(request: Request, call_next):
    path = request.url.path
    protected = path in {"/sandbox/estado", "/api/v1/uber-eats/probar-conexion"} or (
        path.startswith("/api/v1/uber-eats/sandbox/") and path != WEBHOOK_PATH
    )
    try:
        # Reject unauthorized calls before FastAPI reads an action's JSON body.
        if protected:
            private_management(request)
        response = await call_next(request)
    except HTTPException as exc:
        response = JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    response.headers.update({
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Content-Security-Policy": (
            "default-src 'none'; script-src 'self'; style-src 'self'; "
            "img-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'self'"
        ),
    })
    return response


def management_enabled():
    if not settings.UBER_EATS_SANDBOX_MANAGEMENT_ENABLED:
        raise HTTPException(404, "Not found")
    validate_isolation()


def private_management(request: Request):
    management_enabled()
    expected = settings.UBER_EATS_SANDBOX_ADMIN_TOKEN.get_secret_value()
    provided = request.headers.getlist("authorization")
    # Compare fixed-length digests, never credentials in URLs, cookies or browser storage.
    candidate = provided[0][7:] if len(provided) == 1 and provided[0].startswith("Bearer ") else ""
    if not candidate or not hmac.compare_digest(
        hashlib.sha256(candidate.encode()).digest(), hashlib.sha256(expected.encode()).digest(),
    ):
        raise HTTPException(401, "Acceso privado de Sandbox requerido.")


@app.get("/", dependencies=[Depends(management_enabled)])
def dashboard():
    return FileResponse(ASSETS / "index.html")


@app.get("/sandbox.css", dependencies=[Depends(management_enabled)])
def stylesheet():
    return FileResponse(ASSETS / "sandbox.css", media_type="text/css")


@app.get("/sandbox.js", dependencies=[Depends(management_enabled)])
def script():
    return FileResponse(ASSETS / "sandbox.js", media_type="text/javascript")


@app.get("/favicon.svg", dependencies=[Depends(management_enabled)])
def favicon():
    return FileResponse(ASSETS / "favicon.svg", media_type="image/svg+xml")


@app.get("/sandbox/estado", dependencies=[Depends(private_management)])
def management_status():
    return {
        "entorno": "sandbox", "tienda": "Jacaranda Sandbox", "tienda_real_activada": False,
        "acciones_habilitadas": settings.UBER_EATS_SANDBOX_ACTIONS_ENABLED,
    }


for path, endpoint, method in (
    ("/api/v1/uber-eats/sandbox/eventos", sandbox_events, "GET"),
    ("/api/v1/uber-eats/sandbox/eventos/{event_id}/consultar", inspect_sandbox_order, "POST"),
    ("/api/v1/uber-eats/sandbox/pedidos/{order_id}/accion", sandbox_order_action, "POST"),
    ("/api/v1/uber-eats/probar-conexion", probar_conexion, "POST"),
):
    app.add_api_route(path, endpoint, methods=[method], dependencies=[Depends(private_management)])


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
