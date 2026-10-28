"""Inspeccion y acciones manuales sandbox, aisladas del POS y del stock."""

import hashlib
import json
import logging
from datetime import datetime, timezone
from uuid import UUID

import httpx
from sqlalchemy import and_, case, func, or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.core.config import settings
from app.models.uber_eats import PENDING_ORDER_ACTION_STATES, UberSandboxAction, UberSandboxEvent, UberSandboxOrder, UberSandboxOrderCheck, UberSandboxStore
from app.services import uber_eats_service as api
from app.services.uber_webhook_service import (
    STORE_EVENT_TYPES, TERMINAL_ORDER_EVENT_TYPES, WebhookError,
    apply_terminal_order_notice, sandbox_identity, terminal_order_notice,
)

MAX_RESPONSE_BYTES = 512 * 1024
MAX_DETAILS_AGE_SECONDS = 120
_ACTIONS = {"aceptar": "accept", "rechazar": "deny", "cancelar": "cancel", "listo": "ready"}
_REASONS = {"ITEM_ISSUE", "STORE_CLOSED", "POS_NOT_READY", "SPECIAL_INSTRUCTIONS", "TECHNICAL_FAILURE", "OTHER"}
_ERROR_CODES = {"bad_request", "unauthorized", "forbidden", "not_found", "not_implemented", "internal_server_error", "rate_limited"}
_ORDER_CHANGES = frozenset({"orders.cancel", "orders.failure", "orders.customer_order_edit",
                            "orders.fulfillment_issues.resolved", "order.fulfillment_issues.resolved"})
logger = logging.getLogger(__name__)


class SandboxRequestError(Exception):
    def __init__(self, uncertain: bool, status_code: int | None = None):
        self.uncertain = uncertain
        self.status_code = status_code
        super().__init__("No se pudo confirmar la operacion de pruebas con Uber.")


def _request(method: str, order_id: str, payload: dict | None = None, action: str | None = None,
             *, include_payment: bool = False) -> dict:
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
                    params={"expand": "carts,payment" if include_payment else "carts"} if method == "GET" else None,
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
                    if response.status_code != 200:
                        raise SandboxRequestError(
                            method == "POST" and not 400 <= response.status_code < 500,
                            response.status_code,
                        )
                    if method == "POST":
                        if code is not None or (action == "cancelar" and (not body or data != {})):
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


def attention_orders(db: Session) -> dict:
    client_id, store_id = sandbox_identity()
    latest = db.query(
        UberSandboxEvent.id.label("id"),
        func.row_number().over(
            partition_by=UberSandboxEvent.order_id,
            order_by=(UberSandboxEvent.event_time.desc(), UberSandboxEvent.id.desc()),
        ).label("position"),
    ).filter_by(client_id=client_id, store_id=store_id).filter(
        UberSandboxEvent.event_type.not_in(STORE_EVENT_TYPES),
    ).subquery()
    pending = db.query(UberSandboxAction.id).filter(
        UberSandboxAction.client_id == client_id, UberSandboxAction.store_id == store_id,
        UberSandboxAction.order_id == UberSandboxEvent.order_id,
        UberSandboxAction.estado.in_(PENDING_ORDER_ACTION_STATES),
    ).exists()
    pending = or_(pending, UberSandboxOrder.pending_request_key.is_not(None))
    ready = db.query(UberSandboxAction.id).filter(
        UberSandboxAction.client_id == client_id, UberSandboxAction.store_id == store_id,
        UberSandboxAction.order_id == UberSandboxEvent.order_id,
        UberSandboxAction.action == "listo", UberSandboxAction.estado == "confirmada",
    ).exists()
    change = aliased(UberSandboxEvent)
    changed = db.query(change.id).filter(
        change.client_id == client_id, change.store_id == store_id,
        change.order_id == UberSandboxEvent.order_id,
        change.event_type.in_(_ORDER_CHANGES),
        or_(UberSandboxOrder.id.is_(None),
            and_(change.event_type.not_in(("orders.cancel", "orders.failure")),
                 change.recibido_en > UberSandboxOrder.actualizado_en),
            and_(change.event_type.in_(("orders.cancel", "orders.failure")),
                 or_(change.estado != "consultado", UberSandboxOrder.state != "FAILED"))),
    ).exists()
    if settings.UBER_EATS_SANDBOX_ORDER_POLLING_ENABLED:
        changed = or_(changed, db.query(UberSandboxOrderCheck.id).filter(
            UberSandboxOrderCheck.client_id == client_id, UberSandboxOrderCheck.store_id == store_id,
            UberSandboxOrderCheck.order_id == UberSandboxEvent.order_id,
            UberSandboxOrderCheck.needs_review.is_(True),
        ).exists())
    kind = case(
        (or_(pending, changed), "verificar"),
        (UberSandboxOrder.state == "ACCEPTED", "preparacion"),
        (UberSandboxEvent.event_type == "orders.scheduled.notification", "programado"),
        else_="nuevo",
    )
    query = db.query(UberSandboxEvent, kind.label("kind")).join(
        latest, and_(latest.c.id == UberSandboxEvent.id, latest.c.position == 1),
    ).outerjoin(UberSandboxOrder, and_(
        UberSandboxOrder.client_id == client_id, UberSandboxOrder.store_id == store_id,
        UberSandboxOrder.order_id == UberSandboxEvent.order_id,
    )).filter(or_(
        pending, changed, UberSandboxOrder.id.is_(None),
        UberSandboxOrder.state.in_(("CREATED", "OFFERED")),
        and_(UberSandboxOrder.state == "ACCEPTED", ~ready),
    ))
    names = ("nuevo", "verificar", "preparacion", "programado")
    # One statement keeps full-queue counts and the bounded list in the same snapshot.
    rows = query.add_columns(*[
        func.sum(case((kind == name, 1), else_=0)).over() for name in names
    ]).order_by(case((kind == "verificar", 0), (kind == "nuevo", 1), else_=2),
                UberSandboxEvent.id).limit(100).all()
    counts = dict(zip(names, rows[0][2:] if rows else (0, 0, 0, 0), strict=True))
    return {
        "entorno": "sandbox", "total": sum(counts.values()), "conteos": counts,
        "pedidos": [{"pedido_id": event.order_id, "event_id": event.event_id, "tipo": value,
                     "recibido_en": event.recibido_en.replace(tzinfo=timezone.utc).isoformat()}
                    for event, value, *_ in rows],
    }


def _unseen_order_change(db: Session, row: UberSandboxOrder) -> bool:
    if settings.UBER_EATS_SANDBOX_ORDER_POLLING_ENABLED and db.query(UberSandboxOrderCheck.id).filter_by(
        client_id=row.client_id, store_id=row.store_id, order_id=row.order_id, needs_review=True,
    ).first():
        return True
    return db.query(UberSandboxEvent.id).filter_by(
        client_id=row.client_id, store_id=row.store_id, order_id=row.order_id,
    ).filter(
        UberSandboxEvent.event_type.in_(_ORDER_CHANGES),
        or_(and_(UberSandboxEvent.event_type.not_in(("orders.cancel", "orders.failure")),
                 UberSandboxEvent.recibido_en > row.actualizado_en),
            and_(UberSandboxEvent.event_type.in_(("orders.cancel", "orders.failure")),
                 or_(UberSandboxEvent.estado != "consultado", row.state != "FAILED"))),
    ).first() is not None


def inspect_order(db: Session, event_id: UUID, *, background: bool = False) -> dict:
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
    read_started_at = datetime.now(timezone.utc)
    remote_state = None
    details_available = True
    try:
        data = _request("GET", event.order_id)
    except SandboxRequestError as exc:
        if terminal_order_notice(db, client_id, store_id, event.order_id) is None:
            error = WebhookError(502, "No se pudo consultar el pedido de pruebas. Intenta de nuevo.")
            error.provider_status = exc.status_code
            raise error from None
        details_available = False
    if details_available:
        order = data.get("order")
        if not isinstance(order, dict) or not isinstance(order.get("store"), dict):
            raise WebhookError(502, "Uber no confirmo la identidad del pedido.")
        try:
            matches = str(UUID(order.get("id"))) == event.order_id and str(UUID(order["store"].get("id"))) == store_id
        except (ValueError, TypeError, AttributeError):
            matches = False
        if not matches:
            raise WebhookError(502, "Uber no confirmo la identidad del pedido.")
        if order.get("state") not in ("CREATED", "OFFERED", "ACCEPTED", "HANDED_OFF", "SUCCEEDED", "FAILED"):
            raise WebhookError(502, "Uber no confirmo el estado del pedido.")
        remote_state = order["state"]
        # Omit customers, addresses, phone numbers, payment credentials and support contacts.
        snapshot = {key: order[key] for key in (
            "id", "display_id", "state", "status", "carts", "store_instructions",
        ) if key in order}
        encoded = json.dumps(snapshot, ensure_ascii=True)
    else:
        encoded = before.snapshot_json if before else json.dumps({"id": event.order_id, "state": "FAILED"})
    terminal = terminal_order_notice(db, client_id, store_id, event.order_id)
    effective_state = "FAILED" if terminal else remote_state
    row = query.populate_existing().with_for_update().first()
    created = False
    if row is None:
        try:
            with db.begin_nested():
                row = UberSandboxOrder(
                    client_id=client_id, store_id=store_id, order_id=event.order_id,
                    state=effective_state, snapshot_json=encoded,
                    actualizado_en=datetime.fromtimestamp(0, timezone.utc) if background else read_started_at,
                )
                db.add(row)
                db.flush()
                created = True
        except IntegrityError:
            row = query.populate_existing().with_for_update().one()
    changed = not created and row.revision != before_revision
    if terminal:
        apply_terminal_order_notice(db, row, terminal)
    pending = db.query(UberSandboxAction).populate_existing().filter_by(
        client_id=client_id, store_id=store_id, order_id=event.order_id,
    ).filter(UberSandboxAction.estado.in_(PENDING_ORDER_ACTION_STATES)).first()
    rank = {"CREATED": 0, "OFFERED": 0, "ACCEPTED": 1, "HANDED_OFF": 2, "SUCCEEDED": 3, "FAILED": 3}
    regresses = rank.get(effective_state, -1) < rank.get(row.state, -1) or (
        row.state in {"FAILED", "SUCCEEDED"} and row.state != effective_state
    )
    failed = effective_state == "FAILED"
    if (pending is None or failed) and not changed and not regresses and details_available:
        values = {
            "state": effective_state, "revision": UberSandboxOrder.revision + 1,
        }
        if not background:
            values.update(snapshot_json=encoded, actualizado_en=read_started_at)
        # SQLite ignores FOR UPDATE; the version predicate must protect this write too.
        refreshed = db.execute(update(UberSandboxOrder).where(
            UberSandboxOrder.id == row.id,
            UberSandboxOrder.revision == row.revision,
            True if failed else UberSandboxOrder.pending_request_key.is_(None),
        ).values(**values).execution_options(synchronize_session=False))
        changed = refreshed.rowcount != 1
    db.refresh(row)
    snapshot = json.loads(row.snapshot_json)
    snapshot["state"] = row.state
    snapshot_digest = hashlib.sha256(row.snapshot_json.encode()).hexdigest()
    if settings.UBER_EATS_SANDBOX_ORDER_POLLING_ENABLED:
        check = db.query(UberSandboxOrderCheck).filter_by(
            client_id=client_id, store_id=store_id, order_id=event.order_id,
        ).populate_existing().with_for_update().first()
        if check:
            # Background reads never acknowledge an operator's review or authorize an action.
            if background and row.state == "FAILED" and check.last_state != "FAILED":
                check.needs_review = True
            if not background and (check.attempted_at is None or
                    check.attempted_at.replace(tzinfo=timezone.utc) <= read_started_at):
                check.needs_review = False
            check.last_state = row.state
    if not background:
        event.estado = "consultado"
    if terminal and not background:
        db.query(UberSandboxEvent).filter_by(
            client_id=client_id, store_id=store_id, order_id=event.order_id,
        ).filter(UberSandboxEvent.event_type.in_(TERMINAL_ORDER_EVENT_TYPES),
                 UberSandboxEvent.id <= terminal.id).update({"estado": "consultado"}, synchronize_session=False)
    db.commit()
    needs_review = _unseen_order_change(db, row)
    return {
        "entorno": "sandbox", "pedido": snapshot,
        "acciones_habilitadas": not background and row.state in {"CREATED", "OFFERED", "ACCEPTED"} and settings.UBER_EATS_SANDBOX_ACTIONS_ENABLED and terminal is None and pending is None and row.pending_request_key is None and not changed and not regresses and not needs_review,
        "requiere_conciliacion": pending is not None or row.pending_request_key is not None or regresses or needs_review,
        "estado_remoto": remote_state,
        "evento_final": {"tipo": terminal.event_type, "event_id": terminal.event_id} if terminal else None,
        "detalle_disponible": details_available,
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
    action_started_at = datetime.now(timezone.utc)
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
        if existing.estado in {"confirmada", "conciliada", "pendiente_aviso"}:
            return {"entorno": "sandbox", "estado": existing.estado, "repetida": True}
        raise WebhookError(409, "Operacion registrada. Revisa su resultado antes de volver a enviarla.")
    if _unseen_order_change(db, row):
        raise WebhookError(409, "Llego un cambio del pedido. Actualiza y revisa su estado antes de continuar.")
    if actions.filter_by(order_id=str(order_id)).filter(
        UberSandboxAction.estado.in_(PENDING_ORDER_ACTION_STATES)
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
        fingerprint=fingerprint, action=action, estado="enviando", creado_en=action_started_at,
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
        row = _order_query(db, client_id, store_id, str(order_id)).populate_existing().with_for_update().one()
        db.refresh(command)
        terminal = terminal_order_notice(db, client_id, store_id, str(order_id))
        if terminal:
            apply_terminal_order_notice(db, row, terminal)
        if command.estado == "conciliada":
            db.commit()
            return {"entorno": "sandbox", "estado": "conciliada", "repetida": False}
        values = {"revision": UberSandboxOrder.revision + 1}
        if not exc.uncertain:
            values["pending_request_key"] = None
        db.execute(update(UberSandboxOrder).where(
            UberSandboxOrder.id == row.id, UberSandboxOrder.pending_request_key == str(request_key),
        ).values(**values).execution_options(synchronize_session=False))
        db.execute(update(UberSandboxAction).where(
            UberSandboxAction.id == command.id, UberSandboxAction.estado == "enviando",
        ).values(estado="incierta" if exc.uncertain else "rechazada").execution_options(synchronize_session=False))
        db.commit()
        db.refresh(command)
        if command.estado == "conciliada":
            return {"entorno": "sandbox", "estado": "conciliada", "repetida": False}
        status = f" (HTTP {exc.status_code})" if exc.status_code is not None else ""
        raise WebhookError(502, f"Uber no confirmo la accion{status}. No se ha reenviado.") from None
    row = _order_query(db, client_id, store_id, str(order_id)).populate_existing().with_for_update().one()
    db.refresh(command)
    terminal = terminal_order_notice(db, client_id, store_id, str(order_id))
    if terminal:
        apply_terminal_order_notice(db, row, terminal)
    values = {"revision": UberSandboxOrder.revision + 1, "actualizado_en": action_started_at}
    if action != "cancelar":
        # Preserve a terminal callback committed after the last read, including on SQLite.
        values["state"] = case(
            (UberSandboxOrder.state == "FAILED", "FAILED"),
            else_="FAILED" if terminal or action == "rechazar" else "ACCEPTED",
        )
        values["pending_request_key"] = None
    db.execute(update(UberSandboxOrder).where(
        UberSandboxOrder.id == row.id, UberSandboxOrder.pending_request_key == str(request_key),
    ).values(**values).execution_options(synchronize_session=False))
    db.execute(update(UberSandboxAction).where(
        UberSandboxAction.id == command.id, UberSandboxAction.estado == "enviando",
    ).values(estado="pendiente_aviso" if action == "cancelar" else "confirmada").execution_options(synchronize_session=False))
    db.commit()
    db.refresh(command)
    return {"entorno": "sandbox", "estado": command.estado, "repetida": False}
