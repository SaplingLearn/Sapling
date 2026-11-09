// @vitest-environment jsdom
/**
 * Per-node / per-link paint across the render variants, pinned as a golden.
 *
 * The test-mode golden (`KnowledgeGraph2D.testmode.test.tsx`) covers the
 * default plain organism graph only. This one pins every branch the per-node
 * and per-link renderers take — constellation, mastery colours, legible
 * (course focus, hover focus, zoom-dependent labels/arrows/minimum radius),
 * highlight pulse, comparison rings, a pinned (dragged) concept, the hovered
 * stroke and the tooltip — as the full serialized markup, so a refactor of
 * the renderers can prove it changed nothing in the DOM.
 *
 * Test mode is on (as in the test-mode golden) so the simulation settles
 * synchronously and positions are identical on every run. The per-instance
 * gradient/marker prefix (from `useId`) is normalised.
 *
 * Re-capture (only for an intended paint change):
 *   KG_WRITE_GOLDEN=1 npx vitest run src/components/graph/KnowledgeGraph2D.variants.test.tsx
 */

import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render } from "@testing-library/react";
import React from "react";
import fs from "node:fs";
import path from "node:path";
import type { GraphEdge, GraphNode } from "@/lib/data";

vi.stubEnv("NEXT_PUBLIC_TEST_MODE", "1");

let KnowledgeGraph2D: (typeof import("./KnowledgeGraph2D"))["KnowledgeGraph2D"];
let resetTestRng: (typeof import("@/lib/testMode"))["resetTestRng"];

const GOLDEN_PATH = path.join(__dirname, "__fixtures__", "knowledgeGraph2D.variants.golden.json");
const WRITE = process.env.KG_WRITE_GOLDEN === "1";
const captured: Record<string, string[]> = {};
let GOLDEN: Record<string, string[]> = {};

beforeAll(async () => {
  ({ resetTestRng } = await import("@/lib/testMode"));
  ({ KnowledgeGraph2D } = await import("./KnowledgeGraph2D"));
  // jsdom has no pointer capture; the drag handlers call it.
  if (!Element.prototype.setPointerCapture) Element.prototype.setPointerCapture = () => {};
  if (!Element.prototype.releasePointerCapture) Element.prototype.releasePointerCapture = () => {};
  if (!WRITE) GOLDEN = JSON.parse(fs.readFileSync(GOLDEN_PATH, "utf8"));
});

afterEach(() => {
  cleanup();
});

if (WRITE) {
  afterAll(() => fs.writeFileSync(GOLDEN_PATH, JSON.stringify(captured, null, 2) + "\n"));
}

const N = (
  id: string,
  course: string,
  tier: GraphNode["mastery_tier"],
  score: number,
  extra: Partial<GraphNode> = {},
): GraphNode => ({
  id,
  name: id.toUpperCase(),
  subject: course === "c1" ? "Ling" : "Math",
  color: course === "c1" ? "#3e6f8a" : "#7a874f",
  mastery_tier: tier,
  mastery_score: score,
  course_id: course,
  ...extra,
});

const NODES: GraphNode[] = [
  N("r1", "c1", "learning", 0, { name: "CAS LX 250", is_subject_root: true }),
  N("a", "c1", "mastered", 0.9, { name: "Phonemes", last_studied_at: "2d ago" }),
  N("b", "c1", "learning", 0.5, { name: "Morphology" }),
  N("c", "c1", "struggling", 0.2, { name: "A very long concept name indeed" }),
  N("d", "c1", "unexplored", 0, { name: "Semantics" }),
  N("r2", "c2", "learning", 0, { name: "MA 123", is_subject_root: true }),
  N("x", "c2", "learning", 0.4, { name: "Limits" }),
  N("y", "c2", "mastered", 0.8, { name: "Derivatives" }),
];
const EDGES: GraphEdge[] = [
  { source: "r1", target: "a", strength: 0.8 },
  { source: "a", target: "b", strength: 0.9, relationship_type: "prerequisite" },
  { source: "b", target: "c", strength: 0.6, relationship_type: "builds_on" },
  { source: "a", target: "d", strength: 0.4, relationship_type: "related" },
  { source: "c", target: "d", strength: 0.3, relationship_type: "part_of" },
  { source: "r2", target: "x", strength: 0.7 },
  { source: "x", target: "y", strength: 0.5, relationship_type: "prerequisite" },
];

type Props = React.ComponentProps<(typeof import("./KnowledgeGraph2D"))["KnowledgeGraph2D"]>;
type Case = {
  props?: Partial<Props>;
  /** What the pointer does before the capture. */
  act?: (c: HTMLElement) => void;
};

const nodeEl = (c: HTMLElement, id: string) =>
  c.querySelector(`[data-testid="graph-node"][data-node-id="${id}"]`)!;
const hover = (id: string) => (c: HTMLElement) =>
  fireEvent.pointerEnter(nodeEl(c, id), { clientX: 120, clientY: 80 });
const press = (id: string) => (c: HTMLElement) =>
  fireEvent.pointerDown(nodeEl(c, id), { pointerId: 1, clientX: 120, clientY: 80, button: 0 });

const CASES: Record<string, Case> = {
  plain: {},
  "plain-highlight-comparison": {
    props: {
      highlightId: "b",
      comparison: [
        { name: "Phonemes", mastery_score: 0.6 },
        { name: " morphology ", mastery_score: 0.2 },
        { name: "CAS LX 250", mastery_score: 1 },
      ],
      comparisonLabel: "Sam",
    },
  },
  "plain-comparison-nolabel": { props: { comparison: [{ name: "Limits", mastery_score: 0.3 }], comparisonColor: "#123456" } },
  constellation: { props: { variant: "constellation", highlightId: "x" } },
  orb: { props: { variant: "orb" } },
  mastery: { props: { colorMode: "mastery" } },
  "mastery-constellation": { props: { colorMode: "mastery", variant: "constellation" } },
  "plain-hover-concept": { act: hover("b") },
  "plain-hover-root": { act: hover("r1") },
  "plain-hover-unstudied": { act: hover("d") },
  "plain-press-concept": { act: press("b") },
  "plain-press-root": { act: press("r2") },
  legible: { props: { legible: true } },
  "legible-mastery": { props: { legible: true, colorMode: "mastery" } },
  "legible-constellation": { props: { legible: true, variant: "constellation" } },
  "legible-course-focus": { props: { legible: true, focusCourseId: "c2" } },
  "legible-hover-concept": { props: { legible: true }, act: hover("b") },
  "legible-hover-root": { props: { legible: true }, act: hover("r1") },
  "legible-hover-concept-course-focus": { props: { legible: true, focusCourseId: "c2" }, act: hover("a") },
  "legible-mastery-hover": { props: { legible: true, colorMode: "mastery" }, act: hover("a") },
  "legible-zoomed-in": { props: { legible: true, initialZoom: 2 } },
  "legible-zoomed-out": { props: { legible: true, initialZoom: 0.5 } },
  "legible-zoomed-out-hover": { props: { legible: true, initialZoom: 0.5 }, act: hover("c") },
  "legible-press-concept": { props: { legible: true }, act: press("c") },
};

/** The whole rendered markup (svg + controls + tooltip + a11y list), one tag per line. */
function serialize(c: HTMLElement): string[] {
  return c.innerHTML
    .replace(/kg[A-Za-z0-9_]+?-(e\d+|arrow)/g, "kgID-$1")
    .replace(/></g, ">\n<")
    .split("\n");
}

describe("KnowledgeGraph2D — per-node / per-link paint variants", () => {
  for (const [name, { props, act }] of Object.entries(CASES)) {
    it(`renders ${name} identically to the golden`, () => {
      resetTestRng();
      const { container } = render(
        <KnowledgeGraph2D nodes={NODES} edges={EDGES} width={600} height={480} onNodeClick={() => {}} {...props} />,
      );
      act?.(container);
      const out = serialize(container);
      expect(out.join("\n")).not.toMatch(/NaN|undefined/);
      if (WRITE) {
        captured[name] = out;
        return;
      }
      expect(out).toEqual(GOLDEN[name]);
    });
  }
});
