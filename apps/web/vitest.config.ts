import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src")
    }
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup/vitest.setup.tsx"],
    include: ["tests/components/**/*.test.{ts,tsx}"],
    coverage: {
      provider: "v8",
      reporter: ["text", "json", "html"],
      reportsDirectory: "../../.harness/coverage/web-components",
      thresholds: {
        statements: 0,
        branches: 0,
        functions: 0,
        lines: 0
      },
      include: ["src/**/*.{ts,tsx}"],
      exclude: [
        "src/**/*.d.ts",
        "src/app/**/page.tsx",
        "src/app/layout.tsx",
        "src/generated/**"
      ]
    }
  }
});
