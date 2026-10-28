"""One-use merchant authorization, encrypted at rest, for the TEST store only."""

import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.uber_eats import UberSandboxStore
from app.services import uber_eats_service as api
from app.services import uber_store_service as stores
from app.services.uber_webhook_service import WebhookError, store_state

CALLBACK_URL = "https://uber-sandbox-webhook-uber-sandbox.up.railway.app/sandbox/oauth/callback"
AUTHORIZE_URL = "https://sandbox-login.uber.com/oauth/v2/authorize"


def _cipher() -> Fernet:
    secret = settings.UBER_EATS_SANDBOX_ADMIN_TOKEN.get_secret_value()
    if len(secret) < 48:
        raise WebhookError(503, "Falta la clave privada del entorno de pruebas.")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))


def begin(db: Session) -> dict:
    client_id, store_id = stores.identity()
    state = secrets.token_urlsafe(32)
    row = store_state(db, client_id, store_id, lock=True)
    row.oauth_state_hash = hashlib.sha256(state.encode()).hexdigest()
    row.oauth_state_expires = datetime.now(timezone.utc) + timedelta(minutes=10)
    db.commit()
    return {"entorno": "sandbox", "url": AUTHORIZE_URL + "?" + urlencode({
        "client_id": client_id, "response_type": "code", "redirect_uri": CALLBACK_URL,
        "scope": "eats.pos_provisioning", "state": state,
    })}


def complete(db: Session, code: str, state: str) -> None:
    client_id, store_id = stores.identity()
    if not code or len(code) > 4096 or not state or len(state) > 200:
        raise WebhookError(400, "Autorizacion de pruebas no valida.")
    digest = hashlib.sha256(state.encode()).hexdigest()
    row = store_state(db, client_id, store_id, lock=True)
    consumed = db.execute(update(UberSandboxStore).where(
        UberSandboxStore.id == row.id, UberSandboxStore.oauth_state_hash == digest,
        UberSandboxStore.oauth_state_expires > datetime.now(timezone.utc),
    ).values(oauth_state_hash=None, oauth_state_expires=None).execution_options(synchronize_session=False))
    if consumed.rowcount != 1:
        db.rollback()
        raise WebhookError(400, "Autorizacion vencida o ya utilizada. Inicia otra desde Sandbox.")
    db.commit()
    try:
        with httpx.Client(timeout=15, follow_redirects=False) as client:
            response = client.post(api.TOKEN_URL, data={
                "grant_type": "authorization_code", "client_id": client_id,
                "client_secret": settings.UBER_EATS_SANDBOX_CLIENT_SECRET.get_secret_value(),
                "redirect_uri": CALLBACK_URL, "code": code,
            })
            if len(response.content) > 64 * 1024 or response.status_code != 200:
                raise ValueError()
            data = response.json()
            token, expires = data.get("access_token"), data.get("expires_in")
            if not isinstance(token, str) or not token.strip() or len(token) > 32000 or type(expires) is not int or expires <= 0:
                raise ValueError()
            scope = data.get("scope", "")
            if not isinstance(scope, str) or "eats.pos_provisioning" not in scope.split():
                raise ValueError()
            # A merchant token is validated against the TEST host before it is retained.
            response = client.get(api.API_URL + "/v1/eats/stores", headers={"Authorization": "Bearer " + token})
            if response.status_code != 200 or len(response.content) > 2 * 1024 * 1024:
                raise ValueError()
            locations = response.json().get("stores")
            if not isinstance(locations, list) or not locations:
                raise ValueError()
            if any(not isinstance(item, dict) or item.get("id", item.get("store_id")) != store_id for item in locations):
                raise ValueError()
            row = store_state(db, client_id, store_id, lock=True)
            row.merchant_token_encrypted = _cipher().encrypt(token.encode()).decode()
            row.merchant_token_expires = datetime.now(timezone.utc) + timedelta(seconds=min(expires, 2592000))
            db.commit()
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        raise WebhookError(502, "Uber no confirmo la autorizacion exclusiva de la cuenta Sandbox.") from None


def merchant_token(db: Session) -> str:
    client_id, store_id = stores.identity()
    row = store_state(db, client_id, store_id)
    if (
        not row.merchant_token_encrypted or not row.merchant_token_expires
        or stores._utc(row.merchant_token_expires) <= datetime.now(timezone.utc)
    ):
        raise WebhookError(409, "Autoriza primero la cuenta de comerciante Sandbox.")
    try:
        return _cipher().decrypt(row.merchant_token_encrypted.encode()).decode()
    except (InvalidToken, ValueError, UnicodeDecodeError):
        raise WebhookError(409, "Vuelve a autorizar la cuenta Sandbox.") from None
