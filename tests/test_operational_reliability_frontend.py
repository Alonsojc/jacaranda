"""Execute checkout, order recovery and history controls with fictional data."""

import shutil
import subprocess
from pathlib import Path

import pytest

HTML = (Path(__file__).resolve().parents[1] / "docs/index.html").read_text()


def function(name):
    start = HTML.index("function " + name + "(")
    return HTML[start:HTML.index("\n}", start) + 2]


def node(script):
    executable = shutil.which("node")
    if not executable:
        pytest.skip("Node required")
    result = subprocess.run([executable, "-e", script], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_offline_payload_keeps_price_channel_time_and_original_identity():
    node("const assert=require('node:assert/strict');\n" + function("payloadVentaPendiente") + r"""
const original={idempotency_key:'sale-one', canal:'cdmx', _timestamp:'2026-11-10T18:00:00Z',
  _total:140, monto_recibido:150, metodo_pago:'01', terminal:'efectivo', detalles:[{producto_id:1,cantidad:1}]};
const sent=payloadVentaPendiente(original);
assert.equal(sent.idempotency_key,'sale-one');
assert.equal(sent.canal,'cdmx');
assert.equal(sent.total_esperado,140);
assert.equal(sent.fecha_cobro_local,original._timestamp);
assert.equal(sent.monto_recibido,150);
assert.equal(sent._timestamp,undefined);
""")


def test_history_pending_is_not_labelled_paid_and_can_only_query_original_attempt():
    node(r"""
const assert=require('node:assert/strict'), fields={};
const document={getElementById:id=>fields[id]||=( {value:'',style:{},textContent:'',innerHTML:''})};
let _versionSesion=1, _histVentas=[{id:1,folio:'TEST',estado:'pendiente',total:80,pago_integrado:true,pago_proveedor:'clip'}];
let _histVentasResumen={total:1,total_cobrado:0,completadas:0,pagina:1,limite:25};
function fmt(x){return Number(x).toFixed(2);}
function escHtml(x){return String(x);}
function etiquetaPagoVenta(){return 'CLIP';}
function resumenProductosVenta(){return '';}
function renderPaginador(){}
function toast(){}
function cargarHistVentas(){}
function cargarCorte(){}
const requests=[];
function api(method,path){requests.push([method,path]);return Promise.resolve({estado_venta:'pendiente',estado_pago:'pending'});}
""" + function("renderHistVentas") + function("consultarPagoPendiente") + r"""
(async()=>{
renderHistVentas();
const markup=fields['hv-list'].innerHTML;
assert.ok(markup.includes('Pendiente de confirmaci'));
assert.ok(!markup.includes('>OK<'));
assert.ok(markup.includes('Consultar pago CLIP'));
assert.equal(fields['hv-total'].textContent,'$0.00');
assert.equal(fields['hv-count'].textContent,0);
const button={disabled:false};
consultarPagoPendiente(1,button);consultarPagoPendiente(1,button);
await new Promise(resolve=>setImmediate(resolve));
assert.deepEqual(requests,[['GET','/pagos/clip/pinpad/1']]);
assert.equal(button.disabled,false);
})().catch(e=>{console.error(e);process.exitCode=1;});
""")


ORDER_HARNESS = r"""
const assert=require('node:assert/strict');
let TOKEN='fixture',_versionSesion=1,_pedidoSyncPromise=null,_calPedVisible=false,_pedidoLocalRevision=null;
let _pedidosPendientes=[{id:'key1',payload:{idempotency_key:'key1',cliente_nombre:'Prueba',fecha_entrega:'2026-11-01',detalles:[]}}];
let stored=JSON.parse(JSON.stringify(_pedidosPendientes)),requests=0,lastError=null;
function conBloqueoColasVentas(cb){return Promise.resolve().then(()=>cb(()=>{}));}
function exigirSesionColasVigente(v,t){if(v!==_versionSesion||t!==TOKEN) throw Error('Changed');}
function verificarPropietarioColasVentas(){}
function leerPedidosPendientesLocal(){return JSON.parse(JSON.stringify(stored));}
function guardarPedidosPendientes(){stored=JSON.parse(JSON.stringify(_pedidosPendientes));}
function toast(){}
function renderPedidos(){}
function renderCalPed(){}
function cargarPedidos(){}
function mensajeErrorPedido(e){return e.message;}
function esErrorVentaNoReintentable(e){return e.status>=400&&e.status<500&&e.status!==429;}
function api(){requests++;return Promise.reject({status:422,message:'Fecha anterior a hoy'});}
"""


def test_rejected_order_explains_error_and_does_not_loop_forever():
    node(ORDER_HARNESS + function("sincronizarPedidosPendientes") + r"""
(async()=>{
const a=sincronizarPedidosPendientes(false),b=sincronizarPedidosPendientes(false);
assert.equal(a,b);await a;
assert.equal(stored.length,1);
assert.equal(stored[0].requiere_revision,true);
assert.equal(stored[0].ultimo_error,'Fecha anterior a hoy');
await sincronizarPedidosPendientes(false);
assert.equal(requests,1);
})().catch(e=>{console.error(e);process.exitCode=1;});
""")


def test_order_revision_preserves_original_key_and_prior_payload():
    node(ORDER_HARNESS + function("guardarRevisionPedidoLocal") + r"""
(async()=>{
stored[0].requiere_revision=true;stored[0].ultimo_error='Fecha anterior';
const original=JSON.stringify(stored[0].payload), context={id:'key1',original};
await guardarRevisionPedidoLocal({...stored[0].payload,fecha_entrega:'2026-11-11'},context,1,TOKEN);
assert.equal(stored.length,1);
assert.equal(stored[0].payload.idempotency_key,'key1');
assert.equal(stored[0].revisiones[0].payload.fecha_entrega,'2026-11-01');
assert.equal(stored[0].requiere_revision,false);
stored[0].requiere_revision=true;
await assert.rejects(guardarRevisionPedidoLocal({...stored[0].payload},context,1,TOKEN),/otra ventana/);
})().catch(e=>{console.error(e);process.exitCode=1;});
""")


def test_background_order_reply_does_not_overwrite_a_changed_payload():
    node(ORDER_HARNESS + function("sincronizarPedidosPendientes") + r"""
let finish;api=()=>new Promise(resolve=>finish=resolve);
(async()=>{
const syncing=sincronizarPedidosPendientes(true);await Promise.resolve();
stored[0].payload.cliente_nombre='Corregido en otra ventana';
finish({});await syncing;
assert.equal(stored.length,1);
assert.equal(stored[0].payload.cliente_nombre,'Corregido en otra ventana');
})().catch(e=>{console.error(e);process.exitCode=1;});
""")


def test_order_list_and_calendar_render_customer_text_as_text():
    node(r"""
const assert=require('node:assert/strict'), fields={};
const document={getElementById:id=>fields[id]||=( {value:'',style:{},textContent:'',innerHTML:''})};
const row={id:1,folio:'T&1',cliente_nombre:'Pastel <grande> & caja',fecha_entrega:'2026-11-10',estado:'recibido',
  lugar_entrega:'Local <A>',detalles:[{cantidad:1,descripcion:'Pan <chico>'}]};
const _pedCalendario=[row],_pedFiltroEstado='',_pedResumen={hoy:1,manana:0,semana:1};
function pedidosVisibles(){return [row];}
function pedidosPendientesComoCache(){return [];}
function fechaLocalDesdeISO(v){return new Date(v+'T12:00:00');}
function escHtml(v){return String(v).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');}
function jsArg(v){return JSON.stringify(v);}
function fmt(v){return Number(v).toFixed(2);}
""" + function("renderPedidos") + function("renderCalPed") + r"""
renderPedidos();renderCalPed();
assert.ok(fields['ped-list'].innerHTML.includes('Pastel &lt;grande&gt; &amp; caja'));
assert.ok(!fields['ped-list'].innerHTML.includes('Pan <chico>'));
assert.ok(!fields['ped-cal-content'].innerHTML.includes('Pan <chico>'));
assert.equal(fields['ped-sem'].textContent,1);
""")


def test_exports_use_the_server_and_full_applied_filters_not_the_visible_page():
    node(r"""
const assert=require('node:assert/strict');
let _histVentasCargando=false,_histVentasResumen={total:501},_histVentasConsulta='?fecha_inicio=2026-11-01&fecha_fin=2026-11-10&buscar=H-1';
let request;
function descargarArchivoAutenticado(...args){request=args;return Promise.resolve();}
function toast(){}
""" + function("exportarHistVentasCSV") + r"""
exportarHistVentasCSV();
assert.equal(request[0],'/api/v1/punto-de-venta/ventas/historial/csv'+_histVentasConsulta);
assert.ok(!request[0].includes('pagina='));
""")
