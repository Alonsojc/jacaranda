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
  value:'', textContent:'', innerHTML:'', style:{}, disabled:false, hidden:false, attributes:{},
  setAttribute(key,value){this.attributes[key]=value;},removeAttribute(key){delete this.attributes[key];},
  focus(){},select(){},scrollIntoView(){},
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
function toast(){}
function verTicket(){}
function cargarCorte(){}
function cargarHistVentas(){}
function cargarPOSProductos(){}
async function flush(){for(let i=0;i<12;i++)await Promise.resolve();}
const context={venta:{id:10,folio:'T-TEST',edicion_revision:0,metodo_pago:'01',total:'190',monto_recibido:'500',
  detalles:[{id:1,producto_id:1,producto_nombre:'Original',cantidad:'2',precio_unitario:'100',descuento:'10',tasa_iva:'0'}]},
  productos:[{id:1,nombre:'Original'},{id:2,nombre:'Otro'}],bloqueo:null,bloqueo_precios:null};
""" + section("function escHtml(", "function jsArg(") + section("var _ticketEdicion = null", "async function cancelarVentaActual")


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


def test_searchable_product_picker_filters_accents_words_and_presentations():
    node(HARNESS + r"""
const products=[{id:1,nombre:'Panqu\u00e9 de Calabaza',presentacion:'Grande',stock_actual:'4.5000',unidad_medida:'pz'},
  {id:2,nombre:'Panqu\u00e9 de Pl\u00e1tano con Chocolate',presentacion:'Individual'},
  {id:3,nombre:'Rosca de Chocolate grande',presentacion:'Grande'}];
assert.deepEqual(coincidenciasProductoTicket(products,'CALABAZA panque').map(p=>p.id),[1]);
assert.deepEqual(coincidenciasProductoTicket(products,'grande').map(p=>p.id),[1,3]);
assert.deepEqual(coincidenciasProductoTicket(products,'  panque   platano ').map(p=>p.id),[2]);
assert.equal(coincidenciasProductoTicket(products,'sin coincidencia').length,0);
assert.equal(coincidenciasProductoTicket(products,'').length,3);
assert.equal(nombreProductoEdicionTicket(products[0]),'Panqu\u00e9 de Calabaza - Grande');
assert.equal(nombreProductoEdicionTicket(products[2]),'Rosca de Chocolate grande');
""")


def test_product_picker_requires_an_explicit_choice_before_saving():
    node(HARNESS + r"""
(async()=>{
  const opening=abrirEdicionTicket();reads[0].resolve(context);await opening;
  assert.match(fields['met-lines'].innerHTML,/role="combobox"/);
  assert.match(fields['met-lines'].innerHTML,/aria-controls="met-options-0"/);
  assert.match(fields['met-lines'].innerHTML,/role="listbox"/);
  assert.equal(fields['met-search-0'].value,'Original');
  abrirProductosTicket(0);
  fields['met-search-0'].value='Otro';buscarProductosTicket(0);
  assert.equal(fields['met-save'].disabled,true);
  assert.equal(fields['met-total'].textContent,'$190.00');
  assert.equal(fields['met-item-0'].value,'');
  assert.equal(fields['met-search-0'].attributes['aria-expanded'],'true');
  assert.throws(()=>datosEdicionTicket(_ticketEdicion),/Elige un producto/);
  fields['met-motivo'].value='Correccion de prueba';await guardarEdicionTicket();
  assert.equal(calls.length,0);assert.equal(authorize,undefined);
  elegirProductoTicket(0,2);
  assert.equal(fields['met-search-0'].value,'Otro');
  assert.equal(fields['met-name-0'].textContent,'Otro');
  assert.equal(fields['met-save'].disabled,false);
  assert.equal(fields['met-menu-0'].hidden,true);
  assert.equal(fields['met-search-0'].attributes['aria-expanded'],'false');
  assert.equal(fields['met-search-0'].attributes['aria-activedescendant'],undefined);
  assert.deepEqual(datosEdicionTicket(_ticketEdicion),{detalles:[{id:1,producto_id:2}],total:190});
  elegirProductoTicket(0,999);assert.equal(fields['met-item-0'].value,'2');
  fields['met-item-0'].value='999';assert.throws(()=>datosEdicionTicket(_ticketEdicion));
})().catch(e=>{console.error(e);process.exitCode=1;});
""")


def test_product_picker_keyboard_and_blur_never_commit_a_search():
    node(HARNESS + r"""
(async()=>{
  const opening=abrirEdicionTicket();reads[0].resolve(context);await opening;
  const key=(name,extra={})=>{
    const event={key:name,prevented:false,stopped:false,
      preventDefault(){this.prevented=true;},stopPropagation(){this.stopped=true;},...extra};
    teclasProductosTicket(0,event);return event;
  };
  key('ArrowDown');assert.equal(_ticketEdicion.selectores[0].activo,0);
  key('ArrowDown');assert.equal(_ticketEdicion.selectores[0].activo,1);
  key('ArrowDown');assert.equal(_ticketEdicion.selectores[0].activo,1);
  assert.equal(fields['met-search-0'].attributes['aria-activedescendant'],'met-option-0-1');
  assert.equal(key('Enter').prevented,true);assert.equal(fields['met-item-0'].value,'2');
  abrirProductosTicket(0);fields['met-search-0'].value='no existe';buscarProductosTicket(0);
  assert.equal(fields['met-status-0'].textContent,'Sin coincidencias');
  assert.equal(fields['met-options-0'].innerHTML,'');
  key('Enter');assert.equal(fields['met-item-0'].value,'');
  assert.equal(key('Escape').stopped,true);assert.equal(fields['met-item-0'].value,'2');
  assert.equal(_ticketEdicion!==null,true);assert.equal(fields['met-search-0'].value,'Otro');
  abrirProductosTicket(0);fields['met-search-0'].value='Original';buscarProductosTicket(0);
  key('Enter',{isComposing:true});assert.equal(fields['met-item-0'].value,'');
  key('Tab');assert.equal(fields['met-item-0'].value,'2');
  abrirProductosTicket(0);key('ArrowUp');assert.equal(_ticketEdicion.selectores[0].activo,1);
  key('ArrowUp');assert.equal(_ticketEdicion.selectores[0].activo,0);
  key('ArrowUp');assert.equal(_ticketEdicion.selectores[0].activo,0);
  fields['met-search-0'].value='Original';buscarProductosTicket(0);
  salirProductosTicket(0,{relatedTarget:{},currentTarget:{contains(){return true;}}});
  assert.equal(_ticketEdicion.selectores[0].abierto,true);
  salirProductosTicket(0,{relatedTarget:null,currentTarget:{contains(){return false;}}});
  assert.equal(fields['met-item-0'].value,'2');assert.equal(fields['met-menu-0'].hidden,true);
})().catch(e=>{console.error(e);process.exitCode=1;});
""")


def test_product_picker_keeps_unlisted_original_and_shows_stock_without_disabling_swaps():
    node(HARNESS + r"""
(async()=>{
  const opening=abrirEdicionTicket();reads[0].resolve({...context,productos:[
    {id:2,nombre:'Nuevo <producto>',presentacion:'Grande',stock_actual:'0.0000',unidad_medida:'pz'}]});await opening;
  assert.equal(fields['met-search-0'].value,'Original');
  assert.equal(datosEdicionTicket(_ticketEdicion).detalles[0].producto_id,1);
  abrirProductosTicket(0);
  assert.match(fields['met-options-0'].innerHTML,/Producto original fuera del cat&aacute;logo/);
  assert.match(fields['met-options-0'].innerHTML,/Existencias: 0 pzas/);
  assert.match(fields['met-options-0'].innerHTML,/Nuevo &lt;producto&gt;/);
  elegirProductoTicket(0,2);assert.equal(fields['met-search-0'].value,'Nuevo <producto> - Grande');
  assert.equal(fields['met-save'].disabled,false);
  elegirProductoTicket(0,1);assert.equal(fields['met-save'].disabled,true);
})().catch(e=>{console.error(e);process.exitCode=1;});
""")


def test_product_picker_isolates_multiple_lines_and_resets_when_switching_modes():
    node(HARNESS + r"""
(async()=>{
  const opening=abrirEdicionTicket();reads[0].resolve({...context,venta:{...context.venta,
    detalles:[...context.venta.detalles,{...context.venta.detalles[0],id:2}]}});await opening;
  elegirProductoTicket(0,2);abrirProductosTicket(1);
  fields['met-search-1'].value='Original';buscarProductosTicket(1);
  assert.equal(fields['met-save'].disabled,true);
  abrirProductosTicket(0);assert.equal(fields['met-item-1'].value,'1');
  assert.deepEqual(datosEdicionTicket(_ticketEdicion).detalles,[{id:1,producto_id:2},{id:2,producto_id:1}]);
  cambiarModoEdicionTicket('precios');assert.equal(_ticketEdicion.selectores.length,0);
  elegirProductoTicket(0,2);assert.equal(_ticketEdicion.modo,'precios');
  cambiarModoEdicionTicket('productos');assert.equal(fields['met-item-0'].value,'1');
  assert.equal(fields['met-search-0'].value,'Original');
  _versionSesion++;buscarProductosTicket(0);assert.equal(fields['met-item-0'].value,'1');
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
