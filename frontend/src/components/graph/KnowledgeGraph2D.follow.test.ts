import { describe, expect, it } from "vitest";
import GOLDEN from "./__fixtures__/knowledgeGraph2D.follow.golden.json";
import { followForce } from "./KnowledgeGraph2D";

/**
 * The drag "follow" force (ropes between a dragged concept and everything
 * linked to it), one simulation tick at a time. It used to live inline in the
 * simulation effect, closing over refs. The golden
 * (`__fixtures__/knowledgeGraph2D.follow.golden.json`) was captured from that
 * inline body, run verbatim on these scenarios (two ticks each), so the
 * extracted `followForce` is held to exactly the same per-tick math.
 */

type Node = { id: string; x?: number; y?: number; vx?: number; vy?: number; fx?: number | null; fy?: number | null };
type Tether = { leader: string | null; gap: number };
type Free = { leader: Map<string, Tether>; dragging: string | null };
type Orbit = { rootId: string | null; angle: number; radius: number };

const FOLLOW_PULL = 0.1;

type World = {
  free: Free;
  nodes: Node[];
  orbit: Map<string, Orbit>;
  width: number;
  height: number;
  settles: number;
};

/** One tick of `followForce`, wired the way the simulation effect wires it. */
function tick(world: World, alpha: number) {
  const nodeById = new Map(world.nodes.map((n) => [n.id, n]));
  const centerOf = (rootId: string | null) => {
    const root = rootId ? nodeById.get(rootId) : undefined;
    if (root && root.x != null && root.y != null) return { x: root.x, y: root.y };
    return { x: world.width / 2, y: world.height / 2 };
  };
  followForce(alpha, world.free, nodeById, world.orbit, centerOf, () => {
    world.settles += 1;
  });
}

const tethers = (entries: Array<[string, string | null, number]>) =>
  new Map(entries.map(([id, leader, gap]) => [id, { leader, gap }]));

/** Scenario builders: each returns a fresh world plus the alpha to tick at. */
const SCENARIOS: Record<string, () => { world: World; alpha: number }> = {
  "nothing freed": () => ({
    world: {
      free: { leader: new Map(), dragging: null },
      nodes: [{ id: "a", x: 0, y: 0 }],
      orbit: new Map(),
      width: 600,
      height: 480,
      settles: 0,
    },
    alpha: 0.5,
  }),
  "dragging: a stretched rope pulls a free follower; its orbit tracks it": () => ({
    world: {
      free: { leader: tethers([["a", null, 70], ["b", "a", 70], ["c", "b", 70]]), dragging: "a" },
      nodes: [
        { id: "root", x: 300, y: 240, fx: 300, fy: 240 },
        { id: "a", x: 500, y: 100, fx: 500, fy: 100 },
        { id: "b", x: 330, y: 260, vx: 0.5 },
        { id: "c", x: 320, y: 250 },
      ],
      orbit: new Map([
        ["a", { rootId: "root", angle: 0, radius: 80 }],
        ["b", { rootId: "root", angle: 1, radius: 80 }],
        ["c", { rootId: null, angle: 2, radius: 10 }],
      ]),
      width: 600,
      height: 480,
      settles: 0,
    },
    alpha: 0.3,
  }),
  "pinned follower pulls its free leader back": () => ({
    world: {
      free: { leader: tethers([["a", null, 70], ["root", "a", 70]]), dragging: "a" },
      nodes: [
        { id: "root", x: 300, y: 240, fx: 300, fy: 240 },
        { id: "a", x: 450, y: 400, vx: -1, vy: 2 },
      ],
      orbit: new Map([["a", { rootId: "root", angle: 0, radius: 80 }]]),
      width: 600,
      height: 480,
      settles: 0,
    },
    alpha: 0.3,
  }),
  "both ends pinned: no pull": () => ({
    world: {
      free: { leader: tethers([["a", null, 70], ["b", "a", 70]]), dragging: "a" },
      nodes: [
        { id: "a", x: 0, y: 0, fx: 0, fy: 0 },
        { id: "b", x: 300, y: 300, fx: 300, fy: 300 },
      ],
      orbit: new Map(),
      width: 600,
      height: 480,
      settles: 0,
    },
    alpha: 0.3,
  }),
  "slack rope and coincident ends: no pull, unpositioned nodes skipped": () => ({
    world: {
      free: {
        leader: tethers([["a", null, 70], ["b", "a", 200], ["c", "a", 70], ["d", "a", 70], ["e", "ghost", 70], ["z", "a", 70]]),
        dragging: null,
      },
      nodes: [
        { id: "a", x: 100, y: 100 },
        { id: "b", x: 150, y: 120 },
        { id: "c", x: 100, y: 100 },
        { id: "d" },
        { id: "e", x: 50, y: 60, vx: 0.05, vy: 0.05 },
      ],
      orbit: new Map([["d", { rootId: null, angle: 0, radius: 0 }]]),
      width: 600,
      height: 480,
      settles: 0,
    },
    alpha: 0.5,
  }),
  "released and still moving at high alpha: keeps going": () => ({
    world: {
      free: { leader: tethers([["a", null, 70], ["b", "a", 70]]), dragging: null },
      nodes: [
        { id: "a", x: 100, y: 100, vx: 3, vy: -2 },
        { id: "b", x: 400, y: 300 },
      ],
      orbit: new Map([
        ["a", { rootId: "nope", angle: 0, radius: 0 }],
        ["b", { rootId: null, angle: 0, radius: 0 }],
      ]),
      width: 600,
      height: 480,
      settles: 0,
    },
    alpha: 0.5,
  }),
  "released and still moving below the alpha floor: settles": () => ({
    world: {
      free: { leader: tethers([["a", null, 70], ["b", "a", 70]]), dragging: null },
      nodes: [
        { id: "a", x: 100, y: 100, vx: 3, vy: -2 },
        { id: "b", x: 400, y: 300 },
      ],
      orbit: new Map(),
      width: 600,
      height: 480,
      settles: 0,
    },
    alpha: 0.01,
  }),
  "released and at rest: settles": () => ({
    world: {
      free: { leader: tethers([["a", null, 70], ["b", "a", 70]]), dragging: null },
      nodes: [
        { id: "a", x: 100, y: 100, vx: 0.01, vy: 0 },
        { id: "b", x: 120, y: 110 },
      ],
      orbit: new Map(),
      width: 600,
      height: 480,
      settles: 0,
    },
    alpha: 0.5,
  }),
};

/** A plain snapshot of everything the force can mutate. */
function stateOf(world: World) {
  return {
    nodes: world.nodes.map((n) => ({ ...n })),
    orbit: [...world.orbit.entries()].map(([id, o]) => [id, { ...o }]),
    settles: world.settles,
  };
}

describe("followForce", () => {
  it.each(Object.keys(SCENARIOS))("matches the pre-extraction inline force over two ticks: %s", (name) => {
    const { world, alpha } = SCENARIOS[name]();
    tick(world, alpha);
    tick(world, alpha);
    expect(stateOf(world)).toEqual((GOLDEN as Record<string, unknown>)[name]);
  });

  it("never pulls on a NaN slack", () => {
    const world: World = {
      free: { leader: tethers([["a", null, 70], ["b", "a", NaN]]), dragging: "a" },
      nodes: [
        { id: "a", x: 0, y: 0 },
        { id: "b", x: 300, y: 300, vx: 0, vy: 0 },
      ],
      orbit: new Map(),
      width: 600,
      height: 480,
      settles: 0,
    };
    tick(world, 0.3);
    expect(world.nodes[1]).toEqual({ id: "b", x: 300, y: 300, vx: 0, vy: 0 });
  });

  it("does nothing with no freed nodes", () => {
    const { world, alpha } = SCENARIOS["nothing freed"]();
    const before = stateOf(world);
    tick(world, alpha);
    expect(stateOf(world)).toEqual(before);
  });

  it("pulls a free follower along a stretched rope and moves its orbit target", () => {
    const { world, alpha } = SCENARIOS["dragging: a stretched rope pulls a free follower; its orbit tracks it"]();
    tick(world, alpha);
    const b = world.nodes.find((n) => n.id === "b")!;
    const dx = 500 - 330;
    const dy = 100 - 260;
    const len = Math.hypot(dx, dy);
    expect(b.vx).toBe(0.5 + (dx / len) * (len - 70) * FOLLOW_PULL);
    expect(b.vy).toBe(0 + (dy / len) * (len - 70) * FOLLOW_PULL);
    // The dragged node's orbit is left alone; the follower's tracks it.
    expect(world.orbit.get("a")).toEqual({ rootId: "root", angle: 0, radius: 80 });
    expect(world.orbit.get("b")).toEqual({
      rootId: "root",
      angle: Math.atan2(260 - 240, 330 - 300),
      radius: Math.max(40, Math.hypot(30, 20)),
    });
    // A rootless orbit tracks the window centre.
    expect(world.orbit.get("c")!.angle).toBe(Math.atan2(250 - 240, 320 - 300));
    expect(world.settles).toBe(0);
  });

  it("pulls the leader back when the follower is pinned", () => {
    const { world, alpha } = SCENARIOS["pinned follower pulls its free leader back"]();
    tick(world, alpha);
    const a = world.nodes.find((n) => n.id === "a")!;
    const dx = 450 - 300;
    const dy = 400 - 240;
    const len = Math.hypot(dx, dy);
    expect(a.vx).toBe(-1 - (dx / len) * (len - 70) * FOLLOW_PULL);
    expect(a.vy).toBe(2 - (dy / len) * (len - 70) * FOLLOW_PULL);
  });

  it("settles only once released and slow (or below the alpha floor)", () => {
    const settles = (name: string) => {
      const { world, alpha } = SCENARIOS[name]();
      tick(world, alpha);
      return world.settles;
    };
    expect(settles("both ends pinned: no pull")).toBe(0);
    expect(settles("released and still moving at high alpha: keeps going")).toBe(0);
    expect(settles("released and still moving below the alpha floor: settles")).toBe(1);
    expect(settles("released and at rest: settles")).toBe(1);
    expect(settles("slack rope and coincident ends: no pull, unpositioned nodes skipped")).toBe(1);
  });
});

