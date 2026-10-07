"""Helpers reales de reportes, ejecutados sin datos productivos."""

from pathlib import Path
import shutil
import subprocess

import pytest


HTML = Path("docs/index.html").read_text(encoding="utf-8")


def _section(start, end):
    offset = HTML.index(start)
    return HTML[offset:HTML.index(end, offset)]


def _node(js):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required for frontend execution")
    result = subprocess.run([node, "-e", js], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


PREAMBLE = r"""
const assert = require('node:assert/strict');
const fields = {};
const document = {getElementById: id => fields[id] ||= {
  value:'', textContent:'old', innerHTML:'old', style:{display:'none'}, parentElement:{hidden:false}
}};
const window = {_permisos:{egresos:'ver'}};
function moduloDesactivado() { return false; }
let _chartVentas = null, _chartVentasVersion = 0;
let hoy = '2026-10-06';
function fechaHoyISO() { return hoy; }
function fechaDiasAntesISO(n) { const d = new Date(hoy + 'T12:00:00Z'); d.setUTCDate(d.getUTCDate()-n); return d.toISOString().slice(0,10); }
function fmt(n) { return Number(n).toFixed(2); }
function escHtml(n) { return String(n).replace(/</g, '&lt;'); }
const toasts = [];
function toast(m) { toasts.push(m); }
let chartDays = [];
function renderChartVentas(d) { chartDays = d; }
const requests = [];
function api(method,path) { return new Promise((resolve,reject) => requests.push({method,path,resolve,reject})); }
let csvResult = '';
function _descargarCSV(name, csv) { csvResult = csv; }
function response(fi,ff,total=100) { return {periodo:{inicio:fi,fin:ff}, resumen:{total,numero_ventas:total ? 2 : 0,ticket_promedio:total/2},por_dia:{[fi]:{total,cantidad:2}},por_metodo_pago:{efectivo:{total,cantidad:2}}}; }
"""


def test_month_buttons_and_initial_load():
    js = PREAMBLE + _section("function initReportes", "function cargarReporteProductos") + r"""
async function run() {
  repMesActual();
  assert.equal(fields['rep-fi'].value, '2026-10-01');
  assert.equal(fields['rep-ff'].value, '2026-10-06');
  assert.ok(requests[0].path.includes('fecha_inicio=2026-10-01&fecha_fin=2026-10-06'));
  repMesAnterior('ventas');
  assert.equal(fields['rep-fi'].value, '2026-09-01');
  assert.equal(fields['rep-ff'].value, '2026-09-30');
  assert.ok(requests[1].path.includes('fecha_inicio=2026-09-01&fecha_fin=2026-09-30'));
  hoy = '2026-01-04'; repMesAnterior('ventas');
  assert.equal(fields['rep-fi'].value, '2025-12-01');
  assert.equal(fields['rep-ff'].value, '2025-12-31');
  hoy = '2024-03-10'; repMesAnterior('egresos');
  assert.equal(fields['rep-efi'].value, '2024-02-01');
  assert.equal(fields['rep-eff'].value, '2024-02-29');
  hoy = '2026-10-06'; repSetRango(7);
  assert.equal(fields['rep-fi'].value, '2026-09-30');
  assert.equal(diasReporteVentas(response('2024-02-01','2024-02-29')).length,29);
  assert.equal(diasReporteVentas(response('2026-09-01','2026-09-30')).length,30);
  document.getElementById('rep-ventas').style.display = 'block';
  document.getElementById('rep-egresos').style.display = 'none';
  const count = requests.length; initReportes();
  assert.equal(requests.length, count+1);
  assert.ok(requests.every(r => !r.path.includes('ventas-por-dia')));
}
run().catch(e=>{console.error(e);process.exit(1)});
"""
    _node(js)


def test_latest_period_wins_and_failure_clears_totals():
    js = PREAMBLE + _section("function initReportes", "function cargarReporteProductos") + r"""
async function run() {
  fields['rep-fi'] = {value:'2026-09-01'}; fields['rep-ff'] = {value:'2026-09-30'};
  let old = cargarReporteVentas();
  fields['rep-fi'].value = '2026-10-01'; fields['rep-ff'].value = '2026-10-06';
  let latest = cargarReporteVentas();
  requests[1].resolve(response('2026-10-01','2026-10-06',400)); await latest;
  assert.equal(fields['rep-total'].textContent, '$400.00');
  assert.equal(fields['rep-tickets'].textContent,2);
  assert.equal(chartDays.length,6); assert.equal(chartDays[0].fecha,'2026-10-01');
  requests[0].resolve(response('2026-09-01','2026-09-30',350)); await old;
  assert.equal(fields['rep-total'].textContent,'$400.00');
  let fail = cargarReporteVentas();
  assert.equal(fields['rep-total'].textContent,'--');
  requests[2].reject(new Error('timeout')); await fail;
  assert.equal(fields['rep-tickets'].textContent,'--');
  assert.equal(fields['rep-promedio'].textContent,'--');
  assert.equal(fields['rep-metodo'].textContent,'');
  assert.equal(fields['rep-chart-canvas'].parentElement.hidden,true);
  let pending = cargarReporteVentas(); invalidarReporteVentas();
  requests[3].resolve(response('2026-10-01','2026-10-06',900)); await pending;
  assert.equal(fields['rep-total'].textContent,'--');
  let wrong = cargarReporteVentas(); requests[4].resolve(response('2026-08-01','2026-08-31')); await wrong;
  assert.equal(fields['rep-total'].textContent,'--');
  let empty = cargarReporteVentas(); requests[5].resolve(response('2026-10-01','2026-10-06',0)); await empty;
  assert.equal(fields['rep-total'].textContent,'$0.00');
  assert.equal(fields['rep-promedio'].textContent,'$0.00');
  assert.ok(chartDays.every(d=>d.total===0));
}
run().catch(e=>{console.error(e);process.exit(1)});
"""
    _node(js)


def test_expenses_safe_csv_and_failure_reset():
    js = PREAMBLE + _section("function initReportes", "function cargarReporteProductos") + r"""
async function run() {
  fields['rep-efi'] = {value:'2026-09-01'}; fields['rep-eff'] = {value:'2026-09-30'};
  const r = {periodo:{inicio:'2026-09-01',fin:'2026-09-30'},resumen:{total:250,numero_egresos:1,egreso_promedio:250},
    por_categoria:{empaque:{cantidad:1,total:250}},por_metodo_pago:{efectivo:{cantidad:1,total:250}},
    detalle:[{fecha:'2026-09-01',concepto:'=1+1',monto:250,categoria:'empaque',metodo_pago:'efectivo',proveedor:'<script>,"x"',notas:'x\ny'}]};
  let pending = cargarReporteEgresos(); requests[0].resolve(r); await pending;
  assert.equal(fields['rep-eg-total'].textContent,'$250.00');
  assert.ok(!fields['rep-eg-detalle'].innerHTML.includes('<script>'));
  exportarEgresosCSV(); assert.ok(csvResult.includes("'=1+1")); assert.ok(csvResult.includes('""x""'));
  const validCsv = csvResult;
  fields['rep-efi'].value = '2026-10-01'; exportarEgresosCSV(); assert.equal(csvResult,validCsv);
  fields['rep-efi'].value = '2026-09-01';
  pending = cargarReporteEgresos(); requests[1].reject(new Error('offline')); await pending;
  assert.equal(fields['rep-eg-total'].textContent,'--'); assert.equal(_reporteEgresosData,null);
  exportarEgresosCSV(); assert.equal(csvResult,validCsv);
}
run().catch(e=>{console.error(e);process.exit(1)});
"""
    _node(js)


def test_reports_toolbar_permissions_and_empty_chart_contract():
    assert 'class="report-period"' in HTML
    assert "Mes anterior" in HTML
    assert 'data-report-egresos' in HTML
    assert "permiso === 'ver' || permiso === 'editar'" in HTML
    assert "exportarEgresosCSV();" in HTML
    assert "ctx.parentElement.innerHTML" not in _section("function renderChartVentas", "function invTab")


def test_monthly_kpi_only_in_reports_and_dashboard_keeps_three_cards():
    assert 'class="row r3 hero-grid"' in HTML
    assert 'id="d-mes"' not in HTML
    assert "d-sub-mes" not in HTML
    assert "spark-mes" not in HTML
    assert "ventas-mes" not in HTML
    assert 'onclick="repMesActual()"' in HTML
    assert 'id="rep-proyeccion-kpi"' in HTML
    assert 'id="rep-proyeccion-base"' in HTML


def test_projection_follows_latest_period_and_clears_on_change_or_failure():
    js = PREAMBLE + _section("function initReportes", "function cargarReporteProductos") + r"""
async function run() {
  hoy = '2026-10-07';
  fields['rep-fi'] = {value:'2026-09-01'}; fields['rep-ff'] = {value:'2026-09-30'};
  const old = cargarReporteVentas();
  const latest = repMesActual();
  const current = response('2026-10-01','2026-10-07',1500);
  current.proyeccion = {proyeccion_mes:3100,dias_transcurridos:6,fecha_fin:'2026-10-06'};
  requests[1].resolve(current); await latest;
  assert.equal(fields['rep-total'].textContent,'$1500.00');
  assert.equal(fields['rep-proyeccion'].textContent,'$3100.00');
  assert.equal(fields['rep-proyeccion-kpi'].style.display,'');
  assert.equal(fields['rep-ventas-kpis'].className,'row r4');
  assert.ok(fields['rep-proyeccion-base'].textContent.includes('2026-10-06'));
  requests[0].resolve(response('2026-09-01','2026-09-30',9000)); await old;
  assert.equal(fields['rep-proyeccion'].textContent,'$3100.00');
  const previous = repMesAnterior('ventas');
  assert.equal(fields['rep-proyeccion-kpi'].style.display,'none');
  assert.equal(fields['rep-proyeccion-base'].textContent,'');
  requests[2].resolve(response('2026-09-01','2026-09-30',9000)); await previous;
  assert.equal(fields['rep-proyeccion-kpi'].style.display,'none');
  assert.equal(fields['rep-ventas-kpis'].className,'row r3');
  const failed = repMesActual(); requests[3].reject(new Error('offline')); await failed;
  assert.equal(fields['rep-proyeccion'].textContent,'--');
  assert.equal(fields['rep-proyeccion-kpi'].style.display,'none');
}
run().catch(e=>{console.error(e);process.exit(1)});
"""
    _node(js)


def test_projection_distinguishes_first_day_from_completed_days_without_sales():
    js = PREAMBLE + _section("function initReportes", "function cargarReporteProductos") + r"""
async function run() {
  hoy = '2026-11-01';
  let pending = repMesActual();
  const first = response('2026-11-01','2026-11-01',900);
  first.proyeccion = {proyeccion_mes:null,dias_transcurridos:0,fecha_fin:null};
  requests[0].resolve(first); await pending;
  assert.equal(fields['rep-proyeccion-kpi'].style.display,'');
  assert.equal(fields['rep-proyeccion'].textContent,'--');
  assert.ok(fields['rep-proyeccion-base'].textContent.includes('Sin d'));
  hoy = '2026-11-02'; pending = repMesActual();
  const empty = response('2026-11-01','2026-11-02',0);
  empty.proyeccion = {proyeccion_mes:0,dias_transcurridos:1,fecha_fin:'2026-11-01'};
  requests[1].resolve(empty); await pending;
  assert.equal(fields['rep-proyeccion'].textContent,'$0.00');
  assert.ok(fields['rep-proyeccion-base'].textContent.includes('2026-11-01'));
  invalidarReporteVentas();
  assert.equal(fields['rep-proyeccion-kpi'].style.display,'none');
}
run().catch(e=>{console.error(e);process.exit(1)});
"""
    _node(js)
