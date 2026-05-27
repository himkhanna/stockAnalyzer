import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Bind to 0.0.0.0 so the dev server is reachable from other devices
    // on the same LAN or via Tailscale. The /api proxy still hits
    // localhost (the backend on the same machine) — Vite proxies
    // server-side — so the backend can stay bound to 127.0.0.1.
    host: true,
    proxy: {
      "/api": {
        target: "http://localhost:8765",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
});
