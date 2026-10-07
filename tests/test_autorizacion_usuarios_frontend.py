"""Exercise approval and role forms without browsers or operational accounts."""

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
    result = subprocess.run([executable, "-e", script], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


HARNESS = r"""
const assert=require('node:assert/strict'), fields={}, reads=[], writes=[], messages=[], navigation=[];
const document={getElementById:id=>fields[id] ||= {
  value:'', textContent:'', innerHTML:'', style:{}, disabled:false, checked:false, type:'password',
  checkValidity(){return true;}, focus(){},
  classList:{on:false, add(){this.on=true;},remove(){this.on=false;},contains(){return this.on;}}
}};
let _versionSesion=1, _currentUser={id:1,rol:'administrador'}, _userRole='administrador';
let response=()=>Promise.resolve({id:2,rol:'gerente',permisos_modulos:{inv:'editar'}});
function api(...args){writes.push(args);return response();}
function apiLecturaRecuperable(path){return new Promise((resolve,reject)=>reads.push({path,resolve,reject}));}
function esAdminActual(){return _currentUser.rol==='administrador';}
function escHtml(v){return String(v).replace(/</g,'&lt;');}
function jsArg(v){return JSON.stringify(v);}
function actionBtn(label,icon,onclick){return '<button>'+label+'</button>';}
function toast(...args){messages.push(args);}
function guardarUsuarioCache(){}
function aplicarPermisosModulos(){}
function moduloInicioUsuario(){return 'pos';}
function go(page){navigation.push(page);}
async function flush(){for(let i=0;i<12;i++)await Promise.resolve();}
"""

APPROVAL = section("var _adminAuthPending = null", "function refreshAccessToken()")
USERS = section("var _claveAuthEstado = null", "function editarPermisos(")


@pytest.mark.parametrize("configured", [True, False])
def test_approval_label_matches_server_mode_and_clears_secrets(configured):
    node(HARNESS + APPROVAL + r"""
(async()=>{
  const pending=pedirPasswordAdmin('editar ticket',true);
  assert.equal(fields['maa-autorizar'].disabled,true);
  confirmarAdminAuth();assert.notEqual(_adminAuthPending,null);
  reads[0].resolve({configurada:CONFIGURED});await flush();
  assert.equal(fields['maa-label'].textContent,CONFIGURED?'Clave de autorizaci\u00f3n':'Contrase\u00f1a de administrador');
  fields['maa-pass'].value='approval-test-only';fields['maa-motivo'].value='Correccion autorizada';
  confirmarAdminAuth();const headers=await pending;
  assert.equal(headers['X-Admin-Override-Password'],'approval-test-only');
  assert.equal(headers['X-Admin-Override-Motivo'],'Correccion%20autorizada');
  assert.equal(fields['maa-pass'].value,'');assert.equal(fields['maa-motivo'].value,'');
  assert.equal(fields['modal-admin-auth'].classList.on,false);
})();
""".replace("CONFIGURED", "true" if configured else "false"))


def test_cancelled_or_failed_approval_cannot_reopen_from_late_read():
    node(HARNESS + APPROVAL + r"""
(async()=>{
  let pending=pedirPasswordAdmin('editar ticket',true);pending.catch(()=>{});
  fields['maa-pass'].value='temporary-test';cancelarAdminAuth();
  await assert.rejects(pending);reads[0].resolve({configurada:true});await flush();
  assert.equal(fields['modal-admin-auth'].classList.on,false);assert.equal(fields['maa-pass'].value,'');
  pending=pedirPasswordAdmin('cancelar corte',true);pending.catch(()=>{});
  reads[1].reject(new Error('No se pudo cargar'));await assert.rejects(pending);
  assert.equal(fields['modal-admin-auth'].classList.on,false);
})();
""")


def test_approval_requires_motive_and_guards_session_change():
    node(HARNESS + APPROVAL + r"""
(async()=>{
  const pending=pedirPasswordAdmin('editar corte',true);pending.catch(()=>{});
  reads[0].resolve({configurada:true});await flush();
  fields['maa-pass'].value='approval-test-only';confirmarAdminAuth();
  assert.notEqual(_adminAuthPending,null);
  fields['maa-motivo'].value='Prueba';_versionSesion++;confirmarAdminAuth();
  await assert.rejects(pending);assert.equal(fields['maa-pass'].value,'');
})();
""")


def test_key_form_checks_confirmation_and_never_retains_submitted_credentials():
    node(HARNESS + USERS + r"""
(async()=>{
  let opening=abrirClaveAutorizacion();reads[0].resolve({configurada:false});await opening;
  fields['mca-actual'].value='login-test-only';fields['mca-nueva'].value='new-test-only';
  fields['mca-confirmacion'].value='does-not-match';await guardarClaveAutorizacion();assert.equal(writes.length,0);
  fields['mca-confirmacion'].value='new-test-only';
  let finish;response=()=>new Promise(resolve=>finish=resolve);
  let saving=guardarClaveAutorizacion();
  assert.equal(writes[0][0],'PUT');assert.equal(writes[0][1],'/auth/clave-autorizacion');
  assert.equal(writes[0][2].nueva_clave,'new-test-only');assert.equal(writes[0][5],1);
  for(const id of ['mca-actual','mca-nueva','mca-confirmacion'])assert.equal(fields[id].value,'');
  await guardarClaveAutorizacion();assert.equal(writes.length,1);
  cerrarClaveAutorizacion();assert.equal(fields['modal-clave-autorizacion'].classList.on,true);
  finish({configurada:true});await saving;
  assert.equal(fields['modal-clave-autorizacion'].classList.on,false);
})();
""")


def test_key_form_load_retry_and_failed_write_does_not_retry_automatically():
    node(HARNESS + USERS + r"""
(async()=>{
  let opening=abrirClaveAutorizacion();reads[0].reject(new Error('Servidor no disponible'));await opening;
  assert.equal(fields['mca-guardar'].disabled,true);assert.equal(fields['mca-reintentar'].style.display,'');
  opening=abrirClaveAutorizacion();reads[1].resolve({configurada:true});await opening;
  for(const [id,value] of [['mca-actual','login-test-only'],['mca-nueva','new-test-only'],['mca-confirmacion','new-test-only']])fields[id].value=value;
  response=()=>Promise.reject(new Error('Contrase\u00f1a actual incorrecta'));
  await guardarClaveAutorizacion();assert.equal(writes.length,1);
  assert.equal(fields['mca-actual'].value,'');assert.equal(fields['mca-guardar'].disabled,false);
})();
""")


def test_user_editor_sends_role_without_password_and_resets_permissions_by_choice():
    node(HARNESS + USERS + r"""
(async()=>{
  let loading=cargarUsuarios();reads[0].resolve([{id:2,nombre:'<Prueba>',email:'test@example.com',rol:'cajero',activo:true}]);await loading;
  assert(fields['usuarios-list'].innerHTML.includes('&lt;Prueba>'));
  assert(fields['usuarios-list'].innerHTML.includes('Editar'));
  editarUsuario(2);assert.equal(fields['mu-pass-wrap'].style.display,'none');
  fields['mu-rol'].value='gerente';actualizarOpcionesRol();assert.equal(fields['mu-permisos-wrap'].style.display,'');
  await guardarNuevoUsuario();assert.equal(writes[0][0],'PUT');assert.equal(writes[0][1],'/auth/usuarios/2');
  assert.equal(writes[0][2].rol,'gerente');assert.equal(writes[0][2].restablecer_permisos,true);
  assert(!('password' in writes[0][2]));assert.equal(fields['modal-usuario'].classList.on,false);
})();
""")


def test_self_role_change_refreshes_ui_and_no_longer_requests_admin_list():
    node(HARNESS + USERS + r"""
(async()=>{
  _usuariosActuales=[{id:1,nombre:'Prueba',email:'test@example.com',rol:'administrador'}];
  editarUsuario(1);fields['mu-rol'].value='cajero';response=()=>Promise.resolve({id:1,rol:'cajero',permisos_modulos:{pos:'editar'}});
  await guardarNuevoUsuario();assert.equal(_currentUser.rol,'cajero');assert.deepEqual(navigation,['pos']);
  assert.equal(reads.length,0);
})();
""")


def test_user_editor_ignores_late_response_after_session_change():
    node(HARNESS + USERS + r"""
(async()=>{
  _usuariosActuales=[{id:2,nombre:'Prueba',email:'test@example.com',rol:'cajero'}];
  editarUsuario(2);fields['mu-rol'].value='gerente';
  let finish;response=()=>new Promise(resolve=>finish=resolve);let saving=guardarNuevoUsuario();
  _versionSesion++;cerrarUsuario();finish({id:2,rol:'gerente'});await saving;
  assert.equal(messages.length,0);assert.equal(reads.length,0);
})();
""")


def test_login_form_has_password_manager_annotations_and_native_submission():
    class Tags(HTMLParser):
        elements = {}

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if attrs.get("id"):
                self.elements[attrs["id"]] = (tag, attrs)

    tags = Tags()
    tags.feed(HTML)
    assert tags.elements["login-form"][0] == "form"
    assert "event.preventDefault();hacerLogin()" == tags.elements["login-form"][1]["onsubmit"]
    assert tags.elements["login-email"][1]["autocomplete"] == "username"
    assert tags.elements["login-pass"][1]["autocomplete"] == "current-password"
    assert tags.elements["login-email"][1]["name"] == "username"
    assert tags.elements["login-pass"][1]["name"] == "password"
    assert tags.elements["login-submit"][1]["type"] == "submit"
    assert "onclick" not in tags.elements["login-submit"][1]
    assert "onkeydown" not in tags.elements["login-pass"][1]


def test_login_has_no_duplicate_submissions_and_reenables_after_error():
    node(HARNESS + r"""
let _loginEnCurso=false, API_URL='local-test', attempts=0, finish, fail;
function esArchivoLocal(){return false;}
function login(){attempts++;return new Promise((resolve,reject)=>{finish=resolve;fail=reject;});}
function mostrarBotonActualizarApp(){}
function setConnected(){}
function postLogin(){}
""" + section("function hacerLogin()", "function guardarUsuarioCache(") + r"""
(async()=>{
  document.getElementById('login-email').value='test@example.com';document.getElementById('login-pass').value='login-test-only';
  const saving=hacerLogin();hacerLogin();assert.equal(attempts,1);assert.equal(fields['login-submit'].disabled,true);
  fail(new Error('Login failed'));await saving;assert.equal(fields['login-submit'].disabled,false);
  const next=hacerLogin();assert.equal(attempts,2);finish();await next;
  assert.equal(fields['login-screen'].style.display,'none');assert.equal(fields['login-submit'].disabled,false);
})();
""")
