// File-size ratchet: no source file may pass the max-lines limit, and a file
// already over it may not grow.
//
// The real checks measure the frontend tree against max-lines-baseline.json
// (logic in scripts/max_lines_ratchet.mjs). The rest pins the ratchet on
// synthetic input, so a refactor cannot quietly turn it into a no-op.
//
// When the real check fails:
//   * a NEW file over the limit: split it. Do not add a baseline entry.
//   * a baselined file GREW: move the new code into its own module. Raising
//     the number in the JSON is a hand edit the reviewer has to accept.
//   * it went DOWN: nothing fails (slack only warns, so two PRs that each
//     shrink a file cannot turn main red between them), but lock the gain in:
//     `npm run max-lines:shrink`, and commit max-lines-baseline.json.
import path from "node:path";
import { pathToFileURL } from "node:url";
import { ESLint } from "eslint";
import { beforeAll, describe, expect, it } from "vitest";
import * as ratchet from "./max_lines_ratchet.mjs";

const ROOT = ratchet.FRONTEND;
// Measuring the whole tree parses every linted file (a few seconds locally);
// leave plenty of room for a loaded CI runner or a parallel suite.
const REAL_TREE_TIMEOUT_MS = 180_000;

type Entries = Record<string, number>;
type Options = { max: number; skipBlankLines?: boolean; skipComments?: boolean };

function slackMessage(slack: string[]): string {
  return [
    "max-lines baseline has slack:",
    ...slack,
    "Lock in the improvement: run `npm run max-lines:shrink` and commit max-lines-baseline.json.",
  ].join("\n  ");
}

describe("the frontend tree against max-lines-baseline.json", () => {
  let baseline: Entries;
  let current: Entries;
  let options: Options;

  beforeAll(async () => {
    baseline = ratchet.loadBaseline(ROOT)["max-lines"];
    options = await ratchet.configuredOptions(ROOT);
    current = await ratchet.measure(ROOT, Object.keys(baseline), options);
  }, REAL_TREE_TIMEOUT_MS);

  it("has no new file over the limit and no file above its ceiling", () => {
    const problems = ratchet.compare(baseline, current, options.max);
    expect(
      problems,
      `max-lines ratchet: split these files, do not add or raise baseline entries:\n  ${problems.join("\n  ")}`,
    ).toEqual([]);
  });

  it("only warns about slack", async ({ annotate }) => {
    // A file that got shorter should have its ceiling lowered, or the headroom
    // becomes room for the next regression; failing on it would let two
    // independently-green PRs leave main red.
    const slack = ratchet.shrinkable(baseline, current);
    if (slack.length === 0) return;
    console.warn(slackMessage(slack));
    await annotate(slackMessage(slack), "warning");
  });

  it("keeps the baseline file in its canonical shape", () => {
    expect(Object.keys(ratchet.loadBaseline(ROOT)).sort()).toEqual(["_comment", "max-lines"]);
    const keys = Object.keys(baseline);
    expect(keys).toEqual([...keys].sort());
    for (const [file, ceiling] of Object.entries(baseline)) {
      expect(Number.isInteger(ceiling) && ceiling > options.max, `${file}: ${ceiling}`).toBe(true);
    }
  });

  it("eslint.config.mjs gives each baselined file its own ceiling and nothing else", async () => {
    const config = (await import(pathToFileURL(path.join(ROOT, "eslint.config.mjs")).href)).default as Array<{
      name?: string;
      files?: string[];
      rules?: Record<string, unknown>;
    }>;
    const generated = config.filter((block) => block.name?.startsWith("max-lines/ratchet-baselined/"));
    expect(generated.map((block) => block.files)).toEqual(Object.keys(baseline).map((file) => [file]));

    // What ESLint resolves for a real path, so a key its glob matcher reads
    // differently (the `(shell)` route group) cannot silently lose its ceiling.
    const eslint = new ESLint({ cwd: ROOT });
    const setting = async (rel: string) =>
      (await eslint.calculateConfigForFile(path.join(ROOT, rel))).rules?.["max-lines"] as [number, Options?];
    for (const [file, ceiling] of Object.entries(baseline)) {
      expect(await setting(file), file).toEqual([2, { ...options, max: ceiling }]);
    }
    expect(await setting("src/app/page.tsx")).toEqual([2, options]);
    expect((await setting("src/lib/api.test.ts"))[0]).toBe(0);
  });

  it("uses the 800-line limit, not counting blank lines or comments", () => {
    expect(options).toEqual({ max: 800, skipBlankLines: true, skipComments: true });
  });

  it("leaves no rule at warn, so every rule can be baselined", async () => {
    // Bulk suppressions only hold errors and CI allows zero warnings, so a
    // warn-level rule (eslint-config-next adds them in minor releases) would
    // turn CI red on files already on main with no way to baseline it.
    const eslint = new ESLint({ cwd: ROOT });
    for (const rel of ["src/app/page.tsx", "src/lib/api.ts", "src/lib/api.test.ts", "eslint.config.mjs"]) {
      const rules = (await eslint.calculateConfigForFile(path.join(ROOT, rel))).rules ?? {};
      const warned = Object.entries(rules).filter(([, setting]) => (setting as [number])[0] === 1);
      expect(warned.map(([id]) => id), rel).toEqual([]);
    }
  });
});

// ── the ratchet's own rules, on synthetic input ───────────────────────────

describe("measuring", () => {
  const lines = (n: number) => Array.from({ length: n }, (_, i) => `export const v${i} = ${i};`).join("\n");
  const options: Options = { max: 5, skipBlankLines: true, skipComments: true };

  it("reports a file over the limit with its count, and nothing for one under it", async () => {
    const eslint = ratchet.measuringESLint(ROOT, options, ["src/lib/long.ts", "src/lib/short.ts"]);
    expect(await ratchet.measureText(eslint, lines(9), "src/lib/long.ts")).toEqual({ "src/lib/long.ts": 9 });
    expect(await ratchet.measureText(eslint, lines(5), "src/lib/short.ts")).toEqual({});
  });

  it("does not count blank lines or comments", async () => {
    const eslint = ratchet.measuringESLint(ROOT, options, ["src/lib/padded.ts"]);
    const code = `// a comment\n\n${lines(6)}\n\n/* another\n   comment */\n`;
    expect(await ratchet.measureText(eslint, code, "src/lib/padded.ts")).toEqual({ "src/lib/padded.ts": 6 });
  });

  it("cannot be switched off by an inline eslint-disable", async () => {
    const eslint = ratchet.measuringESLint(ROOT, options, ["src/lib/hidden.ts"]);
    const code = `/* eslint-disable max-lines */\n${lines(7)}`;
    expect(await ratchet.measureText(eslint, code, "src/lib/hidden.ts")).toEqual({ "src/lib/hidden.ts": 7 });
  });

  it("refuses a file it cannot parse instead of reading it as short", async () => {
    const eslint = ratchet.measuringESLint(ROOT, options, ["src/lib/broken.ts"]);
    await expect(ratchet.measureText(eslint, "export const = ;", "src/lib/broken.ts")).rejects.toThrow(
      /cannot measure max-lines: src\/lib\/broken\.ts/,
    );
  });
});

describe("ratchet rules", () => {
  it("fails growth and new files, and only those", () => {
    expect(ratchet.compare({ "a.ts": 900, "b.ts": 900 }, { "a.ts": 900, "b.ts": 901, "c.ts": 801 }, 800)).toEqual([
      "b.ts: 901 is over its baselined ceiling of 900",
      "c.ts: 801 is over the limit of 800 (new)",
    ]);
    expect(ratchet.compare({ "a.ts": 900, "b.ts": 900 }, { "a.ts": 850 }, 800)).toEqual([]);
  });

  it("shrink lowers and deletes, never adds or raises", () => {
    expect(ratchet.shrink({ "a.ts": 900, "b.ts": 900, "c.ts": 900 }, { "a.ts": 850, "c.ts": 950, "d.ts": 801 })).toEqual({
      "a.ts": 850,
      "c.ts": 900,
    });
  });
});
