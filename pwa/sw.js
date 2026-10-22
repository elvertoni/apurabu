// Service worker: guarda o app no celular para abrir e ler QR Codes sem internet.
const VERSAO = "apura-bu-v4";
const ARQUIVOS = [
  "./", "index.html", "app.css", "app.js", "bu.js", "db.js", "manifest.webmanifest",
  "icons/icone.svg", "icons/icone-192.png", "icons/icone-512.png",
  "vendor/barcode-detector-ponyfill.js", "vendor/zxing_reader.wasm",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(VERSAO).then((c) => c.addAll(ARQUIVOS)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys()
    .then((ks) => Promise.all(ks.filter((k) => k !== VERSAO).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  // chamadas à API nunca vêm do cache
  if (e.request.method !== "GET" || url.pathname.startsWith("/api/")) return;
  if (url.origin !== location.origin) return;
  // rede primeiro (pega atualizações); sem internet, usa o cache
  e.respondWith(
    fetch(e.request)
      .then((r) => { const copia = r.clone(); caches.open(VERSAO).then((c) => c.put(e.request, copia)); return r; })
      .catch(() => caches.match(e.request, { ignoreSearch: true }))
  );
});
