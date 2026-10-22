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
  const pretty = (s: string) => s.replace(/\*/g, "·").replace(/-/g, "−");
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
