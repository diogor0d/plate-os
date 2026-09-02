import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["apple-touch-icon.png"],
      manifest: {
        name: "PlateOS",
        short_name: "PlateOS",
        description: "Self-hosted nutrition & body recomposition tracker",
        display: "standalone",
        orientation: "portrait",
        background_color: "#09090b",
        theme_color: "#09090b",
        icons: [
          { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "/icon-512.png", sizes: "512x512", type: "image/png" }
        ]
      },
      workbox: {
        importScripts: ["push-sw.js"],
        globPatterns: ["**/*.{js,css,html,svg,png,woff2}"],
        navigateFallback: "/index.html",
        navigateFallbackDenylist: [/^\/api\//]
      }
    })
  ],
  server: {
    proxy: {
      "/api": "http://localhost:8000"
    }
  }
});
