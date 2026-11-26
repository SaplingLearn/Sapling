/**
 * twStyle(el): the element's style as its Tailwind classes and its inline
 * style set it together, as a CSSStyleDeclaration a test can read
 * (`twStyle(row).minHeight`). jsdom applies no stylesheet, so after the
 * Tailwind migration `el.style` alone only shows runtime values.
 *
 * The class -> declarations map is built once per run by
 * vitest.global-setup.ts from the real stylesheet.
 */
import fs from "node:fs";
import path from "node:path";

type ClassMap = Record<string, Record<string, string>>;
let MAP: ClassMap | null = null;

function classMap(): ClassMap {
  if (!MAP) {
    const file = path.resolve(__dirname, "../../node_modules/.cache/sapling/tw-class-map.json");
    MAP = fs.existsSync(file) ? (JSON.parse(fs.readFileSync(file, "utf8")) as ClassMap) : {};
  }
  return MAP;
}

export function twStyle(el: Element): CSSStyleDeclaration {
  const map = classMap();
  const probe = document.createElement("div");
  for (const cls of (el.getAttribute("class") ?? "").split(/\s+/)) {
    const decls = map[cls];
    if (!decls) continue;
    for (const [prop, value] of Object.entries(decls)) probe.style.setProperty(prop, value);
  }
  const inline = (el as HTMLElement).style;
  if (inline) {
    for (let i = 0; i < inline.length; i++) {
      const prop = inline[i];
      probe.style.setProperty(prop, inline.getPropertyValue(prop));
    }
  }
  return probe.style;
}
