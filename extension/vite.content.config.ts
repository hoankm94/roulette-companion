import { resolve } from "node:path";
import { defineConfig, type UserConfig } from "vite";

/** Content scripts must be classic JS — no import/export. */
export default defineConfig({
  publicDir: false,
  build: {
    outDir: "dist",
    emptyOutDir: true,
    cssCodeSplit: false,
    rollupOptions: {
      input: resolve(__dirname, "src/content/content-script.ts"),
      output: {
        entryFileNames: "content/content-script.js",
        format: "iife",
        name: "RouletteCompanionContent",
        inlineDynamicImports: true,
      },
    },
  },
} satisfies UserConfig);
