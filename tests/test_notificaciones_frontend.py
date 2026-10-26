"""Dismiss the actual notification UI with synthetic alerts and local storage."""

import shutil
import subprocess
from pathlib import Path

import pytest


HTML = Path("docs/index.html").read_text(encoding="utf-8")
START = HTML.index("var _notifCache = [];")
SOURCE = HTML[START:HTML.index("function setPushStatus", START)]
ESC_START = HTML.index("function escHtml(v)")
ESCAPE = HTML[ESC_START:HTML.index("function jsArg", ESC_START)]
HARNESS = r"""
const assert = require('node:assert/strict');
const fields = {}, saved = new Map(), pushes = [], errors = [], reads = [];
const window = {_permisos:{dash:'ver'}};
const document = {
  getElementById(id) { return fields[id] ||= {
    textContent:'',innerHTML:'',style:{},disabled:false,
    focus(){this.focused=true;},classList:{toggle(){},contains(){return false;}}
  }; },
  querySelectorAll(){return [];}
};
let API_URL='https://synthetic.test',_currentUser={id:1},TOKEN='test',_versionSesion=1;
let storageFails=false;
const localStorage={
  getItem(key){if(storageFails)throw new Error('blocked');return saved.get(key)||null;},
  setItem(key,value){if(storageFails)throw new Error('quota');saved.set(key,value);}
};
function toast(...args){errors.push(args);}
function enviarNotifLocal(...args){pushes.push(args);}
function fechaHoyISO(){return '2026-10-25';}
function dashGet(){throw new Error('Panel must not replay the dashboard cache');}
function api(method,path,body,critical,unused,version,options){
  return new Promise((resolve,reject)=>reads.push({method,path,version,options,resolve,reject}));
}
function stock(id=1,qty=0,name='Producto de prueba',tipo='producto') {
  return {id,nombre:name,tipo,stock_actual:qty,stock_minimo:2,unidad:'pz',severidad:qty<=0?'critica':'alta'};
}
function data(rows=[stock()]) {
  return {stock_bajo:rows,pedidos_pendientes:[],productos_sin_receta:[],productos_sin_costo:[],
    recetas_sin_ingredientes:[],caducidades:[],merma_hoy:{total_movimientos:0}};
}
function visible(){return _notifCache.filter(notificacionVisible);}
function badge(){return document.getElementById('notif-badge');}
function reload(){_notifStorageKey=null;_notifDescartadas={};_notifCache=[];}
"""


def node(script):
    executable = shutil.which("node")
    if not executable:
        pytest.skip("Node required")
    result = subprocess.run(
        [executable, "-e", HARNESS + ESCAPE + SOURCE + script],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr


def test_dismiss_one_persists_after_poll_and_reload_without_business_writes():
    node(r"""
const original=data([stock(),stock(2)]), untouched=JSON.stringify(original);
actualizarNotificaciones(original,false);
const key=claveNotificacion(_notifCache[0]);descartarNotificacion(key);
assert.equal(visible().length,1);assert.equal(badge().textContent,1);
assert.equal(document.getElementById('notif-restaurar').textContent,'Restaurar (1)');
actualizarNotificaciones(original,true);assert.equal(visible().length,1);assert.equal(pushes.length,0);
reload();actualizarNotificaciones(original,false);assert.equal(visible().length,1);
assert.equal(JSON.stringify(original),untouched);assert.equal(reads.length,0);
descartarNotificacion('stale-or-unknown');assert.equal(visible().length,1);
""")


def test_bulk_dismiss_and_restore_are_reversible_and_update_badge():
    node(r"""
actualizarNotificaciones(data([stock(),stock(2)]),false);
descartarTodasNotificaciones();assert.equal(visible().length,0);assert.equal(badge().style.display,'none');
assert(document.getElementById('notif-descartar-todas').disabled);
assert(!document.getElementById('notif-restaurar').disabled);
assert(document.getElementById('notif-list').innerHTML.includes('No hay avisos nuevos'));
actualizarNotificaciones(data([stock(),stock(2)]),true);assert.equal(pushes.length,0);
restaurarNotificaciones();assert.equal(visible().length,2);assert.equal(badge().textContent,2);
assert(document.getElementById('notif-restaurar').disabled);assert.equal(pushes.length,0);
assert.equal(saved.get(_notifStorageKey),'[]');assert.equal(reads.length,0);
""")


def test_changed_alert_and_resolved_then_recurring_alert_reappear():
    node(r"""
actualizarNotificaciones(data(),false);descartarTodasNotificaciones();
actualizarNotificaciones(data([stock(1,-1)]),true);
assert.equal(visible().length,1);assert.equal(pushes.length,1);
assert.equal(Object.keys(_notifDescartadas).length,0);
descartarTodasNotificaciones();actualizarNotificaciones(data([]),true);
assert.equal(Object.keys(_notifDescartadas).length,0);
assert(document.getElementById('notif-list').innerHTML.includes('Sin alertas activas'));
actualizarNotificaciones(data([stock(1,-1)]),true);
assert.equal(visible().length,1);assert.equal(pushes.length,2);
""")


def test_new_critical_alert_notifies_even_if_total_count_is_unchanged():
    node(r"""
actualizarNotificaciones(data(),false);actualizarNotificaciones(data([stock(2)]),true);
assert.equal(pushes.length,1);actualizarNotificaciones(data([stock(2)]),true);
assert.equal(pushes.length,1);
""")


def test_preferences_are_separate_by_user_and_api_and_never_follow_a_token():
    node(r"""
actualizarNotificaciones(data(),false);descartarTodasNotificaciones();const firstKey=_notifStorageKey;
TOKEN='renewed';reload();actualizarNotificaciones(data(),false);assert.equal(visible().length,0);
_currentUser={id:2};actualizarNotificaciones(data(),false);assert.equal(visible().length,1);
descartarTodasNotificaciones();_currentUser={id:1};actualizarNotificaciones(data(),false);
assert.equal(visible().length,0);API_URL='https://other.test';actualizarNotificaciones(data(),false);
assert.equal(visible().length,1);assert.notEqual(_notifStorageKey,firstKey);
_currentUser=null;actualizarNotificaciones(data(),false);assert.equal(visible().length,1);
assert.equal(_notifStorageKey,'');
""")


def test_product_and_ingredient_with_same_id_and_name_have_distinct_keys():
    node(r"""
actualizarNotificaciones(data([stock(),stock(1,0,'Producto de prueba','ingrediente')]),false);
const [a,b]=_notifCache;assert.notEqual(claveNotificacion(a),claveNotificacion(b));
descartarNotificacion(claveNotificacion(a));assert.equal(visible().length,1);
assert.equal(visible()[0],b);
""")


@pytest.mark.parametrize("broken", ["not-json", "{}", '[null,12,{"bad":1}]'])
def test_malformed_local_preferences_never_hide_alerts(broken):
    import json

    node("saved.set('jc_notif_descartadas_v1:https://synthetic.test:1', " + json.dumps(broken) + r""");
actualizarNotificaciones(data(),false);assert.equal(visible().length,1);
""")


def test_blocked_storage_is_nonfatal_and_explains_session_only_dismissal():
    node(r"""
storageFails=true;actualizarNotificaciones(data(),false);descartarTodasNotificaciones();
assert.equal(visible().length,0);assert.equal(errors.length,1);
assert(errors[0][0].includes('sesi'));
restaurarNotificaciones();assert.equal(visible().length,1);
""")


def test_names_and_dismissal_keys_cannot_break_button_attributes():
    node(r"""
actualizarNotificaciones(data([stock(1,0,'<img src=x onerror="bad()"> & test')]),false);
const html=document.getElementById('notif-list').innerHTML;
assert(!html.includes('<img'));assert(html.includes('&lt;img'));assert(html.includes('&quot;'));
assert(html.includes('aria-label="Descartar aviso:'));
assert(html.includes('data-notif-clave="[&quot;'));
""")


def test_failed_or_stale_reads_do_not_prune_dismissals_or_replace_current_user():
    node(r"""
(async()=>{
  actualizarNotificaciones(data(),false);descartarTodasNotificaciones();
  assert.throws(()=>actualizarNotificaciones({},true),/alertas/);
  assert.equal(Object.keys(_notifDescartadas).length,1);
  let load=cargarNotificaciones();reads[0].reject(new Error('offline'));await load;
  assert.equal(Object.keys(_notifDescartadas).length,1);
  load=cargarNotificaciones();_versionSesion++;_currentUser={id:2};
  actualizarNotificaciones(data([stock(2)]),false);
  reads[1].resolve(data([]));await load;assert.equal(_notifCache.length,1);
  assert.equal(_notifCache[0].titulo,'Agotado: Producto de prueba');
})().catch(e=>{console.error(e);process.exitCode=1;});
""")


def test_reopening_after_a_fresh_poll_does_not_restore_a_dismissed_alert():
    node(r"""
(async()=>{
  actualizarNotificaciones(data(),false);
  actualizarNotificaciones(data([stock(1,-1)]),true);
  descartarTodasNotificaciones();
  const key=claveNotificacion(_notifCache[0]);
  const load=cargarNotificaciones();
  assert.equal(reads[0].method,'GET');assert.equal(reads[0].path,'/reportes/alertas');
  assert.equal(reads[0].options.silenciosa,true);
  reads[0].resolve(data([stock(1,-1)]));await load;
  assert.equal(visible().length,0);assert(_notifDescartadas[key]);
  actualizarNotificaciones(data([stock(1,-1)]),true);
  assert.equal(visible().length,0);assert.equal(pushes.length,1);
})().catch(e=>{console.error(e);process.exitCode=1;});
""")


def test_notification_controls_have_touch_targets_and_scrollable_content():
    assert 'aria-label="Cerrar notificaciones"' in HTML
    assert 'id="notif-descartar-todas"' in HTML
    assert 'id="notif-restaurar"' in HTML
    assert ".notif-dismiss{width:44px;height:44px;min-height:44px" in HTML
    assert ".notif-panel #notif-list{overflow-y:auto;min-height:0;flex:1 1 auto" in HTML
