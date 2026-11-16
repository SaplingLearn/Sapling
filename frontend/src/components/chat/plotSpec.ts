/**
 * The ```plot / ```function-plot fence, parsed and validated.
 *
 * A fence's text is written by a model that read the student's documents, so
 * a document can put words into it. function-plot hands each expression to
 * math-codegen, which compiles it with `new Function`, and math-codegen emits
 * some parts of its input as raw JavaScript (a string inside an array literal
 * is one: `x + ["(globalThis.hit=1, 0)"]` runs). So no fence text reaches
 * function-plot as the model wrote it:
 *
 *   - an expression is tokenized against a strict math allowlist (numbers,
 *     the variables below, `+ - * / ^ ( ) ,`, the functions and constants
 *     below) and REBUILT from its tokens, so what function-plot compiles is
 *     text this module produced, never the fence's own characters;
 *   - every other field is checked against a fixed shape (a colour is a hex
 *     value or a named colour on the list, a graph type is one of three, a
 *     domain is two finite numbers, a title is short plain text).
 *
 * Anything that fails is not plotted: the caller shows the fence as code.
 * Pure; pinned by plotSpec.test.ts.
 */

export const MAX_EXPRESSION_LENGTH = 200;
export const MAX_TITLE_LENGTH = 120;
export const MAX_SERIES = 8;
export const MAX_SPEC_LENGTH = 2000;

const VARIABLES = new Set(["x", "y", "t", "r", "theta"]);

/** Fence spelling → function-plot's own name for the constant. */
const CONSTANTS = new Map([
  ["pi", "PI"],
  ["PI", "PI"],
  ["e", "E"],
  ["E", "E"],
]);

/**
 * Fence spelling → the name function-plot evaluates. `interval` is false for
 * the names its default (interval-arithmetic) sampler lacks; a series that
 * uses one is sampled point by point instead (see `samplerFor`).
 */
const FUNCTIONS = new Map<string, { name: string; interval: boolean }>([
  ...["sin", "cos", "tan", "asin", "acos", "atan", "sinh", "cosh", "tanh"].map(
    (n) => [n, { name: n, interval: true }] as const,
  ),
  ...["sqrt", "nthRoot", "log", "log10", "log2", "exp", "abs", "min", "max", "pow"].map(
    (n) => [n, { name: n, interval: true }] as const,
  ),
  // Natural log: `log` is natural in both samplers, `ln` exists in only one.
  ["ln", { name: "log", interval: true }],
  ...["cbrt", "floor", "ceil", "round", "sign"].map((n) => [n, { name: n, interval: false }] as const),
]);

const OPERATORS = new Set(["+", "-", "*", "/", "^", "(", ")", ","]);

export const GRAPH_TYPES = ["interval", "polyline", "scatter"] as const;
export type GraphType = (typeof GRAPH_TYPES)[number];

const NAMED_COLORS = new Set([
  "black", "white", "gray", "grey", "silver", "red", "maroon", "orange", "gold",
  "yellow", "olive", "lime", "green", "teal", "cyan", "aqua", "blue", "navy",
  "indigo", "purple", "violet", "magenta", "fuchsia", "pink", "brown", "crimson",
  "coral", "salmon", "tomato", "orchid", "plum", "steelblue", "royalblue",
  "darkblue", "darkgreen", "darkred", "darkorange", "seagreen", "forestgreen",
  "slategray", "slateblue", "turquoise", "chocolate", "tan",
]);
const HEX_COLOR = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/;

type Token = { kind: "num" | "var" | "const" | "fn" | "op"; text: string; interval: boolean };

export interface PlotSeries {
  fn: string;
  color?: string;
  graphType?: GraphType;
  sampler?: "builtIn";
  closed?: boolean;
}

export interface PlotSpec {
  data: PlotSeries[];
  title?: string;
  xAxis?: { domain: [number, number] };
  yAxis?: { domain: [number, number] };
  grid: boolean;
}

export type PlotParse = { ok: true; spec: PlotSpec } | { ok: false; reason: string };

class Rejected extends Error {}

function reject(reason: string): never {
  throw new Rejected(reason);
}

const NUMBER = /^(?:\d+(?:\.\d*)?|\.\d+)/;
const WORD = /^[A-Za-z][A-Za-z0-9]*/;

function wordToken(word: string): Token {
  if (VARIABLES.has(word)) return { kind: "var", text: word, interval: true };
  const constant = CONSTANTS.get(word);
  if (constant) return { kind: "const", text: constant, interval: true };
  const fn = FUNCTIONS.get(word);
  if (fn) return { kind: "fn", text: fn.name, interval: fn.interval };
  return reject(`unknown name "${word}"`);
}

/** Splits an expression into allowlisted tokens, or rejects it. */
export function tokenize(src: string): Token[] {
  if (src.length > MAX_EXPRESSION_LENGTH) reject("expression too long");
  const tokens: Token[] = [];
  let i = 0;
  while (i < src.length) {
    const c = src[i];
    if (c === " " || c === "\t") {
      i += 1;
      continue;
    }
    const rest = src.slice(i);
    const num = NUMBER.exec(rest);
    const word = num ? null : WORD.exec(rest);
    if (num) tokens.push({ kind: "num", text: num[0], interval: true });
    else if (word) tokens.push(wordToken(word[0]));
    else if (OPERATORS.has(c)) tokens.push({ kind: "op", text: c, interval: true });
    else reject(`character "${c}" is not allowed`);
    i += num ? num[0].length : word ? word[0].length : 1;
  }
  if (tokens.length === 0) reject("empty expression");
  return tokens;
}

/** Shape checks the tokenizer cannot make on its own. */
function checkStructure(tokens: Token[]): void {
  let depth = 0;
  tokens.forEach((tok, i) => {
    const next = tokens[i + 1];
    const opensCall = next?.text === "(" && next.kind === "op";
    if (tok.kind === "fn" && !opensCall) reject(`"${tok.text}" must be called`);
    if ((tok.kind === "var" || tok.kind === "const") && opensCall) reject(`"${tok.text}" is not a function`);
    if (tok.kind === "num" && next?.kind === "num") reject("two numbers in a row");
    if (tok.text === "(") depth += 1;
    if (tok.text === ")") depth -= 1;
    if (depth < 0) reject("unbalanced parentheses");
  });
  if (depth !== 0) reject("unbalanced parentheses");
}

export interface SafeExpression {
  /** The expression rebuilt from its tokens: the only text function-plot sees. */
  fn: string;
  /** True when a function the interval sampler lacks is used. */
  needsBuiltIn: boolean;
}

/** Validates one expression and rebuilds it from its tokens. */
export function safeExpression(src: string): SafeExpression {
  const tokens = tokenize(src.trim());
  checkStructure(tokens);
  return {
    fn: tokens.map((t) => t.text).join(" "),
    needsBuiltIn: tokens.some((t) => !t.interval),
  };
}

export function isSafeColor(value: string): boolean {
  return HEX_COLOR.test(value) || NAMED_COLORS.has(value.toLowerCase());
}

function parseGraphType(value: string): GraphType {
  const g = GRAPH_TYPES.find((t) => t === value.toLowerCase());
  return g ?? reject(`graph type "${value}" is not allowed`);
}

function parseBool(value: string): boolean {
  const v = value.toLowerCase();
  if (v === "true") return true;
  if (v === "false") return false;
  return reject(`"${value}" is not true or false`);
}

// `[-5, 5]`, `-5, 5`, `-5 to 5` or `-5 5`.
const DOMAIN = /^[[(]?\s*(-?\d+(?:\.\d+)?)\s*(?:,|\s|to)\s*(-?\d+(?:\.\d+)?)\s*[\])]?$/;

export function parseDomain(value: string): [number, number] {
  const m = DOMAIN.exec(value.trim());
  if (!m) return reject(`domain "${value}" is not two numbers`);
  const lo = Number(m[1]);
  const hi = Number(m[2]);
  if (!Number.isFinite(lo) || !Number.isFinite(hi) || !(lo < hi)) reject("domain must be low, high");
  return [lo, hi];
}

// d3 draws the title with .text(), so this is a tidiness bound, not an
// escaping one: short, no control characters, no markup-looking characters.
function isPlainText(value: string): boolean {
  for (const ch of value) {
    const code = ch.codePointAt(0) ?? 0;
    if (code < 0x20 || code === 0x7f || "<>`".includes(ch)) return false;
  }
  return true;
}

function parseTitle(value: string): string {
  if (value.length > MAX_TITLE_LENGTH || !isPlainText(value)) reject("title is not short plain text");
  return value;
}

function applySeriesOption(series: PlotSeries, part: string): void {
  const m = /^([A-Za-z]+)\s*=\s*(.+)$/.exec(part);
  if (!m) return reject(`option "${part}" is not key=value`);
  const key = m[1].toLowerCase();
  const value = m[2].trim();
  if (key === "color") {
    if (!isSafeColor(value)) reject(`colour "${value}" is not allowed`);
    series.color = value;
  } else if (key === "graphtype" || key === "type") {
    series.graphType = parseGraphType(value);
  } else if (key === "closed") {
    series.closed = parseBool(value);
  } else {
    reject(`option "${key}" is not allowed`);
  }
}

/** `plot: <expr>; color=…; graphType=…; closed=…` → one series. */
function parseSeries(value: string): PlotSeries {
  const [expr, ...options] = value.split(/\s*;\s*/);
  const safe = safeExpression(expr);
  const series: PlotSeries = { fn: safe.fn };
  options.filter(Boolean).forEach((p) => applySeriesOption(series, p));
  if (safe.needsBuiltIn) {
    // The interval sampler cannot evaluate this function; sample points and
    // draw them as a line (the interval graph type needs interval samples).
    series.sampler = "builtIn";
    if (!series.graphType || series.graphType === "interval") series.graphType = "polyline";
  }
  return series;
}

function applyLine(out: PlotSpec, key: string, value: string): void {
  if (key === "plot" || key === "fn") {
    if (out.data.length >= MAX_SERIES) reject("too many plot lines");
    out.data.push(parseSeries(value));
  } else if (key === "xdomain" || key === "x") {
    out.xAxis = { domain: parseDomain(value) };
  } else if (key === "ydomain" || key === "y") {
    out.yAxis = { domain: parseDomain(value) };
  } else if (key === "title") {
    out.title = parseTitle(value);
  } else if (key === "grid") {
    out.grid = parseBool(value);
  }
  // Any other key is ignored: nothing outside the fields above is forwarded.
}

function parseOrThrow(input: string): PlotSpec {
  if (input.length > MAX_SPEC_LENGTH) reject("spec too long");
  const out: PlotSpec = { data: [], grid: true };
  const lines = input
    .split("\n")
    .map((l) => l.trim())
    .filter((l) => l && !l.startsWith("#"));
  for (const line of lines) {
    const m = /^([A-Za-z][\w-]*)\s*:\s*(.+)$/.exec(line);
    if (m) applyLine(out, m[1].toLowerCase(), m[2].trim());
  }
  if (out.data.length === 0) reject("no `plot:` line");
  return out;
}

/** Parses a fence; `ok: false` means draw it as code, never plot it. */
export function parsePlotSpec(input: string): PlotParse {
  try {
    return { ok: true, spec: parseOrThrow(input) };
  } catch (e) {
    if (e instanceof Rejected) return { ok: false, reason: e.message };
    throw e;
  }
}
