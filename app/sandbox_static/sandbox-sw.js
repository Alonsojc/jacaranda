'use strict';

self.addEventListener('push', function (event) {
  var payload = {};
  try { payload = event.data ? event.data.json() : {}; } catch (_) { payload = {}; }
  var body = typeof payload.body === 'string' && payload.body.length <= 160 ? payload.body : 'Hay un aviso de prueba.';
  var tag = typeof payload.tag === 'string' && /^sandbox-[0-9a-f-]{36}$/.test(payload.tag) ? payload.tag : 'sandbox-aviso';
  event.waitUntil(self.registration.showNotification('Jacaranda Sandbox', {
    body: body, tag: tag, icon: '/sandbox-icon.png', data: {url: '/'}
  }));
});

self.addEventListener('notificationclick', function (event) {
  event.notification.close();
  event.waitUntil(self.clients.matchAll({type: 'window', includeUncontrolled: true}).then(function (clients) {
    var existing = clients.find(function (client) { return new URL(client.url).origin === self.location.origin; });
    return existing ? existing.focus() : self.clients.openWindow('/');
  }));
});
