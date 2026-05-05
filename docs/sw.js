// Jacaranda Service Worker — Offline support + sync queue
const CACHE_NAME = 'jacaranda-v11';
const STATIC_ASSETS = [
  './',
  './index.html',
  './favicon.svg',
  './js/jacaranda-core.js',
  './manifest.json',
  'https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=Inter:wght@400;500;600;700&display=swap',
  'https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js',
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
    })
  );
  self.clients.claim();
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
