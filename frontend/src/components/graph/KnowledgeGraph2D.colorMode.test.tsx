// @vitest-environment jsdom
/**
 * `colorMode`: `course` (default) paints course colours with the tier as
 * opacity; `mastery` paints one fixed colour per tier, hubs brown, fully
 * opaque, with each edge a gradient between its endpoints' colours.
 */

import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render } from "@testing-library/react";
import React from "react";
import type { GraphEdge, GraphNode } from "@/lib/data";
import { MASTERY_PALETTE, TIER_OPACITY } from "@/lib/graph/nodeStyle";
import { KnowledgeGraph2D } from "./KnowledgeGraph2D";

afterEach(cleanup);

const NODES: GraphNode[] = [
  { id: "hub", name: "CAS LX 250", subject: "Ling", color: "#3e6f8a", mastery_tier: "mastered", mastery_score: 0, course_id: "c1", is_subject_root: true },
  { id: "m", name: "Phonemes", subject: "Ling", color: "#3e6f8a", mastery_tier: "mastered", mastery_score: 0.9, course_id: "c1" },
  { id: "l", name: "Morphology", subject: "Ling", color: "#3e6f8a", mastery_tier: "learning", mastery_score: 0.5, course_id: "c1" },
  { id: "s", name: "Syntax", subject: "Ling", color: "#3e6f8a", mastery_tier: "struggling", mastery_score: 0.2, course_id: "c1" },
  { id: "u", name: "Semantics", subject: "Ling", color: "#3e6f8a", mastery_tier: "unexplored", mastery_score: 0, course_id: "c1" },
];
const EDGES: GraphEdge[] = [
  { source: "hub", target: "m", strength: 0.7 },
  { source: "m", target: "s", strength: 0.7 },
];

const circle = (c: HTMLElement, id: string) =>
  c.querySelector(`[data-testid="graph-node"][data-node-id="${id}"] [data-testid="graph-node-circle"]`)!;

describe("KnowledgeGraph2D — colorMode", () => {
  it("defaults to course colours with the tier as opacity", () => {
    const { container } = render(<KnowledgeGraph2D nodes={NODES} edges={EDGES} width={400} height={300} />);
    expect(container.querySelector("svg[role=img]")!.getAttribute("data-color-mode")).toBe("course");
    expect(circle(container, "hub").getAttribute("fill")).toBe("#3e6f8a");
    expect(circle(container, "s").getAttribute("fill")).toMatch(/^hsl\(/);
    expect(Number(circle(container, "s").getAttribute("opacity"))).toBe(TIER_OPACITY.struggling);
    expect(container.querySelectorAll("linearGradient")).toHaveLength(0);
    // Each link is a flat bar of its course's colour: the course's own, not a
    // node's shade of it, so every link in a course is the same colour.
    const edges = container.querySelectorAll('[data-testid="graph-edge"]');
    expect(edges.length).toBeGreaterThan(0);
    for (const e of edges) {
      expect(e.getAttribute("stroke")).toBe("#3e6f8a");
    }
  });

  it("paints each node one flat colour: a single filled outline, no rim at rest", () => {
    const { container } = render(<KnowledgeGraph2D nodes={NODES} edges={EDGES} width={400} height={300} />);
    for (const n of NODES) {
      const group = container.querySelector(`[data-testid="graph-node"][data-node-id="${n.id}"]`)!;
      const mark = circle(container, n.id);
      expect(mark.tagName.toLowerCase()).toBe("path");
      expect(mark.getAttribute("fill")).not.toMatch(/^url\(/);
      // The rim is the fill's own colour and invisible until hovered or dragged.
      expect(mark.getAttribute("stroke")).toBe(mark.getAttribute("fill"));
      expect(Number(mark.getAttribute("stroke-opacity"))).toBe(0);
      expect(mark).not.toHaveAttribute("filter");
      // Nothing else is painted under or over it: no glow, no second tone.
      expect(group.querySelectorAll("circle, ellipse, image, path")).toHaveLength(1);
    }
    expect(container.querySelector("filter, pattern, radialGradient, image")).toBeNull();
  });

  it("falls back to the sage token for a link whose course has no colour", () => {
    const bare = NODES.map((n) => ({ ...n, color: "" }));
    const { container } = render(<KnowledgeGraph2D nodes={bare} edges={EDGES} width={400} height={300} />);
    for (const e of container.querySelectorAll('[data-testid="graph-edge"]')) {
      expect(e.getAttribute("stroke")).toBe("var(--c-sage)");
    }
  });

  it("mastery mode paints each tier its palette colour, hubs brown, all fully opaque", () => {
    const { container } = render(
      <KnowledgeGraph2D nodes={NODES} edges={EDGES} width={400} height={300} colorMode="mastery" />,
    );
    expect(container.querySelector("svg[role=img]")!.getAttribute("data-color-mode")).toBe("mastery");
    const expected: Record<string, string> = {
      hub: MASTERY_PALETTE.hub,
      m: MASTERY_PALETTE.mastered,
      l: MASTERY_PALETTE.learning,
      s: MASTERY_PALETTE.struggling,
      u: MASTERY_PALETTE.unexplored,
    };
    for (const [id, fill] of Object.entries(expected)) {
      expect(circle(container, id).getAttribute("fill")).toBe(fill);
      expect(Number(circle(container, id).getAttribute("opacity"))).toBe(1);
    }
  });

  it("mastery mode draws each edge as a gradient from its source's colour to its target's", () => {
    const { container } = render(
      <KnowledgeGraph2D nodes={NODES} edges={EDGES} width={400} height={300} colorMode="mastery" />,
    );
    // The /api/graph spoke (hub → m) is not drawn: the course links to its
    // inner-circle concepts instead — here all four, since m → s carries no
    // prerequisite type — and then the one concept edge.
    const edges = Array.from(container.querySelectorAll('[data-testid="graph-edge"]'));
    expect(edges).toHaveLength(5);
    const stops = edges.map((e) => {
      const id = /^url\(#(.+)\)$/.exec(e.getAttribute("stroke")!)![1];
      const grad = container.querySelector(`linearGradient[id="${id}"]`)!;
      // The gradient spans the line in user space, so it tracks the edge.
      expect(grad.getAttribute("gradientUnits")).toBe("userSpaceOnUse");
      expect(grad.getAttribute("x1")).toBe(e.getAttribute("x1"));
      expect(grad.getAttribute("y2")).toBe(e.getAttribute("y2"));
      return Array.from(grad.querySelectorAll("stop")).map((s) => s.getAttribute("stop-color"));
    });
    expect(stops).toEqual([
      [MASTERY_PALETTE.hub, MASTERY_PALETTE.mastered],
      [MASTERY_PALETTE.hub, MASTERY_PALETTE.learning],
      [MASTERY_PALETTE.hub, MASTERY_PALETTE.struggling],
      [MASTERY_PALETTE.hub, MASTERY_PALETTE.unexplored],
      [MASTERY_PALETTE.mastered, MASTERY_PALETTE.struggling],
    ]);
  });

  it("gives two graphs on one page distinct gradient ids", () => {
    const { container } = render(
      <>
        <KnowledgeGraph2D nodes={NODES} edges={EDGES} width={400} height={300} colorMode="mastery" />
        <KnowledgeGraph2D nodes={NODES} edges={EDGES} width={400} height={300} colorMode="mastery" />
      </>,
    );
    const ids = Array.from(container.querySelectorAll("linearGradient")).map((g) => g.id);
    expect(ids).toHaveLength(10);
    expect(new Set(ids).size).toBe(10);
  });
});
