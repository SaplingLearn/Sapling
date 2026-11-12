// @vitest-environment jsdom
/**
 * Where the graph's nodes settle, and how the opening view frames them.
 *
 * The plan (`lib/graph/radialLayout`) seats every concept with room for its
 * caption; the simulation is only allowed to loosen that a little. These
 * tests read the settled positions off the DOM, so they hold the two
 * together: a retuned force that swells a course past its planned space, or
 * bunches concepts up, fails here.
 *
 * The shared setup stubs `matchMedia` to reduced motion, so the simulation
 * settles synchronously before the first paint.
 */

import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import type { GraphEdge, GraphNode } from "@/lib/data";
import { RING_REACH, planBounds, planRadial, splitEdges } from "@/lib/graph/radialLayout";
import { KnowledgeGraph2D } from "./KnowledgeGraph2D";

afterEach(cleanup);

const COLOURS: Record<string, string> = { c1: "#3e6f8a", c2: "#7a874f", c3: "#7b4b99" };
const root = (course: string, name = `${course.toUpperCase()} 101 - Introduction to it`): GraphNode => ({
  id: `root-${course}`,
  name,
  subject: course,
  color: COLOURS[course],
  mastery_tier: "learning",
  mastery_score: 0,
  course_id: course,
  is_subject_root: true,
});
const concepts = (count: number, course = "c1"): GraphNode[] =>
  Array.from({ length: count }, (_, i) => ({
    id: `${course}-n${i}`,
    name: `Concept ${i}`,
    subject: course,
    color: COLOURS[course],
    mastery_tier: "learning",
    mastery_score: (i % 5) / 5,
    course_id: course,
  }));
const chain = (ids: string[]): GraphEdge[] =>
  ids.slice(1).map((id, i) => ({ source: ids[i], target: id, strength: 0.6, relationship_type: "prerequisite" }));

/** The pan/zoom group's transform — the only `<g>` carrying a scale. */
const viewTransform = (container: HTMLElement) =>
  Array.from(container.querySelectorAll("g"))
    .map((g) => g.getAttribute("transform") ?? "")
    .find((t) => t.includes("scale("))!;
const view = (container: HTMLElement) => {
  const m = /translate\(([-\d.e]+), ([-\d.e]+)\) scale\(([-\d.e]+)\)/.exec(viewTransform(container))!;
  return { tx: Number(m[1]), ty: Number(m[2]), scale: Number(m[3]) };
};

/** Every node's settled position, by id. */
function positions(container: HTMLElement): Map<string, { x: number; y: number }> {
  const out = new Map<string, { x: number; y: number }>();
  for (const g of container.querySelectorAll('[data-testid="graph-node"]')) {
    const [, x, y] = /translate\(([-\d.e]+),\s*([-\d.e]+)\)/.exec(g.getAttribute("transform")!)!;
    out.set(g.getAttribute("data-node-id")!, { x: Number(x), y: Number(y) });
  }
  return out;
}

const dist = (a: { x: number; y: number }, b: { x: number; y: number }) => Math.hypot(a.x - b.x, a.y - b.y);

describe("KnowledgeGraph2D — where concepts settle", () => {
  it("seats thirty unlinked concepts on three rings round their course, not one wide wheel", () => {
    const nodes = [root("c1"), ...concepts(30)];
    const { container } = render(<KnowledgeGraph2D nodes={nodes} edges={[]} width={1240} height={744} />);
    const at = positions(container);
    const centre = at.get("root-c1")!;
    expect(centre).toEqual({ x: 620, y: 372 });
    const radii = nodes.slice(1).map((n) => dist(at.get(n.id)!, centre)).sort((a, b) => a - b);
    // Planned at 96, 164 and 232 (6, 10 and 14 concepts); the simulation lets
    // them ease outward by a few units and no more.
    const near = (r: number) => radii.filter((d) => d >= r - 4 && d <= r + 14).length;
    expect([near(96), near(164), near(232)]).toEqual([6, 10, 14]);
    expect(radii[radii.length - 1]).toBeLessThan(232 + 14);
  });

  it.each([5, 12, 30, 60])("leaves every one of %i concepts room for its caption", (count) => {
    const nodes = [root("c1"), ...concepts(count)];
    const { container } = render(<KnowledgeGraph2D nodes={nodes} edges={[]} width={1240} height={744} />);
    const pts = [...positions(container).entries()];
    let nearest = Infinity;
    for (let i = 0; i < pts.length; i++) {
      for (let j = i + 1; j < pts.length; j++) nearest = Math.min(nearest, dist(pts[i][1], pts[j][1]));
    }
    // The old layout settled neighbours about 50 apart, under each other's captions.
    expect(nearest).toBeGreaterThan(60);
  });

  it("keeps a linked course inside the space planned for it", () => {
    const nodes = [root("c1"), ...concepts(30)];
    const ids = nodes.slice(1).map((n) => n.id);
    const edges = [...chain(ids.slice(0, 9)), ...chain(ids.slice(9, 15)), ...chain([ids[2], ids[20], ids[21]])];
    const { container } = render(<KnowledgeGraph2D nodes={nodes} edges={edges} width={1240} height={744} />);
    const at = positions(container);
    const plan = planRadial(nodes, splitEdges(nodes, edges).concept, 1240, 744);
    const b = planBounds(plan, 1240, 744)!;
    for (const [id, p] of at) {
      expect(p.x, id).toBeGreaterThan(b.minX);
      expect(p.x, id).toBeLessThan(b.maxX);
      expect(p.y, id).toBeGreaterThan(b.minY);
      expect(p.y, id).toBeLessThan(b.maxY);
    }
  });

  it("is as compact for a long prerequisite chain as for unlinked concepts", () => {
    const nodes = [root("c1"), ...concepts(30)];
    const edges = chain(nodes.slice(1).map((n) => n.id));
    const { container } = render(<KnowledgeGraph2D nodes={nodes} edges={edges} width={1240} height={744} />);
    const at = positions(container);
    const centre = at.get("root-c1")!;
    const furthest = Math.max(...nodes.slice(1).map((n) => dist(at.get(n.id)!, centre)));
    // One ring per level put the thirtieth concept some 2,000 units out.
    expect(furthest).toBeLessThan(232 + RING_REACH.x);
    // …so the whole course opens at full size.
    expect(viewTransform(container)).toBe("translate(0, 0) scale(1)");
  });

  it("holds each legible course at its planned centre, however its links pull", () => {
    const nodes = [root("c1"), root("c2"), root("c3"), ...concepts(14, "c1"), ...concepts(20, "c2"), ...concepts(9, "c3")];
    const ids = (c: string) => nodes.filter((n) => !n.is_subject_root && n.course_id === c).map((n) => n.id);
    const edges = [...chain(ids("c1").slice(0, 8)), ...chain(ids("c2").slice(3, 15)), ...chain(ids("c3").slice(0, 4))];
    const { container } = render(<KnowledgeGraph2D nodes={nodes} edges={edges} width={1240} height={744} legible />);
    const at = positions(container);
    const plan = planRadial(nodes, splitEdges(nodes, edges).concept, 1240, 744);
    for (const [id, c] of plan.centers) expect(dist(at.get(id)!, c), id).toBeLessThan(RING_REACH.y);
  });
});

describe("KnowledgeGraph2D — the opening view", () => {
  const SMALL = [root("c1"), ...concepts(5)];
  const BIG = [root("c1"), ...concepts(60)];

  it("opens a graph that fits at full size", () => {
    const { container } = render(<KnowledgeGraph2D nodes={SMALL} edges={[]} width={800} height={600} />);
    expect(viewTransform(container)).toBe("translate(0, 0) scale(1)");
  });

  it("zooms out just far enough to show a graph larger than its window, centred", () => {
    const { container } = render(<KnowledgeGraph2D nodes={BIG} edges={[]} width={600} height={500} />);
    const b = planBounds(planRadial(BIG, [], 600, 500), 600, 500)!;
    const v = view(container);
    expect(v.scale).toBeCloseTo(Math.min(600 / (b.maxX - b.minX), 500 / (b.maxY - b.minY)), 9);
    expect(v.scale).toBeLessThan(1);
    // The planned bounds sit in the middle of the window.
    expect(((b.minX + b.maxX) / 2) * v.scale + v.tx).toBeCloseTo(300, 6);
    expect(((b.minY + b.maxY) / 2) * v.scale + v.ty).toBeCloseTo(250, 6);
  });

  it("goes back to full size when re-measured into a window it fits", () => {
    // A panel is laid out at a placeholder size first, then at its real one.
    // The fit worked out for the placeholder must not outlive it.
    const nodes = [root("c1"), ...concepts(12)];
    const shown = render(<KnowledgeGraph2D nodes={nodes} edges={[]} width={600} height={300} />);
    expect(view(shown.container).scale).toBeLessThan(1);
    shown.rerender(<KnowledgeGraph2D nodes={nodes} edges={[]} width={800} height={660} />);
    expect(viewTransform(shown.container)).toBe("translate(0, 0) scale(1)");
  });

  it("re-fits when re-measured into a different window it still overflows", () => {
    const shown = render(<KnowledgeGraph2D nodes={BIG} edges={[]} width={600} height={500} />);
    const before = view(shown.container).scale;
    shown.rerender(<KnowledgeGraph2D nodes={BIG} edges={[]} width={400} height={300} />);
    const after = view(shown.container);
    expect(after.scale).toBeLessThan(before);
    const b = planBounds(planRadial(BIG, [], 400, 300), 400, 300)!;
    expect(after.scale).toBeCloseTo(Math.min(400 / (b.maxX - b.minX), 300 / (b.maxY - b.minY)), 9);
  });

  it("leaves the student's own zoom alone when the window is re-measured", () => {
    const nodes = [root("c1"), ...concepts(12)];
    const shown = render(<KnowledgeGraph2D nodes={nodes} edges={[]} width={600} height={300} />);
    fireEvent.click(screen.getByTestId("graph-zoom-in"));
    const theirs = viewTransform(shown.container);
    shown.rerender(<KnowledgeGraph2D nodes={nodes} edges={[]} width={800} height={660} />);
    expect(viewTransform(shown.container)).toBe(theirs);
  });

  it("never opens further out than the zoom buttons can go", () => {
    // Far too much for a window this small: the fit stops at the zoom floor.
    const nodes = [root("c1"), root("c2"), ...concepts(40, "c1"), ...concepts(40, "c2")];
    const { container } = render(<KnowledgeGraph2D nodes={nodes} edges={[]} width={120} height={90} />);
    expect(view(container).scale).toBe(0.25);
  });
});

describe("KnowledgeGraph2D — re-planning", () => {
  it.each([
    ["plain", {}],
    ["legible", { legible: true }],
  ])("carries each course to its new place when the window is re-measured (%s)", (_name, props) => {
    const nodes = [root("c1"), root("c2"), root("c3"), ...concepts(10, "c1"), ...concepts(10, "c2"), ...concepts(10, "c3")];
    // Squarish: the courses sit in a ring. Then wide: they sit in a row.
    const shown = render(<KnowledgeGraph2D nodes={nodes} edges={[]} width={700} height={700} {...props} />);
    const before = positions(shown.container);
    shown.rerender(<KnowledgeGraph2D nodes={nodes} edges={[]} width={2000} height={500} {...props} />);
    const after = positions(shown.container);
    const plan = planRadial(nodes, [], 2000, 500);
    // The plan really did move them a long way.
    const first = planRadial(nodes, [], 700, 700);
    expect(dist(first.centers.get("root-c3")!, plan.centers.get("root-c3")!)).toBeGreaterThan(400);
    for (const [id, centre] of plan.centers) {
      // Left to the springs, a course stopped well short of a far-off new home.
      expect(dist(after.get(id)!, centre), id).toBeLessThan(6);
      // …and its concepts came with it, each where it sat round its course.
      const course = id.replace("root-", "");
      for (const n of nodes.filter((m) => !m.is_subject_root && m.course_id === course)) {
        const was = { x: before.get(n.id)!.x - before.get(id)!.x, y: before.get(n.id)!.y - before.get(id)!.y };
        const is = { x: after.get(n.id)!.x - after.get(id)!.x, y: after.get(n.id)!.y - after.get(id)!.y };
        expect(dist(was, is), n.id).toBeLessThan(12);
      }
    }
  });
});

describe("KnowledgeGraph2D — the course label", () => {
  it("shows the course code alone under a course root", () => {
    const nodes = [root("c1", "CAS CS 131 - Combinatoric Structures"), ...concepts(3)];
    const { container } = render(<KnowledgeGraph2D nodes={nodes} edges={[]} width={800} height={600} />);
    const label = container.querySelector('[data-testid="graph-node"][data-node-id="root-c1"] text')!;
    expect(label.textContent).toBe("CAS CS 131");
    // The full name is still there for assistive tech and tests.
    expect(screen.getByText("CAS CS 131 - Combinatoric Structures")).toBeInTheDocument();
  });
});
