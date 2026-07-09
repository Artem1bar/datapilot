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
        // Overridable so the E2E harness can point at its own API instance.
        target: process.env.VITE_PROXY_TARGET || "http://localhost:8000",
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
    // userEvent interaction tests run slower under coverage instrumentation and
    // CI load; 5s (the default) flakes. 15s gives headroom without masking hangs.
    testTimeout: 15_000,
    coverage: {
      provider: "v8",
      reporter: ["text-summary", "lcov"],
      // `include` drives which files are measured; in vitest 4 every matching
      // file counts (not just those a test imports), so untested modules can't
      // hide and the total reflects real coverage.
      include: ["src/**/*.{ts,tsx}"],
      exclude: [
        "src/**/*.test.{ts,tsx}",
        "src/test/**",
        "src/main.tsx",
        "src/vite-env.d.ts",
        "src/**/*.d.ts",
        "src/types/**",
        "src/components/ui/**", // vendored shadcn/radix primitives
      ],
      // Regression floor — honest to the current suite, ratcheted up as the
      // dark areas (Chat routing, hooks) get tests. Not aspirational: CI fails
      // below these.
      thresholds: {
        statements: 15,
        branches: 12,
        functions: 20,
        lines: 15,
      },
    },
  },
});
