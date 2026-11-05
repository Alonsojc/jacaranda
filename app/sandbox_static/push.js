(function () {
  'use strict';
  window.createSandboxPush = function (options) {
    var registration = null, publicKey = null, subscription = null, active = false, wrongKey = false, generation = 0;
    var button = document.getElementById('push-toggle'), status = document.getElementById('push-status');
    function message(text) { status.textContent = text; }
    function setActive(value) {
      active = value;
      button.textContent = wrongKey ? 'Restablecer notificaciones' : (value ? 'Desactivar notificaciones' : 'Activar notificaciones');
    }
    function decode(value) {
      var raw = atob(value.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - value.length % 4) % 4));
      return Uint8Array.from(raw, function (c) { return c.charCodeAt(0); });
    }
    function matchesKey(currentSub, key) {
      var existing = currentSub && currentSub.options && currentSub.options.applicationServerKey;
      if (!existing) return true;
      var bytes = new Uint8Array(existing);
      return bytes.length === key.length && bytes.every(function (value, i) { return value === key[i]; });
    }
    async function start(enabled) {
      var current = ++generation;
      registration = null; publicKey = null; subscription = null; wrongKey = false; setActive(false);
      button.hidden = !enabled; button.disabled = true; message('');
      if (!enabled) return;
      if (!window.isSecureContext || !('serviceWorker' in navigator) || !('PushManager' in window)) {
        message('En iPad, agrega Sandbox a la pantalla de inicio para activar avisos.');
        return;
      }
      try {
        var config = await options.api('/api/v1/uber-eats/sandbox/push/config');
        var reg = await navigator.serviceWorker.register('/sandbox-sw.js', {scope: '/'});
        await navigator.serviceWorker.ready;
        var currentSub = await reg.pushManager.getSubscription(), key = decode(config.clave_publica);
        var mismatch = currentSub && !matchesKey(currentSub, key);
        var result = currentSub && !mismatch ? await options.api('/api/v1/uber-eats/sandbox/push/status', 'POST', {endpoint: currentSub.endpoint}) : null;
        if (current !== generation) return;
        registration = reg; publicKey = key; subscription = currentSub; wrongKey = !!mismatch;
        setActive(!!(result && result.activa));
        message(wrongKey ? 'La clave de avisos cambio. Restablece y vuelve a activar.' : (active ? (result.ultimo_envio === 'failed' ? 'Ultimo envio de prueba sin confirmar.' : 'Avisos de prueba activados en este dispositivo.') : 'Avisos de prueba desactivados.'));
        button.disabled = false;
      } catch (_) {
        if (current === generation) message('No se pudo preparar los avisos. Vuelve a entrar con conexion.');
      }
    }
    button.addEventListener('click', function () {
      if (!registration || !publicKey || button.disabled) return;
      var current = generation;
      button.disabled = true;
      if ((active || wrongKey) && subscription) {
        options.api('/api/v1/uber-eats/sandbox/push/unsubscribe', 'POST', {endpoint: subscription.endpoint})
          .then(function () { return subscription.unsubscribe(); })
          .then(function () {
            if (current !== generation) return;
            subscription = null; wrongKey = false; setActive(false); message('Avisos desactivados. Puedes activarlos de nuevo.');
          }).catch(function () { if (current === generation) message('No se pudo desactivar. Comprueba la conexion.'); })
          .finally(function () { if (current === generation) button.disabled = false; });
        return;
      }
      // Subscribe directly from the tap so iPadOS can show its permission prompt.
      var requested = subscription ? Promise.resolve(subscription) : registration.pushManager.subscribe({
        userVisibleOnly: true, applicationServerKey: publicKey
      });
      requested.then(function (value) {
        subscription = value;
        return options.api('/api/v1/uber-eats/sandbox/push/subscription', 'POST', value.toJSON());
      }).then(function () {
        if (current !== generation) return;
        setActive(true); message('Avisos de prueba activados en este dispositivo.');
      }).catch(function () {
        if (current === generation) message('No se activaron los avisos. Revisa el permiso y la conexion.');
      }).finally(function () { if (current === generation) button.disabled = false; });
    });
    return {start: start, reset: function () {
      generation += 1; registration = null; publicKey = null; subscription = null; wrongKey = false;
      setActive(false); button.hidden = true; button.disabled = true; message('');
    }};
  };
}());
