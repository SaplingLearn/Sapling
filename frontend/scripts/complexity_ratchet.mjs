#!/usr/bin/env node
// Frontend complexity ratchet, architecture-hardening Phase 4 (Trov #118).
//
// Phase 4 is done when no function scores above complexity 25. ESLint's
// built-in `complexity` rule is on at 25 for every file in eslint.config.mjs,
// but the functions that already miss it cannot be split in this change, so
// this ratchet stops them getting worse in the meantime (the frontend twin of
// backend/scripts/code_size_ratchet.py):
//
//   complexity  every function ESLint's `complexity` rule scores above the
//               limit is listed in complexity-baseline.json with its current
//               score. A function that is not listed may not cross the limit;
//               a listed one may not score higher than its entry.
//
// ESLint can only switch a rule off per FILE, so eslint.config.mjs turns
// `complexity` off for each file that still holds a baselined function (that
// block is generated from complexity-baseline.json when the config loads) and
// the per-function ceilings live here. Delete a file's last entry and plain
// `eslint .` enforces the limit on it again, with no config edit.
//
// Keys are `<path relative to frontend/>::<qualified name>` (see qualifiedName
// below): `Dashboard>loadAll`, `QuizHome>useEffect()`, `Store.reduce`. They
// carry no line numbers, so an unrelated edit elsewhere in the file never
// re-keys an entry. Two offenders with the same name in one file are numbered
// in source order, `name`, `name#2`, … (counting offenders only, so adding a
// small function never shifts a key).
//
// What is measured: the files `eslint .` lints, restricted to git-tracked ones
// (an untracked scratch directory never counts), minus the landing-page
// animation engine (src/lib/landing/engine/**, exempt by decision, see
// eslint.config.mjs). Test files are measured too, as `eslint .` lints them.
// The run forces the rule on at the configured limit for every file and
// ignores inline `eslint-disable` comments, so neither the per-file offs in
// eslint.config.mjs nor a comment can hide a function from its ceiling.
//
// The baseline can only shrink. scripts/complexity_ratchet.test.ts enforces it
// in `npm test`: growth and new offenders fail; an entry that is now higher
// than it needs to be only warns (so two PRs that each shrink a function
// cannot leave main red between them) and asks for --shrink.
//
// Usage, from frontend/:
//
//   npm run complexity          # report; exit 1 on a violation
//   npm run complexity:shrink   # lower the baseline to today's numbers
//
// --shrink only ever lowers an entry or deletes one that is back under the
// limit; it never adds or raises one, and it exits 1 if a violation remains
// after the write. It cannot re-key either: a move or rename must move its
// baseline key by hand in the same change. Raising an entry is a hand edit to
// the JSON, which shows up in review: split the function instead.

import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { ESLint } from "eslint";
import { builtinRules } from "eslint/use-at-your-own-risk";

export const FRONTEND = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const BASELINE_FILE = "complexity-baseline.json";
// Exempt from the limit by decision (Trov #118 phase 4): eslint.config.mjs
// switches `complexity` off for the same glob.
export const EXEMPT_PREFIXES = ["src/lib/landing/engine/"];
export const EXEMPT_GLOB = "src/lib/landing/engine/**";

const RULE_ID = "complexity-ratchet/keyed";
const BUILTIN = builtinRules.get("complexity");

// ── naming ────────────────────────────────────────────────────────────────

const FUNCTION_TYPES = new Set([
  "FunctionDeclaration",
  "FunctionExpression",
  "ArrowFunctionExpression",
]);

// Wrappers that do not change what an expression "is" for naming purposes.
const TRANSPARENT_PARENTS = new Set([
  "AwaitExpression",
  "ChainExpression",
  "ConditionalExpression",
  "LogicalExpression",
  "ParenthesizedExpression",
  "TSAsExpression",
  "TSNonNullExpression",
  "TSSatisfiesExpression",
  "TSTypeAssertion",
]);

function isFunction(node) {
  return FUNCTION_TYPES.has(node.type);
}

/** The source name of a property/method key: `foo`, `"foo"` → foo, `[x]`. */
function keyName(key, computed) {
  if (!computed && key.type === "Identifier") return key.name;
  if (key.type === "PrivateIdentifier") return `#${key.name}`;
  if (key.type === "Literal") return String(key.value);
  if (key.type === "Identifier") return `[${key.name}]`;
  return "[computed]";
}

/** A name for an assignment target: `a` → a, `this.onDone` / `x.y.onDone` → onDone. */
function targetName(node) {
  if (node.type === "Identifier") return node.name;
  if (node.type === "MemberExpression") return keyName(node.property, node.computed);
  return null;
}

/**
 * How a call reads in a key: `useEffect(…)` → useEffect(), `items.map(…)` →
 * items.map() (the receiver only when it is a plain name: `fetch(u).then(…)`
 * → then()), and a leading string argument is kept so sibling callbacks
 * differ: `sim.force("follow", …)` → sim.force('follow').
 */
function callName(call) {
  const { callee } = call;
  let name = "(call)";
  if (callee.type === "Identifier") name = callee.name;
  else if (callee.type === "MemberExpression") {
    const prop = keyName(callee.property, callee.computed);
    name = callee.object.type === "Identifier" ? `${callee.object.name}.${prop}` : prop;
  }
  const first = call.arguments[0];
  const tag = first?.type === "Literal" && typeof first.value === "string" ? `'${first.value}'` : "";
  return `${name}(${tag})`;
}

function className(cls) {
  return cls.id ? cls.id.name : contextName(cls) ?? "(class)";
}

function memberName(member) {
  const kind = member.kind === "get" || member.kind === "set" ? `${member.kind} ` : "";
  return `${className(member.parent.parent)}.${kind}${keyName(member.key, member.computed)}`;
}

function propertyName(property) {
  const kind = property.kind === "get" || property.kind === "set" ? `${property.kind} ` : "";
  const key = `${kind}${keyName(property.key, property.computed)}`;
  const owner = contextName(property.parent);
  return owner ? `${owner}.${key}` : key;
}

function jsxName(container) {
  const attr = container.parent;
  if (attr?.type === "JSXAttribute") {
    return attr.name.type === "JSXNamespacedName"
      ? `${attr.name.namespace.name}:${attr.name.name.name}`
      : attr.name.name;
  }
  return "(jsx child)";
}

/**
 * The name an anonymous expression takes from where it sits, or null.
 *
 * `const f = …` / `x.f = …` / `f = …` (default) → f; a class member → Class.f;
 * an object property → obj.f (obj only when the object itself is named);
 * a call argument → the name the call itself is bound to when it has one
 * (`const save = useCallback(() => …)` → save), else the call
 * (`useEffect(() => …)` → useEffect(), `items.map(…)` → items.map(), see
 * callName); a JSX attribute → its name (`onClick`); a bare JSX child →
 * (jsx child); a returned function (`return () => …`, `() => () => …`) →
 * (returned); `export default` → default.
 *
 * `bindingOnly` limits the answer to a binding (variable, assignment target,
 * property, class member, default export).
 */
export function contextName(node, bindingOnly = false) {
  let child = node;
  let parent = node.parent;
  while (parent && TRANSPARENT_PARENTS.has(parent.type)) {
    child = parent;
    parent = parent.parent;
  }
  if (!parent) return null;
  const namer = BINDING_NAMERS[parent.type] ?? (bindingOnly ? undefined : POSITION_NAMERS[parent.type]);
  return namer ? namer(parent, child) : null;
}

const assigned = (parent, child) => (parent.right === child ? targetName(parent.left) : null);
const member = (parent, child) => (parent.value === child ? memberName(parent) : null);
const argument = (parent, child) =>
  parent.callee === child ? null : (contextName(parent, true) ?? callName(parent));

// Each takes (parent, child) and names `child` by its place in `parent`.
const BINDING_NAMERS = {
  VariableDeclarator: (parent, child) => (parent.init === child ? targetName(parent.id) : null),
  AssignmentExpression: assigned,
  AssignmentPattern: assigned,
  Property: (parent, child) => (parent.value === child ? propertyName(parent) : null),
  MethodDefinition: member,
  PropertyDefinition: member,
  ExportDefaultDeclaration: () => "default",
};
const POSITION_NAMERS = {
  CallExpression: argument,
  NewExpression: argument,
  JSXExpressionContainer: (parent) => jsxName(parent),
  ReturnStatement: () => "(returned)",
  ArrowFunctionExpression: (parent, child) => (parent.body === child ? "(returned)" : null),
};

/** A function's own name: its id, else the name its context gives it. */
export function ownName(fn) {
  if (fn.id) return fn.id.name;
  return contextName(fn) ?? "(anonymous)";
}

/**
 * The qualified name the baseline keys a reported node by: every enclosing
 * function's own name, outermost first, joined with `>`
 * (`Dashboard>useEffect()>load`). Class field initializers and static blocks
 * (which ESLint also scores) get `Class.field (initializer)` /
 * `Class.static{}`.
 */
export function qualifiedName(node, { initializer = false } = {}) {
  let name;
  if (node.type === "StaticBlock") name = `${className(node.parent.parent)}.static{}`;
  else if (initializer) name = `${memberName(node.parent)} (initializer)`;
  else name = ownName(node);
  for (let cur = node.parent; cur; cur = cur.parent) {
    if (isFunction(cur)) name = `${ownName(cur)}>${name}`;
  }
  return name;
}

/**
 * ESLint's own `complexity` rule, re-reporting each finding under its
 * qualified name. Scores are the built-in rule's (same code, same options);
 * measureComplexity additionally checks every built-in report has a twin.
 */
export const keyedComplexityRule = {
  meta: { ...BUILTIN.meta, messages: { keyed: "{{complexity}}\t{{key}}" } },
  create(context) {
    const proxy = Object.create(context, {
      report: {
        value(descriptor) {
          const initializer = /^Class field initializer/.test(descriptor.data.name);
          context.report({
            node: descriptor.node,
            loc: descriptor.loc,
            messageId: "keyed",
            data: {
              complexity: descriptor.data.complexity,
              key: qualifiedName(descriptor.node, { initializer }),
            },
          });
        },
      },
    });
    return BUILTIN.create(proxy);
  },
};

// ── measuring ─────────────────────────────────────────────────────────────

/** An ESLint instance that scores every function against `limit`, whatever the config says. */
export function measuringESLint(root, limit) {
  return new ESLint({
    cwd: root,
    allowInlineConfig: false,
    warnIgnored: false,
    cache: false,
    ruleFilter: ({ ruleId }) => ruleId === "complexity" || ruleId === RULE_ID,
    overrideConfig: [
      { ignores: [EXEMPT_GLOB] },
      {
        plugins: { "complexity-ratchet": { rules: { keyed: keyedComplexityRule } } },
        rules: { complexity: ["error", limit], [RULE_ID]: ["error", limit] },
      },
    ],
  });
}

/** The `complexity` limit eslint.config.mjs sets for an ordinary file. */
export async function configuredLimit(root = FRONTEND) {
  const config = await new ESLint({ cwd: root }).calculateConfigForFile(
    path.join(root, "eslint.config.mjs"),
  );
  const setting = config.rules?.complexity;
  const [severity, option] = Array.isArray(setting) ? setting : [setting];
  const limit = typeof option === "object" ? (option.max ?? option.maximum) : option;
  if (severity !== 2 || !Number.isInteger(limit)) {
    throw new Error(`eslint.config.mjs must set complexity to ["error", <n>], got ${JSON.stringify(setting)}`);
  }
  return limit;
}

/** Git-tracked files under `root`, relative to it (posix), that exist on disk. */
export function trackedFiles(root = FRONTEND) {
  const out = execFileSync("git", ["ls-files", "-z", "--", "."], { cwd: root, encoding: "utf8" });
  return out
    .split("\0")
    .filter(Boolean)
    .filter((rel) => !EXEMPT_PREFIXES.some((p) => rel.startsWith(p)))
    .filter((rel) => fs.existsSync(path.join(root, rel)));
}

function parseResult(result, root) {
  const rel = path.relative(root, result.filePath).split(path.sep).join("/");
  const fatal = result.messages.find((m) => m.fatal || !m.ruleId);
  if (fatal) throw new Error(`cannot measure complexity: ${rel}:${fatal.line}: ${fatal.message}`);
  const builtin = new Set();
  const keyed = [];
  for (const m of result.messages) {
    if (m.ruleId === "complexity") {
      const score = /has a complexity of (\d+)\./.exec(m.message)?.[1];
      builtin.add(`${m.line}:${m.column}:${score}`);
    } else if (m.ruleId === RULE_ID) {
      const tab = m.message.indexOf("\t");
      const score = Number(m.message.slice(0, tab));
      keyed.push({ line: m.line, column: m.column, score, name: m.message.slice(tab + 1) });
    }
  }
  const twins = new Set(keyed.map((k) => `${k.line}:${k.column}:${k.score}`));
  if (twins.size !== builtin.size || [...builtin].some((b) => !twins.has(b))) {
    throw new Error(`${rel}: keyed complexity disagrees with ESLint's complexity rule`);
  }
  return { rel, keyed };
}

/** Number repeated names in one file `name`, `name#2`, … in source order. */
export function keyFindings(rel, findings) {
  const sorted = [...findings].sort((a, b) => a.line - b.line || a.column - b.column);
  /** @type {Record<string, number>} */
  const result = {};
  for (const f of sorted) {
    const base = `${rel}::${f.name}`;
    let key = base;
    for (let n = 2; key in result; n++) key = `${base}#${n}`;
    result[key] = f.score;
  }
  return result;
}

/** Score findings in `results` from a measuringESLint run, keyed for the baseline. */
export function collect(results, root) {
  /** @type {Record<string, number>} */
  const current = {};
  for (const result of results) {
    const { rel, keyed } = parseResult(result, root);
    Object.assign(current, keyFindings(rel, keyed));
  }
  return current;
}

/**
 * Every function scoring above `limit`, keyed `<file>::<qualified name>`.
 *
 * Lints exactly the git-tracked files `eslint .` would lint (minus the
 * exempt engine). A file that fails to parse throws instead of silently
 * dropping its functions (which would read as "back under the limit" and let
 * --shrink delete entries).
 */
export async function measureComplexity(root = FRONTEND, limit) {
  const max = limit ?? (await configuredLimit(root));
  const eslint = measuringESLint(root, max);
  const files = [];
  for (const rel of trackedFiles(root)) {
    if (!(await eslint.isPathIgnored(path.join(root, rel)))) files.push(rel);
  }
  const results = await eslint.lintFiles(files);
  return collect(results, root);
}

/** Keys and scores for one snippet (tests): every function above `limit`. */
export async function measureText(eslint, code, filePath, root = FRONTEND) {
  const results = await eslint.lintText(code, { filePath: path.join(root, filePath) });
  return collect(results, root);
}

// ── ratchet rules ─────────────────────────────────────────────────────────

/** Violations: a new entry over `limit`, or a baselined one above its ceiling. */
export function compare(baseline, current, limit) {
  const problems = [];
  for (const key of Object.keys(current).sort()) {
    const value = current[key];
    const ceiling = baseline[key];
    if (ceiling === undefined) problems.push(`${key}: ${value} is over the limit of ${limit} (new)`);
    else if (value > ceiling) problems.push(`${key}: ${value} is over its baselined ceiling of ${ceiling}`);
  }
  return problems;
}

/** Baseline entries that are higher than they need to be. */
export function shrinkable(baseline, current) {
  const out = [];
  for (const key of Object.keys(baseline).sort()) {
    const value = current[key];
    if (value === undefined) out.push(`${key}: back under the limit, delete its entry`);
    else if (value < baseline[key]) out.push(`${key}: now ${value}, baselined at ${baseline[key]}, lower it`);
  }
  return out;
}

/** Lower each entry to today's value and drop the ones that are gone. Never adds or raises. */
export function shrink(baseline, current) {
  /** @type {Record<string, number>} */
  const out = {};
  for (const [key, ceiling] of Object.entries(baseline)) {
    if (key in current) out[key] = Math.min(ceiling, current[key]);
  }
  return out;
}

/** The files that still hold a baselined function (eslint.config.mjs switches `complexity` off for them). */
export function baselinedFiles(entries) {
  return [...new Set(Object.keys(entries).map((key) => key.split("::", 1)[0]))].sort();
}

export function loadBaseline(root = FRONTEND) {
  return JSON.parse(fs.readFileSync(path.join(root, BASELINE_FILE), "utf8"));
}

export function writeBaseline(data, root = FRONTEND) {
  const out = {};
  for (const [k, v] of Object.entries(data)) {
    out[k] = v && typeof v === "object"
      ? Object.fromEntries(Object.keys(v).sort().map((key) => [key, v[key]]))
      : v;
  }
  fs.writeFileSync(path.join(root, BASELINE_FILE), `${JSON.stringify(out, null, 2)}\n`);
}

// ── CLI ───────────────────────────────────────────────────────────────────

export async function main(argv = process.argv.slice(2), root = FRONTEND) {
  const shrinkMode = argv.includes("--shrink");
  const baseline = loadBaseline(root);
  const limit = await configuredLimit(root);
  const current = await measureComplexity(root, limit);

  if (shrinkMode) {
    baseline.complexity = shrink(baseline.complexity, current);
    writeBaseline(baseline, root);
    console.log(`wrote ${path.join(root, BASELINE_FILE)}`);
    // --shrink never adds or raises an entry, so growth and new offenders
    // survive it; say so instead of implying the tree is now clean.
    const remaining = compare(baseline.complexity, current, limit);
    for (const line of remaining) console.log(`  FAIL  ${line}`);
    if (remaining.length) console.log("--shrink cannot fix these: split the function (docs/design/domain-modules.md)");
    return remaining.length ? 1 : 0;
  }

  const problems = compare(baseline.complexity, current, limit);
  console.log(`complexity: ${Object.keys(current).length} over the limit of ${limit}`);
  for (const key of Object.keys(current).sort()) console.log(`  ${String(current[key]).padStart(4)}  ${key}`);
  for (const line of problems) console.log(`  FAIL  ${line}`);
  for (const line of shrinkable(baseline.complexity, current)) console.log(`  SHRINK  ${line}`);
  return problems.length ? 1 : 0;
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  process.exitCode = await main();
}
