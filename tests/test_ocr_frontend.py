"""Execute the existing OCR UI with fictional data, never a real financial API."""

from pathlib import Path
import shutil
import subprocess

import pytest

HTML = Path("docs/index.html").read_text(encoding="utf-8")


def section(start, end):
    offset = HTML.index(start)
    return HTML[offset:HTML.index(end, offset)]


def node(code):
    runtime = shutil.which("node")
    if not runtime:
        pytest.skip("Node needed for OCR UI execution")
    result = subprocess.run([runtime, "-e", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


PREAMBLE = r"""
const assert = require('node:assert/strict');
const fields={};
const document={getElementById:id=>fields[id] ||= {value:'',checked:false,textContent:'',innerHTML:'',disabled:false,style:{},
  querySelectorAll(){return []}},addEventListener(){}};
const window={};
let _versionSesion=1;
const messages=[];
function toast(msg){messages.push(msg);}
function fmt(n){return Number(n).toFixed(2);}
function escHtml(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function normalizarBusquedaProductoTicket(v){return v.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,'');}
function cargarIngredientes(){}function cargarAlertasEmpaques(){}
function cargarEgresos(){}function cargarResumenEgresosApi(){}function cargarResguardo(){}function cargarProveedoresEgresos(){}function cargarGastos(){}function cargarGastosFijosEgresos(){}
function fechaHoyISO(){return '2026-10-08';}
function confirmarAccion(){return Promise.resolve(true);}
let _egOcrResultados=[],_egOcrSeleccionado=-1,_egOcrProcesando=false,_egOcrSeq=0;
let _egresoGuardando=false,_egresoCapturaPendiente=null,_egresoOrigen='manual',_egresoOcrPayload=null;
const requests=[];
function api(method,path,body){return new Promise((resolve,reject)=>requests.push({method,path,body,resolve,reject}));}
function nuevaClaveIdempotencia(){return 'ocr-prueba-key';}
const expense=(provider,amount,date='2026-10-07')=>({ocr:{proveedor:provider,total:amount,fecha:date,moneda:'MXN',
  items:[{nombre:'Bolsa',cantidad:2,unidad:'pz',total:amount}],advertencias:[]},_archivo:provider+'.jpg',
  suggested_egreso:{concepto:'Ticket '+provider,proveedor:provider,monto:amount,fecha:date,categoria:'empaque',metodo_pago:'transferencia'}});
"""

COMMON = section("async function _procesarLoteOCR", "function escanearTicket()")
TOTALS = section("function _renderOCRTotales", "function mostrarResultadoOCR(data)")
EXPENSES = section("function _llenarEgresoDesdeSugerencias", "function escanearTicketEgreso(input)")
SUMMARY = section("function _resumenItemsOCR", "function _categoriaDesdeTicketOCR")


def test_batch_runs_sequentially_handles_partial_errors_and_duplicates():
    code = PREAMBLE + COMMON + r"""
async function run(){
  let active=0,maxActive=0,calls=0,progress=[];
  const result=await _procesarLoteOCR([{name:'A'},{name:'B'},{name:'C'},{name:'D'}],async file=>{
    calls++;active++;maxActive=Math.max(maxActive,active);
    await new Promise(resolve=>setTimeout(resolve,2));active--;
    if(file.name==='B') throw Error('Sin conexion');
    return {documento_id:file.name==='D'?'A':file.name,items:[]};
  },(n,total)=>progress.push([n,total]),()=>true);
  assert.equal(maxActive,1);assert.equal(calls,4);
  assert.ok(result[1].error.includes('Sin conexion'));
  assert.ok(result[3].error.includes('duplicado'));
  assert.equal(result.filter(r=>!r.error).length,2);
  assert.deepEqual(progress,[[1,4],[2,4],[3,4],[4,4]]);
  calls=0;
  const huge=await _procesarLoteOCR([{name:'huge',size:20000001}],()=>{calls++;},()=>{},()=>true);
  assert.ok(huge[0].error.includes('20 MB'));assert.equal(calls,0);
  await assert.rejects(_procesarLoteOCR(new Array(11).fill({}),()=>{},()=>{},()=>true),/10 archivos/);
  let vigente=true;
  const stale=await _procesarLoteOCR([{name:'A'},{name:'B'}],async()=>{vigente=false;return {items:[]};},()=>{},()=>vigente);
  assert.deepEqual(stale,[]);
}
run().catch(e=>{console.error(e);process.exit(1)});
"""
    node(code)


def test_duplicate_bytes_are_skipped_before_external_read():
    code = PREAMBLE + COMMON + r"""
window.crypto=require('node:crypto').webcrypto;
async function run(){
  let calls=0;
  const file=name=>({name,arrayBuffer:async()=>new Uint8Array([1,2,3]).buffer});
  const result=await _procesarLoteOCR([file('one'),file('renamed')],async()=>{calls++;return {items:[]};},()=>{},()=>true);
  assert.equal(calls,1);assert.ok(result[1].error.includes('duplicado'));
}
run().catch(e=>{console.error(e);process.exit(1)});
"""
    node(code)


def test_expenses_are_separate_dates_payments_and_unknown_values_reset():
    code = PREAMBLE + COMMON + TOTALS + SUMMARY + EXPENSES + r"""
mostrarTicketsEgresoOCR([expense('<Proveedor A>',100),expense('Proveedor B',80,'2026-10-06')]);
assert.equal(fields['eg-monto'].value,'100.00');
assert.equal(fields['eg-proveedor'].value,'<Proveedor A>');
assert.equal(fields['eg-fecha'].value,'2026-10-07');
assert.equal(_egresoOcrPayload.length,1);
assert.ok(!fields['eg-ocr-result'].innerHTML.includes('<Proveedor A>'));
seleccionarEgresoOCR('1');
assert.equal(fields['eg-monto'].value,'80.00');assert.equal(fields['eg-fecha'].value,'2026-10-06');
assert.ok(!fields['eg-ocr-detalle'].innerHTML.includes('checked'));
const unknown=expense('Desconocido',null);unknown.suggested_egreso.fecha=null;unknown.suggested_egreso.metodo_pago=null;
mostrarTicketsEgresoOCR([unknown]);
assert.equal(fields['eg-monto'].value,'');assert.equal(fields['eg-fecha'].value,'');assert.equal(fields['eg-metodo'].value,'');
assert.ok(fields['eg-ocr-detalle'].innerHTML.includes('--'));
assert.ok(_resumenItemsOCR([{nombre:'Sin leer'}]).includes('? ? Sin leer (--'));
const long=expense('Largo',100);long.ocr.items=Array.from({length:12},(_,i)=>({nombre:'Partida '+i,total:10}));
mostrarTicketsEgresoOCR([long]);
assert.ok(fields['eg-ocr-detalle'].innerHTML.includes('Partida 11'));
fields['eg-monto'].value='333';mostrarTicketsEgresoOCR([expense('Nuevo',100)],false);
assert.equal(fields['eg-monto'].value,'333');assert.equal(_egOcrSeleccionado,-1);
"""
    node(code)


def test_reopening_expenses_preserves_unknown_ocr_date_and_reading_guard():
    code = PREAMBLE + section("function initEgresos()", "function cargarResguardo()") + r"""
_egresoOrigen='ocr';_egOcrProcesando=true;fields['eg-fecha']={value:''};
initEgresos();assert.equal(fields['eg-fecha'].value,'');assert.equal(fields['eg-guardar'].disabled,true);
_egresoOrigen='manual';_egOcrProcesando=false;
initEgresos();assert.equal(fields['eg-fecha'].value,'2026-10-08');assert.equal(fields['eg-guardar'].disabled,false);
"""
    node(code)


def test_session_reset_discards_receipt_fields_payload_and_review_view():
    code = PREAMBLE + section("function limpiarEgresoForm", "function datosFormularioEgreso")
    code += r"""
let _resguardoData=null,_resguardoIniciando=false,_resguardoSeq=0,_egresosResumenSeq=0;
let _ocrSeq=0,_ocrItems=[{nombre:'Dato anterior'}],_ocrGuardando=true;
function cerrarCamaraEgreso(){}
"""
    code += section("function invalidarTareasSesion()", "  _contaCuentas = [];") + "}\n"
    code += r"""
_egresoOrigen='ocr';_egresoOcrPayload=[{proveedor:'Anterior'}];_egOcrResultados=[expense('Anterior',100)];
['eg-concepto','eg-monto','eg-proveedor','eg-notas'].forEach(id=>document.getElementById(id).value='Anterior');
fields['eg-ocr-result']={innerHTML:'Anterior',style:{display:'block'}};
invalidarTareasSesion();
assert.equal(_egresoOrigen,'manual');assert.equal(_egresoOcrPayload,null);assert.deepEqual(_egOcrResultados,[]);
['eg-concepto','eg-monto','eg-proveedor','eg-notas'].forEach(id=>assert.equal(fields[id].value,''));
assert.equal(fields['eg-ocr-result'].innerHTML,'');assert.equal(fields['eg-ocr-result'].style.display,'none');
assert.deepEqual(_ocrItems,[]);assert.equal(fields['ocr-result'].style.display,'none');
"""
    node(code)


def test_user_edits_during_read_and_expired_session_are_not_overwritten():
    code = PREAMBLE + COMMON + TOTALS + SUMMARY + EXPENSES
    code += section("function _firmaFormularioEgresoOCR", "function renderResumenEgresosOperativos")
    code += r"""
let resolveOCR;function _enviarOCREgreso(){return new Promise(resolve=>resolveOCR=resolve);}
async function run(){
  const reading=procesarFotosEgreso([{name:'fake.jpg'}]);
  assert.equal(fields['eg-guardar'].disabled,true);
  fields['eg-monto'].value='42';resolveOCR(expense('Proveedor',100));await reading;
  assert.equal(fields['eg-monto'].value,'42');assert.equal(_egOcrSeleccionado,-1);
  assert.equal(fields['eg-guardar'].disabled,false);
  fields['eg-monto'].value='';_egOcrResultados=[];
  const stale=procesarFotosEgreso([{name:'other.jpg'}]);_versionSesion++;
  resolveOCR(expense('STALE',999));await stale;
  assert.notEqual(fields['eg-proveedor'].value,'STALE');
}
run().catch(e=>{console.error(e);process.exit(1)});
"""
    node(code)


def test_expense_review_double_click_retry_identity_and_next_ticket():
    code = PREAMBLE + COMMON + TOTALS + SUMMARY + EXPENSES
    code += section("function limpiarEgresoForm", "function datosFormularioEgreso")
    code += section("function guardarEgreso()", "function cargarEgresos()")
    code += r"""
function datosFormularioEgreso(){return {concepto:fields['eg-concepto'].value,monto:Number(fields['eg-monto'].value),metodo_pago:fields['eg-metodo'].value};}
async function run(){
  mostrarTicketsEgresoOCR([expense('A',100),expense('B',80)]);
  guardarEgreso();assert.equal(requests.length,0);assert.ok(messages.pop().includes('revisados'));
  fields['eg-ocr-revisado'].checked=true;
  let p=guardarEgreso();guardarEgreso();assert.equal(requests.length,1);
  seleccionarEgresoOCR(1);assert.equal(_egOcrSeleccionado,0);
  requests[0].reject(Error('Respuesta desconocida'));await p;
  p=guardarEgreso();assert.equal(requests[0].body.idempotency_key,requests[1].body.idempotency_key);
  assert.equal(requests[1].body.ocr_payload.tickets.length,1);
  requests[1].resolve({id:1});await p;
  assert.equal(_egOcrResultados.length,1);assert.equal(fields['eg-proveedor'].value,'B');
  assert.equal(fields['eg-monto'].value,'80.00');assert.equal(_egresoCapturaPendiente,null);
}
run().catch(e=>{console.error(e);process.exit(1)});
"""
    node(code)


def test_inventory_converts_units_uses_unit_cost_preserves_supplier_and_no_double_save():
    code = PREAMBLE + "let _ocrItems=[],_ocrSeq=0,_ocrGuardando=false,_allIngs=[{id:1,nombre:'Harina',unidad_medida:'kg'}];\n"
    code += section("function _cantidadInventarioOCR", "function hornear()")
    code += r"""
async function run(){
  assert.equal(_cantidadInventarioOCR(500,'g','kg'),.5);
  assert.equal(_cantidadInventarioOCR(2,'l','ml'),2000);
  assert.equal(_cantidadInventarioOCR(2,'pz','kg'),null);
  _ocrItems=[{_proveedor:'Proveedor A'},{_proveedor:'Proveedor B'}];
  [0,1].forEach(i=>{fields['ocr-chk-'+i]={checked:true};fields['ocr-ing-'+i]={value:'1'};
    fields['ocr-cantidad-'+i]={value:'500'};fields['ocr-unidad-'+i]={value:'g'};fields['ocr-total-'+i]={value:'25'};});
  _ocrItems[0]._moneda='USD';await registrarTodoOCR();assert.equal(requests.length,0);
  assert.ok(messages.pop().includes('importe en pesos'));_ocrItems[0]._moneda='MXN';
  let p=registrarTodoOCR();registrarTodoOCR();await Promise.resolve();assert.equal(requests.length,1);
  assert.ok(requests[0].path.includes('cantidad=0.5&costo=50.0000'));
  assert.ok(requests[0].path.includes('Proveedor%20A'));
  requests[0].resolve({});await new Promise(resolve=>setTimeout(resolve,0));
  assert.ok(requests[1].path.includes('Proveedor%20B'));
  requests[1].reject(Error('Conexion perdida'));await p;
  assert.equal(_ocrItems[0]._registrado,true);assert.equal(_ocrItems[1]._incierto,true);
  await registrarTodoOCR();assert.equal(requests.length,2);
  assert.ok(messages.pop().includes('sin confirmar'));
}
run().catch(e=>{console.error(e);process.exit(1)});
"""
    node(code)


def test_inventory_totals_do_not_sum_missing_values_or_different_currencies():
    code = PREAMBLE + COMMON + TOTALS + "let _ocrItems=[];\n"
    code += section("function mostrarResultadoOCRMulti", "function matchIngrediente")
    code += r"""
function _renderOCRItem(){return '';}
mostrarResultadoOCRMulti([{proveedor:'A',total:100,moneda:'MXN',items:[]},{proveedor:'B',total:null,moneda:'MXN',items:[]}]);
assert.ok(fields['ocr-items'].innerHTML.includes('Total general (2 tickets)</span><span>--'));
mostrarResultadoOCRMulti([{proveedor:'A',total:100,moneda:'MXN',items:[]},{proveedor:'B',total:50,moneda:'USD',items:[]}]);
assert.ok(fields['ocr-items'].innerHTML.includes('Total general (2 tickets)</span><span>--'));
mostrarResultadoOCRMulti([{proveedor:'A',total:100,moneda:'MXN',items:[]},{proveedor:'B',total:50,moneda:'MXN',items:[]}]);
assert.ok(fields['ocr-items'].innerHTML.includes('Total general (2 tickets)</span><span>$150.00'));
"""
    node(code)


def test_inventory_package_units_are_selectable_and_register_without_assumed_contents():
    code = PREAMBLE + COMMON + "let _ocrItems=[],_ocrSeq=0,_ocrGuardando=false,_allIngs=[];\n"
    code += section("function _renderOCRItem", "function _renderOCRTotales")
    code += section("function matchIngrediente", "async function crearIngDesdeOCR")
    code += section("function _cantidadInventarioOCR", "function hornear()")
    code += r"""
async function run(){
  const unidades=['kg','g','l','ml','pz','caja','bolsa','saco'];
  const row=_renderOCRItem({nombre:'Compra',cantidad:3,unidad:'saco',total:300},0);
  unidades.forEach(u=>{
    assert.ok(row.includes('<option value="'+u+'"'));
    assert.equal(_cantidadInventarioOCR(3,u,u),3);
  });
  assert.ok(row.includes('<option value="saco" selected>'));
  const empaques=['caja','bolsa','saco'];
  for(let i=0;i<empaques.length;i++){
    const u=empaques[i];
    unidades.filter(v=>v!==u).forEach(v=>assert.equal(_cantidadInventarioOCR(3,u,v),null));
    _ocrItems=[{_proveedor:'Proveedor prueba',_moneda:'MXN'}];
    _allIngs=[{id:1,nombre:'Compra',unidad_medida:u}];
    fields['ocr-chk-0']={checked:true};fields['ocr-ing-0']={value:'1'};
    fields['ocr-cantidad-0']={value:'3'};fields['ocr-unidad-0']={value:u};fields['ocr-total-0']={value:'300'};
    const p=registrarTodoOCR();await Promise.resolve();assert.equal(requests.length,i+1);
    assert.ok(requests[i].path.includes('cantidad=3&costo=100.0000'));
    requests[i].resolve({});await p;
    assert.equal(_ocrItems[0]._registrado,true);
  }
}
run().catch(e=>{console.error(e);process.exit(1)});
"""
    node(code)


def test_inventory_labels_are_escaped_no_loose_matching_or_default_quantity():
    code = PREAMBLE + COMMON + "let _allIngs=[{id:1,nombre:'Harina',unidad_medida:'kg'}];\n"
    code += section("function _renderOCRItem", "function _renderOCRTotales")
    code += section("function matchIngrediente", "async function crearIngDesdeOCR")
    code += r"""
assert.equal(matchIngrediente('Harina extra con azucar'),null);
assert.equal(matchIngrediente('HARINA'),1);
let row=_renderOCRItem({nombre:'<img src=x onerror=alert(1)>',cantidad:null,total:null,unidad:null},0);
assert.ok(!row.includes('<img'));assert.ok(!row.includes('checked'));
assert.ok(row.includes('id="ocr-cantidad-0" min="0.0001" step="0.0001" value=""'));
assert.ok(row.includes('crearIngDesdeOCR(0)'));
assert.ok(_advertenciasOCR({advertencias:['<script>evil</script>']}).includes('&lt;script&gt;'));
"""
    node(code)
