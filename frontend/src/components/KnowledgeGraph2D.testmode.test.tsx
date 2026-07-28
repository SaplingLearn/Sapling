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

/** Every rendered circle + edge coordinate, as attribute strings. */
function snapshot(container: HTMLElement): string[] {
  const svg = container.querySelector("svg");
  expect(svg).not.toBeNull();
  const circles = Array.from(svg!.querySelectorAll("circle")).map(
    (c) => `c:${c.getAttribute("cx")},${c.getAttribute("cy")},${c.getAttribute("r")}`,
  );
  const lines = Array.from(svg!.querySelectorAll("line")).map(
    (l) => `l:${l.getAttribute("x1")},${l.getAttribute("y1")},${l.getAttribute("x2")},${l.getAttribute("y2")}`,
  );
  return [...circles, ...lines];
}

describe("KnowledgeGraph2D — test-mode determinism", () => {
  it("two consecutive loads render identical node coordinates", () => {
    const first = render(
      <KnowledgeGraph2D nodes={NODES} edges={EDGES} width={600} height={480} />,
    );
    const snap1 = snapshot(first.container);
    // The simulation must have actually laid out and rendered content.
    expect(snap1.length).toBeGreaterThan(0);
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
      Array.from(container.querySelectorAll("circle")).map(
        (c) => `${c.getAttribute("cx")},${c.getAttribute("cy")}`,
      ),
    );
    // 5 nodes must occupy at least 5 distinct positions once settled.
    expect(centers.size).toBeGreaterThanOrEqual(NODES.length);
  });
});
