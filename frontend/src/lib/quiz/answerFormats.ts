import type { QuestionType } from "./types";

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

/** Letter runs the algebra grammar refuses rather than read as products. */
const FUNCTION_NAME = /sin|cos|tan|sec|csc|cot|log|ln|exp|sqrt|abs/i;

function validSymbolicFormat(raw: string): boolean {
  const text = raw.normalize("NFKC").replace(/−/g, "-").replace(/×/g, "*").replace(/÷/g, "/");
  if (text.length > 256 || FUNCTION_NAME.test(text)) return false;

  const tokens = text.match(/\d{1,20}(?:\.\d{0,20})?|\.\d{1,20}|[a-zA-Z]|[()+*/^-]/g) ?? [];
  if (tokens.length > 96 || tokens.join("") !== text.replace(/\s/g, "")) return false;

  let depth = 0;
  let needsOperand = true;
  let canRaise = false;
  for (let i = 0; i < tokens.length; i++) {
    const token = tokens[i];
    if (token === "(") {
      depth++;
      needsOperand = true;
    } else if (token === ")") {
      if (needsOperand || depth === 0) return false;
      depth--;
      canRaise = true;
    } else if (token === "^") {
      if (needsOperand || !canRaise) return false;
      if (tokens[i + 1] === "+" || tokens[i + 1] === "-") i++;
      if (!/^[0-8]$/.test(tokens[++i] ?? "")) return false;
      canRaise = false;
    } else if (token === "+" || token === "-" || token === "*" || token === "/") {
      if (needsOperand && (token === "*" || token === "/")) return false;
      needsOperand = true;
    } else {
      needsOperand = false;
      canRaise = true;
    }
  }
  return !needsOperand && depth === 0;
}

export function isWrittenAnswerFormatValid(type: QuestionType | undefined, value: string, numericUnit?: string): boolean {
  if (!value.trim()) return false;
  if (type === "numeric") {
    if (!numericUnit) return numericValue(value) !== null;
    const quantity = /^([\s\S]+) ([A-Za-zμΩ°][A-Za-zμΩ°0-9*/^·.−+-]{0,31})$/.exec(value.normalize("NFKC").trim());
    return quantity !== null && numericValue(quantity[1]) !== null;
  }
  return type !== "symbolic" || validSymbolicFormat(value);
}
