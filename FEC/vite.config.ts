import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  define: { __BUILD_ID__: JSON.stringify(String(Date.now())) },
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8010",
      "/media": "http://127.0.0.1:8010",
    },
  },
});
