// @vitest-environment jsdom
/**
 * Moving nodes about is free and fluid, and keeps the graph spaced out.
 *
 * A concept the student drags moves alone (nothing linked to it is pulled
 * along) and stays wherever it is let go; whatever it lands on steps aside,
 * keeps the spot it stepped to, and nothing snaps back. A course carries its
 * concepts with it, stays where it is let go, and shoves aside a course it is
 * dragged into. However things are moved about, no two concepts end up
 * closer than their clearance.
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

/** Two concepts never end up closer than this (twice the concept clearance). */
const CLEAR = 64;

/** Press on a node and let go where it was: a click. */
function click(container: HTMLElement, id: string) {
  const svg = container.querySelector("svg[role=img]")!;
  const g = container.querySelector(`[data-testid="graph-node"][data-node-id="${id}"]`)!;
  const p = positions(container).get(id)!;
  fireEvent.pointerDown(g, { pointerId: 1, button: 0, clientX: p.x, clientY: p.y });
  fireEvent.pointerUp(svg, { pointerId: 1, clientX: p.x, clientY: p.y });
  frames(400);
}

/** The smallest distance between any two of the given points. */
function closest(pts: Pt[]): number {
  let nearest = Infinity;
  for (let i = 0; i < pts.length; i++) {
    for (let j = i + 1; j < pts.length; j++) nearest = Math.min(nearest, dist(pts[i], pts[j]));
  }
  return nearest;
}

describe("KnowledgeGraph2D — dragging a concept", SLOW, () => {
  it("drags only the concept in hand: what is linked to it stays put", () => {
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
    // Its neighbours on the chain are not pulled after it. A concept it
    // brushed past on the way may still be stepping back, a little.
    for (const id of ids.filter((i) => i !== held)) expect(dist(now.get(id)!, before.get(id)!), id).toBeLessThan(20);
    expect(dist(now.get("root-c1")!, before.get("root-c1")!)).toBeLessThan(1);
    // Let go: everything else is back where it was.
    const svg = container.querySelector("svg[role=img]")!;
    fireEvent.pointerUp(svg, { pointerId: 1, clientX: to.x, clientY: to.y });
    frames(600);
    const after = positions(container);
    for (const id of ids.filter((i) => i !== held)) expect(dist(after.get(id)!, before.get(id)!), id).toBeLessThan(1);
  });

  it("stays where it is let go, and is still there after other moves", () => {
    const nodes = [root("c1"), ...concepts(12)];
    const ids = nodes.slice(1).map((n) => n.id);
    const { container } = render(<KnowledgeGraph2D nodes={nodes} edges={chain(ids.slice(0, 4))} width={W} height={H} />);
    const before = positions(container);
    const centre = before.get("root-c1")!;
    // Out past the course's edge, in open space.
    const spot = { x: centre.x + 330, y: centre.y + 120 };
    drag(container, ids[1], spot);
    expect(dist(positions(container).get(ids[1])!, spot)).toBeLessThan(1);
    // Moving something else, and clicking a third, leave it where it is.
    drag(container, ids[7], { x: centre.x - 300, y: centre.y - 150 });
    click(container, ids[9]);
    expect(dist(positions(container).get(ids[1])!, spot)).toBeLessThan(1);
  });

  it("goes nowhere when let go near where it was: no snapping back", () => {
    const nodes = [root("c1"), ...concepts(12)];
    const ids = nodes.slice(1).map((n) => n.id);
    const { container } = render(<KnowledgeGraph2D nodes={nodes} edges={[]} width={W} height={H} />);
    const at = positions(container);
    const centre = at.get("root-c1")!;
    // A concept on the outer ring, nudged a little further out: nothing is in
    // the way there, so nothing makes it move.
    const id = ids.reduce((far, i) => (dist(at.get(i)!, centre) > dist(at.get(far)!, centre) ? i : far));
    const p = at.get(id)!;
    const d = dist(p, centre);
    const spot = { x: p.x + ((p.x - centre.x) / d) * 17, y: p.y + ((p.y - centre.y) / d) * 17 };
    drag(container, id, spot);
    expect(dist(positions(container).get(id)!, spot)).toBeLessThan(1);
  });

  it("makes room when let go on another concept, and both keep their new spots", () => {
    const nodes = [root("c1"), ...concepts(12)];
    const ids = nodes.slice(1).map((n) => n.id);
    const { container } = render(<KnowledgeGraph2D nodes={nodes} edges={[]} width={W} height={H} />);
    const before = positions(container);
    const [a, b] = [ids[0], ids[6]];
    drag(container, a, before.get(b)!);
    const after = positions(container);
    // They part to a caption's width, splitting the difference: neither is
    // sent back to where it came from.
    expect(dist(after.get(a)!, after.get(b)!)).toBeGreaterThanOrEqual(CLEAR - 1);
    expect(dist(after.get(a)!, before.get(b)!)).toBeLessThan(CLEAR);
    expect(dist(after.get(b)!, before.get(b)!)).toBeLessThan(CLEAR);
    // Another move elsewhere leaves both where they settled.
    const centre = after.get("root-c1")!;
    drag(container, ids[9], { x: centre.x + 360, y: centre.y });
    const later = positions(container);
    expect(dist(later.get(a)!, after.get(a)!)).toBeLessThan(1);
    expect(dist(later.get(b)!, after.get(b)!)).toBeLessThan(1);
  });

  it("keeps every concept a caption apart, however many are moved about", () => {
    const nodes = [root("c1"), ...concepts(30)];
    const ids = nodes.slice(1).map((n) => n.id);
    const edges = [...chain(ids.slice(0, 10)), ...chain([ids[3], ids[14], ids[15], ids[16]])];
    const { container } = render(<KnowledgeGraph2D nodes={nodes} edges={edges} width={W} height={H} />);
    const start = positions(container);
    const centre = start.get("root-c1")!;
    // Each dropped right on top of another concept, or near the course's centre.
    const moves: Array<[string, Pt]> = [
      [ids[0], start.get(ids[20])!],
      [ids[9], { x: centre.x - 40, y: centre.y + 30 }],
      [ids[21], start.get(ids[22])!],
      [ids[14], start.get(ids[2])!],
      [ids[5], { x: centre.x + 60, y: centre.y + 60 }],
      [ids[27], start.get(ids[28])!],
    ];
    for (const [id, to] of moves) drag(container, id, to);
    const pts = [...positions(container)].filter(([id]) => id !== "root-c1").map(([, p]) => p);
    expect(closest(pts)).toBeGreaterThanOrEqual(CLEAR - 1);
    // Nothing went in under the course's root.
    for (const p of pts) expect(dist(p, centre)).toBeGreaterThanOrEqual(58 + 32 - 1);
  });

  it("moves nothing on a click", () => {
    const nodes = [root("c1"), ...concepts(12)];
    const { container } = render(<KnowledgeGraph2D nodes={nodes} edges={[]} width={W} height={H} />);
    const before = positions(container);
    click(container, "c1-n03");
    const after = positions(container);
    for (const [id, q] of before) expect(dist(after.get(id)!, q), id).toBeLessThan(1);
  });

  it("keeps where it was put when the window is re-measured", () => {
    const nodes = [root("c1"), ...concepts(12)];
    const ids = nodes.slice(1).map((n) => n.id);
    const shown = render(<KnowledgeGraph2D nodes={nodes} edges={[]} width={W} height={H} />);
    const before = positions(shown.container);
    const centre = before.get("root-c1")!;
    const spot = { x: centre.x + 300, y: centre.y - 140 };
    drag(shown.container, ids[3], spot);
    // A wider window re-plans the graph and moves the course to the new middle.
    shown.rerender(<KnowledgeGraph2D nodes={nodes} edges={[]} width={W + 200} height={H} />);
    frames(400);
    const after = positions(shown.container);
    const moved = { x: after.get("root-c1")!.x - centre.x, y: after.get("root-c1")!.y - centre.y };
    // Where it was put, relative to its course: not back on its planned seat.
    expect(dist(after.get(ids[3])!, { x: spot.x + moved.x, y: spot.y + moved.y })).toBeLessThan(1);
    for (const id of ids.filter((i) => i !== ids[3])) {
      const was = before.get(id)!;
      expect(dist(after.get(id)!, { x: was.x + moved.x, y: was.y + moved.y }), id).toBeLessThan(1);
    }
  });
});

describe("KnowledgeGraph2D — dragging a course", SLOW, () => {
  it.each([
    ["plain", false],
    ["legible", true],
  ])("carries its concepts with it and stays where it is let go (%s)", (_name, legible) => {
    const nodes = [root("c1"), root("c2"), ...concepts(12, "c1"), ...concepts(12, "c2")];
    const { container } = render(
      <KnowledgeGraph2D nodes={nodes} edges={[]} width={W} height={H} legible={legible} />,
    );
    const before = positions(container);
    const from = before.get("root-c1")!;
    const to = { x: from.x - 30, y: from.y + 180 };
    drag(container, "root-c1", to);
    const after = positions(container);
    expect(dist(after.get("root-c1")!, to)).toBeLessThan(1);
    // Every concept of the course kept its place round it.
    for (const n of nodes.filter((m) => !m.is_subject_root && m.course_id === "c1")) {
      const was = before.get(n.id)!;
      expect(dist(after.get(n.id)!, { x: was.x + to.x - from.x, y: was.y + to.y - from.y }), n.id).toBeLessThan(1);
    }
    // The other course did not move.
    expect(dist(after.get("root-c2")!, before.get("root-c2")!)).toBeLessThan(1);
  });

  it("pulls its concepts after it while it is being dragged", () => {
    const nodes = [root("c1"), root("c2"), ...concepts(12, "c1"), ...concepts(12, "c2")];
    const { container } = render(<KnowledgeGraph2D nodes={nodes} edges={[]} width={W} height={H} />);
    const before = positions(container);
    const from = before.get("root-c1")!;
    const to = { x: from.x, y: from.y + 200 };
    drag(container, "root-c1", to, { hold: true });
    const held = positions(container);
    // Still holding on: the concepts have followed it most of the way.
    for (const n of nodes.filter((m) => !m.is_subject_root && m.course_id === "c1")) {
      expect(held.get(n.id)!.y - before.get(n.id)!.y, n.id).toBeGreaterThan(150);
    }
  });

  it.each([
    ["plain", false],
    ["legible", true],
  ])("shoves aside a course it is dropped onto, and stays where it is let go (%s)", (_name, legible) => {
    const nodes = [root("c1"), root("c2"), ...concepts(12, "c1"), ...concepts(12, "c2")];
    const { container } = render(
      <KnowledgeGraph2D nodes={nodes} edges={[]} width={W} height={H} legible={legible} />,
    );
    const before = positions(container);
    const target = { x: before.get("root-c2")!.x - 40, y: before.get("root-c2")!.y + 20 };
    drag(container, "root-c1", target);
    const after = positions(container);
    const plan = layout.planRadial(nodes, [], W, H);
    const reach = Math.max(...[...plan.orbit.values()].map((o) => o.radius)) + 32;
    // Clear of each other: both courses' concepts plus a gap.
    expect(dist(after.get("root-c1")!, after.get("root-c2")!)).toBeGreaterThan(2 * reach + 40 - 2);
    // No two concepts overlap, across the two courses.
    const pts = [...after].filter(([id]) => !id.startsWith("root-")).map(([, p]) => p);
    expect(closest(pts)).toBeGreaterThanOrEqual(CLEAR - 1);
    // The pushed course stays in the window.
    expect(after.get("root-c2")!.x).toBeLessThanOrEqual(W - 58 + 1);
  });
});
