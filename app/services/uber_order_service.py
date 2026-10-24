"""Inspeccion y acciones manuales sandbox, aisladas del POS y del stock."""

import hashlib
import json
import logging
from datetime import datetime, timezone
from uuid import UUID

import httpx
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.uber_eats import UberSandboxAction, UberSandboxEvent, UberSandboxOrder, UberSandboxStore
from app.services import uber_eats_service as api
from app.services.uber_webhook_service import STORE_EVENT_TYPES, WebhookError, sandbox_identity

MAX_RESPONSE_BYTES = 512 * 1024
MAX_DETAILS_AGE_SECONDS = 120
_ACTIONS = {"aceptar": "accept", "rechazar": "deny", "cancelar": "cancel", "listo": "ready"}
_REASONS = {"ITEM_ISSUE", "STORE_CLOSED", "POS_NOT_READY", "SPECIAL_INSTRUCTIONS", "TECHNICAL_FAILURE", "OTHER"}
_ERROR_CODES = {"bad_request", "unauthorized", "forbidden", "not_found", "not_implemented", "internal_server_error", "rate_limited"}
logger = logging.getLogger(__name__)


class SandboxRequestError(Exception):
    def __init__(self, uncertain: bool, status_code: int | None = None):
        self.uncertain = uncertain
        self.status_code = status_code
        super().__init__("No se pudo confirmar la operacion de pruebas con Uber.")


def _request(method: str, order_id: str, payload: dict | None = None, action: str | None = None) -> dict:
    if api.API_URL != "https://test-api.uber.com" or api.TOKEN_URL != "https://sandbox-login.uber.com/oauth/v2/token":
        raise SandboxRequestError(False)
    # The webhook's resource_href is never used, even if correctly signed.
    path = f"/v1/delivery/order/{UUID(order_id)}"
    if action:
        path += "/" + _ACTIONS[action]
    try:
        with httpx.Client(timeout=15, follow_redirects=False) as client:
            try:
                token = api._access_token(client, "eats.order")
            except (api.UberEatsError, httpx.HTTPError):
                raise SandboxRequestError(False) from None
            try:
                with client.stream(
                    method, api.API_URL + path,
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                    params={"expand": "carts"} if method == "GET" else None,
                    json=payload if method == "POST" else None,
                ) as response:
                    if response.status_code == 401:
                        with api._token_lock:
                            api._order_token_cache = None
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                            raise SandboxRequestError(method == "POST", response.status_code)
                        body.extend(chunk)
                    try:
                        data = json.loads(body) if body else {}
                    except (ValueError, UnicodeDecodeError, RecursionError):
                        data = None
                    code = data.get("code") if isinstance(data, dict) else None
                    code = code if isinstance(code, str) and code in _ERROR_CODES else None
                    fields = sorted({"order", "code", "error", "errors", "status", "message", "metadata"}.intersection(data)) if isinstance(data, dict) else []
                    try:
                        request_id = str(UUID(response.headers.get("x-uber-request-id", "")))
                    except (ValueError, TypeError, AttributeError):
                        request_id = "-"
                    # Do not log response text, credentials, contacts, or arbitrary provider fields.
                    logger.info(
                        "Uber sandbox response method=%s action=%s http=%s bytes=%s code=%s request_id=%s fields=%s",
                        method, action or "consultar", response.status_code, len(body), code or "-", request_id, ",".join(fields) or "-",
                    )
                    expected = 204 if action == "cancelar" else 200
                    if response.status_code != expected:
                        raise SandboxRequestError(
                            method == "POST" and not 400 <= response.status_code < 500,
                            response.status_code,
                        )
                    if method == "POST":
                        if code is not None:
                            raise SandboxRequestError(True, response.status_code)
                        return {}
                    if not isinstance(data, dict):
                        raise SandboxRequestError(False)
                    return data
            except httpx.HTTPError:
                raise SandboxRequestError(method == "POST") from None
    except httpx.HTTPError:
        raise SandboxRequestError(False) from None


def _order_query(db: Session, client_id: str, store_id: str, order_id: str):
    return db.query(UberSandboxOrder).filter_by(client_id=client_id, store_id=store_id, order_id=order_id)


def inspect_order(db: Session, event_id: UUID) -> dict:
    client_id, store_id = sandbox_identity()
    if not settings.UBER_EATS_SANDBOX_CLIENT_SECRET.get_secret_value():
        raise WebhookError(503, "Falta la credencial privada de pruebas.")
    event = db.query(UberSandboxEvent).filter_by(
        client_id=client_id, store_id=store_id, event_id=str(event_id),
    ).first()
    if event is None:
        raise WebhookError(404, "Notificacion de pruebas no encontrada.")
    if event.event_type in STORE_EVENT_TYPES:
        raise WebhookError(409, "Esta notificacion corresponde a la tienda, no a un pedido.")
    query = _order_query(db, client_id, store_id, event.order_id)
    before = query.first()
    before_revision = before.revision if before else None
    try:
        data = _request("GET", event.order_id)
    except SandboxRequestError:
        raise WebhookError(502, "No se pudo consultar el pedido de pruebas. Intenta de nuevo.") from None
    order = data.get("order")
    if not isinstance(order, dict) or not isinstance(order.get("store"), dict):
        raise WebhookError(502, "Uber no confirmo la identidad del pedido.")
    try:
        matches = str(UUID(order.get("id"))) == event.order_id and str(UUID(order["store"].get("id"))) == store_id
    except (ValueError, TypeError, AttributeError):
        matches = False
    if not matches:
        raise WebhookError(502, "Uber no confirmo la identidad del pedido.")
    if not isinstance(order.get("state"), str) or len(order["state"]) > 40:
        raise WebhookError(502, "Uber no confirmo el estado del pedido.")
    # Omit customers, addresses, phone numbers, payment credentials and support contacts.
    snapshot = {key: order[key] for key in (
        "id", "display_id", "state", "status", "carts", "store_instructions",
    ) if key in order}
    encoded = json.dumps(snapshot, ensure_ascii=True)
    row = query.populate_existing().with_for_update().first()
    created = False
    if row is None:
        try:
            with db.begin_nested():
                row = UberSandboxOrder(
                    client_id=client_id, store_id=store_id, order_id=event.order_id,
                    state=order["state"], snapshot_json=encoded,
                    actualizado_en=datetime.now(timezone.utc),
                )
                db.add(row)
                db.flush()
                created = True
        except IntegrityError:
            row = query.populate_existing().with_for_update().one()
    pending = db.query(UberSandboxAction).filter_by(
        client_id=client_id, store_id=store_id, order_id=event.order_id,
    ).filter(UberSandboxAction.estado.in_(["enviando", "incierta"])).first()
    rank = {"CREATED": 0, "OFFERED": 0, "ACCEPTED": 1, "HANDED_OFF": 2, "SUCCEEDED": 3, "FAILED": 3}
    regresses = rank.get(order["state"], -1) < rank.get(row.state, -1) or (
        row.state in {"FAILED", "SUCCEEDED"} and row.state != order["state"]
    )
    changed = not created and row.revision != before_revision
    reconciles = False
    if (
        pending is not None and pending.estado == "incierta" and pending.action == "cancelar"
        and row.pending_request_key == pending.request_key and order["state"] == "FAILED"
    ):
        # A late terminal GET plus a signed cancellation can resolve an uncertain
        # request without treating its HTTP acknowledgement as confirmation.
        created_at = pending.creado_en.replace(tzinfo=timezone.utc) if pending.creado_en.tzinfo is None else pending.creado_en
        reconciles = db.query(UberSandboxEvent.id).filter_by(
            client_id=client_id, store_id=store_id, order_id=event.order_id, event_type="orders.cancel",
        ).filter(
            UberSandboxEvent.recibido_en >= created_at,
            UberSandboxEvent.event_time >= int(created_at.timestamp()),
        ).first() is not None
    if (pending is None or reconciles) and not changed and not regresses:
        values = {
            "state": order["state"], "snapshot_json": encoded,
            "actualizado_en": datetime.now(timezone.utc), "revision": UberSandboxOrder.revision + 1,
        }
        if reconciles:
            values["pending_request_key"] = None
        # SQLite ignores FOR UPDATE; the version predicate must protect this write too.
        refreshed = db.execute(update(UberSandboxOrder).where(
            UberSandboxOrder.id == row.id,
            UberSandboxOrder.revision == row.revision,
            UberSandboxOrder.pending_request_key == pending.request_key if reconciles else
            UberSandboxOrder.pending_request_key.is_(None),
        ).values(**values).execution_options(synchronize_session=False))
        changed = refreshed.rowcount != 1
        if reconciles and not changed:
            pending.estado = "conciliada"
            pending = None
    db.refresh(row)
    snapshot = json.loads(row.snapshot_json)
    snapshot["state"] = row.state
    snapshot_digest = hashlib.sha256(row.snapshot_json.encode()).hexdigest()
    event.estado = "consultado"
    db.commit()
    return {
        "entorno": "sandbox", "pedido": snapshot,
        "acciones_habilitadas": settings.UBER_EATS_SANDBOX_ACTIONS_ENABLED and pending is None and not changed and not regresses,
        "requiere_conciliacion": pending is not None or regresses,
        "estado_remoto": order["state"],
        "detalle_sha256": snapshot_digest,
        "listo_confirmado": db.query(UberSandboxAction.id).filter_by(
            client_id=client_id, store_id=store_id, order_id=event.order_id, action="listo", estado="confirmada",
        ).first() is not None,
    }


def submit_action(
    db: Session, order_id: UUID, request_key: UUID, action: str,
    reason: str | None, instructions_reviewed: bool, details_digest: str,
) -> dict:
    client_id, store_id = sandbox_identity()
    if not settings.UBER_EATS_SANDBOX_CLIENT_SECRET.get_secret_value():
        raise WebhookError(503, "Falta la credencial privada de pruebas.")
    if not settings.UBER_EATS_SANDBOX_ACTIONS_ENABLED:
        raise WebhookError(409, "Las acciones de pruebas estan deshabilitadas.")
    if settings.UBER_EATS_SANDBOX_STORE_AUTOMATION_ENABLED:
        store = db.query(UberSandboxStore).filter_by(client_id=client_id, store_id=store_id).populate_existing().with_for_update().first()
        if store and store.revoked:
            raise WebhookError(409, "La integracion de la tienda esta revocada.")
    if action not in _ACTIONS or (action in {"rechazar", "cancelar"} and reason not in _REASONS):
        raise WebhookError(422, "Accion o motivo no permitido.")
    if action in {"aceptar", "listo"} and not instructions_reviewed:
        raise WebhookError(422, "Confirma la revision del pedido y sus instrucciones.")
    identity = {"order_id": str(order_id), "action": action, "reason": reason,
                "reviewed": instructions_reviewed, "details_digest": details_digest}
    fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    row = _order_query(db, client_id, store_id, str(order_id)).with_for_update().first()
    if row is None:
        raise WebhookError(409, "Consulta primero el pedido de pruebas.")
    actions = db.query(UberSandboxAction).filter_by(client_id=client_id, store_id=store_id)
    existing = actions.filter_by(request_key=str(request_key)).first()
    if existing:
        if existing.fingerprint != fingerprint:
            raise WebhookError(409, "La clave de la operacion ya tiene otros datos.")
        if existing.estado in {"confirmada", "conciliada"}:
            return {"entorno": "sandbox", "estado": existing.estado, "repetida": True}
        raise WebhookError(409, "Operacion registrada. Revisa su resultado antes de volver a enviarla.")
    if actions.filter_by(order_id=str(order_id)).filter(
        UberSandboxAction.estado.in_(["enviando", "incierta"])
    ).first():
        raise WebhookError(409, "Hay una operacion sin confirmar; no se reenviara automaticamente.")
    if action == "listo" and actions.filter_by(order_id=str(order_id), action="listo", estado="confirmada").first():
        raise WebhookError(409, "El pedido ya fue marcado como listo.")
    if hashlib.sha256(row.snapshot_json.encode()).hexdigest() != details_digest:
        raise WebhookError(409, "El detalle cambio. Revisa de nuevo productos e instrucciones.")
    seen = row.actualizado_en.replace(tzinfo=timezone.utc) if row.actualizado_en.tzinfo is None else row.actualizado_en
    if (datetime.now(timezone.utc) - seen).total_seconds() > MAX_DETAILS_AGE_SECONDS:
        raise WebhookError(409, "Actualiza el pedido antes de enviar una accion.")
    expected_states = {"aceptar": {"OFFERED", "CREATED"}, "rechazar": {"OFFERED", "CREATED"},
                       "cancelar": {"ACCEPTED"}, "listo": {"ACCEPTED"}}
    if row.state not in expected_states[action]:
        raise WebhookError(409, "El estado del pedido no permite esa accion.")
    snapshot = json.loads(row.snapshot_json)
    if action == "aceptar":
        carts = snapshot.get("carts")
        if not isinstance(carts, list) or not carts or not all(
            isinstance(cart, dict) and isinstance(cart.get("items"), list) and cart["items"]
            and all(isinstance(item, dict) and item.get("id") and item.get("title") and item.get("quantity")
                    for item in cart["items"]) for cart in carts
        ):
            raise WebhookError(409, "El pedido no tiene un detalle completo para revision.")
    reserved = db.execute(update(UberSandboxOrder).where(
        UberSandboxOrder.id == row.id,
        UberSandboxOrder.pending_request_key.is_(None),
        UberSandboxOrder.state.in_(expected_states[action]),
        UberSandboxOrder.revision == row.revision,
    ).values(pending_request_key=str(request_key), revision=UberSandboxOrder.revision + 1))
    if reserved.rowcount != 1:
        db.rollback()
        raise WebhookError(409, "El pedido ya tiene una operacion en curso.")
    command = UberSandboxAction(
        client_id=client_id, store_id=store_id, order_id=str(order_id), request_key=str(request_key),
        fingerprint=fingerprint, action=action, estado="enviando", creado_en=datetime.now(timezone.utc),
    )
    db.add(command)
    # Persist before crossing the network boundary. A crash must block blind resends.
    db.commit()
    payload = {} if action == "listo" else {"external_reference_id": "jacaranda-sandbox-" + str(request_key)} if action == "aceptar" else {
        "deny_reason" if action == "rechazar" else "cancellation_reason": {
            "type": reason, "info": "Jacaranda Sandbox UBER_TEST integration validation.",
        },
    }
    try:
        _request("POST", str(order_id), payload, action)
    except SandboxRequestError as exc:
        command.estado = "incierta" if exc.uncertain else "rechazada"
        if not exc.uncertain:
            row.pending_request_key = None
        row.revision += 1
        db.commit()
        status = f" (HTTP {exc.status_code})" if exc.status_code is not None else ""
        raise WebhookError(502, f"Uber no confirmo la accion{status}. No se ha reenviado.") from None
    command.estado = "confirmada"
    row.state = "ACCEPTED" if action in {"aceptar", "listo"} else "FAILED"
    row.pending_request_key = None
    row.revision += 1
    row.actualizado_en = datetime.now(timezone.utc)
    db.commit()
    return {"entorno": "sandbox", "estado": "confirmada", "repetida": False}
