// Map every Tailwind utility class used under src/ to the declarations it
// sets, for unit tests: jsdom applies no stylesheet, so a test that reads an
// element's style needs to know what its classes would set.
//
//   import { buildClassMap } from "./tw-class-map.mjs"
//   buildClassMap() -> { "p-3": { padding: "12px" }, "text-text-dim": { color: "var(--text-dim)" }, ... }
//
// Values are written the way the inline styles they replaced were:
// Tailwind's spacing calc() becomes px, theme aliases become the token they
// point at (var(--fs-md) stays a token, as an inline var() would have).
// Only plain single-class rules are kept; variants (hover:, md:) are not
// what a unit test can see anyway.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { compile } from "@tailwindcss/node";
import { Scanner } from "@tailwindcss/oxide";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "../..");

const FONT_WEIGHTS = { thin: "100", extralight: "200", light: "300", normal: "400", medium: "500", semibold: "600", bold: "700", extrabold: "800", black: "900" };
// Inline sizes and radii were mostly numbers; a test expecting "13px" should
// see 13px whether the class says text-md or text-[13px].
const TOKEN_PX = Object.fromEntries(
  [...fs.readFileSync(path.join(root, "src/styles/tokens.css"), "utf8").matchAll(/^\s*--((?:fs|r)-[a-z0-9]+):\s*(\d+px);/gm)].map((m) => [m[1], m[2]]),
);

function unescapeSelector(sel) {
  return sel.replace(/\\([0-9a-fA-F]{1,6}\s?)/g, (_, hex) => String.fromCodePoint(parseInt(hex, 16))).replace(/\\(.)/g, "$1");
}

export async function buildClassMap() {
  const entry = path.join(root, "src/app/globals.css");
  const compiler = await compile(fs.readFileSync(entry, "utf8"), { base: path.dirname(entry), onDependency() {} });
  const scanner = new Scanner({ sources: [{ base: path.join(root, "src"), pattern: "**/*", negated: false }] });
  const css = compiler.build(scanner.scan());
  const start = css.indexOf("@layer utilities {");
  const utilities = start >= 0 ? css.slice(start) : "";
  const map = {};
  // top-level rules inside the utilities layer: "  .sel {\n    decl;\n  }"
  const rule = /^ {2}\.((?:\\.|[^\s{,:])+)\s*\{\n((?: {4}[^\n]*\n)+?) {2}\}/gm;
  for (const m of utilities.matchAll(rule)) {
    const cls = unescapeSelector(m[1]);
    const decls = {};
    for (const line of m[2].split("\n")) {
      const d = /^ {4}([a-z-]+):\s*(.+);$/.exec(line);
      if (!d) continue;
      let v = d[2].trim();
      v = v.replace(/calc\(var\(--spacing\)\s*\*\s*(-?[\d.]+)\)/g, (_, n) => `${parseFloat(n) * 4}px`);
      v = v.replace(/calc\(var\(--spacing\)\s*\*\s*-(-?[\d.]+)\)/g, (_, n) => `${-parseFloat(n) * 4}px`);
      v = v.replace(/^calc\((-?[\d.]+px)\s*\*\s*-1\)$/, (_, x) => `-${x}`);
      v = v.replace(/var\(--tw-border-style\)/g, "solid");
      v = v.replace(/var\(--font-weight-([a-z]+)\)/g, (m, w) => FONT_WEIGHTS[w] ?? m);
      v = v.replace(/var\(--(fs|r)-([a-z0-9]+)\)/g, (m, kind, n) => TOKEN_PX[`${kind}-${n}`] ?? m);
      if (d[1] === "opacity" && /%$/.test(v)) v = String(parseFloat(v) / 100);
      if (d[1].startsWith("--tw-")) continue;
      const logical = /^(padding|margin)-(block|inline)$/.exec(d[1]);
      if (logical) {
        const [a, b] = logical[2] === "block" ? ["top", "bottom"] : ["left", "right"];
        decls[`${logical[1]}-${a}`] = v;
        decls[`${logical[1]}-${b}`] = v;
        continue;
      }
      decls[d[1]] = v;
    }
    if (Object.keys(decls).length) map[cls] = decls;
  }
  return map;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const out = process.argv[2];
  const map = await buildClassMap();
  if (out) fs.writeFileSync(out, JSON.stringify(map));
  else console.log(Object.keys(map).length, "classes");
}
