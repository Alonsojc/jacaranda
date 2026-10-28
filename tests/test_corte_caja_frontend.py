"""Regresiones de las acciones de corte de caja desde iPad/iPhone."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest


HTML = Path("docs/index.html").read_text(encoding="utf-8")


def test_cash_closing_surface_has_print_and_lifecycle_actions():
    assert 'id="modal-corte-registrado"' in HTML
    assert "Imprimir corte" in HTML
    assert 'id="modal-corte-editar"' in HTML
    assert "function guardarEdicionCorte" in HTML
    assert "function reabrirCorte" in HTML
    assert "function cancelarCorte" in HTML
    assert "Último corte: turno" in HTML
    assert "Ventas del turno" in HTML
    assert "Registrar corte · Turno" in HTML
    assert "/punto-de-venta/corte-caja/ventas?fecha=" in HTML
    assert "function apiProtegidaConPasswordAdmin" in HTML
    assert "apiProtegidaConPasswordAdmin('PUT'" in HTML
    assert "apiProtegidaConPasswordAdmin('POST'" in HTML


def test_cash_closing_actions_require_reason_and_confirmation():
    start = HTML.index("async function cambiarEstadoCorte")
    end = HTML.index("function reabrirCorte", start)
    lifecycle = HTML[start:end]

    assert "solicitarEntrada" in lifecycle
    assert "confirmarAccion" in lifecycle
    assert "motivo.length < 5" in lifecycle
    assert "apiProtegidaConPasswordAdmin('POST'" in lifecycle


def test_cash_closing_controls_are_compact_and_touchable():
    assert "#btn-update-app{width:48px;min-width:48px;height:48px" in HTML
    assert 'id="c-corte-acciones" class="corte-actions"' in HTML
    assert "action-buttons corte-actions" in HTML
    assert ".corte-actions .action-btn{min-width:0" in HTML


def test_cash_handover_controls_and_print_paths():
    for prefix in ("c", "mce"):
        for field in ("retiro", "fondo-entregado", "recibido-por"):
            assert f'id="{prefix}-{field}"' in HTML
    assert "function actualizarResguardoCorte" in HTML
    assert "function datosEntregaCorte" in HTML
    assert "Recibido por (resguardo)" in HTML
    assert "imprimirCorteEasyPos(_ultimoCorteRegistrado)" in HTML
    assert "imprimirCorteEasyPos(' + corte.id" in HTML
    assert "corte.fondo_entregado != null" in HTML
    assert "corte.retiros" in HTML
    assert "corte.recibido_por" in HTML
    assert "r.entrega_efectivo_disponible !== true" in HTML
    assert HTML.count("var guardado = corteGuardadoParaExportar();") == 2
    assert HTML.count("textoCorteParaWhatsApp(corteActualParaCompartir())") == 2
    assert "if (!fondoEntregadoInput.dataset.editado)" in HTML
    assert "this.dataset.editado='1';actualizarResguardoCorte('c')" in HTML


def test_cash_handover_math_validation_and_receipt_text():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to execute frontend helpers")

    def section(start, end):
        offset = HTML.index(start)
        return HTML[offset:HTML.index(end, offset)]

    helpers = section("function actualizarResguardoCorte", "function realizarCorte")
    thermal = section("function textoTicketTermico", "function textoCorteParaEasyPos")
    receipt = section("function textoCorteParaEasyPos", "function imprimirCorteActual")
    js = r"""
const assert = require('node:assert/strict');
const fields = {};
const document = {getElementById: id => fields[id]};
function fmt(n) { return Number(n).toFixed(2); }
function formatearInstanteOperacion() { return '05/10/2026 12:00'; }
function fechaISOOperacion(v) { return v.slice(0, 10); }
function fechaHoyISO() { return '2026-10-05'; }
let _corteActual = null;
let _ultimoCorteRegistrado = null;
let _corteVentas = [];
""" + helpers + thermal + receipt + r"""
fields['c-real'] = {value: '5000'};
fields['c-fondo-entregado'] = {value: '2000'};
fields['c-retiro'] = {value: ''};
fields['c-recibido-por'] = {value: '  Alonso  '};
actualizarResguardoCorte('c');
assert.equal(fields['c-retiro'].value, '3000.00');
assert.deepEqual(datosEntregaCorte('c', 5000), {
  retiros: 3000, fondo_entregado: 2000, recibido_por: 'Alonso'
});
fields['c-fondo-entregado'].value = '6000';
assert.throws(() => datosEntregaCorte('c', 5000));
actualizarResguardoCorte('c');
assert.equal(fields['c-retiro'].value, '');
fields['c-fondo-entregado'].value = '2000';
fields['c-recibido-por'].value = '   ';
assert.throws(() => datosEntregaCorte('c', 5000));
assert.equal(datosEntregaCorte('c', 2000).retiros, 0);
fields['c-fondo-entregado'].value = '2000.10';
fields['c-recibido-por'].value = 'Alonso';
assert.equal(datosEntregaCorte('c', 5000.30).retiros, 3000.2);
fields['mce-fondo-entregado'] = {value: ''};
fields['mce-recibido-por'] = {value: ''};
assert.equal(datosEntregaCorte('mce', 5000).fondo_entregado, null);
const cut = {id: 1, turno: 1, fondo_inicial: 2000, total_ventas_efectivo: 3000,
  efectivo_esperado: 5000, efectivo_real: 5000, diferencia: 0, total_ventas: 3000,
  retiros: 3000, fondo_entregado: 2000, recibido_por: 'Alonso'};
const text = textoCorteParaEasyPos(cut);
assert.ok(text.includes('Retiro a resguardo'));
assert.ok(text.includes('$3000.00'));
assert.ok(text.includes('Fondo entregado al siguiente turno\n$2000.00'));
assert.ok(text.includes('Recibido por (resguardo):\nAlonso'));
assert.ok(text.endsWith('\n\n\n'));
cut.fecha = '2026-10-05T12:00:00Z';
_corteActual = cut;
fields['c-real'].value = '';
fields['c-fecha'] = {value: '2026-10-05'};
assert.equal(corteGuardadoParaExportar(), null);
_ultimoCorteRegistrado = cut;
assert.equal(corteGuardadoParaExportar(), cut);
_corteVentas = [{total: 100}];
assert.equal(corteGuardadoParaExportar(), null);
_corteVentas = [];
const csv = csvCorteGuardado(cut);
assert.ok(csv.includes('"Retiro a resguardo","3000"'));
assert.ok(csv.includes('"Recibido por (resguardo)","Alonso"'));
assert.ok(csv.includes('"Efectivo contado","5000"'));
cut.diferencia = -10;
assert.ok(csvCorteGuardado(cut).includes('"Diferencia","-10"'));
fields['c-real'].value = '2100';
assert.equal(corteGuardadoParaExportar(), null);
fields['c-real'].value = '';
fields['c-fecha'].value = '2026-10-04';
assert.equal(corteGuardadoParaExportar(), null);
cut.recibido_por = '=unsafe,"name"';
assert.ok(csvCorteGuardado(cut).includes("'=unsafe,"));
assert.ok(csvCorteGuardado(cut).includes('""name""'));
delete cut.fondo_entregado;
assert.ok(!textoCorteParaEasyPos(cut).includes('Retiro a resguardo'));
"""
    result = subprocess.run([node, "-e", js], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_cut_load_waits_for_both_requests_and_ignores_old_dates():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required")
    start = HTML.index("function cargarCorte()")
    load = HTML[start:HTML.index("function mostrarResumenCorte", start)]
    js = r"""
const assert = require('node:assert/strict');
const fields = {};
const document = {getElementById: id => fields[id] ||= {value:'',style:{},textContent:'',innerHTML:'',classList:{toggle(){}}}};
let _corteCargaSeq=0, _corteVistaLista=false, _resumenCorteVista=null, _versionSesion=1;
let _efTotal=0, _corteVentas=[], _corteActual=null, _totalVentasDia=0;
function actualizarVisibilidadFinanzasCorte() {}
function calcularDiferencia() { fields['mathLast'] = _efTotal; }
function cargarHistorialCortes() {}
function mostrarResumenCorte() { fields['btn-corte'].disabled=false; }
function fechaHoyISO() { return '2026-10-06'; }
function fechaDiasAntesISO() { return '2026-09-30'; }
function fmt(n) { return Number(n).toFixed(2); }
const requests=[];
function api(method,path) { return new Promise((resolve,reject)=>requests.push({path,resolve,reject})); }
function apiLecturaRecuperable(path) { return api('GET', path); }
function summary(date,total) { return {fecha:date,total_ventas_efectivo:total,total_ventas_tarjeta:0,
total_ventas_transferencia:0,total_ventas_clip:0,total_ventas_bbva:0,total_ventas:total,numero_ventas:0}; }
""" + load + r"""
async function run() {
  document.getElementById('c-fecha').value='2026-10-05';
  let old=cargarCorte();
  assert.equal(fields['c-ventas-fecha'].textContent,'lunes, 5 de octubre de 2026');
  assert.equal(fields['btn-imprimir-corte'].disabled,true);
  fields['c-fecha'].value='2026-10-06'; let latest=cargarCorte();
  assert.equal(fields['c-ventas-fecha'].textContent,'martes, 6 de octubre de 2026');
  requests[2].resolve([]); await Promise.resolve();
  assert.equal(_corteVistaLista,false);
  requests[3].resolve(summary('2026-10-06',502.5)); assert.equal(await latest,true);
  assert.equal(_efTotal,502.5); assert.equal(fields['mathLast'],502.5);
  assert.equal(fields['btn-imprimir-corte'].disabled,false);
  requests[0].resolve([]); requests[1].resolve(summary('2026-10-05',900)); await old;
  assert.equal(_efTotal,502.5);
  assert.equal(fields['c-ventas-fecha'].textContent,'martes, 6 de octubre de 2026');
  latest=cargarCorte(); requests[4].resolve([]); requests[5].reject(new Error('offline')); assert.equal(await latest,false);
  assert.equal(_corteVistaLista,false); assert.equal(_efTotal,null);
  assert.equal(fields['btn-corte'].disabled,true);
  assert.equal(fields['btn-imprimir-corte'].disabled,true);
  latest=cargarCorte();_versionSesion++;_efTotal=99;_corteVistaLista=true;
  requests[6].resolve([]);requests[7].resolve(summary('2026-10-06',500));
  assert.equal(await latest,false);assert.equal(_efTotal,99);assert.equal(_corteVistaLista,true);
}
run().catch(e=>{console.error(e);process.exit(1)});
"""
    result = subprocess.run([node, "-e", js], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_cut_payment_cards_keep_total_last_with_responsive_method_colors():
    start = HTML.index('<div class="row corte-kpis">')
    cards = HTML[start:HTML.index('<div class="row r2">', start)]
    fields = [
        "c-total-ef", "c-total-bbva", "c-total-trans",
        "c-total-clip", "c-total-tar", "c-total-general",
    ]
    positions = [cards.index(f'id="{field}"') for field in fields]
    assert positions == sorted(positions)
    assert "corte-kpi-efectivo" in cards
    assert "corte-kpi-bbva" in cards
    assert "corte-kpi-transferencia" in cards
    assert "corte-kpi-total" in cards
    assert ".corte-kpis{grid-template-columns:repeat(3,minmax(0,1fr))" in HTML
    assert ".corte-kpis{grid-template-columns:repeat(2,minmax(0,1fr))" in HTML
    assert ".corte-kpi-efectivo{--corte-color:#7a513d" in HTML
    assert ".corte-kpi-bbva{--corte-color:#1d4ed8" in HTML
    assert ".corte-kpi-transferencia{--corte-color:#946200" in HTML
    assert ".corte-kpi-total{--corte-color:#047857" in HTML
    assert ".corte-kpi.is-zero,.corte-kpi.is-loading{--corte-color:#6b7280" in HTML


def test_cut_payment_cards_clear_loading_and_zero_styles_without_changing_totals():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required")
    start = HTML.index("function actualizarKpisCorte")
    helper = HTML[start:HTML.index("function textoFechaVentasCorte", start)]
    js = r"""
const assert = require('node:assert/strict'), fields = {};
const document = {getElementById(id) {
  const classes = new Set();
  return fields[id] ||= {textContent:'',classList:{
    toggle(cls,on){if(on) classes.add(cls);else classes.delete(cls);},
    contains(cls){return classes.has(cls);}
  }};
}};
function fmt(n){return Number(n).toFixed(2);}
""" + helper + r"""
const summary = {total_ventas_efectivo:1425,total_ventas_bbva:2305,
  total_ventas_transferencia:0,total_ventas_clip:0,total_ventas_tarjeta:0,total_ventas:3730};
actualizarKpisCorte(null);
for(const id of ['ef','bbva','trans','clip','tar','general']) {
  assert.equal(fields['c-total-'+id].textContent,'--');
  assert(fields['c-total-'+id+'-card'].classList.contains('is-loading'));
  assert(!fields['c-total-'+id+'-card'].classList.contains('is-zero'));
}
actualizarKpisCorte(summary);
assert.equal(fields['c-total-ef'].textContent,'$1425.00');
assert.equal(fields['c-total-bbva'].textContent,'$2305.00');
assert.equal(fields['c-total-general'].textContent,'$3730.00');
for(const id of ['ef','bbva','general']) assert(!fields['c-total-'+id+'-card'].classList.contains('is-zero'));
for(const id of ['trans','clip','tar']) {
  assert.equal(fields['c-total-'+id].textContent,'$0.00');
  assert(fields['c-total-'+id+'-card'].classList.contains('is-zero'));
  assert(!fields['c-total-'+id+'-card'].classList.contains('is-loading'));
}
summary.total_ventas_transferencia=125.50;summary.total_ventas=3855.50;
actualizarKpisCorte(summary);
assert(!fields['c-total-trans-card'].classList.contains('is-zero'));
assert.equal(fields['c-total-trans'].textContent,'$125.50');
assert.equal(fields['c-total-general'].textContent,'$3855.50');
for(const field of Object.keys(summary)) summary[field]=0;
actualizarKpisCorte(summary);
assert(fields['c-total-ef-card'].classList.contains('is-zero'));
assert(fields['c-total-bbva-card'].classList.contains('is-zero'));
assert(!fields['c-total-general-card'].classList.contains('is-zero'));
assert.equal(fields['c-total-general'].textContent,'$0.00');
actualizarKpisCorte(null);
assert(!fields['c-total-ef-card'].classList.contains('is-zero'));
assert(fields['c-total-ef-card'].classList.contains('is-loading'));
"""
    result = subprocess.run([node, "-e", js], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("tz", ["UTC", "America/Mexico_City", "Pacific/Auckland"])
def test_shift_sales_heading_uses_selected_calendar_day_in_every_timezone(tz):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required")
    start = HTML.index("function textoFechaVentasCorte")
    helper = HTML[start:HTML.index("function mostrarResumenCorte", start)]
    script = "const assert=require('node:assert/strict');\n" + helper + r"""
assert.equal(textoFechaVentasCorte('2026-10-25'),'domingo, 25 de octubre de 2026');
assert.equal(textoFechaVentasCorte('2028-02-29'),'martes, 29 de febrero de 2028');
assert.equal(textoFechaVentasCorte('2027-01-01'),'viernes, 1 de enero de 2027');
for(const invalid of ['',null,'2026-02-31','2026-10-25T00:00:00Z','not-a-date']) {
  assert.equal(textoFechaVentasCorte(invalid),'');
}
"""
    result = subprocess.run([node, "-e", script], capture_output=True, text=True,
                            env={**os.environ, "TZ": tz}, timeout=10)
    assert result.returncode == 0, result.stderr


def test_shift_sales_list_fills_its_column_and_wraps_without_hiding_amounts():
    assert '<div class="card corte-ventas-card">' in HTML
    assert '<div id="c-ventas-list">' in HTML
    assert 'id="c-ventas-list" style="max-height:300px' not in HTML
    assert '#c-ventas-list{flex:1 1 0;min-height:0;overflow-y:auto' in HTML
    assert 'grid-template-columns:minmax(0,1fr) max-content' in HTML
    assert '.corte-venta-detalle{min-width:0;overflow-wrap:anywhere}' in HTML
    assert '.corte-venta-total{white-space:nowrap}' in HTML
    assert '@media(max-width:900px){#c-ventas-list{flex:none;overflow:visible' in HTML


def test_current_cut_math_and_preview_are_not_saved_or_copied():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required")

    def section(start, end):
        offset = HTML.index(start)
        return HTML[offset:HTML.index(end, offset)]

    js = r"""
const assert = require('node:assert/strict');
const fields = {};
const document = {getElementById: id => fields[id] ||= {value:'',style:{},textContent:''}};
const window = {location:{href:''}};
function toast() {}
function cerrarModal() {}
function fmt(n) { return Number(n).toFixed(2); }
function formatearInstanteOperacion() { return '06/10/2026 09:00'; }
function fechaISOOperacion() { return '2026-10-06'; }
function fechaHoyISO() { return '2026-10-06'; }
let _efTotal = null, _corteVistaLista = false, _resumenCorteVista = null;
let _corteActual = null, _ultimoCorteRegistrado = null, _corteVentas = [];
""" + section("function calcularDiferencia", "function realizarCorte") + section(
        "function textoTicketTermico", "// ─── Fotos masivas"
    ) + r"""
fields['c-fondo'] = {value:'2000'};
fields['c-real'] = {value:'2502.50'};
fields['c-fondo-entregado'] = {value:'2000'};
fields['c-recibido-por'] = {value:'Pili'};
fields['c-fecha'] = {value:'2026-10-06'};
fields['c-notas'] = {value:'Cuadre'};
calcularDiferencia();
assert.equal(fields['c-dif'].textContent,'--');
_efTotal = 0; calcularDiferencia();
assert.equal(fields['c-dif'].textContent,'$502.50');
_efTotal = 502.50; calcularDiferencia();
assert.equal(fields['c-dif'].textContent,'$0.00 \u2714');
_efTotal = 502; calcularDiferencia();
assert.equal(fields['c-dif'].textContent,'$0.50');
imprimirCorteActual(); assert.equal(window.location.href,'');
_corteVistaLista = true;
_resumenCorteVista = {fecha:'2026-10-06', periodo_fin:'2026-10-06T15:00:00Z',
 siguiente_turno:2,total_ventas_efectivo:502.50,total_ventas_tarjeta:0,total_ventas_bbva:50,
 total_ventas_clip:10,total_ventas_transferencia:0,total_ventas:562.50,numero_ventas:3};
imprimirCorteActual();
let url = new URL(window.location.href);
assert.equal(url.protocol,'easyposprint:');
assert.equal(url.searchParams.get('paper'),'58');
const text = url.searchParams.get('text');
assert.ok(text.includes('PROVISIONAL - NO REGISTRADO'));
assert.ok(text.includes('Turno 2'));
assert.ok(text.includes('Retiro a resguardo'));
assert.ok(text.includes('$502.50'));
assert.ok(text.includes('Pili'));
assert.equal(url.searchParams.has('autoprint'),false);
window.location.href=''; fields['c-fecha'].value='2026-10-05';
imprimirCorteActual(); assert.equal(window.location.href,'');
fields['c-fecha'].value='2026-10-06'; fields['c-real'].value='';
imprimirCorteActual(); url = new URL(window.location.href);
assert.ok(url.searchParams.get('text').includes('Sin contar'));
"""
    result = subprocess.run([node, "-e", js], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_whatsapp_cut_format_unicode_and_native_web_round_trip():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required")

    def section(start, end):
        offset = HTML.index(start)
        return HTML[offset:HTML.index(end, offset)]

    js = r"""
const assert = require('node:assert/strict');
function fmt(n) { return Number(n).toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:2}); }
function textoTicketTermico(v) { return String(v ?? '').replace(/[\r\n]+/g, ' ').trim(); }
const APP_TIMEZONE='America/Mexico_City';
const window = {location:{href:''}, open:()=>{throw new Error('Popup blocked');}};
const document = {hidden:false};
const timers=[];
function setTimeout(fn) { timers.push(fn); }
""" + section("function partesFechaOperacion", "function fechaHoraOperacionInput") + section(
        "function instanteUTC", "function formatearInstanteOperacion"
    ) + section("function textoCorteParaWhatsApp", "function compartirCorteWhatsApp") + section(
        "function abrirWhatsAppConFallback", "function enviarCotizacionWhatsApp"
    ) + r"""
const cut = {id:42, turno:2, estado:'cerrado', fecha:'2026-10-06T03:00:00Z',
  fondo_inicial:500, total_ventas_efectivo:1250.75, total_ventas_tarjeta:50,
  total_ventas_clip:500, total_ventas_bbva:1000, total_ventas_transferencia:200,
  total_ventas:3000.75, numero_ventas:7, efectivo_real:1750.75, diferencia:0,
  retiros:1250.75, fondo_entregado:500, recibido_por:'Persona de prueba \u00d1'};
const text = textoCorteParaWhatsApp(cut);
assert.ok(text.includes('*Jacaranda* \u2014 Lunes 2026-10-05'));
assert.equal(textoCorteParaWhatsApp({...cut, fecha:'2026-10-06T03:00:00'}), text);
assert.equal(textoCorteParaWhatsApp({...cut, fecha:new Date(cut.fecha)}), text);
assert.ok(text.includes('Corte #42 \u00b7 cerrado\nTurno 2'));
for (const heading of ['*Ventas por m\u00e9todo:*','*Resumen:*','*Caja:*']) assert.ok(text.includes(heading));
for (const point of [0x1F35E,0x1F4B0,0x1F4B5,0x1F4B3,0x1F3E6,0x1F4CA,0x1F4DD,0x2728]) {
  assert.ok(text.includes(String.fromCodePoint(point)), point.toString(16));
}
assert.ok(text.includes('  Total ventas: $3,000.75\n  Tickets: 7'));
assert.ok(text.includes('  Fondo: $500.00\n  Contado: $1,750.75\n  Diferencia: $0.00 \u2714'));
assert.ok(text.includes('  Retiro a resguardo: $1,250.75'));
assert.ok(text.includes('  Fondo entregado al siguiente turno: $500.00'));
assert.ok(text.includes('  Recibido por (resguardo): Persona de prueba \u00d1'));
assert.ok(text.endsWith('\u2728 _Jacaranda - sharing flavors_'));
assert.equal(Buffer.from(text, 'utf8').toString('utf8'), text);
assert.ok(!text.includes('\ufffd'));
abrirWhatsAppConFallback(text);
let url = new URL(window.location.href);
assert.equal(url.protocol, 'whatsapp:');
assert.equal(url.searchParams.get('text'), text);
assert.ok(window.location.href.includes('%F0%9F%8D%9E'));
timers.shift()();
url = new URL(window.location.href);
assert.equal(url.hostname, 'web.whatsapp.com');
assert.equal(url.searchParams.get('text'), text);
assert.ok(!window.location.href.includes('wa.me'));
abrirWhatsAppConFallback(text); document.hidden=true; timers.shift()();
assert.equal(new URL(window.location.href).protocol, 'whatsapp:');
cut.efectivo_real=null; cut.diferencia=null; delete cut.fondo_entregado;
delete cut.id; cut.estado='provisional';
const preview = textoCorteParaWhatsApp(cut);
assert.ok(preview.includes('Provisional - no registrado'));
assert.ok(preview.includes('Contado: --\n  Diferencia: --'));
assert.ok(!preview.includes('\u2714'));
assert.ok(!preview.includes('Retiro a resguardo'));
"""
    result = subprocess.run([node, "-e", js], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_whatsapp_current_saved_and_incomplete_cut_use_same_snapshot():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required")

    def section(start, end):
        offset = HTML.index(start)
        return HTML[offset:HTML.index(end, offset)]

    js = r"""
const assert = require('node:assert/strict');
const fields={};
const document={getElementById:id=>fields[id] ||= {value:'',style:{},textContent:''}};
const messages=[], errors=[], copied=[];
const navigator={clipboard:{writeText:txt=>{copied.push(txt); return Promise.resolve();}}};
function toast(txt, error) { if(error) errors.push(txt); }
function abrirWhatsAppConFallback(txt) { messages.push(txt); }
function fmt(n) { return Number(n).toFixed(2); }
const APP_TIMEZONE='America/Mexico_City';
function fechaHoyISO() { return '2026-10-06'; }
let _corteVistaLista=false, _resumenCorteVista=null;
let _corteActual=null, _ultimoCorteRegistrado=null, _corteVentas=[];
""" + section("function partesFechaOperacion", "function fechaHoraOperacionInput") + section(
        "function instanteUTC", "function formatearInstanteOperacion"
    ) + section("function actualizarResguardoCorte", "function realizarCorte") + section(
        "function textoTicketTermico", "function imprimirCorteActual"
    ) + section("function textoCorteParaWhatsApp", "// ─── Pronóstico producción") + section(
        "function exportarCorte()", "// ─── Dynamic inventory loading"
    ) + r"""
fields['c-fecha']={value:'2026-10-06'};
fields['c-fondo']={value:'300'};
fields['c-real']={value:'800'};
fields['c-fondo-entregado']={value:'300'};
fields['c-recibido-por']={value:'Persona de prueba'};
fields['c-notas']={value:''};
fields['c-dif']={textContent:'$0.00 \u2714'};
compartirCorteWhatsApp(); assert.equal(messages.length,0); assert.equal(errors.length,1);
_corteVistaLista=true;
_resumenCorteVista={fecha:'2026-10-06',periodo_fin:'2026-10-06T15:00:00Z',siguiente_turno:1,
 total_ventas_efectivo:100,total_ventas_tarjeta:0,total_ventas_bbva:0,total_ventas_clip:0,
 total_ventas_transferencia:0,total_ventas:100,numero_ventas:1};
compartirCorteWhatsApp();
assert.ok(messages[0].includes('Martes 2026-10-06'));
assert.ok(messages[0].includes('  Diferencia: $400.00'));
assert.ok(!messages[0].includes('$0.00 \u2714'));
assert.ok(messages[0].includes('Retiro a resguardo: $500.00'));
exportarCorte(); assert.equal(copied[0],messages[0]);
fields['c-fecha'].value='2026-10-05'; compartirCorteWhatsApp(); assert.equal(messages.length,1);
fields['c-fecha'].value='2026-10-06'; fields['c-real'].value='';
_corteActual={..._resumenCorteVista,id:42,fecha:'2026-10-06T15:00:00Z',turno:1,estado:'cerrado',
 total_ventas:999,total_ventas_efectivo:999,fondo_inicial:2000,efectivo_real:2999,diferencia:0,
 retiros:999,fondo_entregado:2000,recibido_por:'Responsable de prueba'};
_ultimoCorteRegistrado=_corteActual;
compartirCorteWhatsApp();
assert.ok(messages[1].includes('Corte #42'));
assert.ok(messages[1].includes('Total ventas: $999.00'));
assert.ok(messages[1].includes('Contado: $2999.00'));
assert.ok(messages[1].includes('*Caja:*'));
assert.ok(messages[1].includes(String.fromCodePoint(0x1F35E)));
assert.ok(messages[1].includes('Recibido por (resguardo): Responsable de prueba'));
assert.equal(fields['c-dif'].textContent,'$0.00 \u2714');
"""
    result = subprocess.run([node, "-e", js], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
