"""Browser-side workflow invariants without network, storage or real orders."""

from pathlib import Path
import json
import shutil
import subprocess

import pytest


def test_sandbox_ui_text_rendering_gates_and_stale_responses():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required")
    source = Path("docs/js/uber-sandbox.js").read_text()
    html = Path("docs/index.html").read_text()
    invalidator = html.split("function invalidarTareasSesion() {", 1)[1].split("\nfunction moduloDesactivado", 1)[0]
    invalidator = "function invalidarTareasSesion() {" + invalidator
    assert ".innerHTML" not in source and "localStorage" not in source and "setInterval" not in source
    script = r"""
const assert=require('node:assert/strict'); const vm=require('node:vm');
class Element {
  constructor(){this.children=[];this.disabled=false;this.checked=false;this.style={};this.events={};this.textContent='';this.classList={remove:()=>{this.closed=true;}};}
  replaceChildren(){this.children=[];} appendChild(c){this.children.push(c);return c;}
  insertRow(){return this.appendChild(new Element());} insertCell(){return this.appendChild(new Element());}
  createTHead(){return this.appendChild(new Element());} createTBody(){return this.appendChild(new Element());}
  addEventListener(n,f){this.events[n]=f;}
}
const elements={}; const el=id=>elements[id]||(elements[id]=new Element());
const calls=[]; let admin=true;
const evt={id:1,event_id:'event-uuid',pedido_id:'order-uuid',tipo:'<img src=x onerror=alert(1)>',estado:'recibido',recibido_en:'2026-10-21T18:00:00Z'};
const details={pedido:{id:'order-uuid',display_id:'TEST',state:'OFFERED',carts:[{items:[{title:'<script>attack</script>'}]}],store_instructions:'Alergia: nueces'},detalle_sha256:'a'.repeat(64),acciones_habilitadas:true,requiere_conciliacion:false};
const window={esAdminActual:()=>admin,crypto:{randomUUID:()=> 'request-uuid'},api:async(method,path,data)=>{
  calls.push({method,path,data});
  if(path.includes('/eventos?'))return {eventos:[evt]};
  if(path.endsWith('/consultar'))return structuredClone(details);
  return {estado:'confirmada'};
}};
const document={getElementById:el,createElement:()=>new Element()};
const context=window;Object.assign(context,{window,document,Date,JSON,encodeURIComponent,
  _versionSesion:0,_resguardoSeq:0,_egresosResumenSeq:0,_ocrSeq:0,_ticketEdicion:null,
  _cafCobranzaSeq:0,_pedCargaSeq:0,_migracionVentasTx:null,
  cerrarModal:id=>el(id).classList.remove('on'),cerrarCamaraEgreso:()=>{},limpiarEgresoForm:()=>{},
  cancelarAdminAuth:()=>{},cerrarClaveAutorizacion:()=>{},cerrarUsuario:()=>{}});
vm.createContext(context);vm.runInContext(SOURCE,context);vm.runInContext(INVALIDATOR,context);
(async()=>{
  window.reiniciarUberSandbox(); admin=false;
  await window.cargarEventosUberSandbox(); assert.equal(calls.length,0); admin=true;
  await window.cargarEventosUberSandbox();
  const table=el('uber-sandbox-eventos').children[0];const row=table.children[1].children[0];
  assert.equal(row.children[1].textContent,evt.tipo);
  row.children[4].children[0].events.click(); await new Promise(setImmediate);
  assert(el('uber-sandbox-detalle').textContent.includes('<script>attack</script>'));
  assert(el('uber-sandbox-aceptar').disabled);
  el('uber-sandbox-revisado').checked=true; window.actualizarAccionesUberSandbox();
  assert(!el('uber-sandbox-aceptar').disabled);
  await Promise.all([window.accionUberSandbox('aceptar'),window.accionUberSandbox('aceptar')]);
  assert.equal(calls.filter(c=>c.path.endsWith('/accion')).length,1);
  assert.equal(calls.at(-1).data.detalle_sha256,details.detalle_sha256);
  assert(el('uber-sandbox-aceptar').disabled);
  admin=false; window.invalidarTareasSesion();
  assert(el('modal-uber-preparacion').closed);
  assert(el('uber-sandbox-pedido').hidden);
  assert.equal(el('uber-sandbox-detalle').textContent,'');
  assert.equal(el('uber-sandbox-instrucciones').textContent,'');
  assert.equal(el('uber-sandbox-pedido-titulo').textContent,'');
  assert(el('uber-sandbox-aceptar').disabled);
  admin=true; let resolve;
  window.api=()=>new Promise(r=>resolve=r);
  const loading=window.cargarEventosUberSandbox(); window.reiniciarUberSandbox();
  resolve({eventos:[evt]});await loading;
  assert.equal(el('uber-sandbox-eventos').children.length,0);
  assert.equal(el('uber-sandbox-detalle').textContent,'');
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
    result = subprocess.run([node, "-e", "const SOURCE=" + json.dumps(source) + ";const INVALIDATOR=" + json.dumps(invalidator) + ";" + script], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_sandbox_module_is_cached_and_disabled_by_default():
    html = Path("docs/index.html").read_text()
    worker = Path("docs/sw.js").read_text()
    assert "js/uber-sandbox.js?v=jacaranda-v128" in html
    assert "./js/uber-sandbox.js?v=jacaranda-v128" in worker
    assert "UBER_EATS_SANDBOX_WEBHOOK_ENABLED=false" in Path(".env.example").read_text()
    assert "UBER_EATS_SANDBOX_ACTIONS_ENABLED=false" in Path(".env.example").read_text()
