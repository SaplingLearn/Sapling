// @vitest-environment jsdom
/**
 * Moving nodes about keeps the graph spaced out.
 *
 * Every concept sits on a seat its course planned with room for its caption.
 * A concept the student drags moves alone (nothing linked to it is pulled
 * along), and when it is let go it takes the seat nearest to where it was
 * dropped, trading places with whatever sat there. However the concepts are
 * moved about, they stay as far apart as planned. A course dropped onto
 * another is set down beside it.
 *
 * The simulation runs on d3-timer, which reads its clock and picks how to
 * wait for a frame when it first loads. Here it loads under fake timers and
 * without requestAnimationFrame, so its clock is the fake one and it waits
 * with setTimeout: `frames(n)` plays exactly `n` frames, the same on any
 * machine. (The component's own view animations keep the real
 * requestAnimationFrame.)
 */

import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render } from "@testing-library/react";
import React from "react";
import type { GraphEdge, GraphNode } from "@/lib/data";

let KnowledgeGraph2D: (typeof import("./KnowledgeGraph2D"))["KnowledgeGraph2D"];
let layout: typeof import("@/lib/graph/radialLayout");

beforeAll(async () => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "performance"] });
  const raf = window.requestAnimationFrame;
  (window as { requestAnimationFrame?: unknown }).requestAnimationFrame = undefined;
  try {
    ({ KnowledgeGraph2D } = await import("./KnowledgeGraph2D"));
    layout = await import("@/lib/graph/radialLayout");
  } finally {
    window.requestAnimationFrame = raf;
  }
  // jsdom has no pointer capture; the drag handlers call it.
  if (!Element.prototype.setPointerCapture) Element.prototype.setPointerCapture = () => {};
  if (!Element.prototype.releasePointerCapture) Element.prototype.releasePointerCapture = () => {};
});

afterEach(() => {
  cleanup();
  // Unmounting stops the simulation; let the frame d3-timer still has booked
  // come round and find nothing to do, so the next test starts clean.
  frames(4);
});

afterAll(() => {
  vi.useRealTimers();
});

/**
 * Each test plays the simulation for hundreds of frames, several times over;
 * on a busy machine that outlasts the default five seconds.
 */
const SLOW = { timeout: 60_000 };

/** Play `n` simulation frames. */
const frames = (n: number) => vi.advanceTimersByTime(17 * n);

const COLOURS: Record<string, string> = { c1: "#3e6f8a", c2: "#7a874f" };
const root = (course: string): GraphNode => ({
  id: `root-${course}`,
  name: `${course.toUpperCase()} 101 - A course`,
  subject: course,
  color: COLOURS[course],
  mastery_tier: "learning",
  mastery_score: 0,
  course_id: course,
  is_subject_root: true,
});
const concepts = (count: number, course = "c1"): GraphNode[] =>
  Array.from({ length: count }, (_, i) => ({
    id: `${course}-n${String(i).padStart(2, "0")}`,
    name: `Concept ${i}`,
    subject: course,
    color: COLOURS[course],
    mastery_tier: "learning",
    mastery_score: (i % 5) / 5,
    course_id: course,
  }));
const chain = (ids: string[]): GraphEdge[] =>
  ids.slice(1).map((id, i) => ({ source: ids[i], target: id, strength: 0.6, relationship_type: "prerequisite" }));

type Pt = { x: number; y: number };
const dist = (a: Pt, b: Pt) => Math.hypot(a.x - b.x, a.y - b.y);

/** Every node's position, by id. The view is the identity in these windows, so these are also window points. */
function positions(container: HTMLElement): Map<string, Pt> {
  const out = new Map<string, Pt>();
  for (const g of container.querySelectorAll('[data-testid="graph-node"]')) {
    const [, x, y] = /translate\(([-\d.e]+),\s*([-\d.e]+)\)/.exec(g.getAttribute("transform")!)!;
    out.set(g.getAttribute("data-node-id")!, { x: Number(x), y: Number(y) });
  }
  return out;
}

/** Press on a node, move to `to` in steps, hold a moment, and (unless `hold`) let go and let it settle. */
function drag(container: HTMLElement, id: string, to: Pt, { hold = false } = {}) {
  const svg = container.querySelector("svg[role=img]")!;
  const g = container.querySelector(`[data-testid="graph-node"][data-node-id="${id}"]`)!;
  const from = positions(container).get(id)!;
  fireEvent.pointerDown(g, { pointerId: 1, button: 0, clientX: from.x, clientY: from.y });
  const steps = 12;
  for (let i = 1; i <= steps; i++) {
    fireEvent.pointerMove(svg, {
      pointerId: 1,
      clientX: from.x + ((to.x - from.x) * i) / steps,
      clientY: from.y + ((to.y - from.y) * i) / steps,
    });
    frames(2);
  }
  frames(20);
  if (hold) return;
  fireEvent.pointerUp(svg, { pointerId: 1, clientX: to.x, clientY: to.y });
  frames(600);
}

const W = 1240;
const H = 900;

describe("KnowledgeGraph2D — dragging a concept", SLOW, () => {
  it("drags only the concept in hand: what is linked to it only leans after it", () => {
    const nodes = [root("c1"), ...concepts(12)];
    const ids = nodes.slice(1).map((n) => n.id);
    const edges = chain(ids.slice(0, 6));
    const { container } = render(<KnowledgeGraph2D nodes={nodes} edges={edges} width={W} height={H} />);
    const before = positions(container);
    const held = ids[2];
    // Far out of the course, still holding on.
    const to = { x: before.get(held)!.x + 380, y: before.get(held)!.y + 40 };
    drag(container, held, to, { hold: true });
    const now = positions(container);
    expect(dist(now.get(held)!, to)).toBeLessThan(1);
    // Its neighbours on the chain lean after it, held back by their seats:
    // less than a seat's width. On ropes they were hauled all the way along.
    for (const id of [ids[1], ids[3]]) expect(dist(now.get(id)!, before.get(id)!), id).toBeLessThan(70);
    // What is not linked to it does not move, and neither does its course.
    for (const id of ids.slice(6)) expect(dist(now.get(id)!, before.get(id)!), id).toBeLessThan(15);
    expect(dist(now.get("root-c1")!, before.get("root-c1")!)).toBeLessThan(1);
    // Let go, they spring back.
    const svg = container.querySelector("svg[role=img]")!;
    fireEvent.pointerUp(svg, { pointerId: 1, clientX: to.x, clientY: to.y });
    frames(600);
    const after = positions(container);
    // It took the outer seat on that side; they lean a little toward it.
    for (const id of [ids[1], ids[3]]) expect(dist(after.get(id)!, before.get(id)!), id).toBeLessThan(20);
  });

  it("trades places with the concept it is let go on; nothing else moves", () => {
    const nodes = [root("c1"), ...concepts(12)];
    const ids = nodes.slice(1).map((n) => n.id);
    const { container } = render(<KnowledgeGraph2D nodes={nodes} edges={[]} width={W} height={H} />);
    const before = positions(container);
    // Two concepts on opposite sides of the course.
    const centre = before.get("root-c1")!;
    const [a, b] = [...ids]
      .map((id) => ({ id, a: Math.atan2(before.get(id)!.y - centre.y, before.get(id)!.x - centre.x) }))
      .sort((p, q) => p.a - q.a)
      .filter((_, i, all) => i === 0 || i === Math.floor(all.length / 2))
      .map((p) => p.id);
    drag(container, a, before.get(b)!);
    const after = positions(container);
    // Straight across the course, past its centre, each to the other's seat.
    expect(dist(after.get(a)!, before.get(b)!)).toBeLessThan(4);
    expect(dist(after.get(b)!, before.get(a)!)).toBeLessThan(4);
    for (const id of ids) {
      if (id === a || id === b) continue;
      expect(dist(after.get(id)!, before.get(id)!), id).toBeLessThan(4);
    }
  });

  it("goes back to its own seat when let go near it", () => {
    const nodes = [root("c1"), ...concepts(12)];
    const ids = nodes.slice(1).map((n) => n.id);
    const { container } = render(<KnowledgeGraph2D nodes={nodes} edges={[]} width={W} height={H} />);
    const before = positions(container);
    const p = before.get(ids[4])!;
    drag(container, ids[4], { x: p.x + 14, y: p.y - 10 });
    const after = positions(container);
    for (const id of ids) expect(dist(after.get(id)!, before.get(id)!), id).toBeLessThan(8);
  });

  it("takes the nearest seat when let go outside its course, not a spot off on its own", () => {
    const nodes = [root("c1"), ...concepts(30)];
    const { container } = render(<KnowledgeGraph2D nodes={nodes} edges={[]} width={W} height={H} />);
    const before = positions(container);
    const centre = before.get("root-c1")!;
    const outer = Math.max(...[...before].filter(([id]) => id !== "root-c1").map(([, p]) => dist(p, centre)));
    // The concept nearest the centre, dropped far off to the right.
    const id = [...before].filter(([k]) => k !== "root-c1").sort((p, q) => dist(p[1], centre) - dist(q[1], centre))[0][0];
    drag(container, id, { x: centre.x + 520, y: centre.y + 30 });
    const after = positions(container).get(id)!;
    // On the outer ring, on the side it was dropped.
    expect(dist(after, centre)).toBeGreaterThan(outer - 12);
    expect(dist(after, centre)).toBeLessThan(outer + 12);
    expect(after.x - centre.x).toBeGreaterThan(outer * 0.8);
  });

  it("keeps every concept a caption apart, however many are moved about", () => {
    const nodes = [root("c1"), ...concepts(30)];
    const ids = nodes.slice(1).map((n) => n.id);
    const edges = [...chain(ids.slice(0, 10)), ...chain([ids[3], ids[14], ids[15], ids[16]])];
    const { container } = render(<KnowledgeGraph2D nodes={nodes} edges={edges} width={W} height={H} />);
    const centre = positions(container).get("root-c1")!;
    const moves: Array<[string, Pt]> = [
      [ids[0], { x: centre.x + 300, y: centre.y }],
      [ids[9], { x: centre.x - 40, y: centre.y + 30 }],
      [ids[20], { x: centre.x, y: centre.y - 260 }],
      [ids[14], { x: centre.x - 250, y: centre.y + 200 }],
      [ids[5], { x: centre.x + 60, y: centre.y + 60 }],
      [ids[27], { x: centre.x + 20, y: centre.y - 20 }],
    ];
    for (const [id, to] of moves) drag(container, id, to);
    const pts = [...positions(container)].filter(([id]) => id !== "root-c1").map(([, p]) => p);
    let nearest = Infinity;
    for (let i = 0; i < pts.length; i++) {
      for (let j = i + 1; j < pts.length; j++) nearest = Math.min(nearest, dist(pts[i], pts[j]));
    }
    // As planned: neighbours about 66 or more apart. Pulled along on ropes,
    // concepts used to end up on top of one another.
    expect(nearest).toBeGreaterThan(58);
    for (const p of pts) expect(dist(p, centre)).toBeLessThan(232 + 15);
  });

  it("moves nothing on a click", () => {
    const nodes = [root("c1"), ...concepts(12)];
    const { container } = render(<KnowledgeGraph2D nodes={nodes} edges={[]} width={W} height={H} />);
    const before = positions(container);
    const svg = container.querySelector("svg[role=img]")!;
    const g = container.querySelector('[data-testid="graph-node"][data-node-id="c1-n03"]')!;
    const p = before.get("c1-n03")!;
    fireEvent.pointerDown(g, { pointerId: 1, button: 0, clientX: p.x, clientY: p.y });
    fireEvent.pointerUp(svg, { pointerId: 1, clientX: p.x, clientY: p.y });
    frames(400);
    const after = positions(container);
    for (const [id, q] of before) expect(dist(after.get(id)!, q), id).toBeLessThan(2);
  });
});

describe("KnowledgeGraph2D — dragging a course", SLOW, () => {
  it.each([
    ["plain", false],
    ["legible", true],
  ])("sets a course dropped onto another down beside it (%s)", (_name, legible) => {
    const nodes = [root("c1"), root("c2"), ...concepts(12, "c1"), ...concepts(12, "c2")];
    const { container } = render(
      <KnowledgeGraph2D nodes={nodes} edges={[]} width={W} height={H} legible={legible} />,
    );
    const before = positions(container);
    drag(container, "root-c1", { x: before.get("root-c2")!.x + 10, y: before.get("root-c2")!.y + 10 });
    const after = positions(container);
    const plan = layout.planRadial(nodes, [], W, H);
    const reach = Math.max(...[...plan.orbit.values()].map((o) => o.radius));
    // Each course keeps its rings and a margin to itself.
    expect(dist(after.get("root-c1")!, after.get("root-c2")!)).toBeGreaterThan(2 * reach + 2 * layout.COURSE_MARGIN - 6);
    // The course it landed on did not move.
    expect(dist(after.get("root-c2")!, before.get("root-c2")!)).toBeLessThan(6);
    // Its concepts came with it, around it.
    for (const n of nodes.filter((m) => !m.is_subject_root && m.course_id === "c1")) {
      expect(dist(after.get(n.id)!, after.get("root-c1")!), n.id).toBeLessThan(reach + 15);
    }
  });

  it("stays where it is dropped in open space", () => {
    const nodes = [root("c1"), root("c2"), ...concepts(5, "c1"), ...concepts(5, "c2")];
    const { container } = render(<KnowledgeGraph2D nodes={nodes} edges={[]} width={W} height={H} />);
    const before = positions(container);
    const to = { x: before.get("root-c1")!.x - 40, y: before.get("root-c1")!.y + 120 };
    drag(container, "root-c1", to);
    expect(dist(positions(container).get("root-c1")!, to)).toBeLessThan(2);
  });
});
