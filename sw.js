/* Service worker do painel.
   Faz duas coisas:
     1. Guarda a casca do app, para ele abrir instantaneamente mesmo com o
        servidor do Render adormecido — sem isso a atendente vê a página de
        erro do Render e acha que o sistema quebrou.
     2. Recebe as notificações em segundo plano.
*/

const CASCA = 'girassol-casca-v3';
const ARQUIVOS = ['/painel', '/manifest.json', '/icone-192.png', '/icone-512.png'];

self.addEventListener('install', event => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CASCA)
      .then(c => c.addAll(ARQUIVOS))
      .catch(() => {})       // offline na instalação não pode travar o SW
  );
});

self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    const nomes = await caches.keys();
    await Promise.all(nomes.filter(n => n !== CASCA).map(n => caches.delete(n)));
    await self.clients.claim();
  })());
});

/*
  Navegação: entrega a casca do cache na hora e busca a versão nova por trás.
  A API nunca é cacheada — dado velho de conversa seria pior que esperar.
*/
self.addEventListener('fetch', event => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);
  if (url.origin !== location.origin) return;
  if (url.pathname.startsWith('/api/')) return;

  const ehNavegacao = req.mode === 'navigate' || url.pathname === '/painel';

  if (ehNavegacao) {
    event.respondWith((async () => {
      const cache = await caches.open(CASCA);
      const guardado = await cache.match('/painel');

      const rede = fetch('/painel', { cache: 'no-store' })
        .then(resp => {
          if (resp && resp.ok) cache.put('/painel', resp.clone());
          return resp;
        })
        .catch(() => null);

      // Tem casca guardada? Abre já, e atualiza para a próxima vez.
      if (guardado) { event.waitUntil(rede); return guardado; }

      const resp = await rede;
      return resp || new Response(
        '<meta charset="utf-8"><body style="font-family:system-ui;background:#14301F;' +
        'color:#FBFAF6;display:grid;place-items:center;height:100vh;margin:0;text-align:center">' +
        '<div><h2 style="font-weight:400">Sem conexão</h2>' +
        '<p style="color:#8FA894;font-size:14px">Verifique a internet e abra o app de novo.</p></div>',
        { headers: { 'Content-Type': 'text/html; charset=utf-8' }, status: 200 }
      );
    })());
    return;
  }

  if (ARQUIVOS.includes(url.pathname)) {
    event.respondWith(
      caches.match(req).then(c => c || fetch(req).then(resp => {
        if (resp && resp.ok) caches.open(CASCA).then(k => k.put(req, resp.clone()));
        return resp;
      }))
    );
  }
});

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
