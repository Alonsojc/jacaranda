"""Standalone TEST panel events, confirmations, logout and stale replies."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest


def test_standalone_store_panel_never_repeats_commands_or_renders_after_logout():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required")
    source = Path("app/sandbox_static/sandbox.js").read_text()
    assert "innerHTML" not in source and "localStorage" not in source
    script = r"""
const assert=require('node:assert/strict'),vm=require('node:vm');
class Element {
  constructor(){this.children=[];this.events={};this.value='';this.checked=false;this.disabled=false;this.hidden=false;this.open=false;this.textContent='';}
  addEventListener(n,f,o){(this.events[n]??=[]).push({f,once:o?.once});}
  async fire(n,e={}){const a=this.events[n]||[];this.events[n]=a.filter(x=>!x.once);for(const x of a)await x.f(e);}
  appendChild(c){this.children.push(c);return c;} append(...c){this.children.push(...c);}
  replaceChildren(...c){this.children=c;} setAttribute(n,v){this[n]=v;} removeAttribute(n){delete this[n];}
  showModal(){this.open=true;} close(value){this.open=false;this.returnValue=value;return this.fire('close');}
  reportValidity(){return true;}
}
const elements={},el=id=>elements[id]??=new Element(),calls=[];
const store={nombre:'Jacaranda Sandbox',tienda_id:'test-store',revision:1,estado:'ONLINE',revocada:false,
 integracion:{integration_enabled:true},requiere_conciliacion:false,menu_publicado:true,cuenta_autorizada:false,
 items:[{id:'jacaranda-sandbox-brownie',precio_centavos:100,agotado:false}]};
let delayed=null;
const window={crypto:{randomUUID:()=> 'synthetic-request'},setTimeout:()=>1,clearTimeout:()=>{},setInterval:()=>{},addEventListener:()=>{},
 fetch:async(path,options)=>{
  calls.push({path,options});let data={};
  if(path.endsWith('/tienda'))data=delayed?await delayed:structuredClone(store);
  else if(path.endsWith('/menu-ficticio'))data={menu:{items:[{id:'jacaranda-sandbox-brownie',title:{translations:{es_mx:'<script>fixture</script>'}},price_info:{price:100}}]}};
  else if(path.includes('/eventos'))data={eventos:[],procesamiento:[]};
  return {ok:true,json:async()=>data};
 }};
const document={getElementById:el,createElement:()=>new Element(),querySelectorAll:()=>[],hidden:false};
vm.runInNewContext(SOURCE,{window,document,AbortController,Date,JSON,URL,encodeURIComponent});
const flush=async()=>{for(let i=0;i<8;i++)await new Promise(setImmediate);};
(async()=>{
 el('access-key').value='synthetic-access';await el('access-form').fire('submit',{preventDefault(){}});
 await el('tab-store').fire('click');await flush();assert(!el('store-online').disabled);
 assert.equal(el('fixture-items').children[0].children[0].textContent,'<script>fixture</script>');
 el('store-online').checked=false;await el('store-online').fire('change');await flush();
 assert(el('confirm-dialog').open);await el('confirm-dialog').close('cancel');await flush();
 assert(el('store-online').checked);assert.equal(calls.filter(x=>x.path.endsWith('/accion')).length,0);
 await el('publish-menu').fire('click');await el('publish-menu').fire('click');await flush();
 await el('confirm-dialog').close('confirm');await flush();
 assert.equal(calls.filter(x=>x.path.endsWith('/accion')).length,1);
 const sent=JSON.parse(calls.find(x=>x.path.endsWith('/accion')).options.body);
 assert.equal(sent.accion,'menu_publicar');assert(sent.solo_sandbox_confirmado);
 let resolve;delayed=new Promise(r=>resolve=r);await el('tab-menu').fire('click');await flush();
 await el('logout').fire('click');const count=calls.length;resolve(store);await flush();
 assert.equal(calls.length,count);assert(el('workspace').hidden);assert.equal(el('store-summary').children.length,0);
 assert.equal(el('fixture-items').children.length,0);assert(el('merchant-auth-link').hidden);assert(el('publish-menu').disabled);
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
    result = subprocess.run([node, "-e", "const SOURCE=" + json.dumps(source) + ";" + script],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
