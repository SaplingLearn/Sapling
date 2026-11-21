/**
 * In-place equation editing: the slot model behind the Notes editor's math.
 *
 * There is no LaTeX code box. An equation renders with KaTeX, and every brace
 * group in its source is wrapped so the rendered glyphs carry the source
 * OFFSET they came from (`data-pos`). Clicking a glyph therefore names a span
 * of the LaTeX, which is what makes "click the numerator and type" work —
 * including on groups that already have something in them.
 *
 * Ported from `designs/notes-graph.js` (`slotTex`, `matchClose`, `slotCtx`,
 * `insertTpl`, `nextBox`), which is the handoff's source of truth for this.
 * The logic is unchanged; it is lifted out of the DOM so it can be tested.
 */

/**
 * The index of the brace or bracket that closes the one at `open`, or -1.
 * Escaped characters (`\{`) are skipped, so `\{` never opens or closes a group.
 */
export function matchClose(tex: string, open: number): number {
  const o = tex[open];
  const c = o === "{" ? "}" : "]";
  let depth = 0;
  for (let j = open; j < tex.length; j += 1) {
    if (tex[j] === "\\") { j += 1; continue; }
    if (tex[j] === o) depth += 1;
    else if (tex[j] === c) { depth -= 1; if (depth === 0) return j; }
  }
  return -1;
}

/**
 * Commands whose argument is not math and must not be wrapped: wrapping the
 * body of `\text{…}` would render the markup as words, and wrapping a
 * `\begin{…}` environment name would break the environment outright.
 */
const NOWRAP = /\\(text|mathrm|operatorname|begin|end|htmlClass|htmlData|textbf|mathbf|mathit)\s*$/;

/**
 * `tex`, with every brace group wrapped so the rendered output carries where
 * it came from:
 *
 *  - an EMPTY group becomes a dashed slot box (`.mslot`) — somewhere to type;
 *  - a FILLED group becomes `.mgrp`, clickable and recursively wrapped, so a
 *    numerator that already has something in it is still editable in place.
 *
 * `offset` is where `tex` starts inside the whole equation, so the emitted
 * positions are absolute.
 */
export function slotTex(tex: string, offset = 0): string {
  let out = "";
  let i = 0;
  while (i < tex.length) {
    const ch = tex[i];

    if (ch === "\\") {
      // A control sequence is copied whole: its name must not be split.
      const m = tex.slice(i).match(/^\\([a-zA-Z]+|.)/);
      if (!m) { out += ch; i += 1; continue; }
      out += m[0];
      i += m[0].length;
      continue;
    }

    // `[` opens a group only as a root index: `\sqrt[3]{x}`, or an empty `[]`.
    const isRootIndex = ch === "[" && /\\sqrt\s*$/.test(tex.slice(0, i));
    const isEmptyBracket = ch === "[" && /^\[\s*\]/.test(tex.slice(i));

    if (ch === "{" || isRootIndex || isEmptyBracket) {
      const j = matchClose(tex, i);
      if (j < 0) { out += ch; i += 1; continue; }
      const inner = tex.slice(i + 1, j);
      const close = tex[j];
      const pos = offset + i + 1;
      if (!inner.trim()) {
        out += `${ch}\\htmlData{pos=${pos}}{\\htmlClass{mslot}{\\phantom{0}}}${close}`;
      } else if (NOWRAP.test(tex.slice(0, i))) {
        out += ch + inner + close;
      } else {
        out += `${ch}\\htmlData{pos=${pos}}{\\htmlClass{mgrp}{${slotTex(inner, pos)}}}${close}`;
      }
      i = j + 1;
      continue;
    }

    out += ch;
    i += 1;
  }
  return out;
}

/** Where each empty slot starts, in source order — what Tab walks through. */
export function slotList(raw: string): number[] {
  const out: number[] = [];
  const re = /\{\s*\}|\[\s*\]/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(raw))) out.push(m.index + 1);
  return out;
}

/** The span of source currently being edited. `root` means the whole equation. */
export interface MathCtx {
  start: number;
  end: number;
  root: boolean;
}

/**
 * The context for the group that starts at `pos`, or the whole equation when
 * `pos` does not name one. A group that already has something in it opens with
 * the caret at its END, so typing extends rather than replaces.
 */
export function slotCtx(raw: string, pos: number): { ctx: MathCtx; caret: number } {
  const rootCtx = { ctx: { start: 0, end: raw.length, root: true }, caret: raw.length };
  if (pos < 1 || !/[{[]/.test(raw[pos - 1] || "")) return rootCtx;
  const close = matchClose(raw, pos - 1);
  if (close < 0) return rootCtx;
  const filled = raw.slice(pos, close).trim().length > 0;
  return {
    ctx: { start: pos, end: close, root: false },
    caret: filled ? close - pos : 0,
  };
}

/**
 * Where Tab (or Shift+Tab) goes next.
 *
 * Inside a group, the next empty slot after it; from the root, the next one
 * after the caret. When there is none and we are inside a group, the caret
 * steps out past the group's closing brace — and past any empty groups that
 * immediately follow, so `\frac{a}{}` does not trap it between the two.
 * Returns null when there is nowhere left to go.
 */
export function nextBox(
  raw: string, ctx: MathCtx | null, caretInCtx: number, back = false,
): { ctx: MathCtx; caret: number } | null {
  const slots = slotList(raw);
  const cursor = ctx ? ctx.start + caretInCtx : raw.length;
  const from = ctx && !ctx.root ? (back ? ctx.start : ctx.end) : cursor;
  const target = back
    ? [...slots].reverse().find(p => p < from)
    : slots.find(p => p > from);

  if (target != null) return slotCtx(raw, target);

  if (ctx && !ctx.root) {
    const close = ctx.end + 1;
    const trailing = (raw.slice(close).match(/^(\{\s*\}|\[\s*\])+/) || [""])[0].length;
    return {
      ctx: { start: 0, end: raw.length, root: true },
      caret: Math.min(raw.length, close + trailing),
    };
  }
  return null;
}

/**
 * Insert a template (`\frac{}{}`, `^{}`, …) at the caret.
 *
 * Returns the new source, and where to put the caret next: the template's
 * first empty slot if it has one, otherwise just past what was inserted. A
 * space is added when a letter would otherwise run into the control sequence
 * before it (`\alpha` + `x` must not become `\alphax`).
 */
export function insertTpl(
  raw: string, ctx: MathCtx, selStart: number, selEnd: number, tpl: string,
): { raw: string; ctx: MathCtx; caret: number } {
  const value = raw.slice(ctx.start, ctx.end);
  const pad = /^[a-zA-Z]/.test(tpl) && /\\[a-zA-Z]+$/.test(value.slice(0, selStart)) ? " " : "";
  const next = value.slice(0, selStart) + pad + tpl + value.slice(selEnd);
  const nextRaw = raw.slice(0, ctx.start) + next + raw.slice(ctx.end);
  const nextCtx: MathCtx = { ...ctx, end: ctx.start + next.length };

  const inTpl = slotList(tpl);
  if (inTpl.length) {
    const abs = ctx.start + selStart + pad.length + inTpl[0];
    return { raw: nextRaw, ...slotCtx(nextRaw, abs) };
  }
  return { raw: nextRaw, ctx: nextCtx, caret: selStart + pad.length + tpl.length };
}

/**
 * Typing `/` after a term makes a fraction of it: `1/` becomes `\frac{1}{}`
 * with the caret in the denominator. Returns null when there is no term to
 * take — a bare `/` is just a slash.
 */
export function fractionAt(value: string, selStart: number): { term: string; from: number } | null {
  const m = value.slice(0, selStart).match(/([A-Za-z0-9.]+|\\[a-zA-Z]+)$/);
  if (!m) return null;
  return { term: m[1], from: selStart - m[1].length };
}

/** The symbol palette: a label, and the LaTeX it inserts. */
export const SYMBOLS: [string, string][] = [
  ["a⁄b", "\\frac{}{}"], ["x²", "^{}"], ["xₙ", "_{}"], ["√", "\\sqrt{}"],
  ["ⁿ√", "\\sqrt[]{}"], ["( )", "\\left( {} \\right)"], ["|x|", "\\left| {} \\right|"],
  ["∑", "\\sum_{}^{} "], ["∫", "\\int_{}^{} "], ["lim", "\\lim_{{} \\to {}} "],
  ["v⃗", "\\vec{}"], ["x̄", "\\bar{}"],
  ["π", "\\pi "], ["θ", "\\theta "], ["λ", "\\lambda "], ["Δ", "\\Delta "],
  ["∞", "\\infty "], ["≈", "\\approx "], ["≠", "\\neq "], ["≤", "\\le "], ["≥", "\\ge "],
  ["±", "\\pm "], ["×", "\\times "], ["·", "\\cdot "], ["→", "\\to "], ["∂", "\\partial "],
  ["α", "\\alpha "], ["β", "\\beta "], ["μ", "\\mu "], ["σ", "\\sigma "],
  ["∈", "\\in "], ["°", "^{\\circ}"],
];

/** How many of `SYMBOLS` are structures (the first grid); the rest are symbols. */
export const STRUCTURE_COUNT = 12;

/** What a palette button renders as, when a template's own LaTeX would not read. */
export const SYMBOL_PREVIEW: Record<string, string> = {
  "^{}": "x^{\\square}",
  "_{}": "x_{\\square}",
  "\\sqrt[]{}": "\\sqrt[n]{x}",
  "\\left( {} \\right)": "(\\,)",
  "\\left| {} \\right|": "|x|",
  "\\lim_{{} \\to {}} ": "\\lim",
  "\\vec{}": "\\vec{v}",
  "\\bar{}": "\\bar{x}",
  "\\sum_{}^{} ": "\\sum",
  "\\int_{}^{} ": "\\int",
  "\\frac{}{}": "\\frac{a}{b}",
  "\\sqrt{}": "\\sqrt{x}",
};

/** Unicode a student may paste or type, as the LaTeX it means. */
const TEXMAP: [RegExp, string][] = [
  [/−/g, "-"], [/λ/g, "\\lambda "], [/·/g, "\\cdot "], [/×/g, "\\times "],
  [/π/g, "\\pi "], [/θ/g, "\\theta "], [/Δ/g, "\\Delta "], [/∑/g, "\\sum "],
  [/∫/g, "\\int "], [/∞/g, "\\infty "], [/≈/g, "\\approx "], [/≠/g, "\\neq "],
  [/≤/g, "\\le "], [/≥/g, "\\ge "], [/±/g, "\\pm "], [/÷/g, "\\div "], [/→/g, "\\to "],
  [/²/g, "^2"], [/³/g, "^3"], [/√/g, "\\sqrt "], [/α/g, "\\alpha "], [/β/g, "\\beta "],
  [/μ/g, "\\mu "], [/σ/g, "\\sigma "], [/∂/g, "\\partial "], [/\bdet\b/g, "\\det"],
];

export function toTex(s: string): string {
  return TEXMAP.reduce((t, [re, v]) => t.replace(re, v), String(s || "").trim());
}
