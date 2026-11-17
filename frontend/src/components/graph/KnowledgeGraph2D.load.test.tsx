// @vitest-environment jsdom
/**
 * Opening the graph: it is drawn already at rest.
 *
 * With motion allowed, the simulation used to start on screen at full heat
 * (alpha 0.9) from the planned places, so on every load links pulled,
 * concepts pushed apart and whole courses swung out and back for about a
 * third of a second. A planned graph now settles before it is drawn
 * (`settleQuietly`): nothing moves once it is on screen, whether it has just
 * opened, the window was re-measured or a concept was added.
 *
 * Motion is allowed here (the shared setup's reduced-motion stub is
 * replaced), the path a real browser takes. d3-timer is loaded under fake
 * timers without requestAnimationFrame, as in the drag tests, so
 * `frames(n)` plays exactly `n` frames.
 */

import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";
import React from "react";
import { forceLink, forceManyBody, forceSimulation, forceX, forceY, type SimulationNodeDatum } from "d3-force";
import type { GraphEdge, GraphNode } from "@/lib/data";

let KnowledgeGraph2D: (typeof import("./KnowledgeGraph2D"))["KnowledgeGraph2D"];
let settleQuietly: (typeof import("./KnowledgeGraph2D"))["settleQuietly"];
const sharedMatchMedia = window.matchMedia;

beforeAll(async () => {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "performance"] });
  const raf = window.requestAnimationFrame;
  (window as { requestAnimationFrame?: unknown }).requestAnimationFrame = undefined;
  try {
    ({ KnowledgeGraph2D, settleQuietly } = await import("./KnowledgeGraph2D"));
  } finally {
    window.requestAnimationFrame = raf;
  }
});

afterEach(() => {
  cleanup();
  frames(4);
});

afterAll(() => {
  vi.useRealTimers();
  window.matchMedia = sharedMatchMedia;
});

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
const concepts = (count: number, course = "c1", from = 0): GraphNode[] =>
  Array.from({ length: count }, (_, k) => {
    const i = from + k;
    return {
      id: `${course}-n${String(i).padStart(2, "0")}`,
      name: `Concept ${i}`,
      subject: course,
      color: COLOURS[course],
      mastery_tier: "learning",
      mastery_score: (i % 5) / 5,
      course_id: course,
    };
  });
const chain = (ids: string[]): GraphEdge[] =>
  ids.slice(1).map((id, i) => ({ source: ids[i], target: id, strength: 0.6, relationship_type: "prerequisite" }));

/** Every node's drawn position, by id. */
function positions(container: HTMLElement): Map<string, { x: number; y: number }> {
  const out = new Map<string, { x: number; y: number }>();
  for (const g of container.querySelectorAll('[data-testid="graph-node"]')) {
    const [, x, y] = /translate\(([-\d.e]+),\s*([-\d.e]+)\)/.exec(g.getAttribute("transform")!)!;
    out.set(g.getAttribute("data-node-id")!, { x: Number(x), y: Number(y) });
  }
  return out;
}
/** The furthest any node got from where it was drawn first. */
function furthest(before: Map<string, { x: number; y: number }>, after: Map<string, { x: number; y: number }>) {
  let max = 0;
  for (const [id, a] of before) {
    const b = after.get(id)!;
    max = Math.max(max, Math.hypot(b.x - a.x, b.y - a.y));
  }
  return max;
}
const viewTransform = (container: HTMLElement) =>
  Array.from(container.querySelectorAll("g"))
    .map((g) => g.getAttribute("transform") ?? "")
    .find((t) => t.includes("scale("))!;

// Two courses with strands of linked concepts: links, charge and the orbit
// force all have work to do, so a graph that is not settled moves.
const C1 = concepts(20);
const C2 = concepts(20, "c2");
const NODES = [root("c1"), root("c2"), ...C1, ...C2];
const EDGES = [...chain(C1.slice(0, 8).map((n) => n.id)), ...chain(C2.slice(0, 6).map((n) => n.id))];

describe("KnowledgeGraph2D — opening at rest", () => {
  it.each([
    ["plain", false],
    ["legible", true],
  ])("draws the graph already settled: nothing moves once it is on screen (%s)", (_name, legible) => {
    const { container } = render(
      <KnowledgeGraph2D nodes={NODES} edges={EDGES} width={1240} height={900} legible={legible} />,
    );
    const drawn = positions(container);
    expect(drawn.size).toBe(NODES.length);
    frames(120);
    expect(furthest(drawn, positions(container))).toBeLessThan(0.5);
  });

  it("re-plans at rest when the window is re-measured", () => {
    const shown = render(<KnowledgeGraph2D nodes={NODES} edges={EDGES} width={1240} height={900} legible />);
    frames(10);
    shown.rerender(<KnowledgeGraph2D nodes={NODES} edges={EDGES} width={700} height={900} legible />);
    const drawn = positions(shown.container);
    frames(120);
    expect(furthest(drawn, positions(shown.container))).toBeLessThan(0.5);
  });

  it("takes in a new concept at rest", () => {
    const shown = render(<KnowledgeGraph2D nodes={NODES} edges={EDGES} width={1240} height={900} legible />);
    frames(10);
    const more = [...NODES, ...concepts(1, "c1", 20)];
    shown.rerender(<KnowledgeGraph2D nodes={more} edges={EDGES} width={1240} height={900} legible />);
    const drawn = positions(shown.container);
    expect(drawn.size).toBe(more.length);
    frames(120);
    expect(furthest(drawn, positions(shown.container))).toBeLessThan(0.5);
  });

  it("frames a graph with its own opening zoom at once, rather than zooming there", () => {
    // Quiz home's neighbourhood: a concept and its neighbours, no course root.
    const centre = C1[0];
    const around = C1.slice(1, 9);
    const fragment = [centre, ...around];
    const spokes = around.map((n) => ({ source: centre.id, target: n.id, strength: 0.5 }));
    const { container } = render(
      <KnowledgeGraph2D nodes={fragment} edges={spokes} width={494} height={334} initialZoom={1.6} highlightId={centre.id} />,
    );
    const opened = viewTransform(container);
    expect(opened).not.toBe(`translate(${(494 / 2) * (1 - 1.6)}, ${(334 / 2) * (1 - 1.6)}) scale(1.6)`);
    frames(120);
    expect(viewTransform(container)).toBe(opened);
  });
});

describe("settleQuietly", () => {
  type N = SimulationNodeDatum & { id: string };
  const make = () => {
    const nodes: N[] = Array.from({ length: 30 }, (_, i) => ({ id: `n${i}`, x: (i % 6) * 12, y: Math.floor(i / 6) * 12 }));
    const links = nodes.slice(1).map((n, i) => ({ source: nodes[i].id, target: n.id }));
    return forceSimulation(nodes)
      .force("charge", forceManyBody<N>().strength(-30))
      .force("link", forceLink<N, { source: string; target: string }>(links).id((d) => d.id).distance(30))
      .force("x", forceX<N>(0).strength(0.1))
      .force("y", forceY<N>(0).strength(0.1))
      .stop();
  };

  it("runs the simulation until nothing moves, and leaves it stopped", () => {
    const sim = make();
    expect(settleQuietly(sim)).toBe(true);
    expect(sim.alpha()).toBe(0);
    for (const n of sim.nodes()) expect(Math.max(Math.abs(n.vx ?? 0), Math.abs(n.vy ?? 0))).toBeLessThan(0.05);
  });

  it("hands a graph that is not settled in time back to the screen, still running", () => {
    const sim = make();
    let t = 0;
    expect(settleQuietly(sim, () => (t += 1000))).toBe(false);
    expect(sim.alpha()).toBeGreaterThan(0);
    sim.stop();
  });
});
