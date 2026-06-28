import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";
import path from "node:path";

export default defineConfig({
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
        // API レスポンスはキャッシュしない (常に最新を取りに行く)
        navigateFallback: "/index.html",
        navigateFallbackDenylist: [/^\/(api|admin|healthz|ingest)/],
        globPatterns: ["**/*.{js,css,html,svg,png,woff2}"],
        // Web Push のハンドラを生成 SW に取り込む (public/push-sw.js)
        importScripts: ["push-sw.js"],
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
