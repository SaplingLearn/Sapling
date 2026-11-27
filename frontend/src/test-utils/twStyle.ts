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
    const props = Array.from({ length: inline.length }, (_, i) => inline[i]);
    const isShorthand = (prop: string) => props.some((p) => p !== prop && p.startsWith(`${prop}-`));
    // Shorthands first, then longhands, so a longhand React set after its
    // shorthand still wins. jsdom also lists a shorthand it composed from
    // longhands; one holding var() can't be split again, so it is skipped
    // and its longhands carry the values.
    for (const prop of [...props.filter(isShorthand), ...props.filter((p) => !isShorthand(p))]) {
      const value = inline.getPropertyValue(prop);
      if (value === "" || (isShorthand(prop) && value.includes("var("))) continue;
      probe.style.setProperty(prop, value);
    }
  }
  return probe.style;
}
