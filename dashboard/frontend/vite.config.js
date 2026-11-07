import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath } from "node:url";
export default defineConfig(({ mode }) => ({
  plugins: [react(), ...(mode === "legacy" ? [tailwindcss()] : [])],
  resolve: {
    alias: {
      "selected-app": fileURLToPath(
        new URL(
          mode === "legacy" ? "./src/legacy-main.jsx" : "./src/public-main.jsx",
          import.meta.url,
        ),
      ),
    },
  },
  build: { outDir: mode === "legacy" ? "dist-legacy" : "dist" },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/media": "http://127.0.0.1:8000",
    },
  },
}));
