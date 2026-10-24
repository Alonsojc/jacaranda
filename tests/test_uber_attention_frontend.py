"""Browser-independent behavioral checks for alerts, outages and stale responses."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest


def test_attention_survives_navigation_outages_and_duplicate_notifications():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required")
    source = Path("app/sandbox_static/attention.js").read_text()
    assert "localStorage" not in source and "sessionStorage" not in source and "innerHTML" not in source
    script = r"""
const assert=require('node:assert/strict'),vm=require('node:vm');
class Element {
 constructor(){this.events={};this.checked=false;this.disabled=false;this.hidden=false;this.textContent='';}
 addEventListener(n,f){(this.events[n]??=[]).push(f);}
 async fire(n){for(const f of this.events[n]||[])await f();}
}
const elements={},el=id=>elements[id]??=new Element(),events={},docEvents={},timers=new Map();
let timerId=0,calls=0,unavailable=0,recovered=0,opened=null,busy=false,response,delayed=null,tones=0,resumes=0,closed=0,activeAudio=null;
class Audio {
 constructor(){this.state='suspended';this.currentTime=0;this.destination={};this.listeners=[];activeAudio=this;}
 addEventListener(name,handler){this.listeners.push(handler);}
 async resume(){this.state='running';resumes++;}
 async close(){this.state='closed';closed++;}
 createGain(){return {connect(){},gain:{setValueAtTime(){},linearRampToValueAtTime(){}}};}
 createOscillator(){return {frequency:{value:0},connect(){},start(){tones++;},stop(){}};}
}
const window={navigator:{onLine:true},AudioContext:Audio,
 setTimeout:(fn,delay)=>{const id=++timerId;timers.set(id,{fn,delay});return id;},
 clearTimeout:id=>timers.delete(id),addEventListener:(n,f)=>events[n]=f};
const document={title:'Jacaranda Sandbox',hidden:false,getElementById:el,addEventListener:(n,f)=>docEvents[n]=f};
vm.runInNewContext(SOURCE,{window,document,Date,Set,Math,Number,Error});
const id=n=>'00000000-0000-4000-8000-'+String(n).padStart(12,'0');
const row=(n,type='nuevo',event=n)=>({pedido_id:id(n),event_id:id(1000+event),tipo:type});
const value=rows=>({entorno:'sandbox',total:rows.length,pedidos:rows,
 conteos:Object.fromEntries(['nuevo','verificar','preparacion','programado'].map(k=>[k,rows.filter(r=>r.tipo===k).length]))});
response=value([]);
const monitor=window.createSandboxAttention({
 api:async path=>{assert.equal(path,'/api/v1/uber-eats/sandbox/atencion');calls++;if(delayed)return delayed;if(response instanceof Error)throw response;return response;},
 isBusy:()=>busy,onUnavailable:()=>unavailable++,onRecovered:()=>recovered++,onUpdate:()=>{},openOrder:event=>opened=event,
});
const flush=async()=>{for(let i=0;i<8;i++)await new Promise(setImmediate);};
const run=async delay=>{const next=[...timers].find(([,t])=>t.delay===delay);assert(next,'missing timer '+delay);timers.delete(next[0]);next[1].fn();await flush();};
(async()=>{
 monitor.start();await flush();assert(monitor.connected());assert(el('attention-alert').hidden);assert.equal(recovered,1);
 response=value([row(1)]);await run(15000);
 assert(!el('attention-alert').hidden);assert.equal(el('attention-count').textContent,'1 pedido pendiente');assert.equal(tones,0);
 el('attention-sound').checked=true;await el('attention-sound').fire('change');assert.equal(resumes,1);assert.equal(tones,2);
 response=value([row(1,'nuevo',99)]);await run(15000);assert.equal(tones,2,'repeat event must not ring twice for the same order');
 response=value([row(1),row(2)]);await run(15000);assert.equal(tones,4);assert.equal(document.title,'(2) Jacaranda Sandbox');
 busy=true;monitor.syncControls();assert(el('attention-open').disabled);await el('attention-open').fire('click');assert.equal(opened,null);
 busy=false;monitor.syncControls();await el('attention-open').fire('click');assert.equal(opened,id(1001));
 response=new Error('network');await run(15000);assert(!monitor.connected());assert(!el('attention-alert').hidden);
 assert.equal(el('attention-count').textContent,'2 pedidos pendientes');assert.equal(el('attention-connection').textContent,'Bandeja sin actualizar');
 await run(5000);await run(10000);await run(20000);assert([...timers.values()].some(t=>t.delay===30000));
 const beforeOffline=calls;window.navigator.onLine=false;events.offline();assert.equal(timers.size,0);assert(!monitor.connected());
 await monitor.refresh();assert.equal(calls,beforeOffline);assert.equal(el('attention-connection').textContent,'Sin conexi\u00f3n a internet');
 response=value([row(1),row(2)]);window.navigator.onLine=true;events.online();await flush();assert(monitor.connected());assert.equal(tones,4);
 document.hidden=true;docEvents.visibilitychange();assert.equal(timers.size,0);const hiddenCalls=calls;await monitor.refresh();assert.equal(calls,hiddenCalls);
 document.hidden=false;docEvents.visibilitychange();await flush();assert(monitor.connected());assert.equal(tones,4);
 let resolve;delayed=new Promise(r=>resolve=r);monitor.refresh();monitor.refresh();await flush();const beforeResolve=calls;
 window.navigator.onLine=false;events.offline();resolve(value([row(9)]));await flush();assert(!monitor.connected());assert.equal(el('attention-count').textContent,'2 pedidos pendientes');
 delayed=null;response=value([row(2)]);window.navigator.onLine=true;events.online();await flush();assert(monitor.connected());assert.equal(calls,beforeResolve+1);
 assert.equal(el('attention-count').textContent,'1 pedido pendiente');assert.equal(tones,4);
 let stale;delayed=new Promise(r=>stale=r);monitor.refresh();await flush();monitor.stop();stale(value([row(99)]));await flush();
 assert(el('attention-alert').hidden);assert.equal(document.title,'Jacaranda Sandbox');assert.equal(timers.size,0);assert.equal(closed,1);assert.equal(tones,4);
 delayed=null;response=value([]);monitor.start();await flush();assert(monitor.connected());assert(!el('attention-sound').checked);
 el('attention-sound').checked=true;await el('attention-sound').fire('change');assert(el('attention-sound').checked);
 activeAudio.state='suspended';activeAudio.listeners.forEach(handler=>handler());assert(!el('attention-sound').checked);
 assert.equal(el('attention-audio-status').textContent,'Sonido en pausa');
 response={entorno:'production',total:0,conteos:{nuevo:0,verificar:0,preparacion:0,programado:0},pedidos:[]};
 await run(15000);assert(!monitor.connected());assert(unavailable>0);
 monitor.stop();
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    result = subprocess.run([node, "-e", "const SOURCE=" + json.dumps(source) + ";" + script],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
