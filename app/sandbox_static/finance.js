(function () {
  'use strict';
  window.createSandboxFinance = function (options) {
    var enabled = false, selected = null, orderId = null, loadedAt = 0;
    var base = '/api/v1/uber-eats/sandbox/finanzas';
    function el(id) { return document.getElementById(id); }
    function money(value) { return Number(value).toLocaleString('es-MX', {style: 'currency', currency: 'MXN'}); }
    function controls() {
      var blocked = options.busy() || !options.connected();
      var fresh = selected && Date.now() - loadedAt < 90000;
      var reviewed = el('finance-reviewed').checked;
      el('finance-refresh').disabled = blocked;
      el('finance-reload').disabled = blocked || !orderId;
      el('finance-order-open').disabled = blocked;
      el('finance-import').disabled = blocked || !fresh || !reviewed || !selected.registrable || !!selected.venta_id;
      el('finance-observe').disabled = blocked || !fresh || !reviewed || !selected.venta_id;
      el('finance-reconcile').disabled = blocked || !fresh || !reviewed || !selected.venta_id || selected.estado !== 'SUCCEEDED' || selected.cancelacion || !!selected.problema;
      el('finance-ticket').disabled = blocked || !selected || !selected.venta_id;
    }
    function reset() {
      selected = null; orderId = null; loadedAt = 0;
      ['finance-totals', 'finance-rows', 'finance-stock', 'finance-items'].forEach(function (id) { el(id).replaceChildren(); });
      ['finance-title', 'finance-state', 'finance-notes', 'finance-problem', 'finance-ticket-text'].forEach(function (id) { el(id).textContent = ''; });
      ['finance-reference', 'finance-gross', 'finance-deductions', 'finance-net'].forEach(function (id) { el(id).value = ''; });
      el('finance-detail').hidden = true; el('finance-ticket-text').hidden = true; el('finance-reviewed').checked = false;
    }
    function invalidate() { loadedAt = 0; el('finance-reviewed').checked = false; controls(); }
    function enable(value) {
      enabled = value === true;
      el('tab-finance').hidden = !enabled; el('finance-order-open').hidden = !enabled;
      if (!enabled) reset();
    }
    async function run(fn) {
      if (!enabled || options.busy() || !options.connected()) return;
      var epoch = options.generation(); options.setBusy(true); controls();
      try { await fn(epoch); }
      catch (error) { if (epoch === options.generation()) { invalidate(); options.status(error.message || 'Resultado por verificar. Actualiza antes de reintentar.', true); } }
      finally { if (epoch === options.generation()) { options.setBusy(false); controls(); } }
    }
    function renderReport(data) {
      el('finance-totals').replaceChildren();
      var labels = {bruto_pedidos: 'Bruto TEST', bruto_por_conciliar: 'Por conciliar', bruto_en_revision: 'Por revisar',
        bruto_conciliado_test: 'Conciliado ficticio', deducciones_test: 'Deducciones ficticias', neto_test: 'Neto ficticio'};
      Object.keys(labels).forEach(function (key) {
        var term = document.createElement('dt'), value = document.createElement('dd');
        term.textContent = labels[key]; value.textContent = money(data.totales[key]); el('finance-totals').append(term, value);
      });
      el('finance-rows').replaceChildren();
      data.pedidos.forEach(function (row) {
        var tr = document.createElement('tr');
        [row.pedido_id.slice(0, 8) + ' / ' + row.fuente, money(row.bruto), row.estado.replaceAll('_', ' ') +
          (row.motivos.length ? ': ' + row.motivos.join(', ').replaceAll('_', ' ') : '')].forEach(function (value) {
          var td = document.createElement('td'); td.textContent = value; tr.appendChild(td);
        });
        var cell = document.createElement('td');
        if (row.fuente === 'Uber TEST') {
          var button = document.createElement('button'); button.type = 'button'; button.textContent = 'Revisar';
          button.addEventListener('click', function () { open(row.pedido_id); }); cell.appendChild(button);
        }
        tr.appendChild(cell); el('finance-rows').appendChild(tr);
      });
      el('finance-stock').replaceChildren();
      data.inventario.concat(data.empaques).forEach(function (item) {
        var row = document.createElement('p'); row.textContent = item.producto + ': ' + Number(item.existencias); el('finance-stock').appendChild(row);
      });
      options.status(data.pedidos.length + (data.pedidos.length === 1 ? ' venta TEST.' : ' ventas TEST.') + ' Efectivo recibido en caja: ' + money(data.efectivo_caja));
    }
    async function report(epoch) {
      var data = await options.api(base);
      if (epoch === options.generation()) renderReport(data);
    }
    async function preview(epoch) {
      selected = null; loadedAt = 0; controls();
      var data = await options.api(base + '/pedidos/' + encodeURIComponent(orderId) + '/consultar', 'POST', {});
      if (epoch !== options.generation()) return;
      selected = data; loadedAt = Date.now(); el('finance-reviewed').checked = false;
      el('finance-title').textContent = 'Pedido ' + orderId.slice(0, 8);
      el('finance-state').textContent = data.estado + (data.venta_id ? ' / Venta TEST #' + data.venta_id : ' / Sin registrar');
      el('finance-problem').textContent = data.cancelacion ? 'Cancelacion o fallo por revisar. Sin reposicion automatica.' : data.problema || '';
      el('finance-notes').textContent = data.plan ? data.plan.instructions || 'Sin instrucciones generales' : '';
      el('finance-items').replaceChildren();
      if (data.plan) data.plan.lines.forEach(function (line) {
        var row = document.createElement('p'); row.textContent = line.quantity + ' x ' + line.title + ' / ' + money(line.gross) +
          (line.instructions ? '\n' + line.instructions : ''); el('finance-items').appendChild(row);
      });
      el('finance-gross').value = data.plan ? Number(data.plan.total.gross).toFixed(2) : '';
      el('finance-deductions').max = el('finance-gross').value;
      updateNet(); el('finance-detail').hidden = false; el('finance-ticket-text').hidden = true;
      controls();
    }
    async function open(id) {
      if (!enabled || options.busy()) return;
      if (orderId !== id) {
        reset();
      }
      orderId = id; options.show();
      await run(async function (epoch) { await report(epoch); if (epoch === options.generation()) await preview(epoch); });
    }
    async function action(name) {
      var button = {registrar: 'finance-import', actualizar: 'finance-observe', conciliar: 'finance-reconcile'}[name];
      if (!selected || el(button).disabled) return;
      var data = {accion: name, detalle_sha256: selected.detalle_sha256, revision: selected.revision, solo_sandbox_confirmado: true};
      if (name === 'conciliar') {
        data.referencia = 'TEST-' + el('finance-reference').value.trim(); data.bruto = el('finance-gross').value;
        data.deducciones = Number(el('finance-deductions').value).toFixed(2);
        data.neto = (Math.round(Number(data.bruto) * 100 - Number(data.deducciones) * 100) / 100).toFixed(2);
      }
      var id = orderId;
      await run(async function (epoch) {
        var ok = await options.confirm(name === 'conciliar' ? 'Conciliar liquidacion ficticia' : name === 'registrar' ? 'Registrar venta e inventario TEST' : 'Registrar revision TEST', id);
        if (!ok || epoch !== options.generation()) return;
        await options.api(base + '/pedidos/' + encodeURIComponent(id) + '/accion', 'POST', data);
        if (epoch !== options.generation()) return;
        invalidate(); await report(epoch); if (epoch === options.generation()) await preview(epoch);
      });
    }
    el('finance-refresh').addEventListener('click', function () { run(report); });
    el('finance-reload').addEventListener('click', function () { run(preview); });
    el('finance-reviewed').addEventListener('change', controls);
    el('finance-import').addEventListener('click', function () { action('registrar'); });
    el('finance-observe').addEventListener('click', function () { action('actualizar'); });
    el('finance-settlement').addEventListener('submit', function (event) { event.preventDefault(); action('conciliar'); });
    function updateNet() {
      var value = Math.round(Number(el('finance-gross').value) * 100 - Number(el('finance-deductions').value) * 100) / 100;
      el('finance-net').value = el('finance-gross').value && el('finance-deductions').value && Number.isFinite(value) && value >= 0 ? value.toFixed(2) : '';
    }
    el('finance-deductions').addEventListener('input', updateNet);
    el('finance-ticket').addEventListener('click', function () {
      if (!selected || el('finance-ticket').disabled) return;
      var id = selected.venta_id;
      run(async function (epoch) {
        var data = await options.api(base + '/ventas/' + id + '/ticket');
        if (epoch === options.generation()) { el('finance-ticket-text').textContent = JSON.stringify(data, null, 2); el('finance-ticket-text').hidden = false; }
      });
    });
    return {enable: enable, reset: reset, invalidate: invalidate, controls: controls, open: open, load: function () { run(report); }};
  };
}());
