// @vitest-environment jsdom
/**
 * NEXT_PUBLIC_TEST_MODE determinism for KnowledgeGraph2D (#383).
 *
 * With the flag on the component must (a) seed its initial node
 * positions from the deterministic PRNG instead of Math.random(), and
 * (b) take the reduced-motion path so the d3-force simulation settles
 * synchronously with a fixed tick count. Together those pin the
 * acceptance criterion: two consecutive loads of the graph view render
 * identical node coordinates.
 *
 * Module-loading strategy: the flag is captured when `@/lib/testMode`
 * first evaluates, so we stub the env at file scope and import the
 * component lazily in beforeAll. No `vi.resetModules()` — that would
 * fork a second React copy and break hooks against the test renderer's
 * react-dom. A "fresh page load" is simulated with `resetTestRng()`,
 * which rewinds the seeded sequence to its module-init state.
 */

import { describe, it, expect, vi, beforeAll, afterEach } from "vitest";
import { render, cleanup } from "@testing-library/react";
import React from "react";
import type { GraphEdge, GraphNode } from "@/lib/data";
import GOLDEN from "./__fixtures__/knowledgeGraph2D.golden.json";

vi.stubEnv("NEXT_PUBLIC_TEST_MODE", "1");

let KnowledgeGraph2D: (typeof import("./KnowledgeGraph2D"))["KnowledgeGraph2D"];
let resetTestRng: (typeof import("@/lib/testMode"))["resetTestRng"];

beforeAll(async () => {
  ({ resetTestRng } = await import("@/lib/testMode"));
  ({ KnowledgeGraph2D } = await import("./KnowledgeGraph2D"));
});

afterEach(() => {
  cleanup();
});

const NODES: GraphNode[] = [
  { id: "root", name: "Math", subject: "Math", color: "#7a874f", is_subject_root: true, mastery_tier: "learning", mastery_score: 0, course_id: "c1" },
  { id: "a", name: "Limits", subject: "Math", color: "#7a874f", mastery_tier: "learning", mastery_score: 0.4, course_id: "c1" },
  { id: "b", name: "Derivatives", subject: "Math", color: "#7a874f", mastery_tier: "struggling", mastery_score: 0.2, course_id: "c1" },
  { id: "c", name: "Integrals", subject: "Math", color: "#7a874f", mastery_tier: "unexplored", mastery_score: 0, course_id: "c1" },
  { id: "d", name: "Series", subject: "Math", color: "#7a874f", mastery_tier: "mastered", mastery_score: 0.9, course_id: "c1" },
];

const EDGES: GraphEdge[] = [
  { source: "root", target: "a", strength: 0.8 },
  { source: "a", target: "b", strength: 0.6 },
  { source: "b", target: "c", strength: 0.5 },
  { source: "a", target: "d", strength: 0.7 },
];

/**
 * The golden set (#537): the determinism cases above only need the node/edge
 * subset, but the golden fixture pins the *paint* too, so it carries one more
 * node — a >18-char name, which is where the label truncation shows up.
 */
const GOLDEN_NODES: GraphNode[] = [
  ...NODES,
  { id: "e", name: "Fundamental theorem of calculus", subject: "Math", color: "#7a874f", mastery_tier: "learning", mastery_score: 0.55, course_id: "c1" },
];
const GOLDEN_EDGES: GraphEdge[] = [...EDGES, { source: "d", target: "e", strength: 0.3 }];

const at = (el: Element, name: string) => el.getAttribute(name) ?? "";

/**
 * Every rendered node position + edge coordinate + the paint attributes, as
 * attribute strings. Node positions live on the group's `transform` (#111
 * moved the per-tick writes off React: children sit at relative cx/cy 0 and
 * the group carries the translate); circle radii are kept so size regressions
 * still surface.
 *
 * `fill` / `opacity` / `stroke-opacity` (and the label font/fill/truncation)
 * were added for #537: the node-style layer moved out to `lib/graph/nodeStyle`
 * and this snapshot is the proof that the extraction changed nothing the tree
 * paints. The committed fixture was captured from the pre-extraction renderer.
 * Missing attributes read as "" rather than "null" so the NaN/null/undefined
 * guard below stays meaningful.
 */
function snapshot(container: HTMLElement): string[] {
  const svg = container.querySelector("svg");
  expect(svg).not.toBeNull();
  const groups = Array.from(svg!.querySelectorAll('[data-testid="graph-node"]')).map(
    (g) => `n:${at(g, "transform")}`,
  );
  const circles = Array.from(svg!.querySelectorAll("circle")).map(
    (c) =>
      `c:${at(c, "cx")},${at(c, "cy")},${at(c, "r")}` +
      `|fill=${at(c, "fill")}|op=${at(c, "opacity")}` +
      `|stroke=${at(c, "stroke")}|sw=${at(c, "stroke-width")}|sop=${at(c, "stroke-opacity")}`,
  );
  const lines = Array.from(svg!.querySelectorAll("line")).map(
    (l) =>
      `l:${at(l, "x1")},${at(l, "y1")},${at(l, "x2")},${at(l, "y2")}` +
      `|stroke=${at(l, "stroke")}|sop=${at(l, "stroke-opacity")}|sw=${at(l, "stroke-width")}`,
  );
  const texts = Array.from(svg!.querySelectorAll("text")).map(
    (t) =>
      `t:${t.textContent}|${at(t, "x")},${at(t, "y")}` +
      `|font=${at(t, "font-family")}|fs=${at(t, "font-size")}|fill=${at(t, "fill")}|op=${at(t, "opacity")}`,
  );
  return [...groups, ...circles, ...lines, ...texts];
}

describe("KnowledgeGraph2D — test-mode determinism", () => {
  it("two consecutive loads render identical node coordinates", () => {
    const first = render(
      <KnowledgeGraph2D nodes={NODES} edges={EDGES} width={600} height={480} />,
    );
    const snap1 = snapshot(first.container);
    // The simulation must have actually laid out and rendered content.
    expect(snap1.length).toBeGreaterThan(0);
    expect(snap1.some((s) => s.startsWith("n:"))).toBe(true);
    expect(snap1.some((s) => s.startsWith("l:"))).toBe(true);
    for (const s of snap1) {
      expect(s).not.toMatch(/NaN|null|undefined/);
    }
    cleanup();

    // Fresh "page load": module state rewound, brand-new mount.
    resetTestRng();
    const second = render(
      <KnowledgeGraph2D nodes={NODES} edges={EDGES} width={600} height={480} />,
    );
    expect(snapshot(second.container)).toEqual(snap1);
  });

  it("nodes settle into a spread-out layout, not a degenerate point", () => {
    resetTestRng();
    const { container } = render(
      <KnowledgeGraph2D nodes={NODES} edges={EDGES} width={600} height={480} />,
    );
    const centers = new Set(
      Array.from(container.querySelectorAll('[data-testid="graph-node"]')).map(
        (g) => g.getAttribute("transform"),
      ),
    );
    // 5 nodes must occupy at least 5 distinct positions once settled.
    expect(centers.size).toBeGreaterThanOrEqual(NODES.length);
  });

  it("paints byte-identically to the golden captured before the nodeStyle extraction (#537)", () => {
    resetTestRng();
    const { container } = render(
      <KnowledgeGraph2D nodes={GOLDEN_NODES} edges={GOLDEN_EDGES} width={600} height={480} />,
    );
    // Equality on the whole array, not a subset: a changed shade, a moved
    // opacity ramp, a retuned radius or a lost label truncation all land here.
    expect(snapshot(container)).toEqual(GOLDEN);
  });
});
