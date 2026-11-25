/**
 * The idle drift: with nothing happening, every node the simulation owns
 * keeps wandering a few units about where it rests (see `driftForce`).
 *
 * The force itself is pure, so it is pinned here on its own: the whole-graph
 * behaviour it produces — a map that is drawn where it settles and stays
 * within a few units of there for ever — is pinned in
 * `components/graph/KnowledgeGraph2D.load.test.tsx`.
 */

import { describe, expect, it } from "vitest";
import { driftForce, type DriftNode } from "./motion";

const node = (id: string, extra: Partial<DriftNode> = {}): DriftNode => ({ id, vx: 0, vy: 0, ...extra });
const speed = (n: DriftNode) => Math.hypot(n.vx ?? 0, n.vy ?? 0);

/** Where a node ends up after `ms` of nothing but the drift and d3's decay. */
function wander(n: DriftNode, ms: number, from = 0): { x: number; y: number } {
  let x = 0, y = 0;
  for (let t = from; t < from + ms; t += 1000 / 60) {
    driftForce([n], t);
    n.vx = (n.vx ?? 0) * 0.6;
    n.vy = (n.vy ?? 0) * 0.6;
    x += n.vx ?? 0;
    y += n.vy ?? 0;
  }
  return { x, y };
}

describe("driftForce", () => {
  it("nudges a node that the simulation owns", () => {
    const n = node("concept-1");
    driftForce([n], 0);
    expect(speed(n)).toBeGreaterThan(0);
  });

  it("leaves a held node alone — dragged, or pinned where it was dropped", () => {
    const held = node("concept-1", { fx: 10, fy: 20 });
    driftForce([held], 0);
    expect(speed(held)).toBe(0);
  });

  it("pushes a course root more gently than a concept", () => {
    const concept = node("same-id");
    const root = node("same-id", { is_subject_root: true });
    driftForce([concept, root], 0);
    expect(speed(root)).toBeCloseTo(speed(concept) / 2);
  });

  it("is the same on every load: the push comes from the node's id, not chance", () => {
    const a = node("concept-1");
    const b = node("concept-1");
    driftForce([a], 1234);
    driftForce([b], 1234);
    expect([b.vx, b.vy]).toEqual([a.vx, a.vy]);
  });

  it("never has two nodes swinging together", () => {
    const a = node("concept-1");
    const b = node("concept-2");
    driftForce([a, b], 0);
    driftForce([a, b], 4000);
    expect(Math.abs((a.vx ?? 0) - (b.vx ?? 0))).toBeGreaterThan(0.001);
  });

  // Both bounds below scale with DRIFT_ACCEL, raised 0.03 -> 0.14 on
  // 2026-11-25 because the old amplitude was invisible on screen. What they
  // assert is the SHAPE of the motion, not the number: that the push cancels
  // itself over a full turn, and that a second of it is neither nothing nor a
  // leap. Re-scale them if the constant moves again.

  it("turns right round, so a node wanders rather than flying off", () => {
    // Over a full turn the push cancels itself: the node comes back.
    const n = node("concept-1");
    const far = wander(n, 60_000);
    expect(Math.hypot(far.x, far.y)).toBeLessThan(56);
  });

  it("wanders a few units, not pixels at a time", () => {
    const n = node("concept-1");
    const moved = wander(n, 1000);
    expect(Math.hypot(moved.x, moved.y)).toBeGreaterThan(0.9);
    expect(Math.hypot(moved.x, moved.y)).toBeLessThan(28);
  });
});
