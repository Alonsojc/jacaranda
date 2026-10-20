// Excel: vista previa firmada, seleccion explicita y reintentos sin duplicar.
var _egImport = null;
var _egImportSeq = 0;
var _egImportCampos = ['fecha','proveedor','monto','metodo_pago','concepto','categoria','notas'];
var _egImportEtiquetas = ['Fecha','Proveedor / persona','Monto','Forma de pago','Concepto','Categoría','Notas'];

function abrirImportacionEgresos() {
  if ((window._permisos || {}).egresos !== 'editar') return;
  if (!_egImport || _egImport.version !== _versionSesion) {
    _egImport = {version:_versionSesion, archivo:null, vista:null, seleccion:{}, pendiente:null, ocupado:false};
    document.getElementById('eg-import-file').value = '';
    document.getElementById('eg-import-config').hidden = true;
    document.getElementById('eg-import-tabla').innerHTML = '';
    document.getElementById('eg-import-estado').textContent = 'Sin archivo';
    document.getElementById('eg-import-categoria').innerHTML = document.getElementById('eg-categoria').innerHTML;
    document.getElementById('eg-import-categoria').value = document.getElementById('eg-categoria').value || 'operativo';
    document.getElementById('eg-import-proveedores').checked = true;
    document.getElementById('eg-import-columnas').innerHTML = _egImportCampos.map(function(campo,i) {
      return '<div class="fg"><label for="eg-import-col-' + campo + '">' + _egImportEtiquetas[i] + '</label><select id="eg-import-col-' + campo + '" onchange="invalidarVistaExcelEgresos()"></select></div>';
    }).join('');
  }
  document.getElementById('modal-egresos-importar').classList.add('on');
  actualizarSeleccionExcelEgresos();
}

function cerrarImportacionEgresos(limpiar) {
  if (_egImport && _egImport.ocupado && !limpiar) return;
  ++_egImportSeq;
  document.getElementById('modal-egresos-importar').classList.remove('on');
  if (limpiar) {
    _egImport = null;
    document.getElementById('eg-import-file').value = '';
    document.getElementById('eg-import-tabla').innerHTML = '';
    document.getElementById('eg-import-estado').textContent = '';
  }
}

function invalidarVistaExcelEgresos() {
  if (!_egImport || _egImport.pendiente || _egImport.ocupado) return;
  ++_egImportSeq;
  _egImport.vista = null;
  _egImport.seleccion = {};
  document.getElementById('eg-import-tabla').innerHTML = '';
  document.getElementById('eg-import-estado').textContent = 'Vista previa pendiente';
  actualizarSeleccionExcelEgresos();
}

function opcionesExcelEgresos(reiniciar) {
  var opciones = {categoria:document.getElementById('eg-import-categoria').value,
    guardar_proveedor:document.getElementById('eg-import-proveedores').checked};
  if (document.getElementById('eg-import-config').hidden) return opciones;
  opciones.hoja = document.getElementById('eg-import-hoja').value;
  if (!reiniciar) {
    opciones.fila_encabezado = document.getElementById('eg-import-sin-header').checked ? 0 : Number(document.getElementById('eg-import-header').value);
    opciones.formato_fecha = document.getElementById('eg-import-formato-fecha').value;
    opciones.columnas = {};
    _egImportCampos.forEach(function(campo) {
      var valor = document.getElementById('eg-import-col-' + campo).value;
      opciones.columnas[campo] = valor ? Number(valor) : null;
    });
  }
  return opciones;
}

function cambiarArchivoExcelEgresos(input) {
  if (!_egImport || _egImport.ocupado || _egImport.pendiente) return;
  var archivo = input.files && input.files[0];
  invalidarVistaExcelEgresos();
  _egImport.archivo = null;
  document.getElementById('eg-import-config').hidden = true;
  if (!archivo) return actualizarSeleccionExcelEgresos();
  if (!/\.xlsx$/i.test(archivo.name) || archivo.size > 5 * 1024 * 1024) {
    document.getElementById('eg-import-estado').textContent = 'Selecciona un Excel .xlsx de hasta 5 MB; una foto no es un archivo Excel.';
    input.value = '';
    return actualizarSeleccionExcelEgresos();
  }
  _egImport.archivo = archivo;
  return leerExcelEgresos(true);
}

async function leerExcelEgresos(reiniciar) {
  var estado = _egImport;
  if (!estado || !estado.archivo || estado.ocupado || estado.pendiente) return;
  var opciones = opcionesExcelEgresos(!!reiniciar), seq = ++_egImportSeq;
  estado.ocupado = true;
  estado.vista = null;
  estado.seleccion = {};
  document.getElementById('eg-import-tabla').innerHTML = '';
  document.getElementById('eg-import-estado').textContent = 'Leyendo Excel...';
  actualizarSeleccionExcelEgresos();
  var controller = window.AbortController ? new AbortController() : null;
  var timer = controller ? setTimeout(function() { controller.abort(); }, 60000) : null;
  try {
    var form = new FormData();
    form.append('archivo', estado.archivo);
    form.append('opciones', JSON.stringify(opciones));
    var response;
    for (var intento = 0; intento < 2; intento++) {
      response = await fetch(API_URL + '/api/v1/egresos/importacion/previsualizar', {
        method:'POST', cache:'no-store', body:form, headers:TOKEN ? {Authorization:'Bearer ' + TOKEN} : {},
        signal:controller ? controller.signal : undefined
      });
      if (estado !== _egImport || estado.version !== _versionSesion || seq !== _egImportSeq) return;
      if (response.status !== 401 || intento || !REFRESH_TOKEN) break;
      await refreshAccessToken();
      if (estado !== _egImport || estado.version !== _versionSesion || seq !== _egImportSeq) return;
    }
    var data = await leerRespuestaJson(response);
    if (estado !== _egImport || estado.version !== _versionSesion || seq !== _egImportSeq) return;
    if (!response.ok) {
      if (response.status === 401) expirarSesion();
      throw new Error(typeof data.detail === 'string' ? data.detail : 'No se pudo leer el Excel');
    }
    if (!Array.isArray(data.filas) || !Array.isArray(data.hojas)) throw new Error('Vista previa incompleta');
    estado.vista = data;
    data.filas.forEach(function(f) { if (f.estado === 'lista') estado.seleccion[f.fila] = true; });
    document.getElementById('eg-import-config').hidden = false;
    document.getElementById('eg-import-mapeo').open = data.faltantes.length > 0;
    document.getElementById('eg-import-hoja').innerHTML = data.hojas.map(function(h) {
      return '<option value="' + escHtml(h) + '">' + escHtml(h) + '</option>';
    }).join('');
    document.getElementById('eg-import-hoja').value = data.hoja;
    document.getElementById('eg-import-header').value = data.fila_encabezado || 1;
    document.getElementById('eg-import-sin-header').checked = data.fila_encabezado === 0;
    document.getElementById('eg-import-formato-fecha').value = opciones.formato_fecha || 'dia_mes_anio';
    _egImportCampos.forEach(function(campo) {
      var select = document.getElementById('eg-import-col-' + campo);
      select.innerHTML = '<option value="">Sin columna</option>' + data.opciones_columnas.map(function(c) {
        return '<option value="' + c.indice + '">' + escHtml(c.nombre) + '</option>';
      }).join('');
      select.value = data.columnas[campo] || '';
    });
    renderVistaExcelEgresos(data);
  } catch (e) {
    if (estado === _egImport && estado.version === _versionSesion && seq === _egImportSeq) {
      document.getElementById('eg-import-estado').textContent = e.name === 'AbortError' ? 'La lectura tardo demasiado; no se guardaron gastos.' : (e.message || 'No se pudo leer el Excel');
    }
  } finally {
    if (timer) clearTimeout(timer);
    if (estado === _egImport && estado.version === _versionSesion && seq === _egImportSeq) {
      estado.ocupado = false;
      actualizarSeleccionExcelEgresos();
    }
  }
}

function renderVistaExcelEgresos(data) {
  var etiquetas = {lista:'Lista',duplicado:'Posible duplicado',error:'Revisar',omitida:'Total excluido',registrada:'Ya importada'};
  var conteos = {};
  var h = '<table class="tbl eg-import-table"><colgroup><col style="width:44px"><col style="width:48px"><col style="width:110px"><col style="width:220px"><col style="width:120px"><col style="width:125px"><col style="width:105px"><col style="width:200px"></colgroup><thead><tr><th><input type="checkbox" id="eg-import-todas" aria-label="Seleccionar filas sin alertas" onchange="seleccionarFilasExcelEgresos(this.checked)"></th><th>Fila</th><th>Fecha</th><th>Proveedor / concepto</th><th>Monto MXN</th><th>Pago</th><th>Categoría</th><th>Estado</th></tr></thead><tbody>';
  data.filas.forEach(function(f) {
    conteos[f.estado] = (conteos[f.estado] || 0) + 1;
    var d = f.datos || {}, raw = f.original || {}, elegible = f.estado === 'lista' || f.estado === 'duplicado';
    h += '<tr><td><input type="checkbox" data-eg-import-fila="' + f.fila + '" aria-label="Importar fila ' + f.fila + '" ' + (elegible ? '' : 'disabled ') + (_egImport.seleccion[f.fila] ? 'checked ' : '') + 'onchange="cambiarSeleccionExcelEgresos(' + f.fila + ',this.checked)"></td>';
    h += '<td>' + f.fila + '</td><td class="eg-import-nowrap">' + escHtml(d.fecha || raw.fecha || '--') + '</td>';
    h += '<td class="eg-import-descripcion"><strong>' + escHtml(d.proveedor || raw.proveedor || '--') + '</strong>';
    if (d.concepto && d.concepto !== d.proveedor) h += '<div>' + escHtml(d.concepto) + '</div>';
    if (d.notas) h += '<div class="eg-import-nota">' + escHtml(d.notas) + '</div>';
    h += '</td><td class="eg-import-nowrap">' + (d.monto ? '$' + fmt(d.monto) : escHtml(raw.monto || '--')) + '</td>';
    h += '<td>' + escHtml(d.metodo_pago || raw.metodo_pago || '--') + '</td><td>' + escHtml(d.categoria || '--') + '</td>';
    h += '<td><span class="eg-import-badge eg-import-' + f.estado + '">' + etiquetas[f.estado] + '</span>';
    if (f.errores && f.errores.length) h += '<div class="eg-import-nota">' + f.errores.map(escHtml).join('; ') + '</div>';
    h += '</td></tr>';
  });
  document.getElementById('eg-import-tabla').innerHTML = h + '</tbody></table>';
  document.getElementById('eg-import-estado').textContent = data.faltantes.length ? 'Faltan columnas: ' + data.faltantes.join(', ') :
    (conteos.lista || 0) + ' listas; ' + (conteos.duplicado || 0) + ' posibles duplicados; ' + (conteos.error || 0) + ' por revisar; ' + (conteos.registrada || 0) + ' ya importadas; ' + (conteos.omitida || 0) + ' totales excluidos. Sin guardar.';
}

function cambiarSeleccionExcelEgresos(fila, incluir) {
  if (!_egImport || !_egImport.vista || _egImport.ocupado || _egImport.pendiente) return;
  var dato = _egImport.vista.filas.find(function(f) { return f.fila === fila; });
  if (!dato || ['lista','duplicado'].indexOf(dato.estado) < 0) return;
  if (incluir) _egImport.seleccion[fila] = true;
  else delete _egImport.seleccion[fila];
  actualizarSeleccionExcelEgresos();
}

function seleccionarFilasExcelEgresos(incluir) {
  if (!_egImport || !_egImport.vista || _egImport.ocupado || _egImport.pendiente) return;
  _egImport.vista.filas.forEach(function(f) {
    if (f.estado === 'lista') {
      if (incluir) _egImport.seleccion[f.fila] = true;
      else delete _egImport.seleccion[f.fila];
    }
  });
  actualizarSeleccionExcelEgresos();
}

function seleccionExcelEgresos() {
  var filas = _egImport && _egImport.vista ? _egImport.vista.filas.filter(function(f) { return _egImport.seleccion[f.fila]; }) : [];
  return {filas:filas.map(function(f) { return f.fila; }), incluir_duplicados:filas.filter(function(f) { return f.estado === 'duplicado'; }).map(function(f) { return f.fila; }),
    centavos:filas.reduce(function(total,f) { return total + Math.round(Number(f.datos.monto) * 100); },0)};
}

function actualizarSeleccionExcelEgresos() {
  if (!_egImport) return;
  var seleccion = seleccionExcelEgresos(), bloqueado = _egImport.ocupado || !!_egImport.pendiente;
  document.querySelectorAll('#eg-import-config input,#eg-import-config select,#eg-import-columnas select,#eg-import-file').forEach(function(el) { el.disabled = bloqueado; });
  document.getElementById('eg-import-header').disabled = bloqueado || document.getElementById('eg-import-sin-header').checked;
  document.getElementById('eg-import-proveedores').disabled = bloqueado;
  document.getElementById('eg-import-categoria').disabled = bloqueado;
  document.querySelectorAll('[data-eg-import-fila]').forEach(function(el) {
    var fila = Number(el.getAttribute('data-eg-import-fila'));
    var datos = _egImport.vista && _egImport.vista.filas.find(function(f) { return f.fila === fila; });
    el.disabled = bloqueado || !datos || ['lista','duplicado'].indexOf(datos.estado) < 0;
    el.checked = !!_egImport.seleccion[fila];
  });
  var todas = document.getElementById('eg-import-todas');
  if (todas) {
    var listas = _egImport.vista.filas.filter(function(f) { return f.estado === 'lista'; });
    var elegidas = listas.filter(function(f) { return _egImport.seleccion[f.fila]; }).length;
    todas.disabled = bloqueado || !listas.length;
    todas.checked = listas.length > 0 && elegidas === listas.length;
    todas.indeterminate = elegidas > 0 && elegidas < listas.length;
  }
  document.getElementById('eg-import-revisar').disabled = bloqueado || !_egImport.archivo;
  document.getElementById('eg-import-cerrar').disabled = _egImport.ocupado;
  document.getElementById('eg-import-total').textContent = seleccion.filas.length + ' seleccionados · $' + fmt(seleccion.centavos / 100) + ' MXN';
  var button = document.getElementById('eg-import-confirmar');
  button.disabled = _egImport.ocupado || !_egImport.vista || !_egImport.vista.token || !seleccion.filas.length;
  button.textContent = _egImport.pendiente ? 'Reintentar confirmación' : 'Importar ' + seleccion.filas.length + ' gastos';
}

async function confirmarExcelEgresos() {
  var estado = _egImport;
  if (!estado || estado.ocupado || !estado.vista || !estado.vista.token) return;
  var seleccion = seleccionExcelEgresos();
  if (!seleccion.filas.length) return;
  estado.ocupado = true;
  actualizarSeleccionExcelEgresos();
  try {
    if (!estado.pendiente) {
      var ok = await confirmarAccion({title:'Importar gastos',message:seleccion.filas.length + ' gastos por $' + fmt(seleccion.centavos / 100) + ' MXN',
        detail:seleccion.incluir_duplicados.length ? 'Incluye ' + seleccion.incluir_duplicados.length + ' posibles duplicados seleccionados expresamente.' : 'Archivo: ' + estado.vista.archivo + ' / ' + estado.vista.hoja,
        acceptText:'Importar gastos'});
      if (!ok || estado !== _egImport || estado.version !== _versionSesion) return;
      estado.pendiente = {token:estado.vista.token,filas:seleccion.filas,incluir_duplicados:seleccion.incluir_duplicados};
    }
    document.getElementById('eg-import-estado').textContent = 'Confirmando importación...';
    var resultado = await api('POST','/egresos/importacion/confirmar',estado.pendiente,false,null,estado.version,{timeoutMs:60000,silenciosa:true});
    if (estado !== _egImport || estado.version !== _versionSesion) return;
    estado.pendiente = null;
    estado.vista = null;
    estado.seleccion = {};
    document.getElementById('eg-import-tabla').innerHTML = '';
    document.getElementById('eg-import-estado').textContent = resultado.importados + ' gastos importados por $' + fmt(resultado.monto_importado) + ' MXN. ' + resultado.ya_registrados + ' ya registrados.' + (resultado.anulados ? ' ' + resultado.anulados + ' están anulados.' : '');
    toast('Importación confirmada');
    cargarEgresos();cargarResumenEgresosApi();cargarResguardo();cargarProveedoresEgresos();
    cargarGastos(document.getElementById('c-fecha') ? document.getElementById('c-fecha').value : null);
  } catch (e) {
    if (estado !== _egImport || estado.version !== _versionSesion) return;
    if (e.status >= 400 && e.status < 500) estado.pendiente = null;
    document.getElementById('eg-import-estado').textContent = estado.pendiente ?
      'La confirmación no llegó. Reintenta la misma importación; no selecciones otro archivo. ' + (e.message || '') : (e.message || 'No se pudo confirmar la importación');
  } finally {
    if (estado === _egImport && estado.version === _versionSesion) {
      estado.ocupado = false;
      actualizarSeleccionExcelEgresos();
    }
  }
}
