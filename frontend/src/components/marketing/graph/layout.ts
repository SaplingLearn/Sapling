/**
 * Layout + entry-path math for the landing graph demo (#344).
 *
 * Deterministic by construction — no randomness, no time input. The E2E lane
 * parks the animation and asserts against the laid-out frame, so the same graph
 * and viewport must always produce the same coordinates.
 */
import type { CourseGraph } from './courseGraphs';

export interface Point {
  x: number;
  y: number;
}

function clamp01(t: number): number {
  return t < 0 ? 0 : t > 1 ? 1 : t;
}

export function easeOutCubic(t: number): number {
  const c = clamp01(t);
  return 1 - Math.pow(1 - c, 3);
}

/**
 * Root at the centre, each BFS depth on its own ring, siblings spread evenly
 * around it. Alternate rings are rotated by half a slot so spokes don't line
 * up into visual spokes.
 */
export function radialLayout(
  graph: CourseGraph,
  width: number,
  height: number,
): Map<string, Point> {
  const adj = new Map<string, string[]>();
  for (const e of graph.edges) {
    adj.set(e.source, [...(adj.get(e.source) ?? []), e.target]);
    adj.set(e.target, [...(adj.get(e.target) ?? []), e.source]);
  }

  const depth = new Map<string, number>([[graph.rootId, 0]]);
  const queue = [graph.rootId];
  while (queue.length) {
    const cur = queue.shift()!;
    for (const nxt of adj.get(cur) ?? []) {
      if (!depth.has(nxt)) {
        depth.set(nxt, depth.get(cur)! + 1);
        queue.push(nxt);
      }
    }
  }

  const byDepth = new Map<number, string[]>();
  // Iterate graph.nodes (declaration order), not the Map, so ring ordering is
  // stable regardless of BFS visit order.
  for (const n of graph.nodes) {
    const d = depth.get(n.id) ?? 0;
    byDepth.set(d, [...(byDepth.get(d) ?? []), n.id]);
  }

  const cx = width / 2;
  const cy = height / 2;
  const maxDepth = Math.max(...byDepth.keys(), 1);
  const ring = (Math.min(width, height) / 2 - 48) / maxDepth;

  const out = new Map<string, Point>();
  for (const [d, ids] of byDepth) {
    if (d === 0) {
      for (const id of ids) out.set(id, { x: cx, y: cy });
      continue;
    }
    const step = (Math.PI * 2) / ids.length;
    const offset = d % 2 === 0 ? step / 2 : 0;
    ids.forEach((id, i) => {
      const a = i * step + offset - Math.PI / 2;
      out.set(id, {
        x: cx + Math.cos(a) * ring * d,
        y: cy + Math.sin(a) * ring * d,
      });
    });
  }
  return out;
}

/**
 * Position along the helical entry path. `t` runs 0 → 1.
 *
 * The node spirals inward: its offset from the centre is rotated by a
 * decreasing angle and stretched outward by a decreasing factor, while scale
 * and opacity rise. At t=1 every term collapses and the node sits exactly on
 * `target`, so the animation has no seam where it hands off to the static
 * layout.
 */
export function helixEntry(
  target: Point,
  centre: Point,
  t: number,
  turns = 1.5,
): { x: number; y: number; scale: number; opacity: number } {
  const e = easeOutCubic(t);
  const dx = target.x - centre.x;
  const dy = target.y - centre.y;

  const angle = (1 - e) * turns * Math.PI * 2;
  const stretch = 1 + (1 - e) * 0.9;
  const cos = Math.cos(angle);
  const sin = Math.sin(angle);

  return {
    x: centre.x + (dx * cos - dy * sin) * stretch,
    y: centre.y + (dx * sin + dy * cos) * stretch,
    scale: 0.35 + 0.65 * e,
    opacity: e,
  };
}
