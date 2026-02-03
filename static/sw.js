// Service Worker for Push Notifications
// Home Assistant themed push notifications for Telegram monitoring
// Compatible with Safari, Chrome, Firefox, and Edge

const CACHE_NAME = 'ha-notifications-v6';

// Install event
self.addEventListener('install', (event) => {
    console.log('[Service Worker] Installing v6...');
    // Activate immediately, don't wait for old service worker to close
    self.skipWaiting();
});

// Log service worker state for debugging
console.log('[Service Worker] Script loaded at', new Date().toLocaleTimeString());

// Helper function to update badge
async function updateBadge() {
    try {
        const response = await fetch('/api/badge/count');
        if (!response.ok) {
            console.log('[Service Worker] Badge API not available');
            return;
        }

        const data = await response.json();
        const badgeCount = data.count || 0;

        if ('setAppBadge' in navigator) {
            if (badgeCount > 0) {
                await navigator.setAppBadge(badgeCount);
                console.log('[Service Worker] Badge updated to:', badgeCount);
            } else {
                await navigator.clearAppBadge();
                console.log('[Service Worker] Badge cleared');
            }
        }
    } catch (error) {
        console.log('[Service Worker] Error updating badge:', error);
    }
}

// Activate event
self.addEventListener('activate', (event) => {
    console.log('[Service Worker] Activating v6...');
    // Claim all clients immediately
    event.waitUntil(
        Promise.all([
            self.clients.claim(),
            // Clean up old caches
            caches.keys().then(cacheNames => {
                return Promise.all(
                    cacheNames.map(cacheName => {
                        if (cacheName !== CACHE_NAME) {
                            console.log('[Service Worker] Deleting old cache:', cacheName);
                            return caches.delete(cacheName);
                        }
                    })
                );
            }),
            // Update badge on activation - with delay to ensure API is ready
            new Promise(resolve => setTimeout(resolve, 1000)).then(() => updateBadge())
        ])
    );
    console.log('[Service Worker] Activated and ready for push notifications');
});

// Push notification event
self.addEventListener('push', (event) => {
    console.log('[Service Worker] Push received at', new Date().toLocaleTimeString());

    let notificationData = {
        title: 'Home Assistant',
        body: 'New automation event',
        icon: '/static/ha-icon.svg',
        badge: '/static/ha-icon.svg',
        tag: 'ha-activity',
        requireInteraction: false,
        silent: false,
        data: {
            url: '/messages',
            timestamp: Date.now()
        },
        badgeCount: 0
    };

    if (event.data) {
        try {
            const data = event.data.json();
            notificationData = {
                ...notificationData,
                ...data
            };
            console.log('[Service Worker] Push data parsed:', notificationData.title);
        } catch (e) {
            console.error('[Service Worker] Failed to parse push data:', e);
        }
    }

    // Set app badge count (red number on icon)
    const badgeCount = notificationData.badgeCount || 0;
    const setBadge = async () => {
        if ('setAppBadge' in navigator) {
            try {
                if (badgeCount > 0) {
                    await navigator.setAppBadge(badgeCount);
                    console.log('[Service Worker] Badge set to:', badgeCount);
                } else {
                    await navigator.clearAppBadge();
                }
            } catch (e) {
                console.log('[Service Worker] Badge API error:', e);
            }
        }
    };

    // Show notification with retry logic
    const showNotificationWithRetry = async () => {
        let attempts = 0;
        const maxAttempts = 3;

        while (attempts < maxAttempts) {
            try {
                await self.registration.showNotification(notificationData.title, notificationData);
                console.log('[Service Worker] Notification shown successfully');
                return;
            } catch (e) {
                attempts++;
                console.error(`[Service Worker] Failed to show notification (attempt ${attempts}/${maxAttempts}):`, e);
                if (attempts < maxAttempts) {
                    // Wait before retry (exponential backoff)
                    await new Promise(resolve => setTimeout(resolve, 1000 * attempts));
                }
            }
        }
        throw new Error('Failed to show notification after ' + maxAttempts + ' attempts');
    };

    event.waitUntil(
        Promise.all([
            showNotificationWithRetry().catch(e => console.error('[Service Worker] Notification error:', e)),
            setBadge().catch(e => console.error('[Service Worker] Badge error:', e)),
            // Also update badge from API to ensure accuracy
            updateBadge().catch(e => console.error('[Service Worker] Badge API sync error:', e))
        ])
    );
});

// Notification click event - do nothing to keep it secret
self.addEventListener('notificationclick', (event) => {
    console.log('[Service Worker] Notification clicked');
    event.notification.close();

    // Do nothing - per user request to keep it secret
    // No window opening, no navigation
    event.waitUntil(Promise.resolve());
});

// Background sync for notifications
self.addEventListener('sync', (event) => {
    if (event.tag === 'check-messages') {
        event.waitUntil(checkForNewMessages());
    }
});

async function checkForNewMessages() {
    try {
        // This will be called periodically to check for new messages
        // The actual notification will be triggered from the main page
        console.log('[Service Worker] Checking for new messages...');
    } catch (error) {
        console.error('[Service Worker] Error checking messages:', error);
    }
}

// Periodically update badge (every 30 seconds)
// This also serves as a keep-alive mechanism to prevent service worker suspension
setInterval(() => {
    updateBadge();
}, 30000);

// Keep-alive mechanism: Wake up every 20 seconds to prevent iOS suspension
// On iOS Safari, service workers can be suspended after ~30 minutes of inactivity
// This periodic task helps keep the service worker active
setInterval(() => {
    // Lightweight operation to keep worker alive
    console.log('[Service Worker] Keep-alive ping at', new Date().toLocaleTimeString());
}, 20000);

// Periodic sync registration attempt (if supported)
// This ensures notifications can be delivered even if the service worker was suspended
self.addEventListener('periodicsync', (event) => {
    if (event.tag === 'badge-update') {
        event.waitUntil(updateBadge());
    }
});

// Message event handler for communication with the page
self.addEventListener('message', (event) => {
    console.log('[Service Worker] Message received:', event.data);

    if (event.data.type === 'BADGE_UPDATE') {
        // Immediate badge update requested from page
        event.waitUntil(updateBadge());
    } else if (event.data.type === 'KEEP_ALIVE') {
        // Keep-alive ping from page
        event.ports[0].postMessage({ status: 'alive' });
    } else if (event.data.type === 'SYNC_STATE') {
        // Sync state with page
        event.waitUntil(
            updateBadge().then(() => {
                event.ports[0].postMessage({ status: 'synced' });
            })
        );
    }
});
