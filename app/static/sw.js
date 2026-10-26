// Guarda a interface no iPhone para ela abrir mesmo com o PC desligado.
// Troque o numero quando quiser forcar todo mundo a baixar de novo.
const CACHE = "com-v1";
const SHELL = [
  "/",
  "/static/style.css",
  "/static/app.js",
  "/static/manifest.json",
  "/static/icon-180.png",
];

self.addEventListener("install", (e) => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// cache primeiro e atualiza por tras: com o PC desligado o fetch pela rede
// pode levar dezenas de segundos ate desistir, e a tela de espera tem que
// aparecer na hora. A versao nova entra na proxima abertura
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  e.respondWith(
    caches.open(CACHE).then(async (cache) => {
      const hit = await cache.match(e.request, { ignoreSearch: true });
      const fresh = fetch(e.request).then((r) => {
        if (r.ok) cache.put(e.request, r.clone());
        return r;
      });
      if (hit) {
        e.waitUntil(fresh.catch(() => {}));
        return hit;
      }
      return fresh;
    })
  );
});
