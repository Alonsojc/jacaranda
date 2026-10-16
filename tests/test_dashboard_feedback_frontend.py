"""Execute actual toast and weekly dashboard functions without production data."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest


HTML = Path("docs/index.html").read_text(encoding="utf-8")


def section(start, end):
    offset = HTML.index(start)
    return HTML[offset:HTML.index(end, offset)]


def node(script, tz="UTC"):
    executable = shutil.which("node")
    if not executable:
        pytest.skip("Node required")
    result = subprocess.run(
        [executable, "-e", script], capture_output=True, text=True, timeout=10,
        env={**os.environ, "TZ": tz},
    )
    assert result.returncode == 0, result.stderr


TOAST = section("var _toastTimer = null;", "function esArchivoLocal")
DATES = section("function fechaHoyISO()", "function llenarHorasPedido()")
WEEK = section("function cargarComparativoSemanal()", "// Auto-conectar si hay URL guardada")
HARNESS = r"""
const assert = require('node:assert/strict'), fields = {}, calls = [], charts = [];
function field(id) { return fields[id] ||= {innerHTML:'',textContent:'',setAttribute(){}}; }
const document = {getElementById:field};
const APP_TIMEZONE = 'America/Mexico_City';
let _versionSesion = 1;
function fmt(v) { return Number(v).toFixed(2); }
function deferred() { let resolve, reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject}; }
function dashGet(path) { const d=deferred();calls.push({path,...d});return d.promise; }
let Chart = function(ctx, config) { charts.push(config);this.destroy=()=>{}; };
const NativeDate=Date;
let now=NativeDate.parse('2026-10-16T14:00:00Z');
globalThis.Date=class extends NativeDate {
  constructor(...args) { super(...(args.length?args:[now])); }
  static now() { return now; }
};
function dailySeries() {
  const today=fechaHoyISO(), result=[];
  for(let i=14;i>=0;i--) {
    const day=new NativeDate(today+'T12:00:00Z');day.setUTCDate(day.getUTCDate()-i);
    result.push({fecha:day.toISOString().slice(0,10),total:i===0?999999:i>7?10:20,tickets:1});
  }
  return result;
}
"""


def test_toasts_expire_replace_messages_and_clear_after_safari_resume():
    node(r"""
const assert=require('node:assert/strict'),events={},timers=new Map();
let now=1000,serial=0;
Date.now=()=>now;
function setTimeout(fn,delay){timers.set(++serial,{fn,at:now+delay});return serial;}
function clearTimeout(id){timers.delete(id);}
const el={className:'toast',textContent:'',attrs:{},setAttribute(k,v){this.attrs[k]=v;}};
el.classList={remove(cls){el.className=el.className.split(' ').filter(c=>c!==cls).join(' ');},
  contains(cls){return el.className.split(' ').includes(cls);}};
const document={getElementById:()=>el,addEventListener:(type,fn)=>events[type]=fn};
const window={addEventListener:(type,fn)=>events[type]=fn};
function advance(ms){now+=ms;for(const [id,t] of timers){if(t.at<=now){timers.delete(id);t.fn();}}}
""" + TOAST + r"""
toast('App actualizada');assert(el.classList.contains('show'));
assert.equal(el.attrs['aria-hidden'],'false');assert.equal(timers.size,1);
advance(3200);assert(!el.classList.contains('show'));assert.equal(el.textContent,'');
assert.equal(el.attrs['aria-hidden'],'true');assert.equal(_toastTimer,null);
toast('Anterior');advance(1000);toast('Error nuevo',true);
assert.equal(el.attrs.role,'alert');assert.equal(timers.size,1);
advance(2200);assert.equal(el.textContent,'Error nuevo');
advance(2800);assert(!el.classList.contains('show'));
toast('Aviso suspendido');now+=20000;events.visibilitychange();
assert(!el.classList.contains('show'));assert.equal(timers.size,0);
toast('Aviso bfcache');now+=10000;events.pageshow();assert(!el.classList.contains('show'));
toast('Reciente');now+=100;events.pageshow();assert.equal(el.textContent,'Reciente');
""")
    css = section(".toast{", ".toast.err{")
    assert "opacity:0;visibility:hidden" in css
    assert "opacity:1;visibility:visible" in css


@pytest.mark.parametrize("tz", ["UTC", "America/Mexico_City", "Pacific/Auckland"])
@pytest.mark.parametrize("instant", [
    "2026-10-16T14:00:00Z",  # Friday morning: compare through Thursday.
    "2026-10-16T05:59:59Z",  # Still Thursday in CDMX, regardless of device timezone.
    "2026-01-01T06:00:00Z",  # Calendar year boundary.
    "2028-03-01T06:01:00Z",  # Leap day.
])
def test_weekly_comparison_uses_two_aligned_closed_periods(tz, instant):
    node(HARNESS + DATES + WEEK + f"now=NativeDate.parse('{instant}');" + r"""
(async()=>{
  const rows=dailySeries(),load=cargarComparativoSemanal();
  assert.equal(calls[0].path,'/reportes/ventas-por-dia?dias=15');
  calls[0].resolve(rows);await load;
  assert.deepEqual(charts[0].data.datasets.map(s=>s.data),[Array(7).fill(20),Array(7).fill(10)]);
  const expected=rows.slice(7,14).map(d=>['Dom','Lun','Mar','Mié','Jue','Vie','Sáb'][new NativeDate(d.fecha+'T12:00:00Z').getUTCDay()]);
  assert.deepEqual(charts[0].data.labels,expected);
  const html=field('d-week-compare').innerHTML;
  assert(html.includes('$140.00'));assert(html.includes('$70.00'));assert(html.includes('100.0%'));
  assert(html.includes('Días completos hasta el'));assert(!html.includes('999999'));
  assert.equal(rows[14].fecha,fechaHoyISO());
})();
""", tz)


def test_weekly_comparison_ignores_stale_requests_and_waits_for_chart_without_refetch():
    node(HARNESS + DATES + WEEK + r"""
(async()=>{
  const rows=dailySeries();let old=cargarComparativoSemanal(),current=cargarComparativoSemanal();
  calls[1].resolve(rows);await current;
  calls[0].reject(new Error('Old error'));await old;assert.equal(charts.length,1);
  Chart=undefined;const ready=deferred();globalThis.ensureChart=()=>ready.promise;
  old=cargarComparativoSemanal();calls[2].resolve(rows);await new Promise(resolve=>setImmediate(resolve));
  _versionSesion++;Chart=function(){throw new Error('Old session rendered');};
  ready.resolve();await old;assert.equal(calls.length,3);assert.equal(charts.length,1);
  const html=field('d-week-compare').innerHTML;
  old=cargarComparativoSemanal();_versionSesion++;calls[3].resolve(rows);await old;
  assert.equal(field('d-week-compare').innerHTML,html);
})();
""")


def test_weekly_zero_baseline_and_incomplete_response_do_not_invent_percentages():
    node(HARNESS + DATES + WEEK + r"""
(async()=>{
  const rows=dailySeries().map(d=>({...d,total:0}));
  let load=cargarComparativoSemanal();calls[0].resolve(rows);await load;
  assert(field('d-week-compare').innerHTML.includes('Sin base previa'));
  assert(!field('d-week-compare').innerHTML.includes('NaN'));
  load=cargarComparativoSemanal();calls[1].resolve(rows.slice(1));await load;
  assert(field('d-week-compare').innerHTML.includes('No se pudo cargar'));
})();
""")


@pytest.mark.parametrize("failure", ["loader", "canvas"])
def test_weekly_chart_failures_preserve_totals_dates_and_percentage(failure):
    node(HARNESS + DATES + WEEK + f"const failure='{failure}';" + r"""
(async()=>{
  Chart=failure==='loader'?undefined:function(){throw new Error('Canvas failed');};
  globalThis.ensureChart=()=>Promise.reject(new Error('CDN offline'));
  const load=cargarComparativoSemanal();calls[0].resolve(dailySeries());await load;
  const html=field('d-week-compare').innerHTML;
  assert(html.includes('$140.00'));assert(html.includes('$70.00'));assert(html.includes('100.0%'));
  assert(html.includes('D\u00edas completos hasta el'));assert(!html.includes('No se pudo cargar el comparativo'));
  assert.equal(field('chart-week-panel').hidden,true);
  assert.equal(field('chart-week-estado').hidden,false);
  assert(field('chart-week-estado').textContent.includes('Datos disponibles'));
  assert.equal(calls.length,1);
})();
""")


def test_sparklines_share_the_daily_request_but_still_include_today():
    node(HARNESS + DATES + section("function cargarSparklines()", "var _dashAlertas") + r"""
const sparks=[];function _renderSpark(id,values){sparks.push(values);}
function _setDelta(){}
cargarSparklines();assert.equal(calls[0].path,'/reportes/ventas-por-dia?dias=15');
calls[0].resolve(dailySeries());
setImmediate(()=>{assert.equal(sparks[0].length,14);assert.equal(sparks[0][13],999999);});
""")
