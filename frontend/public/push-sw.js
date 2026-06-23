/* Web Push のハンドラ。Workbox 生成の Service Worker に importScripts で取り込む。
 * (vite.config.ts の workbox.importScripts: ["push-sw.js"])
 *
 * サーバ (app/notifications) が送る payload:
 *   { title, body, tag, url, priority }  priority: "critical" | "high" | "normal"
 */

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (e) {
    data = {};
  }
  const title = data.title || "ヘルスケア";
  const options = {
    body: data.body || "",
    tag: data.tag || undefined,
    data: { url: data.url || "/" },
    icon: "/icon-192.png",
    badge: "/icon-192.png",
    // critical は明示的に消すまで残す (危険アラート)
    requireInteraction: data.priority === "critical",
    renotify: Boolean(data.tag),
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((wins) => {
      for (const w of wins) {
        if ("focus" in w) {
          w.focus();
          if ("navigate" in w) {
            try {
              w.navigate(url);
            } catch (e) {
              /* navigate は同一オリジンのみ。失敗は無視 */
            }
          }
          return;
        }
      }
      if (self.clients.openWindow) return self.clients.openWindow(url);
    }),
  );
});
