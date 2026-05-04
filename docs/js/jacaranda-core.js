(function(window) {
  function fmt(n) {
    var x = parseFloat(n) || 0;
    return x.toLocaleString('en-US', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    });
  }

  function escHtml(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, function(c) {
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
    });
  }

  function nuevaClaveIdempotencia(prefix) {
    if (window.crypto && window.crypto.randomUUID) {
      return prefix + '-' + window.crypto.randomUUID();
    }
    return prefix + '-' + Date.now() + '-' + Math.random().toString(16).slice(2);
  }

  function clearSensitiveCaches() {
    if (!('caches' in window)) return Promise.resolve();
    return caches.keys().then(function(names) {
      return Promise.all(
        names
          .filter(function(name) { return name.indexOf('jacaranda-') === 0; })
          .map(function(name) { return caches.delete(name); })
      );
    });
  }

  window.JacarandaCore = {
    fmt: fmt,
    escHtml: escHtml,
    nuevaClaveIdempotencia: nuevaClaveIdempotencia,
    clearSensitiveCaches: clearSensitiveCaches
  };
})(window);
