"""Execute the real worker with simulated cache, network and time."""

from pathlib import Path
import shutil
import subprocess

import pytest


HARNESS = r"""
const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const listeners={},timers=new Map(),cache=new Map(),writes=[],requests=[];
let time=0,nextTimer=0,fetchImpl;
const key=request=>new URL(typeof request==='string'?request:request.url,'https://app.test/jacaranda/').href;
const store={match:async request=>cache.get(key(request))?.clone(),
  put:async(request,response)=>{writes.push(key(request));cache.set(key(request),response.clone());}};
const ctx=vm.createContext({URL,Response,AbortController,console,
  self:{addEventListener:(type,fn)=>listeners[type]=fn,skipWaiting:async()=>{},clients:{claim:async()=>{}}},
  caches:{open:async()=>store,match:request=>store.match(request),keys:async()=>[],delete:async()=>true},
  setTimeout:(fn,ms)=>{const id=++nextTimer;timers.set(id,{fn,at:time+ms});return id;},
  clearTimeout:id=>timers.delete(id),
  fetch:(request,opts)=>{requests.push({request,opts});return fetchImpl(request,opts);}});
vm.runInContext(fs.readFileSync('docs/sw.js','utf8'),ctx);
function response(text='fresh shell',status=200,type='text/html'){
  const r=new Response(text,{status,headers:{'Content-Type':type}});
  Object.defineProperty(r,'type',{value:'basic'});return r;
}
function request(url='https://app.test/jacaranda/?refresh=1',method='GET',extra={}){
  return {url,method,mode:'navigate',headers:new Headers({Accept:'text/html',...extra})};
}
function dispatch(req=request()){
  let result;const work=[];
  listeners.fetch({request:req,respondWith:p=>result=Promise.resolve(p),waitUntil:p=>work.push(p)});
  return {result,work};
}
async function flush(){for(let i=0;i<6;i++)await new Promise(setImmediate);}
async function advance(ms){
  const end=time+ms;
  while(true){
    const due=[...timers].filter(([,t])=>t.at<=end).sort((a,b)=>a[1].at-b[1].at)[0];
    if(!due)break;time=due[1].at;timers.delete(due[0]);due[1].fn();await flush();
  }
  time=end;await flush();
}
function seed(){cache.set(key('./index.html'),response('cached shell'));}
"""


def run_worker(body):
    executable = shutil.which("node")
    if not executable:
        pytest.skip("Node required")
    script = HARNESS + "\nconst watchdog=setTimeout(()=>process.exit(97),8000);\n(async()=>{\n" + body + r"""
})().then(()=>clearTimeout(watchdog),e=>{clearTimeout(watchdog);console.error(e);process.exitCode=1;});
"""
    result = subprocess.run([executable, "-e", script], capture_output=True, text=True, timeout=12)
    assert result.returncode == 0, result.stderr


def test_stalled_navigation_returns_cached_shell_within_budget():
    run_worker(r"""
seed();fetchImpl=()=>new Promise(()=>{});
const event=dispatch();let done=false;event.result.then(()=>done=true);await flush();
await advance(1799);assert.equal(done,false);
await advance(1);assert.equal(await (await event.result).text(),'cached shell');
assert.equal(writes.length,0);
await advance(10200);await Promise.all(event.work);
assert.equal(requests[0].opts.signal.aborted,true);assert.equal(timers.size,0);
""")


def test_late_success_refreshes_only_canonical_shell_without_reloading_clients():
    run_worker(r"""
seed();let resolve;fetchImpl=()=>new Promise(r=>resolve=r);
const event=dispatch();await flush();await advance(1800);
assert.equal(await (await event.result).text(),'cached shell');
resolve(response('new shell'));await Promise.all(event.work);
assert.deepEqual(writes,[key('./index.html')]);assert.equal(cache.size,1);
fetchImpl=()=>Promise.reject(new TypeError('offline'));
assert.equal(await (await dispatch(request('https://app.test/jacaranda/?refresh=2')).result).text(),'new shell');
assert.equal(timers.size,0);
""")


@pytest.mark.parametrize("failure", ["network", "502", "invalid-type"])
def test_unavailable_navigation_preserves_cached_shell(failure):
    run_worker("const failure=" + repr(failure) + r""";
seed();fetchImpl=()=>failure==='network'?Promise.reject(new TypeError('offline')):
  Promise.resolve(failure==='502'?response('bad gateway',502):response('{}',200,'application/json'));
const event=dispatch();assert.equal(await (await event.result).text(),'cached shell');
await Promise.all(event.work);assert.equal(writes.length,0);assert.equal(timers.size,0);
""")


def test_missing_cache_gets_nonblank_recovery_page_on_error_or_timeout():
    run_worker(r"""
fetchImpl=()=>Promise.resolve(response('bad gateway',503));
let event=dispatch(),r=await event.result;
assert.equal(r.status,503);assert((await r.text()).includes('Reintentar'));
assert.equal(r.headers.get('Cache-Control'),'no-store');assert.equal(writes.length,0);
fetchImpl=()=>new Promise(()=>{});event=dispatch();await flush();await advance(12000);
r=await event.result;assert.equal(r.status,503);assert((await r.text()).includes('Jacaranda'));
await Promise.all(event.work);assert.equal(timers.size,0);
""")


def test_header_success_with_stalled_body_is_not_returned_or_cached():
    run_worker(r"""
seed();fetchImpl=(_,opts)=>{
  const r=response();r.clone=()=>({arrayBuffer:()=>new Promise((resolve,reject)=>{
    opts.signal.addEventListener('abort',()=>reject(new Error('body interrupted')));
  })});return Promise.resolve(r);
};
const event=dispatch();await flush();await advance(1800);
assert.equal(await (await event.result).text(),'cached shell');
await advance(10200);await Promise.all(event.work);
assert.equal(writes.length,0);assert.equal(timers.size,0);
""")


def test_fast_fresh_navigation_wins_and_is_cached_before_worker_finishes():
    run_worker(r"""
seed();fetchImpl=()=>Promise.resolve(response('new shell'));
const event=dispatch();assert.equal(await (await event.result).text(),'new shell');
await Promise.all(event.work);assert.equal(await cache.get(key('./index.html')).text(),'new shell');
assert.equal(timers.size,0);
""")


def test_install_is_local_only_and_bounded_when_one_asset_stalls():
    run_worker(r"""
fetchImpl=req=>String(req).includes('favicon')?new Promise(()=>{}):Promise.resolve(response('asset'));
let install;listeners.install({waitUntil:p=>install=p});await flush();
assert(requests.every(r=>String(r.request).startsWith('./')));
await advance(12000);await install;
assert(cache.has(key('./index.html')));assert(!cache.has(key('./favicon.svg')));
assert.equal(timers.size,0);
""")


def test_authenticated_requests_remain_network_only_and_mutations_are_not_replayed():
    run_worker(r"""
seed();fetchImpl=()=>Promise.reject(new TypeError('offline'));
for(const req of [request('https://api.test/api/v1/auth/me'),request(undefined,'GET',{Authorization:'Bearer test-only'})]){
  const event=dispatch(req),r=await event.result;assert.equal(r.status,503);
  assert.equal((await r.json()).error,'offline');assert.equal(event.work.length,0);
}
assert.equal(requests.length,2);assert.equal(writes.length,0);assert.equal(timers.size,0);
for(const method of ['POST','PUT','PATCH','DELETE'])assert.equal(dispatch(request(undefined,method)).result,undefined);
assert.equal(requests.length,2);
""")


def test_failed_shell_install_cannot_activate_and_discard_previous_cached_version():
    run_worker(r"""
fetchImpl=req=>(req==='./'||req==='./index.html')?new Promise(()=>{}):Promise.resolve(response('asset'));
let install;listeners.install({waitUntil:p=>install=p});
const rejected=assert.rejects(install,/Keep the previous worker/);
await flush();await advance(12000);await rejected;
assert(!cache.has(key('./index.html')));assert(!cache.has(key('./')));assert.equal(timers.size,0);
""")


def test_static_cache_hit_avoids_network_and_miss_always_returns_a_response():
    run_worker(r"""
cache.set(key('./favicon.svg'),response('cached icon',200,'image/svg+xml'));
fetchImpl=()=>new Promise(()=>{});
let req=request('https://app.test/jacaranda/favicon.svg');req.mode='cors';req.headers=new Headers();
assert.equal(await (await dispatch(req).result).text(),'cached icon');assert.equal(requests.length,0);
req=request('https://app.test/jacaranda/missing.js');req.mode='cors';req.headers=new Headers();
const event=dispatch(req);await flush();await advance(12000);
assert.equal((await event.result).status,504);assert.equal(timers.size,0);
""")


def test_railway_waits_for_ready_application_before_routing(client):
    import json

    deploy = json.loads(Path("railway.json").read_text())["deploy"]
    assert deploy["healthcheckPath"] == "/health"
    assert deploy["healthcheckTimeout"] == 300
    assert client.get(deploy["healthcheckPath"]).status_code == 200
