import { resolve } from "node:path";
import { defineConfig, type UserConfig } from "vite";
import { copyExtensionStatic } from "./vite.shared";

/** Service worker may be ES module (manifest background.type = module). */
export default defineConfig({
  publicDir: false,
  build: {
    outDir: "dist",
    emptyOutDir: false,
    cssCodeSplit: false,
    rollupOptions: {
      input: resolve(__dirname, "src/background/service-worker.ts"),
      output: {
        entryFileNames: "background/service-worker.js",
        format: "es",
        inlineDynamicImports: true,
      },
    },
  },
  plugins: [copyExtensionStatic()],
} satisfies UserConfig);
