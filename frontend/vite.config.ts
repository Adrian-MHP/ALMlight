import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

// In development the API runs in the app container; Vite proxies /api to it.
export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    port: 5173,
    proxy: { "/api": { target: process.env.API_URL ?? "http://localhost:48080", changeOrigin: true } },
  },
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 1500 },
});
