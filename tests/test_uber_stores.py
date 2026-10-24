"""Four Sandbox capability blocks, tested with synthetic provider responses only."""

import copy
import hashlib
import hmac
import json
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app import uber_sandbox_runtime as runtime
from app.core.config import settings
from app.models.uber_eats import UberSandboxEvent, UberSandboxStore, UberSandboxStoreAction, UberSandboxStoreJob
from app.services import uber_sandbox_oauth as oauth
from app.services import uber_store_service as stores
from app.services.uber_webhook_service import STORE_EVENT_TYPES, WebhookError
from tests.test_uber_sandbox_management import AUTH, management  # noqa: F401
from tests.test_uber_sandbox_runtime import SECRET, isolated  # noqa: F401

BASE = "/api/v1/uber-eats/sandbox"


@contextmanager
def provider(change=None):
    state = {
        "config": {"store_id": runtime.TEST_STORE_ID, "integration_enabled": True,
                   "order_manager_client_id": runtime.TEST_APPLICATION_ID, "require_manual_acceptance": False},
        "status": "ONLINE", "menu": {"items": [], "menus": []}, "calls": [], "tokens": [],
    }
    original = httpx.Client

    def respond(request):
        if request.url.host == "sandbox-login.uber.com":
            values = parse_qs(request.content.decode())
            state["tokens"].append(values)
            if values["grant_type"] == ["authorization_code"]:
                return httpx.Response(200, json={"access_token": "synthetic-merchant-token", "expires_in": 3600,
                                               "scope": "eats.pos_provisioning"})
            assert values["scope"][0] in {"eats.store", "eats.store.status.write"}
            return httpx.Response(200, json={"access_token": "synthetic-app-token", "expires_in": 3600})
        assert request.url.host == "test-api.uber.com"
        state["calls"].append(request)
        if change:
            changed = change(request, state)
            if changed is not None:
                return changed
        path = request.url.path
        if path in {"/v1/eats/stores", "/v1/delivery/stores"}:
            return httpx.Response(200, json={"stores": [{"id": runtime.TEST_STORE_ID}]})
        if path == "/v1/delivery/store/" + runtime.TEST_STORE_ID:
            return httpx.Response(200, json={"store": {"id": runtime.TEST_STORE_ID}})
        if path.endswith("/pos_data"):
            if request.method == "POST":
                assert request.headers["authorization"] == "Bearer synthetic-merchant-token"
                state["config"].update(json.loads(request.content))
                state["config"]["integration_enabled"] = True
                return httpx.Response(200)
            if request.method == "PATCH":
                state["config"].update(json.loads(request.content))
                return httpx.Response(204)
            return httpx.Response(200, json=state["config"])
        if path.endswith("/status"):
            return httpx.Response(200, json={"status": state["status"]})
        if path.endswith("/update-store-status"):
            state["status"] = json.loads(request.content)["status"]
            return httpx.Response(200, json={"status": state["status"]})
        if "/menus/items/" in path:
            item_id = path.rsplit("/", 1)[1]
            assert item_id in stores.ITEM_IDS
            for item in state["menu"]["items"]:
                if item["id"] == item_id:
                    item.update(json.loads(request.content))
            return httpx.Response(204)
        if path.endswith("/menus"):
            if request.method == "PUT":
                state["menu"] = json.loads(request.content)
                return httpx.Response(204)
            return httpx.Response(200, json=state["menu"])
        raise AssertionError("Unexpected test endpoint")

    with patch.object(httpx, "Client", side_effect=lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs)):
        yield state


def store_event(kind, **changes):
    result = {
        "event_type": kind, "store_id": runtime.TEST_STORE_ID,
        "webhook_meta": {"client_id": runtime.TEST_APPLICATION_ID, "webhook_msg_uuid": str(uuid4()),
                         "webhook_msg_timestamp": int(time.time())},
        "resource_href": "https://attacker.invalid/never-follow",
        "customer": {"phone": "never-retain-contact"},
    }
    result.update(changes)
    return result


def receive(client, event, extra_headers=None):
    raw = json.dumps(event).encode()
    signature = hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return client.post(runtime.WEBHOOK_PATH, content=raw, headers={
        "X-Uber-Signature": signature, "X-Environment": "sandbox", **(extra_headers or {}),
    })


def current(client):
    r = client.get(BASE + "/tienda", headers=AUTH)
    assert r.status_code == 200, r.text
    return r.json()


def action(client, kind, **changes):
    state = current(client)
    body = {"request_key": str(uuid4()), "accion": kind, "revision": state["revision"],
            "solo_sandbox_confirmado": True, **changes}
    return client.post(BASE + "/tienda/accion", headers=AUTH, json=body), body


@pytest.mark.parametrize("path,method", [
    ("/tiendas", "get"), ("/tienda", "get"), ("/menu-ficticio", "get"),
    ("/tienda/eventos", "get"), ("/tienda/accion", "post"), ("/oauth/iniciar", "post"),
])
def test_capabilities_are_private_before_any_provider_request(management, path, method):
    with TestClient(runtime.app) as client, patch("httpx.Client") as network:
        assert getattr(client, method)(BASE + path).status_code == 401
        network.assert_not_called()


def test_discovery_reads_all_documented_test_routes_and_omits_other_stores(management):
    with TestClient(runtime.app) as client, provider() as remote:
        result = client.get(BASE + "/tiendas", headers=AUTH)
        assert result.status_code == 200
        assert result.json()["tiendas"] == [{"id": runtime.TEST_STORE_ID, "nombre": "Jacaranda Sandbox"}]
        assert len(remote["calls"]) == 3
        assert all(call.method == "GET" for call in remote["calls"])


def test_discovery_follows_bounded_delivery_pagination(management):
    def page(request, _state):
        if request.url.path == "/v1/delivery/stores" and "next_page_token" not in request.url.params:
            return httpx.Response(200, json={"stores": [{"id": str(uuid4()), "phone": "never-expose"}],
                                           "pagination_data": {"next_page_token": "page-2"}})
    with TestClient(runtime.app) as client, provider(page) as remote:
        result = client.get(BASE + "/tiendas", headers=AUTH)
        assert result.status_code == 200 and "never-expose" not in result.text
        pages = [r for r in remote["calls"] if r.url.path == "/v1/delivery/stores"]
        assert len(pages) == 2 and pages[1].url.params["next_page_token"] == "page-2"


def test_fixture_upload_price_and_stock_are_verified_and_replay_does_not_write(management):
    with TestClient(runtime.app) as client, provider() as remote:
        result, body = action(client, "menu_publicar")
        assert result.status_code == 200
        state = current(client)
        assert state["menu_publicado"] and not state["requiere_conciliacion"]
        assert len(state["items"]) == 2
        assert all(item["id"] in stores.ITEM_IDS for item in remote["menu"]["items"])
        assert "No preparar" in json.dumps(remote["menu"])
        writes = len([r for r in remote["calls"] if r.method != "GET"])
        repeat = client.post(BASE + "/tienda/accion", headers=AUTH, json=body)
        assert repeat.status_code == 200 and repeat.json()["repetida"]
        assert len([r for r in remote["calls"] if r.method != "GET"]) == writes
        result, _ = action(client, "item_actualizar", item_id=stores.ITEM_IDS[0], precio_centavos=150, agotado=True)
        assert result.status_code == 200
        item = next(i for i in current(client)["items"] if i["id"] == stores.ITEM_IDS[0])
        assert item["precio_centavos"] == 150 and item["agotado"]
        result, _ = action(client, "item_actualizar", item_id=stores.ITEM_IDS[0], precio_centavos=100, agotado=False)
        assert result.status_code == 200
        assert not next(i for i in current(client)["items"] if i["id"] == stores.ITEM_IDS[0])["agotado"]


@pytest.mark.parametrize("values", [
    {"item_id": "real-product"}, {"precio_centavos": 0}, {"precio_centavos": 501},
    {"precio_centavos": True}, {"agotado": "true"}, {"tienda_id": "real-store"},
])
def test_arbitrary_or_real_menu_changes_are_rejected(management, values):
    with TestClient(runtime.app) as client, provider() as remote:
        state = current(client)
        body = {"request_key": str(uuid4()), "accion": "item_actualizar", "revision": state["revision"],
                "solo_sandbox_confirmado": True, "item_id": stores.ITEM_IDS[0], "precio_centavos": 100, "agotado": False,
                **values}
        assert client.post(BASE + "/tienda/accion", headers=AUTH, json=body).status_code == 422
        assert all(r.method == "GET" for r in remote["calls"])


def test_pause_resume_and_integration_updates_are_verified(management):
    with TestClient(runtime.app) as client, provider() as remote:
        for kind, expected in (("pausar", "OFFLINE"), ("reanudar", "ONLINE")):
            result, _ = action(client, kind)
            assert result.status_code == 200
            assert current(client)["estado"] == expected
        assert any(t["scope"] == ["eats.store.status.write"] for t in remote["tokens"])
        for kind, expected in (("integracion_pausar", False), ("integracion_activar", True)):
            result, _ = action(client, kind)
            assert result.status_code == 200
            assert current(client)["integracion"]["integration_enabled"] is expected


def test_uncertain_store_change_is_not_resent_and_only_matching_read_reconciles(management):
    def uncertain(request, state):
        if request.method == "POST" and request.url.path.endswith("/update-store-status"):
            state["status"] = "OFFLINE"
            return httpx.Response(500, json={"message": "never-expose-response-secret"})
    with TestClient(runtime.app) as client, provider(uncertain) as remote:
        result, body = action(client, "pausar")
        assert result.status_code == 502 and "never-expose" not in result.text
        assert client.post(BASE + "/tienda/accion", headers=AUTH, json=body).json()["repetida"]
        assert not current(client)["requiere_conciliacion"]
        assert len([r for r in remote["calls"] if r.method == "POST"]) == 1
    with management[1]() as db:
        assert db.query(UberSandboxStoreAction).one().state == "conciliada"


@pytest.mark.parametrize("kind", sorted(STORE_EVENT_TYPES))
def test_signed_store_events_commit_once_without_network_or_order_inspection(management, kind):
    with TestClient(runtime.app) as client, patch("httpx.Client") as network:
        payload = store_event(kind, perform_refresh_menu=kind == "store.provisioned")
        assert receive(client, payload).status_code == 200
        assert receive(client, payload).status_code == 200
        event_id = payload["webhook_meta"]["webhook_msg_uuid"]
        result = client.post(BASE + "/eventos/" + event_id + "/consultar", headers=AUTH, json={})
        assert result.status_code == 409
        assert client.get(BASE + "/eventos", headers=AUTH).json()["eventos"] == []
        assert len(client.get(BASE + "/tienda/eventos", headers=AUTH).json()["eventos"]) == 1
        network.assert_not_called()
    with management[1]() as db:
        assert db.query(UberSandboxEvent).count() == db.query(UberSandboxStoreJob).count() == 1
        assert "never-retain" not in str(db.query(UberSandboxEvent).one().__dict__)
        assert "attacker.invalid" not in str(db.query(UberSandboxEvent).one().__dict__)
        assert db.query(UberSandboxStore).one().revoked is (kind == "store.deprovisioned")


@pytest.mark.parametrize("change", ["store", "client", "uuid", "time", "flag", "environment"])
def test_invalid_store_events_cannot_enter_or_disable_a_store(management, change):
    payload = store_event("store.deprovisioned")
    if change == "store":
        payload["store_id"] = str(uuid4())
    elif change == "client":
        payload["webhook_meta"]["client_id"] = "other-client"
    elif change == "uuid":
        payload["webhook_meta"]["webhook_msg_uuid"] = "invalid"
    elif change == "time":
        payload["webhook_meta"]["webhook_msg_timestamp"] = True
    elif change == "flag":
        payload["perform_refresh_menu"] = "yes"
    with TestClient(runtime.app) as client:
        r = receive(client, payload, {"X-Environment": "production"} if change == "environment" else None)
        assert r.status_code in {400, 403}
    with management[1]() as db:
        assert db.query(UberSandboxEvent).count() == db.query(UberSandboxStoreJob).count() == 0


def test_deprovision_is_an_immediate_write_barrier(management):
    with TestClient(runtime.app) as client, provider() as remote:
        current(client)
        assert receive(client, store_event("store.deprovisioned")).status_code == 200
        response, _ = action(client, "menu_publicar")
        assert response.status_code == 409
        assert all(r.method == "GET" for r in remote["calls"])


@pytest.mark.parametrize("kind", ["store.provisioned", "store.menu_refresh_request", "store.status.changed", "store.deprovisioned"])
def test_durable_jobs_process_fixture_or_canonical_status_only(management, monkeypatch, kind):
    with TestClient(runtime.app) as client, provider() as remote:
        payload = store_event(kind, perform_refresh_menu=kind == "store.provisioned")
        assert receive(client, payload).status_code == 200
        monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_STORE_AUTOMATION_ENABLED", True)
        with management[1]() as db:
            db.query(UberSandboxStoreJob).update({"updated_at": datetime.now(timezone.utc) - timedelta(minutes=1)})
            db.commit()
            assert stores.process_job(db)
            assert db.query(UberSandboxStoreJob).one().state == "done"
            assert db.query(UberSandboxEvent).one().estado == "procesado"
            if kind in {"store.provisioned", "store.menu_refresh_request"}:
                assert db.query(UberSandboxStore).one().menu_uploaded
                assert len([r for r in remote["calls"] if r.method == "PUT"]) == 1
            elif kind == "store.deprovisioned":
                assert remote["calls"] == []
            else:
                assert db.query(UberSandboxStore).one().online_status == "ONLINE"
            assert not stores.process_job(db)


def test_merchant_oauth_is_one_use_encrypted_and_test_store_scoped(management):
    with TestClient(runtime.app) as client, provider() as remote:
        first = client.post(BASE + "/oauth/iniciar", headers=AUTH).json()
        params = parse_qs(urlsplit(first["url"]).query)
        assert urlsplit(first["url"]).netloc == "sandbox-login.uber.com"
        assert params["scope"] == ["eats.pos_provisioning"]
        query = {"code": "synthetic-authorization-code", "state": params["state"][0]}
        result = client.get("/sandbox/oauth/callback", params=query)
        assert result.status_code == 200 and "synthetic-authorization-code" not in result.text
        assert client.get("/sandbox/oauth/callback", params=query).status_code == 400
        assert current(client)["cuenta_autorizada"]
        result, _ = action(client, "vincular")
        assert result.status_code == 200
        assert not current(client)["requiere_conciliacion"]
        assert len([t for t in remote["tokens"] if t["grant_type"] == ["authorization_code"]]) == 1
    with management[1]() as db:
        row = db.query(UberSandboxStore).one()
        assert row.merchant_token_encrypted and "synthetic-merchant-token" not in row.merchant_token_encrypted
        assert row.oauth_state_hash is None
        assert oauth.merchant_token(db) == "synthetic-merchant-token"


def test_oauth_rejects_a_different_store_even_with_a_valid_token(management):
    def other_store(request, _state):
        if request.url.path == "/v1/eats/stores":
            return httpx.Response(200, json={"stores": [{"id": str(uuid4())}]})
    with TestClient(runtime.app) as client, provider(other_store):
        url = client.post(BASE + "/oauth/iniciar", headers=AUTH).json()["url"]
        state = parse_qs(urlsplit(url).query)["state"][0]
        assert client.get("/sandbox/oauth/callback", params={"code": "test-code", "state": state}).status_code == 400
    with management[1]() as db:
        assert not db.query(UberSandboxStore).one().merchant_token_encrypted


def test_oauth_wrong_state_is_rejected_before_exchange_and_activation_needs_user_token(management):
    with TestClient(runtime.app) as client, provider() as remote:
        result = client.get("/sandbox/oauth/callback", params={"code": "private-code", "state": "wrong-state"})
        assert result.status_code == 400 and "private-code" not in result.text
        response, _ = action(client, "vincular")
        assert response.status_code == 409
        assert all(r.method == "GET" for r in remote["calls"])


def test_store_client_cannot_reach_live_hosts_or_other_store_paths(management, monkeypatch):
    with patch("httpx.Client") as network:
        with pytest.raises(WebhookError):
            stores.request("GET", "/v1/delivery/store/" + str(uuid4()))
        monkeypatch.setattr(stores.api, "API_URL", "https://api.uber.com")
        with pytest.raises(WebhookError):
            stores.request("GET", "/v1/eats/stores")
        network.assert_not_called()


@pytest.mark.parametrize("missing", ["categories", "service_availability"])
def test_menu_confirmation_requires_categories_and_opening_hours(management, missing):
    with TestClient(runtime.app) as client, provider() as remote:
        result, _ = action(client, "menu_publicar")
        assert result.status_code == 200
        if missing == "categories":
            original = remote["menu"].pop("categories")
        else:
            original = remote["menu"]["menus"][0].pop("service_availability")
        state = current(client)
        assert not state["menu_publicado"] and state["requiere_conciliacion"]
        if missing == "categories":
            remote["menu"]["categories"] = original
        else:
            remote["menu"]["menus"][0]["service_availability"] = original
        assert current(client)["menu_publicado"]
        assert len([r for r in remote["calls"] if r.method == "PUT"]) == 1


@pytest.mark.parametrize("broken", [
    {"items": [{"id": stores.ITEM_IDS[0], "price_info": []}]},
    {"menus": [{"id": "test", "category_ids": [1]}]},
    {"categories": [{"id": "test", "entities": [None]}]},
    {"menus": [{"id": "test", "service_availability": [None]}]},
])
def test_malformed_menu_is_rejected_without_internal_details(management, broken):
    with TestClient(runtime.app), pytest.raises(stores.StoreAPIError):
        stores.menu_signature(broken)


def test_expired_authorization_never_exchanges_or_reflects_code(management):
    with TestClient(runtime.app) as client, provider() as remote:
        result = client.post(BASE + "/oauth/iniciar", headers=AUTH).json()
        state = parse_qs(urlsplit(result["url"]).query)["state"][0]
        with management[1]() as db:
            db.query(UberSandboxStore).update({"oauth_state_expires": datetime.now(timezone.utc) - timedelta(seconds=1)})
            db.commit()
        result = client.get("/sandbox/oauth/callback", params={"code": "private-test-code", "state": state})
        assert result.status_code == 400 and "private-test-code" not in result.text
        assert remote["tokens"] == []


def test_retrying_a_menu_job_after_uncertain_ack_never_repeats_the_put(management, monkeypatch):
    def uncertain(request, state):
        if request.method == "PUT":
            state["menu"] = json.loads(request.content)
            return httpx.Response(500)
    with TestClient(runtime.app) as client, provider(uncertain) as remote:
        payload = store_event("store.menu_refresh_request")
        assert receive(client, payload).status_code == 200
        monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_STORE_AUTOMATION_ENABLED", True)
        with management[1]() as db:
            for _ in range(2):
                db.query(UberSandboxStoreJob).update({"updated_at": datetime.now(timezone.utc) - timedelta(minutes=1)})
                db.commit()
                assert stores.process_job(db)
            assert db.query(UberSandboxStoreJob).one().state == "done"
            assert db.query(UberSandboxStoreAction).one().state == "conciliada"
            assert not db.query(UberSandboxStore).one().pending_request_key
        assert len([r for r in remote["calls"] if r.method == "PUT"]) == 1


def test_revoked_store_cannot_accept_or_mark_order_ready(management, monkeypatch):
    from app.services import uber_order_service as orders
    with TestClient(runtime.app) as client, provider() as remote:
        assert receive(client, store_event("store.deprovisioned")).status_code == 200
        monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_STORE_AUTOMATION_ENABLED", True)
        with management[1]() as db:
            for kind in ("aceptar", "listo"):
                with pytest.raises(WebhookError, match="revocada"):
                    orders.submit_action(db, uuid4(), uuid4(), kind, None, True, "0" * 64)
        assert remote["calls"] == []
