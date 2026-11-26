// Convert one CSS declaration (React style key + CSS value) to Tailwind classes
// in Sapling's theme (src/styles/theme.css). Shared by the inline-style codemod
// and its browser equivalence check.
//
// toClasses(prop, value, { strict }) -> string[]
//   prop   React camelCase key ("paddingTop", "WebkitLineClamp", "--x")
//   value  the CSS value React would write (numbers already given their px)
//   strict the element also has non-Tailwind classes: shorthands that reset
//          hidden longhands (background) stay exact arbitrary properties
//
// Anything without an idiomatic utility becomes an exact arbitrary property,
// [prop:value], so every declaration converts and none change meaning.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const stylesDir = path.resolve(here, "../../src/styles");
const themeCss = fs.readFileSync(path.join(stylesDir, "theme.css"), "utf8");
const tokensCss = fs.readFileSync(path.join(stylesDir, "tokens.css"), "utf8");

export const COLORS = new Set([...themeCss.matchAll(/--color-([a-z0-9-]+):/g)].map((m) => m[1]));
COLORS.delete("*");

const tokenDefs = [...tokensCss.matchAll(/^\s*--([a-z0-9-]+):\s*([^;]+);/gm)].map((m) => [m[1], m[2].trim()]);

// px -> font size name (text-md = 13px)
const FONT_SIZE = new Map();
for (const [k, v] of tokenDefs) {
  const m = /^fs-(.+)$/.exec(k);
  if (m && /^\d+px$/.test(v)) FONT_SIZE.set(parseFloat(v), m[1]);
}
const RADIUS = new Map();
for (const [k, v] of tokenDefs) {
  const m = /^r-(xs|sm|md|lg|xl)$/.exec(k);
  if (m && /^\d+px$/.test(v)) RADIUS.set(parseFloat(v), m[1]);
}
// exact hex -> first colour token defined with that literal value
export const HEX = new Map();
for (const [k, v] of tokenDefs) {
  if (/^#[0-9a-f]{3}([0-9a-f]{3})?$/i.test(v) && COLORS.has(k)) {
    const key = normHex(v);
    if (!HEX.has(key)) HEX.set(key, k);
  }
}
function normHex(h) {
  h = h.toLowerCase();
  if (h.length === 4) h = "#" + [...h.slice(1)].map((c) => c + c).join("");
  return h;
}

// React's unitless properties (react-dom/shared/isUnitlessNumber)
const UNITLESS = new Set(
  "animationIterationCount aspectRatio borderImageOutset borderImageSlice borderImageWidth boxFlex boxFlexGroup boxOrdinalGroup columnCount columns flex flexGrow flexPositive flexShrink flexNegative flexOrder gridArea gridRow gridRowEnd gridRowSpan gridRowStart gridColumn gridColumnEnd gridColumnSpan gridColumnStart fontWeight lineClamp lineHeight opacity order orphans scale tabSize widows zIndex zoom fillOpacity floodOpacity stopOpacity strokeDasharray strokeDashoffset strokeMiterlimit strokeOpacity strokeWidth".split(" "),
);
export function isUnitless(prop) {
  if (prop.startsWith("--")) return true;
  const bare = prop.replace(/^(Webkit|Moz|ms|O)(?=[A-Z])/, "");
  return UNITLESS.has(bare.charAt(0).toLowerCase() + bare.slice(1));
}
export function cssValue(prop, v) {
  if (typeof v === "number") return v !== 0 && !isUnitless(prop) ? `${v}px` : String(v);
  return String(v).trim().replace(/\s+/g, " ").replace(/"/g, "'");
}
export function kebab(prop) {
  if (prop.startsWith("--")) return prop;
  let p = prop.replace(/^(Webkit|Moz|O)(?=[A-Z])/, (m) => "-" + m.toLowerCase());
  p = p.replace(/^ms(?=[A-Z])/, "-ms");
  return p.replace(/[A-Z]/g, (c) => "-" + c.toLowerCase());
}

// ---- value helpers --------------------------------------------------------
function enc(v) {
  return v.replace(/_/g, "\\_").replace(/ /g, "_");
}
function arbitraryProperty(prop, v) {
  return `[${kebab(prop)}:${enc(v)}]`;
}
function splitTop(v) {
  const out = [];
  let depth = 0, cur = "";
  for (const ch of v) {
    if (ch === "(") depth++;
    if (ch === ")") depth--;
    if (ch === " " && depth === 0) {
      if (cur) out.push(cur);
      cur = "";
    } else cur += ch;
  }
  if (cur) out.push(cur);
  return out;
}
function pxOf(v) {
  if (v === "0") return 0;
  const m = /^(-?\d*\.?\d+)px$/.exec(v);
  return m ? parseFloat(m[1]) : null;
}
const FRACTIONS = { "50%": "1/2", "25%": "1/4", "75%": "3/4", "20%": "1/5", "40%": "2/5", "60%": "3/5", "80%": "4/5" };
// A length on Tailwind's spacing scale (4px step), or an arbitrary value.
// kind: "space" (p/m/gap), "size" (w/h/min/max/inset/basis)
function len(v, kind) {
  if (v === "auto" && kind !== "space-noauto") return "auto";
  const n = pxOf(v);
  if (n !== null) {
    if (n === 0) return "0";
    const a = Math.abs(n);
    let s;
    if (a === 1) s = "px";
    else if (Number.isInteger(a) && a % 2 === 0) s = String(a / 4);
    else return `[${v}]`;
    return n < 0 ? { neg: s } : s;
  }
  const m = /^var\((--[a-z0-9-]+)\)$/.exec(v);
  if (m) return `(${m[1]})`;
  if (kind === "size") {
    if (v === "100%") return "full";
    if (FRACTIONS[v]) return FRACTIONS[v];
    if (v === "fit-content") return "fit";
    if (v === "max-content") return "max";
    if (v === "min-content") return "min";
  }
  if (/\s/.test(v) && !/^(calc|min|max|clamp|var)\(/.test(v)) return null;
  return `[${enc(v)}]`;
}
function withPrefix(prefix, l) {
  if (l === null) return null;
  if (typeof l === "object") return `-${prefix}-${l.neg}`;
  return `${prefix}-${l}`;
}
function sizeClass(prefix, v, extra = {}) {
  if (extra[v]) return `${prefix}-${extra[v]}`;
  return withPrefix(prefix, len(v, "size"));
}
// padding/margin/inset shorthand with 1-4 values
function box(prefix, v, kind) {
  const parts = splitTop(v);
  if (parts.length < 1 || parts.length > 4) return null;
  const [t, r = t, b = t, l = r] = parts;
  const P = prefix; // p | m | inset
  const side = (s) => (P === "inset" ? { t: "top", r: "right", b: "bottom", l: "left", x: "inset-x", y: "inset-y" }[s] : P + s);
  const one = (pre, x) => withPrefix(pre, len(x, kind));
  let out;
  if (t === r && r === b && b === l) out = [one(P, t)];
  else if (t === b && l === r) out = [one(side("y"), t), one(side("x"), l)];
  else if (l === r) out = [one(side("t"), t), one(side("x"), l), one(side("b"), b)];
  else out = [one(side("t"), t), one(side("r"), r), one(side("b"), b), one(side("l"), l)];
  return out.includes(null) ? null : out;
}
export function colorName(v) {
  const m = /^var\(--([a-z0-9-]+)\)$/.exec(v);
  if (m) return COLORS.has(m[1]) ? m[1] : null;
  if (/^#[0-9a-f]{3}([0-9a-f]{3})?$/i.test(v)) return HEX.get(normHex(v)) ?? `[${v}]`;
  if (/^#[0-9a-f]{8}$/i.test(v)) return `[${v}]`;
  if (/^(rgba?|hsla?|oklch|color-mix)\(/.test(v)) return `[${enc(v)}]`;
  if (v === "transparent" || v === "inherit") return v;
  if (v === "currentColor" || v === "currentcolor") return "current";
  if (v === "white" || v === "#fff" || v === "#ffffff") return "white";
  if (v === "black") return "black";
  return null;
}
const BORDER_STYLES = new Set(["solid", "dashed", "dotted", "double", "none", "hidden"]);
function border(prop, v) {
  const side = { border: "", borderTop: "t", borderRight: "r", borderBottom: "b", borderLeft: "l" }[prop];
  const pre = side ? `border-${side}` : "border";
  // width 0, never border-none: border-none sets --tw-border-style, which a
  // later border-b on the same element would inherit and draw nothing
  if (v === "none" || v === "0") return [`${pre}-0`];
  const parts = splitTop(v);
  let width = null, style = null, color = null;
  for (const p of parts) {
    if (BORDER_STYLES.has(p)) style = p;
    else if (pxOf(p) !== null || p === "thin") width = p;
    else if (color === null) color = p;
    else return null;
  }
  if (style === null || style === "hidden") return null; // CSS: no style = none
  if (style === "none") return [`${pre}-0`];
  const out = [];
  const w = width === null ? "medium" : width;
  if (w === "1px") out.push(pre);
  else if (pxOf(w) !== null) out.push(pxOf(w) === 0 ? `${pre}-0` : Number.isInteger(pxOf(w)) ? `${pre}-${pxOf(w)}` : `${pre}-[${w}]`);
  else return null;
  if (style !== "solid") {
    if (side) return null; // border-dashed is all sides
    out.push(`border-${style}`);
  }
  const c = color === null ? "current" : colorName(color);
  if (c === null) return null;
  out.push(`${pre}-${c}`);
  return out;
}

const KEYWORDS = {
  display: { flex: "flex", "inline-flex": "inline-flex", block: "block", "inline-block": "inline-block", grid: "grid", "inline-grid": "inline-grid", none: "hidden", inline: "inline", contents: "contents", table: "table", "table-cell": "table-cell", "list-item": "list-item", "flow-root": "flow-root" },
  position: { absolute: "absolute", relative: "relative", fixed: "fixed", sticky: "sticky", static: "static" },
  flexDirection: { column: "flex-col", row: "flex-row", "column-reverse": "flex-col-reverse", "row-reverse": "flex-row-reverse" },
  flexWrap: { wrap: "flex-wrap", nowrap: "flex-nowrap", "wrap-reverse": "flex-wrap-reverse" },
  alignItems: { center: "items-center", "flex-start": "items-start", "flex-end": "items-end", baseline: "items-baseline", stretch: "items-stretch" },
  alignSelf: { center: "self-center", "flex-start": "self-start", "flex-end": "self-end", stretch: "self-stretch", baseline: "self-baseline", auto: "self-auto" },
  alignContent: { center: "content-center", "flex-start": "content-start", "flex-end": "content-end", "space-between": "content-between" },
  justifyContent: { center: "justify-center", "space-between": "justify-between", "flex-start": "justify-start", "flex-end": "justify-end", "space-around": "justify-around", "space-evenly": "justify-evenly", stretch: "justify-stretch" },
  justifyItems: { center: "justify-items-center", start: "justify-items-start", end: "justify-items-end", stretch: "justify-items-stretch" },
  justifySelf: { center: "justify-self-center", stretch: "justify-self-stretch", auto: "justify-self-auto" },
  placeItems: { center: "place-items-center", start: "place-items-start", end: "place-items-end", stretch: "place-items-stretch" },
  placeContent: { center: "place-content-center" },
  placeSelf: { center: "place-self-center" },
  textAlign: { center: "text-center", left: "text-left", right: "text-right", justify: "text-justify", start: "text-start", end: "text-end" },
  textTransform: { uppercase: "uppercase", lowercase: "lowercase", capitalize: "capitalize", none: "normal-case" },
  fontStyle: { italic: "italic", normal: "not-italic" },
  fontWeight: { 100: "font-thin", 200: "font-extralight", 300: "font-light", 400: "font-normal", 500: "font-medium", 600: "font-semibold", 700: "font-bold", 800: "font-extrabold", 900: "font-black", normal: "font-normal", bold: "font-bold" },
  whiteSpace: { nowrap: "whitespace-nowrap", normal: "whitespace-normal", pre: "whitespace-pre", "pre-wrap": "whitespace-pre-wrap", "pre-line": "whitespace-pre-line", "break-spaces": "whitespace-break-spaces" },
  textOverflow: { ellipsis: "text-ellipsis", clip: "text-clip" },
  overflow: { hidden: "overflow-hidden", auto: "overflow-auto", scroll: "overflow-scroll", visible: "overflow-visible", clip: "overflow-clip" },
  overflowX: { hidden: "overflow-x-hidden", auto: "overflow-x-auto", scroll: "overflow-x-scroll", visible: "overflow-x-visible", clip: "overflow-x-clip" },
  overflowY: { hidden: "overflow-y-hidden", auto: "overflow-y-auto", scroll: "overflow-y-scroll", visible: "overflow-y-visible", clip: "overflow-y-clip" },
  visibility: { hidden: "invisible", visible: "visible", collapse: "collapse" },
  pointerEvents: { none: "pointer-events-none", auto: "pointer-events-auto" },
  userSelect: { none: "select-none", text: "select-text", all: "select-all", auto: "select-auto" },
  boxSizing: { "border-box": "box-border", "content-box": "box-content" },
  objectFit: { cover: "object-cover", contain: "object-contain", fill: "object-fill", none: "object-none", "scale-down": "object-scale-down" },
  verticalAlign: { middle: "align-middle", top: "align-top", bottom: "align-bottom", baseline: "align-baseline", "text-top": "align-text-top", "text-bottom": "align-text-bottom", "sub": "align-sub", "super": "align-super" },
  wordBreak: { "break-all": "break-all", "keep-all": "break-keep", normal: "break-normal" },
  listStyle: { none: "list-none" },
  listStyleType: { none: "list-none", disc: "list-disc", decimal: "list-decimal" },
  resize: { none: "resize-none", vertical: "resize-y", horizontal: "resize-x", both: "resize" },
  appearance: { none: "appearance-none", auto: "appearance-auto" },
  isolation: { isolate: "isolate", auto: "isolation-auto" },
  fontVariantNumeric: { "tabular-nums": "tabular-nums", normal: "normal-nums", "lining-nums": "lining-nums", "oldstyle-nums": "oldstyle-nums" },
  textDecoration: { none: "no-underline", underline: "underline", "line-through": "line-through" },
  textDecorationLine: { none: "no-underline", underline: "underline", "line-through": "line-through" },
  flexShrink: { 0: "shrink-0", 1: "shrink" },
  flexGrow: { 0: "grow-0", 1: "grow" },
  mixBlendMode: { multiply: "mix-blend-multiply", screen: "mix-blend-screen", overlay: "mix-blend-overlay" },
  tableLayout: { fixed: "table-fixed", auto: "table-auto" },
  borderCollapse: { collapse: "border-collapse", separate: "border-separate" },
  scrollBehavior: { smooth: "scroll-smooth" },
  textWrap: { balance: "text-balance", pretty: "text-pretty", nowrap: "text-nowrap", wrap: "text-wrap" },
  touchAction: { none: "touch-none", manipulation: "touch-manipulation" },
  fill: { none: "fill-none" },
  stroke: { none: "stroke-none" },
  outline: { none: "outline-none" },
};
const CURSORS = new Set("auto default pointer wait text move help not-allowed none context-menu progress cell crosshair vertical-text alias copy no-drop grab grabbing all-scroll col-resize row-resize n-resize e-resize s-resize w-resize ne-resize nw-resize se-resize sw-resize ew-resize ns-resize nesw-resize nwse-resize zoom-in zoom-out".split(" "));
const SPACE_PREFIX = { padding: "p", margin: "m", paddingTop: "pt", paddingRight: "pr", paddingBottom: "pb", paddingLeft: "pl", paddingInline: "px", paddingBlock: "py", marginTop: "mt", marginRight: "mr", marginBottom: "mb", marginLeft: "ml", marginInline: "mx", marginBlock: "my", gap: "gap", rowGap: "gap-y", columnGap: "gap-x" };
const SIZE_PREFIX = { width: "w", height: "h", minWidth: "min-w", maxWidth: "max-w", minHeight: "min-h", maxHeight: "max-h", top: "top", right: "right", bottom: "bottom", left: "left", flexBasis: "basis", inset: "inset" };
const COLOR_PREFIX = { color: "text", backgroundColor: "bg", borderColor: "border", borderTopColor: "border-t", borderRightColor: "border-r", borderBottomColor: "border-b", borderLeftColor: "border-l", fill: "fill", stroke: "stroke", outlineColor: "outline", caretColor: "caret", accentColor: "accent", textDecorationColor: "decoration" };
const FONT_ROLE = { "var(--font-sans)": "font-sans", "var(--font-serif)": "font-serif", "var(--font-display)": "font-display", "var(--font-code)": "font-code" };

function convert(prop, v, strict) {
  const kw = KEYWORDS[prop];
  if (kw && kw[v] !== undefined) return [kw[v]];

  if (SPACE_PREFIX[prop]) {
    const pre = SPACE_PREFIX[prop];
    if (prop === "padding" || prop === "margin") return box(pre, v, pre === "p" ? "space-noauto" : "space");
    if (prop === "gap" && splitTop(v).length === 2) {
      const [r, c] = splitTop(v);
      const a = withPrefix("gap-y", len(r, "space-noauto")), b = withPrefix("gap-x", len(c, "space-noauto"));
      return a && b ? [a, b] : null;
    }
    const c = withPrefix(pre, len(v, pre.startsWith("p") || pre.startsWith("gap") ? "space-noauto" : "space"));
    return c ? [c] : null;
  }
  if (prop === "inset") return box("inset", v, "size");
  if (SIZE_PREFIX[prop]) {
    const pre = SIZE_PREFIX[prop];
    const extra = {};
    if (pre === "w") Object.assign(extra, { "100vw": "screen", "100dvw": "dvw" });
    if (pre === "h" || pre === "min-h" || pre === "max-h") Object.assign(extra, { "100vh": "screen", "100dvh": "dvh", "100svh": "svh" });
    if (pre === "max-w" || pre === "max-h") extra.none = "none";
    if (pre === "basis") extra.auto = "auto";
    const c = sizeClass(pre, v, extra);
    return c ? [c] : null;
  }
  if (COLOR_PREFIX[prop]) {
    const c = colorName(v);
    return c === null ? null : [`${COLOR_PREFIX[prop]}-${c}`];
  }
  switch (prop) {
    case "background": {
      if (strict) return null;
      const c = colorName(v);
      if (c !== null) return [`bg-${c}`];
      return null;
    }
    case "border": case "borderTop": case "borderRight": case "borderBottom": case "borderLeft":
      return border(prop, v);
    case "borderWidth": {
      const n = pxOf(v);
      if (n === 1) return ["border"];
      if (n !== null && Number.isInteger(n)) return [`border-${n}`];
      return null;
    }
    case "borderStyle":
      return ["solid", "dashed", "dotted", "double", "none"].includes(v) ? [`border-${v}`] : null;
    case "borderRadius": {
      const n = pxOf(v);
      if (n === 0) return ["rounded-none"];
      if (n !== null && n >= 999) return ["rounded-full"];
      if (n !== null && RADIUS.has(n)) return [`rounded-${RADIUS.get(n)}`];
      const m = /^var\(--r-(xs|sm|md|lg|xl|full)\)$/.exec(v);
      if (m) return [m[1] === "full" ? "rounded-[var(--r-full)]" : `rounded-${m[1]}`];
      if (!/\s/.test(v) || /^(calc|var)\(/.test(v)) return [`rounded-[${enc(v)}]`];
      return null;
    }
    case "fontSize": {
      const n = pxOf(v);
      if (n !== null && FONT_SIZE.has(n)) return [`text-${FONT_SIZE.get(n)}`];
      const m = /^var\(--fs-([a-z0-9]+)\)$/.exec(v);
      if (m && [...FONT_SIZE.values()].includes(m[1])) return [`text-${m[1]}`];
      if (n !== null) return [`text-[${v}]`];
      if (/^(\d*\.?\d+(rem|em|%|vw|vh)|clamp\(|calc\(|min\(|max\()/.test(v)) return [`text-[length:${enc(v)}]`];
      return null;
    }
    case "fontFamily": {
      // A stack is named by the face it leads with; the trailing fallbacks
      // only differ in which system font shows if the webfont never loads.
      if (FONT_ROLE[v]) return [FONT_ROLE[v]];
      const head = /^var\(--font-([a-z]+)\)/.exec(v)?.[1];
      const role = { suse: "font-sans", sans: "font-sans", aleo: "font-serif", serif: "font-serif", gummi: "font-display", display: "font-display", code: "font-code" }[head];
      return role ? [role] : null;
    }
    case "lineHeight": {
      if (v === "1") return ["leading-none"];
      if (/^\d*\.?\d+(px|rem|em|%)?$/.test(v)) return [`leading-[${v}]`];
      return null;
    }
    case "letterSpacing":
      if (/^-?\d*\.?\d+(px|em|rem)$/.test(v) || v === "0") return [`tracking-[${v}]`];
      return null;
    case "opacity": {
      const n = parseFloat(v);
      if (!Number.isNaN(n) && String(n) === v) {
        const k = Math.round(n * 100);
        if (Math.abs(k - n * 100) < 1e-9) return [`opacity-${k}`];
        return [`opacity-[${v}]`];
      }
      return null;
    }
    case "zIndex": {
      if (/^-?\d+$/.test(v)) return [v.startsWith("-") ? `-z-${v.slice(1)}` : `z-${v}`];
      if (v === "auto") return ["z-auto"];
      return null;
    }
    case "flex": {
      if (v === "1") return ["flex-1"];
      if (v === "none") return ["flex-none"];
      if (v === "auto") return ["flex-auto"];
      if (/^\d+$/.test(v)) return [`flex-${v}`];
      return [`flex-[${enc(v)}]`];
    }
    case "flexShrink":
      return /^\d+$/.test(v) ? [`shrink-${v}`] : null;
    case "flexGrow":
      return /^\d+$/.test(v) ? [`grow-${v}`] : null;
    case "order":
      return /^-?\d+$/.test(v) ? [v.startsWith("-") ? `-order-${v.slice(1)}` : `order-${v}`] : null;
    case "cursor":
      return CURSORS.has(v) ? [`cursor-${v}`] : null;
    case "boxShadow": {
      if (v === "none") return ["shadow-none"];
      const m = /^var\(--shadow-(sm|md|lg|inset)\)$/.exec(v);
      if (m) return [`shadow-${m[1]}`];
      return null; // keep exact; Tailwind's shadow-[..] re-colours via --tw-shadow-color
    }
    case "gridTemplateColumns":
      return [`grid-cols-[${enc(v)}]`];
    case "gridTemplateRows":
      return [`grid-rows-[${enc(v)}]`];
    case "aspectRatio":
      if (v === "1" || v === "1 / 1" || v === "1/1") return ["aspect-square"];
      if (v === "16 / 9" || v === "16/9") return ["aspect-video"];
      return [`aspect-[${enc(v.replace(/ /g, ""))}]`];
    case "objectPosition":
      return v === "center" ? ["object-center"] : null;
    case "transformOrigin":
      return v === "center" ? ["origin-center"] : null;
    default:
      return null;
  }
}

export function toClasses(prop, value, { strict = false } = {}) {
  const v = cssValue(prop, value);
  if (v === "") return [];
  const c = convert(prop, v, strict);
  return c ?? [arbitraryProperty(prop, v)];
}
