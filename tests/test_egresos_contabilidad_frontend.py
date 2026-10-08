"""Execute the real frontend helpers with fictional data and fake camera streams."""

from pathlib import Path
import shutil
import subprocess

import pytest

HTML = Path("docs/index.html").read_text(encoding="utf-8")


def _section(start, end):
    offset = HTML.index(start)
    return HTML[offset:HTML.index(end, offset)]


def _node(code):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node needed for frontend execution")
    result = subprocess.run([node, "-e", code], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


PREAMBLE = r"""
const assert = require('node:assert/strict');
const fields = {};
const options = [{disabled:true},{disabled:true}];
const document = {getElementById:id=>fields[id] ||= {
  value:'', innerHTML:'old', textContent:'old', style:{}, hidden:false, disabled:false,
  classList:{add(){},remove(){}}
},querySelectorAll:()=>options,addEventListener(){}};
let _versionSesion = 1;
function fmt(n){return Number(n).toFixed(2);}
function escHtml(s){return String(s).replace(/</g,'&lt;');}
function etiquetaReporteEgreso(s){return s;}
const toasts=[];
function toast(m){toasts.push(m);}
const requests=[];
function api(method,path,body){return new Promise((resolve,reject)=>requests.push({method,path,body,resolve,reject}));}
"""


def test_operational_summary_and_report_do_not_override_each_other():
    assert HTML.count("function renderResumenEgresos(") == 1
    code = PREAMBLE + "let _egresosResumenSeq=0;\n"
    code += _section("function cargarResumenEgresosApi", "function cargarProveedoresEgresos")
    code += _section("function renderResumenEgresosOperativos", "function renderEgresos")
    code += _section("function renderResumenEgresos(grupo)", "function puedeVerReporteEgresos")
    code += r"""
async function run(){
  let pending=cargarResumenEgresosApi();
  requests[0].resolve({hoy:{total:250,cantidad:2},mes_actual:{total:1300},recurrentes:{total_mensual:9000}});
  await pending;
  assert.equal(fields['eg-kpi-hoy'].textContent,'$250.00');
  assert.equal(fields['eg-kpi-mes'].textContent,'$1300.00');
  assert.ok(fields['eg-resumen'].innerHTML.includes('Movimientos hoy'));
  assert.ok(renderResumenEgresos({gas:{total:120,cantidad:1}}).includes('$120.00'));
  pending=cargarResumenEgresosApi();requests[1].reject(new Error('sin conexion'));await pending;
  assert.equal(fields['eg-kpi-hoy'].textContent,'--');
  assert.ok(fields['eg-resumen'].innerHTML.includes('sin conexion'));
  pending=cargarResumenEgresosApi();_versionSesion++;
  requests[2].resolve({hoy:{total:999}});await pending;
  assert.equal(fields['eg-kpi-hoy'].textContent,'--');
}
run().catch(e=>{console.error(e);process.exit(1)});
"""
    _node(code)


def test_resguardo_failures_do_not_show_zero_or_enable_payment():
    code = PREAMBLE + "let _resguardoSeq=0,_resguardoData=null;\n"
    code += _section("function cargarResguardo", "async function iniciarResguardo")
    code += r"""
async function run(){
  let p=cargarResguardo();requests[0].resolve({configurado:true,saldo:60,saldo_inicial:0,entradas:100,salidas:40,iniciado_en:'2026-10-08',movimientos:[]});await p;
  assert.equal(fields['eg-kpi-resguardo'].textContent,'$60.00');
  assert.ok(options.every(o=>!o.disabled));
  p=cargarResguardo();requests[1].reject(new Error('no disponible'));await p;
  assert.equal(fields['eg-kpi-resguardo'].textContent,'--');
  assert.ok(options.every(o=>o.disabled));
  assert.equal(fields['eg-resguardo-historial'].hidden,true);
  p=cargarResguardo();requests[2].resolve({configurado:false});await p;
  assert.ok(fields['eg-resguardo'].innerHTML.includes('value="0"'));
  assert.ok(options.every(o=>o.disabled));
}
run().catch(e=>{console.error(e);process.exit(1)});
"""
    _node(code)


def test_expense_double_click_and_unknown_response_keep_same_retry_key():
    code = PREAMBLE + r"""
let _egresoGuardando=false,_egresoCapturaPendiente=null,_egresoOrigen='manual',_egresoOcrPayload=null;
function datosFormularioEgreso(){return {concepto:'Prueba',monto:40,fecha:'2026-10-08',proveedor:'Proveedor',metodo_pago:'resguardo'};}
let keys=0;function nuevaClaveIdempotencia(){return 'egreso-prueba-'+(++keys);}
function limpiarEgresoForm(){_egresoCapturaPendiente=null;}
function cargarEgresos(){}function cargarResumenEgresosApi(){}function cargarResguardo(){}function cargarProveedoresEgresos(){}function cargarGastos(){}
""" + _section("function guardarEgreso()", "function cargarEgresos()") + r"""
async function run(){
  let p=guardarEgreso();guardarEgreso();assert.equal(requests.length,1);
  requests[0].reject(new Error('servidor tardo'));await p;
  const key=requests[0].body.idempotency_key;
  p=guardarEgreso();assert.equal(requests[1].body.idempotency_key,key);
  assert.equal(keys,1);requests[1].resolve({id:1});await p;
  assert.equal(_egresoCapturaPendiente,null);
  assert.equal(fields['eg-guardar'].disabled,false);
}
run().catch(e=>{console.error(e);process.exit(1)});
"""
    _node(code)


def test_camera_stream_is_stopped_on_close_and_late_permission_response():
    code = PREAMBLE + r"""
let _egCameraState=null,stopped=0,resolveCamera;
const stream={getTracks:()=>[{stop(){stopped++;}}]};
const navigator={mediaDevices:{getUserMedia(opts){assert.equal(opts.audio,false);return new Promise(resolve=>resolveCamera=resolve);}}};
fields['eg-camera-video']={play(){return Promise.resolve();}};
function procesarFotosEgreso(){}
""" + _section("function cerrarCamaraEgreso()", "function procesarFotosEgreso(files)") + r"""
async function run(){
  let p=abrirCamaraEgreso();cerrarCamaraEgreso();resolveCamera(stream);await p;
  assert.equal(stopped,1);assert.equal(fields['eg-camera-video'].srcObject,null);
  p=abrirCamaraEgreso();resolveCamera(stream);await p;
  assert.equal(fields['eg-camera-video'].srcObject,stream);
  fields['eg-camera-video'].onloadedmetadata();assert.equal(fields['eg-camera-capture'].disabled,false);
  cerrarCamaraEgreso();assert.equal(stopped,2);
  p=abrirCamaraEgreso();_versionSesion++;resolveCamera(stream);await p;
  assert.equal(stopped,3);
}
run().catch(e=>{console.error(e);process.exit(1)});
"""
    _node(code)


def test_accounting_latest_period_wins_and_error_is_visible():
    code = PREAMBLE + "let _contaSeq={};function validarFechas(){return true;}\n"
    code += _section("function iniciarConsultaContable", "function contaSetRango")
    code += _section("function cargarEdoResultados", "function cargarBalanceGeneral")
    code += r"""
async function run(){
  fields['conta-er-fi']={value:'2026-09-01'};fields['conta-er-ff']={value:'2026-09-30'};
  let old=cargarEdoResultados();fields['conta-er-fi'].value='2026-10-01';
  let latest=cargarEdoResultados();
  const response={ingresos_netos:600,costo_ventas:100,utilidad_bruta:500,utilidad_neta:400,
    gastos_operacion:{'<bad>':100},total_gastos_operacion:100};
  requests[1].resolve(response);await latest;
  assert.ok(fields['conta-er-content'].innerHTML.includes('$600.00'));
  assert.ok(!fields['conta-er-content'].innerHTML.includes('<bad>'));
  requests[0].resolve({...response,ingresos_netos:999});await old;
  assert.ok(!fields['conta-er-content'].innerHTML.includes('$999.00'));
  let fail=cargarEdoResultados();requests[2].reject(new Error('Conexion perdida'));await fail;
  assert.ok(fields['conta-er-content'].innerHTML.includes('Reintentar'));
  assert.ok(!fields['conta-er-content'].innerHTML.includes('$600.00'));
  let changed=cargarEdoResultados();fields['conta-er-fi'].value='2026-10-02';fields['conta-er-fi'].onchange();
  requests[3].resolve(response);await changed;
  assert.ok(!fields['conta-er-content'].innerHTML.includes('$600.00'));
}
run().catch(e=>{console.error(e);process.exit(1)});
"""
    _node(code)


def test_accounting_account_and_journal_labels_are_escaped():
    code = PREAMBLE + "let _contaSeq={};function validarFechas(){return true;}\n"
    code += _section("function iniciarConsultaContable", "function contaSetRango")
    code += _section("function cargarBalanceGeneral", "function cargarConciliacion")
    code += _section("function cargarLibroDiario", "function seedearCatalogo")
    code += r"""
async function run(){
  let p=cargarBalanceGeneral();requests[0].resolve({activos:[{cuenta:'<activo>',saldo:10}],
    pasivos:[{cuenta:'<pasivo>',saldo:5}],capital:[{cuenta:'<capital>',saldo:5}],fecha_corte:'2026-10-08'});await p;
  assert.ok(!fields['conta-bg-content'].innerHTML.includes('<activo>'));
  assert.ok(!fields['conta-bg-content'].innerHTML.includes('<pasivo>'));
  p=cargarLibroDiario();requests[1].resolve([{numero:'<numero>',fecha:'2026-10-08',tipo:'diario',
    concepto:'<concepto>',lineas:[{cuenta_codigo:'1101',cuenta_nombre:'<cuenta>',debe:10,haber:0}]}]);await p;
  assert.ok(!fields['conta-ld-content'].innerHTML.includes('<concepto>'));
  assert.ok(!fields['conta-ld-content'].innerHTML.includes('<cuenta>'));
  p=cargarCatalogoCuentas();requests[2].resolve({activo:[{codigo:'1101',nombre:'<cuenta>',nivel:3}]});await p;
  assert.ok(!fields['conta-cat-content'].innerHTML.includes('<cuenta>'));
}
run().catch(e=>{console.error(e);process.exit(1)});
"""
    _node(code)
