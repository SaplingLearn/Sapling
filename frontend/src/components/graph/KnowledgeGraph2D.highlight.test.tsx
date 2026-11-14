// @vitest-environment jsdom
/**
 * The rings drawn round a node: the pulsing highlight (`highlightId`) and the
 * dashed comparison ring (`comparison`). Both follow the node's own
 * hand-drawn outline, not a circle round it.
 *
 * The highlight ring is also a seam for the browser suite: the capture
 * recipes in `e2e/figma/recipes` wait for an `<animate>` inside the
 * highlighted node's group to know the highlight has landed.
 */

import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render } from "@testing-library/react";
import React from "react";
import type { GraphEdge, GraphNode } from "@/lib/data";
import { nodeBlobPath, wobbleFor } from "@/lib/graph/blobShape";
import { KnowledgeGraph2D } from "./KnowledgeGraph2D";

afterEach(cleanup);

const node = (id: string, score: number, extra: Partial<GraphNode> = {}): GraphNode => ({
  id, name: id, subject: "Ling", color: "#3e6f8a", mastery_tier: "learning", mastery_score: score, course_id: "c1", ...extra,
});
const NODES: GraphNode[] = [
  node("hub", 0, { name: "CAS LX 250", is_subject_root: true }),
  node("a", 0.9, { name: "Phonemes" }),
  node("b", 0.5, { name: "Morphology" }),
  node("c", 0.2, { name: "Syntax" }),
];
const EDGES: GraphEdge[] = [{ source: "a", target: "b", strength: 0.6, relationship_type: "prerequisite" }];

const group = (c: HTMLElement, id: string) => c.querySelector(`[data-testid="graph-node"][data-node-id="${id}"]`)!;
const mark = (c: HTMLElement, id: string) => group(c, id).querySelector('[data-testid="graph-node-circle"]')!;

describe("KnowledgeGraph2D — the highlight ring", () => {
  it("draws no ring when nothing is highlighted", () => {
    const { container } = render(<KnowledgeGraph2D nodes={NODES} edges={EDGES} width={600} height={480} />);
    expect(container.querySelector('[data-testid="graph-node-highlight"]')).toBeNull();
    expect(container.querySelector("animate, animateTransform")).toBeNull();
  });

  it("rings the highlighted node, and only it, with its own outline", () => {
    const { container } = render(
      <KnowledgeGraph2D nodes={NODES} edges={EDGES} width={600} height={480} highlightId="b" />,
    );
    const rings = container.querySelectorAll('[data-testid="graph-node-highlight"]');
    expect(rings).toHaveLength(1);
    const ring = rings[0];
    expect(group(container, "b").contains(ring)).toBe(true);
    // The node's own shape, 8 units out: radiusFor(0.5) = 14.
    const r = Number(mark(container, "b").getAttribute("data-r"));
    expect(r).toBe(14);
    expect(ring.tagName.toLowerCase()).toBe("path");
    expect(ring).toHaveAttribute("d", nodeBlobPath("b", r + 8, wobbleFor(r)));
    expect(ring).toHaveAttribute("fill", "none");
    expect(ring).toHaveAttribute("stroke", mark(container, "b").getAttribute("fill")!);
    // Drawn under the mark, so the mark stays the thing you click.
    const kids = Array.from(group(container, "b").children);
    expect(kids.indexOf(ring)).toBeLessThan(kids.indexOf(mark(container, "b")));
  });

  it("breathes: out and fainter, then back", () => {
    const { container } = render(
      <KnowledgeGraph2D nodes={NODES} edges={EDGES} width={600} height={480} highlightId="b" />,
    );
    const ring = container.querySelector('[data-testid="graph-node-highlight"]')!;
    const grow = ring.querySelector("animateTransform")!;
    expect(grow).toHaveAttribute("type", "scale");
    expect(grow).toHaveAttribute("repeatCount", "indefinite");
    // From 5 units past the node to 11 and back, as scales of the ring drawn at 8.
    const scales = grow.getAttribute("values")!.split(";").map(Number);
    expect(scales).toHaveLength(3);
    expect(scales[0]).toBeCloseTo((14 + 5) / (14 + 8), 3);
    expect(scales[1]).toBeCloseTo((14 + 11) / (14 + 8), 3);
    expect(scales[2]).toBe(scales[0]);
    const fade = ring.querySelector("animate")!;
    expect(fade).toHaveAttribute("attributeName", "opacity");
    expect(fade.getAttribute("dur")).toBe(grow.getAttribute("dur"));
  });

  it("keeps an `<animate>` inside the highlighted node's group, the browser suite's signal", () => {
    // e2e/figma/recipes waits on exactly this selector.
    const { container } = render(
      <KnowledgeGraph2D nodes={NODES} edges={EDGES} width={600} height={480} highlightId="b" />,
    );
    expect(container.querySelectorAll('[data-testid="graph-node"][data-node-id="b"] animate')).toHaveLength(1);
    expect(container.querySelector('[data-testid="graph-node"][data-node-id="a"] animate')).toBeNull();
    for (const variant of ["orb", "constellation"] as const) {
      cleanup();
      const other = render(
        <KnowledgeGraph2D nodes={NODES} edges={EDGES} width={600} height={480} highlightId="b" variant={variant} />,
      );
      expect(other.container.querySelectorAll('[data-testid="graph-node"][data-node-id="b"] animate')).toHaveLength(1);
      expect(other.container.querySelector('[data-testid="graph-node-highlight"]')!.tagName.toLowerCase()).toBe("circle");
    }
  });

  it("moves with the highlight", () => {
    const shown = render(<KnowledgeGraph2D nodes={NODES} edges={EDGES} width={600} height={480} highlightId="b" />);
    shown.rerender(<KnowledgeGraph2D nodes={NODES} edges={EDGES} width={600} height={480} highlightId="c" />);
    expect(group(shown.container, "b").querySelector('[data-testid="graph-node-highlight"]')).toBeNull();
    expect(group(shown.container, "c").querySelector('[data-testid="graph-node-highlight"]')).not.toBeNull();
  });
});

describe("KnowledgeGraph2D — the comparison ring", () => {
  const COMPARISON = [{ name: " phonemes ", mastery_score: 0.6 }, { name: "CAS LX 250", mastery_score: 1 }];

  it("draws a dashed outline round each concept the other student has, sized by their mastery", () => {
    const { container } = render(
      <KnowledgeGraph2D nodes={NODES} edges={EDGES} width={600} height={480} comparison={COMPARISON} comparisonLabel="Sam" />,
    );
    const dashed = Array.from(container.querySelectorAll("path[stroke-dasharray]"));
    // Matched by name, whatever its case or padding; never drawn on a course root.
    expect(dashed).toHaveLength(1);
    const ring = dashed[0];
    expect(group(container, "a").contains(ring)).toBe(true);
    const r = Number(mark(container, "a").getAttribute("data-r"));
    expect(ring).toHaveAttribute("d", nodeBlobPath("a", r + 4 + 0.6 * 5, wobbleFor(r)));
    expect(ring).toHaveAttribute("fill", "none");
    expect(Number(ring.getAttribute("opacity"))).toBeCloseTo(0.35 + 0.6 * 0.55, 10);
    expect(ring.querySelector("title")!.textContent).toBe("Sam: 60% mastery on Phonemes");
  });

  it("names nobody when no label is given", () => {
    const { container } = render(
      <KnowledgeGraph2D nodes={NODES} edges={EDGES} width={600} height={480} comparison={COMPARISON} />,
    );
    expect(container.querySelector("path[stroke-dasharray] title")!.textContent).toBe("60% mastery on Phonemes");
  });
});
