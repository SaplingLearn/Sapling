// Phase 4 (Trov #118) complexity ratchet: no function may get more complex.
//
// The real checks measure the frontend tree against complexity-baseline.json
// (logic in scripts/complexity_ratchet.mjs). The rest pins the ratchet's own
// rules and its function keys on synthetic input, so a refactor of the script
// cannot quietly turn it into a no-op.
//
// When the real check fails:
//   * a NEW offender: split the function (docs/design/domain-modules.md,
//     "Frontend"). Do not add a baseline entry.
//   * a baselined entry GREW: shrink it back under its ceiling. If that is
//     genuinely impossible in this change, raising the number in the JSON is a
//     hand edit the reviewer has to accept.
//   * it went DOWN: nothing fails (slack only warns, so two PRs that each
//     shrink a function cannot turn main red between them), but lock the gain
//     in: `npm run complexity:shrink`, and commit complexity-baseline.json.
import path from "node:path";
import { pathToFileURL } from "node:url";
import { ESLint } from "eslint";
import { beforeAll, describe, expect, it, vi } from "vitest";
import * as ratchet from "./complexity_ratchet.mjs";

const ROOT = ratchet.FRONTEND;
// Measuring the whole tree parses every linted file (a few seconds locally);
// leave plenty of room for a loaded CI runner or a parallel suite.
const REAL_TREE_TIMEOUT_MS = 180_000;

type Entries = Record<string, number>;

function warnSlack(slack: string[]): void {
  if (slack.length === 0) return;
  console.warn(
    [
      "complexity baseline has slack:",
      ...slack,
      "Lock in the improvement: run `npm run complexity:shrink` and commit complexity-baseline.json.",
    ].join("\n  "),
  );
}

describe("the frontend tree against complexity-baseline.json", () => {
  let baseline: Entries;
  let current: Entries;
  let limit: number;

  beforeAll(async () => {
    baseline = ratchet.loadBaseline(ROOT).complexity;
    limit = await ratchet.configuredLimit(ROOT);
    current = await ratchet.measureComplexity(ROOT, limit);
  }, REAL_TREE_TIMEOUT_MS);

  it("has no new offender and no function above its ceiling", () => {
    const problems = ratchet.compare(baseline, current, limit);
    expect(
      problems,
      `complexity ratchet (#118): fix these, do not add baseline entries:\n  ${problems.join("\n  ")}\n` +
        "See docs/design/domain-modules.md (Frontend) for the rules.",
    ).toEqual([]);
  });

  it("only warns about slack", () => {
    // A function that got simpler should have its ceiling lowered, or the
    // headroom becomes room for the next regression; failing on it would let
    // two independently-green PRs leave main red.
    warnSlack(ratchet.shrinkable(baseline, current));
  });

  it("uses the Phase 4 limit", () => {
    expect(limit).toBe(25);
  });

  it("keeps the baseline file in its canonical shape", () => {
    const data = ratchet.loadBaseline(ROOT);
    expect(Object.keys(data).sort()).toEqual(["_comment", "complexity"]);
    const keys = Object.keys(baseline);
    expect(keys).toEqual([...keys].sort());
    for (const [key, ceiling] of Object.entries(baseline)) {
      expect(key).toMatch(/^[^:]+::.+$/);
      expect(Number.isInteger(ceiling) && ceiling > limit, `${key}: ${ceiling}`).toBe(true);
    }
  });

  it("never baselines the exempt landing engine", () => {
    const exempt = Object.keys(baseline).filter((key) =>
      ratchet.EXEMPT_PREFIXES.some((prefix: string) => key.startsWith(prefix)),
    );
    expect(exempt).toEqual([]);
  });

  it("eslint.config.mjs switches complexity off for exactly the baselined files", async () => {
    const config = (await import(pathToFileURL(path.join(ROOT, "eslint.config.mjs")).href)).default as Array<{
      name?: string;
      files?: string[];
      rules?: Record<string, unknown>;
    }>;
    const generated = config.find((block) => block.name === "complexity/ratchet-baselined");
    expect(generated?.files ?? []).toEqual(ratchet.baselinedFiles(baseline));
    if (generated) expect(generated.rules).toEqual({ complexity: "off" });
    const engine = config.find((block) => block.name === "complexity/landing-engine-exempt");
    expect(engine).toEqual({
      name: "complexity/landing-engine-exempt",
      files: [ratchet.EXEMPT_GLOB],
      rules: { complexity: "off" },
    });
  });

  it(
    "leaves complexity on everywhere else",
    async () => {
      const eslint = new ESLint({ cwd: ROOT });
      // [severity, max]; "off" keeps the inherited option, so only the
      // severity says whether it is enforced.
      const setting = async (rel: string) =>
        (await eslint.calculateConfigForFile(path.join(ROOT, rel))).rules?.complexity as [number, number];
      for (const rel of ratchet.baselinedFiles(baseline)) expect((await setting(rel))[0], rel).toBe(0);
      expect((await setting("src/lib/landing/engine/hero.ts"))[0]).toBe(0);
      expect(await setting("scripts/complexity_ratchet.mjs")).toEqual([2, 25]);
      expect(await setting("src/app/page.tsx")).toEqual([2, 25]);
    },
    REAL_TREE_TIMEOUT_MS,
  );
});

// ── the ratchet's own rules, on synthetic numbers ─────────────────────────

describe("ratchet rules", () => {
  it("flags new offenders and growth only", () => {
    expect(ratchet.compare({ a: 30, b: 30 }, { a: 30, b: 31, c: 26 }, 25)).toEqual([
      "b: 31 is over its baselined ceiling of 30",
      "c: 26 is over the limit of 25 (new)",
    ]);
  });

  it("allows shrinking and disappearing", () => {
    expect(ratchet.compare({ a: 30, b: 30 }, { a: 27 }, 25)).toEqual([]);
  });

  it("reports slack without failing", () => {
    expect(ratchet.shrinkable({ a: 30, b: 30, c: 30 }, { a: 27, c: 30 })).toEqual([
      "a: now 27, baselined at 30, lower it",
      "b: back under the limit, delete its entry",
    ]);
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    warnSlack(ratchet.shrinkable({ a: 30 }, { a: 27 }));
    expect(warn).toHaveBeenCalledWith(expect.stringContaining("lower it"));
    warn.mockRestore();
  });

  it("shrink lowers and drops but never adds or raises", () => {
    const baseline = { lower: 30, gone: 30, grew: 30 };
    const current = { lower: 27, grew: 35, new: 40 };
    expect(ratchet.shrink(baseline, current)).toEqual({ lower: 27, grew: 30 });
    // …so growth and new offenders survive it and still fail.
    expect(ratchet.compare(ratchet.shrink(baseline, current), current, 25)).toEqual([
      "grew: 35 is over its baselined ceiling of 30",
      "new: 40 is over the limit of 25 (new)",
    ]);
  });

  it("lists each baselined file once", () => {
    expect(ratchet.baselinedFiles({ "b.ts::f": 30, "a.tsx::X>y": 30, "a.tsx::X": 40 })).toEqual(["a.tsx", "b.ts"]);
  });

  it("numbers repeated names in source order", () => {
    expect(
      ratchet.keyFindings("f.ts", [
        { line: 9, column: 1, score: 27, name: "X>useEffect()" },
        { line: 3, column: 1, score: 30, name: "X>useEffect()" },
        { line: 5, column: 1, score: 40, name: "X" },
      ]),
    ).toEqual({ "f.ts::X>useEffect()": 30, "f.ts::X": 40, "f.ts::X>useEffect()#2": 27 });
  });
});

// ── function keys, on small snippets ──────────────────────────────────────

describe("function keys", () => {
  const FIXTURE = "src/__complexity_ratchet_fixture__.tsx";
  // limit 0 reports every function, so every key is visible.
  let everyFunction: ESLint;

  beforeAll(() => {
    everyFunction = ratchet.measuringESLint(ROOT, 0);
  });

  const keys = async (code: string, eslint: ESLint = everyFunction) =>
    Object.keys(await ratchet.measureText(eslint, code, FIXTURE, ROOT)).map((key) => key.split("::")[1]);

  it("names anonymous callbacks from their context", async () => {
    const code = `
      export default function Page({ items }) {
        const load = useCallback(async () => {}, []);
        useEffect(() => { const inner = () => 1; return () => inner(); }, []);
        const curried = (a) => (b) => a + b;
        useEffect(() => {}, []);
        fetch(url).then((r) => r);
        sim.force("follow", () => 1);
        return <ul>{items.map((i) => <li key={i} onClick={() => go(i)} />)}{(x) => x}</ul>;
      }
    `;
    expect((await keys(code)).sort()).toEqual(
      [
        "Page",
        "Page>load",
        "Page>useEffect()",
        "Page>useEffect()>inner",
        "Page>useEffect()>(returned)",
        "Page>curried",
        "Page>curried>(returned)",
        "Page>useEffect()#2",
        "Page>then()",
        "Page>sim.force('follow')",
        "Page>items.map()",
        "Page>items.map()>onClick",
        "Page>(jsx child)",
      ].sort(),
    );
  }, REAL_TREE_TIMEOUT_MS);

  it("names methods, object members, nested and assigned functions", async () => {
    const code = `
      class Store {
        reduce(s) { return s; }
        get size() { return 1; }
        handler = () => 2;
        static { init(); }
      }
      const api = { load() {}, save: async () => {}, nested: { deep() {} } };
      function outer() { function inner() {} return inner; }
      export const thing = (a = () => 1) => a;
      promise.then(function named() {});
      x.onDone = () => {};
      export default () => {};
    `;
    expect((await keys(code)).sort()).toEqual(
      [
        "Store.reduce",
        "Store.get size",
        "Store.handler",
        "Store.handler (initializer)",
        "Store.static{}",
        "api.load",
        "api.save",
        "api.nested.deep",
        "outer",
        "outer>inner",
        "thing",
        "thing>a",
        "named",
        "onDone",
        "default",
      ].sort(),
    );
  });

  it("does not depend on line numbers", async () => {
    const body = "function Card() { const go = () => { if (a) b(); }; return go; }";
    const before = await keys(body);
    const after = await keys(`function added() {}\n\n\n// spacer\n${body}`);
    expect(after.filter((key) => key !== "added")).toEqual(before);
  });

  it("numbers collisions among offenders only", async () => {
    // At limit 1 the branch-free callback is not an offender, so the one that
    // is keeps the bare name instead of `run()#2`.
    const atOne = ratchet.measuringESLint(ROOT, 1);
    expect(await keys("run(() => {}); run(() => { if (a) b(); });", atOne)).toEqual(["run()"]);
    expect(await keys("run(() => { if (a) b(); }); run(() => { if (c) d(); });", atOne)).toEqual([
      "run()",
      "run()#2",
    ]);
  });

  it("scores like ESLint's complexity rule", async () => {
    // 1 + if + && + for + if + ?. + ?: (ESLint's "classic" count).
    const code = "function f(a, b) { if (a && b) return 1; for (;;) { if (b?.c) break; } return a ? 2 : 3; }";
    const scored = await ratchet.measureText(everyFunction, code, FIXTURE, ROOT);
    expect(scored).toEqual({ [`${FIXTURE}::f`]: 7 });
  });

  it("refuses a run where its keyed rule and ESLint's disagree", () => {
    const result = (messages: object[]) => [{ filePath: path.join(ROOT, FIXTURE), messages }];
    const builtin = { ruleId: "complexity", line: 1, column: 1, message: "Function 'f' has a complexity of 30. Maximum allowed is 25." };
    expect(() => ratchet.collect(result([builtin]), ROOT)).toThrow(/disagrees/);
    const keyed = { ruleId: "complexity-ratchet/keyed", line: 1, column: 1, message: "30\tf" };
    expect(ratchet.collect(result([builtin, keyed]), ROOT)).toEqual({ [`${FIXTURE}::f`]: 30 });
  });

  it("refuses a file it cannot parse", () => {
    const fatal = { ruleId: null, fatal: true, line: 3, column: 1, message: "Parsing error: ';' expected." };
    expect(() => ratchet.collect([{ filePath: path.join(ROOT, FIXTURE), messages: [fatal] }], ROOT)).toThrow(
      /cannot measure complexity/,
    );
  });
});
