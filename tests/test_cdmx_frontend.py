"""CDMX shares the POS workflow but never falls back to another price list."""

from pathlib import Path
import shutil
import subprocess

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
const assert=require('node:assert/strict'), fields={}, navigation=[], tabs=['mostrador','cafeterias','uber_eats','cdmx'];
const buttons=tabs.map(mode=>({mode, selected:'false',classList:{toggle(){}},getAttribute(){return mode;},setAttribute(k,v){this.selected=v;}}));
const document={querySelectorAll:()=>buttons,getElementById:id=>fields[id]||={textContent:'',innerHTML:'',placeholder:'',style:{},classList:{toggle(){}}}};
const window={_permisos:{pos:'editar',cafeteria:'editar'}};
let _posCanal='mostrador',cart=[],clears=0,approve=true;
function esAdminActual(){return true;}
function toast(){}
function confirmarAccion(){return Promise.resolve(approve);}
function limpiar(){clears++;cart=[];}
function go(p){navigation.push(p);}
function fmt(n){return Number(n).toFixed(2);}
function escHtml(n){return String(n);}
function jsArg(n){return JSON.stringify(n);}
function grupoFormalProducto(p){return {key:String(p.id),nombre:p.nombre,presentacion:p.presentacion};}
"""


def test_cdmx_switch_is_visible_and_preserves_ticket_on_cancel():
    node(HARNESS + section("function actualizarModoVentaUI", "async function abrirPreparacionUber")
         + section("async function cambiarModoVenta", "var POS_DRAFT_KEY") + r"""
(async()=>{
  const product={precio_unitario:100,precio_cafeteria:80,precio_uber_eats:120,precio_cdmx:180};
  await cambiarModoVenta('cdmx');assert.equal(_posCanal,'cdmx');assert.equal(precioProductoPOS(product),180);
  assert.equal(buttons[3].selected,'true');assert.equal(fields['pos-ticket-title'].textContent,'Ticket CDMX');
  assert.equal(precioProductoPOS({precio_unitario:100}),0);
  cart=[{id:1}];approve=false;await cambiarModoVenta('mostrador');assert.equal(_posCanal,'cdmx');assert.equal(cart.length,1);
  approve=true;await cambiarModoVenta('mostrador');assert.equal(clears,1);assert.equal(cart.length,0);
  assert.equal(precioProductoPOS(product),100);
  await cambiarModoVenta('uber_eats');assert.equal(precioProductoPOS(product),120);
})();
""")


def test_cdmx_only_shows_products_with_its_price_including_zero_stock():
    node(HARNESS + section("function precioProductoPOS", "var POS_DRAFT_KEY")
         + section("var _posGroups = {}", "function cargarPOSProductos") + r"""
_posCanal='cdmx';
renderPOSFromData([
  {id:1,nombre:'CDMX disponible',activo:true,stock_actual:4,precio_cdmx:180,precio_unitario:100},
  {id:2,nombre:'Sin precio CDMX',activo:true,stock_actual:20,precio_unitario:100},
  {id:3,nombre:'Inactivo',activo:false,precio_cdmx:100},
  {id:4,nombre:'CDMX agotado',activo:true,stock_actual:0,precio_cdmx:400}
]);
assert.deepEqual(Object.keys(_posGroups).sort(),['1','4']);
assert(fields['pos-products'].innerHTML.includes('$180.00'));
assert(!fields['pos-products'].innerHTML.includes('Sin precio CDMX'));
assert(fields['pos-products'].innerHTML.includes('Agotado'));
renderPOSFromData([{id:2,activo:true,precio_unitario:100}]);
assert(fields['pos-products'].innerHTML.includes('Sin productos con precio CDMX'));
""")


def test_cdmx_draft_restores_its_channel_and_reconciles_only_available_prices():
    node(HARNESS + section("function precioProductoPOS", "var POS_DRAFT_KEY")
         + section("var POS_DRAFT_KEY", "function updateMobileTicketBar") + r"""
let draft={owner:'1',savedAt:Date.now(),channel:'cdmx',items:[{id:1,n:'Test',p:100,q:1},{id:2,n:'Unpriced',p:100,q:1}]};
const localStorage={getItem:()=>JSON.stringify(draft),setItem(){},removeItem(){}};
const _currentUser={id:1};let pm='ef',_ventaIdempotencyKey=null,_posFacturaIvaActiva=false;
function setPm(){}function ren(){}function actualizarModoVentaUI(){}
restorePosDraft(_currentUser);assert.equal(_posCanal,'cdmx');
reconcilePosDraftWithProducts([{id:1,nombre:'CDMX',activo:true,precio_cdmx:180},{id:2,activo:true,precio_unitario:100}]);
assert.equal(cart.length,1);assert.equal(cart[0].p,180);assert.equal(cart[0].n,'CDMX');
""")


def test_cdmx_price_fields_export_and_mobile_tabs_are_available():
    assert HTML.count('data-sales-mode="cdmx"') == 2
    assert 'id="mnp-precio-cdmx"' in HTML
    assert 'id="mep-precio-cdmx"' in HTML
    assert "precio_cdmx: precioCdmxRaw ? Number(precioCdmxRaw) : null" in HTML
    assert "Precio Uber Eats,Precio CDMX,Costo" in HTML
    assert ".sales-mode-tabs{width:100%;display:grid;grid-template-columns:repeat(2,minmax(0,1fr))}" in HTML
    assert section("function nuevaPresentacion", "function actualizarEstadoCodigo").count("document.getElementById('mnp-precio-cdmx').value = '';") == 1


def test_save_cdmx_only_sends_its_price_and_blocks_duplicate_writes():
    node(HARNESS + section("var _guardandoPrecioCdmx", "function guardarProducto") + r"""
let _versionSesion=1,calls=[],release;
fields['mep-id']={value:'123'};
fields['mep-precio-cdmx']={value:'400',checkValidity:()=>true};
fields['modal-edit-prod']={classList:{contains:()=>true}};
fields['mep-precio']={value:'350'};fields['mep-caja']={value:'99'};
function pedirPasswordAdminSiHaceFalta(){return Promise.resolve({});}
function api(...args){calls.push(args);return new Promise(resolve=>{release=resolve;});}
function cargarListaProductos(){}function cargarPOSProductos(){}
(async()=>{
  let first=guardarPrecioCdmx();await Promise.resolve();await guardarPrecioCdmx();
  assert.equal(calls.length,1);assert.equal(calls[0][0],'PUT');assert.equal(calls[0][1],'/inventario/productos/123');
  assert.deepEqual(calls[0][2],{precio_cdmx:400});assert.equal(calls[0][5],1);
  assert.equal(fields['mep-guardar-cdmx'].disabled,true);release({});await first;
  assert.equal(fields['mep-guardar-cdmx'].disabled,false);
  assert.equal(fields['mep-precio'].value,'350');assert.equal(fields['mep-caja'].value,'99');
})();
""")


def test_cdmx_save_does_not_write_after_session_change_or_retry_on_error():
    node(HARNESS + section("var _guardandoPrecioCdmx", "function guardarProducto") + r"""
let _versionSesion=1,calls=0,authorizationReply;
fields['mep-id']={value:'123'};fields['mep-precio-cdmx']={value:'400',checkValidity:()=>true};
fields['modal-edit-prod']={classList:{contains:()=>true}};
function pedirPasswordAdminSiHaceFalta(){return new Promise(resolve=>{authorizationReply=resolve;});}
function api(){calls++;return Promise.reject(new Error('Servidor no disponible'));}
function cargarListaProductos(){}function cargarPOSProductos(){}
(async()=>{
  let first=guardarPrecioCdmx();_versionSesion=2;authorizationReply({});await first;assert.equal(calls,0);
  let next=guardarPrecioCdmx();authorizationReply({});await next;assert.equal(calls,1);
  assert.equal(fields['mep-guardar-cdmx'].disabled,false);
})();
""")
