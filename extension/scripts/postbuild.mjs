import { copyFileSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const dist = resolve(root, "dist");

mkdirSync(dist, { recursive: true });
copyFileSync(resolve(root, "manifest.json"), resolve(dist, "manifest.json"));

// Minimal valid 48x48 and 128x128 PNG (solid #3DB8FF) — pre-encoded tiny PNGs
const ICON_48_BASE64 =
  "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAARHAAAAMUlEQVRoge3OMQEAAAgDINc/9K3hL2QAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAADgWQN1AAE3yI1nAAAAAElFTkSuQmCC";
const ICON_128_BASE64 =
  "iVBORw0KGgoAAAANSUhEUgAAAIAAAACACAYAAADDPmHLAAAANUlEQVR4nO3BAQEAAACCqP9b9hPoAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAADwZxYAAAF/8i1nAAAAAElFTkSuQmCC";

const iconsDir = resolve(dist, "icons");
mkdirSync(iconsDir, { recursive: true });
writeFileSync(resolve(iconsDir, "icon48.png"), Buffer.from(ICON_48_BASE64, "base64"));
writeFileSync(resolve(iconsDir, "icon128.png"), Buffer.from(ICON_128_BASE64, "base64"));

console.log("postbuild: manifest and icons copied to dist/");
