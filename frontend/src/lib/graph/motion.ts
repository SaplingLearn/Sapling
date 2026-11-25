/**
 * How the knowledge map moves: how a newly planned graph is settled and set
 * going (`settleQuietly`, `startPlanned`), and the idle drift — its gravity —
 * that keeps it alive once it has.
 *
 * A map that nothing is happening to is not dead still: once the layout has
 * settled, every node the simulation still owns keeps wandering a few units
 * around where it came to rest, the way the first Sapling maps breathed.
 * `KnowledgeGraph2D` registers `driftForce` alongside its link, charge,
 * collide and orbit forces, and the simulation is left running at
 * `IDLE_ALPHA` (`idle`) rather than stopped.
 *
 * None of the motion runs for a viewer who asked for reduced motion, or in a
 * NEXT_PUBLIC_TEST_MODE build (`driftAllowed`): there the graph is settled on
 * a fixed tick count and left stopped, so coordinates are identical on every
 * load.
 */

import type { Simulation, SimulationLinkDatum, SimulationNodeDatum } from "d3-force";

import { IS_TEST_MODE } from "@/lib/testMode";

// The drift itself. Each node is pushed by an acceleration of its own that
// turns slowly through a full circle, so it wanders instead of going
// anywhere: phase and turn rate come from the node's id, which keeps the
// motion the same on every load (no Math.random, nothing to re-measure) and
// stops any two nodes swinging together. Nothing else about the layout
// changes — the orbit and home springs bound the wander, and
// the simulation is only kept barely warm (IDLE_ALPHA), so those springs
// stay gentle and the planned layout is never re-run.
/** How hard the drift pushes a concept, per tick, before velocity decay.
 *  0.03 measured ~10 units of wander over five seconds, which at a normal
 *  zoom is a couple of screen pixels — indistinguishable from a dead stop.
 *  Tuned up until the motion is actually legible on screen. */
const DRIFT_ACCEL = 0.14;
/** How long one node's push takes to turn right round (ms). */
const DRIFT_TURN_MS = 13_000;
/** Course roots are anchors: they wander at half a concept's amplitude. */
const DRIFT_ROOT_SCALE = 0.5;
/** Below this heat a released concept adopts where it came to rest (the
 *  graph's follow force). The drift keeps every freed node moving faster than
 *  the follow force's speed exit, so this alpha exit is the only one left. */
export const SETTLE_ALPHA = 0.02;
/** The heat a drifting graph is held at — under SETTLE_ALPHA, or a released
 *  concept would never settle. */
export const IDLE_ALPHA = 0.015;
const TAU = Math.PI * 2;

/** A node's place in the drift: its phase, and how fast its push turns. */
const driftSeeds = new Map<string, number>();
function driftSeed(id: string): number {
  let seed = driftSeeds.get(id);
  if (seed === undefined) {
    // FNV-1a over the id: a stable number in [0, 1) for a stable id.
    let h = 0x811c9dc5;
    for (let i = 0; i < id.length; i++) {
      h ^= id.charCodeAt(i);
      h = Math.imul(h, 0x01000193);
    }
    seed = (h >>> 0) / 4294967296;
    driftSeeds.set(id, seed);
  }
  return seed;
}

export interface DriftNode {
  id: string;
  vx?: number;
  vy?: number;
  fx?: number | null;
  fy?: number | null;
  is_subject_root?: boolean;
}

/**
 * The "drift" force, one simulation tick: nudges every node the simulation
 * still owns. A node being dragged, or pinned where it was dropped (`fx`),
 * is left alone. Deliberately independent of alpha — the wander is the same
 * whether the graph is settling or idling. Exported for tests.
 */
export function driftForce(nodes: readonly DriftNode[], nowMs: number): void {
  for (const n of nodes) {
    if (n.fx != null || n.fy != null) continue;
    const seed = driftSeed(n.id);
    // ±25% on the turn rate, so the map never pulses as one.
    const phase = (nowMs / (DRIFT_TURN_MS * (0.75 + seed * 0.5)) + seed) * TAU;
    const push = n.is_subject_root ? DRIFT_ACCEL * DRIFT_ROOT_SCALE : DRIFT_ACCEL;
    n.vx = (n.vx ?? 0) + Math.cos(phase) * push;
    n.vy = (n.vy ?? 0) + Math.sin(phase) * push;
  }
}

/**
 * Hands a simulation back to the screen at its idle heat — drifting on for
 * ever (`drifting`), or settling to a stop where motion is not wanted. The
 * alpha is lifted to the target as well as aimed at it, because d3 stops its
 * timer as soon as alpha falls under alphaMin: a graph restarted from a dead
 * stop would otherwise tick once and stop again.
 */
export function idle<N extends SimulationNodeDatum, L extends SimulationLinkDatum<N>>(
  sim: Simulation<N, L>,
  drifting: boolean,
): void {
  if (!drifting) {
    sim.alphaTarget(0);
    return;
  }
  sim.alpha(Math.max(sim.alpha(), IDLE_ALPHA)).alphaTarget(IDLE_ALPHA).restart();
}

/** Whether this viewer asked, at the OS level, for less animation. */
export function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

/** Whether this viewer gets the idle drift at all. */
export function driftAllowed(): boolean {
  return !IS_TEST_MODE && !prefersReducedMotion();
}

/** The most ticks, and the most time, spent settling a graph before it is drawn. */
const QUIET_TICKS = 300;
const QUIET_MS = 150;
/** A graph whose fastest node moves less than this (graph units a tick) is at rest. */
const REST_SPEED = 0.05;

/**
 * Settles a newly planned graph before it is drawn: the simulation runs
 * synchronously, from where the plan put each node, until nothing moves,
 * so the first frame shows the graph at rest instead of shaking into place
 * (links pulling, concepts pushing apart, every course swinging out and
 * back). `tick()` fires no "tick" events: the caller re-renders. If time
 * runs out first (a huge graph on a slow machine), the rest plays out on
 * screen, already nearly still.
 */
export function settleQuietly<N extends SimulationNodeDatum, L extends SimulationLinkDatum<N>>(
  sim: Simulation<N, L>,
  now: () => number = () => performance.now(),
): boolean {
  sim.stop().alpha(0.9);
  const start = now();
  for (let i = 0; i < QUIET_TICKS; i++) {
    sim.tick();
    let fastest = 0;
    for (const n of sim.nodes()) fastest = Math.max(fastest, Math.abs(n.vx ?? 0), Math.abs(n.vy ?? 0));
    if (fastest < REST_SPEED) {
      sim.alpha(0);
      return true;
    }
    if (now() - start > QUIET_MS) break;
  }
  sim.restart();
  return false;
}

/**
 * Sets a newly planned simulation going, and says whether it is already at
 * rest when first drawn (the caller then frames it where it rests, at once).
 * "At rest" means the layout is done: the idle drift (driftForce) goes on
 * nudging nodes a few units about afterwards, which is why the simulation is
 * left running at IDLE_ALPHA rather than stopped.
 * Normally it is settled before it is drawn (`settleQuietly`). With reduced
 * motion — and in test mode, so node coordinates are identical on every
 * load — it settles synchronously on a fixed tick count, and is at rest
 * too. Mid-drag it plays on, on screen.
 */
export function startPlanned<N extends SimulationNodeDatum, L extends SimulationLinkDatum<N>>(
  sim: Simulation<N, L>,
  dragging: boolean,
): boolean {
  if (!driftAllowed()) {
    sim.alpha(1).tick(200).alpha(0).stop();
    return true;
  }
  if (dragging) {
    // Keep the drag's own alphaTarget: the release calls `idle`.
    sim.alpha(0.9).restart();
    return false;
  }
  settleQuietly(sim);
  // Settled, and drawn where it settled — then handed back to the screen at
  // its idle heat, where nothing but the drift moves anything (see `idle`).
  idle(sim, true);
  return true;
}

