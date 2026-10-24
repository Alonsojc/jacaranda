"""Store capabilities restricted to the approved TEST application and fixture menu."""

import copy
import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.uber_eats import UberSandboxEvent, UberSandboxStore, UberSandboxStoreAction, UberSandboxStoreJob
from app.services import uber_eats_service as api
from app.services.uber_webhook_service import WebhookError, sandbox_identity, store_state

TEST_CLIENT_ID = "I2pbZ-jD6Qa7FQzhLUbX3Y5gN12EasPL"
TEST_STORE_ID = "b412bb20-cf36-4ada-ba77-fdda96ce8a9e"
ITEM_IDS = ("jacaranda-sandbox-brownie", "jacaranda-sandbox-galleta")
MAX_BYTES = 2 * 1024 * 1024
OPERATIONS = frozenset({"menu_publicar", "item_actualizar", "pausar", "reanudar", "integracion_pausar", "integracion_activar", "vincular"})
logger = logging.getLogger(__name__)


class StoreAPIError(Exception):
    def __init__(self, status: int | None = None, uncertain: bool = False):
        self.status = status
        self.uncertain = uncertain
        super().__init__("Uber no confirmo la operacion de tienda de pruebas.")


def identity() -> tuple[str, str]:
    client_id, store_id = sandbox_identity()
    if (
        (client_id, store_id) != (TEST_CLIENT_ID, TEST_STORE_ID)
        or os.environ.get("JACARANDA_RUNTIME") != "uber-sandbox"
        or os.environ.get("RAILWAY_ENVIRONMENT_NAME") != "uber-sandbox"
        or not settings.UBER_EATS_SANDBOX_MANAGEMENT_ENABLED
        or api.API_URL != "https://test-api.uber.com"
        or api.TOKEN_URL != "https://sandbox-login.uber.com/oauth/v2/token"
    ):
        raise WebhookError(503, "Solo esta permitido el entorno dedicado de Jacaranda Sandbox.")
    return client_id, store_id


def fixture_menu() -> dict:
    return {
        "menus": [{
            "id": "jacaranda-sandbox-menu", "title": {"translations": {"es_mx": "Menu ficticio de pruebas"}},
            "service_availability": [{"day_of_week": day, "time_periods": [{"start_time": "00:00", "end_time": "23:59"}]}
                                     for day in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")],
            "category_ids": ["jacaranda-sandbox-postres"],
        }],
        "categories": [{
            "id": "jacaranda-sandbox-postres", "title": {"translations": {"es_mx": "PRUEBA - No preparar"}},
            "entities": [{"id": item_id, "type": "ITEM"} for item_id in ITEM_IDS],
        }],
        "items": [{
            "id": item_id, "title": {"translations": {"es_mx": name}},
            "description": {"translations": {"es_mx": "Producto ficticio. Solo UBER_TEST. No preparar ni entregar."}},
            "price_info": {"price": price}, "tax_info": {"vat_rate_percentage": 0},
            "suspension_info": {"suspension": None},
        } for item_id, name, price in zip(ITEM_IDS, ("Brownie ficticio de prueba", "Galleta ficticia de prueba"), (100, 200), strict=True)],
        "modifier_groups": [],
    }


def _path(suffix: str) -> str:
    return f"/v1/eats/stores/{TEST_STORE_ID}{suffix}"


def request(method: str, path: str, payload: dict | None = None, merchant_token: str | None = None,
            params: dict | None = None) -> dict:
    identity()
    allowed = {
        ("GET", "/v1/eats/stores"): (200, "eats.store"),
        ("GET", "/v1/delivery/stores"): (200, "eats.store"),
        ("GET", f"/v1/delivery/store/{TEST_STORE_ID}"): (200, "eats.store"),
        ("GET", _path("/pos_data")): (200, "eats.store"),
        ("PATCH", _path("/pos_data")): (204, "eats.store"),
        ("POST", _path("/pos_data")): (200, "merchant"),
        ("GET", f"/v1/delivery/store/{TEST_STORE_ID}/status"): (200, "eats.store"),
        ("POST", f"/v1/delivery/store/{TEST_STORE_ID}/update-store-status"): (200, "eats.store.status.write"),
        ("GET", f"/v2/eats/stores/{TEST_STORE_ID}/menus"): (200, "eats.store"),
        ("PUT", f"/v2/eats/stores/{TEST_STORE_ID}/menus"): (204, "eats.store"),
    }
    for item_id in ITEM_IDS:
        allowed[("POST", f"/v2/eats/stores/{TEST_STORE_ID}/menus/items/{item_id}")] = (204, "eats.store")
    if (method, path) not in allowed:
        raise WebhookError(403, "Operacion fuera de la tienda de pruebas permitida.")
    if params and (method, path) != ("GET", "/v1/delivery/stores"):
        raise WebhookError(403, "Consulta fuera del contrato de tiendas de pruebas.")
    expected, scope = allowed[(method, path)]
    if scope == "merchant" and not merchant_token:
        raise WebhookError(409, "Autoriza primero la cuenta del comerciante de Sandbox.")
    writing = method != "GET"
    try:
        with httpx.Client(timeout=15, follow_redirects=False) as client:
            try:
                token = merchant_token if scope == "merchant" else api._access_token(client, scope)
            except (api.UberEatsError, httpx.HTTPError):
                raise StoreAPIError() from None
            with client.stream(method, api.API_URL + path, json=payload if writing else None, params=params,
                               headers={"Authorization": "Bearer " + token, "Accept": "application/json"}) as response:
                raw = bytearray()
                for chunk in response.iter_bytes():
                    if len(raw) + len(chunk) > MAX_BYTES:
                        raise StoreAPIError(response.status_code, writing)
                    raw.extend(chunk)
                try:
                    data = json.loads(raw) if raw else {}
                except (ValueError, UnicodeDecodeError, RecursionError):
                    raise StoreAPIError(response.status_code, writing) from None
                logger.info("Uber sandbox store response method=%s path=%s http=%s bytes=%s",
                            method, path, response.status_code, len(raw))
                if response.status_code != expected or not isinstance(data, dict) or data.get("code"):
                    raise StoreAPIError(response.status_code, writing and not 400 <= response.status_code < 500)
                return data
    except httpx.HTTPError:
        raise StoreAPIError(uncertain=writing) from None


def integration() -> dict:
    data = request("GET", _path("/pos_data"))
    if data.get("store_id") != TEST_STORE_ID:
        raise StoreAPIError()
    manager = data.get("order_manager_client_id")
    if manager not in {None, "", TEST_CLIENT_ID}:
        raise WebhookError(409, "La tienda de pruebas esta asociada a otra aplicacion.")
    return {k: data[k] for k in (
        "store_id", "integration_enabled", "pos_integration_enabled", "require_manual_acceptance", "order_manager_client_id",
    ) if k in data}


def menu_view(data: dict) -> list[dict]:
    items = data.get("items") or []
    if not isinstance(items, list) or len(items) > 2000:
        raise StoreAPIError()
    result = []
    for item in items:
        if not isinstance(item, dict) or item.get("id") not in ITEM_IDS:
            continue
        title = _title(item)
        price_info = item.get("price_info") or {}
        suspension_info = item.get("suspension_info") or {}
        if not isinstance(price_info, dict) or not isinstance(suspension_info, dict):
            raise StoreAPIError()
        price = price_info.get("price")
        if type(price) is not int or not 100 <= price <= 500:
            raise StoreAPIError()
        suspension = suspension_info.get("suspension") or {}
        if not isinstance(suspension, dict):
            raise StoreAPIError()
        until = suspension.get("suspend_until", 0)
        result.append({"id": item["id"], "nombre": title or "Producto ficticio",
                       "precio_centavos": price, "agotado": isinstance(until, (int, float)) and until > datetime.now(timezone.utc).timestamp()})
    return sorted(result, key=lambda item: item["id"])


def _title(row: dict) -> str | None:
    value = row.get("title") or {}
    translations = value.get("translations") if isinstance(value, dict) else None
    if translations is not None and not isinstance(translations, dict):
        raise StoreAPIError()
    title = (translations or {}).get("es_mx")
    if title is not None and not isinstance(title, str):
        raise StoreAPIError()
    return title


def menu_signature(menu: dict) -> dict:
    result = {"items": menu_view(menu), "menus": [], "categories": []}
    for kind in ("menus", "categories"):
        rows = menu.get(kind) or []
        if not isinstance(rows, list) or len(rows) > 100:
            raise StoreAPIError()
        for row in rows:
            if not isinstance(row, dict):
                raise StoreAPIError()
            if not isinstance(row.get("id"), str):
                raise StoreAPIError()
            value = {"id": row["id"], "title": _title(row)}
            if kind == "menus":
                categories = row.get("category_ids") or []
                availability = row.get("service_availability") or []
                if not isinstance(categories, list) or not all(isinstance(v, str) for v in categories) or not isinstance(availability, list):
                    raise StoreAPIError()
                value["category_ids"] = sorted(categories)
                value["availability"] = []
                for day in availability:
                    if not isinstance(day, dict) or not isinstance(day.get("day_of_week"), str):
                        raise StoreAPIError()
                    periods = day.get("time_periods")
                    if not isinstance(periods, list) or not all(
                        isinstance(p, dict) and isinstance(p.get("start_time"), str) and isinstance(p.get("end_time"), str)
                        for p in periods
                    ):
                        raise StoreAPIError()
                    value["availability"].append([day["day_of_week"], sorted([p["start_time"], p["end_time"]] for p in periods)])
                value["availability"].sort()
            else:
                entities = row.get("entities") or []
                if not isinstance(entities, list) or not all(
                    isinstance(item, dict) and isinstance(item.get("id"), str) and isinstance(item.get("type"), str)
                    for item in entities
                ):
                    raise StoreAPIError()
                value["entities"] = sorted([item["id"], item["type"]] for item in entities)
            result[kind].append(value)
        result[kind].sort(key=lambda item: item["id"] or "")
    return result


def _desired_matches(desired: dict, config: dict, status: str, menu: dict) -> bool:
    if "integration_enabled" in desired:
        return config.get("integration_enabled") is desired["integration_enabled"] and (
            not desired["integration_enabled"] or config.get("require_manual_acceptance") is False
        )
    if "online_status" in desired:
        return status == desired["online_status"]
    if "menu" in desired:
        return menu_signature(menu) == desired["menu"]
    items = menu_view(menu)
    wanted = desired.get("items")
    if isinstance(wanted, list):
        actual = {item["id"]: item for item in items}
        return bool(wanted) and all(
            item["id"] in actual and all(actual[item["id"]].get(key) == item[key] for key in ("nombre", "precio_centavos", "agotado"))
            for item in wanted
        )
    return False


def inspect_store(db: Session) -> dict:
    client_id, store_id = identity()
    row = store_state(db, client_id, store_id)
    revision = row.revision
    config = integration()
    status = request("GET", f"/v1/delivery/store/{store_id}/status").get("status")
    if status not in {"ONLINE", "OFFLINE"}:
        raise StoreAPIError()
    menu = request("GET", f"/v2/eats/stores/{store_id}/menus")
    items = menu_view(menu)
    row = store_state(db, client_id, store_id, lock=True)
    pending = db.query(UberSandboxStoreAction).filter_by(
        client_id=client_id, store_id=store_id, request_key=row.pending_request_key,
    ).first() if row.pending_request_key else None
    if row.revision == revision:
        values = {"online_status": status, "integration_enabled": config.get("integration_enabled") is True,
                  "updated_at": datetime.now(timezone.utc), "revision": UberSandboxStore.revision + 1}
        resolved = pending is not None and pending.state in {"recibida", "incierta"} and _desired_matches(
            json.loads(pending.desired_json), config, status, menu,
        )
        if resolved:
            values["pending_request_key"] = None
        updated = db.execute(update(UberSandboxStore).where(
            UberSandboxStore.id == row.id, UberSandboxStore.revision == revision,
        ).values(**values).execution_options(synchronize_session=False))
        if updated.rowcount == 1 and resolved:
            pending.state = "conciliada" if pending.state == "incierta" else "confirmada"
            if pending.action in {"integracion_activar", "vincular"}:
                row.revoked = False
            if pending.action == "menu_publicar":
                row.menu_uploaded = True
    db.flush()
    db.refresh(row)
    db.commit()
    return {"entorno": "sandbox", "tienda_id": store_id, "nombre": "Jacaranda Sandbox", "revision": row.revision,
            "integracion": config, "estado": status, "revocada": row.revoked,
            "requiere_conciliacion": row.pending_request_key is not None,
            "menu_publicado": row.menu_uploaded, "items": items,
            "cuenta_autorizada": bool(row.merchant_token_encrypted and row.merchant_token_expires and
                                       _utc(row.merchant_token_expires) > datetime.now(timezone.utc))}


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def discover_stores() -> dict:
    identity()
    results = []
    for path in ("/v1/eats/stores", "/v1/delivery/stores"):
        found, page_token, visited = False, None, set()
        for _ in range(10):
            params = {"page_size": 50, **({"next_page_token": page_token} if page_token else {})} if path == "/v1/delivery/stores" else None
            data = request("GET", path, params=params)
            stores = data.get("stores")
            if not isinstance(stores, list):
                raise StoreAPIError()
            found = found or any(isinstance(item, dict) and item.get("id", item.get("store_id")) == TEST_STORE_ID for item in stores)
            page_token = (data.get("pagination_data") or {}).get("next_page_token") if path == "/v1/delivery/stores" else None
            if not page_token:
                break
            if not isinstance(page_token, str) or len(page_token) > 4096 or page_token in visited:
                raise StoreAPIError()
            visited.add(page_token)
        if page_token or not found:
            raise StoreAPIError()
        results.append({"ruta": path, "tienda_encontrada": found})
    detail = request("GET", f"/v1/delivery/store/{TEST_STORE_ID}")
    store = detail.get("store", detail)
    if store.get("id", store.get("store_id")) != TEST_STORE_ID:
        raise StoreAPIError()
    return {"entorno": "sandbox", "tiendas": [{"id": TEST_STORE_ID, "nombre": "Jacaranda Sandbox"}], "consultas": results}


def _integration_payload() -> dict:
    return {"integrator_store_id": "jacaranda-sandbox", "integrator_brand_id": "jacaranda-sandbox",
            "is_order_manager": True, "require_manual_acceptance": False,
            "allowed_customer_requests": {"allow_special_instruction_requests": True},
            "store_configuration_data": "Jacaranda Sandbox: fictional fixtures and UBER_TEST only"}


def submit(db: Session, request_key: UUID, operation: str, revision: int, confirmed: bool,
           item_id: str | None = None, price: int | None = None, sold_out: bool | None = None,
           merchant_token: str | None = None) -> dict:
    client_id, store_id = identity()
    if not settings.UBER_EATS_SANDBOX_ACTIONS_ENABLED or not confirmed or operation not in OPERATIONS:
        raise WebhookError(409, "Confirma la operacion exclusiva de Sandbox.")
    if operation == "vincular" and not merchant_token:
        raise WebhookError(409, "Autoriza primero la cuenta de comerciante de pruebas.")
    if operation == "item_actualizar" and (
        item_id not in ITEM_IDS or type(price) is not int or not 100 <= price <= 500 or type(sold_out) is not bool
    ):
        raise WebhookError(422, "Solo se permiten productos ficticios con precios de prueba.")
    fingerprint = hashlib.sha256(json.dumps({"operation": operation, "revision": revision, "item": item_id,
                                           "price": price, "sold_out": sold_out}, sort_keys=True).encode()).hexdigest()
    existing = db.query(UberSandboxStoreAction).filter_by(client_id=client_id, store_id=store_id, request_key=str(request_key)).first()
    if existing:
        if existing.fingerprint != fingerprint:
            raise WebhookError(409, "La clave ya corresponde a otra operacion.")
        return {"entorno": "sandbox", "estado": existing.state, "repetida": True}
    row = store_state(db, client_id, store_id, lock=True)
    if row.pending_request_key or row.revision != revision:
        raise WebhookError(409, "Actualiza la tienda; existe una operacion pendiente o un estado nuevo.")
    if row.revoked and operation not in {"integracion_activar", "vincular"}:
        raise WebhookError(409, "La integracion esta revocada.")
    if (datetime.now(timezone.utc) - _utc(row.updated_at)).total_seconds() > 120:
        raise WebhookError(409, "Actualiza la tienda antes de enviar cambios.")
    if operation in {"menu_publicar", "item_actualizar", "pausar", "reanudar"} and not row.integration_enabled:
        raise WebhookError(409, "La integracion de pruebas no esta habilitada.")
    menu = json.loads(row.menu_json) if row.menu_json else fixture_menu()
    if operation == "menu_publicar":
        method, path, payload = "PUT", f"/v2/eats/stores/{store_id}/menus", menu
        desired = {"menu": menu_signature(menu)}
    elif operation == "item_actualizar":
        if not row.menu_uploaded:
            raise WebhookError(409, "Publica primero el menu ficticio por API.")
        suspension = {"suspend_until": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()), "reason": "UBER_TEST"} if sold_out else None
        payload = {"price_info": {"price": price}, "suspension_info": {"suspension": suspension}}
        for item in menu["items"]:
            if item["id"] == item_id:
                item.update(copy.deepcopy(payload))
        method, path = "POST", f"/v2/eats/stores/{store_id}/menus/items/{item_id}"
        desired = {"items": [item for item in menu_view(menu) if item["id"] == item_id]}
    elif operation in {"pausar", "reanudar"}:
        desired = {"online_status": "OFFLINE" if operation == "pausar" else "ONLINE"}
        method, path = "POST", f"/v1/delivery/store/{store_id}/update-store-status"
        payload = {"status": desired["online_status"], "reason": "Jacaranda Sandbox UBER_TEST validation"}
    else:
        method, path = ("POST" if operation == "vincular" else "PATCH"), _path("/pos_data")
        enabled = operation != "integracion_pausar"
        payload = _integration_payload() if operation == "vincular" else {"integration_enabled": enabled}
        if enabled and operation != "vincular":
            payload["require_manual_acceptance"] = False
        desired = {"integration_enabled": enabled}
    claim = db.execute(update(UberSandboxStore).where(
        UberSandboxStore.id == row.id, UberSandboxStore.revision == revision,
        UberSandboxStore.pending_request_key.is_(None),
    ).values(pending_request_key=str(request_key), revision=UberSandboxStore.revision + 1,
             menu_json=json.dumps(menu, ensure_ascii=True)).execution_options(synchronize_session=False))
    if claim.rowcount != 1:
        db.rollback()
        raise WebhookError(409, "Otra operacion esta en curso.")
    command = UberSandboxStoreAction(client_id=client_id, store_id=store_id, request_key=str(request_key),
                                    action=operation, fingerprint=fingerprint, state="enviando", desired_json=json.dumps(desired))
    db.add(command)
    db.commit()
    try:
        request(method, path, payload, merchant_token=merchant_token)
    except StoreAPIError as exc:
        command.state = "incierta" if exc.uncertain else "rechazada"
        if not exc.uncertain:
            db.execute(update(UberSandboxStore).where(UberSandboxStore.id == row.id,
                       UberSandboxStore.pending_request_key == str(request_key)).values(pending_request_key=None))
        db.commit()
        raise WebhookError(502, "Uber no confirmo la operacion. Actualiza; no se ha reenviado.") from None
    command.state = "recibida"
    db.commit()
    return {"entorno": "sandbox", "estado": "recibida", "repetida": False}


def process_job(db: Session) -> bool:
    client_id, store_id = identity()
    if not settings.UBER_EATS_SANDBOX_STORE_AUTOMATION_ENABLED:
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=15)
    job = db.query(UberSandboxStoreJob).filter_by(client_id=client_id, store_id=store_id).filter(
        UberSandboxStoreJob.state == "pending", UberSandboxStoreJob.attempts < 3,
        UberSandboxStoreJob.updated_at <= cutoff,
    ).order_by(UberSandboxStoreJob.id).first()
    if job is None:
        return False
    claimed = db.execute(update(UberSandboxStoreJob).where(
        UberSandboxStoreJob.id == job.id, UberSandboxStoreJob.state == "pending",
    ).values(state="processing", attempts=UberSandboxStoreJob.attempts + 1, updated_at=datetime.now(timezone.utc)))
    if claimed.rowcount != 1:
        db.rollback()
        return False
    db.commit()
    event = db.query(UberSandboxEvent).filter_by(client_id=client_id, store_id=store_id, event_id=job.event_id).one()
    try:
        row = store_state(db, client_id, store_id)
        if event.event_type != "store.deprovisioned":
            config = integration()
            row = store_state(db, client_id, store_id, lock=True)
            if event.event_type == "store.provisioned" and event.event_time > row.lifecycle_event_time:
                row.revoked = config.get("integration_enabled") is not True
                row.integration_enabled = config.get("integration_enabled") is True
                row.lifecycle_event_time = event.event_time
                row.revision += 1
            db.commit()
            if event.event_type == "store.status.changed":
                status = request("GET", f"/v1/delivery/store/{store_id}/status").get("status")
                if status not in {"ONLINE", "OFFLINE"}:
                    raise StoreAPIError()
                row = store_state(db, client_id, store_id, lock=True)
                row.online_status = status
                db.commit()
            if job.needs_menu:
                inspect_store(db)
                row = store_state(db, client_id, store_id)
                if row.revoked or config.get("integration_enabled") is not True:
                    raise StoreAPIError()
                menu = json.loads(row.menu_json) if row.menu_json else fixture_menu()
                remote = request("GET", f"/v2/eats/stores/{store_id}/menus")
                if menu_signature(remote) != menu_signature(menu):
                    submit(db, UUID(job.event_id), "menu_publicar", row.revision, True)
                verified = request("GET", f"/v2/eats/stores/{store_id}/menus")
                if menu_signature(verified) != menu_signature(menu):
                    raise StoreAPIError()
                inspect_store(db)
                row = store_state(db, client_id, store_id)
                row.menu_json = json.dumps(menu)
                row.menu_uploaded = True
        event.estado = "procesado"
        job.state = "done"
    except (StoreAPIError, WebhookError, ValueError):
        db.rollback()
        job = db.get(UberSandboxStoreJob, job.id)
        job.state = "failed" if job.attempts >= 3 else "pending"
    job.updated_at = datetime.now(timezone.utc)
    db.commit()
    return True
