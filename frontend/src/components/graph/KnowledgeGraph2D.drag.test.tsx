// @vitest-environment jsdom
/**
 * Moving nodes about, with main's physics on the planned layout.
 *
 * A dragged concept pulls what it is linked to along on ropes (each as long
 * as its link was when the drag began, the course root's links included),
 * so no link is left stretched across the canvas; a pinned course root pulls
 * a concept it links to back instead. Let go, a concept rests where it
 * stops, and nothing pulls it back to where it was planned. A dragged course
 * carries its concepts with it and stays where it is let go.
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
import { courseLinks, planRadial } from "@/lib/graph/radialLayout";

let KnowledgeGraph2D: (typeof import("./KnowledgeGraph2D"))["KnowledgeGraph2D"];

beforeAll(async () => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "performance"] });
  const raf = window.requestAnimationFrame;
  (window as { requestAnimationFrame?: unknown }).requestAnimationFrame = undefined;
  try {
    ({ KnowledgeGraph2D } = await import("./KnowledgeGraph2D"));
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

/** Press on a node and let go where it was: a click. */
function click(container: HTMLElement, id: string) {
  const svg = container.querySelector("svg[role=img]")!;
  const g = container.querySelector(`[data-testid="graph-node"][data-node-id="${id}"]`)!;
  const p = positions(container).get(id)!;
  fireEvent.pointerDown(g, { pointerId: 1, button: 0, clientX: p.x, clientY: p.y });
  fireEvent.pointerUp(svg, { pointerId: 1, clientX: p.x, clientY: p.y });
  frames(400);
}

describe("KnowledgeGraph2D — dragging a concept", SLOW, () => {
  it("pulls the concepts linked to it along, and leaves the rest where they are", () => {
    const nodes = [root("c1"), ...concepts(12)];
    const ids = nodes.slice(1).map((n) => n.id);
    const edges = chain(ids.slice(0, 6));
    const { container } = render(<KnowledgeGraph2D nodes={nodes} edges={edges} width={W} height={H} />);
    const before = positions(container);
    const held = ids[2];
    const to = { x: before.get(held)!.x + 380, y: before.get(held)!.y + 40 };
    drag(container, held, to, { hold: true });
    const now = positions(container);
    expect(dist(now.get(held)!, to)).toBeLessThan(1);
    // Its neighbours on the chain come after it…
    for (const id of [ids[1], ids[3]]) expect(dist(now.get(id)!, before.get(id)!), id).toBeGreaterThan(100);
    // …and a concept linked to nothing stays put.
    for (const id of ids.slice(6)) expect(dist(now.get(id)!, before.get(id)!), id).toBeLessThan(15);
    // The course root is pinned: the drag does not move it.
    expect(dist(now.get("root-c1")!, before.get("root-c1")!)).toBeLessThan(1);
  });

  it("leaves no link stretched once everything has come to rest", () => {
    const nodes = [root("c1"), ...concepts(12)];
    const ids = nodes.slice(1).map((n) => n.id);
    const edges = chain(ids.slice(0, 6));
    const { container } = render(<KnowledgeGraph2D nodes={nodes} edges={edges} width={W} height={H} />);
    const before = positions(container);
    const length = (at: Map<string, Pt>, a: string, b: string) => dist(at.get(a)!, at.get(b)!);
    drag(container, ids[5], { x: before.get(ids[5])!.x + 360, y: before.get(ids[5])!.y - 60 });
    const after = positions(container);
    for (let i = 0; i < 5; i++) {
      // A rope is as long as its link was when the drag began (70 at least).
      // Where the chain meets its pinned course root the two ends tug at
      // each other a little; nothing is left stretched across the canvas.
      const rope = Math.max(70, length(before, ids[i], ids[i + 1]));
      expect(length(after, ids[i], ids[i + 1]), `${ids[i]} – ${ids[i + 1]}`).toBeLessThan(1.5 * rope);
    }
  });

  it("rests where it stops when let go: nothing pulls it back to where it was planned", () => {
    const nodes = [root("c1"), ...concepts(12)];
    const ids = nodes.slice(1).map((n) => n.id);
    // Concepts the course root does not link to: nothing ties them to anything.
    const spokes = new Set(courseLinks(planRadial(nodes, [], W, H)).map((l) => l.target));
    const [loose, other] = ids.filter((id) => !spokes.has(id));
    const { container } = render(<KnowledgeGraph2D nodes={nodes} edges={[]} width={W} height={H} />);
    const before = positions(container);
    const centre = before.get("root-c1")!;
    const spot = { x: centre.x + 380, y: centre.y + 150 };
    drag(container, loose, spot);
    const after = positions(container);
    expect(dist(after.get(loose)!, spot)).toBeLessThan(25);
    expect(dist(after.get(loose)!, before.get(loose)!)).toBeGreaterThan(200);
    // Another move later leaves it where it came to rest.
    drag(container, other, { x: centre.x - 300, y: centre.y - 150 });
    expect(dist(positions(container).get(loose)!, after.get(loose)!)).toBeLessThan(10);
  });

  it("is pulled back toward its course on a rope when the course root links to it", () => {
    const nodes = [root("c1"), ...concepts(12)];
    const spoke = courseLinks(planRadial(nodes, [], W, H))[0].target;
    const { container } = render(<KnowledgeGraph2D nodes={nodes} edges={[]} width={W} height={H} />);
    const before = positions(container);
    const centre = before.get("root-c1")!;
    const rope = Math.max(70, dist(before.get(spoke)!, centre));
    drag(container, spoke, { x: centre.x + 420, y: centre.y + 120 });
    // The course root is pinned: it stays, and pulls the concept back to
    // about the length of their link, wherever round the course it now is.
    const after = positions(container);
    expect(dist(after.get("root-c1")!, centre)).toBeLessThan(1);
    expect(dist(after.get(spoke)!, centre)).toBeLessThan(rope + 40);
  });

  it("moves nothing on a click", () => {
    const nodes = [root("c1"), ...concepts(12)];
    const ids = nodes.slice(1).map((n) => n.id);
    const { container } = render(<KnowledgeGraph2D nodes={nodes} edges={chain(ids.slice(0, 5))} width={W} height={H} />);
    const before = positions(container);
    click(container, ids[2]);
    const after = positions(container);
    for (const [id, q] of before) expect(dist(after.get(id)!, q), id).toBeLessThan(1);
  });

  it("keeps where it was left when the window is re-measured", () => {
    const nodes = [root("c1"), ...concepts(12)];
    const ids = nodes.slice(1).map((n) => n.id);
    const shown = render(<KnowledgeGraph2D nodes={nodes} edges={[]} width={W} height={H} />);
    const centre = positions(shown.container).get("root-c1")!;
    drag(shown.container, ids[3], { x: centre.x + 330, y: centre.y - 140 });
    const before = positions(shown.container);
    // A wider window re-plans the graph and moves the course to the new middle.
    shown.rerender(<KnowledgeGraph2D nodes={nodes} edges={[]} width={W + 200} height={H} />);
    frames(600);
    const after = positions(shown.container);
    const moved = { x: after.get("root-c1")!.x - centre.x, y: after.get("root-c1")!.y - centre.y };
    const was = before.get(ids[3])!;
    // Where it was left, relative to its course: not back where it was planned.
    expect(dist(after.get(ids[3])!, { x: was.x + moved.x, y: was.y + moved.y })).toBeLessThan(12);
  });
});

describe("KnowledgeGraph2D — dragging a course", SLOW, () => {
  /** Two courses of twelve, the first with a short strand of links. */
  const twoCourses = () => {
    const nodes = [root("c1"), root("c2"), ...concepts(12, "c1"), ...concepts(12, "c2")];
    const ids = nodes.filter((n) => !n.is_subject_root && n.course_id === "c1").map((n) => n.id);
    return { nodes, ids, edges: chain(ids.slice(0, 4)) };
  };
  /**
   * A drag target away from the other course, so the two never meet, and a
   * little to one side; inside the window, where a dragged node is kept.
   */
  const awayFrom = (from: Pt, other: Pt, by = 180) => {
    const len = dist(from, other);
    const [ux, uy] = [(from.x - other.x) / len, (from.y - other.y) / len];
    const inside = (v: number, size: number) => Math.min(size - 60, Math.max(60, v));
    return { x: inside(from.x + ux * by - uy * 30, W), y: inside(from.y + uy * by + ux * 30, H) };
  };

  it.each([
    ["plain", false],
    ["legible", true],
  ])("brings its concepts along on ropes and stays where it is let go (%s)", (_name, legible) => {
    const { nodes, ids, edges } = twoCourses();
    const { container } = render(
      <KnowledgeGraph2D nodes={nodes} edges={edges} width={W} height={H} legible={legible} />,
    );
    const before = positions(container);
    const from = before.get("root-c1")!;
    const to = awayFrom(from, before.get("root-c2")!);
    drag(container, "root-c1", to);
    const after = positions(container);
    // A legible course root is elastic: its concepts tug it, its home holds it.
    expect(dist(after.get("root-c1")!, to)).toBeLessThan(legible ? 40 : 1);
    const centre = after.get("root-c1")!;
    for (const id of ids) {
      // Every concept came after it: the course is still one body round its
      // root (a concept on a strand hangs off the strand, so a little further).
      expect(dist(after.get(id)!, centre), id).toBeLessThan(1.2 * dist(before.get(id)!, from) + 40);
    }
    // …on ropes, not as one rigid block: some sit differently round it now.
    const shifted = ids.map((id) =>
      dist(
        { x: after.get(id)!.x - centre.x, y: after.get(id)!.y - centre.y },
        { x: before.get(id)!.x - from.x, y: before.get(id)!.y - from.y },
      ),
    );
    expect(Math.max(...shifted)).toBeGreaterThan(20);
    // The other course did not move.
    expect(dist(after.get("root-c2")!, before.get("root-c2")!)).toBeLessThan(legible ? 20 : 1);
  });

  it("trails its concepts behind it while it is being dragged", () => {
    const { nodes, ids, edges } = twoCourses();
    const { container } = render(<KnowledgeGraph2D nodes={nodes} edges={edges} width={W} height={H} />);
    const before = positions(container);
    const from = before.get("root-c1")!;
    const to = awayFrom(from, before.get("root-c2")!, 220);
    drag(container, "root-c1", to, { hold: true });
    const held = positions(container);
    const along = (id: string) => {
      const [dx, dy] = [to.x - from.x, to.y - from.y];
      const len = Math.hypot(dx, dy);
      return ((held.get(id)!.x - before.get(id)!.x) * dx + (held.get(id)!.y - before.get(id)!.y) * dy) / len;
    };
    const moved = ids.map(along);
    // Still holding on: the concepts are coming after it…
    expect(moved.reduce((sum, m) => sum + m, 0) / moved.length).toBeGreaterThan(30);
    // …some well behind the others: a rope pulls only once it is taut.
    expect(Math.max(...moved) - Math.min(...moved)).toBeGreaterThan(40);
  });
});

describe("KnowledgeGraph2D — the course node", () => {
  it.each([
    ["plain", false],
    ["legible", true],
  ])("is bigger than any concept and labelled with its course code (%s)", (_name, legible) => {
    const nodes = [root("c1"), ...concepts(12)];
    const ids = nodes.slice(1).map((n) => n.id);
    const { container } = render(
      <KnowledgeGraph2D nodes={nodes} edges={chain(ids.slice(0, 8))} width={W} height={H} legible={legible} />,
    );
    const radius = (id: string) =>
      Number(container.querySelector(`[data-testid="graph-node"][data-node-id="${id}"] [data-testid="graph-node-circle"]`)!.getAttribute("data-r"));
    const largest = Math.max(...ids.map(radius));
    expect(radius("root-c1")).toBeGreaterThanOrEqual(1.2 * largest);
    const label = container.querySelector('[data-node-id="root-c1"] [data-testid="graph-course-label"]')!;
    expect(label.textContent).toBe("C1 101");
  });
});
