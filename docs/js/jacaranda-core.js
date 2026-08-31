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

  function clearSensitiveCaches(options) {
    var preserveSales = !!(options && options.preserveSales);
    var localKeys = [
      'jacaranda_prods_cache',
      'jacaranda_pedidos_pendientes',
      'jacaranda_pedido_contactos',
      'jacaranda_pos_draft',
      'jacaranda_tab'
    ];
    if (!preserveSales) {
      localKeys.push(
        'jacaranda_ventas_pendientes',
        'jacaranda_ventas_legacy_revision',
        'jacaranda_ventas_propietario'
      );
    }
    try {
      localKeys.forEach(function(key) { localStorage.removeItem(key); });
    } catch (e) {}

    var cachePromise = Promise.resolve();
    if ('caches' in window) {
      cachePromise = caches.keys().then(function(names) {
        return Promise.all(
          names
            .filter(function(name) {
              return /^jacaranda-(auth|api|data|offline)/.test(name);
            })
            .map(function(name) { return caches.delete(name); })
        );
      });
    }

    var dbPromise = Promise.resolve();
    if (!preserveSales && window.indexedDB && indexedDB.deleteDatabase) {
      dbPromise = new Promise(function(resolve) {
        var req = indexedDB.deleteDatabase('jacaranda-offline');
        req.onsuccess = req.onerror = req.onblocked = function() { resolve(); };
      });
    }

    return Promise.all([cachePromise, dbPromise]);
  }

  function clearSensitiveCachesPreservingSales() {
    return clearSensitiveCaches({preserveSales: true});
  }

  window.JacarandaCore = {
    fmt: fmt,
    escHtml: escHtml,
    nuevaClaveIdempotencia: nuevaClaveIdempotencia,
    clearSensitiveCaches: clearSensitiveCaches,
    clearSensitiveCachesPreservingSales: clearSensitiveCachesPreservingSales
  };
})(window);
