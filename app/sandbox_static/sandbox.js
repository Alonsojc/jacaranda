(function () {
  'use strict';
  var key = '', selected = null, eventId = null, beforeId = null, busy = false, generation = 0, viewingOlder = false;
  var names = {aceptar: 'Aceptar prueba', rechazar: 'Rechazar prueba', cancelar: 'Cancelar prueba'};
  var ids = {aceptar: 'accept', rechazar: 'deny', cancelar: 'cancel'};
  function el(id) { return document.getElementById(id); }
  function status(text, error) { el('status').textContent = text; el('status').className = error ? 'error' : ''; }
  function controls() {
    ['refresh', 'connection', 'reload-order'].forEach(function (id) { el(id).disabled = busy; });
    el('older').disabled = busy || beforeId === null;
    Object.keys(ids).forEach(function (action) {
      var state = selected && selected.pedido.state;
      var stateOK = action === 'cancelar' ? state === 'ACCEPTED' : ['OFFERED', 'CREATED'].indexOf(state) !== -1;
      el(ids[action]).disabled = busy || !selected || !selected.acciones_habilitadas ||
        selected.requiere_conciliacion || !stateOK || (action === 'aceptar' && !el('reviewed').checked);
    });
  }
  function logout() {
    generation += 1; key = ''; selected = null; eventId = null; beforeId = null; busy = false; viewingOlder = false;
    el('access-key').value = ''; el('access-form').hidden = false; el('workspace').hidden = true;
    el('logout').hidden = true; el('events').replaceChildren(); el('order-detail').hidden = true;
    el('raw-detail').textContent = ''; el('items').replaceChildren(); el('instructions').textContent = '';
    el('reviewed').checked = false; el('empty').hidden = false;
    if (el('confirm-dialog').open) el('confirm-dialog').close('cancel');
    status('Acceso privado'); controls();
  }
  async function api(path, method, body) {
    var controller = new AbortController();
    var timeout = window.setTimeout(function () { controller.abort(); }, 20000);
    try {
      var response = await window.fetch(path, {
        method: method || 'GET', credentials: 'omit', cache: 'no-store', redirect: 'error',
        headers: {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'},
        body: body === undefined ? undefined : JSON.stringify(body), signal: controller.signal
      });
      var data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'No se pudo completar la solicitud.');
      return data;
    } finally { window.clearTimeout(timeout); }
  }
  async function load(older, silent) {
    if (!key || busy || (older && beforeId === null)) return;
    var current = generation;
    busy = true; controls();
    if (!silent) status('Consultando notificaciones...');
    try {
      var data = await api('/api/v1/uber-eats/sandbox/eventos?limit=10' + (older ? '&before_id=' + beforeId : ''));
      if (current !== generation) return;
      viewingOlder = Boolean(older);
      el('events').replaceChildren();
      beforeId = data.eventos.length === 10 ? data.eventos[data.eventos.length - 1].id : null;
      data.eventos.forEach(function (item) {
        var button = document.createElement('button'); button.type = 'button';
        button.className = 'event' + (item.event_id === eventId ? ' selected' : '');
        var title = document.createElement('strong'); title.textContent = 'Pedido ' + item.pedido_id.slice(0, 8);
        var meta = document.createElement('span'); meta.textContent = new Date(item.recibido_en).toLocaleString('es-MX') + ' - ' + item.estado;
        var type = document.createElement('span'); type.textContent = item.tipo;
        button.append(title, meta, type); button.addEventListener('click', function () { inspect(item.event_id); });
        el('events').appendChild(button);
      });
      if (!silent) status(data.eventos.length ? data.eventos.length + ' notificaciones de Sandbox' : 'Sin notificaciones de Sandbox');
    } catch (error) { if (current === generation) status(error.message || 'No se pudo actualizar.', true); }
    finally { if (current === generation) { busy = false; controls(); } }
  }
  function render(data) {
    var order = data.pedido;
    el('order-title').textContent = 'Pedido ' + (order.display_id || order.id.slice(0, 8));
    el('order-state').textContent = order.state + (data.estado_remoto && data.estado_remoto !== order.state ?
      ' (Uber: ' + data.estado_remoto + ')' : '');
    el('instructions').textContent = order.store_instructions || 'Sin instrucciones generales';
    el('raw-detail').textContent = JSON.stringify(order, null, 2);
    el('items').replaceChildren();
    (Array.isArray(order.carts) ? order.carts : []).forEach(function (cart) {
      (Array.isArray(cart.items) ? cart.items : []).forEach(function (item) {
        var row = document.createElement('div'); row.className = 'line-item';
        var name = document.createElement('strong');
        var quantity = item.quantity && item.quantity.amount;
        name.textContent = String(quantity === undefined ? '?' : quantity) + ' x ' + (item.title || 'Producto');
        row.appendChild(name);
        var notes = [item.special_instructions, item.customer_request && item.customer_request.special_instructions];
        notes.forEach(function (text, index) {
          if (typeof text !== 'string' || !text || notes.indexOf(text) !== index) return;
          var note = document.createElement('p'); note.textContent = text; row.appendChild(note);
        });
        el('items').appendChild(row);
      });
    });
    el('reviewed').checked = false; el('empty').hidden = true; el('order-detail').hidden = false;
  }
  async function inspect(id) {
    if (!key || busy) return;
    var current = generation;
    selected = null; eventId = id; busy = true; el('order-detail').hidden = true; controls();
    status('Consultando pedido...');
    try {
      var data = await api('/api/v1/uber-eats/sandbox/eventos/' + encodeURIComponent(id) + '/consultar', 'POST', {});
      if (current !== generation) return;
      selected = data; render(data);
      status(data.requiere_conciliacion ? 'Resultado pendiente de confirmar. No se reenviara la accion.' :
        (data.acciones_habilitadas ? 'Pedido de Sandbox actualizado' : 'Acciones de Sandbox deshabilitadas'));
    } catch (error) { if (current === generation) status(error.message || 'No se pudo consultar el pedido.', true); }
    finally { if (current === generation) { busy = false; controls(); } }
  }
  async function action(name) {
    if (!key || busy || !selected || el(ids[name]).disabled) return;
    if (!window.crypto || !window.crypto.randomUUID) { status('Este navegador no permite confirmar la operacion.', true); return; }
    var current = generation, orderId = selected.pedido.id, digest = selected.detalle_sha256;
    var reviewed = el('reviewed').checked, reason = el('reason').value;
    busy = true; controls();
    el('confirm-title').textContent = names[name];
    el('confirm-order').textContent = 'Jacaranda Sandbox - ' + (selected.pedido.display_id || orderId.slice(0, 8));
    el('confirm-submit').className = name === 'aceptar' ? '' : 'danger';
    el('confirm-dialog').showModal();
    var confirmed = await new Promise(function (resolve) {
      el('confirm-dialog').addEventListener('close', function () { resolve(el('confirm-dialog').returnValue === 'confirm'); }, {once: true});
    });
    if (current !== generation) return;
    if (!confirmed) { busy = false; controls(); return; }
    try {
      status('Enviando accion de Sandbox...');
      await api('/api/v1/uber-eats/sandbox/pedidos/' + encodeURIComponent(orderId) + '/accion', 'POST', {
        request_key: window.crypto.randomUUID(), accion: name, motivo: name === 'aceptar' ? null : reason,
        instrucciones_revisadas: reviewed, detalle_sha256: digest
      });
      if (current === generation) status('Uber recibio la solicitud de Sandbox. Actualiza para verificar el estado.');
    } catch (error) { if (current === generation) status(error.message || 'Resultado sin confirmar. No se reenviara la accion.', true); }
    finally { if (current === generation) { if (selected) selected.acciones_habilitadas = false; busy = false; controls(); } }
  }
  el('access-form').addEventListener('submit', async function (event) {
    event.preventDefault(); if (busy) return;
    var current = generation; key = el('access-key').value.trim(); el('access-key').value = ''; busy = true;
    try {
      await api('/sandbox/estado'); if (current !== generation) return;
      el('access-form').hidden = true; el('workspace').hidden = false; el('logout').hidden = false;
      busy = false; await load(false, false);
    } catch (error) { if (current === generation) { key = ''; status(error.message || 'No se pudo entrar.', true); } }
    finally { if (current === generation) { busy = false; controls(); } }
  });
  el('logout').addEventListener('click', logout);
  el('refresh').addEventListener('click', function () { load(false, false); });
  el('older').addEventListener('click', function () { load(true, false); });
  el('reload-order').addEventListener('click', function () { if (eventId) inspect(eventId); });
  el('reviewed').addEventListener('change', controls);
  Object.keys(ids).forEach(function (name) { el(ids[name]).addEventListener('click', function () { action(name); }); });
  el('connection').addEventListener('click', async function () {
    if (!key || busy) return;
    var current = generation; busy = true; controls(); status('Consultando conexion de pruebas...');
    try { await api('/api/v1/uber-eats/probar-conexion', 'POST', {}); if (current === generation) status('Conexion con Jacaranda Sandbox verificada'); }
    catch (error) { if (current === generation) status(error.message || 'No se pudo verificar la conexion.', true); }
    finally { if (current === generation) { busy = false; controls(); } }
  });
  window.addEventListener('pagehide', logout);
  window.setInterval(function () { if (key && !busy && !viewingOlder && !document.hidden) load(false, true); }, 15000);
  controls();
}());
