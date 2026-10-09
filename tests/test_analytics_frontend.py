"""Actual analytics functions: recovery, stale requests and CRM permissions."""

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
const assert=require('node:assert/strict'), fields={}, calls=[];
function field(id){return fields[id]||=( {value:'',textContent:'',innerHTML:'',disabled:false,
  hidden:false,style:{},children:[],parentElement:{hidden:false},
  appendChild(child){if(child.parentElement.children) child.parentElement.children=child.parentElement.children.filter(c=>c!==child);
    this.children.push(child);child.parentElement=this;},
  getAttribute(){return '';},setAttribute(){},querySelectorAll(){return [];},
  classList:{toggle(){},add(){},remove(){}}});}
const document={getElementById:field,querySelectorAll:()=>[],querySelector:()=>null};
const window={_permisos:{crm:'ver',listas:'ver'}};
let _versionSesion=1,admin=true;
function esAdminActual(){return admin;}
function fmt(v){return Number(v).toFixed(2);}
function fmtQty(v){return String(v);}
function escHtml(v){return String(v).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
function fechaCortaCafeteria(v){return v;}
function formatearInstanteOperacion(v){return v.slice(0,10);}
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};}
function api(method,path){const d=deferred();calls.push({method,path,...d});return d.promise;}
"""
DASH = section("var _chartMeses = null;", "var _chartVentas = null;")
DASH_HARNESS = r"""
let _dashGetCache={},invalidated=[],charts=[];
function dashGet(path){return api('GET',path);}
function apiCacheInvalidate(path){invalidated.push(path);}
let Chart=function(ctx,options){charts.push({ctx,options});this.destroy=()=>{};};
const monthly={utilidad:{ingresos:100,costo_ventas:40,utilidad_bruta:60,gastos_fijos:10,
  utilidad_neta:50,partidas_sin_costo:2},meses:[{mes:'Oct 2026',total:100}],
  clientes_vip:[{nombre:'Cliente <uno>',puntos:5,total_compras:100,visitas:1}]};
"""
IA = section("var _iaVista = 'ia-dash';", "// \u2500\u2500\u2500 Contabilidad")
CRM = section("var _crmSeq = 0,", "function cargarSegmentacion()")


def test_dashboard_error_retry_empty_and_chart_failures_preserve_real_values():
    node(HARNESS + DASH_HARNESS + DASH + r"""
(async()=>{
  admin=false;await cargarDashAvanzado();assert.equal(calls.length,0);admin=true;
  let load=cargarDashAvanzado();calls[0].reject(new Error('Servidor no disponible'));await load;
  assert.equal(field('da-u-ingresos').textContent,'--');assert.equal(field('da-reintentar').hidden,false);
  assert(field('da-estado').textContent.includes('Servidor'));
  _dashGetCache['/reportes/dashboard-avanzado']=monthly;
  load=cargarDashAvanzado(true);calls[1].resolve(monthly);await load;
  assert.equal(_dashGetCache['/reportes/dashboard-avanzado'],undefined);
  assert.deepEqual(invalidated,['/reportes/dashboard-avanzado']);
  assert.equal(field('da-u-ingresos').textContent,'$100.00');
  assert(field('da-costos-aviso').textContent.includes('2 partidas'));
  assert(field('da-vip').innerHTML.includes('Cliente &lt;uno&gt;'));
  assert.equal(charts.length,1);assert.equal(field('chart-meses').parentElement.hidden,false);
  load=cargarDashAvanzado();calls[2].resolve({...monthly,meses:[]});await load;
  assert.equal(field('chart-meses').parentElement.hidden,true);assert(field('da-estado').textContent.includes('Sin ventas'));
  Chart=function(){throw new Error('Canvas no disponible');};
  load=cargarDashAvanzado();calls[3].resolve(monthly);await load;
  assert(field('da-estado').textContent.includes('Datos disponibles'));
  assert(field('da-vip').innerHTML.includes('Cliente &lt;uno&gt;'));
  assert.equal(field('da-u-neta').textContent,'$50.00');
})();
""")


def test_dashboard_stale_response_and_delayed_chart_do_not_repaint_new_session():
    node(HARNESS + DASH_HARNESS + DASH + r"""
(async()=>{
  let old=cargarDashAvanzado(),current=cargarDashAvanzado();
  calls[1].resolve(monthly);await current;
  calls[0].resolve({...monthly,utilidad:{...monthly.utilidad,ingresos:999}});await old;
  assert.equal(field('da-u-ingresos').textContent,'$100.00');
  Chart=undefined;const chartReady=deferred();function ensure(){return chartReady.promise;}
  globalThis.ensureChart=ensure;
  let late=cargarDashAvanzado();calls[2].resolve(monthly);await new Promise(resolve=>setImmediate(resolve));
  _versionSesion++;Chart=function(){throw new Error('Should not render');};chartReady.resolve();await late;
  assert.equal(field('chart-meses').parentElement.hidden,true);
})();
""")


def test_old_dashboard_cache_rejection_cannot_remove_new_session_request():
    node(HARNESS + section("var _dashGetCache = {};", "function deferDashboard") + r"""
(async()=>{
  const path='/reportes/dashboard-avanzado';
  const old=dashGet(path);const oldResult=old.catch(()=>{});
  assert.equal(dashGet(path),old);assert.equal(calls.length,1);
  _dashGetCache={};_dashCacheAt=0;
  const current=dashGet(path);assert.equal(calls.length,2);
  calls[0].reject(new Error('Sesion anterior'));await oldResult;
  assert.equal(dashGet(path),current);assert.equal(calls.length,2);
  calls[1].resolve({ingresos:100});await current;
})();
""")


def test_prediction_can_reload_dashboard_and_ignores_old_requests_and_errors():
    node(HARNESS + IA + r"""
const forecast={precision_modelo:{muestras:0,valor:0,calificacion:'sin datos'},
  total_productos_hornear:0,alertas_pricing:[],sugerencias_produccion:[],
  impacto_potencial_mensual:0,productos_sin_rotacion:0,advertencias:['Stock <negativo>'],fecha_base:'2026-10-08'};
(async()=>{
  let old=initIA(),current=iaTab('ia-dash');assert.equal(calls.length,2);
  calls[1].resolve(forecast);await current;
  calls[0].resolve({...forecast,total_productos_hornear:999});await old;
  assert(field('ia-dash-content').innerHTML.includes('Stock &lt;negativo&gt;'));
  assert(!field('ia-dash-content').innerHTML.includes('999'));
  assert(!field('ia-dash-content').innerHTML.includes('entrenamiento'));
  let prod=iaTab('ia-produccion');calls[2].reject(new Error('Servidor <offline>'));await prod;
  assert(field('ia-prod-content').innerHTML.includes('Reintentar'));
  assert(field('ia-prod-content').innerHTML.includes('Servidor &lt;offline&gt;'));
  prod=initIA();assert(calls[3].path.includes('produccion-sugerida'));
  _versionSesion++;calls[3].resolve([{nombre:'Should not paint'}]);await prod;
  assert(!field('ia-prod-content').innerHTML.includes('Should not paint'));
})();
""")


def test_crm_filter_pagination_purchase_detail_and_session_guards():
    node(HARNESS + CRM + r"""
const customer={cliente_id:1,nombre:'Cliente <uno>',nivel:'plata',telefono:'442',
  total_compras:100,compras:2,ticket_promedio:50,puntos:10,ultima_compra:'2026-10-08'};
const purchase={nombre:'Cliente <uno>',hay_mas:true,compras:[{folio:'T-1',fecha:'2026-10-08T12:00:00Z',
  total:50,detalles:[{cantidad:1,producto:'Pan <chocolate>'}]}]};
(async()=>{
  let load=initCRM();assert(calls[0].path.includes('limit=50&offset=0'));
  calls[0].resolve({clientes:[customer],hay_mas:true});await load;
  assert(field('crm-clientes-tbl').innerHTML.includes('Cliente &lt;uno&gt;'));
  assert(field('crm-clientes-tbl').innerHTML.includes('$100.00'));
  assert.equal(field('crm-siguiente').disabled,false);
  let detail=verComprasCRM(1,0);calls[1].resolve(purchase);await detail;
  assert(field('crm-compras').innerHTML.includes('Pan &lt;chocolate&gt;'));
  assert(field('crm-compras').innerHTML.includes('verComprasCRM(1,25)'));
  detail=verComprasCRM(1,25);load=paginaClientesCRM(1);
  assert.equal(field('crm-compras').hidden,true);assert(calls[3].path.includes('offset=50'));
  calls[3].resolve({clientes:[],hay_mas:false});await load;
  calls[2].resolve(purchase);await detail;assert.equal(field('crm-compras').hidden,true);
  field('crm-buscar').value='Cafe & Norte';_crmOffset=0;
  load=cargarClientesCRM();assert(calls[4].path.includes('q=Cafe%20%26%20Norte'));
  _versionSesion++;calls[4].resolve({clientes:[customer],hay_mas:true});await load;
  assert.equal(field('crm-clientes-tbl').innerHTML,'');
  load=cargarClientesCRM();calls[5].reject(new Error('Servidor no disponible'));await load;
  assert(field('crm-clientes-tbl').innerHTML.includes('Reintentar'));
})();
""")


def test_loyalty_uses_single_panel_and_preserves_list_permissions():
    node(HARNESS + CRM + r"""
let loyaltyLoads=0;function cargarLealtad(){loyaltyLoads++;return Promise.resolve();}
(async()=>{
  const panel=field('l-lealtad');field('listas').appendChild(panel);
  await crmTab('c-lealtad');assert.equal(panel.parentElement,field('c-lealtad'));
  assert.equal(field('listas').children.length,0);
  mostrarLealtadEnCRM(false);assert.equal(panel.parentElement,field('listas'));
  assert.equal(field('c-lealtad').children.length,0);
  window._permisos.listas='oculto';await crmTab('c-lealtad');
  assert.equal(loyaltyLoads,1);assert.equal(panel.parentElement,field('listas'));
})();
""")
    assert "if ((window._permisos || {}).listas !== 'editar') return;" in section(
        "function guardarConfigLealtad()", "// \u2500\u2500\u2500 Sucursales")
    assert HTML.count('id="l-lealtad"') == 1
    assert 'id="lealtad-dash" class="card"' not in HTML


def test_prediction_cache_is_short_lived_and_does_not_cache_customer_data():
    node(HARNESS + section("function apiGetCacheTtl", "function apiGetCacheRead") + r"""
assert.equal(apiGetCacheTtl('/ia/dashboard'),30000);
assert.equal(apiGetCacheTtl('/ia/pricing?dias=30'),30000);
assert.equal(apiGetCacheTtl('/crm/clientes'),0);
""")


def test_loading_lists_restores_loyalty_without_changing_selected_tab():
    node(HARNESS + CRM + section("function cargarListas()", "function cargarListaProductos()") + r"""
let selected=true,loyaltyLoads=0;
document.querySelector=selector=>selector==='#listas .tab.active[onclick*="l-lealtad"]'&&selected?{}:null;
function cargarLealtad(){loyaltyLoads++;return Promise.resolve();}
function cargarListaProductos(){}
function cargarListaFamiliasProducto(){}
function cargarListaEmpaques(){}
function cargarListaClientes(){}
(async()=>{
  const panel=field('l-lealtad');field('listas').appendChild(panel);
  await crmTab('c-lealtad');assert.equal(panel.parentElement,field('c-lealtad'));
  cargarListas();assert.equal(panel.parentElement,field('listas'));
  assert.equal(panel.style.display,'block');assert.equal(loyaltyLoads,2);
  selected=false;await crmTab('c-lealtad');cargarListas();
  assert.equal(panel.parentElement,field('listas'));assert.equal(panel.style.display,'none');
  assert.equal(loyaltyLoads,3);
})();
""")
