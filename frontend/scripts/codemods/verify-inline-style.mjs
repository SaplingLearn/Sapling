#!/usr/bin/env node
// Prove the inline-style codemod changed no styles.
//
//   node scripts/codemods/inline-style-to-tailwind.mjs --dry --log cases.json
//   node scripts/codemods/verify-inline-style.mjs cases.json
//
// For each converted element, Chromium renders the same tag twice in the same
// parent: once with the original declarations as an inline style, once with
// the generated classes against the real stylesheet (src/app/globals.css).
// Every computed property must match. Exits 1 on any difference.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { kebab } from "./css-to-tailwind.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "../..");
const cases = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));

const seen = new Map();
for (const c of cases) {
  const key = JSON.stringify([c.tag, c.decls, c.classes]);
  if (!seen.has(key)) seen.set(key, { ...c, files: new Set([c.file]) });
  else seen.get(key).files.add(c.file);
}
const uniq = [...seen.values()];

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "twverify-"));
const cands = [...new Set(uniq.flatMap((c) => c.classes))];
fs.writeFileSync(path.join(tmp, "c.json"), JSON.stringify(cands));
execFileSync("node", [path.join(here, "twbuild.mjs"), path.join(root, "src/app/globals.css"), path.join(tmp, "c.json"), path.join(tmp, "out.css")]);
const css = fs.readFileSync(path.join(tmp, "out.css"), "utf8");

const SVG = new Set("svg g path rect circle ellipse line polyline polygon text tspan defs linearGradient radialGradient stop clipPath mask pattern use foreignObject marker symbol image".split(" "));
const styleText = (decls) => decls.map(([p, v]) => `${kebab(p)}: ${v}`).join("; ");

// PW_CHROMIUM: a Chromium binary, when the installed Playwright has no browser
const browser = await chromium.launch(process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {});
const page = await browser.newPage();
await page.setContent(`<!doctype html><html><head><style>
:root { --font-suse: "SUSE"; --font-aleo: "Aleo"; }
${css}
</style></head><body><div id="root"></div></body></html>`);

const results = await page.evaluate(({ cases, svgTags }) => {
  const NS = "http://www.w3.org/2000/svg";
  const host = document.getElementById("root");
  const out = [];
  const make = (tag) => (svgTags.includes(tag) ? document.createElementNS(NS, tag) : document.createElement(tag));
  cases.forEach((c, i) => {
    const wrap = document.createElement("div");
    wrap.style.cssText = "position:relative;width:800px;height:600px;font-size:14px";
    const parentA = svgTags.includes(c.tag) && c.tag !== "svg" ? document.createElementNS(NS, "svg") : document.createElement("div");
    const parentB = parentA.cloneNode();
    const a = make(c.tag), b = make(c.tag);
    a.setAttribute("style", c.style);
    b.setAttribute("class", c.classes.join(" "));
    parentA.appendChild(a); parentB.appendChild(b);
    wrap.append(parentA, parentB);
    host.appendChild(wrap);
    const ca = getComputedStyle(a), cb = getComputedStyle(b);
    const diffs = [];
    for (let k = 0; k < ca.length; k++) {
      const p = ca[k];
      if (p.startsWith("--")) continue;
      const va = ca.getPropertyValue(p), vb = cb.getPropertyValue(p);
      if (va !== vb) diffs.push([p, va, vb]);
    }
    if (diffs.length) {
      const widths = {};
      for (const [p] of diffs) { const w = p.replace(/-(style|color)$/, "-width"); widths[w] = ca.getPropertyValue(w) === cb.getPropertyValue(w) ? ca.getPropertyValue(w) : "?"; }
      out.push({ i, diffs, widths });
    }
    host.removeChild(wrap);
  });
  return out;
}, { cases: uniq.map((c) => ({ tag: c.tag, style: styleText(c.decls), classes: c.classes })), svgTags: [...SVG] });
await browser.close();

// Known, intended differences: a stack named by its leading webfont drops
// system fallbacks that only show if the webfont fails to load.
// Tailwind's shadow utilities stack transparent ring/inset layers, which draw
// nothing. A pill radius past 999px is the same pill. A border side with zero
// width draws nothing whatever its style.
const firstFace = (v) => v.split(",")[0].trim().replace(/['"]/g, "");
const visibleShadows = (v) => v === "none" ? "" : v.split(/,(?![^(]*\))/).map((s) => s.trim()).filter((s) => !/^rgba\(0, 0, 0, 0\) 0px 0px 0px 0px$/.test(s)).join(", ");
const ALLOWED = (p, va, vb, a) =>
  (p === "font-family" && firstFace(va) === firstFace(vb)) ||
  (p === "box-shadow" && visibleShadows(va) === visibleShadows(vb)) ||
  (/radius$/.test(p) && parseFloat(va) >= 999 && parseFloat(vb) >= 999) ||
  (/^border-.*-(style|color)$/.test(p) && a[p.replace(/-(style|color)$/, "-width")] === "0px");

let bad = 0;
for (const r of results) {
  const diffs = r.diffs.filter(([p, a, b]) => !ALLOWED(p, a, b, r.widths));
  if (!diffs.length) continue;
  bad++;
  const c = uniq[r.i];
  if (bad <= 60) {
    console.log(`\n✗ <${c.tag}> ${[...c.files][0]}${c.files.size > 1 ? ` (+${c.files.size - 1})` : ""}`);
    console.log(`  style:   ${styleText(c.decls)}`);
    console.log(`  classes: ${c.classes.join(" ")}`);
    for (const [p, a, b] of diffs.slice(0, 6)) console.log(`    ${p}: ${a}  →  ${b}`);
  }
}
console.log(`\n${uniq.length} unique elements checked, ${bad} differ`);
process.exit(bad ? 1 : 0);
