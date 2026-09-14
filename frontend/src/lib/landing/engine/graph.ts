/**
 * Builds the projected 3D knowledge graph for Act I / explore mode.
 *
 * Ported from `Sapling Landing v4.dc.html`. Node 0 is the course itself,
 * anchoring the middle; each topic becomes a hub wired to it, and each hub
 * gets its five concepts arranged on a tilted ellipse around it.
 *
 * `spawnAt` / `colorAt` / `drawAt` are scroll-progress thresholds baked in at
 * build time: the reveal order is shuffled once so the graph assembles
 * organically rather than sweeping left-to-right.
 */

import { COURSE, XTIER, type MasteryTier } from '../course';

export interface GraphNode {
  /** Authored 3D position, pre-projection. */
  ox: number;
  oy: number;
  oz: number;
  /** Base radius in CSS pixels, before projection scale. */
  r: number;
  label: string;
  root?: boolean;
  hub: boolean;
  tier: MasteryTier;
  mastery: number;
  blurb: string;
  /** The tier colour this node lerps to as it reveals. */
  final: string;
  /** Per-node phase offset, so the breathing/wobble never syncs up. */
  seed: number;
  /** Index into COURSE.topics; undefined on the root. */
  topic?: number;
  /** Scroll progress at which this node starts to appear. */
  spawnAt: number;
  /** Scroll progress at which it starts grey → tier-colour. */
  colorAt: number;
}

export interface GraphEdge {
  a: number;
  b: number;
  /** True for the hand-picked cross-unit links, which draw fainter. */
  cross?: boolean;
  drawAt: number;
}

export interface BuiltGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
  /** Adjacency list, indexed by node. */
  adj: number[][];
}

/** The real cross-unit dependencies, drawn fainter than structural edges. */
const CROSS_LINKS: [string, string][] = [
  ['Recursion', 'Traversals'],
  ['Recursion', 'DFS'],
  ['Memoization', 'Dynamic programming'],
  ['Heaps', 'Dijkstra'],
  ['Heap sort', 'Heaps'],
  ['Complexity', 'Sorting'],
  ['Recurrences', 'Merge sort'],
  ['Hashing', 'Union-find'],
  ['Optimal substructure', 'Greedy vs DP'],
];

export function buildGraph(): BuiltGraph {
  const nodes: GraphNode[] = [];
  const edges: GraphEdge[] = [];

  // 0 = the class itself, anchoring the middle
  nodes.push({
    ox: 0, oy: 0, oz: 0, r: 12,
    label: COURSE.code, root: true, hub: true,
    tier: 'learning', mastery: 0.55, blurb: COURSE.blurb,
    final: '#0E9E5A', seed: Math.random() * 100,
    spawnAt: 0, colorAt: 0,
  });

  COURSE.topics.forEach((tp, ti) => {
    const hi = nodes.length;
    nodes.push({
      ox: tp.at[0], oy: tp.at[1], oz: tp.at[2], r: 7.5,
      label: tp.label, hub: true,
      tier: tp.tier, mastery: tp.mastery, blurb: tp.blurb,
      final: XTIER[tp.tier], seed: Math.random() * 100, topic: ti,
      spawnAt: 0, colorAt: 0,
    });
    edges.push({ a: 0, b: hi, drawAt: 0 });

    const tilt = ti * 0.9;
    const R = 158;
    tp.subs.forEach((sb, k) => {
      const idx = nodes.length;
      const a = (k / tp.subs.length) * Math.PI * 2 + tilt;
      // deterministic per-index jitter, so the ring isn't a perfect circle
      const j = 0.84 + (((k * 37) % 11) / 11) * 0.32;
      nodes.push({
        ox: tp.at[0] + Math.cos(a) * R * j,
        oy: tp.at[1] + Math.sin(a) * R * 0.72 * j,
        oz: tp.at[2] + Math.sin(a * 1.7 + tilt) * R * 0.8,
        r: 3.2 + sb.mastery * 3.4,
        label: sb.label, hub: false,
        tier: sb.tier, mastery: sb.mastery, blurb: sb.blurb,
        final: XTIER[sb.tier], seed: Math.random() * 100, topic: ti,
        spawnAt: 0, colorAt: 0,
      });
      edges.push({ a: hi, b: idx, drawAt: 0 });
      // chain every other sibling, so each ring reads as a loop not a fan
      if (k > 0 && k % 2 === 0) edges.push({ a: idx, b: idx - 1, drawAt: 0 });
    });
  });

  const find = (l: string) => nodes.findIndex((n) => n.label === l);
  CROSS_LINKS.forEach(([x, y]) => {
    const a = find(x);
    const b = find(y);
    if (a >= 0 && b >= 0) edges.push({ a, b, cross: true, drawAt: 0 });
  });

  // Shuffle the reveal order so the graph assembles organically.
  const order = nodes.map((_, i) => i).sort(() => Math.random() - 0.5);
  order.forEach((idx, k) => {
    nodes[idx].spawnAt = 0.02 + (k / nodes.length) * 0.2;
    nodes[idx].colorAt = 0.5 + (k / nodes.length) * 0.2;
  });
  // the course node always leads, whatever the shuffle said
  nodes[0].spawnAt = 0.02;
  nodes[0].colorAt = 0.46;
  edges.forEach((e, k) => {
    e.drawAt = 0.26 + (k / edges.length) * 0.2;
  });

  const adj: number[][] = nodes.map(() => []);
  edges.forEach((e) => {
    adj[e.a].push(e.b);
    adj[e.b].push(e.a);
  });

  return { nodes, edges, adj };
}
