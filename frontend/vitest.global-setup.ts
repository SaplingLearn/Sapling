// Runs once per `vitest` run: writes the Tailwind class -> declarations map
// that src/test-utils/twStyle.ts reads (jsdom applies no stylesheet).
import fs from "node:fs";
import path from "node:path";
import { buildClassMap } from "./scripts/codemods/tw-class-map.mjs";

export const TW_CLASS_MAP = path.resolve(__dirname, "node_modules/.cache/sapling/tw-class-map.json");

export default async function setup() {
  fs.mkdirSync(path.dirname(TW_CLASS_MAP), { recursive: true });
  fs.writeFileSync(TW_CLASS_MAP, JSON.stringify(await buildClassMap()));
}
