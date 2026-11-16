/* صادِح service worker.
   Two reasons it exists: Chrome only offers "install" reliably when there is a fetch handler, and
   Google Play wants an app that does something without a network. It must never serve stale code,
   so everything except icons is network-first and the cache is only a fallback.

   Deliberately NOT touched: /ws/… (websockets never reach fetch anyway), /config and /healthz —
   those must always be the truth from the server, never a cached answer. */
const V = "sadih-v2";
const SHELL = [
  "/app",
  "/static/client.js",
  "/static/worklet.js",
  "/manifest.webmanifest",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
];

const OFFLINE = `<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>صادِح</title><style>
 body{margin:0;height:100dvh;display:grid;place-content:center;gap:14px;text-align:center;
      background:#0C0A18;color:#fff;font-family:"IBM Plex Sans Arabic",Tahoma,sans-serif;padding:0 32px}
 b{color:#FF6F5E;font-size:30px}p{color:#A49FC4;line-height:1.8;margin:0}
</style><b>صادِح</b><p>ما فيه اتصال بالإنترنت.<br>صادِح يحتاج اتصال عشان يترجم الكلام.</p>`;

self.addEventListener("install", e => {
  e.waitUntil(caches.open(V).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys()
      .then(ks => Promise.all(ks.filter(k => k !== V).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;
  if (url.pathname.startsWith("/ws/") || url.pathname === "/config" || url.pathname === "/healthz") return;
  // the licensed SMPL-X body, fetched with the access code in its URL: never into the offline cache
  if (url.pathname === "/avatar.glb") return;

  // icons and the manifest never change without a new cache version — serve them instantly
  const stable = url.pathname.startsWith("/static/icons/") || url.pathname === "/manifest.webmanifest";
  if (stable) {
    e.respondWith(caches.match(req).then(hit => hit || fetch(req).then(res => {
      const copy = res.clone();
      caches.open(V).then(c => c.put(req, copy));
      return res;
    })));
    return;
  }

  // everything else: the network is the truth, the cache is the safety net
  e.respondWith(
    fetch(req)
      .then(res => {
        if (res.ok) {
          const copy = res.clone();
          caches.open(V).then(c => c.put(req, copy));
        }
        return res;
      })
      .catch(() => caches.match(req).then(hit =>
        hit || (req.mode === "navigate"
          ? new Response(OFFLINE, { headers: { "Content-Type": "text/html; charset=utf-8" } })
          : Response.error())))
  );
});
