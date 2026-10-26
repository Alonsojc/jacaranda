// Jacaranda Service Worker — Offline support
const CACHE_NAME = 'jacaranda-v129';
const SHELL_WAIT_MS = 1800;
const STATIC_FETCH_TIMEOUT_MS = 12000;
const STATIC_ASSETS = [
  './',
  './index.html',
  './favicon.svg',
  './js/jacaranda-core.js?v=jacaranda-v129',
  './js/egresos-import.js?v=jacaranda-v129',
  './manifest.json',
];

function fetchStaticBounded(request) {
  var controller = typeof AbortController === 'function' ? new AbortController() : null;
  return new Promise(function(resolve, reject) {
    var timer = setTimeout(function() {
      if (controller) controller.abort();
      reject(new Error('Static resource timed out'));
    }, STATIC_FETCH_TIMEOUT_MS);
    var options = {cache: 'no-store'};
    if (controller) options.signal = controller.signal;
    fetch(request, options).then(function(response) {
      // Include the response body in the deadline, not only the headers.
      if (!cacheableStaticResponse(response)) return response;
      return response.clone().arrayBuffer().then(function() { return response; });
    }).then(function(response) {
      clearTimeout(timer);
      resolve(response);
    }, function(error) {
      clearTimeout(timer);
      reject(error);
    });
  });
}

// Install: pre-cache static assets
self.addEventListener('install', function(event) {
  event.waitUntil(
    caches.open(CACHE_NAME).then(function(cache) {
      return Promise.all(STATIC_ASSETS.map(function(asset) {
        return fetchStaticBounded(asset).then(function(response) {
          if ((asset === './' || asset === './index.html') && !/text\/html/i.test(response.headers.get('Content-Type') || '')) return;
          if (cacheableStaticResponse(response)) return cache.put(asset, response);
        }).catch(function() { return null; });
      })).then(function() {
        return cache.match('./index.html').then(function(shell) { return shell || cache.match('./'); });
      }).then(function(shell) {
        if (!shell) throw new Error('Keep the previous worker until an app shell is available');
      });
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

function shellUnavailableResponse() {
  return new Response('<!doctype html><html lang="es"><meta charset="utf-8">' +
    '<meta name="viewport" content="width=device-width,initial-scale=1"><title>Jacaranda</title>' +
    '<body style="font-family:system-ui,sans-serif;background:#fdf9f7;color:#4a3530;padding:2rem">' +
    '<h1>Jacaranda</h1><p>No se pudo cargar la app. Tu sesi&oacute;n sigue guardada.</p>' +
    '<a href="./" style="display:inline-block;padding:.8rem;background:#fff;border:1px solid #ede3df;border-radius:8px;color:inherit">Reintentar</a></body></html>', {
    status: 503,
    headers: {'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store'}
  });
}

function navigationResponse(event) {
  var network = fetchStaticBounded(event.request).then(function(response) {
    return cacheableStaticResponse(response) && /text\/html/i.test(response.headers.get('Content-Type') || '') ? response : null;
  }).catch(function() { return null; });
  // A slow refresh must not hold the cached shell, but can update it for next time.
  event.waitUntil(network.then(function(response) {
    if (!response) return;
    return caches.open(CACHE_NAME).then(function(cache) {
      return cache.put('./index.html', response.clone());
    });
  }).catch(function() {}));
  return caches.open(CACHE_NAME).then(function(cache) {
    return cache.match('./index.html').then(function(cached) {
      return cached || cache.match('./');
    });
  }).catch(function() { return null; }).then(function(cached) {
    if (!cached) return network.then(function(response) { return response || shellUnavailableResponse(); });
    return new Promise(function(resolve) {
      var timer = setTimeout(function() { resolve(cached); }, SHELL_WAIT_MS);
      network.then(function(response) {
        clearTimeout(timer);
        resolve(response || cached);
      });
    });
  });
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
    event.respondWith(navigationResponse(event));
    return;
  }

  // Static assets: cache-first, then network
  event.respondWith(
    caches.match(event.request).then(function(cached) {
      if (cached) return cached;
      return fetchStaticBounded(event.request).then(function(response) {
        if (cacheableStaticResponse(response)) {
          var clone = response.clone();
          caches.open(CACHE_NAME).then(function(cache) {
            cache.put(event.request, clone);
          });
        }
        return response;
      }).catch(function() { return new Response('', {status: 504}); });
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
