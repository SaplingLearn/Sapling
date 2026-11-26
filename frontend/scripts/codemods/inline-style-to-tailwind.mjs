#!/usr/bin/env node
// Move static inline styles onto Tailwind classes.
//
//   node scripts/codemods/inline-style-to-tailwind.mjs [--dry] [--log cases.json] [paths...]
//
// For every JSX `style={{ ... }}` on an intrinsic element (div, span, svg,
// motion.div ...), each declaration whose value is known at build time moves
// to className through css-to-tailwind.mjs:
//   - string / number literals, and `cond ? "a" : "b"` between literals
//     (undefined/null as "no declaration")
//   - identifiers and `X.y` reads that resolve to const literals, and
//     spreads / `style={X}` of const objects made only of those
// Declarations that depend on runtime values stay in `style`. A spread of an
// unknown object stays too, along with every declaration after it (it could
// override them). Elements with a JSX spread attribute are skipped, because
// a className inside the spread would fight the new one.
//
// The conversion is checked in a real browser by verify-inline-style.mjs,
// which reads the --log output. Safe to re-run: converted elements have no
// static style left.
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { toClasses, cssValue } from "./css-to-tailwind.mjs";
import { extendTailwindMerge } from "tailwind-merge";

// Same theme names as src/lib/cn.ts. Used to resolve "a later declaration
// wins" inside one element: margin: "20px 0 0" then marginTop: 14 must end
// as mt-3.5, not mt-5 and mt-3.5 side by side.
const twMerge = extendTailwindMerge({
  override: {
    // Sapling's font sizes carry no line height, so text-md must not drop an
    // earlier leading-[1.6] (tailwind-merge's default assumes it does).
    conflictingClassGroups: { "font-size": [] },
    theme: {
      text: ["2xs", "xs", "sm", "md", "base", "lg", "xl", "2xl", "3xl", "4xl", "5xl"],
      radius: ["xs", "sm", "md", "lg", "xl"],
      shadow: ["sm", "md", "lg", "inset"],
      font: ["sans", "serif", "display", "code"],
    },
  },
});

const require = createRequire(import.meta.url);
const ts = require("typescript");

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "../..");
const args = process.argv.slice(2);
const DRY = args.includes("--dry");
const logIdx = args.indexOf("--log");
const LOG = logIdx >= 0 ? args[logIdx + 1] : null;
const targets = args.filter((a, i) => !a.startsWith("--") && i !== logIdx + 1);

function listFiles(p) {
  const abs = path.resolve(root, p);
  if (fs.statSync(abs).isFile()) return [abs];
  const out = [];
  (function walk(d) {
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
      const q = path.join(d, e.name);
      if (e.isDirectory()) { if (e.name !== "node_modules") walk(q); }
      else if (/\.tsx$/.test(e.name) && !/\.test\.tsx$/.test(e.name)) out.push(q);
    }
  })(abs);
  return out;
}
const files = (targets.length ? targets : ["src"]).flatMap(listFiles);

const program = ts.createProgram(files, {
  jsx: ts.JsxEmit.Preserve, target: ts.ScriptTarget.Latest, module: ts.ModuleKind.ESNext,
  moduleResolution: ts.ModuleResolutionKind.Bundler, allowJs: false, noEmit: true, skipLibCheck: true,
  baseUrl: root, paths: { "@/*": ["./src/*"] },
});
const checker = program.getTypeChecker();

const NONE = Symbol("none");

// A const that is also read OUTSIDE a style object (layout maths, a canvas,
// a test) must stay a reference: copying its value into a class would let
// the two drift apart. Collect those declarations up front.
const sharedConsts = new Set();
function inStyleAttr(n) {
  for (let p = n.parent; p; p = p.parent) {
    if (ts.isJsxAttribute(p)) return p.name.getText() === "style";
    if (ts.isFunctionLike(p) || ts.isSourceFile(p)) return false;
  }
  return false;
}
for (const f of program.getSourceFiles()) {
  if (f.isDeclarationFile || f.fileName.includes("node_modules")) continue;
  (function walk(n) {
    if (ts.isIdentifier(n) && !(ts.isVariableDeclaration(n.parent) && n.parent.name === n) && !ts.isImportSpecifier(n.parent) && !ts.isExportSpecifier(n.parent) && !(ts.isPropertyAssignment(n.parent) && n.parent.name === n) && !(ts.isPropertyAccessExpression(n.parent) && n.parent.name === n)) {
      let sym = checker.getSymbolAtLocation(n);
      if (sym && sym.flags & ts.SymbolFlags.Alias) sym = checker.getAliasedSymbol(sym);
      const d = sym?.valueDeclaration;
      if (d && ts.isVariableDeclaration(d) && !inStyleAttr(n) && !isStyleConstUse(n)) sharedConsts.add(d);
    }
    ts.forEachChild(n, walk);
  })(f);
}
// `const BOX = { padding: PAD }` used as style={BOX}: PAD's use inside BOX is
// a style use too.
function isStyleConstUse(n) {
  for (let p = n.parent; p; p = p.parent) {
    if (ts.isVariableDeclaration(p)) {
      const t = p.type?.getText() ?? "";
      return /CSSProperties/.test(t) || /^[A-Z_]+$/.test(p.name.getText?.() ?? "") && ts.isObjectLiteralExpression(unwrap(p.initializer));
    }
    if (ts.isFunctionLike(p) || ts.isSourceFile(p)) return false;
  }
  return false;
}
const stats = { files: 0, elements: 0, converted: 0, partial: 0, skippedComponent: 0, skippedSpreadAttr: 0, declsMoved: 0, declsKept: 0 };
const cases = [];

// ---- static evaluation -----------------------------------------------------
function unwrap(e) {
  while (e && (ts.isParenthesizedExpression(e) || ts.isAsExpression(e) || ts.isSatisfiesExpression(e) || ts.isTypeAssertionExpression?.(e) || ts.isNonNullExpression(e))) e = e.expression;
  return e;
}
function constInit(id, depth) {
  if (depth > 6) return null;
  let sym = checker.getSymbolAtLocation(id);
  if (sym && sym.flags & ts.SymbolFlags.Alias) sym = checker.getAliasedSymbol(sym);
  const decl = sym?.valueDeclaration ?? sym?.declarations?.[0];
  if (!decl || !ts.isVariableDeclaration(decl) || !decl.initializer) return null;
  const list = decl.parent;
  if (!ts.isVariableDeclarationList(list) || !(list.flags & ts.NodeFlags.Const)) return null;
  if (decl.getSourceFile().isDeclarationFile) return null;
  if (sharedConsts.has(decl)) return null;
  return unwrap(decl.initializer);
}
// -> string | number | NONE (no declaration) | undefined (not static)
function evalLiteral(e, depth = 0) {
  e = unwrap(e);
  if (!e) return undefined;
  if (ts.isStringLiteral(e) || ts.isNoSubstitutionTemplateLiteral(e)) return e.text;
  if (ts.isNumericLiteral(e)) return Number(e.text);
  if (ts.isPrefixUnaryExpression(e) && e.operator === ts.SyntaxKind.MinusToken && ts.isNumericLiteral(e.operand)) return -Number(e.operand.text);
  if (ts.isIdentifier(e)) {
    if (e.text === "undefined") return NONE;
    const init = constInit(e, depth + 1);
    return init ? evalLiteral(init, depth + 1) : undefined;
  }
  if (e.kind === ts.SyntaxKind.NullKeyword) return NONE;
  if (ts.isPropertyAccessExpression(e)) {
    const obj = evalObject(e.expression, depth + 1);
    if (!obj) return undefined;
    const hit = obj.props.find((p) => p.name === e.name.text);
    return hit && hit.kind === "lit" ? hit.value : undefined;
  }
  if (ts.isTemplateExpression(e)) {
    let s = e.head.text;
    for (const span of e.templateSpans) {
      const v = evalLiteral(span.expression, depth + 1);
      if (v === undefined || v === NONE) return undefined;
      s += String(v) + span.literal.text;
    }
    return s;
  }
  return undefined;
}
// A const object made only of static props -> { props: [{name, kind:"lit", value}] }
function evalObject(e, depth = 0) {
  e = unwrap(e);
  if (!e || depth > 6) return null;
  if (ts.isIdentifier(e)) {
    const init = constInit(e, depth + 1);
    return init ? evalObject(init, depth + 1) : null;
  }
  if (ts.isPropertyAccessExpression(e)) {
    const parent = evalObjectRaw(e.expression, depth + 1);
    if (!parent) return null;
    const p = parent.properties.find((q) => ts.isPropertyAssignment(q) && propName(q) === e.name.text);
    return p ? evalObject(p.initializer, depth + 1) : null;
  }
  if (!ts.isObjectLiteralExpression(e)) return null;
  const props = [];
  for (const p of e.properties) {
    if (ts.isSpreadAssignment(p)) {
      const inner = evalObject(p.expression, depth + 1);
      if (!inner) return null;
      props.push(...inner.props);
      continue;
    }
    if (!ts.isPropertyAssignment(p) || propName(p) == null) return null;
    const v = evalLiteral(p.initializer, depth + 1);
    if (v === undefined) {
      // nested objects are fine for X.y lookups, not as style values
      if (ts.isObjectLiteralExpression(unwrap(p.initializer))) { props.push({ name: propName(p), kind: "obj" }); continue; }
      return null;
    }
    props.push({ name: propName(p), kind: "lit", value: v });
  }
  return { props };
}
function evalObjectRaw(e, depth) {
  e = unwrap(e);
  if (ts.isIdentifier(e)) { const init = constInit(e, depth + 1); return init && ts.isObjectLiteralExpression(init) ? init : null; }
  return ts.isObjectLiteralExpression(e) ? e : null;
}
// The property names a spread sets, when they are known even if the values
// aren't (`...ARTICLE.eyebrow` where eyebrow = { fontFamily: LABEL, ... }).
function spreadKeys(e, depth = 0) {
  e = unwrap(e);
  if (!e || depth > 6) return null;
  let obj = null;
  if (ts.isObjectLiteralExpression(e)) obj = e;
  else if (ts.isIdentifier(e)) {
    let sym = checker.getSymbolAtLocation(e);
    if (sym && sym.flags & ts.SymbolFlags.Alias) sym = checker.getAliasedSymbol(sym);
    const d = sym?.valueDeclaration;
    if (d && ts.isVariableDeclaration(d) && d.initializer && d.parent.flags & ts.NodeFlags.Const) obj = unwrap(d.initializer);
  } else if (ts.isPropertyAccessExpression(e)) {
    const parent = spreadObject(e.expression, depth + 1);
    const prop = parent?.properties.find((q) => ts.isPropertyAssignment(q) && propName(q) === e.name.text);
    obj = prop ? unwrap(prop.initializer) : null;
  }
  if (!obj || !ts.isObjectLiteralExpression(obj)) return null;
  const keys = [];
  for (const q of obj.properties) {
    if (ts.isSpreadAssignment(q)) { const k = spreadKeys(q.expression, depth + 1); if (!k) return null; keys.push(...k); }
    else if ((ts.isPropertyAssignment(q) || ts.isShorthandPropertyAssignment(q)) && propName(q) != null) keys.push(propName(q));
    else return null;
  }
  return keys;
}
function spreadObject(e, depth) {
  e = unwrap(e);
  if (ts.isObjectLiteralExpression(e)) return e;
  if (ts.isIdentifier(e)) {
    let sym = checker.getSymbolAtLocation(e);
    if (sym && sym.flags & ts.SymbolFlags.Alias) sym = checker.getAliasedSymbol(sym);
    const d = sym?.valueDeclaration;
    const init = d && ts.isVariableDeclaration(d) && d.initializer ? unwrap(d.initializer) : null;
    return init && ts.isObjectLiteralExpression(init) ? init : null;
  }
  if (ts.isPropertyAccessExpression(e) && depth < 6) {
    const parent = spreadObject(e.expression, depth + 1);
    const prop = parent?.properties.find((q) => ts.isPropertyAssignment(q) && propName(q) === e.name.text);
    const v = prop ? unwrap(prop.initializer) : null;
    return v && ts.isObjectLiteralExpression(v) ? v : null;
  }
  return null;
}
function propName(p) {
  const n = p.name;
  if (ts.isIdentifier(n) || ts.isStringLiteral(n) || ts.isNumericLiteral(n)) return n.text;
  return null;
}

// ---- element helpers -------------------------------------------------------
// Components that render one DOM element with className and style passed
// straight through, and no inline style of their own.
const PASS_THROUGH = { Link: ["next/link", "a"] };
function tagOf(el) {
  const t = el.tagName;
  if (ts.isIdentifier(t) && PASS_THROUGH[t.text]) {
    const [mod, tag] = PASS_THROUGH[t.text];
    const imp = t.getSourceFile().statements.find((s) => ts.isImportDeclaration(s) && s.moduleSpecifier.text === mod && s.importClause?.name?.text === t.text);
    return imp ? tag : null;
  }
  if (ts.isIdentifier(t)) return /^[a-z]/.test(t.text) ? t.text : null;
  if (ts.isPropertyAccessExpression(t) && ts.isIdentifier(t.expression) && t.expression.text === "motion") return t.name.text;
  return null;
}
const SVG_TAGS = new Set("svg g path rect circle ellipse line polyline polygon text tspan defs linearGradient radialGradient stop clipPath mask pattern use foreignObject marker symbol image filter feGaussianBlur feOffset feMerge feMergeNode feColorMatrix feBlend feFlood feComposite".split(" "));

function classLiteralOf(attr) {
  if (!attr) return { kind: "none" };
  const init = attr.initializer;
  if (!init) return { kind: "none" };
  if (ts.isStringLiteral(init)) return { kind: "str", text: init.text };
  if (ts.isJsxExpression(init) && init.expression) {
    const e = init.expression;
    if (ts.isStringLiteral(e) || ts.isNoSubstitutionTemplateLiteral(e)) return { kind: "str", text: e.text };
    return { kind: "expr", node: e };
  }
  return { kind: "none" };
}
// Any class that isn't obviously a Tailwind utility means component CSS may
// target the element; shorthands that reset hidden longhands stay exact.
function hasCustomClass(cls) {
  if (cls.kind === "none") return false;
  if (cls.kind === "expr") return true;
  return cls.text.split(/\s+/).filter(Boolean).some((c) => !/^[a-z0-9:[\]()/._%#,'-]+$/.test(c) || /^[a-z]+(-[a-z]+)+$/.test(c) && !KNOWN_TW.test(c));
}
const KNOWN_TW = /^(flex|inline-flex|grid|items-|justify-|gap-|p[trblxy]?-|m[trblxy]?-|w-|h-|min-|max-|rounded|text-|bg-|border|font-|leading-|tracking-|shrink|grow|overflow|whitespace|absolute|relative|fixed|sticky|inset|top-|left-|right-|bottom-|z-|opacity-|cursor-|select-|pointer-|truncate|block|inline|hidden|antialiased|mx-auto|self-|place-|object-|aspect-|shadow|transition|duration-|ease-|uppercase|italic|underline|sr-only|flex-)/;

// Order matters inline: a later shorthand resets an earlier longhand.
const FAMILY = {
  padding: /^padding(Top|Right|Bottom|Left|Inline|Block)$/, margin: /^margin(Top|Right|Bottom|Left|Inline|Block)$/,
  inset: /^(top|right|bottom|left)$/, border: /^border(Top|Right|Bottom|Left)?(Width|Style|Color)?$|^border(Top|Right|Bottom|Left)$/,
  borderTop: /^borderTop(Width|Style|Color)$/, borderRight: /^borderRight(Width|Style|Color)$/, borderBottom: /^borderBottom(Width|Style|Color)$/, borderLeft: /^borderLeft(Width|Style|Color)$/,
  borderColor: /^border(Top|Right|Bottom|Left)Color$/, borderWidth: /^border(Top|Right|Bottom|Left)Width$/, borderStyle: /^border(Top|Right|Bottom|Left)Style$/,
  background: /^background[A-Z]/, flex: /^flex(Grow|Shrink|Basis)$/, font: /^(font[A-Z]|lineHeight)/, gap: /^(rowGap|columnGap)$/,
  overflow: /^overflow[XY]$/, borderRadius: /^border(Top|Bottom)(Left|Right)Radius$/, transition: /^transition[A-Z]/, animation: /^animation[A-Z]/,
  outline: /^outline[A-Z]/, gridTemplate: /^gridTemplate[A-Z]/, placeItems: /^(alignItems|justifyItems)$/, textDecoration: /^textDecoration[A-Z]/,
  paddingInline: /^padding(Left|Right)$/, paddingBlock: /^padding(Top|Bottom)$/, marginInline: /^margin(Left|Right)$/, marginBlock: /^margin(Top|Bottom)$/,
};
function dropOverridden(decls) {
  // decls: [{name, ...}] in source order; drop a decl that a LATER one replaces
  const keep = decls.map(() => true);
  for (let i = 0; i < decls.length; i++) {
    for (let j = i + 1; j < decls.length; j++) {
      const a = decls[i].name, b = decls[j].name;
      if (a === b || (FAMILY[b] && FAMILY[b].test(a))) { keep[i] = false; break; }
    }
  }
  return decls.filter((_, i) => keep[i]);
}

function jsString(s) {
  return JSON.stringify(s);
}

// ---- transform ---------------------------------------------------------------
for (const file of files) {
  const sf = program.getSourceFile(file);
  if (!sf) continue;
  const text = sf.getFullText();
  const edits = [];
  let needCn = false;

  function visit(node) {
    if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) handle(node);
    ts.forEachChild(node, visit);
  }
  function handle(el) {
    const attrs = el.attributes.properties;
    const styleAttr = attrs.find((a) => ts.isJsxAttribute(a) && a.name.getText(sf) === "style");
    if (!styleAttr || !styleAttr.initializer || !ts.isJsxExpression(styleAttr.initializer) || !styleAttr.initializer.expression) return;
    stats.elements++;
    const tag = tagOf(el);
    if (!tag) { stats.skippedComponent++; return; }
    if (attrs.some((a) => ts.isJsxSpreadAttribute(a))) { stats.skippedSpreadAttr++; return; }
    const classAttr = attrs.find((a) => ts.isJsxAttribute(a) && a.name.getText(sf) === "className");
    const cls = classLiteralOf(classAttr);
    const strict = hasCustomClass(cls);

    const expr = unwrap(styleAttr.initializer.expression);
    // Normalise to a list of entries: {kind:"decl", name, value|cond, src} | {kind:"spread", src} | {kind:"dyn", src}
    let entries;
    if (ts.isObjectLiteralExpression(expr)) {
      entries = [];
      for (const p of expr.properties) {
        if (ts.isSpreadAssignment(p)) {
          const obj = evalObject(p.expression);
          if (obj && obj.props.every((q) => q.kind === "lit")) {
            for (const q of obj.props) entries.push({ kind: "decl", name: q.name, value: q.value, src: null });
          } else entries.push({ kind: "spread", src: p.getText(sf), keys: spreadKeys(p.expression) });
          continue;
        }
        if (!ts.isPropertyAssignment(p) || propName(p) == null) { entries.push({ kind: "dyn", src: p.getText(sf) }); continue; }
        const name = propName(p);
        const init = unwrap(p.initializer);
        const v = evalLiteral(init);
        if (v !== undefined) { entries.push({ kind: "decl", name, value: v, src: p.getText(sf) }); continue; }
        // `1px solid ${on ? "var(--a)" : "var(--b)"}`: one conditional between literals
        if (ts.isTemplateExpression(init) && init.templateSpans.length >= 1) {
          const spans = init.templateSpans;
          const ci = spans.findIndex((sp) => ts.isConditionalExpression(unwrap(sp.expression)));
          const others = spans.every((sp, k) => k === ci || evalLiteral(sp.expression) !== undefined);
          if (ci >= 0 && others && spans.filter((sp) => ts.isConditionalExpression(unwrap(sp.expression))).length === 1) {
            const c = unwrap(spans[ci].expression);
            const A = evalLiteral(c.whenTrue), B = evalLiteral(c.whenFalse);
            if (A !== undefined && B !== undefined && A !== NONE && B !== NONE) {
              const build = (pick) => init.head.text + spans.map((sp, k) => (k === ci ? String(pick) : String(evalLiteral(sp.expression))) + sp.literal.text).join("");
              entries.push({ kind: "decl", name, cond: { test: c.condition.getText(sf), a: build(A), b: build(B) }, src: p.getText(sf) });
              continue;
            }
          }
        }
        if (ts.isConditionalExpression(init)) {
          const a = evalLiteral(init.whenTrue), b = evalLiteral(init.whenFalse);
          if (a !== undefined && b !== undefined) {
            entries.push({ kind: "decl", name, cond: { test: init.condition.getText(sf), a, b }, src: p.getText(sf) });
            continue;
          }
        }
        entries.push({ kind: "dynDecl", name, src: p.getText(sf) });
      }
    } else {
      const obj = evalObject(expr);
      if (obj && obj.props.every((q) => q.kind === "lit")) entries = obj.props.map((q) => ({ kind: "decl", name: q.name, value: q.value, src: null }));
      else return; // style={fn()} / style={props.style}: leave it
    }

    // A static declaration stays inline when something EARLIER that stays
    // inline could set the same property: a dynamic declaration in its
    // family, or a spread (all of it if its keys are unknown, else only those
    // keys). Inline, the later static won; as a class it would lose.
    const movable = [], kept = [];
    const overlaps = (a, b) => a === b || (FAMILY[a] && FAMILY[a].test(b)) || (FAMILY[b] && FAMILY[b].test(a));
    entries.forEach((e, i) => {
      const before = entries.slice(0, i);
      const shadowedByKept = e.kind === "decl" && before.some((k) => k.kind === "dynDecl" && overlaps(k.name, e.name));
      const shadowedBySpread = e.kind === "decl" && before.some((k) => k.kind === "spread" && (!k.keys || k.keys.some((key) => overlaps(key, e.name))));
      if (e.kind === "decl" && !shadowedBySpread && !shadowedByKept) movable.push(e);
      else kept.push(e);
    });
    // a static entry that came from an expanded const spread has no source
    // text of its own; if it must stay inline, keep the whole element as is
    if (kept.some((e) => e.kind === "decl" && e.src == null)) return;
    // A kept dynamic declaration overrides any moved one in its family, which
    // is still true once the moved one is a class (inline beats classes).
    // `font: inherit` followed by font longhands: Tailwind emits arbitrary
    // shorthands after longhands, so spell it out and let the later ones win.
    const FONT_PARTS = ["fontFamily", "fontSize", "fontWeight", "fontStyle", "fontVariant", "fontStretch", "lineHeight"];
    const expanded = movable.flatMap((d, i) =>
      d.name === "font" && d.value === "inherit" && movable.slice(i + 1).some((l) => FAMILY.font.test(l.name))
        ? FONT_PARTS.map((n) => ({ kind: "decl", name: n, value: "inherit", src: null }))
        : [d],
    );
    let decls = dropOverridden(expanded);
    // Any other shorthand that can only be an arbitrary property ([border-top:..])
    // would land after a later longhand of its family and beat it: keep the
    // shorthand and those longhands inline.
    const keepInline = new Set();
    decls.forEach((d, i) => {
      if (d.cond || d.value === NONE || !FAMILY[d.name]) return;
      if (!toClasses(d.name, d.value, { strict }).some((c) => c.startsWith("["))) return;
      const later = decls.slice(i + 1).filter((l) => FAMILY[d.name].test(l.name));
      if (later.length) { keepInline.add(d); later.forEach((l) => keepInline.add(l)); }
    });
    if ([...keepInline].some((d) => d.src == null)) return;
    if (keepInline.size) {
      kept.push(...keepInline);
      decls = decls.filter((d) => !keepInline.has(d));
    }
    if (!decls.length) return;

    const staticClasses = [];
    const condParts = [];
    for (const d of decls) {
      if (d.name.startsWith("--") && d.cond) { kept.push(d); continue; }
      if (d.cond) {
        const ca = d.cond.a === NONE ? [] : toClasses(d.name, d.cond.a, { strict });
        const cb = d.cond.b === NONE ? [] : toClasses(d.name, d.cond.b, { strict });
        condParts.push(`${d.cond.test} ? ${jsString(ca.join(" "))} : ${jsString(cb.join(" "))}`);
        if (d.cond.a !== NONE) cases.push({ file: path.relative(root, file), tag, decls: [[d.name, cssValue(d.name, d.cond.a)]], classes: ca });
        if (d.cond.b !== NONE) cases.push({ file: path.relative(root, file), tag, decls: [[d.name, cssValue(d.name, d.cond.b)]], classes: cb });
        stats.declsMoved++;
        continue;
      }
      if (d.value === NONE) continue;
      staticClasses.push(...toClasses(d.name, d.value, { strict }));
      stats.declsMoved++;
    }
    const staticDecls = decls.filter((d) => !d.cond && d.value !== NONE).map((d) => [d.name, cssValue(d.name, d.value)]);
    if (staticDecls.length) cases.push({ file: path.relative(root, file), tag, svg: SVG_TAGS.has(tag), decls: staticDecls, classes: twMerge(staticClasses.join(" ")).split(" ").filter(Boolean) });
    stats.declsKept += kept.length;

    // ---- build className
    const statStr = twMerge(staticClasses.join(" "));
    let classSrc;
    const parts = [];
    if (cls.kind === "str" && cls.text.trim()) parts.push(jsString(cls.text.trim()));
    if (cls.kind === "expr") parts.push(cls.node.getText(sf));
    if (statStr) parts.push(jsString(statStr));
    parts.push(...condParts);
    if (cls.kind !== "expr" && condParts.length === 0) {
      const joined = [cls.kind === "str" ? cls.text.trim() : "", statStr].filter(Boolean).join(" ");
      classSrc = `className=${jsString(joined)}`;
    } else {
      needCn = true;
      classSrc = `className={cn(${parts.join(", ")})}`;
    }

    // ---- build remaining style
    const keptSrc = kept.map((e) => e.src).filter(Boolean);
    const outer = styleAttr.initializer.expression;
    const cast = ts.isAsExpression(outer) || ts.isSatisfiesExpression(outer) ? ` ${ts.isAsExpression(outer) ? "as" : "satisfies"} ${outer.type.getText(sf)}` : "";
    const styleSrc = keptSrc.length ? `style={{ ${keptSrc.join(", ")} }${cast}}` : "";

    if (classAttr) {
      edits.push({ start: classAttr.getStart(sf), end: classAttr.getEnd(), text: classSrc });
      if (styleSrc) edits.push({ start: styleAttr.getStart(sf), end: styleAttr.getEnd(), text: styleSrc });
      else edits.push(removal(styleAttr));
    } else {
      edits.push({ start: styleAttr.getStart(sf), end: styleAttr.getEnd(), text: styleSrc ? `${classSrc} ${styleSrc}` : classSrc });
    }
    if (kept.length) stats.partial++; else stats.converted++;
  }
  function removal(attr) {
    // remove the attribute and the whitespace before it
    // remove the attribute and the whitespace before it, but never pull the
    // rest of the tag up onto a line that ends in a // comment
    let start = attr.getStart(sf);
    while (start > 0 && /[ \t]/.test(text[start - 1])) start--;
    if (text[start - 1] === "\n") {
      const lineStart = text.lastIndexOf("\n", start - 2) + 1;
      const prev = text.slice(lineStart, start - 1);
      if (!prev.includes("//")) {
        start--;
        while (start > 0 && /\s/.test(text[start - 1])) start--;
      }
    }
    return { start, end: attr.getEnd(), text: "" };
  }

  visit(sf);
  if (!edits.length) continue;

  // Nested elements inside a className expression would overlap: apply the
  // outermost edits, and let a re-run pick up the rest.
  edits.sort((a, b) => a.start - b.start || b.end - a.end);
  const applied = [];
  for (const e of edits) {
    if (applied.length && e.start < applied[applied.length - 1].end) continue;
    applied.push(e);
  }
  let out = text;
  for (const e of applied.reverse()) out = out.slice(0, e.start) + e.text + out.slice(e.end);

  if (needCn && !/import\s*\{[^}]*\bcn\b[^}]*\}\s*from\s*["']@\/lib\/cn["']/.test(out)) {
    out = addImport(out);
  }
  stats.files++;
  if (!DRY) fs.writeFileSync(file, out);
}

function addImport(src) {
  const sf = ts.createSourceFile("x.tsx", src, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const imports = sf.statements.filter((s) => ts.isImportDeclaration(s));
  const line = `import { cn } from "@/lib/cn";\n`;
  if (imports.length) {
    const last = imports[imports.length - 1];
    const end = last.getEnd();
    return src.slice(0, end) + "\n" + line.trimEnd() + src.slice(end);
  }
  // after a "use client" directive if there is one
  const first = sf.statements[0];
  if (first && ts.isExpressionStatement(first) && ts.isStringLiteral(first.expression)) {
    const end = first.getEnd();
    return src.slice(0, end) + "\n\n" + line.trimEnd() + src.slice(end);
  }
  return line + src;
}

if (LOG) fs.writeFileSync(LOG, JSON.stringify(cases));
console.log(JSON.stringify(stats));
