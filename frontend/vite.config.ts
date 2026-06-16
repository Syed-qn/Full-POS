/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  // Resolve the API proxy target. Priority: shell env (VITE_API_PROXY) →
  // .env.local (VITE_API_PROXY=…) → local backend on :9001. Point it at the
  // Render URL in frontend/.env.local to develop the UI against live data
  // without running a backend locally. 8000/8001 fall in a Windows reserved
  // port range after Docker restarts, hence :9001 for the local default.
  const env = loadEnv(mode, process.cwd(), "");
  const apiTarget =
    process.env.VITE_API_PROXY ?? env.VITE_API_PROXY ?? "http://localhost:9001";

  return {
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: apiTarget,
        changeOrigin: true,
        secure: true,
      },
    },
    headers: {
      "X-Content-Type-Options": "nosniff",
      "X-Frame-Options": "DENY",
      "Referrer-Policy": "no-referrer",
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: true,
    exclude: ["e2e/**", "node_modules/**"],
  },
  };
});
