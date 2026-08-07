/**
 * vite.config.js
 * --------------
 * Vite build configuration for Atomwalk HMS frontend.
 *
 * Environment variables (create a .env.local file — never commit secrets):
 *   VITE_API_BASE_URL   — Django backend URL (default: http://localhost:8000)
 *
 * Path aliases:
 *   @  → src/    (e.g. import Button from "@/components/common/Button")
 */

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "path";

export default defineConfig({
  plugins: [react()],

  resolve: {
    alias: {
      "@": resolve(__dirname, "src"),
    },
  },

  server: {
    port: 3000,
    // Proxy API calls to Django during development so CORS isn't an issue
    proxy: {
      "/api": {
        target: process.env.VITE_API_BASE_URL || "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },

  build: {
    outDir: "dist",
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ["react", "react-dom", "react-router-dom"],
          icons:  ["react-icons", "lucide-react"],
        },
      },
    },
  },
});
