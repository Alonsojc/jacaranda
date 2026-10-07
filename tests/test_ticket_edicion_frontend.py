"""Exercise browser-side corrections without a live server or real records."""

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
        pytest.skip("Node required")
    result = subprocess.run([executable, "-e", script], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


HARNESS = r"""
const assert = require('node:assert/strict');
const fields = {};
const document = {getElementById: id => fields[id] ||= {
  value:'', textContent:'', innerHTML:'', style:{}, disabled:false,
  classList:{on:true, add(){this.on=true;},remove(){this.on=false;},contains(){return this.on;}}
}};
let _versionSesion=1, _ventaActualId=10, _dashGetCache={}, _dashCacheAt=0;
const window={_permisos:{pos:'editar'}}, calls=[], reads=[];
let authorize, apiResult=()=>Promise.resolve({id:10});
function apiLecturaRecuperable(path){return new Promise((resolve,reject)=>reads.push({path,resolve,reject}));}
function api(...args){calls.push(args);return apiResult();}
function pedirPasswordAdmin(action, forced){assert.equal(forced,true);return new Promise(resolve=>authorize=resolve);}
function cancelarAdminAuth(){}
function fmt(v){return Number(v).toFixed(2);}
function fmtQty(v){return Number(v);}
function escHtml(v){return String(v).replace(/</g,'&lt;');}
function toast(){}
function verTicket(){}
function cargarCorte(){}
function cargarHistVentas(){}
function cargarPOSProductos(){}
async function flush(){for(let i=0;i<12;i++)await Promise.resolve();}
const context={venta:{id:10,folio:'T-TEST',edicion_revision:0,metodo_pago:'01',total:'190',monto_recibido:'500',
  detalles:[{id:1,producto_id:1,producto_nombre:'Original',cantidad:'2',precio_unitario:'100',descuento:'10',tasa_iva:'0'}]},
  productos:[{id:1,nombre:'Original'},{id:2,nombre:'Otro'}],bloqueo:null,bloqueo_precios:null};
""" + section("var _ticketEdicion = null", "async function cancelarVentaActual")


def test_cart_controls_use_stable_grid_and_discount_is_30_percent():
    ren = section("function ren()", "function cartQty(")
    assert 'class="ti cart-item"' in ren
    assert 'class="cart-quantity"' in ren
    assert "escHtml(c.n)" in ren
    assert 'class="cart-amount"' in ren
    assert 'id="md-pct-30" onclick="mdSet(30)"' in HTML
    assert 'id="md-pct-50"' not in HTML
    node(section("function mdSet(", "function mdAplicar(") + r"""
const assert=require('node:assert/strict');
const cart=[{p:50,q:2}], fields={'md-monto':{value:0},'md-preview':{textContent:''}};
let _descIdx=0;
const document={getElementById:id=>fields[id]};
function mdCalc(){}
mdSet(30);assert.equal(fields['md-monto'].value,30);
""")


def test_day_arrows_cross_month_year_and_leap_day():
    node(section("function cambiarDiaCorte(", "function cargarCorte()") + r"""
const assert=require('node:assert/strict'), input={value:'2026-01-01'};
const document={getElementById:()=>input};
let loads=0;
function fechaHoyISO(){return '2026-10-07';}
function cargarCorte(){loads++;}
cambiarDiaCorte(-1);assert.equal(input.value,'2025-12-31');
cambiarDiaCorte(1);assert.equal(input.value,'2026-01-01');
input.value='2028-03-01';cambiarDiaCorte(-1);assert.equal(input.value,'2028-02-29');
input.value='';cambiarDiaCorte(-1);assert.equal(input.value,'2026-10-06');
assert.equal(loads,4);
""")


def test_editor_requires_admin_and_separates_product_from_price_payload():
    node(HARNESS + r"""
(async()=>{
  let opening=abrirEdicionTicket();reads[0].resolve(context);await opening;
  fields['met-item-0'].value='2';fields['met-motivo'].value='Correccion de prueba';
  actualizarTotalEdicionTicket();assert.equal(fields['met-name-0'].textContent,'Otro');
  assert.equal(datosEdicionTicket(_ticketEdicion).total,190);
  let saving=guardarEdicionTicket();assert.equal(calls.length,0);
  authorize({'X-Admin-Override-Password':'test-only'});await saving;
  assert.equal(calls.length,1);assert.equal(calls[0][0],'PATCH');
  assert.deepEqual(calls[0][2].detalles,[{id:1,producto_id:2}]);
  assert.equal(calls[0][5],1);
  assert.equal(calls[0][4]['X-Admin-Override-Password'],'test-only');
  opening=abrirEdicionTicket();reads[1].resolve(context);await opening;
  cambiarModoEdicionTicket('precios');fields['met-item-0'].value='150.00';
  assert.equal(datosEdicionTicket(_ticketEdicion).total,290);
  assert.deepEqual(datosEdicionTicket(_ticketEdicion).detalles,[{id:1,precio_unitario:'150.00'}]);
  fields['met-item-0'].value='-1';assert.throws(()=>datosEdicionTicket(_ticketEdicion));
})().catch(e=>{console.error(e);process.exitCode=1;});
""")


@pytest.mark.parametrize("invalidate", ["_versionSesion++", "cerrarEdicionTicket()", "_ventaActualId=20"])
def test_editor_never_sends_after_authorization_context_changes(invalidate):
    node(HARNESS + r"""
(async()=>{
  const opening=abrirEdicionTicket();reads[0].resolve(context);await opening;
  fields['met-item-0'].value='2';fields['met-motivo'].value='Correccion de prueba';
  const saving=guardarEdicionTicket();
""" + invalidate + r""";
  authorize({});await saving;assert.equal(calls.length,0);
})().catch(e=>{console.error(e);process.exitCode=1;});
""")


def test_editor_ignores_stale_reads_and_never_replays_unknown_write():
    node(HARNESS + r"""
(async()=>{
  const a=abrirEdicionTicket(),b=abrirEdicionTicket();
  reads[1].resolve(context);await b;
  reads[0].resolve({...context,bloqueo:'Old response'});await a;
  assert.equal(_ticketEdicion.contexto.bloqueo,null);
  fields['met-item-0'].value='2';fields['met-motivo'].value='Correccion de prueba';
  apiResult=()=>Promise.reject(new Error('Servidor no disponible'));
  const saving=guardarEdicionTicket();authorize({});await saving;
  await guardarEdicionTicket();assert.equal(calls.length,1);
  assert.equal(fields['met-save'].disabled,true);
  assert.equal(fields['met-retry'].style.display,'');
})().catch(e=>{console.error(e);process.exitCode=1;});
""")
