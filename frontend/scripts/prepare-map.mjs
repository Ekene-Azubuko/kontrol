import { copyFileSync, mkdirSync } from "node:fs";
import { resolve } from "node:path";

// MapLibre v6 ships an ES-module worker; serve its relative shared module locally.
const target = resolve("public/maplibre");
mkdirSync(target, { recursive: true });
for (const name of ["maplibre-gl-worker.mjs", "maplibre-gl-shared.mjs"]) {
  copyFileSync(resolve("node_modules/maplibre-gl/dist", name), resolve(target, name));
}
copyFileSync(resolve("node_modules/maplibre-gl/LICENSE.txt"), resolve(target, "LICENSE.txt"));
