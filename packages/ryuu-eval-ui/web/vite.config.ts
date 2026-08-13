import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: "./",
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  build: {
    outDir: "../src/ryuu_eval_ui/dist",
    emptyOutDir: true,
    manifest: true,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("recharts")) return "charts";
          if (id.includes("@tanstack/react-query")) return "query";
          if (id.includes("node_modules/react") || id.includes("react-router-dom")) return "vendor";
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8001",
        changeOrigin: true,
      },
    },
  },
});
