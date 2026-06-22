import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: parseInt(process.env.PORT || "5174", 10),
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        timeout: 120_000, // 2 min for AI calls
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    globals: true,
  },
});
