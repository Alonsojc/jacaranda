"""History recovery uses simulated transport, never real sales or credentials."""

import shutil
import subprocess
from pathlib import Path

import pytest


HTML = Path("docs/index.html").read_text(encoding="utf-8")


def section(start, end):
    offset = HTML.index(start)
    return HTML[offset:HTML.index(end, offset)]


def node(script):
    executable = shutil.which("node")
    if not executable:
        pytest.skip("Node required for frontend execution")
    result = subprocess.run(
        [executable, "-e", script], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr


API_HARNESS = r"""
const assert = require('node:assert/strict');
const window = {AbortController};
let API_URL = 'https://api.test', TOKEN = 'test', REFRESH_TOKEN = '';
let _versionSesion = 1, _apiGetInFlight = {};
const API_TIMEOUT_MS = 25000;
const timers = new Map(), requests = [], failures = [];
let timerId = 0, expired = 0, available = 0;
let fetchImpl, delayImpl = fn => queueMicrotask(fn);
function setTimeout(fn, ms) {
  const id = ++timerId;
  if (ms === 600) delayImpl(fn);
  else timers.set(id, {fn, ms});
  return id;
}
function clearTimeout(id) { timers.delete(id); }
function apiGetCacheTtl() { return 0; }
function apiGetCacheWrite() {}
function apiCacheInvalidate() {}
function marcarApiDisponible() { available++; }
function marcarApiTemporalmenteNoDisponible(e, opts) {
  if (!opts || !opts.silenciosa) failures.push(e);
}
function expirarSesion() { expired++; _versionSesion++; }
function refreshAccessToken() { TOKEN = 'refreshed'; return Promise.resolve(); }
function fetch(url, opts) { requests.push({url, opts}); return fetchImpl(url, opts); }
function response(status, data) {
  return {ok: status < 400, status, text: () => Promise.resolve(
    typeof data === 'string' ? data : JSON.stringify(data))};
}
async function flush() { for (let i = 0; i < 12; i++) await Promise.resolve(); }
""" + section("function leerRespuestaJson(r)", "function loadScriptOnce") + section(
    "function errorSesionSolicitudCambiada()", "function apiPublic"
)


@pytest.mark.parametrize("failure", [0, 502, 503, 504])
def test_history_retries_transient_read_once_without_expiring_session(failure):
    node(API_HARNESS + f"const status = {failure};" + r"""
(async () => {
  fetchImpl = () => requests.length === 1
    ? (status === 0 ? Promise.reject(new TypeError('Failed to fetch'))
      : Promise.resolve(response(status, {detail:'temporary'})))
    : Promise.resolve(response(200, [{id:10}]));
  assert.deepEqual(await apiLecturaRecuperable('/history'), [{id:10}]);
  assert.equal(requests.length, 2);
  assert.ok(requests.every(r => r.opts.method === 'GET'));
  assert.equal(expired, 0);
  assert.equal(failures.length, 0);
  assert.equal(timers.size, 0);
})().catch(e => { console.error(e); process.exitCode = 1; });
""")


@pytest.mark.parametrize("status", [400, 403, 404, 429])
def test_history_does_not_retry_permission_validation_or_rate_limit_errors(status):
    node(API_HARNESS + f"const status = {status};" + r"""
(async () => {
  fetchImpl = () => Promise.resolve(response(status, {detail:'not allowed'}));
  await assert.rejects(apiLecturaRecuperable('/history'), e => e.status === status);
  assert.equal(requests.length, 1);
  assert.equal(expired, 0);
  assert.equal(timers.size, 0);
})().catch(e => { console.error(e); process.exitCode = 1; });
""")


def test_read_recovery_is_bounded_and_never_replays_cancellation():
    node(API_HARNESS + r"""
(async () => {
  fetchImpl = () => Promise.resolve(response(503, {detail:'temporary'}));
  await assert.rejects(apiLecturaRecuperable('/history'), e => e.status === 503);
  assert.equal(requests.length, 2);
  assert.equal(failures.length, 1);
  assert.equal(expired, 0);
  requests.length = failures.length = 0;
  await assert.rejects(api('POST', '/sales/10/cancel', {motivo:'test only'}));
  assert.equal(requests.length, 1);
  assert.equal(requests[0].opts.method, 'POST');
})().catch(e => { console.error(e); process.exitCode = 1; });
""")


def test_json_body_read_stays_timed_and_invalid_success_is_not_cached():
    node(API_HARNESS + r"""
(async () => {
  fetchImpl = () => Promise.resolve(response(200, '<html>bad gateway</html>'));
  await assert.rejects(api('GET', '/invalid'), e => e.code === 'INVALID_RESPONSE');
  assert.equal(available, 0);
  assert.equal(timers.size, 0);
  assert.deepEqual(await leerRespuestaJson(response(204, '')), {});
  let bodyStarted;
  const started = new Promise(resolve => bodyStarted = resolve);
  fetchImpl = (_, opts) => Promise.resolve({ok:true, status:200, text: () => {
    bodyStarted();
    return new Promise((resolve, reject) => opts.signal.addEventListener('abort', () => {
      const e = new Error('aborted'); e.name = 'AbortError'; reject(e);
    }));
  }});
  const reading = api('GET', '/stalled-body', null, false, null, null, {timeoutMs:8000});
  await started;
  assert.equal(timers.size, 1);
  const timer = [...timers.values()][0];
  assert.equal(timer.ms, 8000);
  timer.fn();
  await assert.rejects(reading, e => e.status === 504);
  assert.equal(timers.size, 0);
})().catch(e => { console.error(e); process.exitCode = 1; });
""")


def test_read_recovery_stops_at_session_change_and_preserves_auth_refresh():
    node(API_HARNESS + r"""
(async () => {
  let continueDelay;
  delayImpl = fn => continueDelay = fn;
  fetchImpl = () => Promise.resolve(response(503, {detail:'temporary'}));
  const reading = apiLecturaRecuperable('/history');
  await flush();
  assert.equal(typeof continueDelay, 'function');
  _versionSesion++;
  continueDelay();
  await assert.rejects(reading, e => e.code === 'SESSION_CHANGED');
  assert.equal(requests.length, 1);
  assert.equal(failures.length, 0);
  requests.length = 0;
  REFRESH_TOKEN = 'test-refresh';
  fetchImpl = () => Promise.resolve(requests.length === 1
    ? response(401, {detail:'refresh needed'}) : response(200, {id:10}));
  assert.deepEqual(await apiLecturaRecuperable('/history'), {id:10});
  assert.equal(requests.length, 2);
  assert.equal(requests[1].opts.headers.Authorization, 'Bearer refreshed');
  assert.equal(expired, 0);
  REFRESH_TOKEN = '';
  fetchImpl = () => Promise.resolve(response(401, {detail:'expired'}));
  await assert.rejects(api('GET', '/history'), e => e.status === 401);
  assert.equal(expired, 1);
})().catch(e => { console.error(e); process.exitCode = 1; });
""")


UI_HARNESS = r"""
const assert = require('node:assert/strict');
const fields = {};
const window = {_permisos:{pos:'editar'}};
const document = {getElementById: id => fields[id] ||= {
  value:'', textContent:'old', innerHTML:'old', style:{}, disabled:false,
  classList:{on:false, add() {this.on=true;}, remove() {this.on=false;}, contains() {return this.on;}}
}};
let _versionSesion = 1, _ultimoTicket = {folio:'old'}, _mtVentaId, _mtFolio;
let _histVentas = [{id:999}], _histVentasCargaSeq = 0, _histVentasCargando = false;
const reads = [], rendered = [], mutations = [];
function escHtml(v) { return String(v).replace(/</g, '&lt;'); }
function toast() {}
function actionBtn(label, icon, action) { return '<button onclick="' + action + '">' + label + '</button>'; }
function apiLecturaRecuperable(path) { return new Promise((resolve,reject) => reads.push({path, resolve, reject})); }
function renderTicket(tk) { rendered.push(tk.folio); }
function renderHistVentas() { rendered.push(_histVentas.map(v => v.id)); }
function solicitarEntrada() { return Promise.resolve('test reason'); }
function confirmarAccion() { return Promise.resolve(true); }
function apiCritica(...args) { mutations.push(args); return Promise.resolve(); }
function cerrarModal() {}
function cargarCorte() {}
function cargarPOSProductos() {}
"""


def test_ticket_read_resets_stale_data_and_ignores_out_of_order_or_closed_modal():
    node(UI_HARNESS + section("function cargaTicketVigente", "function mostrarTicket")
         + section("var _ventaActualId", "async function cancelarVentaActual") + r"""
(async () => {
  const a = verTicket(1, false);
  assert.equal(_ultimoTicket, null);
  assert.equal(document.getElementById('mt-cancel-wrap').style.display, 'none');
  const b = verTicket(2, true);
  reads[1].resolve({folio:'T-2', productos:[]}); await b;
  reads[0].resolve({folio:'T-1', productos:[]}); await a;
  assert.equal(_ultimoTicket.folio, 'T-2');
  assert.deepEqual(rendered, ['T-2']);
  assert.equal(document.getElementById('mt-cancel-wrap').style.display, 'none');
  const c = verTicket(3, false);
  reads[2].reject(new Error('temporary')); await c;
  assert.equal(_ultimoTicket, null);
  assert.ok(document.getElementById('mt-detalles').innerHTML.includes('Reintentar'));
  const d = verTicket(4, false);
  document.getElementById('modal-ticket').classList.remove('on');
  reads[3].resolve({folio:'T-4', productos:[]}); await d;
  assert.equal(_ultimoTicket, null);
  const e = verTicket(5, false);
  _versionSesion++;
  reads[4].resolve({folio:'T-5', productos:[]}); await e;
  assert.equal(_ultimoTicket, null);
  const f = verTicket(6, false);
  _ventaActualId = 7;
  reads[5].resolve({folio:'T-6', productos:[]}); await f;
  assert.equal(_ultimoTicket, null);
})().catch(e => { console.error(e); process.exitCode = 1; });
""")


def test_history_loading_error_and_latest_request_state_are_recoverable():
    node(UI_HARNESS + section("function cargarHistVentas()", "function renderHistVentas()") + r"""
(async () => {
  document.getElementById('hv-fi').value = '2026-10-01';
  document.getElementById('hv-ff').value = '2026-10-06';
  const a = cargarHistVentas();
  assert.equal(document.getElementById('hv-consultar').disabled, true);
  assert.deepEqual(_histVentas, []);
  filtrarHistVentas(); assert.deepEqual(rendered, []);
  const b = cargarHistVentas();
  reads[0].resolve([{id:1}]); await a;
  assert.equal(document.getElementById('hv-consultar').disabled, true);
  reads[1].resolve([{id:2}]); await b;
  assert.deepEqual(_histVentas, [{id:2}]);
  assert.equal(document.getElementById('hv-consultar').disabled, false);
  const c = cargarHistVentas();
  reads[2].reject(new Error('temporary')); await c;
  assert.equal(document.getElementById('hv-consultar').disabled, false);
  assert.ok(document.getElementById('hv-list').innerHTML.includes('Reintentar'));
  filtrarHistVentas();
  assert.ok(document.getElementById('hv-list').innerHTML.includes('Reintentar'));
  const d = cargarHistVentas();
  _versionSesion++;
  reads[3].resolve([{id:3}]); await d;
  assert.deepEqual(_histVentas, []);
  assert.equal(document.getElementById('hv-consultar').disabled, false);
})().catch(e => { console.error(e); process.exitCode = 1; });
""")


def test_cancellation_is_disabled_until_the_selected_ticket_is_loaded():
    node(UI_HARNESS + "let _ventaActualId = 10; function cargarHistVentas() {}\n" + section(
        "async function cancelarVentaActual()", "function textoTicketParaEasyPos"
    ) + r"""
(async () => {
  _ultimoTicket = null;
  await cancelarVentaActual();
  assert.equal(mutations.length, 0);
  _ultimoTicket = {folio:'T-10'};
  await cancelarVentaActual();
  assert.equal(mutations.length, 1);
  assert.equal(mutations[0][0], 'POST');
  assert.equal(mutations[0][1], '/punto-de-venta/ventas/10/cancelar');
})().catch(e => { console.error(e); process.exitCode = 1; });
""")


def test_notifications_use_the_grouped_backend_contract_and_keep_critical_alerts():
    node(UI_HARNESS + r"""
let _notifCache = [];
const pushes = [];
function enviarNotifLocal(...args) { pushes.push(args); }
""" + section("function normalizarNotificaciones(data)", "function setPushStatus") + r"""
const data = {stock_bajo:[{severidad:'critica', nombre:'<test>', stock_actual:0, stock_minimo:2}],
  pedidos_pendientes:[{severidad:'alta', pedido_id:10, razon:'Entrega hoy', cliente:'Test'}],
  productos_sin_receta:[{severidad:'alta', nombre:'Test', razon:'Sin receta'}],
  productos_sin_costo:[], recetas_sin_ingredientes:[], caducidades:[],
  merma_hoy:{total_movimientos:0}};
actualizarNotificaciones(data, true);
assert.equal(_notifCache.length, 3);
assert.equal(document.getElementById('notif-badge').textContent, 3);
assert.equal(pushes.length, 1);
assert.ok(document.getElementById('notif-list').innerHTML.includes('&lt;test>'));
actualizarNotificaciones(data, true);
assert.equal(pushes.length, 1);
assert.throws(() => normalizarNotificaciones({}), /alertas/);
assert.equal(_notifCache.length, 3);
""")


def test_background_polling_never_marks_the_whole_application_offline():
    for start, end in (
        ("function iniciarNotifPeriodicas()", "var _lcdClienteId"),
        ("function iniciarPollPedidos()", "function seleccionarRepTab"),
    ):
        source = section(start, end)
        assert "!TOKEN || document.hidden" in source
        assert "{silenciosa: true}" in source
