"""Cross-panel browser workflow with fixtures, not physical iPad certification."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest


def test_finance_keeps_order_alerts_and_blocks_stale_actions_without_orders_app():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required")
    source = "\n".join(Path("app/sandbox_static", name).read_text()
                       for name in ("attention.js", "finance.js", "sandbox.js"))
    script = r"""
const assert=require('node:assert/strict'),vm=require('node:vm');
class Element {
  constructor(){this.children=[];this.events={};this.value='';this.checked=false;this.disabled=false;
    this.hidden=false;this.open=false;this.textContent='';}
  addEventListener(n,f,o){(this.events[n]??=[]).push({f,once:o?.once});}
  async fire(n,e={}){const a=this.events[n]||[];this.events[n]=a.filter(x=>!x.once);for(const x of a)await x.f(e);}
  appendChild(c){this.children.push(c);return c;} append(...c){this.children.push(...c);}
  replaceChildren(...c){this.children=c;} setAttribute(n,v){this[n]=v;} removeAttribute(n){delete this[n];}
  showModal(){this.open=true;} close(value){this.open=false;this.returnValue=value;return this.fire('close');}
}
const elements={},el=id=>elements[id]??=new Element(),calls=[],timers=new Map(),events={},docEvents={};
const order='11111111-1111-4111-8111-111111111111',event='22222222-2222-4222-8222-222222222222';
let serial=0,pending=[],failed=false;
const window={navigator:{onLine:true},crypto:{randomUUID:()=> 'fixture-request'},
 setTimeout(fn,ms){timers.set(++serial,{fn,ms});return serial;},clearTimeout(id){timers.delete(id);},
 setInterval(){},addEventListener(n,f){events[n]=f;},
 fetch:async(path,options)=>{
   assert(path.startsWith('/'));calls.push({path,options});
   if(failed)throw new TypeError('Fixture offline');
   let data;
   if(path==='/sandbox/estado')data={entorno:'sandbox',tienda_real_activada:false,finanzas_habilitadas:true};
   else if(path.endsWith('/atencion'))data={entorno:'sandbox',total:pending.length,pedidos:pending,
     conteos:{nuevo:pending.filter(x=>x.tipo==='nuevo').length,verificar:pending.filter(x=>x.tipo==='verificar').length,preparacion:0,programado:0}};
   else if(path.endsWith('/finanzas'))data={efectivo_caja:'0.00',pedidos:[],inventario:[],empaques:[],
     totales:{bruto_pedidos:'0.00',bruto_por_conciliar:'0.00',bruto_en_revision:'0.00',bruto_conciliado_test:'0.00',deducciones_test:'0.00',neto_test:'0.00'}};
   else if(path.includes('/eventos/')&&path.endsWith('/consultar'))data={entorno:'sandbox',
     acciones_habilitadas:true,requiere_conciliacion:false,listo_confirmado:false,detalle_sha256:'a'.repeat(64),
     pedido:{id:order,display_id:'TEST',state:'OFFERED',carts:[],store_instructions:'Ficticio; no preparar'}};
   else if(path.includes('/finanzas/pedidos/')&&path.endsWith('/consultar'))data={pedido_id:order,
     estado:'SUCCEEDED',registrable:true,venta_id:1,revision:0,detalle_sha256:'b'.repeat(64),
     cancelacion:false,problema:null,plan:{instructions:'Ficticio; no preparar',total:{gross:'1.00'},lines:[]}};
   else if(path.endsWith('/ticket'))data={ensayo:true,folio:'TEST-1',monto_recibido:'0.00'};
   else throw new Error('Unexpected operation: '+path);
   return {ok:true,status:200,json:async()=>data};
 }};
const document={title:'Jacaranda Sandbox',hidden:false,getElementById:el,createElement:()=>new Element(),
 querySelectorAll:()=>[],addEventListener(n,f){docEvents[n]=f;}};
vm.runInNewContext(SOURCE,{window,document,AbortController,Date,JSON,URL,encodeURIComponent});
const flush=async()=>{for(let i=0;i<14;i++)await new Promise(setImmediate);};
async function poll(){const entry=[...timers].find(([,t])=>t.ms===15000);assert(entry);timers.delete(entry[0]);await entry[1].fn();await flush();}
(async()=>{
 el('access-key').value='local-fixture-only';await el('access-form').fire('submit',{preventDefault(){}});await flush();
 assert(!el('workspace').hidden);assert(!el('tab-finance').hidden);
 await el('tab-finance').fire('click');await flush();assert(!el('finance-panel').hidden);
 pending=[{pedido_id:order,event_id:event,tipo:'nuevo'}];await poll();
 assert(!el('finance-panel').hidden);assert(!el('attention-alert').hidden);
 assert.equal(el('attention-count').textContent,'1 pedido pendiente');
 await el('attention-open').fire('click');await flush();assert(!el('orders-panel').hidden);
 assert.equal(el('order-title').textContent,'Pedido TEST');assert(el('accept').disabled);
 await el('finance-order-open').fire('click');await flush();assert(!el('finance-panel').hidden);
 assert(!el('finance-ticket').disabled);await el('finance-ticket').fire('click');await flush();
 assert(!el('finance-ticket-text').hidden);
 el('finance-reviewed').checked=true;await el('finance-reviewed').fire('change');
 pending=[{pedido_id:order,event_id:event,tipo:'verificar'}];await poll();
 assert(!el('finance-panel').hidden);assert(el('finance-ticket-text').hidden);
 assert(el('finance-ticket').disabled);assert(el('finance-reconcile').disabled);
 assert(!el('finance-reviewed').checked);
 const writes=()=>calls.filter(x=>x.path.endsWith('/accion')).length;
 assert.equal(writes(),0);window.navigator.onLine=false;events.offline();await flush();
 assert.equal(el('attention-connection').textContent,'Sin conexi\u00f3n a internet');
 assert(el('finance-reload').disabled);assert(el('accept').disabled);
 window.navigator.onLine=true;events.online();await flush();
 assert.equal(el('attention-connection').textContent,'Bandeja conectada');assert.equal(writes(),0);
 assert(el('finance-ticket').disabled);assert(!el('finance-reviewed').checked);
 await el('logout').fire('click');await flush();assert(el('workspace').hidden);
 assert(el('attention-alert').hidden);assert(el('finance-detail').hidden);
 assert.equal(el('access-key').value,'');assert.equal(timers.size,0);
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
    result = subprocess.run([node, "-e", "const SOURCE=" + json.dumps(source) + ";" + script],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
