'use strict';
// Only the PUBLIC shell belongs in CacheStorage. Private photos/data are owned
// by the frontend's IndexedDB flow, never by this service worker.
const CACHE_PREFIX = 'nosotros-shell-';
const CACHE = `${CACHE_PREFIX}v3`;
const SHELL = ['/', '/index.html', '/sync.js', '/manifest.json', '/icon-192.png', '/icon-512.png'];
const ALLOWED = new Set(SHELL);
const cacheable = response => response.status === 200 && response.type !== 'opaque' && !response.redirected;

self.addEventListener('install', event => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    // Fail installation rather than install a partial/offline login-error shell.
    for (const path of SHELL) {
      const response = await fetch(new Request(path, {cache: 'reload', credentials: 'omit'}));
      if (!cacheable(response)) throw new Error(`Public shell unavailable: ${path}`);
      await cache.put(path, response);
    }
    await self.skipWaiting();
  })());
});
self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) {
      if (key.startsWith(CACHE_PREFIX) && key !== CACHE) await caches.delete(key);
    }
    await self.clients.claim();
  })());
});
self.addEventListener('fetch', event => {
  const request = event.request;
  const url = new URL(request.url);
  // Strict allowlist, including navigations: API/uploads/other paths always go
  // straight to the network. Never return index.html for a protected route.
  if (request.method !== 'GET' || url.origin !== self.location.origin ||
      !ALLOWED.has(url.pathname) || url.search) return;
  event.respondWith((async () => {
    const cache = await caches.open(CACHE);
    try {
      const response = await fetch(request);
      // A gateway can remain online while Python is down. Only public shell gets fallback.
      if (response.status >= 500) throw new Error("Servidor temporalmente no disponible");
      // Authentication failures are NEVER transformed into cached content.
      if (cacheable(response)) await cache.put(url.pathname, response.clone());
      return response;
    } catch (error) {
      const offline = request.mode === 'navigate'
        ? await cache.match('/index.html')
        : await cache.match(url.pathname);
      if (offline) return offline;
      throw error;
    }
  })());
});
