#!/usr/bin/env node
// Hardcode ratchet: design values belong in tokens, not in component files.
//
// globals.css defines the design tokens (colours, the spacing / type / radius
// / shadow / z-index scales, motion), and src/lib/designTokens.ts mirrors the
// ones code needs as numbers. docs/frontend-design-tokens.md says which is
// which. This script counts, per git-tracked source file under src/, the
// values written out by hand instead:
//
//   color         a raw colour (#hex, rgb[a](), hsl[a]()) in a CSS declaration
//                 or in a TS/TSX string literal.
//   css-size      in a CSS declaration of margin*, padding*, gap, font-size,
//                 *-radius or box-shadow: each non-zero px/rem number; of
//                 z-index: the number; of transition* or animation*: each
//                 non-zero time (ms/s) and each cubic-bezier().
//   inline-style  in a React style object (a `style={{…}}` attribute, a
//                 `style:` property, or an object typed/asserted as
//                 CSSProperties): each non-zero literal number, and each px/rem
//                 number or colour inside a string value. Unitless properties
//                 (flex, opacity, fontWeight, lineHeight, …: UNITLESS below)
//                 are not counted. A colour counted here is not counted again
//                 under `color`.
//   url           an http(s):// URL or `localhost` in a TS/TSX string literal
//                 (the SVG/XML namespace URIs are not configuration and are
//                 skipped).
//
// Not measured: tests (*.test.*), __snapshots__/, __fixtures__/, JSON
// (golden files included), lib/designTokens.ts (the token mirror itself), the
// token DEFINITIONS in app/globals.css (declarations of a `--*` property), and
// the pre-auth landing scope, which keeps its own token set: the files under
// LANDING_PREFIXES and, in any stylesheet, a rule whose selector is in the
// landing classes (LANDING_SELECTOR) or a @keyframes named for them, and the
// two landing sections of globals.css (GLOBALS_LANDING_SECTIONS).
//
// The baseline (hardcode-baseline.json) holds today's count for every
// `<file>::<category>` that is not zero. A key may not go up and a new key may
// not appear: write the token instead. A count that went DOWN is not an error
// (two PRs that each convert part of a file must not leave main red between
// them) but it should be locked in with --shrink, or the headroom becomes room
// for the next hardcode. scripts/hardcode-ratchet.test.ts enforces this in
// `npm test`, which the frontend CI job already runs.
//
// Usage, from frontend/:
//
//   npm run hardcode           # report; exit 1 when a count went up
//   npm run hardcode:shrink    # lower the baseline to today's numbers
//   npm run hardcode -- --top 40      # show more of the per-file table
//   npm run hardcode -- --file <path> # list every hit in one file
//
// --shrink only ever lowers an entry or deletes one that reached zero; it
// never adds or raises one. Raising an entry is a hand edit to the JSON, which
// shows up in review.

import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import ts from "typescript";

export const FRONTEND = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const BASELINE_FILE = "hardcode-baseline.json";
export const KEY = "hardcode";
export const CATEGORIES = ["color", "css-size", "inline-style", "url"];

const SOURCE = /\.(css|[cm]?[jt]sx?)$/;
const TS_SOURCE = /\.[cm]?[jt]sx?$/;

/** The pre-auth landing scope: its own token set, out of this ratchet's reach. */
export const LANDING_PREFIXES = [
  "src/app/(public)/",
  "src/components/companion/",
  "src/components/landing/",
  "src/components/landing-v5/",
  "src/components/marketing/",
  "src/lib/landing/",
];
/** A CSS rule in the landing scope (globals.css holds it beside the app's rules). */
export const LANDING_SELECTOR = /\.(?:public-surface|landing-v5)\b|\.(?:landing|ld|cp|wiki)-[\w-]+/;
const LANDING_KEYFRAMES = /^@keyframes\s+(?:landing|ld|cp)[\w-]*/i;
/**
 * The two banner-headed sections of globals.css that hold landing rules under
 * unscoped selectors (`.font-aleo`, bare @keyframes): each runs from its banner
 * to the next banner, or to the end of the file when `toEnd`.
 * scripts/hardcode-ratchet.test.ts fails if a banner is renamed away.
 */
export const GLOBALS_LANDING_SECTIONS = [
  { banner: "LANDING PAGE STYLES (ported from main branch)", toEnd: false },
  { banner: "LANDING (design-component ports)", toEnd: true },
];
const BANNER = "/* ═";

/** globals.css with its landing sections blanked (newlines kept, so lines still match). */
export function blankGlobalsLanding(css) {
  let out = css;
  for (const { banner, toEnd } of GLOBALS_LANDING_SECTIONS) {
    const at = out.indexOf(banner);
    if (at < 0) continue;
    const from = out.lastIndexOf(BANNER, at);
    const next = toEnd ? -1 : out.indexOf(BANNER, at);
    const to = next < 0 ? out.length : next;
    out = out.slice(0, from) + out.slice(from, to).replace(/[^\n]/g, " ") + out.slice(to);
  }
  return out;
}

// The app stylesheet: globals.css is an import list since the Tailwind
// migration (ADR 0031), and the tokens, the Tailwind theme and the shared
// rules live in src/styles. Token definitions in any of them are not counted.
const GLOBALS = new Set(["src/app/globals.css", "src/styles/tokens.css", "src/styles/theme.css", "src/styles/base.css", "src/styles/components.css"]);
const TOKEN_MIRROR = "src/lib/designTokens.ts";

/** Whether a frontend-relative path is measured at all. */
export function isMeasured(rel) {
  if (!rel.startsWith("src/") || !SOURCE.test(rel)) return false;
  if (/\.test\.[^/]+$/.test(rel) || /\.d\.ts$/.test(rel)) return false;
  if (/(^|\/)__(snapshots|fixtures)__\//.test(rel)) return false;
  if (rel === TOKEN_MIRROR) return false;
  return !LANDING_PREFIXES.some((p) => rel.startsWith(p));
}

// ── value matchers ────────────────────────────────────────────────────────

const HEX = /(?<![\w&/#-])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![\w-])/g;
const COLOR_FN = /\b(?:rgba?|hsla?)\(/g;
const LENGTH = /(?<![\w.#-])-?(\d*\.?\d+)(?:px|rem)\b/g;
const TIME = /(?<![\w.#-])(\d*\.?\d+)m?s\b/g;
const BEZIER = /cubic-bezier\(/g;
const URL_RE = /https?:\/\/[^\s"'`)]*|\blocalhost\b/g;
const NAMESPACE_URL = /^https?:\/\/www\.w3\.org\//;

const countMatches = (re, text) => (text.match(re) ?? []).length;
const nonZero = (re, text) => [...text.matchAll(re)].filter((m) => Number(m[1]) !== 0).length;

export function countColors(text) {
  return countMatches(HEX, text) + countMatches(COLOR_FN, text);
}

export function countUrls(text) {
  return (text.match(URL_RE) ?? []).filter((u) => !NAMESPACE_URL.test(u)).length;
}

const SIZE_PROP = /^(?:margin|padding)(?:-[a-z-]+)?$|^(?:gap|row-gap|column-gap|font-size|box-shadow)$|^border(?:-[a-z]+)*-radius$/;
const MOTION_PROP = /^(?:transition|animation)(?:-[a-z-]+)?$/;

/** css-size hits in one CSS declaration (property already lower-cased). */
export function countCssSize(prop, value) {
  if (SIZE_PROP.test(prop)) return nonZero(LENGTH, value);
  if (prop === "z-index") return /^\s*-?\d+\s*(!important)?\s*$/.test(value) && Number.parseInt(value, 10) !== 0 ? 1 : 0;
  if (MOTION_PROP.test(prop)) return nonZero(TIME, value) + countMatches(BEZIER, value);
  return 0;
}

// ── CSS ───────────────────────────────────────────────────────────────────

/** Comments blanked out (newlines kept), so nothing inside one is counted. */
function stripCssComments(css) {
  return css.replace(/\/\*[\s\S]*?\*\//g, (c) => c.replace(/[^\n]/g, " "));
}

/**
 * Hits in one stylesheet. A hand-rolled walk (see app/globals.test.ts for why
 * postcss is not imported): it tracks the prelude of every open block, so a
 * declaration knows whether it sits in the landing scope.
 */
export function scanCss(css, { isGlobals = false } = {}) {
  const counts = { color: 0, "css-size": 0 };
  const hits = [];
  const text = stripCssComments(isGlobals ? blankGlobalsLanding(css) : css);
  const stack = [];
  let start = 0;
  let quote = null;

  const inLanding = () => stack.some((p) => LANDING_SELECTOR.test(p) || LANDING_KEYFRAMES.test(p));
  const lineAt = (i) => text.slice(0, i).split("\n").length;

  const declaration = (from, to) => {
    const raw = text.slice(from, to);
    const colon = raw.indexOf(":");
    if (colon < 0 || stack.length === 0 || inLanding()) return;
    const prop = raw.slice(0, colon).trim().toLowerCase();
    const value = raw.slice(colon + 1).trim();
    if (!/^-{0,2}[a-z][\w-]*$/.test(prop)) return;
    if (prop.startsWith("--") && isGlobals) return; // a token definition
    const line = lineAt(from + raw.search(/\S/));
    const color = countColors(value);
    const size = countCssSize(prop, value);
    if (color) { counts.color += color; hits.push({ line, category: "color", n: color, text: `${prop}: ${value}` }); }
    if (size) { counts["css-size"] += size; hits.push({ line, category: "css-size", n: size, text: `${prop}: ${value}` }); }
  };

  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quote) { if (c === "\\") i++; else if (c === quote) quote = null; continue; }
    if (c === '"' || c === "'") { quote = c; continue; }
    if (c === "{") { stack.push(text.slice(start, i).trim()); start = i + 1; }
    else if (c === ";") { declaration(start, i); start = i + 1; }
    else if (c === "}") { declaration(start, i); stack.pop(); start = i + 1; }
  }
  return { counts, hits };
}

// ── TS / TSX ──────────────────────────────────────────────────────────────

/** Style properties whose bare numbers are not lengths, colours or layers. */
export const UNITLESS = new Set([
  "aspectRatio", "columnCount", "fillOpacity", "flex", "flexGrow", "flexShrink", "fontWeight",
  "gridColumn", "gridColumnEnd", "gridColumnStart", "gridRow", "gridRowEnd", "gridRowStart",
  "lineHeight", "opacity", "order", "scale", "stopOpacity", "strokeOpacity", "tabSize",
  "WebkitLineClamp", "zoom",
]);

const STRINGISH = new Set([
  ts.SyntaxKind.StringLiteral,
  ts.SyntaxKind.NoSubstitutionTemplateLiteral,
  ts.SyntaxKind.TemplateHead,
  ts.SyntaxKind.TemplateMiddle,
  ts.SyntaxKind.TemplateTail,
]);

const isCssPropertiesType = (typeNode, sf) => Boolean(typeNode) && /CSSProperties/.test(typeNode.getText(sf));

function unwrap(node) {
  let n = node;
  while (n && (ts.isParenthesizedExpression(n) || ts.isAsExpression(n) || ts.isSatisfiesExpression(n) || ts.isNonNullExpression(n))) n = n.expression;
  return n;
}

function propName(prop, sf) {
  const name = prop.name;
  if (!name) return "";
  if (ts.isIdentifier(name) || ts.isStringLiteral(name) || ts.isNumericLiteral(name)) return name.text;
  return name.getText(sf);
}

/** Whether `node` (an object literal) is a style object by where it sits. */
function isStyleObject(node, sf) {
  let child = node;
  let parent = node.parent;
  // Climb through wrappers and conditional branches: `style={a ? {…} : {…}}`.
  while (parent && (ts.isParenthesizedExpression(parent) || ts.isConditionalExpression(parent) || (ts.isBinaryExpression(parent) && child !== parent.left))) {
    child = parent;
    parent = parent.parent;
  }
  if (!parent) return false;
  if ((ts.isAsExpression(parent) || ts.isSatisfiesExpression(parent)) && isCssPropertiesType(parent.type, sf)) return true;
  if (ts.isJsxExpression(parent) && parent.parent && ts.isJsxAttribute(parent.parent)) return parent.parent.name.getText(sf) === "style";
  if (ts.isPropertyAssignment(parent) && parent.initializer === child) return propName(parent, sf) === "style";
  if (ts.isVariableDeclaration(parent) || ts.isPropertyDeclaration(parent) || ts.isParameter(parent)) return isCssPropertiesType(parent.type, sf);
  if (ts.isReturnStatement(parent) || ts.isArrowFunction(parent)) {
    let fn = parent;
    while (fn && !ts.isFunctionLike(fn)) fn = fn.parent;
    return Boolean(fn) && isCssPropertiesType(fn.type, sf);
  }
  return false;
}

/** Hits in one TS/TSX source. */
export function scanTs(code, fileName = "x.tsx") {
  const kind = /x$/.test(fileName) ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  const sf = ts.createSourceFile(fileName, code, ts.ScriptTarget.Latest, true, kind);
  const counts = { color: 0, "inline-style": 0, url: 0 };
  const hits = [];
  const claimed = new Set(); // string nodes counted as inline-style
  const styleObjects = new Set();

  const add = (node, category, n) => {
    if (!n) return;
    counts[category] += n;
    const { line } = sf.getLineAndCharacterOfPosition(node.getStart(sf));
    hits.push({ line: line + 1, category, n, text: node.getText(sf).slice(0, 120) });
  };

  // Every value position of a style property: the expression itself, or the
  // branches of a conditional / `??` / `||` / `&&` that picks one.
  const styleValue = (expr, prop) => {
    const e = unwrap(expr);
    if (!e) return;
    if (ts.isConditionalExpression(e)) { styleValue(e.whenTrue, prop); styleValue(e.whenFalse, prop); return; }
    if (ts.isBinaryExpression(e) && [ts.SyntaxKind.QuestionQuestionToken, ts.SyntaxKind.BarBarToken, ts.SyntaxKind.AmpersandAmpersandToken].includes(e.operatorToken.kind)) {
      styleValue(e.left, prop); styleValue(e.right, prop); return;
    }
    if (ts.isObjectLiteralExpression(e)) { styleObject(e); return; }
    const num = ts.isPrefixUnaryExpression(e) && e.operator === ts.SyntaxKind.MinusToken ? e.operand : e;
    if (ts.isNumericLiteral(num)) {
      if (!UNITLESS.has(prop) && Number(num.text) !== 0) add(e, "inline-style", 1);
      return;
    }
    const strings = [];
    const collect = (n) => { if (STRINGISH.has(n.kind)) strings.push(n); ts.forEachChild(n, collect); };
    collect(e);
    for (const s of strings) {
      claimed.add(s);
      const t = s.text ?? "";
      const motion = /^(transition|animation)/.test(prop);
      const n = countColors(t) + (UNITLESS.has(prop) ? 0 : nonZero(LENGTH, t)) + (motion ? nonZero(TIME, t) + countMatches(BEZIER, t) : 0);
      add(s, "inline-style", n);
    }
  };

  const styleObject = (obj) => {
    if (styleObjects.has(obj)) return;
    styleObjects.add(obj);
    for (const p of obj.properties) {
      if (ts.isPropertyAssignment(p)) styleValue(p.initializer, propName(p, sf));
    }
  };

  const visit = (node) => {
    if (ts.isObjectLiteralExpression(node) && isStyleObject(node, sf)) styleObject(node);
    ts.forEachChild(node, visit);
  };
  visit(sf);

  const strings = (node) => {
    if (STRINGISH.has(node.kind) && !claimed.has(node)) {
      const inModuleSpecifier = node.parent && (ts.isImportDeclaration(node.parent) || ts.isExportDeclaration(node.parent));
      if (!inModuleSpecifier) {
        add(node, "color", countColors(node.text ?? ""));
        add(node, "url", countUrls(node.text ?? ""));
      }
    }
    ts.forEachChild(node, strings);
  };
  strings(sf);
  return { counts, hits };
}

// ── the tree ──────────────────────────────────────────────────────────────

/** Git-tracked, measured files under `root`, relative to it (posix). */
export function trackedFiles(root = FRONTEND) {
  const out = execFileSync("git", ["ls-files", "-z", "--", "src"], { cwd: root, encoding: "utf8" });
  return out.split("\0").filter((rel) => rel && isMeasured(rel) && fs.existsSync(path.join(root, rel))).sort();
}

/** Hits in one file, by its path relative to `root`. */
export function scanFile(rel, root = FRONTEND) {
  const text = fs.readFileSync(path.join(root, rel), "utf8");
  if (TS_SOURCE.test(rel)) return scanTs(text, rel);
  return scanCss(text, { isGlobals: GLOBALS.has(rel) });
}

/** `{ "<file>::<category>": count }` for every non-zero count in the tree. */
export function measure(root = FRONTEND) {
  /** @type {Record<string, number>} */
  const current = {};
  for (const rel of trackedFiles(root)) {
    const { counts } = scanFile(rel, root);
    for (const [category, n] of Object.entries(counts)) if (n) current[`${rel}::${category}`] = n;
  }
  return current;
}

// ── the ratchet ───────────────────────────────────────────────────────────

/** Keys that went up or appeared. */
export function compare(baseline, current) {
  const problems = [];
  for (const key of Object.keys(current).sort()) {
    const ceiling = baseline[key];
    if (ceiling === undefined) problems.push(`${key}: ${current[key]} new (use a token from globals.css / lib/designTokens.ts)`);
    else if (current[key] > ceiling) problems.push(`${key}: ${current[key]}, up from ${ceiling}`);
  }
  return problems;
}

/** Entries that are higher than they need to be. */
export function shrinkable(baseline, current) {
  const out = [];
  for (const key of Object.keys(baseline).sort()) {
    const value = current[key] ?? 0;
    if (value === 0) out.push(`${key}: now 0, delete its entry`);
    else if (value < baseline[key]) out.push(`${key}: now ${value}, baselined at ${baseline[key]}, lower it`);
  }
  return out;
}

/** Lower each entry to today's value and drop the ones at zero. Never adds or raises. */
export function shrink(baseline, current) {
  /** @type {Record<string, number>} */
  const out = {};
  for (const [key, ceiling] of Object.entries(baseline)) {
    if (current[key]) out[key] = Math.min(ceiling, current[key]);
  }
  return out;
}

/** Per-category totals and the per-file totals, largest first. */
export function summarize(current) {
  const totals = Object.fromEntries(CATEGORIES.map((c) => [c, 0]));
  /** @type {Record<string, Record<string, number>>} */
  const files = {};
  for (const [key, n] of Object.entries(current)) {
    const [file, category] = key.split("::");
    totals[category] += n;
    files[file] ??= Object.fromEntries(CATEGORIES.map((c) => [c, 0]));
    files[file][category] = n;
  }
  const ranked = Object.entries(files)
    .map(([file, byCat]) => ({ file, total: CATEGORIES.reduce((s, c) => s + byCat[c], 0), ...byCat }))
    .sort((a, b) => b.total - a.total || a.file.localeCompare(b.file));
  return { totals, total: CATEGORIES.reduce((s, c) => s + totals[c], 0), files: ranked };
}

export const COMMENT =
  "Hardcode ratchet (scripts/hardcode-ratchet.mjs): today's count of hand-written design values per `<file>::<category>` under src/ (categories: color, css-size, inline-style, url; see docs/frontend-design-tokens.md). A count may not rise and a new key may not appear: use a token. Entries may only be lowered or deleted (npm run hardcode:shrink).";

export function loadBaseline(root = FRONTEND) {
  return JSON.parse(fs.readFileSync(path.join(root, BASELINE_FILE), "utf8"));
}

export function writeBaseline(entries, root = FRONTEND) {
  const sorted = Object.fromEntries(Object.keys(entries).sort().map((k) => [k, entries[k]]));
  fs.writeFileSync(path.join(root, BASELINE_FILE), `${JSON.stringify({ _comment: COMMENT, [KEY]: sorted }, null, 2)}\n`);
}

function table(current, top) {
  const { totals, total, files } = summarize(current);
  const lines = [
    `hardcode: ${total} hand-written values in ${files.length} files  (${CATEGORIES.map((c) => `${c} ${totals[c]}`).join(", ")})`,
    `  ${"total".padStart(5)} ${"color".padStart(6)} ${"size".padStart(5)} ${"style".padStart(6)} ${"url".padStart(4)}  file`,
  ];
  for (const f of files.slice(0, top)) {
    lines.push(`  ${String(f.total).padStart(5)} ${String(f.color).padStart(6)} ${String(f["css-size"]).padStart(5)} ${String(f["inline-style"]).padStart(6)} ${String(f.url).padStart(4)}  ${f.file}`);
  }
  if (files.length > top) lines.push(`  … ${files.length - top} more (--top N)`);
  return lines.join("\n");
}

export function main(argv = process.argv.slice(2), root = FRONTEND) {
  const fileArg = argv.indexOf("--file");
  if (fileArg >= 0) {
    const rel = argv[fileArg + 1];
    for (const h of scanFile(rel, root).hits) console.log(`${rel}:${h.line}  ${h.category} ×${h.n}  ${h.text}`);
    return 0;
  }
  const topArg = argv.indexOf("--top");
  const top = topArg >= 0 ? Number(argv[topArg + 1]) : 25;
  const current = measure(root);

  if (argv.includes("--init")) {
    // Bootstrap only: records today's tree as the baseline, raises included.
    writeBaseline(current, root);
    console.log(`wrote ${path.join(root, BASELINE_FILE)}`);
    console.log(table(current, top));
    return 0;
  }

  const baseline = loadBaseline(root)[KEY];
  if (argv.includes("--shrink")) {
    const next = shrink(baseline, current);
    writeBaseline(next, root);
    console.log(`wrote ${path.join(root, BASELINE_FILE)}`);
    const remaining = compare(next, current);
    for (const line of remaining) console.log(`  FAIL  ${line}`);
    if (remaining.length) console.log("--shrink cannot fix these: replace the values with tokens");
    return remaining.length ? 1 : 0;
  }

  console.log(table(current, top));
  const problems = compare(baseline, current);
  for (const line of problems) console.log(`  FAIL  ${line}`);
  const slack = shrinkable(baseline, current);
  for (const line of slack) console.log(`  SHRINK  ${line}`);
  if (slack.length) console.log("Lock the improvement in: npm run hardcode:shrink, and commit hardcode-baseline.json.");
  return problems.length ? 1 : 0;
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  process.exitCode = main();
}
