#!/usr/bin/env node
// Frontend file-size ratchet: no source file may pass the `max-lines` limit,
// and a file that is already over it may not grow.
//
// ESLint's `max-lines` rule is on for every file in eslint.config.mjs (800
// lines, blank lines and comments not counted, tests exempt). The files that
// already miss it cannot be split in one change, and a bulk suppression
// (eslint-suppressions.json) cannot hold them: the rule reports ONE problem
// per file however long the file is, so a suppressed file could grow by a
// thousand lines and still pass. So each one is listed in
// max-lines-baseline.json with its current count instead:
//
//   max-lines  a file that is not listed may not cross the limit; a listed
//              one may not have more lines than its entry.
//
// eslint.config.mjs turns each entry into that file's own `max-lines` ceiling
// when the config loads, so plain `eslint .` (and the editor) reports growth
// like any other lint error. This script is the rest of the ratchet: it
// measures every file against the LIMIT, ignoring the per-file ceilings and
// any inline `eslint-disable`, so neither can hide a file, and it lowers the
// baseline when a file shrinks.
//
// What is measured: the git-tracked files `eslint .` lints, counted the way
// the configured rule counts them (same options, read from the config).
//
// The baseline can only shrink. scripts/max_lines_ratchet.test.ts enforces it
// in `npm test`: growth and new offenders fail; an entry that is now higher
// than it needs to be only warns (so two PRs that each shrink a file cannot
// leave main red between them) and asks for --shrink.
//
// Usage, from frontend/:
//
//   npm run max-lines          # report; exit 1 on a violation
//   npm run max-lines:shrink   # lower the baseline to today's numbers
//
// --shrink only ever lowers an entry or deletes one that is back under the
// limit; it never adds or raises one. A renamed file must move its key by
// hand in the same change. Raising an entry is a hand edit to the JSON, which
// shows up in review: split the file instead.

import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { ESLint } from "eslint";
import { compare, shrink, shrinkable } from "./complexity_ratchet.mjs";

export { compare, shrink, shrinkable };

export const FRONTEND = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const BASELINE_FILE = "max-lines-baseline.json";
const RULE = "max-lines";
const MESSAGE = /^File has too many lines \((\d+)\)\. Maximum allowed is \d+\.$/;

export function loadBaseline(root = FRONTEND) {
  return JSON.parse(fs.readFileSync(path.join(root, BASELINE_FILE), "utf8"));
}

export function writeBaseline(data, root = FRONTEND) {
  const entries = data[RULE];
  const sorted = Object.fromEntries(Object.keys(entries).sort().map((key) => [key, entries[key]]));
  fs.writeFileSync(path.join(root, BASELINE_FILE), `${JSON.stringify({ ...data, [RULE]: sorted }, null, 2)}\n`);
}

/** The `max-lines` options eslint.config.mjs sets for an ordinary file. */
export async function configuredOptions(root = FRONTEND) {
  const config = await new ESLint({ cwd: root }).calculateConfigForFile(
    path.join(root, "eslint.config.mjs"),
  );
  const [severity, options] = config.rules?.[RULE] ?? [];
  if (severity !== 2 || !Number.isInteger(options?.max)) {
    throw new Error(`eslint.config.mjs must set max-lines to ["error", { max: <n>, … }], got ${JSON.stringify(config.rules?.[RULE])}`);
  }
  return options;
}

/** Git-tracked files under `root`, relative to it (posix), that exist on disk. */
export function trackedFiles(root = FRONTEND) {
  const out = execFileSync("git", ["ls-files", "-z", "--", "."], { cwd: root, encoding: "utf8" });
  return out.split("\0").filter((rel) => rel && fs.existsSync(path.join(root, rel)));
}

/**
 * An ESLint instance that holds `baselined` files to the plain limit instead
 * of their own ceiling, and ignores inline config. Every other file keeps
 * what eslint.config.mjs gives it (the limit, or off for tests).
 */
export function measuringESLint(root, options, baselined) {
  return new ESLint({
    cwd: root,
    allowInlineConfig: false,
    warnIgnored: false,
    cache: false,
    ruleFilter: ({ ruleId }) => ruleId === RULE,
    overrideConfig: baselined.length ? [{ files: baselined, rules: { [RULE]: ["error", options] } }] : [],
  });
}

/** Line counts from a measuringESLint run, keyed by path relative to `root`. */
export function collect(results, root) {
  /** @type {Record<string, number>} */
  const current = {};
  for (const result of results) {
    const rel = path.relative(root, result.filePath).split(path.sep).join("/");
    for (const m of result.messages) {
      const count = m.ruleId === RULE ? MESSAGE.exec(m.message)?.[1] : undefined;
      // A file that fails to parse must not read as "back under the limit".
      if (count === undefined) throw new Error(`cannot measure max-lines: ${rel}:${m.line}: ${m.message}`);
      current[rel] = Number(count);
    }
  }
  return current;
}

/**
 * Every linted, git-tracked file over the limit, with its line count.
 *
 * Only files with more RAW lines than the limit are parsed: the rule counts a
 * subset of a file's lines (blank lines and comments may be skipped), so a
 * file that short cannot be over it. That keeps this to a handful of files
 * instead of a second full-tree lint inside `npm test`.
 */
export async function measure(root = FRONTEND, baselined = [], options) {
  const opts = options ?? (await configuredOptions(root));
  const eslint = measuringESLint(root, opts, baselined);
  const files = [];
  for (const rel of trackedFiles(root)) {
    const full = path.join(root, rel);
    if (fs.readFileSync(full, "utf8").split("\n").length <= opts.max) continue;
    if (!(await eslint.isPathIgnored(full))) files.push(rel);
  }
  return files.length ? collect(await eslint.lintFiles(files), root) : {};
}

/** Keys and counts for one snippet (tests). */
export async function measureText(eslint, code, filePath, root = FRONTEND) {
  return collect(await eslint.lintText(code, { filePath: path.join(root, filePath) }), root);
}

export async function main(argv = process.argv.slice(2), root = FRONTEND) {
  const baseline = loadBaseline(root);
  const options = await configuredOptions(root);
  const current = await measure(root, Object.keys(baseline[RULE]), options);

  if (argv.includes("--shrink")) {
    baseline[RULE] = shrink(baseline[RULE], current);
    writeBaseline(baseline, root);
    console.log(`wrote ${path.join(root, BASELINE_FILE)}`);
    // --shrink never adds or raises an entry, so growth and new offenders
    // survive it; say so instead of implying the tree is now clean.
    const remaining = compare(baseline[RULE], current, options.max);
    for (const line of remaining) console.log(`  FAIL  ${line}`);
    if (remaining.length) console.log("--shrink cannot fix these: split the file");
    return remaining.length ? 1 : 0;
  }

  const problems = compare(baseline[RULE], current, options.max);
  console.log(`max-lines: ${Object.keys(current).length} files over the limit of ${options.max}`);
  for (const key of Object.keys(current).sort()) console.log(`  ${String(current[key]).padStart(5)}  ${key}`);
  for (const line of problems) console.log(`  FAIL  ${line}`);
  for (const line of shrinkable(baseline[RULE], current)) console.log(`  SHRINK  ${line}`);
  return problems.length ? 1 : 0;
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  process.exitCode = await main();
}
