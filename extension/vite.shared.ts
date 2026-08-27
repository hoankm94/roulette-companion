import { copyFileSync, mkdirSync, existsSync, cpSync } from "node:fs";
import { resolve } from "node:path";

export function copyExtensionStatic() {
  return {
    name: "copy-extension-static",
    closeBundle() {
      const dist = resolve(__dirname, "dist");
      copyFileSync(resolve(__dirname, "manifest.json"), resolve(dist, "manifest.json"));
      const iconsSrc = resolve(__dirname, "icons");
      const iconsDest = resolve(dist, "icons");
      if (existsSync(iconsSrc)) {
        mkdirSync(iconsDest, { recursive: true });
        cpSync(iconsSrc, iconsDest, { recursive: true });
      }
    },
  };
}
