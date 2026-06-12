const CACHE_NAME = 'wms-react-pwa-v1';
const ASSETS_TO_CACHE = [
  '/',
  '/manifest.json',
  '/favicon.svg',
  '/static/icons/icon-192x192.svg',
  '/static/icons/icon-512x512.svg'
];

// Installation phase: pre-cache stable files
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(ASSETS_TO_CACHE);
    }).then(() => {
      return self.skipWaiting();
    })
  );
});

// Activation phase: purge older caches
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => {
          if (key !== CACHE_NAME) {
            return caches.delete(key);
          }
        })
      );
    }).then(() => {
      return self.clients.claim();
    })
  );
});

// Intercept fetch requests
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // 1. Only process GET requests from our origin
  if (request.method !== 'GET' || url.origin !== self.location.origin) {
    return;
  }

  // 2. Do not cache any API requests
  if (url.pathname.startsWith('/api/')) {
    return;
  }

  // 3. For compiled asset scripts and stylesheets, use Cache-First strategy (Dynamic cache)
  if (url.pathname.includes('/assets/')) {
    event.respondWith(
      caches.match(request).then((cachedResponse) => {
        if (cachedResponse) {
          return cachedResponse;
        }

        return fetch(request).then((networkResponse) => {
          if (networkResponse && networkResponse.status === 200) {
            const cacheCopy = networkResponse.clone();
            caches.open(CACHE_NAME).then((cache) => {
              cache.put(request, cacheCopy);
            });
          }
          return networkResponse;
        }).catch(() => {
          // Return cached index.html as a absolute fallback if a main JS bundle fails
          return caches.match('/');
        });
      })
    );
    return;
  }

  // 4. For page navigation paths (e.g. /desktop/dashboard, /login), use Network-First,
  // falling back to '/' (index.html) so the React router can resolve routing offline.
  event.respondWith(
    fetch(request).catch(() => {
      // Offline fallback: try to serve the exact path cache, or return the shell index.html
      return caches.match(request).then((cachedResponse) => {
        return cachedResponse || caches.match('/');
      });
    })
  );
});
