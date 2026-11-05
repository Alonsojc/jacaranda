"""Exercise the Home Screen push flow without an Apple device or remote services."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest


def run_node(source, script):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required")
    result = subprocess.run([node, "-e", "const SOURCE=" + json.dumps(source) + ";" + script],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_push_permission_subscription_logout_and_key_rotation():
    source = Path("app/sandbox_static/push.js").read_text()
    assert "localStorage" not in source and "sessionStorage" not in source
    script = r"""
const assert=require('node:assert/strict'),vm=require('node:vm');
class Element {
 constructor(){this.events={};this.disabled=false;this.hidden=false;this.textContent='';}
 addEventListener(name,fn){this.events[name]=fn;}
 click(){this.events.click();}
}
const elements={},get=id=>elements[id]??=new Element();
const key=new Uint8Array([4,5,6,7]), other=new Uint8Array([9,8,7]), encoded=Buffer.from(key).toString('base64url');
const endpoint='https://web.push.apple.com/fake';
let current=null,subscriptions=0,unsubscribes=0,calls=[],permissionGesture=false,serverActive=false;
const subscription=which=>({endpoint,options:{applicationServerKey:which},toJSON:()=>({endpoint,keys:{auth:'test',p256dh:'test'}}),
 async unsubscribe(){unsubscribes++;current=null;return true;}});
const registration={pushManager:{async getSubscription(){return current;},subscribe(options){
 assert(permissionGesture,'subscribe must be initiated synchronously by user click');
 assert(options.userVisibleOnly); assert.deepEqual([...options.applicationServerKey],[...key]);
 subscriptions++; current=subscription(key);return Promise.resolve(current);
}}};
const api=async(path,method,data)=>{
 calls.push([path,method,data]);
 if(path.endsWith('/config'))return {clave_publica:encoded};
 if(path.endsWith('/status'))return {activa:serverActive,ultimo_envio:null};
 if(path.endsWith('/subscription')){serverActive=true;return {activa:true};}
 if(path.endsWith('/unsubscribe')){serverActive=false;return {activa:false};}
 throw Error('unexpected API');
};
const navigator={serviceWorker:{async register(path,opts){assert.equal(path,'/sandbox-sw.js');assert.equal(opts.scope,'/');return registration;},ready:Promise.resolve(registration)}};
const window={isSecureContext:true,PushManager:function(){}};
vm.runInNewContext(SOURCE,{window,navigator,document:{getElementById:get},Uint8Array,atob:s=>Buffer.from(s,'base64').toString('binary'),Promise});
const flush=async()=>{for(let i=0;i<8;i++)await new Promise(setImmediate);};
const controller=window.createSandboxPush({api});
(async()=>{
 await controller.start(false);assert(get('push-toggle').hidden);
 await controller.start(true);assert(!get('push-toggle').hidden&&!get('push-toggle').disabled);
 assert.match(get('push-status').textContent,/desactivados/);
 permissionGesture=true;get('push-toggle').click();permissionGesture=false;await flush();
 assert.equal(subscriptions,1);assert(serverActive);assert.match(get('push-status').textContent,/activados/);
 controller.reset();assert(get('push-toggle').hidden);assert.equal(unsubscribes,0,'page hide must preserve push');
 await controller.start(true);assert.match(get('push-toggle').textContent,/Desactivar/);
 get('push-toggle').click();await flush();assert.equal(unsubscribes,1);assert(!serverActive);
 current=subscription(other);await controller.start(true);
 assert.match(get('push-toggle').textContent,/Restablecer/);assert.match(get('push-status').textContent,/clave/);
 get('push-toggle').click();await flush();assert.equal(unsubscribes,2);assert.equal(subscriptions,1);
 permissionGesture=true;get('push-toggle').click();permissionGesture=false;await flush();
 assert.equal(subscriptions,2);assert(serverActive);
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    run_node(source, script)


def test_worker_displays_generic_notification_and_opens_same_origin():
    source = Path("app/sandbox_static/sandbox-sw.js").read_text()
    assert "fetch(" not in source and "caches" not in source
    script = r"""
const assert=require('node:assert/strict'),vm=require('node:vm');
const handlers={},shown=[],opened=[],focused=[];
let clients=[{url:'https://other.test/',focus:()=>focused.push('other')},
 {url:'https://sandbox.test/',focus:()=>focused.push('sandbox')}];
const self={location:{origin:'https://sandbox.test'},addEventListener:(name,fn)=>handlers[name]=fn,
 registration:{showNotification:async(title,options)=>shown.push({title,options})},
 clients:{matchAll:async()=>clients,openWindow:async(url)=>opened.push(url)}};
vm.runInNewContext(SOURCE,{self,URL});
(async()=>{
 let wait;handlers.push({data:{json:()=>({body:'Nuevo pedido de prueba.',tag:'sandbox-12345678-1234-1234-1234-123456789abc'})},waitUntil:p=>wait=p});await wait;
 assert.equal(shown[0].title,'Jacaranda Sandbox');assert.equal(shown[0].options.body,'Nuevo pedido de prueba.');
 assert.equal(shown[0].options.data.url,'/');
 handlers.push({data:{json:()=>{throw Error('bad JSON')}},waitUntil:p=>wait=p});await wait;
 assert.equal(shown[1].options.body,'Hay un aviso de prueba.');
 let closed=0;handlers.notificationclick({notification:{close:()=>closed++},waitUntil:p=>wait=p});await wait;
 assert.deepEqual(focused,['sandbox']);assert.equal(closed,1);
 clients=[];handlers.notificationclick({notification:{close:()=>closed++},waitUntil:p=>wait=p});await wait;
 assert.deepEqual(opened,['/']);
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    run_node(source, script)
