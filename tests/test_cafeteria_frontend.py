"""Run the actual receivables functions against a bounded DOM/API harness."""

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
const assert=require('node:assert/strict'), fields={}, messages=[], downloads=[];
const document={getElementById:id=>fields[id]||={value:'',textContent:'',innerHTML:'',disabled:false,
  hidden:false,style:{},focus(){},setAttribute(){},classList:{toggle(){},add(){},remove(){}}}};
const window={_permisos:{cafeteria:'editar'}};
let _versionSesion=1,_cafCobranzaVista='pendientes',_cafCobranzaOffset=0,_cafCobranzaSeq=0,
  _cafCobranzaMas=false,_cafVentas=[],_cafFechaGuardando={},_cafPagoContext=null,
  _cafPagoGuardando=false,_cafPagosPendientes={},cafPm='ef',keyCount=0,closed=[],refreshes=0;
function fmt(v){return Number(v).toFixed(2);}
function fmtQty(v){return String(v);}
function escHtml(v){return String(v).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
function jsArg(v){return JSON.stringify(v);}
function toast(v){messages.push(v);}
function fechaHoyISO(){return '2026-10-08';}
function formatearInstanteOperacion(v){return v.slice(0,10);}
function nuevaClaveIdempotencia(){return 'test-'+(++keyCount);}
function cerrarModal(id){closed.push(id);}
function cargarCafeteriaReportes(){}
function apiCacheInvalidate(){}
function descargarArchivoAutenticado(...args){downloads.push(args);return Promise.resolve();}
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};}
const cuenta={id:1,folio:'CAF-PRUEBA',cafeteria_nombre:'Cafe & Uno',total:'100.00',monto_pagado:'25.00',
  saldo_pendiente:'75.00',estado:'parcial',fecha:'2026-10-01T12:00:00Z',fecha_entrega:null,
  fecha_credito:'2026-10-08',detalles:[{cantidad:1,producto_nombre:'Pan <chocolate>'}],
  pagos:[{id:1,monto:'25.00',fecha:'2026-10-05T06:00:00Z',fecha_pago:'2026-10-05',
    metodo_pago:'03',terminal:'efectivo',referencia:'REF <uno>'}]};
"""
FUNCTIONS = (section("function metodoPagoCafeteria", "function registrarCafeteria")
             + section("function cargarCafeteriaVentas", "async function cancelarCafeteria"))
SESSION_RESET = section("function invalidarTareasSesion()", "function moduloDesactivado")
SESSION_HARNESS = r"""
let _ticketEdicion=null,_ventaEnProceso=false,_apiGetCache={},_apiGetInFlight={},_migracionVentasTx=null;
let _dashGetCache={old:Promise.resolve({})},_dashCacheAt=100;
let _resguardoSeq=0,_egresosResumenSeq=0,_egOcrSeq=0,_ocrSeq=0;
function cancelarAdminAuth(){}
function cerrarClaveAutorizacion(){}
function cerrarUsuario(){}
function cerrarCamaraEgreso(){}
function limpiarEgresoForm(){}
"""


def test_sales_catalogs_only_show_generic_product_search():
    pos = section('<div class="page" id="pos">', '<!-- CAFETERIA -->')
    cafe = section('<div class="page" id="cafeteria">', '<!-- PEDIDOS -->')
    for page in (pos, cafe):
        assert 'placeholder="Buscar producto..."' in page
        assert 'sales-mode-badge' not in page
        assert 'pos-uber-connect' not in page
        assert 'caf-k-llevado' not in page
        assert 'cafeteria-tools' not in page
    assert 'Normal $' not in section("function renderCafeteriaProductos", "function cargarCafeteriaProductos")
    assert 'id="caf-fecha-entrega"' in cafe
    assert 'id="caf-fecha-pago-inicial"' in cafe
    assert 'id="caf-filtro-cliente"' in cafe
    assert 'role="tablist" aria-label="Cuentas de cafeter' in cafe


def test_client_filter_pagination_and_out_of_order_responses_do_not_mix():
    node(HARNESS + FUNCTIONS + r"""
let requests=[];
function api(method,path){const d=deferred();requests.push({method,path,...d});return d.promise;}
(async()=>{
  document.getElementById('caf-ventas').innerHTML='OLD';
  document.getElementById('caf-filtro-cliente').value='id:1';let a=cargarCafeteriaVentas();
  assert.equal(fields['caf-ventas'].innerHTML,'');assert.equal(fields['caf-pdf-cliente'].disabled,false);
  assert(requests[0].path.includes('pendientes=true&cafeteria_id=1'));
  fields['caf-filtro-cliente'].value='id:2';let b=cargarCafeteriaVentas();
  requests[2].resolve([{...cuenta,folio:'CAF-CLIENTE-2'}]);
  requests[3].resolve({saldo:75,cuentas:1,vencidas:0});await b;
  requests[0].resolve([{...cuenta,folio:'CAF-CLIENTE-1'}]);
  requests[1].resolve({saldo:999,cuentas:99,vencidas:99});await a;
  assert(fields['caf-ventas'].innerHTML.includes('CAF-CLIENTE-2'));
  assert(!fields['caf-ventas'].innerHTML.includes('CAF-CLIENTE-1'));
  assert.equal(fields['caf-cobranza-saldo'].textContent,'$75.00');
  let hist=cambiarVistaCobranza('historial');assert(requests[4].path.includes('pendientes=false'));
  requests[4].resolve(Array.from({length:51},(_,i)=>({...cuenta,id:i+1})));
  requests[5].resolve({saldo:75,cuentas:1,vencidas:0});await hist;
  assert.equal(_cafVentas.length,50);assert.equal(fields['caf-pagination'].hidden,false);
  let next=cambiarPaginaCafeteria(1);assert(requests[6].path.includes('offset=50'));
  requests[6].resolve([cuenta]);requests[7].resolve({saldo:75,cuentas:1});await next;
  assert.equal(fields['caf-pagina-label'].textContent,'Página 2');assert.equal(_cafCobranzaMas,false);
})();
""")


def test_loading_error_clears_stale_data_and_session_change_cannot_repaint():
    node(HARNESS + FUNCTIONS + r"""
let requests=[];function api(){const d=deferred();requests.push(d);return d.promise;}
(async()=>{
  document.getElementById('caf-filtro-cliente').value='id:1';
  let load=cargarCafeteriaVentas();requests[0].reject(new Error('Servidor no disponible'));
  requests[1].reject(new Error('Servidor no disponible'));await load;
  assert(fields['caf-ventas'].innerHTML.includes('Reintentar'));assert.deepEqual(_cafVentas,[]);
  assert.equal(fields['caf-cobranza-saldo'].textContent,'--');
  assert.equal(fields['caf-cobranza-cuentas'].textContent,'Saldo no disponible');
  let old=cargarCafeteriaVentas();_versionSesion++;
  requests[2].resolve([cuenta]);requests[3].resolve({saldo:999,cuentas:99});await old;
  assert.equal(fields['caf-ventas'].innerHTML,'');
  assert.equal(fields['caf-cobranza-saldo'].textContent,'--');
})();
""")


def test_first_client_is_selected_before_loading_accounts_and_all_is_explicit():
    node(HARNESS + FUNCTIONS + r"""
let requests=[];
function api(method,path){requests.push(path);return Promise.resolve(path.endsWith('/clientes')?
  [{id:3,nombre:'Primero'},{id:4,nombre:'Segundo'}]:path.includes('/ventas?')?[]:{saldo:0,cuentas:0,vencidas:0});}
(async()=>{
  await cargarCafeteriaVentas();assert.equal(requests.length,0);
  await cargarClientesCobranzaCafeteria();assert.equal(fields['caf-filtro-cliente'].value,'id:3');
  await cargarCafeteriaVentas();assert(requests[1].includes('cafeteria_id=3'));
  fields['caf-filtro-cliente'].value='todos';await cargarClientesCobranzaCafeteria();
  assert.equal(fields['caf-filtro-cliente'].value,'todos');
  await cargarCafeteriaVentas();assert(!requests.at(-2).includes('cafeteria_id='));
  fields['caf-filtro-cliente'].value='id:999';await cargarClientesCobranzaCafeteria();
  assert.equal(fields['caf-filtro-cliente'].value,'id:3');
})();
""")


def test_pdf_requires_selected_client_and_excel_never_uses_list_filter_or_limit():
    node(HARNESS + FUNCTIONS + r"""
descargarEstadoCuentaCafeteria();assert.equal(downloads.length,0);
document.getElementById('caf-filtro-cliente').value='id:2';
descargarEstadoCuentaCafeteria();assert.equal(downloads[0][0],'/api/v1/cafeteria/estado-cuenta/pdf?cafeteria_id=2');
fields['caf-filtro-cliente'].value='nombre:Cafe & Norte';
descargarEstadoCuentaCafeteria();assert(downloads[1][0].endsWith('cafeteria_nombre=Cafe%20%26%20Norte'));
_cafCobranzaOffset=100;descargarHistorialCafeteriaExcel();
assert.equal(downloads[2][0],'/api/v1/cafeteria/historial/excel');
""")


def test_pending_and_history_render_payment_dates_without_html_injection():
    node(HARNESS + FUNCTIONS + r"""
const paid={...cuenta,id:2,folio:'CAF-PAGADA',estado:'pagada',saldo_pendiente:'0.00'};
const canceled={...cuenta,id:3,folio:'CAF-CANCELADA',estado:'cancelada',saldo_pendiente:'100.00'};
renderCafeteriaVentas([cuenta,paid,canceled]);let h=fields['caf-ventas'].innerHTML;
assert(h.includes('CAF-PRUEBA'));assert(!h.includes('CAF-PAGADA'));assert(!h.includes('CAF-CANCELADA'));
assert(h.includes('No registrada'));assert(h.includes('Pagos (1)'));
assert(h.includes('2026'));assert(h.includes('REF &lt;uno&gt;'));assert(!h.includes('REF <uno>'));
assert(h.includes('Pan &lt;chocolate&gt;'));
_cafCobranzaVista='historial';window._permisos.cafeteria='ver';renderCafeteriaVentas([paid,canceled]);
h=fields['caf-ventas'].innerHTML;assert(h.includes('CAF-PAGADA'));assert(h.includes('CAF-CANCELADA'));
assert(!h.includes('Pago parcial'));assert(!h.includes('Editar fecha de entrega'));
""")


def test_payment_double_click_and_ambiguous_retry_use_same_body_and_independent_method():
    node(HARNESS + FUNCTIONS + r"""
let requests=[];function api(...args){const d=deferred();requests.push({args,...d});return d.promise;}
cargarCafeteriaVentas=()=>{refreshes++;return Promise.resolve();};
(async()=>{
  _cafVentas=[cuenta];pagarCafeteria(1,false);
  fields['caf-pago-monto'].value='20.25';fields['caf-pago-fecha'].value='2026-10-06';
  fields['caf-pago-metodo'].value='bbva';fields['caf-pago-referencia'].value=' REF-25 ';
  let first=guardarPagoCafeteria();await guardarPagoCafeteria();assert.equal(requests.length,1);
  const body=requests[0].args[2];assert.equal(body.monto,20.25);assert.equal(body.fecha_pago,'2026-10-06');
  assert.equal(body.metodo_pago,'28');assert.equal(body.terminal,'bbva');assert.equal(body.referencia,'REF-25');
  assert.equal(cafPm,'ef');assert.equal(requests[0].args[5],1);
  requests[0].reject(Object.assign(new Error('Timeout'),{status:503}));await first;
  assert.equal(fields['caf-pago-monto'].disabled,true);
  assert.equal(fields['caf-pago-guardar'].textContent,'Reintentar el mismo pago');
  pagarCafeteria(1,false);assert.equal(fields['caf-pago-monto'].value,20.25);
  fields['caf-pago-monto'].value='50';let retry=guardarPagoCafeteria();
  assert.deepEqual(requests[1].args[2],body);assert.equal(keyCount,1);
  requests[1].resolve({...cuenta,monto_pagado:'45.25'});await retry;
  assert.equal(refreshes,1);assert.deepEqual(closed,['modal-caf-pago']);
  assert.equal(_cafPagoContext,null);assert.equal(_cafPagosPendientes[1],undefined);
})();
""")


def test_payment_validation_unlocks_on_rejection_and_never_submits_after_session_change():
    node(HARNESS + FUNCTIONS + r"""
let requests=[];function api(...args){const d=deferred();requests.push({args,...d});return d.promise;}
(async()=>{
  _cafVentas=[cuenta];pagarCafeteria(1,true);assert.equal(fields['caf-pago-monto'].readOnly,true);
  fields['caf-pago-monto'].value='999';await guardarPagoCafeteria();assert.equal(requests.length,0);
  fields['caf-pago-monto'].value='75';let first=guardarPagoCafeteria();
  requests[0].reject(Object.assign(new Error('Saldo cambió'),{status:400}));await first;
  assert.equal(fields['caf-pago-monto'].disabled,false);assert.equal(_cafPagoContext.body,null);
  assert.equal(keyCount,2);assert.equal(_cafPagosPendientes[1],undefined);
  _versionSesion++;await guardarPagoCafeteria();assert.equal(requests.length,1);
})();
""")


def test_delivery_date_edit_respects_session_and_does_not_send_payment_data():
    node(HARNESS + FUNCTIONS + r"""
let prompt,requests=[];function solicitarEntrada(){prompt=deferred();return prompt.promise;}
function api(...args){requests.push(args);return Promise.resolve();}
cargarCafeteriaVentas=()=>Promise.resolve();
(async()=>{
  _cafVentas=[cuenta];let old=editarFechaEntregaCafeteria(1);_versionSesion++;
  prompt.resolve('2026-10-01');await old;assert.equal(requests.length,0);
  let next=editarFechaEntregaCafeteria(1);prompt.resolve('2026-10-02');await next;
  assert.equal(requests[0][0],'PUT');assert.equal(requests[0][1],'/cafeteria/ventas/1/entrega');
  assert.deepEqual(requests[0][2],{fecha_entrega:'2026-10-02'});assert.equal(requests[0][5],2);
})();
""")


def test_old_payment_completion_cannot_unlock_another_users_payment():
    node(HARNESS + SESSION_HARNESS + FUNCTIONS + SESSION_RESET + r"""
let requests=[];function api(...args){const d=deferred();requests.push({args,...d});return d.promise;}
cargarCafeteriaVentas=()=>{refreshes++;return Promise.resolve();};
(async()=>{
  _cafVentas=[cuenta];pagarCafeteria(1,true);let old=guardarPagoCafeteria();
  assert.equal(_cafPagoGuardando,true);invalidarTareasSesion();
  assert.equal(_cafPagoGuardando,false);assert.equal(_cafPagoContext,null);
  assert.deepEqual(_dashGetCache,{});assert.equal(_dashCacheAt,0);
  assert.deepEqual(_cafPagosPendientes,{});assert.deepEqual(_cafVentas,[]);
  assert.deepEqual(closed,['modal-caf-pago']);
  _cafVentas=[cuenta];pagarCafeteria(1,true);let current=guardarPagoCafeteria();
  requests[0].resolve(cuenta);await old;
  assert.equal(_cafPagoGuardando,true);assert.equal(fields['caf-pago-guardar'].disabled,true);
  assert.equal(refreshes,0);assert.equal(_cafPagoContext.version,2);
  await guardarPagoCafeteria();assert.equal(requests.length,2);
  requests[1].resolve(cuenta);await current;
  assert.equal(_cafPagoGuardando,false);assert.equal(refreshes,1);
})();
""")


def test_old_delivery_completion_cannot_unlock_another_users_edit():
    node(HARNESS + SESSION_HARNESS + FUNCTIONS + SESSION_RESET + r"""
let requests=[];function solicitarEntrada(){return Promise.resolve('2026-10-02');}
function api(...args){const d=deferred();requests.push({args,...d});return d.promise;}
cargarCafeteriaVentas=()=>{refreshes++;return Promise.resolve();};
(async()=>{
  _cafVentas=[cuenta];let old=editarFechaEntregaCafeteria(1);await Promise.resolve();
  assert.equal(_cafFechaGuardando[1],true);invalidarTareasSesion();
  assert.deepEqual(_cafFechaGuardando,{});
  _cafVentas=[cuenta];let current=editarFechaEntregaCafeteria(1);await Promise.resolve();
  requests[0].resolve(cuenta);await old;
  assert.equal(_cafFechaGuardando[1],true);assert.equal(refreshes,0);
  await editarFechaEntregaCafeteria(1);assert.equal(requests.length,2);
  requests[1].resolve(cuenta);await current;
  assert.equal(_cafFechaGuardando[1],undefined);assert.equal(refreshes,1);
})();
""")
