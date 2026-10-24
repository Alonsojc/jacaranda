(function () {
  'use strict';
  window.createSandboxAttention = function (options) {
    var active = false, connected = false, inFlight = false, again = false, epoch = 0, failures = 0, timer = null;
    var data = null, lastSuccess = null, audio = null, sounded = new Set(), title = document.title || 'Jacaranda Sandbox';
    var kinds = ['nuevo', 'verificar', 'preparacion', 'programado'];
    var uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
    function el(id) { return document.getElementById(id); }
    function online() { return !window.navigator || window.navigator.onLine !== false; }
    function text(id, value) { if (el(id).textContent !== value) el(id).textContent = value; }
    function clearTimer() { if (timer !== null) window.clearTimeout(timer); timer = null; }
    function syncControls() { el('attention-open').disabled = !active || !data || !data.pedidos.length || options.isBusy(); }
    function connection(value, problem) {
      connected = value;
      el('attention-connection').className = value ? 'connection-good' : 'connection-warning';
      text('attention-connection', problem || 'Bandeja conectada');
      text('attention-updated', lastSuccess ? '\u00daltima actualizaci\u00f3n: ' + lastSuccess.toLocaleTimeString('es-MX') : 'Sin actualizar');
      if (!value && active) options.onUnavailable();
      syncControls();
    }
    function validate(value) {
      if (!value || value.entorno !== 'sandbox' || !value.conteos || !Array.isArray(value.pedidos) || value.pedidos.length > 100 ||
          !Number.isInteger(value.total) || value.total < value.pedidos.length ||
          kinds.some(function (kind) { return !Number.isInteger(value.conteos[kind]) || value.conteos[kind] < 0; }) ||
          kinds.reduce(function (total, kind) { return total + value.conteos[kind]; }, 0) !== value.total ||
          value.pedidos.some(function (row) { return !row || !uuid.test(row.pedido_id) || !uuid.test(row.event_id) || kinds.indexOf(row.tipo) === -1; })) {
        throw new Error('No se pudo comprobar la bandeja.');
      }
      return value;
    }
    function chime() {
      if (!audio || !el('attention-sound').checked || audio.state !== 'running') return;
      var start = audio.currentTime, gain = audio.createGain();
      gain.connect(audio.destination);
      gain.gain.setValueAtTime(0, start);
      gain.gain.linearRampToValueAtTime(0.12, start + 0.02);
      gain.gain.setValueAtTime(0.12, start + 0.34);
      gain.gain.linearRampToValueAtTime(0, start + 0.4);
      [660, 880].forEach(function (frequency, index) {
        var tone = audio.createOscillator(); tone.frequency.value = frequency; tone.connect(gain);
        tone.start(start + index * 0.18); tone.stop(start + index * 0.18 + 0.19);
      });
    }
    function render(value) {
      data = value;
      var counts = value.conteos, parts = [];
      if (counts.nuevo) parts.push(counts.nuevo + ' por aceptar');
      if (counts.verificar) parts.push(counts.verificar + ' por verificar');
      if (counts.preparacion) parts.push(counts.preparacion + ' en preparaci\u00f3n');
      if (counts.programado) parts.push(counts.programado + (counts.programado === 1 ? ' programado' : ' programados'));
      text('attention-count', value.total === 1 ? '1 pedido pendiente' : value.total + ' pedidos pendientes');
      text('attention-summary', parts.join('; '));
      el('attention-alert').hidden = value.total === 0;
      document.title = value.total ? '(' + value.total + ') ' + title : title;
      var notify = false;
      value.pedidos.forEach(function (row) {
        if (row.tipo !== 'nuevo' && row.tipo !== 'verificar') return;
        var identity = row.pedido_id + ':' + row.tipo;
        if (!sounded.has(identity)) { sounded.add(identity); notify = true; }
      });
      if (notify) {
        try { chime(); }
        catch (error) { el('attention-sound').checked = false; text('attention-audio-status', 'No se pudo reproducir el sonido'); }
      }
      options.onUpdate(value);
      syncControls();
    }
    function schedule(delay) {
      clearTimer();
      if (active && online() && !document.hidden) timer = window.setTimeout(poll, delay);
    }
    async function poll() {
      clearTimer();
      if (!active || document.hidden) return;
      if (!online()) { connection(false, 'Sin conexi\u00f3n a internet'); return; }
      if (inFlight) { again = true; return; }
      var current = epoch;
      inFlight = true;
      try {
        var result = validate(await options.api('/api/v1/uber-eats/sandbox/atencion'));
        if (!active || current !== epoch) return;
        var recovered = failures > 0 || !connected;
        failures = 0; lastSuccess = new Date();
        render(result); connection(true);
        if (recovered) options.onRecovered();
      } catch (error) {
        if (active && current === epoch) { failures += 1; connection(false, online() ? 'Bandeja sin actualizar' : 'Sin conexi\u00f3n a internet'); }
      } finally {
        inFlight = false;
        if (active) {
          if (again || current !== epoch) { again = false; schedule(0); }
          else schedule(failures ? Math.min(30000, 5000 * Math.pow(2, Math.min(failures - 1, 3))) : 15000);
        }
      }
    }
    function stop() {
      active = false; connected = false; epoch += 1; failures = 0; again = false; data = null; lastSuccess = null;
      clearTimer(); sounded.clear(); document.title = title;
      el('attention-alert').hidden = true; el('attention-sound').checked = false; el('attention-sound').disabled = false;
      text('attention-audio-status', ''); text('attention-count', ''); text('attention-summary', '');
      text('attention-connection', 'Acceso privado'); text('attention-updated', '');
      if (audio) { var previous = audio; audio = null; previous.close().catch(function () {}); }
      syncControls();
    }
    el('attention-sound').addEventListener('change', async function () {
      if (!active || !el('attention-sound').checked) return;
      var current = epoch, Audio = window.AudioContext || window.webkitAudioContext;
      if (!Audio) { el('attention-sound').checked = false; text('attention-audio-status', 'Sonido no disponible'); return; }
      el('attention-sound').disabled = true;
      try {
        if (!audio) {
          audio = new Audio();
          var context = audio;
          if (audio.addEventListener) audio.addEventListener('statechange', function () {
            if (active && audio === context && el('attention-sound').checked && context.state !== 'running') {
              el('attention-sound').checked = false; text('attention-audio-status', 'Sonido en pausa');
            }
          });
        }
        await audio.resume();
        if (!active || current !== epoch) return;
        if (audio.state !== 'running') throw new Error('Audio unavailable');
        text('attention-audio-status', ''); chime();
      } catch (error) {
        if (active && current === epoch) { el('attention-sound').checked = false; text('attention-audio-status', 'No se pudo activar el sonido'); }
      } finally { if (active && current === epoch) el('attention-sound').disabled = false; }
    });
    el('attention-open').addEventListener('click', function () {
      if (active && data && data.pedidos.length && !options.isBusy()) options.openOrder(data.pedidos[0].event_id, data.pedidos);
    });
    window.addEventListener('offline', function () {
      if (!active) return;
      epoch += 1; clearTimer(); connection(false, 'Sin conexi\u00f3n a internet');
    });
    window.addEventListener('online', function () { if (active) { connection(false, 'Reconectando...'); poll(); } });
    document.addEventListener('visibilitychange', function () {
      if (!active) return;
      if (document.hidden) clearTimer();
      else { connection(false, 'Actualizando bandeja...'); poll(); }
    });
    return {
      start: function () { stop(); active = true; connection(false, 'Conectando bandeja...'); poll(); },
      stop: stop, refresh: poll, connected: function () { return active && connected && online(); }, syncControls: syncControls
    };
  };
}());
