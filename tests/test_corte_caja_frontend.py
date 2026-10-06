"""Regresiones de las acciones de corte de caja desde iPad/iPhone."""

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
    assert HTML.count("var guardado = corteGuardadoParaExportar();") == 4
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
const document = {getElementById: id => fields[id] ||= {value:'',style:{},textContent:'',innerHTML:''}};
let _corteCargaSeq=0, _corteVistaLista=false, _resumenCorteVista=null;
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
function summary(date,total) { return {fecha:date,total_ventas_efectivo:total,total_ventas_tarjeta:0,
total_ventas_transferencia:0,total_ventas_clip:0,total_ventas_bbva:0,total_ventas:total,numero_ventas:0}; }
""" + load + r"""
async function run() {
  document.getElementById('c-fecha').value='2026-10-05';
  let old=cargarCorte();
  assert.equal(fields['btn-imprimir-corte'].disabled,true);
  fields['c-fecha'].value='2026-10-06'; let latest=cargarCorte();
  requests[2].resolve([]); await Promise.resolve();
  assert.equal(_corteVistaLista,false);
  requests[3].resolve(summary('2026-10-06',502.5)); await latest;
  assert.equal(_efTotal,502.5); assert.equal(fields['mathLast'],502.5);
  assert.equal(fields['btn-imprimir-corte'].disabled,false);
  requests[0].resolve([]); requests[1].resolve(summary('2026-10-05',900)); await old;
  assert.equal(_efTotal,502.5);
  latest=cargarCorte(); requests[4].resolve([]); requests[5].reject(new Error('offline')); await latest;
  assert.equal(_corteVistaLista,false); assert.equal(_efTotal,null);
  assert.equal(fields['btn-corte'].disabled,true);
  assert.equal(fields['btn-imprimir-corte'].disabled,true);
}
run().catch(e=>{console.error(e);process.exit(1)});
"""
    result = subprocess.run([node, "-e", js], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


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
