import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const backend = process.env.EMNEKLAR_BACKEND ?? "http://127.0.0.1:8770";

export default defineConfig({
  plugins: [react()],
  server: {
    // The dev server is local-only, like the backend.
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: backend, changeOrigin: false },
      "/auth": { target: backend, changeOrigin: false },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    // Everything is bundled locally; nothing is loaded from a CDN at runtime.
    assetsInlineLimit: 0,
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    exclude: ["e2e/**", "node_modules/**"],
  },
});
