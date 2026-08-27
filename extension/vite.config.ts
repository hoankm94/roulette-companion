import { defineConfig } from "vitest/config";

/** Vitest only — production builds use vite.content + vite.background. */
export default defineConfig({
  publicDir: false,
  test: {
    environment: "jsdom",
  },
});
