// Importaciones: vista previa firmada, revision y reintentos sin duplicar.
var _egImport = null;
var _egImportSeq = 0;
var _egImportCampos = ['fecha','proveedor','monto','metodo_pago','concepto','categoria','notas'];
var _egImportEtiquetas = ['Fecha','Proveedor / persona','Monto','Forma de pago','Concepto','Categoría','Notas'];

function abrirImportacionEgresos(tipo) {
  if ((window._permisos || {}).egresos !== 'editar') return;
  if (!_egImport || _egImport.version !== _versionSesion) {
    _egImport = {version:_versionSesion, tipo:tipo === 'foto' ? 'foto' : 'excel', archivo:null, vista:null, seleccion:{}, pendiente:null, ocupado:false};
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
  document.getElementById('eg-import-tipo').value = _egImport.tipo || 'excel';
  if (tipo && tipo !== _egImport.tipo) cambiarTipoImportacionEgresos(tipo);
  configurarArchivoEgresos();
  document.getElementById('modal-egresos-importar').classList.add('on');
  actualizarSeleccionExcelEgresos();
}

function configurarArchivoEgresos() {
  var foto = _egImport && _egImport.tipo === 'foto';
  document.getElementById('eg-import-file').accept = foto ? 'image/jpeg,image/png,image/webp,image/gif,application/pdf' : '.xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
  document.getElementById('eg-import-file-label').textContent = foto ? 'Foto o PDF de tabla (hasta 20 MB)' : 'Excel (.xlsx, hasta 5 MB)';
  document.getElementById('eg-import-revision-wrap').hidden = !foto;
}

function cambiarTipoImportacionEgresos(tipo) {
  if (!_egImport) return;
  if (_egImport.ocupado || _egImport.pendiente) {
    document.getElementById('eg-import-tipo').value = _egImport.tipo || 'excel'; return;
  }
  _egImport.tipo = tipo === 'foto' ? 'foto' : 'excel';
  document.getElementById('eg-import-tipo').value = _egImport.tipo;
  _egImport.archivo = null;
  document.getElementById('eg-import-file').value = '';
  document.getElementById('eg-import-config').hidden = true;
  configurarArchivoEgresos();
  invalidarVistaExcelEgresos();
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
  _egImport.correcciones = {};
  _egImport.cambios = false;
  document.getElementById('eg-import-revisado').checked = false;
  document.getElementById('eg-import-tabla').innerHTML = '';
  document.getElementById('eg-import-estado').textContent = 'Vista previa pendiente';
  actualizarSeleccionExcelEgresos();
}

function opcionesExcelEgresos(reiniciar) {
  var opciones = {categoria:document.getElementById('eg-import-categoria').value,
    guardar_proveedor:document.getElementById('eg-import-proveedores').checked};
  if (_egImport.tipo === 'foto' || document.getElementById('eg-import-config').hidden) return opciones;
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
  var foto = _egImport.tipo === 'foto';
  var valido = foto ? /\.(jpe?g|png|webp|gif|pdf)$/i.test(archivo.name) || /^(image\/(jpeg|png|webp|gif)|application\/pdf)$/.test(archivo.type || '') : /\.xlsx$/i.test(archivo.name);
  if (!valido || archivo.size > (foto ? 20000000 : 5 * 1024 * 1024)) {
    document.getElementById('eg-import-estado').textContent = foto ? 'Selecciona una foto JPG, PNG, WebP o un PDF de hasta 20 MB. Para HEIC, exporta como JPG.' : 'Selecciona un Excel .xlsx de hasta 5 MB; una foto no es un archivo Excel.';
    input.value = '';
    return actualizarSeleccionExcelEgresos();
  }
  _egImport.archivo = archivo;
  return leerExcelEgresos(true);
}

async function leerExcelEgresos(reiniciar) {
  var estado = _egImport;
  if (!estado || !estado.archivo || estado.ocupado || estado.pendiente) return;
  if (estado.tipo === 'foto' && estado.vista && estado.cambios) return revisarFotoEgresos();
  var opciones = opcionesExcelEgresos(!!reiniciar), seq = ++_egImportSeq;
  estado.ocupado = true;
  estado.vista = null;
  estado.seleccion = {};
  document.getElementById('eg-import-revisado').checked = false;
  document.getElementById('eg-import-tabla').innerHTML = '';
  document.getElementById('eg-import-estado').textContent = estado.tipo === 'foto' ? 'Leyendo tabla de gastos...' : 'Leyendo Excel...';
  actualizarSeleccionExcelEgresos();
  var controller = window.AbortController ? new AbortController() : null;
  var timer = controller ? setTimeout(function() { controller.abort(); }, estado.tipo === 'foto' ? 120000 : 60000) : null;
  try {
    var form = new FormData();
    form.append('archivo', estado.archivo);
    form.append('opciones', JSON.stringify(opciones));
    var response;
    for (var intento = 0; intento < 2; intento++) {
      response = await fetch(API_URL + '/api/v1/egresos/importacion/' + (estado.tipo === 'foto' ? 'foto/' : '') + 'previsualizar', {
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
    estado.correcciones = {};
    estado.cambios = false;
    data.filas.forEach(function(f) { if (f.estado === 'lista') estado.seleccion[f.fila] = true; });
    document.getElementById('eg-import-config').hidden = estado.tipo === 'foto';
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

function campoFilaFotoEgresos(f, campo, valor) {
  var label = {fecha:'Fecha',proveedor:'Proveedor',monto:'Monto MXN',metodo_pago:'Forma de pago'}[campo] + ' fila ' + f.fila;
  var attrs = ' data-eg-foto-campo="' + campo + '" aria-label="' + label + '" onchange="editarFilaFotoEgresos(' + f.fila + ',\'' + campo + '\',this.value)"';
  if (campo === 'metodo_pago') {
    var opciones = ['efectivo','transferencia','tarjeta','credito','debito','bbva','clip','mixto','resguardo'];
    return '<select' + attrs + '><option value="">Sin identificar</option>' + opciones.map(function(m) {
      return '<option value="' + m + '"' + (valor === m ? ' selected' : '') + '>' + escHtml(m) + '</option>';
    }).join('') + '</select>';
  }
  return '<input type="' + (campo === 'fecha' ? 'date' : 'text') + '"' + attrs +
    (campo === 'monto' ? ' inputmode="decimal"' : '') + ' value="' + escHtml(valor || '') + '">';
}

function editarFilaFotoEgresos(numero, campo, valor) {
  var estado = _egImport;
  if (!estado || estado.tipo !== 'foto' || !estado.vista || estado.ocupado || estado.pendiente) return;
  var f = estado.vista.filas.find(function(fila) { return fila.fila === numero; });
  if (!f || f.estado === 'registrada' || f.omitida) return;
  estado.correcciones = estado.correcciones || {};
  if (!estado.correcciones[numero]) {
    var d = f.datos || {}, r = f.original || {};
    estado.correcciones[numero] = {fila:numero,fecha:d.fecha || null,proveedor:d.proveedor || r.proveedor || null,
      monto:d.monto || r.monto || null,metodo_pago:d.metodo_pago || r.metodo_pago || null};
  }
  estado.correcciones[numero][campo] = valor || null;
  estado.cambios = true;
  document.getElementById('eg-import-revisado').checked = false;
  document.getElementById('eg-import-estado').textContent = 'Cambios pendientes de revisar. Sin guardar.';
  actualizarSeleccionExcelEgresos();
}

async function revisarFotoEgresos() {
  var estado = _egImport, version = _versionSesion;
  if (!estado || estado.ocupado || estado.pendiente || !estado.vista || !estado.vista.token) return;
  estado.ocupado = true;
  actualizarSeleccionExcelEgresos();
  document.getElementById('eg-import-estado').textContent = 'Revisando cambios y duplicados...';
  try {
    var data = await api('POST','/egresos/importacion/foto/revisar',{token:estado.vista.token,
      correcciones:Object.keys(estado.correcciones).map(function(k) { return estado.correcciones[k]; })},false,null,version,{timeoutMs:60000,silenciosa:true});
    if (estado !== _egImport || version !== _versionSesion) return;
    estado.vista = data;estado.correcciones = {};estado.cambios = false;estado.seleccion = {};
    document.getElementById('eg-import-revisado').checked = false;
    data.filas.forEach(function(f) { if (f.estado === 'lista') estado.seleccion[f.fila] = true; });
    renderVistaExcelEgresos(data);
  } catch(e) {
    if (estado === _egImport && version === _versionSesion) document.getElementById('eg-import-estado').textContent = e.message || 'No se pudieron revisar los cambios';
  } finally {
    if (estado === _egImport && version === _versionSesion) { estado.ocupado = false;actualizarSeleccionExcelEgresos(); }
  }
}

function renderVistaExcelEgresos(data) {
  var etiquetas = {lista:'Lista',duplicado:'Posible duplicado',error:'Revisar',omitida:'Total excluido',registrada:'Ya importada'};
  var conteos = {};
  var h = '<table class="tbl eg-import-table' + (_egImport.tipo === 'foto' ? ' eg-import-foto' : '') + '"><colgroup><col style="width:44px"><col style="width:48px"><col style="width:110px"><col style="width:220px"><col style="width:120px"><col style="width:125px"><col style="width:105px"><col style="width:200px"></colgroup><thead><tr><th><input type="checkbox" id="eg-import-todas" aria-label="Seleccionar filas sin alertas" onchange="seleccionarFilasExcelEgresos(this.checked)"></th><th>Fila</th><th>Fecha</th><th>Proveedor / concepto</th><th>Monto MXN</th><th>Pago</th><th>Categoría</th><th>Estado</th></tr></thead><tbody>';
  data.filas.forEach(function(f) {
    conteos[f.estado] = (conteos[f.estado] || 0) + 1;
    var d = f.datos || {}, raw = f.original || {}, elegible = f.estado === 'lista' || f.estado === 'duplicado';
    var editable = _egImport.tipo === 'foto' && f.estado !== 'registrada' && !f.omitida;
    h += '<tr><td><input type="checkbox" data-eg-import-fila="' + f.fila + '" aria-label="Importar fila ' + f.fila + '" ' + (elegible ? '' : 'disabled ') + (_egImport.seleccion[f.fila] ? 'checked ' : '') + 'onchange="cambiarSeleccionExcelEgresos(' + f.fila + ',this.checked)"></td>';
    h += '<td>' + f.fila + '</td><td class="eg-import-nowrap">' + (editable ? campoFilaFotoEgresos(f,'fecha',d.fecha) : escHtml(d.fecha || raw.fecha || '--')) + '</td>';
    h += '<td class="eg-import-descripcion">' + (editable ? campoFilaFotoEgresos(f,'proveedor',d.proveedor || raw.proveedor) : '<strong>' + escHtml(d.proveedor || raw.proveedor || '--') + '</strong>');
    if (d.concepto && d.concepto !== d.proveedor) h += '<div>' + escHtml(d.concepto) + '</div>';
    if (d.notas) h += '<div class="eg-import-nota">' + escHtml(d.notas) + '</div>';
    h += '</td><td class="eg-import-nowrap">' + (editable ? campoFilaFotoEgresos(f,'monto',d.monto || raw.monto) : d.monto ? '$' + fmt(d.monto) : escHtml(raw.monto || '--')) + '</td>';
    h += '<td>' + (editable ? campoFilaFotoEgresos(f,'metodo_pago',d.metodo_pago) : escHtml(d.metodo_pago || raw.metodo_pago || '--')) + '</td><td>' + escHtml(d.categoria || '--') + '</td>';
    h += '<td><span class="eg-import-badge eg-import-' + f.estado + '">' + etiquetas[f.estado] + '</span>';
    if (f.errores && f.errores.length) h += '<div class="eg-import-nota">' + f.errores.map(escHtml).join('; ') + '</div>';
    h += '</td></tr>';
  });
  document.getElementById('eg-import-tabla').innerHTML = h + '</tbody></table>';
  document.getElementById('eg-import-estado').textContent = (data.faltantes.length ? 'Faltan columnas: ' + data.faltantes.join(', ') :
    (conteos.lista || 0) + ' listas; ' + (conteos.duplicado || 0) + ' posibles duplicados; ' + (conteos.error || 0) + ' por revisar; ' + (conteos.registrada || 0) + ' ya importadas; ' + (conteos.omitida || 0) + ' totales excluidos. Sin guardar.') +
    (Array.isArray(data.advertencias) && data.advertencias.length ? ' ' + data.advertencias.join('; ') : '');
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
  document.getElementById('eg-import-tipo').disabled = bloqueado;
  document.getElementById('eg-import-revisado').disabled = bloqueado || !_egImport.vista;
  document.querySelectorAll('[data-eg-foto-campo]').forEach(function(el) { el.disabled = bloqueado; });
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
  document.getElementById('eg-import-revisar').textContent = _egImport.cambios ? 'Revisar cambios' : 'Vista previa';
  document.getElementById('eg-import-cerrar').disabled = _egImport.ocupado;
  document.getElementById('eg-import-total').textContent = seleccion.filas.length + ' seleccionados · $' + fmt(seleccion.centavos / 100) + ' MXN';
  var button = document.getElementById('eg-import-confirmar');
  button.disabled = _egImport.ocupado || !_egImport.vista || !_egImport.vista.token || !seleccion.filas.length ||
    !!_egImport.cambios || (_egImport.tipo === 'foto' && !document.getElementById('eg-import-revisado').checked);
  button.textContent = _egImport.pendiente ? 'Reintentar confirmación' : 'Importar ' + seleccion.filas.length + ' gastos';
}

async function confirmarExcelEgresos() {
  var estado = _egImport;
  if (!estado || estado.ocupado || !estado.vista || !estado.vista.token) return;
  if (estado.cambios || (estado.tipo === 'foto' && !document.getElementById('eg-import-revisado').checked)) return;
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
      estado.pendiente = {token:estado.vista.token,filas:seleccion.filas,incluir_duplicados:seleccion.incluir_duplicados,
        revision_confirmada:estado.tipo === 'foto' && document.getElementById('eg-import-revisado').checked};
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
