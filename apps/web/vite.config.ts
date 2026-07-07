import { defineConfig } from "vitest/config";
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
  build: {
    rollupOptions: {
      output: {
        // Split large, independent vendor groups into their own cacheable
        // chunks so the initial bundle stays under the 500 kB warning. React
        // and its ecosystem stay together to avoid duplicate-context issues;
        // recharts is lazy-loaded at its call site (see ChartPanel).
        manualChunks(id: string) {
          if (!id.includes("node_modules")) return undefined;
          if (id.includes("@clerk")) return "clerk";
          if (
            /[\\/](react-markdown|remark-|micromark|mdast|hast|unist|property-information|comma-separated-tokens|space-separated-tokens|vfile|unified|bail|trough|decode-named-character-reference|character-entities|zwitch|longest-streak|html-url-attributes|devlop|estree)/.test(
              id,
            )
          ) {
            return "markdown";
          }
          if (
            /[\\/](react|react-dom|react-router|react-router-dom|scheduler)[\\/]/.test(
              id,
            )
          ) {
            return "react-vendor";
          }
          return undefined;
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    globals: true,
  },
});
