"""Controles de revision, sesion y reintento del importador real."""

from pathlib import Path
import shutil
import subprocess

import pytest

JS = Path("docs/js/egresos-import.js").read_text(encoding="utf-8")
HTML = Path("docs/index.html").read_text(encoding="utf-8")

HARNESS = r"""
const assert=require('node:assert/strict'),fields={},requests=[],messages=[];
let _versionSesion=1,approvals=0,reloads=0;
const window={_permisos:{egresos:'editar'}};
function field(id){return fields[id] ||= {value:'',checked:false,disabled:false,hidden:false,
  textContent:'',innerHTML:'',classList:{add(){},remove(){}},getAttribute(){return null;}};}
const document={getElementById:id=>id==='eg-import-todas'?(fields[id]||null):field(id),
  querySelectorAll:selector=>selector.includes('#eg-import-file')?[field('eg-import-file')]:[]};
function escHtml(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;');}
function fmt(n){return Number(n).toFixed(2);}
function toast(m){messages.push(m);}
function confirmarAccion(){approvals++;return Promise.resolve(true);}
function api(method,path,body){return new Promise((resolve,reject)=>requests.push({method,path,body,resolve,reject}));}
function cargarEgresos(){reloads++;}function cargarResumenEgresosApi(){reloads++;}
function cargarResguardo(){reloads++;}function cargarProveedoresEgresos(){reloads++;}function cargarGastos(){reloads++;}
function vista(){return {token:'signed-preview',archivo:'gastos.xlsx',hoja:'Septiembre',faltantes:[],filas:[
  {fila:2,estado:'lista',datos:{proveedor:'Proveedor',fecha:'2026-09-01',monto:'10.25',metodo_pago:'efectivo'}},
  {fila:3,estado:'duplicado',datos:{proveedor:'Proveedor',fecha:'2026-09-01',monto:'10.25',metodo_pago:'efectivo'}},
  {fila:4,estado:'error',datos:{},original:{proveedor:'<img src=x onerror=alert(1)>'},errores:['<error>']}
]};}
function estado(){return {version:1,archivo:{name:'gastos.xlsx',size:1024},vista:vista(),seleccion:{2:true},pendiente:null,ocupado:false};}
"""


def node(code):
    executable = shutil.which("node")
    if not executable:
        pytest.skip("Node required")
    result = subprocess.run([executable, "-e", HARNESS + JS + code], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_selection_defaults_to_ready_rows_and_uses_integer_cents():
    node(r"""
_egImport=estado();
assert.deepEqual(seleccionExcelEgresos(),{filas:[2],incluir_duplicados:[],centavos:1025});
cambiarSeleccionExcelEgresos(4,true);assert.deepEqual(seleccionExcelEgresos().filas,[2]);
cambiarSeleccionExcelEgresos(3,true);assert.deepEqual(seleccionExcelEgresos(),{filas:[2,3],incluir_duplicados:[3],centavos:2050});
seleccionarFilasExcelEgresos(false);assert.deepEqual(seleccionExcelEgresos().filas,[3]);
seleccionarFilasExcelEgresos(true);assert.deepEqual(seleccionExcelEgresos().filas,[2,3]);
renderVistaExcelEgresos(_egImport.vista);
assert(!field('eg-import-tabla').innerHTML.includes('<img'));
assert(field('eg-import-tabla').innerHTML.includes('&lt;img'));
assert(field('eg-import-estado').textContent.includes('Sin guardar'));
""")


def test_double_click_unknown_response_keeps_the_exact_confirmation_body():
    node(r"""
(async()=>{
  _egImport=estado();let pending=confirmarExcelEgresos();confirmarExcelEgresos();await Promise.resolve();
  assert.equal(requests.length,1);assert.equal(approvals,1);
  const body=requests[0].body;
  requests[0].reject(Object.assign(new Error('Sin respuesta'),{status:503}));await pending;
  assert.equal(_egImport.pendiente,body);
  assert.equal(field('eg-import-file').disabled,true);
  invalidarVistaExcelEgresos();cambiarSeleccionExcelEgresos(3,true);
  assert.deepEqual(seleccionExcelEgresos().filas,[2]);
  assert(field('eg-import-confirmar').textContent.includes('Reintentar'));
  pending=confirmarExcelEgresos();assert.equal(requests[1].body,body);assert.equal(approvals,1);
  requests[1].resolve({importados:0,monto_importado:'0.00',ya_registrados:1,anulados:0});await pending;
  assert.equal(_egImport.pendiente,null);assert.equal(_egImport.vista,null);
  assert.equal(reloads,5);assert.equal(field('eg-import-file').disabled,false);
  assert(field('eg-import-estado').textContent.includes('1 ya registrados'));
})();
""")


def test_definitive_error_can_be_revised_and_cancel_never_posts():
    node(r"""
(async()=>{
  _egImport=estado();confirmarAccion=()=>Promise.resolve(false);
  await confirmarExcelEgresos();assert.equal(requests.length,0);assert.equal(_egImport.ocupado,false);
  confirmarAccion=()=>Promise.resolve(true);
  const pending=confirmarExcelEgresos();await Promise.resolve();
  requests[0].reject(Object.assign(new Error('Duplicado nuevo; actualiza'),{status:409}));await pending;
  assert.equal(_egImport.pendiente,null);assert.equal(field('eg-import-file').disabled,false);
  invalidarVistaExcelEgresos();assert.equal(_egImport.vista,null);
  assert.equal(field('eg-import-confirmar').disabled,true);
})();
""")


def test_changed_session_cannot_confirm_or_render_an_old_result():
    node(r"""
(async()=>{
  _egImport=estado();let allow;
  confirmarAccion=()=>new Promise(resolve=>allow=resolve);
  let pending=confirmarExcelEgresos();_versionSesion++;cerrarImportacionEgresos(true);allow(true);await pending;
  assert.equal(requests.length,0);assert.equal(_egImport,null);
  _versionSesion=1;_egImport=estado();confirmarAccion=()=>Promise.resolve(true);
  pending=confirmarExcelEgresos();await Promise.resolve();
  _versionSesion++;cerrarImportacionEgresos(true);
  requests[0].resolve({importados:1,monto_importado:'10.25',ya_registrados:0});await pending;
  assert.equal(reloads,0);assert.equal(field('eg-import-estado').textContent,'');
})();
""")


def test_upload_ignores_old_session_even_if_it_changes_during_json_read():
    node(r"""
(async()=>{
  _egImport=estado();field('eg-import-config').hidden=true;
  let read;
  const TOKEN='synthetic',API_URL='https://example.invalid';
  globalThis.TOKEN=TOKEN;globalThis.API_URL=API_URL;
  globalThis.FormData=class{append(){}};
  globalThis.fetch=async()=>({ok:true});
  globalThis.leerRespuestaJson=()=>new Promise(resolve=>read=resolve);
  const pending=leerExcelEgresos(true);await Promise.resolve();
  _versionSesion++;cerrarImportacionEgresos(true);
  read({filas:[],hojas:[]});await pending;
  assert.equal(_egImport,null);assert.equal(field('eg-import-estado').textContent,'');
})();
""")


def test_new_file_resets_displayed_date_format_to_the_one_actually_parsed():
    node(r"""
(async()=>{
  _egImport=estado();field('eg-import-config').hidden=true;
  field('eg-import-formato-fecha').value='mes_dia_anio';
  globalThis.TOKEN='synthetic';globalThis.API_URL='https://example.invalid';
  globalThis.FormData=class{append(){}};
  globalThis.fetch=async()=>({ok:true});
  globalThis.leerRespuestaJson=async()=>({...vista(),hojas:['Septiembre'],fila_encabezado:1,
    columnas:{fecha:1,proveedor:2,monto:3,metodo_pago:4},opciones_columnas:[]});
  await leerExcelEgresos(true);
  assert.equal(field('eg-import-formato-fecha').value,'dia_mes_anio');
  assert.equal(_egImport.ocupado,false);assert(_egImport.vista);
})();
""")


def test_preview_refreshes_access_token_once_without_losing_the_workbook():
    node(r"""
(async()=>{
  _egImport=estado();field('eg-import-config').hidden=true;
  const calls=[];let refreshed=0,expired=0;
  globalThis.TOKEN='expired';globalThis.REFRESH_TOKEN='refresh-session';globalThis.API_URL='https://example.invalid';
  globalThis.FormData=class{append(){}};
  globalThis.fetch=async(url,options)=>{calls.push(options);return {ok:calls.length>1,status:calls.length>1?200:401};};
  globalThis.refreshAccessToken=async()=>{refreshed++;globalThis.TOKEN='renewed';};
  globalThis.expirarSesion=()=>{expired++;};
  globalThis.leerRespuestaJson=async()=>({...vista(),hojas:['Septiembre'],fila_encabezado:1,
    columnas:{fecha:1,proveedor:2,monto:3,metodo_pago:4},opciones_columnas:[]});
  const workbook=_egImport.archivo;
  await leerExcelEgresos(true);
  assert.equal(refreshed,1);assert.equal(expired,0);assert.equal(calls.length,2);
  assert.equal(calls[0].body,calls[1].body);
  assert.equal(calls[0].headers.Authorization,'Bearer expired');
  assert.equal(calls[1].headers.Authorization,'Bearer renewed');
  assert.equal(_egImport.archivo,workbook);assert(_egImport.vista);
})();
""")


def test_preview_does_not_retry_after_session_changes_during_refresh():
    node(r"""
(async()=>{
  _egImport=estado();field('eg-import-config').hidden=true;
  let calls=0;
  globalThis.TOKEN='expired';globalThis.REFRESH_TOKEN='refresh-session';globalThis.API_URL='https://example.invalid';
  globalThis.FormData=class{append(){}};
  globalThis.fetch=async()=>{calls++;return {ok:false,status:401};};
  globalThis.refreshAccessToken=async()=>{_versionSesion++;cerrarImportacionEgresos(true);};
  await leerExcelEgresos(true);
  assert.equal(calls,1);assert.equal(_egImport,null);
  assert.equal(field('eg-import-estado').textContent,'');
})();
""")


def test_preview_stops_after_second_unauthorized_response():
    node(r"""
(async()=>{
  _egImport=estado();field('eg-import-config').hidden=true;
  let calls=0,refreshed=0,expired=0;
  globalThis.TOKEN='expired';globalThis.REFRESH_TOKEN='refresh-session';globalThis.API_URL='https://example.invalid';
  globalThis.FormData=class{append(){}};
  globalThis.fetch=async()=>{calls++;return {ok:false,status:401};};
  globalThis.refreshAccessToken=async()=>{refreshed++;};
  globalThis.leerRespuestaJson=async()=>({detail:'Sesion expirada'});
  globalThis.expirarSesion=()=>{expired++;};
  await leerExcelEgresos(true);
  assert.equal(calls,2);assert.equal(refreshed,1);assert.equal(expired,1);
  assert.equal(_egImport.ocupado,false);assert.equal(_egImport.vista,null);
})();
""")


def test_import_script_and_worker_share_build_and_all_close_paths_clean_up():
    build = HTML.split("var APP_BUILD = '", 1)[1].split("'", 1)[0]
    asset = "js/egresos-import.js?v=" + build
    assert f'<script defer src="{asset}"></script>' in HTML
    assert "'./" + asset + "'" in Path("docs/sw.js").read_text()
    assert "#eg-importar-btn[hidden]{display:none}" in HTML
    assert "hidden = permisos.egresos !== 'editar'" in HTML
    assert "cerrarImportacionEgresos(true)" in HTML
    assert HTML.count("cerrarImportacionEgresos();") >= 3
    assert "localStorage" not in JS and "sessionStorage" not in JS
    assert "timeoutMs:60000" in JS
