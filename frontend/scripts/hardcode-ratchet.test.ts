// Hardcode ratchet: no file may gain a hand-written colour, size, layer,
// timing or URL that a token should carry.
//
// The real check measures the src/ tree against hardcode-baseline.json (logic
// in scripts/hardcode-ratchet.mjs). The rest pins the counting on synthetic
// input, so a refactor cannot quietly turn the ratchet into a no-op.
//
// When the real check fails:
//   * a count went UP or a NEW key appeared: use the token
//     (docs/frontend-design-tokens.md). Do not raise or add a baseline entry.
//   * it went DOWN: nothing fails (slack only warns, so two PRs that each
//     convert part of a file cannot leave main red between them), but lock the
//     gain in: `npm run hardcode:shrink`, and commit hardcode-baseline.json.
import fs from "node:fs";
import path from "node:path";
import { beforeAll, describe, expect, it } from "vitest";
import * as ratchet from "./hardcode-ratchet.mjs";

const ROOT = ratchet.FRONTEND;
const REAL_TREE_TIMEOUT_MS = 120_000;

type Entries = Record<string, number>;

describe("the src/ tree against hardcode-baseline.json", () => {
  let baseline: Entries;
  let current: Entries;

  beforeAll(() => {
    baseline = ratchet.loadBaseline(ROOT)[ratchet.KEY];
    current = ratchet.measure(ROOT);
  }, REAL_TREE_TIMEOUT_MS);

  it("has no new hardcoded value", () => {
    const problems = ratchet.compare(baseline, current);
    expect(
      problems,
      `hardcode ratchet: use a token (docs/frontend-design-tokens.md), do not add or raise baseline entries:\n  ${problems.join("\n  ")}`,
    ).toEqual([]);
  });

  it("only warns about slack", async ({ annotate }) => {
    const slack = ratchet.shrinkable(baseline, current);
    if (slack.length === 0) return;
    const message = [
      "hardcode baseline has slack:",
      ...slack,
      "Lock in the improvement: run `npm run hardcode:shrink` and commit hardcode-baseline.json.",
    ].join("\n  ");
    console.warn(message);
    await annotate(message, "warning");
  });

  it("keeps the baseline file in its canonical shape", () => {
    const file = ratchet.loadBaseline(ROOT);
    expect(Object.keys(file).sort()).toEqual(["_comment", ratchet.KEY]);
    const keys = Object.keys(baseline);
    expect(keys).toEqual([...keys].sort());
    for (const [key, count] of Object.entries(baseline)) {
      const [file_, category] = key.split("::");
      expect(ratchet.isMeasured(file_), `${key}: not a measured file`).toBe(true);
      expect(ratchet.CATEGORIES, key).toContain(category);
      expect(Number.isInteger(count) && count > 0, `${key}: ${count}`).toBe(true);
    }
  });

  it("still finds the landing sections it skips in globals.css", () => {
    const css = fs.readFileSync(path.join(ROOT, "src/app/globals.css"), "utf8");
    for (const { banner } of ratchet.GLOBALS_LANDING_SECTIONS) {
      expect(css.includes(banner), `globals.css lost the banner "${banner}"; update GLOBALS_LANDING_SECTIONS`).toBe(true);
    }
  });
});

describe("what is measured", () => {
  it.each([
    ["src/components/learn/LoopLearn.tsx", true],
    ["src/components/quiz/question/question.css", true],
    ["src/app/globals.css", true],
    ["src/components/learn/LoopLearn.test.tsx", false],
    ["src/components/graph/__fixtures__/x.ts", false],
    ["src/components/x/__snapshots__/y.tsx", false],
    ["src/lib/designTokens.ts", false],
    ["src/components/landing-v5/Hero.tsx", false],
    ["src/app/(public)/about/page.tsx", false],
    ["src/components/marketing/SignInModal.tsx", false],
    ["src/lib/x.json", false],
    ["scripts/x.mjs", false],
  ])("%s → %s", (rel, measured) => {
    expect(ratchet.isMeasured(rel)).toBe(measured);
  });
});

describe("CSS", () => {
  const scan = (css: string, opts?: { isGlobals?: boolean }) => ratchet.scanCss(css, opts).counts;

  it("counts colours in declarations, not in selectors or comments", () => {
    expect(scan("#id { color: #fff; background: rgba(0,0,0,.5); } /* #abc rgb(1,2,3) */")).toEqual({ color: 2, "css-size": 0 });
  });

  it("counts px/rem on spacing, type, radius and shadow, but not zero or other properties", () => {
    expect(scan(".a { margin: 0 8px; padding-top: 1.5rem; gap: 4px 6px; font-size: 13px; border-top-left-radius: 6px; width: 200px; top: 4px; }"))
      .toEqual({ color: 0, "css-size": 6 });
    expect(scan(".a { box-shadow: 0 1px 2px var(--x); }")["css-size"]).toBe(2);
  });

  it("counts a literal z-index, but not zero or a token", () => {
    expect(scan(".a { z-index: 20; } .b { z-index: 0; } .c { z-index: var(--z-modal); }")["css-size"]).toBe(1);
  });

  it("counts times and curves in transitions and animations", () => {
    expect(scan(".a { transition: opacity 200ms ease, transform 0.2s cubic-bezier(0.2,0,0,1); animation-delay: 0s; }")["css-size"]).toBe(3);
    expect(scan(".a { transition: opacity var(--dur) var(--ease); }")["css-size"]).toBe(0);
  });

  it("skips globals.css token definitions, but not a component's", () => {
    expect(scan(":root { --x: #fff; } .a { --y: #000; color: #111; }", { isGlobals: true }).color).toBe(1);
    expect(scan(".a { --y: #000; }").color).toBe(1);
  });

  it("skips the landing scope", () => {
    expect(scan(".landing-page .x { color: #fff; } .ld-btn:hover { color: #000; } @keyframes landing-glow { to { color: #111; } }").color).toBe(0);
    expect(scan("@media (max-width: 600px) { .landing-v5 .x { margin: 4px; } .app { margin: 4px; } }")["css-size"]).toBe(1);
  });

  it("blanks globals.css's landing sections, keeping line numbers", () => {
    const banner = (title: string) => `/* ════\n   ${title}\n   ════ */\n`;
    const css = `.a { color: #111; }\n${banner("LANDING PAGE STYLES (ported from main branch)")}.font-x { color: #222; }\n${banner("RARITY")}.b { color: #333; }\n${banner("LANDING (design-component ports)")}.c { color: #444; }\n`;
    const { counts, hits } = ratchet.scanCss(css, { isGlobals: true });
    expect(counts.color).toBe(2);
    expect(hits.map((h: { line: number }) => h.line)).toEqual([1, 9]);
  });
});

describe("TS / TSX", () => {
  const scan = (code: string, file = "x.tsx") => ratchet.scanTs(code, file).counts;

  it("counts colours in string literals, not in comments", () => {
    expect(scan(`// #866 is the PR, rgb(1, 2, 3)\nconst a = "#7A4A78"; const b = \`rgb(1, 2, 3)\`; /* #abc */`))
      .toEqual({ color: 2, "inline-style": 0, url: 0 });
  });

  it("does not take a URL fragment or an entity for a colour", () => {
    expect(scan(`const a = "/learn#add"; const b = "&#123;";`).color).toBe(0);
  });

  it("counts literal numbers, lengths and colours in a style attribute", () => {
    const code = `<div style={{ padding: 12, margin: "4px 8px", color: "#fff", gap: 0, flex: 1, opacity: 0.5, zIndex: 20, top: -4, background: "var(--bg)" }} />`;
    expect(scan(code)).toEqual({ color: 0, "inline-style": 6, url: 0 });
  });

  it("follows conditionals and CSSProperties-typed objects", () => {
    expect(scan(`<div style={dense ? { padding: 8 } : { padding: 12 }} />`)["inline-style"]).toBe(2);
    expect(scan(`const S: React.CSSProperties = { borderRadius: 8, fontSize: "var(--fs-sm)" };`, "x.ts")["inline-style"]).toBe(1);
    expect(scan(`const M: Record<string, CSSProperties> = { a: { margin: 4 }, b: { margin: 6 } };`, "x.ts")["inline-style"]).toBe(2);
    expect(scan(`function f(): React.CSSProperties { return { padding: 10 }; }`, "x.ts")["inline-style"]).toBe(1);
    expect(scan(`const p = { style: { marginTop: 6 } };`, "x.ts")["inline-style"]).toBe(1);
  });

  it("counts timings only in a style's transition or animation", () => {
    expect(scan(`<div style={{ transition: "opacity 200ms ease" }} />`)["inline-style"]).toBe(1);
    expect(scan(`<div style={{ transition: "opacity var(--dur) var(--ease)" }} />`)["inline-style"]).toBe(0);
  });

  it("counts URLs and localhost, but not XML namespaces or imports", () => {
    const code = `import x from "https://cdn.example/x.js";\nconst a = "https://api.example.com/v1"; const b = \`http://localhost:\${port}\`; const ns = "http://www.w3.org/2000/svg";`;
    expect(scan(code, "x.ts").url).toBe(2);
  });

  it("leaves a plain object's numbers alone", () => {
    expect(scan(`const config = { retries: 3, timeoutMs: 1500 };`, "x.ts")["inline-style"]).toBe(0);
  });
});

describe("the ratchet", () => {
  it("fails on growth and on a new key, never on a drop", () => {
    expect(ratchet.compare({ "a::color": 3 }, { "a::color": 4, "b::url": 1 })).toHaveLength(2);
    expect(ratchet.compare({ "a::color": 3 }, { "a::color": 2 })).toEqual([]);
  });

  it("asks for --shrink when a count drops or reaches zero", () => {
    expect(ratchet.shrinkable({ "a::color": 3, "b::url": 1 }, { "a::color": 2 })).toHaveLength(2);
  });

  it("shrink only lowers and deletes", () => {
    expect(ratchet.shrink({ "a::color": 3, "b::url": 1, "c::color": 2 }, { "a::color": 2, "c::color": 5, "d::url": 1 }))
      .toEqual({ "a::color": 2, "c::color": 2 });
  });

  it("summarizes per category and per file, largest first", () => {
    const s = ratchet.summarize({ "a::color": 1, "b::color": 2, "b::url": 2 });
    expect(s.total).toBe(5);
    expect(s.totals).toEqual({ color: 3, "css-size": 0, "inline-style": 0, url: 2 });
    expect(s.files[0]).toMatchObject({ file: "b", total: 4 });
  });
});
