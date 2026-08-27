/* Service worker do painel — recebe as notificações em segundo plano. */

self.addEventListener('install', e => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));

self.addEventListener('push', event => {
  let d = {};
  try { d = event.data.json(); } catch (_) { d = { titulo: 'Sítio Girassol', corpo: '' }; }

  const urgente = !!d.urgente;

  const opcoes = {
    body: d.corpo || '',
    icon: '/icone-192.png',
    badge: '/icone-192.png',
    tag: d.tag || 'geral',
    renotify: urgente,
    requireInteraction: urgente,          // fica na tela até tocarem
    vibrate: urgente ? [220, 90, 220, 90, 220] : [90],
    silent: false,
    data: { telefone: d.telefone || '', aba: d.aba || '' },
    actions: d.telefone
      ? [{ action: 'abrir', title: 'Abrir conversa' }]
      : (d.aba === 'agenda' ? [{ action: 'abrir', title: 'Ver agenda' }] : []),
  };

  event.waitUntil(self.registration.showNotification(d.titulo || 'Sítio Girassol', opcoes));
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  const tel = event.notification.data?.telefone || '';
  const aba = event.notification.data?.aba || '';
  const destino = tel ? `/painel?tel=${tel}` : (aba ? `/painel?aba=${aba}` : '/painel');

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(lista => {
      for (const c of lista) {
        if (c.url.includes('/painel')) {
          c.focus();
          if (tel) c.postMessage({ abrir: tel });
          else if (aba) c.postMessage({ aba });
          return;
        }
      }
      return clients.openWindow(destino);
    })
  );
});
