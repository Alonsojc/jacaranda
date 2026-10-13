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
const assert=require('node:assert/strict'),tabs=[];
let _currentUser={id:1},_userRole='',drafts=0,_ultimaRecuperacionVentasCompleta=false;
const _ventasPendientes=[],_pedidosPendientes=[];
const document={querySelector:()=>({id:'ped'}),getElementById:()=>({style:{}})};
function guardarUsuarioCache(){}function aplicarPermisosModulos(){}function restorePosDraft(){drafts++;}
function puedeVerModuloUsuario(u,p){return !!u.permisos_modulos[p];}
function pantallaInicialUsuario(){return 'pos';}function go(tab){tabs.push(tab);}
function iniciarPollPedidos(){}function deferDashboard(){}function mostrarBotonActualizarApp(){}
function iniciarNotifPeriodicas(){}function solicitarPermisoNotif(){}function registrarFCMPush(){}function initWebSocket(){}
function recuperarVentasIndexedDB(){return Promise.resolve();}
"""
    node(harness + section("function aplicarPostLogin(u, opciones)", "function postLogin") + r"""
async function run(){
  aplicarPostLogin({id:1,permisos_modulos:{ped:'ver'}},{conservarVista:true});
  assert.equal(tabs[0],'ped');assert.equal(drafts,0);
  aplicarPostLogin({id:2,permisos_modulos:{pos:'editar'}},{conservarVista:true});
  assert.equal(tabs[1],'pos');assert.equal(drafts,1);
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


def test_logout_clears_local_business_cache_even_when_deferred_core_is_unavailable():
    cleanup = section("function limpiarClavesSesionCompartida()", "function limpiarSesionConBloqueo")
    for key in ("jacaranda_prods_cache", "jacaranda_pedidos_pendientes", "jacaranda_pedido_contactos", "jacaranda_tab"):
        assert key in cleanup
    assert "'jacaranda_ventas_pendientes'" in cleanup
    assert "if (!preservarVentasPendientes)" in cleanup


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
