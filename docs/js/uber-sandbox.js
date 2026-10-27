(function () {
  'use strict';
  var selected = null;
  var beforeId = null;
  var busy = false;
  var generation = 0;
  function el(id) { return document.getElementById(id); }
  function allowed() { return typeof window.esAdminActual === 'function' && window.esAdminActual(); }
  function status(message) { el('uber-sandbox-estado').textContent = message; }

  function controls() {
    el('uber-eventos-cargar').disabled = busy;
    el('uber-eventos-anteriores').disabled = busy || beforeId === null;
    ['aceptar', 'rechazar', 'cancelar'].forEach(function (action) {
      var ready = selected && selected.acciones_habilitadas && !selected.requiere_conciliacion;
      var state = selected && selected.pedido.state;
      var stateAllowed = action === 'cancelar' ? state === 'ACCEPTED' : ['OFFERED', 'CREATED'].indexOf(state) >= 0;
      el('uber-sandbox-' + action).disabled = !allowed() || busy || !ready || !stateAllowed ||
        (action === 'aceptar' && !el('uber-sandbox-revisado').checked);
    });
  }

  window.actualizarAccionesUberSandbox = controls;
  window.reiniciarUberSandbox = function () {
    generation += 1;
    busy = false;
    beforeId = null;
    selected = null;
    el('uber-sandbox-pedido').hidden = true;
    el('uber-sandbox-revisado').checked = false;
    el('uber-sandbox-pedido-titulo').textContent = '';
    el('uber-sandbox-instrucciones').textContent = '';
    el('uber-sandbox-detalle').textContent = '';
    el('uber-sandbox-eventos').replaceChildren();
    status('Sin notificaciones consultadas. Tienda real sin activar.');
    controls();
  };

  window.cargarEventosUberSandbox = async function (older) {
    if (!allowed() || busy || (older && beforeId === null)) return;
    var current = generation;
    busy = true;
    controls();
    status('Consultando notificaciones de prueba...');
    try {
      var url = '/uber-eats/sandbox/eventos?limit=10' + (older ? '&before_id=' + beforeId : '');
      var data = await window.api('GET', url, null, false, null, null, {silenciosa: true});
      if (current !== generation || !allowed()) return;
      var rows = data.eventos;
      var container = el('uber-sandbox-eventos');
      container.replaceChildren();
      beforeId = rows.length === 10 ? rows[rows.length - 1].id : null;
      var table = document.createElement('table');
      table.className = 'tbl';
      table.style.minWidth = '490px';
      var heading = table.createTHead().insertRow();
      ['Recibido', 'Tipo', 'Pedido', 'Estado', ''].forEach(function (label) {
        var th = document.createElement('th'); th.textContent = label; heading.appendChild(th);
      });
      var body = table.createTBody();
      rows.forEach(function (item) {
        var row = body.insertRow();
        [new Date(item.recibido_en).toLocaleString('es-MX'), item.tipo,
          item.pedido_id.slice(0, 8), item.estado].forEach(function (value) {
          row.insertCell().textContent = value;
        });
        var button = document.createElement('button');
        button.type = 'button'; button.className = 'limpiar'; button.textContent = 'Revisar';
        button.style.minHeight = '44px';
        button.addEventListener('click', function () { inspect(item.event_id); });
        row.insertCell().appendChild(button);
      });
      if (rows.length) container.appendChild(table);
      status(rows.length ? rows.length + (rows.length === 1 ? ' notificacion de prueba.' : ' notificaciones de prueba.') + ' Aceptacion automatica deshabilitada.' : 'Sin notificaciones de prueba.');
    } catch (error) {
      if (current === generation) status(error.message || 'No se pudieron consultar las notificaciones.');
    } finally {
      if (current === generation) { busy = false; controls(); }
    }
  };

  async function inspect(eventId) {
    if (!allowed() || busy) return;
    var current = generation;
    selected = null;
    busy = true;
    el('uber-sandbox-pedido').hidden = true;
    controls();
    status('Consultando pedido de prueba...');
    try {
      var data = await window.api('POST', '/uber-eats/sandbox/eventos/' + encodeURIComponent(eventId) + '/consultar', {}, false, null, null, {silenciosa: true});
      if (current !== generation || !allowed()) return;
      selected = data;
      el('uber-sandbox-pedido-titulo').textContent = 'Prueba ' + (data.pedido.display_id || data.pedido.id) + ' - ' +
        (data.evento_final ? (data.evento_final.tipo === 'orders.cancel' ? 'Cancelado' : 'Finalizado por Uber') +
          ' - aviso firmado de Uber' : data.pedido.state);
      el('uber-sandbox-instrucciones').textContent = data.pedido.store_instructions || 'Sin instrucciones generales.';
      el('uber-sandbox-detalle').textContent = JSON.stringify(data.pedido, null, 2);
      el('uber-sandbox-revisado').checked = false;
      el('uber-sandbox-pedido').hidden = false;
      status(data.evento_final ? 'No preparar ni entregar. Aviso firmado de Uber confirmado.' +
        (data.detalle_disponible === false ? ' El detalle actualizado no esta disponible.' : '') +
        (data.requiere_conciliacion ? ' Queda una operacion por conciliar; no se reenviara.' : '') :
        data.requiere_conciliacion ? 'Operacion sin confirmar. No se reenviara automaticamente.' :
        (data.acciones_habilitadas ? 'Pedido de prueba pendiente de revision.' : 'Acciones de pruebas deshabilitadas.'));
    } catch (error) {
      if (current === generation) status(error.message || 'No se pudo consultar el pedido.');
    } finally {
      if (current === generation) { busy = false; controls(); }
    }
  }

  window.accionUberSandbox = async function (action) {
    if (!allowed() || busy || !selected || ['aceptar', 'rechazar', 'cancelar'].indexOf(action) < 0) return;
    if (el('uber-sandbox-' + action).disabled) return;
    if (!window.crypto || !window.crypto.randomUUID) { status('Actualiza Safari para usar las acciones de prueba.'); return; }
    var current = generation;
    var orderId = selected.pedido.id;
    var data = {
      request_key: window.crypto.randomUUID(), accion: action,
      detalle_sha256: selected.detalle_sha256,
      instrucciones_revisadas: el('uber-sandbox-revisado').checked,
      motivo: action === 'aceptar' ? null : el('uber-sandbox-motivo').value
    };
    busy = true;
    controls();
    status('Enviando accion de prueba...');
    try {
      var result = await window.api('POST', '/uber-eats/sandbox/pedidos/' + encodeURIComponent(orderId) + '/accion', data, false, null, null, {silenciosa: true});
      if (current === generation) status(result.estado === 'pendiente_aviso' ?
        'Uber recibio la solicitud de cancelacion. Falta el aviso firmado; no se reenviara.' :
        result.estado === 'conciliada' ? 'Cancelacion confirmada por aviso firmado de Uber. No preparar ni entregar.' :
        'Accion de prueba confirmada por Uber. Actualiza el pedido antes de otra accion.');
    } catch (error) {
      if (current === generation) status(error.message || 'Resultado sin confirmar. Revisa el pedido antes de otra accion.');
    } finally {
      if (current === generation) {
        if (selected) selected.acciones_habilitadas = false;
        busy = false;
        controls();
      }
    }
  };
}());
