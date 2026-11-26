/**
 * The app's whole stylesheet as text, for tests that pin a rule in it.
 *
 * src/app/globals.css is only the entry: it @imports src/styles/{tokens,
 * theme,base,components}.css and app/library-notes.css. This follows those
 * local imports (one level, in order) so a test reads every rule the app
 * ships, wherever it now lives.
 */
import fs from "node:fs";
import path from "node:path";

export const GLOBALS_CSS = path.resolve(__dirname, "../app/globals.css");

export function readAppCss(): string {
  const entry = fs.readFileSync(GLOBALS_CSS, "utf8");
  const dir = path.dirname(GLOBALS_CSS);
  return entry.replace(/^@import\s+"(\.{1,2}\/[^"]+)"[^;]*;$/gm, (_, rel: string) =>
    fs.readFileSync(path.resolve(dir, rel), "utf8"),
  );
}

/** Every local stylesheet the entry imports, plus the entry itself. */
export function appCssFiles(): string[] {
  const entry = fs.readFileSync(GLOBALS_CSS, "utf8");
  const dir = path.dirname(GLOBALS_CSS);
  return [GLOBALS_CSS, ...[...entry.matchAll(/^@import\s+"(\.{1,2}\/[^"]+)"/gm)].map((m) => path.resolve(dir, m[1]))];
}
