// @vitest-environment jsdom
/**
 * Links run rim to rim: no line is drawn underneath a node. Node fills are
 * translucent (tier opacity, legible fades), so a line to a node's centre
 * showed through it.
 *
 * A node is a hand-drawn outline, not a circle, so "the rim" is the outline
 * itself in the link's direction (`lib/graph/blobShape`). A link's square end
 * runs half a unit under it to close the sliver against the curve; a link
 * with an arrowhead stops short of its target to leave room for the head.
 */

import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render } from "@testing-library/react";
import React from "react";
import type { GraphEdge, GraphNode } from "@/lib/data";
import { blobProfile, rimRadius, wobbleFor } from "@/lib/graph/blobShape";
import { edgeWidthFor, radiusFor } from "@/lib/graph/nodeStyle";
import { importanceRadii, splitEdges } from "@/lib/graph/radialLayout";
import { KnowledgeGraph2D } from "./KnowledgeGraph2D";
import { ANCHOR_WIDTH, ARROW_REF_X, ARROW_SIZE } from "./knowledgeGraph2DPaint";

afterEach(cleanup);

const node = (id: string, tier: GraphNode["mastery_tier"], score: number): GraphNode => ({
  id, name: id, subject: "Ling", color: "#3e6f8a", mastery_tier: tier, mastery_score: score, course_id: "c1",
});
const NODES: GraphNode[] = [
  { ...node("hub", "mastered", 0), name: "CAS LX 250", is_subject_root: true },
  node("a", "mastered", 0.9),
  node("b", "learning", 0.5),
  node("c", "struggling", 0.2),
  node("d", "unexplored", 0),
];
const EDGES: GraphEdge[] = [
  { source: "a", target: "b", strength: 0.9, relationship_type: "prerequisite" },
  { source: "b", target: "c", strength: 0.6, relationship_type: "builds_on" },
  { source: "a", target: "d", strength: 0.4, relationship_type: "related" },
];

/** How far a link's square end runs under the rim it meets. */
const OVERLAP = 0.5;
/** How far an arrowed link stops short of its target's rim. */
const ARROW_REACH = (ARROW_SIZE * (10 - ARROW_REF_X)) / 10 + 1;

type Mark = { id: string; x: number; y: number; r: number; rest: number };

/**
 * A node's resting radius, as the component sizes it: by mastery, or in
 * legible mode by importance (how much hangs off the concept).
 */
function restingRadii(legible: boolean): Map<string, number> {
  const importance = legible ? importanceRadii(NODES, splitEdges(NODES, EDGES).concept) : null;
  return new Map(
    NODES.map((n) => [
      n.id,
      (!n.is_subject_root && importance?.get(n.id)) || radiusFor(n.mastery_score, n.is_subject_root),
    ]),
  );
}

function marks(container: HTMLElement, legible = false): Mark[] {
  const rest = restingRadii(legible);
  return Array.from(container.querySelectorAll<SVGGElement>('[data-testid="graph-node"]')).map((g) => {
    const [, x, y] = /translate\(([-\d.e]+),\s*([-\d.e]+)\)/.exec(g.getAttribute("transform")!)!;
    const mark = g.querySelector('[data-testid="graph-node-circle"]')!;
    const id = g.getAttribute("data-node-id")!;
    return {
      id,
      x: Number(x),
      y: Number(y),
      // The drawn radius: the resting one, or larger when a legible graph is
      // zoomed out and holds its nodes at a minimum size on screen. The
      // outline's irregularity always follows the resting radius.
      r: Number(mark.getAttribute("data-r")),
      rest: rest.get(id)!,
    };
  });
}

/** The mark's drawn outline in the direction of (x, y). */
const rimToward = (m: Mark, x: number, y: number) =>
  rimRadius(blobProfile(m.id, wobbleFor(m.rest)), m.r, Math.atan2(y - m.y, x - m.x));

const ends = (e: Element) => ({
  x1: Number(e.getAttribute("x1")),
  y1: Number(e.getAttribute("y1")),
  x2: Number(e.getAttribute("x2")),
  y2: Number(e.getAttribute("y2")),
});

describe.each([
  ["plain", {} as { legible?: boolean }],
  ["legible", { legible: true }],
  // Wide enough to open at 1×, where directed links carry their arrowheads.
  ["legible, at 1×", { legible: true, width: 1200, height: 900 }],
  ["mastery colours", { colorMode: "mastery" as const }],
])("KnowledgeGraph2D links (%s)", (_name, props) => {
  const legible = "legible" in props && props.legible === true;

  it("reads a real radius off every node", () => {
    const { container } = render(
      <KnowledgeGraph2D nodes={NODES} edges={EDGES} width={500} height={400} {...props} />,
    );
    const all = marks(container, legible);
    expect(all).toHaveLength(NODES.length);
    for (const m of all) {
      expect(m.r).toBeGreaterThanOrEqual(m.rest);
      expect(m.r).toBeGreaterThan(0);
    }
  });

  it("never draws a link endpoint inside a node", () => {
    const { container } = render(
      <KnowledgeGraph2D nodes={NODES} edges={EDGES} width={500} height={400} {...props} />,
    );
    const all = marks(container, legible);
    const edges = Array.from(container.querySelectorAll('[data-testid="graph-edge"]'));
    expect(edges.length).toBeGreaterThan(0);
    let drawn = 0;
    for (const e of edges) {
      const { x1, y1, x2, y2 } = ends(e);
      if (x1 === x2 && y1 === y2) continue; // touching nodes: nothing drawn
      drawn += 1;
      for (const [x, y] of [[x1, y1], [x2, y2]]) {
        for (const m of all) {
          const inside = rimToward(m, x, y) - Math.hypot(x - m.x, y - m.y);
          expect(inside, `edge end ${inside.toFixed(2)} inside ${m.id}`).toBeLessThanOrEqual(OVERLAP + 1e-6);
        }
      }
    }
    expect(drawn).toBeGreaterThan(0);
  });

  it("starts every link on its source's outline and ends it on, or just short of, its target's", () => {
    const { container } = render(
      <KnowledgeGraph2D nodes={NODES} edges={EDGES} width={500} height={400} {...props} />,
    );
    const all = marks(container, legible);
    /** The mark whose outline the point (x, y) is nearest. */
    const nearest = (x: number, y: number) =>
      all
        .map((m) => ({ m, gap: Math.hypot(x - m.x, y - m.y) - rimToward(m, x, y) }))
        .sort((p, q) => Math.abs(p.gap) - Math.abs(q.gap))[0];
    let drawn = 0;
    for (const e of container.querySelectorAll('[data-testid="graph-edge"]')) {
      const { x1, y1, x2, y2 } = ends(e);
      if (x1 === x2 && y1 === y2) continue;
      drawn += 1;
      // The source end sits half a unit under the source's outline.
      expect(nearest(x1, y1).gap).toBeCloseTo(-OVERLAP, 6);
      // The target end too, unless the link carries an arrowhead.
      const arrowed = e.hasAttribute("marker-end");
      expect(nearest(x2, y2).gap).toBeCloseTo(arrowed ? ARROW_REACH : -OVERLAP, 6);
    }
    expect(drawn).toBeGreaterThan(0);
  });
});

describe("KnowledgeGraph2D links — the hand-drawn bar", () => {
  const edgesOf = (container: HTMLElement) => Array.from(container.querySelectorAll('[data-testid="graph-edge"]'));

  // The course's own links (one to each starting concept) are drawn faint and
  // thin; every other link is a concept-to-concept link.
  const isAnchor = (e: Element) => Number(e.getAttribute("stroke-width")) === ANCHOR_WIDTH;

  it("is a flat bar in the course's colour, with square ends", () => {
    const { container } = render(<KnowledgeGraph2D nodes={NODES} edges={EDGES} width={500} height={400} />);
    const solid = edgesOf(container).filter((e) => !e.hasAttribute("stroke-dasharray") && !isAnchor(e));
    // prerequisite and builds_on.
    expect(solid).toHaveLength(2);
    for (const e of solid) {
      expect(e).toHaveAttribute("stroke", "#3e6f8a");
      expect(e).toHaveAttribute("stroke-linecap", "butt");
      expect(Number(e.getAttribute("stroke-opacity"))).toBe(0.45);
      // Thick enough to read as part of the drawing.
      expect(Number(e.getAttribute("stroke-width"))).toBeGreaterThanOrEqual(2.2);
    }
    expect(Number(solid[0].getAttribute("stroke-width"))).toBeCloseTo(edgeWidthFor(0.9), 10);
    expect(Number(solid[1].getAttribute("stroke-width"))).toBeCloseTo(edgeWidthFor(0.6), 10);
    expect(container.querySelector("linearGradient")).toBeNull();
  });

  it("draws the course's own links faint and thin, in the same colour", () => {
    const { container } = render(<KnowledgeGraph2D nodes={NODES} edges={EDGES} width={500} height={400} />);
    const anchors = edgesOf(container).filter(isAnchor);
    // One to each concept nothing leads into: a, and d (only `related` to a).
    expect(anchors).toHaveLength(2);
    for (const e of anchors) {
      expect(e).toHaveAttribute("stroke", "#3e6f8a");
      expect(Number(e.getAttribute("stroke-opacity"))).toBe(0.16);
      expect(e).not.toHaveAttribute("marker-end");
    }
    // …and just as faint in mastery colours, where they are gradients.
    cleanup();
    const mastery = render(
      <KnowledgeGraph2D nodes={NODES} edges={EDGES} width={500} height={400} colorMode="mastery" />,
    );
    const faint = edgesOf(mastery.container).filter(isAnchor);
    expect(faint).toHaveLength(2);
    for (const e of faint) expect(Number(e.getAttribute("stroke-opacity"))).toBe(0.16);
  });

  it("draws a `related` link as a row of round dots", () => {
    const { container } = render(<KnowledgeGraph2D nodes={NODES} edges={EDGES} width={500} height={400} />);
    const dotted = edgesOf(container).filter((e) => e.hasAttribute("stroke-dasharray"));
    expect(dotted).toHaveLength(1);
    const width = edgeWidthFor(0.4);
    expect(Number(dotted[0].getAttribute("stroke-width"))).toBeCloseTo(width, 10);
    expect(dotted[0]).toHaveAttribute("stroke-dasharray", `0.01 ${(width * 2.2).toFixed(2)}`);
    expect(dotted[0]).toHaveAttribute("stroke-linecap", "round");
  });

  it("keeps the same width in mastery colours, where the gradient carries the meaning", () => {
    const plain = render(<KnowledgeGraph2D nodes={NODES} edges={EDGES} width={500} height={400} />);
    const widths = edgesOf(plain.container).map((e) => e.getAttribute("stroke-width"));
    cleanup();
    const mastery = render(
      <KnowledgeGraph2D nodes={NODES} edges={EDGES} width={500} height={400} colorMode="mastery" />,
    );
    expect(edgesOf(mastery.container).map((e) => e.getAttribute("stroke-width"))).toEqual(widths);
    for (const e of edgesOf(mastery.container)) expect(e.getAttribute("stroke")).toMatch(/^url\(#/);
  });

  it("gives directed links an arrowhead in legible mode, sized in the graph's own units", () => {
    // Arrowheads show from 0.9× up: a window the whole graph fits in at 1×.
    const { container } = render(
      <KnowledgeGraph2D nodes={NODES} edges={EDGES} width={1200} height={900} legible />,
    );
    const arrowed = edgesOf(container).filter((e) => e.hasAttribute("marker-end"));
    // prerequisite and builds_on; `related` and the course's own links carry none.
    expect(arrowed).toHaveLength(2);
    for (const marker of container.querySelectorAll("marker")) {
      // A marker scaled by the stroke would grow with the bar's width.
      expect(marker).toHaveAttribute("markerUnits", "userSpaceOnUse");
      expect(Number(marker.getAttribute("markerWidth"))).toBe(ARROW_SIZE);
      expect(Number(marker.getAttribute("markerHeight"))).toBe(ARROW_SIZE);
      expect(Number(marker.getAttribute("refX"))).toBe(ARROW_REF_X);
    }
  });
});
