const CACHE_NAME = "atm-pwa-v3";

const STATIC_ASSETS = [
    "/inicio",
    "/static/manifest.json",
    "/static/img/icon-192.png",
    "/static/img/icon-512.png"
];

// =====================================================
// INSTALL
// =====================================================

self.addEventListener("install", (event) => {
    self.skipWaiting();

    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            return cache.addAll(STATIC_ASSETS);
        })
    );
});

// =====================================================
// ACTIVATE
// =====================================================

self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches.keys().then((cacheNames) => {
            return Promise.all(
                cacheNames.map((cacheName) => {
                    if (cacheName !== CACHE_NAME) {
                        return caches.delete(cacheName);
                    }
                })
            );
        })
    );

    self.clients.claim();
});

// =====================================================
// FETCH
// =====================================================

self.addEventListener("fetch", (event) => {
    if (event.request.method !== "GET") {
        return;
    }

    event.respondWith(
        fetch(event.request)
            .then((networkResponse) => {
                if (
                    !networkResponse ||
                    networkResponse.status !== 200 ||
                    networkResponse.type !== "basic"
                ) {
                    return networkResponse;
                }

                const responseClone = networkResponse.clone();

                caches.open(CACHE_NAME).then((cache) => {
                    cache.put(event.request, responseClone);
                });

                return networkResponse;
            })
            .catch(() => {
                return caches.match(event.request).then((cachedResponse) => {
                    return cachedResponse || caches.match("/inicio");
                });
            })
    );
});