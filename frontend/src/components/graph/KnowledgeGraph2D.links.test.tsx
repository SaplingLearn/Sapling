// @vitest-environment jsdom
/**
 * Links run rim to rim: no line is drawn underneath a node. Node fills are
 * translucent (tier opacity, legible fades), so a line to a node's centre
 * showed through it.
 */

import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render } from "@testing-library/react";
import React from "react";
import type { GraphEdge, GraphNode } from "@/lib/data";
import { KnowledgeGraph2D } from "./KnowledgeGraph2D";

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

function nodeDiscs(container: HTMLElement) {
  return Array.from(container.querySelectorAll<SVGGElement>('[data-testid="graph-node"]')).map((g) => {
    const [, x, y] = /translate\(([-\d.e]+),\s*([-\d.e]+)\)/.exec(g.getAttribute("transform")!)!;
    const r = Number(g.querySelector('[data-testid="graph-node-circle"]')!.getAttribute("r"));
    return { id: g.getAttribute("data-node-id"), x: Number(x), y: Number(y), r };
  });
}

describe.each([
  ["plain", {}],
  ["legible", { legible: true }],
  ["mastery colours", { colorMode: "mastery" as const }],
])("KnowledgeGraph2D links (%s)", (_name, props) => {
  it("never draws a link endpoint inside a node", () => {
    const { container } = render(
      <KnowledgeGraph2D nodes={NODES} edges={EDGES} width={500} height={400} {...props} />,
    );
    const discs = nodeDiscs(container);
    const edges = Array.from(container.querySelectorAll('[data-testid="graph-edge"]'));
    expect(edges.length).toBeGreaterThan(0);
    for (const e of edges) {
      const ends = [
        [Number(e.getAttribute("x1")), Number(e.getAttribute("y1"))],
        [Number(e.getAttribute("x2")), Number(e.getAttribute("y2"))],
      ];
      if (ends[0][0] === ends[1][0] && ends[0][1] === ends[1][1]) continue; // touching nodes: nothing drawn
      for (const [x, y] of ends) {
        for (const d of discs) {
          expect(Math.hypot(x - d.x, y - d.y), `edge end inside ${d.id}`).toBeGreaterThanOrEqual(d.r);
        }
      }
    }
  });
});
