/**
 * sw.js — Service Worker для склада
 * Стратегии:
 *  - Статика (CSS, JS, SVG) → Cache First (кеш навсегда)
 *  - HTML-страницы (/desktop/*, /login) → Network First (кеш как fallback)
 *  - API (/api/*) → Network Only (не кешируем, чтобы данные были свежими)
 *  - Офлайн-заглушка → Cache Only
 */

const CACHE = {
  STATIC: 'warehouse-static-v1',
  PAGES: 'warehouse-pages-v2',
  FALLBACK: 'warehouse-fallback-v1',
};

const STATIC_URLS = [
  '/static/manifest.json',
  '/static/icons/icon-192x192.svg',
  '/static/icons/icon-512x512.svg',
  '/static/js/dexie.js',
  '/static/js/db-cache.js',
  '/static/js/sync-worker.js',
  '/static/js/realtime.js',
  '/static/js/firebase-app-compat.js',
  '/static/js/firebase-firestore-compat.js',
  '/static/js/html5-qrcode.min.js',
  '/static/js/spa-router.js',
  '/static/js/desktop/dashboard.js',
  '/static/js/mobile/app.js',
  '/static/css/desktop.css',
  '/static/css/mobile.css',
  '/static/css/history.css',
];

const PAGE_PATTERNS = [
  '/',
  '/login',
  '/desktop/dashboard',
  '/desktop/parts_list',
  '/desktop/catalog',
  '/desktop/transactions',
  '/desktop/orders',
  '/desktop/history',
  '/desktop/users',
  '/desktop/import_export',
  '/desktop/part_detail',
  '/profile',
];

const FALLBACK_URL = '/static/offline.html';

// ==========================================
// УСТАНОВКА — кешируем статику
// ==========================================
self.addEventListener('install', (event) => {
  console.log('🛠️ SW: Установка...');
  event.waitUntil(
    Promise.all([
      // Кеш статики
      caches.open(CACHE.STATIC).then((cache) => {
        return cache.addAll(STATIC_URLS).catch((err) => {
          console.warn('⚠️ SW: Не удалось закешировать некоторые статические файлы:', err);
        });
      }),
      // Кеш страниц (базовые)
      caches.open(CACHE.PAGES).then((cache) => {
        return cache.addAll(PAGE_PATTERNS).catch((err) => {
          console.warn('⚠️ SW: Не удалось закешировать некоторые страницы:', err);
        });
      }),
      // Кеш заглушки
      caches.open(CACHE.FALLBACK).then((cache) => {
        return cache.add(FALLBACK_URL).catch(() => {});
      }),
    ]).then(() => {
      console.log('✅ SW: Кеш готов!');
      return self.skipWaiting();
    })
  );
});

// ==========================================
// АКТИВАЦИЯ — чистим старые кеши
// ==========================================
self.addEventListener('activate', (event) => {
  console.log('🔄 SW: Активация...');
  const validCaches = Object.values(CACHE);
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames
          .filter((name) => !validCaches.includes(name))
          .map((name) => {
            console.log(`🧹 SW: Удаляем старый кеш: ${name}`);
            return caches.delete(name);
          })
      );
    }).then(() => {
      console.log('✅ SW: Активирован!');
      return self.clients.claim();
    })
  );
});

// ==========================================
// ПЕРЕХВАТ ЗАПРОСОВ
// ==========================================
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Пропускаем не-GET и не наши URL
  if (request.method !== 'GET') return;
  if (url.origin !== self.location.origin) return;

  // 1. API и мобильные запросы — только сеть (свежие данные)
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/mobile/')) {
    return;
  }

  // 2. Статика (CSS, JS, SVG, иконки) — Cache First
  if (
    url.pathname.startsWith('/static/') &&
    (url.pathname.endsWith('.css') ||
     url.pathname.endsWith('.js') ||
     url.pathname.endsWith('.svg') ||
     url.pathname.endsWith('.json'))
  ) {
    event.respondWith(cacheFirst(request, CACHE.STATIC));
    return;
  }

  // 3. HTML страницы — Network First
  if (
    url.pathname === '/' ||
    url.pathname.startsWith('/login') ||
    url.pathname.startsWith('/desktop/') ||
    url.pathname.startsWith('/profile')
  ) {
    event.respondWith(networkFirst(request, CACHE.PAGES));
    return;
  }

  // 4. Всё остальное — Network First с fallback
  event.respondWith(networkFirst(request, CACHE.PAGES));
});

// ==========================================
// СТРАТЕГИИ КЕШИРОВАНИЯ
// ==========================================

/** Cache First: сначала кеш, если нет — сеть */
async function cacheFirst(request, cacheName) {
  const cached = await caches.match(request);
  if (cached) {
    return cached;
  }

  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(cacheName);
      cache.put(request, response.clone());
    }
    return response;
  } catch (error) {
    // Если нет сети и нет кеша
    const fallback = await caches.match(FALLBACK_URL);
    return fallback || new Response('Нет соединения', { status: 503 });
  }
}

/** Network First: сначала сеть, при ошибке — кеш */
async function networkFirst(request, cacheName) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(cacheName);
      cache.put(request, response.clone());
    }
    return response;
  } catch (error) {
    const cached = await caches.match(request);
    if (cached) {
      return cached;
    }
    const fallback = await caches.match(FALLBACK_URL);
    return fallback || new Response('Нет соединения', { status: 503 });
  }
}