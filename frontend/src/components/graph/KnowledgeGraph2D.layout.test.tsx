// @vitest-environment jsdom
/**
 * Where the graph's nodes settle, and how the opening view frames them.
 *
 * The plan (`lib/graph/radialLayout`) places every concept with room for its
 * caption; the simulation (links pulling, concepts pushing apart, the orbit
 * force holding each near its place) may only loosen that a little. These
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
import { LABEL_ZOOM, planBounds, planRadial, splitEdges } from "@/lib/graph/radialLayout";
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
  it("settles thirty unlinked concepts close to their planned places, not on rings round their course", () => {
    const nodes = [root("c1"), ...concepts(30)];
    const { container } = render(<KnowledgeGraph2D nodes={nodes} edges={[]} width={1240} height={744} />);
    const at = positions(container);
    const plan = planRadial(nodes, [], 1240, 744);
    const centre = plan.centers.get("root-c1")!;
    expect(dist(at.get("root-c1")!, centre)).toBeLessThan(1e-6);
    let total = 0;
    for (const n of nodes.slice(1)) {
      const o = plan.orbit.get(n.id)!;
      const place = { x: centre.x + Math.cos(o.angle) * o.radius, y: centre.y + Math.sin(o.angle) * o.radius };
      // Links and crowding nudge a concept off its planned place, a little.
      expect(dist(at.get(n.id)!, place), n.id).toBeLessThan(30);
      total += dist(at.get(n.id)!, place);
    }
    expect(total / 30).toBeLessThan(12);
    // Rings would leave a handful of distances from the root; nearly every
    // concept has its own.
    const radii = new Set(nodes.slice(1).map((n) => Math.round(dist(at.get(n.id)!, centre) / 4)));
    expect(radii.size).toBeGreaterThanOrEqual(20);
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

  it("coils a long prerequisite chain up, so the course still opens whole at full size", () => {
    const nodes = [root("c1"), ...concepts(30)];
    const edges = chain(nodes.slice(1).map((n) => n.id));
    const { container } = render(<KnowledgeGraph2D nodes={nodes} edges={edges} width={1240} height={744} />);
    // Laid out link after link, the thirtieth concept would sit some 3,500 units out.
    for (const [id, p] of positions(container)) {
      expect(p.x, id).toBeGreaterThan(0);
      expect(p.x, id).toBeLessThan(1240);
      expect(p.y, id).toBeGreaterThan(0);
      expect(p.y, id).toBeLessThan(744);
    }
    expect(viewTransform(container)).toBe("translate(0, 0) scale(1)");
  });

  it("holds each legible course near its planned centre, however its links pull", () => {
    const nodes = [root("c1"), root("c2"), root("c3"), ...concepts(14, "c1"), ...concepts(20, "c2"), ...concepts(9, "c3")];
    const ids = (c: string) => nodes.filter((n) => !n.is_subject_root && n.course_id === c).map((n) => n.id);
    const edges = [...chain(ids("c1").slice(0, 8)), ...chain(ids("c2").slice(3, 15)), ...chain(ids("c3").slice(0, 4))];
    const { container } = render(<KnowledgeGraph2D nodes={nodes} edges={edges} width={1240} height={744} legible />);
    const at = positions(container);
    const plan = planRadial(nodes, splitEdges(nodes, edges).concept, 1240, 744, LABEL_ZOOM.hidden);
    // A legible course root is elastic: its concepts tug it, its home holds it.
    for (const [id, c] of plan.centers) expect(dist(at.get(id)!, c), id).toBeLessThan(20);
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

  describe("a legible graph (the tree)", () => {
    const COURSES = [root("c1"), root("c2"), root("c3"), ...concepts(14, "c1"), ...concepts(10, "c2"), ...concepts(8, "c3")];
    const conceptLabels = (container: HTMLElement) =>
      [...container.querySelectorAll('[data-testid="graph-node"] text:not([data-testid="graph-course-label"])')];

    it("opens zoomed out to where its concept labels have faded out, though it would fit at full size", () => {
      const { container } = render(<KnowledgeGraph2D nodes={SMALL} edges={[]} width={800} height={600} legible />);
      expect(view(container).scale).toBe(LABEL_ZOOM.hidden);
      const labels = conceptLabels(container);
      expect(labels).toHaveLength(5);
      for (const label of labels) expect(label).toHaveAttribute("opacity", "0");
      // The course is still named.
      expect(container.querySelector('[data-testid="graph-course-label"]')).toHaveTextContent("C1 101");
    });

    it("shows the labels again on zooming in", () => {
      const { container } = render(<KnowledgeGraph2D nodes={SMALL} edges={[]} width={800} height={600} legible />);
      for (let i = 0; i < 3; i++) fireEvent.click(screen.getByTestId("graph-zoom-in"));
      for (const label of conceptLabels(container)) expect(Number(label.getAttribute("opacity"))).toBeGreaterThan(0.5);
    });

    it("opens with its courses spread through the window, not gathered in the middle of it", () => {
      const [w, h] = [1500, 800];
      const { container } = render(<KnowledgeGraph2D nodes={COURSES} edges={[]} width={w} height={h} legible />);
      const v = view(container);
      expect(v.scale).toBe(LABEL_ZOOM.hidden);
      let [left, right, top, bottom] = [Infinity, -Infinity, Infinity, -Infinity];
      for (const p of positions(container).values()) {
        const [x, y] = [p.x * v.scale + v.tx, p.y * v.scale + v.ty];
        // Every concept opens on screen…
        expect(x).toBeGreaterThan(0);
        expect(x).toBeLessThan(w);
        expect(y).toBeGreaterThan(0);
        expect(y).toBeLessThan(h);
        [left, right, top, bottom] = [Math.min(left, x), Math.max(right, x), Math.min(top, y), Math.max(bottom, y)];
      }
      // …and between them they reach most of the way across it and down it
      // (planned at full size and opened this far out, under a third of it).
      expect(right - left).toBeGreaterThan(0.6 * w);
      expect(bottom - top).toBeGreaterThan(0.6 * h);
    });

    it("resets to that opening view", () => {
      const { container } = render(<KnowledgeGraph2D nodes={COURSES} edges={[]} width={1500} height={800} legible />);
      const opened = viewTransform(container);
      fireEvent.click(screen.getByTestId("graph-zoom-in"));
      expect(viewTransform(container)).not.toBe(opened);
      fireEvent.click(screen.getByTestId("graph-zoom-reset"));
      expect(viewTransform(container)).toBe(opened);
    });

    it("opens further out still when the graph is too large to show at that zoom", () => {
      const many = ["c1", "c2", "c3"].flatMap((c) => [root(c), ...concepts(60, c)]);
      const { container } = render(<KnowledgeGraph2D nodes={many} edges={[]} width={600} height={400} legible />);
      const b = planBounds(planRadial(many, [], 600, 400, LABEL_ZOOM.hidden), 600, 400)!;
      const v = view(container);
      expect(v.scale).toBeLessThan(LABEL_ZOOM.hidden);
      expect(v.scale).toBeCloseTo(Math.min(600 / (b.maxX - b.minX), 400 / (b.maxY - b.minY)), 9);
    });
  });

  it("leaves the student's own zoom alone when the window is re-measured", () => {
    const nodes = [root("c1"), ...concepts(12)];
    const shown = render(<KnowledgeGraph2D nodes={nodes} edges={[]} width={600} height={300} />);
    fireEvent.click(screen.getByTestId("graph-zoom-in"));
    const theirs = viewTransform(shown.container);
    shown.rerender(<KnowledgeGraph2D nodes={nodes} edges={[]} width={800} height={660} />);
    expect(viewTransform(shown.container)).toBe(theirs);
  });

  describe("a window too small for the graph even at the buttons' furthest zoom (0.25)", () => {
    // A phone, or a narrow dashboard column.
    const TWO = [root("c1"), root("c2"), ...concepts(40, "c1"), ...concepts(40, "c2")];
    const fitIn = (w: number, h: number) => {
      const b = planBounds(planRadial(TWO, [], w, h), w, h)!;
      return Math.min(w / (b.maxX - b.minX), h / (b.maxY - b.minY));
    };

    it("still opens on the whole graph, every concept on screen", () => {
      const fit = fitIn(200, 150);
      expect(fit).toBeLessThan(0.25);
      expect(fit).toBeGreaterThan(0.1);
      const { container } = render(<KnowledgeGraph2D nodes={TWO} edges={[]} width={200} height={150} />);
      const v = view(container);
      expect(v.scale).toBeCloseTo(fit, 9);
      for (const [, p] of positions(container)) {
        expect(p.x * v.scale + v.tx).toBeGreaterThanOrEqual(0);
        expect(p.x * v.scale + v.tx).toBeLessThanOrEqual(200);
        expect(p.y * v.scale + v.ty).toBeGreaterThanOrEqual(0);
        expect(p.y * v.scale + v.ty).toBeLessThanOrEqual(150);
      }
    });

    it("zooms out no further than that opening view", () => {
      const fit = fitIn(200, 150);
      const { container } = render(<KnowledgeGraph2D nodes={TWO} edges={[]} width={200} height={150} />);
      fireEvent.click(screen.getByTestId("graph-zoom-out"));
      expect(view(container).scale).toBeCloseTo(fit, 9);
      fireEvent.click(screen.getByTestId("graph-zoom-in"));
      fireEvent.click(screen.getByTestId("graph-zoom-out"));
      fireEvent.click(screen.getByTestId("graph-zoom-out"));
      expect(view(container).scale).toBeCloseTo(fit, 9);
    });

    it("shrinks legible nodes with the view, so they keep their room", () => {
      // Down to 0.25 a legible concept is at least 7px on screen (28 graph
      // units at 0.25), a course node 10px (40). Further out they keep those
      // sizes in the graph rather than growing until neighbours overlap.
      const { container } = render(<KnowledgeGraph2D legible nodes={TWO} edges={[]} width={200} height={150} />);
      expect(view(container).scale).toBeLessThan(0.25);
      const radii = (sel: string) =>
        Array.from(container.querySelectorAll(`${sel} [data-testid="graph-node-circle"]`)).map((s) =>
          Number(s.getAttribute("data-r")),
        );
      const conceptRadii = radii('[data-testid="graph-node"]:not([data-node-id^="root-"])');
      expect(conceptRadii).toHaveLength(80);
      expect(Math.max(...conceptRadii)).toBeLessThanOrEqual(28);
      expect(Math.max(...radii('[data-testid="graph-node"][data-node-id^="root-"]'))).toBeLessThanOrEqual(40);
    });

    it("never opens further out than 0.1", () => {
      expect(fitIn(120, 90)).toBeLessThan(0.1);
      const { container } = render(<KnowledgeGraph2D nodes={TWO} edges={[]} width={120} height={90} />);
      expect(view(container).scale).toBe(0.1);
    });
  });
});

describe("KnowledgeGraph2D — re-planning", () => {
  it.each([
    ["plain", {}],
    ["legible", { legible: true }],
  ])("carries each course to its new place when the window is re-measured (%s)", (_name, props) => {
    const nodes = [root("c1"), root("c2"), root("c3"), ...concepts(10, "c1"), ...concepts(10, "c2"), ...concepts(10, "c3")];
    // Squarish: the courses sit in two rows. Then wide: they sit in one.
    const shown = render(<KnowledgeGraph2D nodes={nodes} edges={[]} width={700} height={700} {...props} />);
    const before = positions(shown.container);
    shown.rerender(<KnowledgeGraph2D nodes={nodes} edges={[]} width={2000} height={500} {...props} />);
    const after = positions(shown.container);
    // A legible graph is planned for the zoom it opens at.
    const openZoom = "legible" in props ? LABEL_ZOOM.hidden : 1;
    const plan = planRadial(nodes, [], 2000, 500, openZoom);
    // The plan really did move them a long way.
    const first = planRadial(nodes, [], 700, 700, openZoom);
    expect(dist(first.centers.get("root-c3")!, plan.centers.get("root-c3")!)).toBeGreaterThan(400);
    for (const [id, centre] of plan.centers) {
      // Left to the springs, a course stopped well short of a far-off new home.
      // (A legible root is elastic: its concepts, all round it, tug it a little.)
      expect(dist(after.get(id)!, centre), id).toBeLessThan("legible" in props ? 15 : 6);
      // …and its concepts came with it, each where it sat round its course
      // (a legible course as much wider or closer as the new window has it
      // planned: it is spread to fill the window it opens in).
      const course = id.replace("root-", "");
      for (const n of nodes.filter((m) => !m.is_subject_root && m.course_id === course)) {
        const wider = plan.orbit.get(n.id)!.radius / first.orbit.get(n.id)!.radius;
        const was = { x: before.get(n.id)!.x - before.get(id)!.x, y: before.get(n.id)!.y - before.get(id)!.y };
        const is = { x: after.get(n.id)!.x - after.get(id)!.x, y: after.get(n.id)!.y - after.get(id)!.y };
        expect(dist({ x: was.x * wider, y: was.y * wider }, is), n.id).toBeLessThan(12 * Math.max(1, wider));
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
