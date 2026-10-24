(function () {
  'use strict';
  var key = '', selected = null, eventId = null, beforeId = null, busy = false, generation = 0, viewingOlder = false;
  var storeSelected = null, panel = 'orders';
  var names = {aceptar: 'Aceptar prueba', rechazar: 'Rechazar prueba', cancelar: 'Cancelar prueba', listo: 'Listo para recoger'};
  var ids = {aceptar: 'accept', rechazar: 'deny', cancelar: 'cancel', listo: 'ready'};
  function el(id) { return document.getElementById(id); }
  function status(text, error) { el('status').textContent = text; el('status').className = error ? 'error' : ''; }
  function controls() {
    ['refresh', 'connection', 'reload-order'].forEach(function (id) { el(id).disabled = busy; });
    el('older').disabled = busy || beforeId === null;
    Object.keys(ids).forEach(function (action) {
      var state = selected && selected.pedido.state;
      var stateOK = action === 'cancelar' || action === 'listo' ? state === 'ACCEPTED' : ['OFFERED', 'CREATED'].indexOf(state) !== -1;
      el(ids[action]).disabled = busy || !selected || !selected.acciones_habilitadas ||
        selected.requiere_conciliacion || !stateOK || (action === 'listo' && selected.listo_confirmado) ||
        ((action === 'aceptar' || action === 'listo') && !el('reviewed').checked);
    });
    ['reload-store', 'reload-menu', 'discover-stores', 'authorize-store'].forEach(function (id) { el(id).disabled = busy; });
    var storeOK = storeSelected && !storeSelected.requiere_conciliacion;
    el('store-online').disabled = busy || !storeOK || storeSelected.revocada || !storeSelected.integracion.integration_enabled;
    el('store-integrated').disabled = busy || !storeOK;
    el('publish-menu').disabled = busy || !storeOK || storeSelected.revocada || !storeSelected.integracion.integration_enabled;
    el('provision-store').disabled = busy || !storeOK || !storeSelected.cuenta_autorizada;
    document.querySelectorAll('#fixture-items input, #fixture-items button').forEach(function (input) {
      input.disabled = busy || !storeOK || !storeSelected.menu_publicado || storeSelected.revocada;
    });
  }
  function logout() {
    generation += 1; key = ''; selected = null; eventId = null; beforeId = null; busy = false; viewingOlder = false;
    el('access-key').value = ''; el('access-form').hidden = false; el('workspace').hidden = true;
    el('logout').hidden = true; el('events').replaceChildren(); el('order-detail').hidden = true;
    el('raw-detail').textContent = ''; el('items').replaceChildren(); el('instructions').textContent = '';
    el('reviewed').checked = false; el('empty').hidden = false;
    storeSelected = null; el('store-summary').replaceChildren(); el('store-events').replaceChildren();
    el('fixture-items').replaceChildren(); el('fixture-detail').textContent = '';
    el('merchant-auth-link').removeAttribute('href'); el('merchant-auth-link').hidden = true;
    panel = 'orders';
    ['orders', 'store', 'menu'].forEach(function (id) { el(id + '-panel').hidden = id !== panel; el('tab-' + id).setAttribute('aria-selected', String(id === panel)); });
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
        request_key: window.crypto.randomUUID(), accion: name, motivo: name === 'aceptar' || name === 'listo' ? null : reason,
        instrucciones_revisadas: reviewed, detalle_sha256: digest
      });
      if (current === generation) status('Uber recibio la solicitud de Sandbox. Actualiza para verificar el estado.');
    } catch (error) { if (current === generation) status(error.message || 'Resultado sin confirmar. No se reenviara la accion.', true); }
    finally { if (current === generation) { if (selected) selected.acciones_habilitadas = false; busy = false; controls(); } }
  }
  function renderStore(data, fixture, events) {
    storeSelected = data;
    el('store-summary').replaceChildren();
    [['Tienda', data.nombre], ['Identificador', data.tienda_id], ['Disponibilidad', data.estado],
      ['Integracion', data.revocada ? 'Revocada' : data.integracion.integration_enabled ? 'Habilitada' : 'Pausada'],
      ['Cuenta de pruebas', data.cuenta_autorizada ? 'Autorizada' : 'Pendiente'],
      ['Ultima operacion', data.requiere_conciliacion ? 'Por verificar' : 'Sin operaciones pendientes']].forEach(function (pair) {
      var term = document.createElement('dt'), value = document.createElement('dd');
      term.textContent = pair[0]; value.textContent = pair[1]; el('store-summary').append(term, value);
    });
    el('store-online').checked = data.estado === 'ONLINE';
    el('store-integrated').checked = data.integracion.integration_enabled === true;
    el('fixture-detail').textContent = JSON.stringify(fixture.menu, null, 2);
    el('fixture-items').replaceChildren();
    fixture.menu.items.forEach(function (item) {
      var actual = data.items.find(function (row) { return row.id === item.id; });
      var row = document.createElement('tr');
      var nameCell = document.createElement('td'); nameCell.textContent = item.title.translations.es_mx;
      var priceCell = document.createElement('td'), price = document.createElement('input');
      price.type = 'number'; price.min = '1'; price.max = '5'; price.step = '0.01';
      price.value = ((actual ? actual.precio_centavos : item.price_info.price) / 100).toFixed(2);
      price.setAttribute('aria-label', 'Precio de ' + item.title.translations.es_mx); priceCell.appendChild(price);
      var stockCell = document.createElement('td'), stock = document.createElement('input');
      stock.type = 'checkbox'; stock.checked = Boolean(actual && actual.agotado);
      stock.setAttribute('aria-label', 'Agotado: ' + item.title.translations.es_mx); stockCell.appendChild(stock);
      var commandCell = document.createElement('td'), save = document.createElement('button');
      save.type = 'button'; save.textContent = 'Guardar';
      save.addEventListener('click', function () {
        if (!price.reportValidity()) return;
        var amount = Math.round(Number(price.value) * 100);
        if (!Number.isInteger(amount) || amount < 100 || amount > 500) return;
        storeAction('item_actualizar', {item_id: item.id, precio_centavos: amount, agotado: stock.checked}, 'Actualizar producto ficticio');
      });
      commandCell.appendChild(save); row.append(nameCell, priceCell, stockCell, commandCell); el('fixture-items').appendChild(row);
    });
    el('store-events').replaceChildren();
    (events.eventos || []).forEach(function (item) {
      var job = (events.procesamiento || []).find(function (row) { return row.event_id === item.event_id; });
      var row = document.createElement('div'), type = document.createElement('span'), meta = document.createElement('span');
      type.textContent = item.tipo; meta.textContent = new Date(item.recibido_en).toLocaleString('es-MX') + ' - ' + (job ? job.estado : item.estado);
      row.append(type, meta); el('store-events').appendChild(row);
    });
    if (!events.eventos.length) el('store-events').textContent = 'Sin eventos de tienda';
  }
  async function storeData(current) {
    var data = await api('/api/v1/uber-eats/sandbox/tienda');
    if (current !== generation) return null;
    var fixture = await api('/api/v1/uber-eats/sandbox/menu-ficticio');
    if (current !== generation) return null;
    var events = await api('/api/v1/uber-eats/sandbox/tienda/eventos');
    return [data, fixture, events];
  }
  async function loadStore() {
    if (!key || busy) return;
    var current = generation; busy = true; controls(); status('Consultando tienda de pruebas...');
    try {
      var result = await storeData(current);
      if (current !== generation) return;
      renderStore(result[0], result[1], result[2]);
      status(result[0].requiere_conciliacion ? 'Resultado pendiente de verificar. No se reenviara la operacion.' : 'Jacaranda Sandbox actualizada');
    } catch (error) { if (current === generation) status(error.message || 'No se pudo consultar la tienda de pruebas.', true); }
    finally { if (current === generation) { busy = false; controls(); } }
  }
  async function storeAction(name, parameters, title) {
    if (!key || busy || !storeSelected || storeSelected.requiere_conciliacion) return;
    var current = generation, revision = storeSelected.revision;
    busy = true; controls();
    el('confirm-title').textContent = title; el('confirm-order').textContent = 'Solo Jacaranda Sandbox - ' + storeSelected.tienda_id;
    el('confirm-submit').className = 'danger'; el('confirm-dialog').showModal();
    var confirmed = await new Promise(function (resolve) {
      el('confirm-dialog').addEventListener('close', function () { resolve(el('confirm-dialog').returnValue === 'confirm'); }, {once: true});
    });
    if (current !== generation) return;
    if (!confirmed) {
      el('store-online').checked = storeSelected.estado === 'ONLINE';
      el('store-integrated').checked = storeSelected.integracion.integration_enabled === true;
      busy = false; controls(); return;
    }
    try {
      status('Enviando operacion a Sandbox...');
      await api('/api/v1/uber-eats/sandbox/tienda/accion', 'POST', Object.assign({
        request_key: window.crypto.randomUUID(), accion: name, revision: revision, solo_sandbox_confirmado: true
      }, parameters || {}));
      var result = await storeData(current);
      if (current !== generation) return;
      renderStore(result[0], result[1], result[2]);
      status(result[0].requiere_conciliacion ? 'Uber recibio la operacion. Resultado por verificar.' : 'Operacion de Sandbox verificada');
    } catch (error) {
      if (current === generation) { storeSelected.requiere_conciliacion = true; status(error.message || 'Actualiza para verificar el resultado.', true); }
    } finally { if (current === generation) { busy = false; controls(); } }
  }
  ['orders', 'store', 'menu'].forEach(function (name) {
    el('tab-' + name).addEventListener('click', function () {
      if (busy) return;
      panel = name;
      ['orders', 'store', 'menu'].forEach(function (id) { el(id + '-panel').hidden = id !== name; el('tab-' + id).setAttribute('aria-selected', String(id === name)); });
      if (name !== 'orders') loadStore();
    });
  });
  el('reload-store').addEventListener('click', loadStore); el('reload-menu').addEventListener('click', loadStore);
  el('publish-menu').addEventListener('click', function () { storeAction('menu_publicar', {}, 'Publicar menu ficticio'); });
  el('provision-store').addEventListener('click', function () { storeAction('vincular', {}, 'Vincular tienda de pruebas'); });
  el('store-online').addEventListener('change', function () { storeAction(el('store-online').checked ? 'reanudar' : 'pausar', {}, 'Cambiar disponibilidad de Sandbox'); });
  el('store-integrated').addEventListener('change', function () { storeAction(el('store-integrated').checked ? 'integracion_activar' : 'integracion_pausar', {}, 'Cambiar integracion de Sandbox'); });
  el('discover-stores').addEventListener('click', async function () {
    if (!key || busy) return;
    var current = generation; busy = true; controls();
    try { var result = await api('/api/v1/uber-eats/sandbox/tiendas'); if (current === generation) status(result.tiendas.length + ' tienda de pruebas verificada'); }
    catch (error) { if (current === generation) status(error.message, true); }
    finally { if (current === generation) { busy = false; controls(); } }
  });
  el('authorize-store').addEventListener('click', async function () {
    if (!key || busy) return;
    var current = generation; busy = true; controls();
    try {
      var result = await api('/api/v1/uber-eats/sandbox/oauth/iniciar', 'POST', {});
      var url = new URL(result.url);
      if (url.origin !== 'https://sandbox-login.uber.com' || url.pathname !== '/oauth/v2/authorize' ||
          url.searchParams.get('client_id') !== 'I2pbZ-jD6Qa7FQzhLUbX3Y5gN12EasPL' ||
          url.searchParams.get('scope') !== 'eats.pos_provisioning' ||
          url.searchParams.get('redirect_uri') !== 'https://uber-sandbox-webhook-uber-sandbox.up.railway.app/sandbox/oauth/callback') throw new Error('Autorizacion de pruebas no valida.');
      if (current === generation) { el('merchant-auth-link').href = url.href; el('merchant-auth-link').hidden = false; status('Autorizacion de cuenta Sandbox preparada'); }
    } catch (error) { if (current === generation) status(error.message, true); }
    finally { if (current === generation) { busy = false; controls(); } }
  });
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
  window.setInterval(function () { if (key && panel === 'orders' && !busy && !viewingOlder && !document.hidden) load(false, true); }, 15000);
  controls();
}());
