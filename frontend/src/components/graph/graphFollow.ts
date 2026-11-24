// The drag's follow physics (moved out of KnowledgeGraph2D.tsx unchanged):
// dragging a concept frees it and everything linked to it, which follow it on
// ropes; each freed concept's orbit tracks it, and wherever it all comes to
// rest becomes the layout.
import type { SimulationNodeDatum } from "d3-force";
import { ROOT_ROOM } from "@/lib/graph/radialLayout";

/** A link may always stretch to at least this before it pulls (px). */
export const FOLLOW_GAP = 70;
/** Share of the extra stretch closed per tick (before velocity decay). */
const FOLLOW_PULL = 0.1;

/**
 * Everything a dragged concept is connected to, through concept links and
 * course spokes alike, each mapped to the node it was reached through (its
 * leader, so the tree of who pulls whom). The dragged concept maps to null.
 */
export function followersOf(
  dragId: string,
  links: ReadonlyArray<{ source: string | { id: string }; target: string | { id: string } }>,
  hops = Infinity,
): Map<string, string | null> {
  const idOf = (end: string | { id: string }) => (typeof end === "string" ? end : end.id);
  const adjacent = new Map<string, string[]>();
  for (const l of links) {
    const s = idOf(l.source);
    const t = idOf(l.target);
    if (!adjacent.has(s)) adjacent.set(s, []);
    if (!adjacent.has(t)) adjacent.set(t, []);
    adjacent.get(s)!.push(t);
    adjacent.get(t)!.push(s);
  }
  const leader = new Map<string, string | null>([[dragId, null]]);
  let frontier = [dragId];
  for (let hop = 0; hop < hops && frontier.length; hop++) {
    const next: string[] = [];
    for (const id of frontier) {
      for (const m of adjacent.get(id) ?? []) {
        if (leader.has(m)) continue;
        leader.set(m, id);
        next.push(m);
      }
    }
    frontier = next;
  }
  return leader;
}

/**
 * A freed node's rope to the node that leads it (null for the dragged one)
 * and its length: as long as their link was when the drag began.
 */
export type Tether = { leader: string | null; gap: number };
/** Freed nodes while a drag plays out, and the node being dragged (if any). */
export type FreeNodes = { leader: Map<string, Tether>; dragging: string | null };
type FollowNode = Pick<SimulationNodeDatum, "x" | "y" | "vx" | "vy" | "fx">;
export type OrbitSlot = { rootId: string | null; angle: number; radius: number };

/**
 * The nearest a concept may come to rest to what it sits round: clear of
 * its course root's mark and course code (`ROOT_ROOM`, as it was planned),
 * however a drag pushed the two together; with no root, just off the middle.
 */
export const restFloor = (rootId: string | null) => (rootId ? ROOT_ROOM : 40);

/**
 * A rope stretched past its length pulls the follower `n` after its leader
 * `l` — or, when the follower is pinned (a classic-layout course root), pulls
 * the leader back instead. `n` is positioned (the caller checked).
 */
function pullAlongRope(n: FollowNode, l: FollowNode | undefined, gap: number): void {
  if (!l || l.x == null || l.y == null) return;
  const dx = l.x - n.x!;
  const dy = l.y - n.y!;
  const len = Math.hypot(dx, dy) || 1e-6;
  const slack = len - gap;
  // Not `slack <= 0`: a NaN slack must not pull, as before.
  if (!(slack > 0)) return;
  const px = (dx / len) * slack * FOLLOW_PULL;
  const py = (dy / len) * slack * FOLLOW_PULL;
  if (n.fx == null) {
    n.vx = (n.vx ?? 0) + px;
    n.vy = (n.vy ?? 0) + py;
  } else if (l.fx == null) {
    l.vx = (l.vx ?? 0) - px;
    l.vy = (l.vy ?? 0) - py;
  }
}

/**
 * The "follow" force, one simulation tick. Freed nodes (`free`): each rope
 * stretched past its length pulls (see `pullAlongRope`). Each freed concept's
 * orbit target tracks it so the orbit force (next) doesn't hold it on its old
 * ring. Once everything has slowed down, wherever it all came to rest becomes
 * the layout (`settle`). Runs every tick: allocates nothing beyond `centerOf`.
 * Exported for tests.
 */
export function followForce(
  alpha: number,
  free: FreeNodes,
  nodeById: ReadonlyMap<string, FollowNode>,
  orbit: ReadonlyMap<string, OrbitSlot>,
  centerOf: (rootId: string | null) => { x: number; y: number },
  settle: () => void,
): void {
  if (!free.leader.size) return;
  let moving = free.dragging != null;
  for (const [id, { leader: leaderId, gap }] of free.leader) {
    const n = nodeById.get(id);
    if (!n || n.x == null || n.y == null) continue;
    pullAlongRope(n, leaderId ? nodeById.get(leaderId) : undefined, gap);
    const o = orbit.get(id);
    if (o && id !== free.dragging) {
      const c = centerOf(o.rootId);
      o.angle = Math.atan2(n.y - c.y, n.x - c.x);
      // Never nearer its course root than it was planned to be: a course
      // dragged into its own concepts parts them, and the orbit force (next)
      // moves any it ran into back out to this distance.
      o.radius = Math.max(restFloor(o.rootId), Math.hypot(n.x - c.x, n.y - c.y));
    }
    if (Math.hypot(n.vx ?? 0, n.vy ?? 0) >= 0.1) moving = true;
  }
  if (!moving || (free.dragging == null && alpha < 0.02)) settle();
}
