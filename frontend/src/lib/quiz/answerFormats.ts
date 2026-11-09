/**
 * Live read-backs for the written answer inputs — what the grader will make of
 * what the student has typed, before they submit it.
 *
 * DISPLAY ONLY. Grading stays server-side (`services/quiz_grading.py`,
 * `services/quiz_algebra.py`); these mirror the accepted notation closely
 * enough to say "this reads as 0.75" or "functions aren't supported", and a
 * disagreement can only mislabel a preview, never a score.
 */

const THOUSANDS = /^[+-]?\d{1,3}(?:,\d{3})+(?:\.\d*)?$/;
const MIXED = /^([+-]?)(\d{1,40})\s+(\d{1,40})\/(\d{1,40})$/;
const NUMBER = String.raw`[+-]?(?:\d{1,40}(?:\.\d{0,40})?|\.\d{1,40})(?:[eE][+-]?\d{1,2})?`;
const SIMPLE = new RegExp(`^(${NUMBER})(?:/(${NUMBER}))?$`);

/**
 * `quiz_grading.numeric_value`, as a float: decimals, scientific (`3e8`),
 * fractions, mixed numbers (`1 1/2`), strict thousands groups (`1,000`) and
 * percentages. `null` for anything the grader would refuse.
 */
export function numericValue(raw: string): number | null {
  let value = raw.normalize("NFKC").trim().replace(/−/g, "-").replace(/⁄/g, "/");
  if (!value || value.length > 128) return null;
  const percent = value.endsWith("%");
  if (percent) value = value.slice(0, -1).trim();
  if (THOUSANDS.test(value)) value = value.replace(/,/g, "");
  value = value.replace(/\s*\/\s*/g, "/");

  let result: number;
  const mixed = MIXED.exec(value);
  if (mixed) {
    const denominator = Number(mixed[4]);
    if (denominator === 0) return null;
    result = Number(mixed[2]) + Number(mixed[3]) / denominator;
    if (mixed[1] === "-") result = -result;
  } else {
    const simple = SIMPLE.exec(value);
    if (!simple) return null;
    result = Number(simple[1]);
    if (simple[2] !== undefined) {
      const denominator = Number(simple[2]);
      if (denominator === 0) return null;
      result /= denominator;
    }
  }
  if (!Number.isFinite(result)) return null;
  return percent ? result / 100 : result;
}

/** A read-back value without float noise (`0.1 + 0.2` shows as 0.3). */
export function formatNumber(value: number): string {
  return String(Number(value.toPrecision(10)));
}

/** Letter runs the algebra grammar refuses rather than read as products. */
const FUNCTION_NAME = /sin|cos|tan|sec|csc|cot|log|ln|exp|sqrt|abs/i;

/** Why an algebra answer can't be graded as typed, or null. */
export function symbolicProblem(raw: string): string | null {
  const text = raw.trim();
  if (!text) return null;
  if (text.includes("=")) return "Enter an expression, not an equation — leave out the “=”.";
  for (const run of text.match(/[A-Za-z]+/g) ?? []) {
    if (FUNCTION_NAME.test(run)) return "Functions like sin, log or sqrt aren't supported.";
  }
  let depth = 0;
  for (const ch of text) {
    if (ch === "(") depth += 1;
    if (ch === ")") depth -= 1;
    if (depth < 0) return "There's a “)” without a matching “(”.";
  }
  if (depth > 0) return "A bracket isn't closed yet.";
  return null;
}

export type ExpressionPart = { text: string; sup: boolean };

/**
 * An algebra answer split for display: exponents raised, `*` as a centred
 * dot, `-` as a true minus. `2x^2 - 3*y^(n+1)` → 2x² − 3·yⁿ⁺¹, as parts the
 * input's preview renders with `<sup>`.
 */
export function expressionParts(raw: string): ExpressionPart[] {
  return superscriptParts(raw, s => s.replace(/\*/g, "·").replace(/-/g, "−"));
}

/**
 * Exponents raised and nothing else touched — for a question STEM, where a `-`
 * may be a hyphen in prose and a `*` emphasis, so only `^n` is read as maths.
 * `Expand (x + 1)^2` → Expand (x + 1)².
 */
export function superscriptParts(
  raw: string,
  pretty: (s: string) => string = s => s,
): ExpressionPart[] {
  const parts: ExpressionPart[] = [];
  const exponent = /\^(\(([^()]*)\)|[+-]?\d+(?:\.\d+)?|[A-Za-z])/g;
  let last = 0;
  for (const m of raw.matchAll(exponent)) {
    const at = m.index ?? 0;
    if (at > last) parts.push({ text: pretty(raw.slice(last, at)), sup: false });
    parts.push({ text: pretty(m[2] ?? m[1]), sup: true });
    last = at + m[0].length;
  }
  if (last < raw.length) parts.push({ text: pretty(raw.slice(last)), sup: false });
  return parts;
}

// ── The algebra field, typeset in place ─────────────────────────────────
//
// The symbolic input SHOWS its answer the way the grader will read it —
// `x^2` as x², `*` as ·, `-` as − — while the session (and so the grader)
// only ever holds the plain ASCII the grammar accepts. The two functions
// below are that boundary: `prettyExpression` for what the field displays,
// `asciiExpression` for what goes back into the session.
//
// The backend NFKC-normalises answers, which reads ² as a bare 2 (x² → x2),
// so a typeset character must never reach it: `asciiExpression` is what
// keeps that from happening.

const SUPERSCRIPT: Record<string, string> = {
  "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹",
  "+": "⁺", "-": "⁻", "(": "⁽", ")": "⁾",
  a: "ᵃ", b: "ᵇ", c: "ᶜ", d: "ᵈ", e: "ᵉ", f: "ᶠ", g: "ᵍ", h: "ʰ", i: "ⁱ", j: "ʲ", k: "ᵏ", l: "ˡ", m: "ᵐ",
  n: "ⁿ", o: "ᵒ", p: "ᵖ", r: "ʳ", s: "ˢ", t: "ᵗ", u: "ᵘ", v: "ᵛ", w: "ʷ", x: "ˣ", y: "ʸ", z: "ᶻ",
};
const FROM_SUPERSCRIPT: Record<string, string> = Object.fromEntries(
  Object.entries(SUPERSCRIPT).map(([plain, sup]) => [sup, plain]),
);
const PRETTY_OPERATOR: Record<string, string> = { "*": "·", "-": "−" };
const PLAIN_OPERATOR: Record<string, string> = { "·": "*", "×": "*", "−": "-", "÷": "/" };

/** The exponents `expressionParts` raises: `^(…)`, `^-12`, `^n`. */
const EXPONENT = /\^(\([^()]*\)|[+-]?\d+(?:\.\d+)?|[A-Za-z])/g;

/**
 * ASCII → what the field shows. Only a NUMBER exponent is raised (x^2,
 * 10^-3). A letter or bracketed one (x^n, 2^(n+1)) stays as typed: the
 * reading serif has superscript digits and signs but no superscript letters
 * or brackets, so those would fall back to another font, sit at another
 * height, and read worse than the caret does.
 */
export function prettyExpression(ascii: string): string {
  const operators = (s: string) => s.replace(/[*-]/g, ch => PRETTY_OPERATOR[ch]);
  let out = "";
  let last = 0;
  let raisedEnd = -1;
  for (const m of ascii.matchAll(EXPONENT)) {
    const at = m.index ?? 0;
    const body = m[1];
    if (!/^[+-]?\d+$/.test(body)) continue;
    // A power stacked straight onto a raised one (x^2^3) stays as typed: two
    // superscript runs side by side would read back as ONE exponent.
    if (at === raisedEnd) continue;
    out += operators(ascii.slice(last, at)) + [...body].map(ch => SUPERSCRIPT[ch]).join("");
    last = at + m[0].length;
    raisedEnd = last;
  }
  return out + operators(ascii.slice(last));
}

/** What the field shows → the ASCII the grader reads. A run of superscripts
 *  is one exponent (`x²³` → `x^23`, `x⁽ⁿ⁺¹⁾` → `x^(n+1)`). */
export function asciiExpression(display: string): string {
  let out = "";
  let run = "";
  for (const ch of display) {
    if (ch in FROM_SUPERSCRIPT) {
      run += FROM_SUPERSCRIPT[ch];
      continue;
    }
    if (run) {
      out += `^${run}`;
      run = "";
    }
    out += PLAIN_OPERATOR[ch] ?? ch;
  }
  return run ? `${out}^${run}` : out;
}

// ── The numeric field, typeset in place ─────────────────────────────────
//
// Only NOTATION is typeset — e-notation as ×10ⁿ and the minus as − — never
// the value: 3/4 stays 3/4 (the read-back says 0.75), because rewriting it
// would overwrite the student's answer and any rounding the question asked
// for. The grader reads neither ×10⁸ nor a superscript, so `asciiNumber`
// turns them back into `e8` before anything leaves the field.

/** `3e8` / `1.5E-3`: an exponent only once it has a digit. */
const E_NOTATION = /(\d|\.)[eE]([+-]?\d+)/g;

/** ASCII → what the numeric field shows. */
export function prettyNumber(ascii: string): string {
  return ascii
    .replace(E_NOTATION, (_, before: string, exp: string) =>
      `${before}×10${[...exp].map(ch => SUPERSCRIPT[ch]).join("")}`)
    .replace(/-/g, "−");
}

/** What the numeric field shows → the ASCII the grader reads. */
export function asciiNumber(display: string): string {
  return display
    .replace(/×10([⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻]+)/g, (_, run: string) => `e${[...run].map(ch => FROM_SUPERSCRIPT[ch]).join("")}`)
    .replace(/[⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻]/g, ch => FROM_SUPERSCRIPT[ch])
    .replace(/−/g, "-");
}
