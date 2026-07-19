import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";
import path from "node:path";
import { execFileSync } from "node:child_process";

// ビルド時刻 + git SHA を焼き込み、設定画面でどの版が動いているか確認できるようにする。
const BUILD_TIME = new Date().toISOString().replace("T", " ").slice(0, 16);
let GIT_SHA = process.env.GIT_SHA ?? "";
if (!GIT_SHA) {
  try {
    GIT_SHA = execFileSync("git", ["rev-parse", "--short", "HEAD"], { encoding: "utf8" }).trim();
  } catch {
    GIT_SHA = "unknown";
  }
}

export default defineConfig({
  define: {
    __ASCEND_BUILD__: JSON.stringify(BUILD_TIME),
    __ASCEND_SHA__: JSON.stringify(GIT_SHA),
  },
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["favicon.svg", "apple-touch-icon.png"],
      manifest: {
        name: "Ascend",
        short_name: "Ascend",
        description: "Ascend — 人生最適化 OS (tailnet only)",
        theme_color: "#0a0e14",
        background_color: "#0a0e14",
        display: "standalone",
        start_url: "/",
        scope: "/",
        lang: "ja",
        icons: [
          { src: "icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "icon-512.png", sizes: "512x512", type: "image/png" },
          { src: "icon-512-maskable.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
        ],
      },
      workbox: {
        navigateFallback: "/index.html",
        navigateFallbackDenylist: [/^\/(api|admin|healthz|ingest)/],
        globPatterns: ["**/*.{js,css,html,svg,png,woff2}"],
        // Web Push のハンドラを生成 SW に取り込む (public/push-sw.js)
        importScripts: ["push-sw.js"],
        // GET /api/* は stale-while-revalidate: 起動でキャッシュから即描画し、裏で更新。
        // Tailscale 外/圏外でも「最後に取れたデータ」が見える (オフライン対応)。
        // runtimeCaching の既定 method は GET なので、POST 系ミューテーションは対象外。
        // (ストリーミング/SSE エンドポイントは存在しないため全 GET を対象にして安全)
        runtimeCaching: [
          {
            urlPattern: /\/api\/.*$/,
            handler: "StaleWhileRevalidate",
            options: {
              cacheName: "ascend-api",
              expiration: { maxEntries: 300, maxAgeSeconds: 604800 },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
        ],
      },
    }),
  ],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  server: {
    proxy: {
      "/api": "http://localhost:8000",
      "/admin": "http://localhost:8000",
      "/healthz": "http://localhost:8000",
    },
  },
});
