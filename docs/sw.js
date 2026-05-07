// Jacaranda Service Worker — Offline support + sync queue
const CACHE_NAME = 'jacaranda-v56';
const STATIC_ASSETS = [
  './',
  './index.html',
  './favicon.svg',
  './js/jacaranda-core.js',
  './manifest.json',
  'https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=Inter:wght@400;500;600;700&display=swap',
  'https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js',
  'https://cdn.jsdelivr.net/npm/jspdf@2.5.2/dist/jspdf.umd.min.js',
];

// Install: pre-cache static assets
self.addEventListener('install', function(event) {
  event.waitUntil(
    caches.open(CACHE_NAME).then(function(cache) {
      return cache.addAll(STATIC_ASSETS);
    })
  );
  self.skipWaiting();
});

// Activate: clean old caches
self.addEventListener('activate', function(event) {
  event.waitUntil(
    caches.keys().then(function(names) {
      return Promise.all(
        names.filter(function(n) { return n !== CACHE_NAME; })
             .map(function(n) { return caches.delete(n); })
      );
    }).then(function() {
      return self.clients.claim();
    }).then(function() {
      return clients.matchAll({type: 'window', includeUncontrolled: true});
    }).then(function(clientList) {
      return Promise.all(clientList.map(function(client) {
        try {
          var url = new URL(client.url);
          if (url.origin === self.location.origin && url.pathname.indexOf('/jacaranda/') !== -1) {
            return client.navigate(client.url);
          }
        } catch (e) {}
      }));
    })
  );
});

self.addEventListener('message', function(event) {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});

// Fetch: network-first for API, cache-first for static
self.addEventListener('fetch', function(event) {
  var url = new URL(event.request.url);

  // Skip non-GET for caching (POST requests handled by offline queue in app)
  if (event.request.method !== 'GET') return;

  // API calls: network-only. Authenticated business data must not be cached.
  if (url.pathname.includes('/api/')) {
    event.respondWith(
      fetch(event.request, {cache: 'no-store'}).catch(function() {
        return new Response(JSON.stringify({error: 'offline'}), {
          status: 503,
          headers: {'Content-Type': 'application/json'}
        });
      })
    );
    return;
  }

  // HTML shell: network-first so UI changes do not get stuck behind old cache.
  if (event.request.mode === 'navigate' ||
      (event.request.headers.get('accept') || '').includes('text/html')) {
    event.respondWith(
      fetch(event.request).then(function(response) {
        if (response.status === 200) {
          var clone = response.clone();
          var indexClone = response.clone();
          caches.open(CACHE_NAME).then(function(cache) {
            cache.put(event.request, clone);
            cache.put('./index.html', indexClone);
          });
        }
        return response;
      }).catch(function() {
        return caches.match(event.request).then(function(cached) {
          return cached || caches.match('./index.html');
        });
      })
    );
    return;
  }

  // Static assets: cache-first, then network
  event.respondWith(
    caches.match(event.request).then(function(cached) {
      if (cached) return cached;
      return fetch(event.request).then(function(response) {
        if (response.status === 200) {
          var clone = response.clone();
          caches.open(CACHE_NAME).then(function(cache) {
            cache.put(event.request, clone);
          });
        }
        return response;
      }).catch(function() {
        if (event.request.headers.get('accept') &&
            event.request.headers.get('accept').includes('text/html')) {
          return caches.match('./index.html');
        }
      });
    })
  );
});

// Listen for sync events (Background Sync API)
self.addEventListener('sync', function(event) {
  if (event.tag === 'sync-ventas') {
    event.waitUntil(syncOfflineVentas());
  }
});

self.addEventListener('notificationclick', function(event) {
  event.notification.close();
  var targetUrl = (event.notification.data && event.notification.data.url) || './index.html#ped';
  event.waitUntil(
    clients.matchAll({type: 'window', includeUncontrolled: true}).then(function(clientList) {
      for (var i = 0; i < clientList.length; i++) {
        var client = clientList[i];
        if ('focus' in client) {
          client.navigate(targetUrl);
          return client.focus();
        }
      }
      if (clients.openWindow) return clients.openWindow(targetUrl);
    })
  );
});

self.addEventListener('push', function(event) {
  var payload = {};
  if (event.data) {
    try {
      payload = event.data.json();
    } catch (e) {
      payload = {notification: {body: event.data.text()}};
    }
  }

  var data = payload.data || {};
  var notif = payload.notification || {};
  var title = notif.title || data.title || 'Jacaranda';
  var options = {
    body: notif.body || data.body || 'Nuevo aviso de Jacaranda',
    icon: notif.icon || './favicon.svg',
    badge: notif.badge || './favicon.svg',
    tag: notif.tag || data.tag || 'jacaranda-push',
    renotify: true,
    requireInteraction: data.tipo === 'nuevo_pedido' || data.requireInteraction === 'true',
    data: {
      url: data.url || './index.html#ped'
    }
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

// Sync offline sales queue from IndexedDB
function syncOfflineVentas() {
  return openDB().then(function(db) {
    return getAllPending(db);
  }).then(function(items) {
    return Promise.all(items.map(function(item) {
      return fetch(item.url, {
        method: 'POST',
        headers: item.headers,
        body: item.body,
      }).then(function(resp) {
        if (resp.ok) return removePending(item.id);
      }).catch(function() { /* will retry on next sync */ });
    }));
  });
}

function openDB() {
  return new Promise(function(resolve, reject) {
    var req = indexedDB.open('jacaranda-offline', 1);
    req.onupgradeneeded = function(e) {
      var db = e.target.result;
      if (!db.objectStoreNames.contains('pending-sales')) {
        db.createObjectStore('pending-sales', { keyPath: 'id', autoIncrement: true });
      }
    };
    req.onsuccess = function(e) { resolve(e.target.result); };
    req.onerror = function() { reject(req.error); };
  });
}

function getAllPending(db) {
  return new Promise(function(resolve) {
    var tx = db.transaction('pending-sales', 'readonly');
    var store = tx.objectStore('pending-sales');
    var req = store.getAll();
    req.onsuccess = function() { resolve(req.result || []); };
    req.onerror = function() { resolve([]); };
  });
}

function removePending(id) {
  return openDB().then(function(db) {
    var tx = db.transaction('pending-sales', 'readwrite');
    tx.objectStore('pending-sales').delete(id);
  });
}
