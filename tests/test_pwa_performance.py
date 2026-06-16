"""Tests para Sprint 8: PWA, cache seguro y estabilidad movil."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def segment_between(text: str, start: str, end: str) -> str:
    start_idx = text.index(start)
    end_idx = text.index(end, start_idx)
    return text[start_idx:end_idx]


def test_api_responses_are_not_cached(client, auth_headers):
    response = client.get("/api/v1/auth/me", headers=auth_headers)

    assert response.status_code == 200
    assert "no-store" in response.headers["cache-control"].lower()
    assert response.headers["pragma"] == "no-cache"


def test_cors_allows_legacy_no_store_request_headers(client):
    response = client.options(
        "/api/v1/auth/me",
        headers={
            "Origin": "https://alonsojc.github.io",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": (
                "authorization,content-type,cache-control,pragma"
            ),
        },
    )

    assert response.status_code == 200
    allowed = response.headers["access-control-allow-headers"].lower()
    assert "authorization" in allowed
    assert "content-type" in allowed
    assert "cache-control" in allowed
    assert "pragma" in allowed


def test_service_worker_never_caches_authenticated_api_data():
    sw = read_text("docs/sw.js")

    assert "const CACHE_NAME = 'jacaranda-v80'" in sw
    assert "request.headers.has('Authorization')" in sw
    assert "offlineApiResponse" in sw
    assert "'Cache-Control': 'no-store'" in sw
    assert "fetch(event.request, {cache: 'no-store'})" in sw
    assert "Promise.all(STATIC_ASSETS.map" in sw
    assert "cache.add(asset).catch" in sw
    assert "client.navigate(client.url)" not in sw


def test_frontend_api_cache_is_short_lived_and_not_persistent():
    html = read_text("docs/index.html")

    assert "var APP_BUILD = 'jacaranda-v80'" in html
    assert "function apiGetCacheTtl(path)" in html
    assert "if (clean === '/inventario/productos') return 45000" in html
    assert "if (clean === '/pedidos/reservas') return 15000" in html
    assert "function guardarCacheLocalJson" in html
    assert "function leerCacheLocalJson" in html
    assert "cache: 'no-store'" in html
    assert "function leerRespuestaJson" in html
    assert "localStorage.setItem('jacaranda_prods_cache'" not in html


def test_frontend_no_store_does_not_add_disallowed_cors_headers():
    html = read_text("docs/index.html")
    api_segment = segment_between(html, "function api(method, path", "function apiPublic")
    public_segment = segment_between(html, "function apiPublic", "function codigoTarjetaDesdeTexto")

    assert "cache: 'no-store'" in api_segment
    assert "'Cache-Control':'no-store'" not in api_segment
    assert "'Pragma':'no-cache'" not in api_segment
    assert "'Cache-Control':'no-store'" not in public_segment
    assert "'Pragma':'no-cache'" not in public_segment


def test_frontend_keeps_session_during_temporary_server_errors():
    html = read_text("docs/index.html")
    api_segment = segment_between(html, "function api(method, path", "function apiPublic")

    assert "function esErrorTemporal" in html
    assert "function marcarApiTemporalmenteNoDisponible" in html
    assert "Mantengo tu sesi" in html
    assert "cerrarSesion();" in api_segment
    assert "if (r.status === 401)" in api_segment
    assert "marcarApiTemporalmenteNoDisponible(netErr)" in api_segment
    assert "marcarApiTemporalmenteNoDisponible(timeoutErr)" in api_segment


def test_offline_queue_does_not_persist_bearer_tokens():
    html = read_text("docs/index.html")
    queue_segment = segment_between(
        html,
        "function guardarVentaIndexedDB",
        "function sanearVentasIndexedDB",
    )
    logout_segment = segment_between(html, "function cerrarSesion()", "async function confirmarCerrarSesion")

    assert "Authorization" not in queue_segment
    assert "function sanearVentasIndexedDB" in html
    assert "delete item.headers.Authorization" in html
    assert "_apiGetCache = {}" in logout_segment
    assert "{type: 'CLEAR_AUTH_DATA'}" in logout_segment


def test_mobile_navigation_has_loading_feedback_and_guarded_pull_refresh():
    html = read_text("docs/index.html")

    assert '<div class="app-status" id="app-status"' in html
    assert ".page-load-chip" in html
    assert "function programarCargaPagina" in html
    assert "function go(p, opts)" in html
    assert "go(pg, {force: true})" in html
    assert "function esTargetPullRefreshSeguro" in html
    assert "deltaX < 60" in html
    assert "@media(hover:none)" in html
    assert "mobileMenuOpenedAt > 450" in html


def test_inventory_loads_heavy_recipe_data_after_essential_data():
    html = read_text("docs/index.html")
    inventory_segment = segment_between(
        html,
        "function cargarInventarioCompleto",
        "// ─── Edit modals",
    )

    assert "Promise.all" in inventory_segment
    assert "cargarProductos()" in inventory_segment
    assert "cargarIngredientes()" in inventory_segment
    assert "setTimeout(function()" in inventory_segment
    assert "cargarRecetas()" in inventory_segment


def test_core_sensitive_cleanup_preserves_static_cache_and_clears_offline_db():
    core = read_text("docs/js/jacaranda-core.js")

    assert "function clearSensitiveCaches" in core
    assert "jacaranda_prods_cache" in core
    assert "indexedDB.deleteDatabase('jacaranda-offline')" in core
    assert "jacaranda-(auth|api|data|offline)" in core
    assert "caches.delete(name)" in core
