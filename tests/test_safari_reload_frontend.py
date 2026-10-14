"""Startup, read recovery and mobile refresh execute without production APIs."""

from html.parser import HTMLParser
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
    script += r"""
const watchdog=require('node:timers').setTimeout(()=>process.exit(97),8000);
run().then(()=>require('node:timers').clearTimeout(watchdog),e=>{
  require('node:timers').clearTimeout(watchdog);console.error(e);process.exitCode=1;
});
"""
    result = subprocess.run([executable, "-e", script], capture_output=True, text=True, timeout=12)
    assert result.returncode == 0, result.stderr


class HeadParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.head = False
        self.noscript = False
        self.tags = []

    def handle_starttag(self, tag, attrs):
        if tag == "head":
            self.head = True
        if tag == "noscript":
            self.noscript = True
        if self.head and not self.noscript and tag in {"script", "link"}:
            self.tags.append((tag, dict(attrs)))

    def handle_endtag(self, tag):
        if tag == "head":
            self.head = False
        if tag == "noscript":
            self.noscript = False


def test_startup_does_not_wait_for_fonts_or_core_before_painting():
    parser = HeadParser()
    parser.feed(HTML)
    core = [attrs for tag, attrs in parser.tags if tag == "script" and attrs.get("src") == "js/jacaranda-core.js"]
    fonts = [attrs for tag, attrs in parser.tags if tag == "link" and "fonts.googleapis.com" in attrs.get("href", "")]
    assert len(core) == len(fonts) == 1
    assert "defer" in core[0]
    assert fonts[0]["rel"] == "preload"
    assert fonts[0]["as"] == "style"
    assert "this.rel='stylesheet'" in fonts[0]["onload"]


START_HARNESS = r"""
const assert=require('node:assert/strict'),fields={},requests=[],posts=[],timers=new Map();
const document={getElementById:id=>fields[id]||=( {style:{},textContent:''}),querySelector:()=>({style:{}})};
const user={id:1,rol:'CAJERO',permisos_modulos:{pos:'editar',ped:'ver'}};
const stored=new Map([['jacaranda_token','test-token'],['jacaranda_user',JSON.stringify(user)]]);
const localStorage={getItem:key=>stored.get(key)||null};
let TOKEN='',REFRESH_TOKEN='',API_URL='https://api.test',_versionSesion=1,_currentUser=null,starts=0,active='pos';
let nextTimer=0;const connected=[];
function setTimeout(fn,ms){const id=++nextTimer;timers.set(id,{fn,ms});return id;}
function clearTimeout(id){timers.delete(id);}
function esRutaClientePublica(){return false;}
function esArchivoLocal(){return false;}
function usuarioCacheado(){return user;}
function mostrarInicioGuardado(u){starts++;_currentUser=u;active='pos';}
function apiLecturaRecuperable(path,options){return new Promise((resolve,reject)=>requests.push({path,options,resolve,reject}));}
function setConnecting(){}
function setConnected(ok){connected.push(ok);}
function esSesionExpirada(e){return e.status===401||e.status===403;}
function mostrarErrorLogin(message){document.getElementById('login-error').textContent=message;}
function postLogin(u,opts){posts.push({u,opts,active});}
""" + section("var _reconectar = 0;", "\nactualizarBannerOffline();\ninitNavDropdowns();")


def test_startup_deduplicates_validation_and_reconnect_preserves_active_view():
    node(START_HARNESS + r"""
async function run(){
  const first=autoConectar();assert.equal(autoConectar(),first);assert.equal(requests.length,1);
  assert.equal(starts,1);assert.equal(requests[0].options.silenciosa,true);
  active='ped';requests[0].reject({status:503});await first;
  assert.equal(fields['login-screen'].style.display,'none');assert.equal(stored.get('jacaranda_token'),'test-token');
  assert.equal(timers.size,1);assert.equal([...timers.values()][0].ms,15000);
  const retry=autoConectar();assert.equal(starts,1);requests[1].resolve(user);await retry;
  assert.equal(posts[0].active,'ped');assert.equal(posts[0].opts.conservarVista,true);
  assert.equal(timers.size,0);assert.equal(_autoConectarEnCurso,null);
}
""")


@pytest.mark.parametrize("result", ["success", "failure"])
def test_old_startup_cannot_hide_login_or_schedule_retry_after_logout(result):
    node(START_HARNESS + "const result=" + repr(result) + r""";
async function run(){
  const old=autoConectar();_versionSesion++;_currentUser=null;
  fields['login-screen'].style.display='flex';
  if(result==='success')requests[0].resolve(user);else requests[0].reject({status:503});
  await old;assert.equal(fields['login-screen'].style.display,'flex');
  assert.equal(posts.length,0);assert.equal(timers.size,0);
  const current=autoConectar();requests[1].resolve(user);await current;assert.equal(posts.length,1);
}
""")


def test_cached_products_are_rendered_before_session_validation_finishes():
    harness = r"""
const assert=require('node:assert/strict');
let _currentUser=null,_userRole='',_offline=false,renders=[],drafts=0,selected='',reconciled=0;
const APP_DEFAULT_PAGE='pos',products=[{id:1,precio_unitario:100}],document={getElementById:()=>({})};
function pantallaInicialUsuario(){return 'pos';}function mostrarBotonActualizarApp(){}
function aplicarPermisosModulos(){}function restorePosDraft(){drafts++;}
function activarPagina(tab){selected=tab;}function leerCacheLocalJson(){return products;}
function actualizarBannerOffline(){}function renderPOSFromData(p){renders.push(p);}
function reconcilePosDraftWithProducts(){reconciled++;}
"""
    node(harness + section("function mostrarInicioGuardado(u)", "function aplicarPostLogin") + r"""
async function run(){mostrarInicioGuardado({id:1,rol:'CAJERO'});
  assert.equal(selected,'pos');assert.equal(drafts,1);assert.deepEqual(renders,[products]);assert.equal(_offline,true);
  assert.equal(reconciled,0);}
""")


def test_post_login_preserves_working_view_and_draft_only_for_same_customer_session():
    harness = r"""
const assert=require('node:assert/strict'),tabs=[],orderChecks=[];
let _currentUser={id:1},_userRole='',drafts=0,_ultimaRecuperacionVentasCompleta=false,TOKEN='token',rejectOwner=false;
const _ventasPendientes=[],savedOrders=[{id:'order-1'}];let _pedidosPendientes=[];
const document={querySelector:()=>({id:'ped'}),getElementById:()=>({style:{}})};
function guardarUsuarioCache(){}function aplicarPermisosModulos(){}function restorePosDraft(){drafts++;}
function puedeVerModuloUsuario(u,p){return !!u.permisos_modulos[p];}
function pantallaInicialUsuario(){return 'pos';}function go(tab){tabs.push(tab);}
function iniciarPollPedidos(){}function deferDashboard(){}function mostrarBotonActualizarApp(){}
function iniciarNotifPeriodicas(){}function solicitarPermisoNotif(){}function registrarFCMPush(){}function initWebSocket(){}
function recuperarVentasIndexedDB(){return Promise.resolve();}
function leerPedidosPendientesLocal(){orderChecks.push('read');return savedOrders;}
function verificarPropietarioColasVentas(){orderChecks.push('owner');if(rejectOwner)throw Error('owner mismatch');}
"""
    node(harness + section("function aplicarPostLogin(u, opciones)", "function postLogin") + r"""
async function run(){
  aplicarPostLogin({id:1,permisos_modulos:{ped:'ver'}},{conservarVista:true});
  assert.equal(tabs[0],'ped');assert.equal(drafts,0);
  assert.deepEqual(_pedidosPendientes,savedOrders);
  aplicarPostLogin({id:2,permisos_modulos:{pos:'editar'}},{conservarVista:true});
  assert.equal(tabs[1],'pos');assert.equal(drafts,1);
  assert.deepEqual(orderChecks,['read','owner','read','owner']);rejectOwner=true;
  assert.throws(()=>aplicarPostLogin({id:3,permisos_modulos:{ped:'ver'}},{conservarVista:true}));
  assert.equal(tabs.length,2);
}
""")


PED_HARNESS = r"""
const assert=require('node:assert/strict'),fields={},reads=[],rendered=[];
const document={getElementById:id=>fields[id]||=( {style:{},textContent:'',hidden:true})};
let _pedCargaSeq=0,_versionSesion=1,_pedidosCache=[{id:9}],_pedidosPendientes=[],_calPedVisible=true;
function apiLecturaRecuperable(path,options){return new Promise((resolve,reject)=>reads.push({path,options,resolve,reject}));}
function registrarPedidosConocidos(){}function sincronizarPedidosPendientes(){}
function renderPedidos(){rendered.push(_pedidosCache.map(p=>p.id));}
function cargarReservasPedidos(){}function renderCalPed(){}function pedidosVisibles(){return _pedidosCache;}
""" + section("function cargarPedidos(opciones)", "function cargarReservasPedidos()")


def test_orders_error_keeps_existing_data_and_retry_clears_warning_on_success():
    node(PED_HARNESS + r"""
async function run(){
  let load=cargarPedidos();reads[0].reject({status:503});assert.equal(await load,false);
  assert.equal(_pedidosCache[0].id,9);assert.equal(fields['ped-reintentar'].hidden,false);
  assert(fields['ped-datos-estado'].textContent.includes('al d'));
  load=cargarPedidos();assert.equal(fields['ped-reintentar'].hidden,true);
  reads[1].resolve([{id:10,estado:'recibido'}]);assert.equal(await load,true);
  assert.equal(fields['ped-datos-estado'].hidden,true);assert.equal(_pedidosCache[0].id,10);
}
""")


def test_old_orders_response_cannot_replace_newer_data_or_repaint_after_logout():
    node(PED_HARNESS + r"""
async function run(){
  let old=cargarPedidos(),current=cargarPedidos({silenciosa:true});
  assert.equal(reads[1].options.silenciosa,true);
  reads[1].resolve([{id:10}]);await current;reads[0].resolve([{id:99}]);await old;
  assert.deepEqual(rendered,[[10]]);
  old=cargarPedidos();_versionSesion++;reads[2].resolve([{id:88}]);await old;
  assert.deepEqual(rendered,[[10]]);
}
""")


def test_order_form_catalog_is_loaded_only_when_opening_new_order():
    assert "prepararDatosNuevoPedido" not in section("function cargarPagina(p, opts)", "function activarPagina")
    assert "prepararDatosNuevoPedido();" in section("function abrirNuevoPedido()", "function cerrarNuevoPedido()")


def test_post_login_owner_mismatch_restores_login_and_preserves_queued_work():
    harness = r"""
const assert=require('node:assert/strict'),fields={},messages=[],reads=[];
let _versionSesion=1;
const document={getElementById:id=>fields[id]||={style:{display:'none'}}};
function mostrarErrorLogin(message){messages.push(message);}
function apiLecturaRecuperable(){return new Promise((resolve,reject)=>reads.push({resolve,reject}));}
function aplicarPostLogin(){const error=new Error('owner');error.code='PENDING_SALES_OWNER_MISMATCH';throw error;}
"""
    node(harness + section("function postLogin(usuario, opciones)", "function aplicarPermisosModulos") + r"""
async function run(){
  let login=postLogin();reads[0].resolve({id:2});assert.equal(await login,false);
  assert.equal(fields['login-screen'].style.display,'flex');assert.match(messages[0],/cuenta anterior/);
  fields['login-screen'].style.display='none';assert.equal(await postLogin({id:2}),false);
  assert.equal(fields['login-screen'].style.display,'flex');assert.equal(messages.length,2);
  login=postLogin();_versionSesion++;fields['login-screen'].style.display='none';
  reads[1].reject({code:'PENDING_SALES_OWNER_MISMATCH'});await login;
  assert.equal(fields['login-screen'].style.display,'none');assert.equal(messages.length,2);
}
""")


def test_logout_clears_local_business_cache_even_when_deferred_core_is_unavailable():
    cleanup = section("function limpiarClavesSesionCompartida()", "function limpiarSesionConBloqueo")
    for key in ("jacaranda_prods_cache", "jacaranda_pedido_contactos", "jacaranda_tab"):
        assert key in cleanup
    assert "jacaranda_pedidos_pendientes" not in cleanup
    assert "'jacaranda_ventas_pendientes'" in cleanup
    assert "if (!preservarVentasPendientes)" in cleanup


def test_expired_session_cleanup_preserves_pending_orders_and_their_owner():
    harness = r"""
const assert=require('node:assert/strict');
const order={id:'order-1',payload:{idempotency_key:'order-1'}};
const stored=new Map([['jacaranda_pedidos_pendientes',JSON.stringify([order])],['jacaranda_ventas_propietario','1'],
  ['jacaranda_token','token'],['jacaranda_refresh_token','refresh'],['jacaranda_prods_cache','cache']]);
const localStorage={getItem:key=>stored.get(key)||null,setItem:(key,value)=>stored.set(key,value),removeItem:key=>stored.delete(key)};
const window={};let preservarVentasPendientes=true,_fcmRegistroIntentado=true;
let _currentUser={id:1},TOKEN='token',_ventasPendientes=[],_ventasLegacyRevision=[];
const FCM_TOKEN_KEY='fcm';function clearPosDraft(){}
"""
    code = section("var VENTAS_QUEUE_OWNER_KEY", "function leerVentasPendientesLocal()")
    code += section("function limpiarClavesSesionCompartida()", "function limpiarSesionConBloqueo")
    code += Path("docs/js/jacaranda-core.js").read_text(encoding="utf-8")
    node(harness + code + r"""
async function run(){
  limpiarClavesSesionCompartida();await window.JacarandaCore.clearSensitiveCachesPreservingSales();
  assert.deepEqual(leerPedidosPendientesLocal(),[order]);assert.equal(stored.has('jacaranda_token'),false);
  assert.equal(stored.has('jacaranda_prods_cache'),false);
  actualizarPropietarioColasVentas();assert.equal(leerPropietarioColasVentas(),'1');
  const token=id=>'header.'+Buffer.from(JSON.stringify({sub:id})).toString('base64url')+'.signature';
  assert.throws(()=>verificarPropietarioColasVentas(token(2)),{code:'PENDING_SALES_OWNER_MISMATCH'});
  verificarPropietarioColasVentas(token(1));
  stored.set('jacaranda_pedidos_pendientes','[]');actualizarPropietarioColasVentas();
  assert.equal(leerPropietarioColasVentas(),'');
}
""")
    logout = section("function cerrarSesion(opciones)", "async function confirmarCerrarSesion()")
    assert "if (leerPedidosPendientesLocal().length) preservarVentasPendientes = true" in logout
    assert "ventasDetectadas || pedidosDetectados" in logout


def test_manual_logout_warns_before_closing_with_pending_orders():
    harness = r"""
const assert=require('node:assert/strict'),messages=[];
function leerPedidosPendientesLocal(){return [{id:'order-1'}];}
function confirmarAccion(options){messages.push(options);return Promise.resolve(true);}
function recuperarVentasIndexedDB(){throw Error('Logout continued despite pending orders');}
"""
    node(harness + section("async function confirmarCerrarSesion()", "// ─── Gestión de usuarios") + r"""
async function run(){await confirmarCerrarSesion();assert.equal(messages.length,1);
  assert.equal(messages[0].title,'Hay pedidos pendientes');}
""")


ORDER_SYNC_HARNESS = r"""
const assert=require('node:assert/strict'),requests=[];
const original={id:'order-1',payload:{idempotency_key:'order-1'}};
let _versionSesion=1,TOKEN='token',_pedidosPendientes=[original],_calPedVisible=false;
let stored=JSON.stringify(_pedidosPendientes);
const localStorage={getItem:()=>stored,setItem:(key,value)=>stored=value};
function asegurarPropietarioColasVentas(){return true;}function actualizarPropietarioColasVentas(){}
function verificarPropietarioColasVentas(){}
function exigirSesionColasVigente(version,token){if(version!==_versionSesion||!TOKEN||!token)throw Error('Session changed');}
function conBloqueoColasVentas(task){return Promise.resolve().then(()=>task(()=>true));}
function api(){return new Promise((resolve,reject)=>requests.push({resolve,reject}));}
function toast(){}function renderPedidos(){}function cargarPedidos(){}
async function flush(){for(let i=0;i<10;i++)await Promise.resolve();}
"""


def test_order_sync_cannot_clear_pending_orders_after_session_expiry():
    code = section("function leerPedidosPendientesLocal()", "function hayColasVentasConPropietario()")
    code += section("function guardarPedidosPendientes()", "function guardarPedidoPendiente(pedido, versionSesion, tokenSesion)")
    code += section("function sincronizarPedidosPendientes(silencioso)", "function guardarPed()")
    node(ORDER_SYNC_HARNESS + code + r"""
async function run(){
  const second={id:'order-2',payload:{idempotency_key:'order-2'}};
  _pedidosPendientes.push(second);guardarPedidosPendientes();const before=stored;
  const sync=sincronizarPedidosPendientes(true);await flush();
  _versionSesion++;TOKEN='';_pedidosPendientes=[];requests[0].reject(new Error('401'));
  assert.equal(await sync,false);assert.equal(stored,before);assert.equal(requests.length,1);
}
""")


def test_order_sync_preserves_orders_added_while_a_request_is_pending():
    code = section("function leerPedidosPendientesLocal()", "function hayColasVentasConPropietario()")
    code += section("function guardarPedidosPendientes()", "function guardarPedidoPendiente(pedido, versionSesion, tokenSesion)")
    code += section("function sincronizarPedidosPendientes(silencioso)", "function guardarPed()")
    node(ORDER_SYNC_HARNESS + code + r"""
async function run(){
  const sync=sincronizarPedidosPendientes(true);await flush();
  const added={id:'order-2',payload:{idempotency_key:'order-2'}};
  stored=JSON.stringify([original,added]);requests[0].resolve({id:1});await sync;
  assert.deepEqual(_pedidosPendientes,[added]);assert.deepEqual(JSON.parse(stored),[added]);
}
""")


def test_pending_order_writes_share_the_login_lock_and_reject_an_old_account_tab():
    harness = r"""
const assert=require('node:assert/strict');
let _versionSesion=1,TOKEN='old-token',_pedidosPendientes=[],tail=Promise.resolve();
const stored=new Map([['jacaranda_token',TOKEN]]);
const localStorage={getItem:key=>stored.get(key)||null,setItem:(key,value)=>stored.set(key,value)};
function conBloqueoColasVentas(task){const job=tail.then(()=>task(()=>true));tail=job.catch(()=>{});return job;}
function exigirSesionColasVigente(version,token){
  if(version!==_versionSesion||token!==TOKEN||stored.get('jacaranda_token')!==TOKEN)throw Error('Session changed');}
function verificarPropietarioColasVentas(){}function asegurarPropietarioColasVentas(){return true;}
function actualizarPropietarioColasVentas(){}function nuevaClaveIdempotencia(){throw Error('Key already supplied');}
async function flush(){for(let i=0;i<10;i++)await Promise.resolve();}
"""
    code = section("function leerPedidosPendientesLocal()", "function hayColasVentasConPropietario()")
    code += section("function guardarPedidosPendientes()", "function pedidosPendientesComoCache()")
    node(harness + code + r"""
async function run(){
  let release;const held=conBloqueoColasVentas(()=>new Promise(resolve=>release=resolve));await flush();
  const pending=guardarPedidoPendiente({idempotency_key:'late'},1,'old-token');
  await flush();assert.equal(stored.has('jacaranda_pedidos_pendientes'),false);
  stored.set('jacaranda_token','new-token');release();await held;
  await assert.rejects(pending,/Session changed/);assert.equal(stored.has('jacaranda_pedidos_pendientes'),false);
  stored.set('jacaranda_token','old-token');
  stored.set('jacaranda_pedidos_pendientes',JSON.stringify([{id:'existing',payload:{idempotency_key:'existing'}}]));
  await guardarPedidoPendiente({idempotency_key:'mine'},1,'old-token');
  await guardarPedidoPendiente({idempotency_key:'mine'},1,'old-token');
  assert.deepEqual(leerPedidosPendientesLocal().map(p=>p.id),['existing','mine']);
}
""")


def test_sensitive_cache_cleanup_finishes_before_releasing_the_session_queue_lock():
    cleanup = section("function limpiarSesionConBloqueo(exigirBloqueoVigente)", "var limpiezaSesionCompartida =")
    after = section("limpiezaSesionCompartida.then(function(limpiada)", "if (navigator.serviceWorker && navigator.serviceWorker.controller)")
    assert "if (leerPedidosPendientesLocal().length) preservarVentasPendientes = true" in cleanup
    assert "return Promise.resolve(limpiezaCore()).then(function() { return true; })" in cleanup
    assert "clearSensitiveCaches" not in after
    for start, end in (
        ("function guardarPedidoPendiente(pedido, versionSesion, tokenSesion)", "function pedidosPendientesComoCache()"),
        ("function sincronizarPedidosPendientes(silencioso)", "function guardarPed()"),
        ("function borrarPedidoLocal(localId)", "function "),
    ):
        if end == "function ":
            offset = HTML.index(start)
            code = HTML[offset:HTML.index(end, offset + len(start))]
        else:
            code = section(start, end)
        assert "conBloqueoColasVentas(function(exigirBloqueoVigente)" in code
        assert "exigirSesionColasVigente(" in code


def test_mobile_refresh_only_reports_success_after_actual_reads_complete():
    harness = r"""
const assert=require('node:assert/strict'),handlers={},loads=[],messages=[];
let _versionSesion=1;
const window={scrollY:0},localStorage={getItem:()=> 'pos'},document={addEventListener:(n,fn)=>handlers[n]=fn};
function moduloDesactivado(){return false;}function paginaDesactivada(){return false;}
function activarPagina(p){return p;}function apiCacheInvalidate(){}
function setTimeout(fn){queueMicrotask(fn);}function programarCargaPagina(){return ()=>{};}
function cargarPagina(){return new Promise((resolve,reject)=>loads.push({resolve,reject}));}
function reportarErrorPagina(){}function toast(message){messages.push(message);}
function pull(){handlers.touchstart({target:{closest:()=>null},touches:[{clientY:100,clientX:10}]});
  handlers.touchend({changedTouches:[{clientY:240,clientX:10}]});}
async function flush(){for(let i=0;i<15;i++)await Promise.resolve();}
"""
    code = section("function go(p, opts)", "function activarConTeclado")
    code += section("var _pullStart = 0;", "// Auto-hide desktop nav")
    node(harness + code + r"""
async function run(){
  pull();await flush();assert.equal(messages.length,0);loads[0].resolve([false,true]);await flush();assert.equal(messages.length,0);
  pull();await flush();loads[1].resolve(true);await flush();assert.deepEqual(messages,['Actualizado']);
  pull();await flush();_versionSesion++;loads[2].resolve(true);await flush();assert.equal(messages.length,1);
  pull();await flush();loads[3].reject(new Error('temporary'));await flush();assert.equal(messages.length,1);
}
""")
