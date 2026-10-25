"""TEST finance UI confirmations, exact amounts and stale-session protection."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest


def test_finance_confirmation_replay_logout_and_net():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required")
    source = Path("app/sandbox_static/finance.js").read_text()
    assert "innerHTML" not in source and "localStorage" not in source
    script = r"""
const assert=require('node:assert/strict'),vm=require('node:vm');
class Element {
 constructor(){this.children=[];this.events={};this.value='';this.checked=false;this.disabled=false;this.hidden=false;this.textContent='';}
 addEventListener(n,f){(this.events[n]??=[]).push(f);} async fire(n,e={}){for(const f of this.events[n]||[])await f(e);}
 appendChild(c){this.children.push(c);return c;} append(...c){this.children.push(...c);} replaceChildren(...c){this.children=c;}
}
const elements={},el=id=>elements[id]??=new Element(),calls=[],window={};
const document={getElementById:el,createElement:()=>new Element()};
vm.runInNewContext(SOURCE,{window,document,Date,JSON,Number,encodeURIComponent});
let busy=false,connected=true,generation=1,confirmation,delayed=null;
const preview={pedido_id:'test-id',estado:'SUCCEEDED',registrable:true,detalle_sha256:'a'.repeat(64),revision:0,
 plan:{total:{gross:'4.00'},instructions:'<img onerror=fixture>',lines:[]}};
const data={totales:{},pedidos:[],inventario:[],empaques:[],efectivo_caja:'0.00'};
const panel=window.createSandboxFinance({busy:()=>busy,connected:()=>connected,generation:()=>generation,
 setBusy:x=>busy=x,show:()=>{},status:()=>{},confirm:()=>new Promise(r=>confirmation=r),
 api:async(path,method,body)=>{
   calls.push({path,method,body});
   if(path.endsWith('/consultar'))return delayed?await delayed:structuredClone(preview);
   if(path.endsWith('/accion')){preview.venta_id=1;preview.revision++;return {};}
   return data;
 }});
const flush=async()=>{for(let i=0;i<8;i++)await new Promise(setImmediate);};
(async()=>{
 panel.enable(true);await panel.open('test-id');
 assert(el('finance-import').disabled);assert.equal(el('finance-notes').textContent,'<img onerror=fixture>');
 el('finance-reviewed').checked=true;await el('finance-reviewed').fire('change');assert(!el('finance-import').disabled);
 await el('finance-import').fire('click');await el('finance-import').fire('click');await flush();
 assert.equal(calls.filter(c=>c.path.endsWith('/accion')).length,0);
 confirmation(true);await flush();assert.equal(calls.filter(c=>c.path.endsWith('/accion')).length,1);
 assert(!el('finance-reviewed').checked);assert(el('finance-import').disabled);
 el('finance-reference').value='visual';el('finance-deductions').value='1.00';await el('finance-deductions').fire('input');
 assert.equal(el('finance-net').value,'3.00');
 el('finance-reviewed').checked=true;await el('finance-reviewed').fire('change');
 await el('finance-settlement').fire('submit',{preventDefault(){}});await flush();confirmation(true);await flush();
 const sent=calls.filter(c=>c.path.endsWith('/accion')).at(-1).body;
 assert.equal(sent.bruto,'4.00');assert.equal(sent.deducciones,'1.00');assert.equal(sent.neto,'3.00');
 assert.equal(sent.referencia,'TEST-visual');assert.equal(el('finance-net').value,'3.00');
 connected=false;panel.invalidate();assert(el('finance-reconcile').disabled);
 connected=true;let resolve;delayed=new Promise(r=>resolve=r);const pending=panel.open('test-id');await flush();
 generation++;panel.reset();resolve(preview);await pending;
 assert(el('finance-detail').hidden);assert.equal(el('finance-reference').value,'');
 assert.equal(el('finance-notes').textContent,'');
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
    result = subprocess.run([node, "-e", "const SOURCE=" + json.dumps(source) + ";" + script],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
