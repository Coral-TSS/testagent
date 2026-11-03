/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Build output is served by FastAPI from src/testagent/web (see architecture §10).
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../src/testagent/web",
    emptyOutDir: true,
    chunkSizeWarningLimit: 2500,
  },
  server: {
    port: 5173,
    // dev: run the backend (uv run testagent --no-browser), open http://localhost:5173/ and sign in
    proxy: { "/api": "http://127.0.0.1:8765" },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["src/test/setup.ts"],
    css: false,
    // AntD-heavy page tests take 5–8 s on a loaded Windows machine; default is 5 s
    testTimeout: 20000,
  },
});
