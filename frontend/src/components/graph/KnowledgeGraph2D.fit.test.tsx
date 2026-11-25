// @vitest-environment jsdom
/**
 * `fit` (PR #866 U4): the Tutor's session panel draws the course's map in a
 * 264 × 240 box. Framed on the plan, concepts the layout pushed outward lost
 * their captions at the panel's edge ("Algorithms" cut at the right). With
 * `fit` the view frames every node AND its whole caption where the nodes
 * rest, never past full size. `zoomControls={false}` leaves the zoom stack off
 * so nothing is drawn over the nodes. Neither changes a graph that does not
 * ask (the Tree, the dashboard).
 *
 * Captions are SVG text and jsdom lays nothing out, so a caption's extent is
 * worked out here from what is drawn — its text, font size and baseline — at
 * 0.6 em a character, independently of the component's own estimate.
 */
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { GraphEdge, GraphNode } from "@/lib/data";
import { KnowledgeGraph2D } from "./KnowledgeGraph2D";

afterEach(cleanup);

const W = 264;
const H = 240;

const ROOT: GraphNode = {
  id: "root",
  name: "CS 111 - Introduction to Programming",
  subject: "CS",
  color: "#7a874f",
  mastery_tier: "unexplored",
  mastery_score: 0,
  course_id: "c1",
  is_subject_root: true,
};
const NAMES = ["Variables and Types", "Algorithms", "Control Flow and Loops", "Functions"];
const TIERS = ["mastered", "learning", "struggling", "unexplored"] as const;
const SCORES = [0.96, 0.8, 0.2, 0];

/** A course of `n` concepts round its hub; `chain` adds a prerequisite chain. */
function course(n: number, chain: boolean): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const concepts: GraphNode[] = Array.from({ length: n }, (_, i) => ({
    id: `c${i}`,
    name: NAMES[i % NAMES.length] + (i >= NAMES.length ? ` ${i}` : ""),
    subject: "CS",
    color: "#7a874f",
    mastery_tier: TIERS[i % 4],
    mastery_score: SCORES[i % 4],
    course_id: "c1",
  }));
  return {
    nodes: [ROOT, ...concepts],
    edges: [
      // the backend's hub spokes
      ...concepts.map((c) => ({ source: ROOT.id, target: c.id, strength: 0.7 })),
      ...(chain
        ? concepts.slice(1).map((c, i) => ({ source: concepts[i].id, target: c.id, strength: 0.6, relationship_type: "prerequisite" as const }))
        : []),
    ],
  };
}
const { nodes: NODES, edges: EDGES } = course(10, false);

function view(container: HTMLElement) {
  const t = Array.from(container.querySelectorAll("g"))
    .map((g) => g.getAttribute("transform") ?? "")
    .find((s) => s.includes("scale("))!;
  const m = /translate\(([-\d.e]+), ([-\d.e]+)\) scale\(([-\d.e]+)\)/.exec(t)!;
  return { tx: Number(m[1]), ty: Number(m[2]), scale: Number(m[3]) };
}

/** Every node's mark and caption, on screen. */
function drawn(container: HTMLElement) {
  const { tx, ty, scale } = view(container);
  return Array.from(container.querySelectorAll<SVGGElement>('[data-testid="graph-node"]')).map((g) => {
    const [, x, y] = /translate\(([-\d.e]+),\s*([-\d.e]+)\)/.exec(g.getAttribute("transform")!)!.map(Number);
    const r = Number(g.querySelector('[data-testid="graph-node-circle"]')!.getAttribute("data-r"));
    const text = g.querySelector("text")!;
    const size = Number(text.getAttribute("font-size"));
    const half = (text.textContent!.length * size * 0.6) / 2;
    const foot = Number(text.getAttribute("y")) + size * 0.3;
    return {
      caption: text.textContent!,
      left: (x - Math.max(r, half)) * scale + tx,
      right: (x + Math.max(r, half)) * scale + tx,
      top: (y - r) * scale + ty,
      bottom: (y + foot) * scale + ty,
    };
  });
}

describe("KnowledgeGraph2D — fit", () => {
  // Sizes where the planned view (no `fit`) cuts a caption at the edge by a
  // few pixels in this harness — and by more in a browser, where the layout
  // settles further from the plan.
  it.each([
    [3, true],
    [6, true],
    [10, false],
    [24, false],
  ])("keeps every node and its whole caption inside a small window (%i concepts, chain %s)", (n, chain) => {
    const { nodes, edges } = course(n, chain);
    const { container } = render(<KnowledgeGraph2D nodes={nodes} edges={edges} width={W} height={H} fit />);
    const boxes = drawn(container);
    expect(boxes).toHaveLength(nodes.length);
    for (const b of boxes) {
      expect(b.left, b.caption).toBeGreaterThanOrEqual(0);
      expect(b.right, b.caption).toBeLessThanOrEqual(W);
      expect(b.top, b.caption).toBeGreaterThanOrEqual(0);
      expect(b.bottom, b.caption).toBeLessThanOrEqual(H);
    }
    // framed, not merely shrunk: the content is centred in the window
    const left = Math.min(...boxes.map((b) => b.left));
    const right = Math.max(...boxes.map((b) => b.right));
    expect(Math.abs((left + right) / 2 - W / 2)).toBeLessThan(W * 0.1);
  });

  it("never zooms a graph that fits past full size", () => {
    const { container } = render(<KnowledgeGraph2D nodes={[NODES[2]]} edges={[]} width={800} height={600} fit />);
    expect(view(container).scale).toBe(1);
  });

  it("re-frames when the reset button is pressed", () => {
    const { container } = render(<KnowledgeGraph2D nodes={NODES} edges={EDGES} width={W} height={H} fit />);
    const framed = view(container);
    fireEvent.click(screen.getByTestId("graph-zoom-in"));
    expect(view(container).scale).toBeGreaterThan(framed.scale);
    fireEvent.click(screen.getByTestId("graph-zoom-reset"));
    expect(view(container)).toEqual(framed);
  });
});

describe("KnowledgeGraph2D — the panel map's zoom and its auto-fit (PR #866 U4 review)", () => {
  const panel = (nodes = NODES, edges = EDGES) => (
    <KnowledgeGraph2D nodes={nodes} edges={edges} width={W} height={H} fit zoomControls={false} wheelZoom="pinch" />
  );
  const svg = () => screen.getByRole("img", { name: "Knowledge map" });

  it("a plain wheel (scrolling the panel) leaves the frame alone", () => {
    const { container } = render(panel());
    const framed = view(container);
    fireEvent.wheel(svg(), { deltaY: 120, clientX: W / 2, clientY: H / 2 });
    expect(view(container)).toEqual(framed);
  });

  it("a pinch zooms and the auto-fit lets it stand; a double-click re-frames", () => {
    const { container } = render(panel());
    const framed = view(container);
    fireEvent.wheel(svg(), { deltaY: -120, ctrlKey: true, clientX: W / 2, clientY: H / 2 });
    const zoomed = view(container);
    expect(zoomed.scale).toBeGreaterThan(framed.scale);
    fireEvent.doubleClick(svg());
    expect(view(container)).toEqual(framed);
  });

  it("a new set of concepts is framed again after the student zoomed", () => {
    const { container, rerender } = render(panel());
    fireEvent.wheel(svg(), { deltaY: -120, ctrlKey: true, clientX: W / 2, clientY: H / 2 });
    const zoomed = view(container);
    const { nodes, edges } = course(4, true);
    rerender(panel(nodes, edges));
    expect(view(container)).not.toEqual(zoomed);
    for (const b of drawn(container)) {
      expect(b.left, b.caption).toBeGreaterThanOrEqual(0);
      expect(b.right, b.caption).toBeLessThanOrEqual(W);
    }
  });

  it("a graph with its zoom stack keeps the wheel and no double-click reset (the Tree)", () => {
    const { container } = render(<KnowledgeGraph2D nodes={NODES} edges={EDGES} width={W} height={H} fit />);
    const framed = view(container);
    fireEvent.wheel(svg(), { deltaY: -120, clientX: W / 2, clientY: H / 2 });
    const zoomed = view(container);
    expect(zoomed.scale).toBeGreaterThan(framed.scale);
    fireEvent.doubleClick(svg());
    expect(view(container)).toEqual(zoomed);
  });
});

describe("KnowledgeGraph2D — zoomControls", () => {
  it("draws the zoom stack unless asked not to", () => {
    const { rerender } = render(<KnowledgeGraph2D nodes={NODES} edges={EDGES} width={W} height={H} />);
    expect(screen.getByTestId("graph-zoom-controls")).toBeTruthy();
    rerender(<KnowledgeGraph2D nodes={NODES} edges={EDGES} width={W} height={H} zoomControls={false} />);
    expect(screen.queryByTestId("graph-zoom-controls")).toBeNull();
  });

  it("leaves a graph that does not ask to fit on its planned view", () => {
    const { container } = render(<KnowledgeGraph2D nodes={[NODES[2]]} edges={[]} width={400} height={300} />);
    expect(view(container)).toEqual({ tx: 0, ty: 0, scale: 1 });
  });
});
