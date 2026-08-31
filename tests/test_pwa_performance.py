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

    assert "const CACHE_NAME = 'jacaranda-v88'" in sw
    assert "request.headers.has('Authorization')" in sw
    assert "offlineApiResponse" in sw
    assert "'Cache-Control': 'no-store'" in sw
    assert "fetch(event.request, {cache: 'no-store'})" in sw
    assert "Promise.all(STATIC_ASSETS.map" in sw
    assert "cache.add(asset).catch" in sw
    assert "client.navigate(client.url)" not in sw


def test_frontend_api_cache_is_short_lived_and_not_persistent():
    html = read_text("docs/index.html")

    assert "var APP_BUILD = 'jacaranda-v88'" in html
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
    refresh_segment = segment_between(html, "function refreshAccessToken()", "function filenameFromDisposition")

    assert "function esErrorTemporal" in html
    assert "function marcarApiTemporalmenteNoDisponible" in html
    assert "Mantengo tu sesi" in html
    assert "cerrarSesion();" in api_segment
    assert "if (r.status === 401)" in api_segment
    assert "marcarApiTemporalmenteNoDisponible(netErr)" in api_segment
    assert "marcarApiTemporalmenteNoDisponible(timeoutErr)" in api_segment
    assert "var versionSesionRefresh = _versionSesion" in refresh_segment
    assert "var refreshTokenSolicitado = REFRESH_TOKEN" in refresh_segment
    assert "function sesionRefreshSigueActiva()" in refresh_segment
    assert refresh_segment.index("if (!sesionRefreshSigueActiva())") < refresh_segment.index("cerrarSesion()")


def test_offline_sales_queue_keeps_failures_and_avoids_background_auth_tokens():
    html = read_text("docs/index.html")
    sync_segment = segment_between(
        html,
        "function sincronizarVentas",
        "function recuperarVentasIndexedDB",
    )
    queue_merge_segment = segment_between(
        html,
        "function claveVentaPendienteCompartida",
        "function sincronizarVentas",
    )
    payload_segment = segment_between(
        html,
        "function payloadVentaPendiente",
        "function sincronizarVentas",
    )
    recovery_segment = segment_between(
        html,
        "function recuperarVentasIndexedDB",
        "recuperarVentasIndexedDB();",
    )
    review_segment = segment_between(
        html,
        "async function revisarSiguienteVentaLegacy",
        "function sincronizarVentas",
    )
    sw = read_text("docs/sw.js")
    logout_segment = segment_between(html, "function cerrarSesion()", "async function confirmarCerrarSesion")
    login_segment = segment_between(html, "function login(email, pass)", "function togglePassword")
    session_tasks_segment = segment_between(
        html,
        "function invalidarTareasSesion()",
        "function moduloDesactivado",
    )

    assert "fallidas.push(venta)" in sync_segment
    assert "fusionarVentasPendientesCompartidas(pending, fallidas)" in sync_segment
    assert "leerVentasPendientesLocal()" in queue_merge_segment
    assert "procesadasPorClave" in queue_merge_segment
    assert "fallidasPorClave" in queue_merge_segment
    assert "var sesionSync = _versionSesion" in sync_segment
    assert "function sesionCambioDuranteSync()" in sync_segment
    assert "if (sesionCancelada || sesionCambioDuranteSync()) return" in sync_segment
    assert ", false, null, sesionSync)" in sync_segment
    assert "guardarVentasPendientesLocal()" in sync_segment
    assert "body.referencia_pago = venta.referencia_pago" in payload_segment
    assert "localStorage.removeItem('jacaranda_ventas_pendientes')" not in sync_segment
    assert "function guardarVentaIndexedDB" not in html
    assert "sync-ventas" not in html
    assert "sync-ventas" not in sw
    assert "syncOfflineVentas" not in sw
    assert "Authorization" not in recovery_segment
    assert "item.headers" not in recovery_segment
    assert "_ventasLegacyRevision.push" in recovery_segment
    assert "ventaLimpia = payloadVentaPendiente(venta)" in recovery_segment
    assert "db.transaction('pending-sales', 'readwrite')" in recovery_segment
    assert "var versionSesionMigracion = _versionSesion" in recovery_segment
    assert "function sesionCambioDuranteMigracion()" in recovery_segment
    assert "emparejarVentasLegacyIndexedDB(registros)" in recovery_segment
    assert "_ventasPendientes = fusionarVentasPendientesCompartidas([], [])" in recovery_segment
    assert "_ventasLegacyRevision = fusionarVentasLegacyCompartidas()" in recovery_segment
    assert recovery_segment.index("fusionarVentasPendientesCompartidas([], [])") < recovery_segment.index(
        "var ventasGuardadas = guardarVentasPendientesLocal()"
    )
    assert "if (!completa) revertirVentasMigradas()" in recovery_segment
    assert "store.clear()" in recovery_segment
    assert "indexedDB.deleteDatabase('jacaranda-offline')" not in recovery_segment
    assert "if (!ventasGuardadas || !legacyGuardadas)" in recovery_segment
    assert "tx.abort()" in recovery_segment
    assert "tx.onabort = function() { finalizarMigracion(false); }" in recovery_segment
    assert "claveIdempotenciaVentaLegacy(item)" in review_segment
    assert "confirmarAccion({" in review_segment
    assert "var versionSesionRevision = _versionSesion" in review_segment
    assert review_segment.count("if (!revisionLegacySigueActiva()) return") == 3
    assert review_segment.count("recargarColasVentasCompartidas()") == 3
    assert "moverVentasLocalesLegacyARevision();" in sync_segment
    assert "var total = _ventasPendientes.length + _ventasLegacyRevision.length" in html
    assert "total === 1 ? 'venta pendiente' : 'ventas pendientes'" in html
    assert 'onclick="accionVentasPendientes()"' in html
    assert "function leerVentasPendientesLocal" in html
    assert "function moverVentasLocalesLegacyARevision()" in html
    assert "moverVentasLocalesLegacyARevision();" in html
    assert "if (valida && venta.idempotency_key)" in html
    assert "_apiGetCache = {}" in logout_segment
    assert "invalidarTareasSesion()" in logout_segment
    assert "resolverConfirmacion(false)" in logout_segment
    assert "resolverEntrada(false)" in logout_segment
    assert "cancelarAdminAuth()" in logout_segment
    assert "invalidarTareasSesion()" in login_segment
    assert "_versionSesion++" in session_tasks_segment
    assert "tx.abort()" in session_tasks_segment
    assert "_ventasLegacyRevision = []" in logout_segment
    assert "{type: 'CLEAR_AUTH_DATA'}" in logout_segment


def test_offline_sale_retry_never_crosses_into_a_new_session():
    html = read_text("docs/index.html")
    api_segment = segment_between(html, "function api(method, path", "function apiPublic")
    sync_segment = segment_between(
        html,
        "function sincronizarVentas",
        "function recuperarVentasIndexedDB",
    )

    assert "versionSesionEsperada" in api_segment
    assert "function sesionSolicitudSigueActiva()" in api_segment
    assert "errorSesionSolicitudCambiada()" in api_segment
    assert "api(method, path, body, true, extraHeaders, versionSesionEsperada)" in api_segment
    assert api_segment.index("if (!sesionSolicitudSigueActiva())") < api_segment.index(
        "refreshAccessToken()"
    )
    assert ", false, null, sesionSync)" in sync_segment


def test_legacy_sale_matching_uses_complete_payload_and_nearest_timestamp():
    html = read_text("docs/index.html")
    matching_segment = segment_between(
        html,
        "function huellaVentaLegacy",
        "function moverVentasLocalesLegacyARevision",
    )

    assert "var payload = payloadVentaPendiente(venta || {})" in matching_segment
    assert "delete payload.idempotency_key" in matching_segment
    assert "function ordenarValorHuella" in matching_segment
    assert "Object.keys(valor).sort()" in matching_segment
    assert "diferencia <= 30000" in matching_segment
    assert "candidatos.sort" in matching_segment
    assert "a.diferencia - b.diferencia" in matching_segment
    assert "indexedEmparejadas[candidato.indexedKey]" in matching_segment
    assert "localesUsadas[candidato.localKey]" in matching_segment


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
    assert "function initNavDropdowns" in html
    assert "trigger.addEventListener('touchend', activar, {passive: false})" in html
    assert "aria-expanded" in html
    assert "mobileMenuOpenedAt > 450" in html


def test_frontend_defaults_to_pos_when_opening_app():
    html = read_text("docs/index.html")
    initial_segment = segment_between(
        html,
        "function pantallaInicialUsuario",
        "function irInicio",
    )
    cached_start_segment = segment_between(
        html,
        "function mostrarInicioGuardado",
        "function aplicarPostLogin",
    )

    assert "var APP_DEFAULT_PAGE = 'pos';" in html
    assert "return moduloInicioUsuario(u);" in initial_segment
    assert "localStorage.getItem('jacaranda_tab')" not in initial_segment
    assert "var tab = u ? pantallaInicialUsuario(u) : APP_DEFAULT_PAGE;" in cached_start_segment


def test_frontend_keeps_dashboard_access_without_making_it_default():
    html = read_text("docs/index.html")
    dashboard_segment = segment_between(
        html,
        "function moduloDashboardUsuario",
        "function reportarErrorPagina",
    )

    assert '>Dashboard</a>' in html
    assert '<span class="mn-label">Dashboard</span>' in html
    assert 'aria-label="Ver dashboard"' in html
    assert "function moduloDashboardUsuario" in html
    assert "if (puedeVerModuloUsuario(usuario, 'dash')) return 'dash';" in dashboard_segment
    assert "go(moduloDashboardUsuario());" in dashboard_segment
    assert "var APP_DEFAULT_PAGE = 'pos';" in html


def test_frontend_has_manual_installed_app_refresh():
    html = read_text("docs/index.html")
    refresh_segment = segment_between(
        html,
        "async function actualizarAppInstalada",
        "// ─── PDF Downloads",
    )

    assert 'id="btn-update-app"' in html
    assert "Actualizar app" in html
    assert "function mostrarBotonActualizarApp" in html
    assert "function limpiarCacheAppInstalada" in html
    assert "sessionStorage.setItem('jacaranda_app_refresh_pending'" in html
    assert "navigator.serviceWorker.getRegistrations" in html
    assert "registration.unregister()" in html
    assert "caches.keys()" in html
    assert "_jc_refresh" in html
    assert "confirmarAccion({" in refresh_segment
    assert "confirm(" not in refresh_segment
    assert "alert(" not in refresh_segment


def test_inventory_does_not_eager_load_hidden_ingredients_or_recipes():
    html = read_text("docs/index.html")
    inventory_segment = segment_between(
        html,
        "function cargarInventarioCompleto",
        "// ─── Edit modals",
    )

    assert "return cargarProductos();" in inventory_segment
    assert "cargarIngredientes()" not in inventory_segment
    assert "cargarRecetas()" not in inventory_segment


def test_core_sensitive_cleanup_preserves_static_cache_and_clears_offline_db():
    core = read_text("docs/js/jacaranda-core.js")

    assert "function clearSensitiveCaches" in core
    assert "jacaranda_prods_cache" in core
    assert "jacaranda_ventas_legacy_revision" in core
    assert "indexedDB.deleteDatabase('jacaranda-offline')" in core
    assert "jacaranda-(auth|api|data|offline)" in core
    assert "caches.delete(name)" in core
