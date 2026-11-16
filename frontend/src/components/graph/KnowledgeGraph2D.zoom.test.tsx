// @vitest-environment jsdom
/**
 * `initialZoom`: the zoom a graph opens and resets at, framed on its nodes
 * where they come to rest. Quiz home's live neighbourhood uses it so a small
 * fragment fills its frame; every other caller keeps the default.
 */

import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import type { GraphEdge, GraphNode } from "@/lib/data";
import { KnowledgeGraph2D } from "./KnowledgeGraph2D";

afterEach(cleanup);

const NODES: GraphNode[] = [
  { id: "a", name: "Limits", subject: "Math", color: "#7a874f", mastery_tier: "learning", mastery_score: 0.4, course_id: "c1" },
  { id: "b", name: "Derivatives", subject: "Math", color: "#7a874f", mastery_tier: "struggling", mastery_score: 0.2, course_id: "c1" },
];
const EDGES: GraphEdge[] = [{ source: "a", target: "b", strength: 0.6 }];

/** The pan/zoom group's transform — the only `<g>` carrying a scale. */
const viewTransform = (container: HTMLElement) =>
  Array.from(container.querySelectorAll("g"))
    .map(g => g.getAttribute("transform") ?? "")
    .find(t => t.includes("scale("));

/**
 * The view, and where the nodes' frame (each mark with the room a frame
 * keeps round it: 24 past it, 10 more under it for the caption) shows in
 * the window.
 */
function framed(container: HTMLElement) {
  const m = /translate\(([-\d.e]+), ([-\d.e]+)\) scale\(([-\d.e]+)\)/.exec(viewTransform(container) ?? "")!;
  const [tx, ty, scale] = [Number(m[1]), Number(m[2]), Number(m[3])];
  let [left, right, top, bottom] = [Infinity, -Infinity, Infinity, -Infinity];
  for (const g of container.querySelectorAll('[data-testid="graph-node"]')) {
    const [, x, y] = /translate\(([-\d.e]+),\s*([-\d.e]+)\)/.exec(g.getAttribute("transform")!)!;
    const r = Number(g.querySelector('[data-testid="graph-node-circle"]')!.getAttribute("data-r"));
    left = Math.min(left, (Number(x) - r - 24) * scale + tx);
    right = Math.max(right, (Number(x) + r + 24) * scale + tx);
    top = Math.min(top, (Number(y) - r - 24) * scale + ty);
    bottom = Math.max(bottom, (Number(y) + r + 34) * scale + ty);
  }
  return { scale, left, right, top, bottom };
}

describe("KnowledgeGraph2D — initialZoom", () => {
  it("defaults to the identity view", () => {
    const { container } = render(<KnowledgeGraph2D nodes={NODES} edges={EDGES} width={400} height={300} />);
    expect(viewTransform(container)).toBe("translate(0, 0) scale(1)");
  });

  it("opens zoomed, framed on where its nodes rest", () => {
    // A window the two-node fragment fits in at 2×. (These tests run with
    // reduced motion, where the graph is settled before it is drawn: it is
    // framed at once, as it is for everyone else.)
    const { container } = render(
      <KnowledgeGraph2D nodes={NODES} edges={EDGES} width={800} height={600} initialZoom={2} />,
    );
    const f = framed(container);
    expect(f.scale).toBe(2);
    // The nodes' frame sits in the middle of the window.
    expect((f.left + f.right) / 2).toBeCloseTo(400, 4);
    expect((f.top + f.bottom) / 2).toBeCloseTo(300, 4);
  });

  it("opens a fragment too large for its window at the opening zoom further out, all of it showing", () => {
    const { container } = render(
      <KnowledgeGraph2D nodes={NODES} edges={EDGES} width={260} height={200} initialZoom={2} />,
    );
    const f = framed(container);
    expect(f.scale).toBeLessThan(2);
    expect(f.left).toBeGreaterThanOrEqual(-1e-6);
    expect(f.right).toBeLessThanOrEqual(260 + 1e-6);
    expect(f.top).toBeGreaterThanOrEqual(-1e-6);
    expect(f.bottom).toBeLessThanOrEqual(200 + 1e-6);
  });

  it("resets to the opening zoom, framed on the nodes, not to 1", () => {
    // A window the two-node fragment fits in at 2×.
    const { container } = render(
      <KnowledgeGraph2D nodes={NODES} edges={EDGES} width={800} height={600} initialZoom={2} />,
    );
    fireEvent.click(screen.getByTestId("graph-zoom-out"));
    expect(viewTransform(container)).toMatch(/scale\(1\.6\)$/);
    fireEvent.click(screen.getByTestId("graph-zoom-reset"));
    // The opening zoom again, centred on where the nodes are rather than on
    // the window (a fragment centred on the window sat off to one side).
    expect(viewTransform(container)).toMatch(/scale\(2\)$/);
  });

  it("resets a fragment too wide for its window to the largest zoom that shows all of it", () => {
    // Measure the pair once, in a roomy window: the marks with the margin a
    // frame keeps round them (24 past each mark, 10 more under it for the
    // caption).
    const roomy = render(<KnowledgeGraph2D nodes={NODES} edges={EDGES} width={1000} height={800} />);
    let minX = Infinity;
    let maxX = -Infinity;
    let minY = Infinity;
    let maxY = -Infinity;
    for (const g of roomy.container.querySelectorAll('[data-testid="graph-node"]')) {
      const [, x, y] = /translate\(([-\d.e]+),\s*([-\d.e]+)\)/.exec(g.getAttribute("transform")!)!;
      const r = Number(g.querySelector('[data-testid="graph-node-circle"]')!.getAttribute("data-r"));
      minX = Math.min(minX, Number(x) - r - 24);
      maxX = Math.max(maxX, Number(x) + r + 24);
      minY = Math.min(minY, Number(y) - r - 24);
      maxY = Math.max(maxY, Number(y) + r + 34);
    }
    cleanup();
    // A window that holds it at about one and a half times: at 2× the two
    // nodes and their captions would not fit, so the reset stops short of the
    // opening zoom rather than cutting a node off.
    const w = Math.round((maxX - minX) * 1.5);
    const h = Math.round((maxY - minY) * 1.5);
    const { container } = render(
      <KnowledgeGraph2D nodes={NODES} edges={EDGES} width={w} height={h} initialZoom={2} />,
    );
    fireEvent.click(screen.getByTestId("graph-zoom-out"));
    fireEvent.click(screen.getByTestId("graph-zoom-reset"));
    const m = /translate\(([-\d.e]+), ([-\d.e]+)\) scale\(([-\d.e]+)\)/.exec(viewTransform(container) ?? "")!;
    const [tx, ty, scale] = [Number(m[1]), Number(m[2]), Number(m[3])];
    expect(scale).toBeGreaterThan(1);
    expect(scale).toBeLessThan(2);
    const nodes = Array.from(container.querySelectorAll('[data-testid="graph-node"]'));
    expect(nodes).toHaveLength(2);
    let left = Infinity;
    let right = -Infinity;
    for (const g of nodes) {
      const [, x, y] = /translate\(([-\d.e]+),\s*([-\d.e]+)\)/.exec(g.getAttribute("transform")!)!;
      const r = Number(g.querySelector('[data-testid="graph-node-circle"]')!.getAttribute("data-r"));
      const sx = Number(x) * scale + tx;
      const sy = Number(y) * scale + ty;
      // The whole mark is inside the window.
      expect(sx - r * scale).toBeGreaterThanOrEqual(0);
      expect(sx + r * scale).toBeLessThanOrEqual(w);
      expect(sy - r * scale).toBeGreaterThanOrEqual(0);
      expect(sy + r * scale).toBeLessThanOrEqual(h);
      left = Math.min(left, sx - r * scale);
      right = Math.max(right, sx + r * scale);
    }
    // …and the pair, edge to edge, is centred in it.
    expect((left + right) / 2).toBeCloseTo(w / 2, 4);
  });

  it("zooms the buttons about the window's centre, not the content's origin", () => {
    const { container } = render(
      <KnowledgeGraph2D nodes={NODES} edges={EDGES} width={400} height={300} initialZoom={2} />,
    );
    const parse = () => {
      const m = /translate\(([-\d.e]+), ([-\d.e]+)\) scale\(([-\d.e]+)\)/.exec(viewTransform(container) ?? "")!;
      return { tx: Number(m[1]), ty: Number(m[2]), s: Number(m[3]) };
    };
    const before = parse();
    fireEvent.click(screen.getByTestId("graph-zoom-out"));
    const after = parse();
    expect(after.s).toBeCloseTo(before.s / 1.25, 6);
    // The content point under the window's centre (200, 150) stays put.
    expect((200 - after.tx) / after.s).toBeCloseTo((200 - before.tx) / before.s, 4);
    expect((150 - after.ty) / after.s).toBeCloseTo((150 - before.ty) / before.s, 4);
  });

  it("keeps the student's own pan/zoom when the window is re-measured", () => {
    const view = render(
      <KnowledgeGraph2D nodes={NODES} edges={EDGES} width={400} height={300} initialZoom={2} />,
    );
    fireEvent.click(screen.getByTestId("graph-zoom-out"));
    const moved = viewTransform(view.container);
    view.rerender(<KnowledgeGraph2D nodes={NODES} edges={EDGES} width={600} height={340} initialZoom={2} />);
    expect(viewTransform(view.container)).toBe(moved);
  });

  it("re-centres when the window is measured to a new size", () => {
    const view = render(
      <KnowledgeGraph2D nodes={NODES} edges={EDGES} width={800} height={600} initialZoom={2} />,
    );
    view.rerender(<KnowledgeGraph2D nodes={NODES} edges={EDGES} width={900} height={640} initialZoom={2} />);
    const f = framed(view.container);
    expect(f.scale).toBe(2);
    expect((f.left + f.right) / 2).toBeCloseTo(450, 4);
    expect((f.top + f.bottom) / 2).toBeCloseTo(320, 4);
  });
});
