// Jacaranda Service Worker — Offline support
const CACHE_NAME = 'jacaranda-v94';
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
      return Promise.all(STATIC_ASSETS.map(function(asset) {
        return cache.add(asset).catch(function() { return null; });
      }));
    })
  );
  self.skipWaiting();
});

function isApiRequest(request, url) {
  return url.pathname.includes('/api/') || request.headers.has('Authorization');
}

function offlineApiResponse() {
  return new Response(JSON.stringify({
    error: 'offline',
    detail: 'Servidor temporalmente no disponible'
  }), {
    status: 503,
    headers: {
      'Content-Type': 'application/json',
      'Cache-Control': 'no-store',
      'X-Jacaranda-Offline': 'true'
    }
  });
}

function cacheableStaticResponse(response) {
  return response &&
    response.status === 200 &&
    (response.type === 'basic' || response.type === 'cors');
}

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
    })
  );
});

self.addEventListener('message', function(event) {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
  if (event.data && event.data.type === 'CLEAR_AUTH_DATA') {
    event.waitUntil(
      caches.keys().then(function(names) {
        return Promise.all(
          names
            .filter(function(name) { return /^jacaranda-(auth|api|data|offline)/.test(name); })
            .map(function(name) { return caches.delete(name); })
        );
      })
    );
  }
});

// Fetch: network-first for API, cache-first for static
self.addEventListener('fetch', function(event) {
  var url = new URL(event.request.url);

  // Skip non-GET for caching (POST requests handled by offline queue in app)
  if (event.request.method !== 'GET') return;

  // API calls and any Authorization-bearing request: network-only.
  // Authenticated business data must never be placed in Cache Storage.
  if (isApiRequest(event.request, url)) {
    event.respondWith(
      fetch(event.request, {cache: 'no-store'}).catch(function() {
        return offlineApiResponse();
      })
    );
    return;
  }

  // HTML shell: network-first so UI changes do not get stuck behind old cache.
  if (event.request.mode === 'navigate' ||
      (event.request.headers.get('accept') || '').includes('text/html')) {
    event.respondWith(
      fetch(event.request).then(function(response) {
        if (cacheableStaticResponse(response)) {
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
        if (cacheableStaticResponse(response)) {
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
