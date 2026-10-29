"""Execute the shipped module with a minimal DOM and controlled async responses."""

import subprocess
from pathlib import Path

SOURCE = Path("docs/js/asistencia.js").read_text()
PREAMBLE = r"""
const assert = require('node:assert/strict');
const nodes = new Map();
function node(id) {
  if (!nodes.has(id)) nodes.set(id, {
    value:'',textContent:'',innerHTML:'',disabled:false,hidden:false,open:false,
    classList:{toggle(){},remove(){}}, listeners:{},
    addEventListener(name,fn){this.listeners[name]=fn;},
    querySelectorAll(){return [];},
    setAttribute(){}, showModal(){this.open=true;},close(){this.open=false;}
  });
  return nodes.get(id);
}
global.window = global;
let ready;
global.document = {getElementById:node,querySelectorAll(){return [];},
  addEventListener(name,fn){if(name==='DOMContentLoaded')ready=fn;}};
global._permisos = {asistencia:'editar'};
let _versionSesion=1;
const APP_TIMEZONE='America/Mexico_City';
function fechaHoyISO(){return '2026-10-28';}
function escHtml(v){return String(v).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;');}
const requests=[];
let respond;
function api(method,path,body){requests.push({method,path,body});return respond(method,path,body);}
let downloaded;
function descargarArchivoAutenticado(path){downloaded=path;}
const empty={items:[],total:0,resumen:{marcas:0,personas:0,sin_vincular:0}};
const row={dia:'2026-10-28',numero_reloj:'001',nombre_reloj:'<img onerror=alert(1)>',empleado_id:null,
  primera:'2026-10-28T15:30:00Z',ultima:null,marcas:1};
const populated={items:[row],total:1,resumen:{marcas:1,personas:1,sin_vincular:1}};
const status={lista:true,ultima_sincronizacion:null};
const event={preventDefault(){}};
async function settle(){await new Promise(resolve=>setImmediate(resolve));}
"""


def run_js(body):
    result = subprocess.run(["node", "-e", PREAMBLE + SOURCE + "\nready();\n(async()=>{" + body
                             + "})().catch(e=>{console.error(e);process.exitCode=1;});"],
                            text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_empty_state_disabled_sync_and_date_defaults():
    run_js("""
      respond=async(m,p)=>p.includes('/estado')?{lista:false}:empty;
      await initAsistencia();
      assert.equal(node('att-from').value,'2026-10-28');
      assert.equal(node('att-sync').disabled,true);
      assert.equal(node('att-export').disabled,true);
      assert.equal(node('att-marks').textContent,0);
      assert.match(node('att-body').innerHTML,/Sin checadas/);
      assert.equal(requests.length,2);
    """)


def test_readonly_no_mutations_and_escaped_names():
    run_js("""
      _permisos={asistencia:'ver'};
      respond=async(m,p)=>p.includes('/estado')?status:populated;
      await initAsistencia();
      assert.equal(node('att-sync').hidden,true);
      assert.match(node('att-body').innerHTML,/&lt;img/);
      assert.doesNotMatch(node('att-body').innerHTML,/<img onerror/);
      assert.doesNotMatch(node('att-body').innerHTML,/data-link/);
      await node('att-sync').listeners.click();
      assert.equal(requests.length,2);
    """)


def test_logout_ignores_inflight_response_and_does_not_requery_new_session():
    run_js("""
      let release;
      respond=()=>new Promise(resolve=>release=resolve);
      const loading=initAsistencia();
      _versionSesion++; resetAsistencia();
      release(populated); await loading;
      assert.doesNotMatch(node('att-body').innerHTML,/img/);
      assert.equal(node('att-marks').textContent,'\u2014');
      assert.equal(requests.length,1);
      assert.equal(node('att-export').disabled,true);
    """)


def test_failed_query_clears_previous_private_results():
    run_js("""
      respond=async(m,p)=>p.includes('/estado')?status:populated;
      await initAsistencia();
      respond=async()=>{throw new Error('Sin conexion');};
      node('att-filters').listeners.submit(event); await settle();
      assert.doesNotMatch(node('att-body').innerHTML,/&lt;img/);
      assert.equal(node('att-export').disabled,true);
      assert.equal(node('att-feedback').textContent,'Sin conexion');
    """)


def test_pending_connection_is_not_invalidated_by_a_records_query():
    run_js("""
      let release;
      respond=(m,p)=>p.includes('/estado')?new Promise(resolve=>release=resolve):Promise.resolve(populated);
      const loading=initAsistencia(); await settle();
      node('att-filters').listeners.submit(event); await settle();
      assert.equal(node('att-sync').disabled,true);
      release(status); await loading;
      assert.equal(node('att-sync').disabled,false);
      assert.equal(node('att-status').textContent,'Conexi\u00f3n configurada');
    """)


def test_logout_discards_pending_connection_status():
    run_js("""
      let release;
      respond=(m,p)=>p.includes('/estado')?new Promise(resolve=>release=resolve):Promise.resolve(populated);
      const loading=initAsistencia(); await settle();
      _versionSesion++; resetAsistencia();
      release(status); await loading;
      assert.equal(node('att-sync').disabled,true);
      assert.equal(node('att-status').textContent,'Conexi\u00f3n pendiente');
      assert.equal(node('att-last-sync').textContent,'');
    """)


def test_sync_rejects_large_range_and_does_not_double_submit():
    run_js("""
      respond=async(m,p)=>p.includes('/estado')?status:populated;
      await initAsistencia();
      node('att-from').value='2026-10-01';
      await node('att-sync').listeners.click();
      assert.match(node('att-feedback').textContent,/7 d/);
      assert.equal(requests.filter(r=>r.method==='POST').length,0);
      node('att-from').value='2026-10-28';
      let release;
      respond=(m,p)=>m==='POST'?new Promise(resolve=>release=resolve):Promise.resolve(p.includes('/estado')?status:populated);
      const pending=node('att-sync').listeners.click();
      await node('att-sync').listeners.click();
      assert.equal(requests.filter(r=>r.method==='POST').length,1);
      release({nuevas:1,repetidas:0,omitidas_otro_equipo:0}); await pending;
      assert.match(node('att-feedback').textContent,/1 nuevas/);
      assert.equal(node('att-sync').disabled,false);
    """)


def test_export_uses_loaded_filter_not_unsaved_inputs():
    run_js("""
      respond=async(m,p)=>p.includes('/estado')?status:populated;
      await initAsistencia();
      node('att-from').value='2026-01-01';
      node('att-export').listeners.click();
      assert.match(downloaded,/desde=2026-10-28/);
      assert.doesNotMatch(downloaded,/2026-01-01/);
    """)


def test_pagination_preserves_applied_filters_until_submit():
    run_js("""
      respond=async(m,p)=>p.includes('/estado')?status:{...populated,total:60};
      await initAsistencia();
      node('att-from').value='2026-10-27';
      node('att-search').value='Sofia';
      node('att-next').listeners.click(); await settle();
      assert.match(requests.at(-1).path,/desde=2026-10-28/);
      assert.match(requests.at(-1).path,/buscar=&vista=diario&pagina=2/);
      node('att-previous').listeners.click(); await settle();
      assert.match(requests.at(-1).path,/buscar=&vista=diario&pagina=1/);
      node('att-next').listeners.click(); await settle();
      node('att-filters').listeners.submit(event); await settle();
      assert.match(requests.at(-1).path,/desde=2026-10-27/);
      assert.match(requests.at(-1).path,/buscar=Sofia&vista=diario&pagina=1/);
    """)


def test_link_refresh_preserves_applied_filters_and_page():
    run_js("""
      respond=async(m,p)=>p.includes('/estado')?status:
        p.includes('/empleados')?[{id:1,nombre:'Sofia',numero_empleado:'001'}]:
        {...populated,total:60};
      await initAsistencia();
      node('att-next').listeners.click(); await settle();
      node('att-from').value='2026-10-27';
      node('att-search').value='Sofia';
      node('att-body').listeners.click({target:{closest(){return {dataset:{link:'0'}};}}});
      await settle();
      node('att-employee').value='1';
      node('att-reason').value='Vinculacion verificada';
      await node('att-link-form').listeners.submit(event);
      assert.equal(node('att-dialog').open,false);
      assert.match(requests.at(-1).path,/desde=2026-10-28/);
      assert.match(requests.at(-1).path,/buscar=&vista=diario&pagina=2/);
      assert.equal(requests.filter(r=>r.method==='POST').length,1);
    """)


def test_assets_registered_and_privacy_reset_wired():
    html = Path("docs/index.html").read_text()
    sw = Path("docs/sw.js").read_text()
    assert 'id="asistencia"' in html
    assert 'role="tablist" aria-label="Vista de asistencia"' in html
    assert "if (p === 'asistencia') return initAsistencia();" in html
    assert "if (typeof resetAsistencia === 'function') resetAsistencia();" in html
    for asset in ("css/asistencia.css", "js/asistencia.js"):
        assert asset + "?v=jacaranda-v133" in html
        assert asset + "?v=jacaranda-v133" in sw
    assert "localStorage" not in SOURCE and "sessionStorage" not in SOURCE
