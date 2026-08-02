/**
 * Hand-authored demo graphs for the landing page (#344).
 *
 * Deliberately static. An earlier option generated these live from a public
 * endpoint, which was rejected: it puts an unauthenticated, billable LLM call
 * on the most-crawled page on the site. See the spec's "Rejected alternatives".
 *
 * Shapes mirror the real `graph_nodes` / `graph_edges` semantics — mastery
 * tiers included — so the colour language matches the app and the hero legend.
 */

export type MasteryTier = 'mastered' | 'learning' | 'struggling' | 'unexplored';

/**
 * The canonical knowledge-status palette — the SAME tokens the product uses.
 *
 * globals.css:80-89 declares these as the "Single source for the 3
 * previously-inlined copies in Dashboard / Tree / notetaker", and the app reads
 * them under exactly the four tier names below (notetaker/page.tsx,
 * screens/Dashboard.tsx, screens/Learn.tsx). This file shipped a FOURTH inlined
 * copy with four different literals — `#1B6C42` / `#D97706` / `#EF4444` /
 * `#9CA3AF` — so the landing page advertised different mastery colours than the
 * product it advertises, and the saturated amber root plus a `#EF4444` that
 * reads as an error state were the loudest objects on a page whose brand
 * atmosphere is "barely-there … like the glow under water" (#344 visual 1).
 *
 * Tokens, not hexes, on purpose: a future palette move lands here for free, and
 * the hero's floating legend card ((public)/page.tsx) now reads the same four.
 */
export const TIER_COLOR: Record<MasteryTier, string> = {
  mastered: 'var(--state-mastery)',
  learning: 'var(--state-progress)',
  struggling: 'var(--state-struggle)',
  unexplored: 'var(--state-neutral)',
};

/**
 * The product's own words for the four tiers — byte-identical to `TIER_META`
 * in `components/screens/Tree.tsx`, which is what a signed-in student reads
 * next to these same four colours. The landing page's legend has to teach the
 * vocabulary the app then uses, or it has taught the visitor nothing.
 */
export const TIER_LABEL: Record<MasteryTier, string> = {
  mastered: 'Mastered',
  learning: 'Learning',
  struggling: 'Struggling',
  unexplored: 'Unexplored',
};

/** Legend order: strongest first, so the ramp reads as a ramp. */
export const TIER_ORDER: readonly MasteryTier[] = [
  'mastered',
  'learning',
  'struggling',
  'unexplored',
] as const;

/**
 * The score → tier cutoffs, ported from `backend/config.py::get_mastery_tier`.
 *
 * The demo now draws a mastery ARC on every node, so each fixture node carries
 * a numeric `mastery` alongside its `tier` — two fields that can disagree. They
 * are held together by this function plus the fixture-integrity test, so a
 * hand-authored node whose ring says 90% can never be painted "struggling".
 * Same numbers as the backend on purpose: the ring a visitor reads here is the
 * ring they get after signing in.
 */
export function tierForMastery(score: number): MasteryTier {
  if (score >= 0.75) return 'mastered';
  if (score >= 0.45) return 'learning';
  if (score >= 0.1) return 'struggling';
  return 'unexplored';
}

export interface DemoNode {
  id: string;
  label: string;
  tier: MasteryTier;
  /**
   * Mastery score, 0–1. Drives the arc swept around the node's ring and the
   * meter in the detail panel. Must agree with `tier` via `tierForMastery`.
   * On the root this is the COURSE aggregate — the mean of its concepts —
   * which is also what the surface's chrome bar prints.
   */
  mastery: number;
  /** Shown on hover. One sentence, no trailing period. */
  blurb: string;
  /** Revealed when this node is expanded. Empty means leaf. */
  children: string[];
}

export interface DemoEdge {
  source: string;
  target: string;
}

export interface CourseGraph {
  id: string;
  /** Chip label, e.g. "CS 210". */
  code: string;
  name: string;
  rootId: string;
  /**
   * Concepts the real course carries. The demo draws a legible SLICE of them
   * (five plus the root), and the chrome bar says so — "5 of 19 shown" — so
   * the surface never implies a nineteen-concept course fits in six dots. Kept
   * in step with the root blurb and with `UploadSurface`'s "19 concepts mapped
   * onto MA 242" one band below.
   */
  conceptCount: number;
  nodes: DemoNode[];
  edges: DemoEdge[];
}

/** The drawn concepts — everything but the course anchor. */
export function conceptNodes(graph: CourseGraph): DemoNode[] {
  return graph.nodes.filter((n) => n.id !== graph.rootId);
}

/** Tier histogram over the drawn concepts. The legend's counts. */
export function tierCounts(graph: CourseGraph): Record<MasteryTier, number> {
  const counts: Record<MasteryTier, number> = {
    mastered: 0,
    learning: 0,
    struggling: 0,
    unexplored: 0,
  };
  for (const n of conceptNodes(graph)) counts[n.tier] += 1;
  return counts;
}

/**
 * Everything `id` shares a drawn edge with, in edge order.
 *
 * Reads `graph.edges` rather than `DemoNode.children` for the same reason
 * `layout.ts::spanningTree` does: `children` is dead data that disagrees with
 * the edges, and the detail panel's connection count has to be the count of
 * lines a visitor can see running out of that node.
 */
export function neighbours(graph: CourseGraph, id: string): DemoNode[] {
  const byId = new Map(graph.nodes.map((n) => [n.id, n]));
  const out: DemoNode[] = [];
  const seen = new Set<string>();
  for (const e of graph.edges) {
    const other = e.source === id ? e.target : e.target === id ? e.source : null;
    if (!other || seen.has(other)) continue;
    const node = byId.get(other);
    if (!node) continue;
    seen.add(other);
    out.push(node);
  }
  return out;
}

export const COURSE_GRAPHS: CourseGraph[] = [
  {
    id: 'cs210',
    code: 'CS 210',
    name: 'Data Structures',
    rootId: 'cs-root',
    conceptCount: 24,
    nodes: [
      { id: 'cs-root', label: 'CS 210', tier: 'learning', mastery: 0.482, blurb: 'Data Structures — 24 concepts mapped from your syllabus', children: ['cs-arrays', 'cs-recursion', 'cs-complexity'] },
      { id: 'cs-arrays', label: 'Arrays', tier: 'mastered', mastery: 0.9, blurb: 'Contiguous storage and index arithmetic', children: ['cs-sorting'] },
      { id: 'cs-recursion', label: 'Recursion', tier: 'struggling', mastery: 0.28, blurb: 'Base cases, call stack depth, and when to prefer iteration', children: ['cs-trees'] },
      { id: 'cs-complexity', label: 'Big-O', tier: 'learning', mastery: 0.62, blurb: 'Asymptotic bounds for time and space', children: [] },
      { id: 'cs-sorting', label: 'Sorting', tier: 'learning', mastery: 0.55, blurb: 'Comparison sorts and their lower bound', children: [] },
      { id: 'cs-trees', label: 'Trees', tier: 'unexplored', mastery: 0.06, blurb: 'Traversals, balance, and why recursion fits them', children: [] },
    ],
    edges: [
      { source: 'cs-root', target: 'cs-arrays' },
      { source: 'cs-root', target: 'cs-recursion' },
      { source: 'cs-root', target: 'cs-complexity' },
      { source: 'cs-arrays', target: 'cs-sorting' },
      { source: 'cs-recursion', target: 'cs-trees' },
      { source: 'cs-sorting', target: 'cs-complexity' },
    ],
  },
  {
    id: 'ma242',
    code: 'MA 242',
    name: 'Linear Algebra',
    rootId: 'ma-root',
    conceptCount: 19,
    nodes: [
      { id: 'ma-root', label: 'MA 242', tier: 'learning', mastery: 0.498, blurb: 'Linear Algebra — 19 concepts mapped from your syllabus', children: ['ma-vectors', 'ma-matrices', 'ma-eigen'] },
      { id: 'ma-vectors', label: 'Vector Spaces', tier: 'mastered', mastery: 0.93, blurb: 'Span, basis, and dimension', children: ['ma-independence'] },
      { id: 'ma-matrices', label: 'Matrices', tier: 'learning', mastery: 0.66, blurb: 'Linear maps written as arrays of numbers', children: ['ma-determinant'] },
      { id: 'ma-eigen', label: 'Eigenvalues', tier: 'struggling', mastery: 0.31, blurb: 'Directions a transformation only scales', children: [] },
      { id: 'ma-independence', label: 'Independence', tier: 'learning', mastery: 0.52, blurb: 'When no vector is redundant', children: [] },
      { id: 'ma-determinant', label: 'Determinant', tier: 'unexplored', mastery: 0.07, blurb: 'Signed volume scaling of a transformation', children: [] },
    ],
    edges: [
      { source: 'ma-root', target: 'ma-vectors' },
      { source: 'ma-root', target: 'ma-matrices' },
      { source: 'ma-root', target: 'ma-eigen' },
      { source: 'ma-vectors', target: 'ma-independence' },
      { source: 'ma-matrices', target: 'ma-determinant' },
      { source: 'ma-matrices', target: 'ma-eigen' },
    ],
  },
  {
    id: 'sm275',
    code: 'SM 275',
    name: 'Statistics',
    rootId: 'sm-root',
    conceptCount: 21,
    nodes: [
      { id: 'sm-root', label: 'SM 275', tier: 'learning', mastery: 0.47, blurb: 'Statistics — 21 concepts mapped from your syllabus', children: ['sm-prob', 'sm-dist', 'sm-testing'] },
      { id: 'sm-prob', label: 'Probability', tier: 'mastered', mastery: 0.86, blurb: 'Sample spaces, events, and conditioning', children: ['sm-bayes'] },
      { id: 'sm-dist', label: 'Distributions', tier: 'learning', mastery: 0.66, blurb: 'Shapes that recur across real data', children: ['sm-clt'] },
      // "Hypothesis Tests" was 16 characters — three more than any other label
      // in any fixture, and the widest object in the phone layout by a margin.
      // At the 390px breakpoint it overlapped its sibling "Distributions" by
      // ~21 CSS px of solid text (#344 visual 4, "worse at 390px"), and no
      // legible mobile type scale can separate them: the two labels need
      // 0.6·font·29/2 units of room against a ring that only yields 1.732·ring.
      // Shortening the label is the proportionate fix — not a collision solver.
      { id: 'sm-testing', label: 'p-Values', tier: 'struggling', mastery: 0.27, blurb: 'What a p-value does and does not claim', children: [] },
      { id: 'sm-bayes', label: 'Bayes', tier: 'learning', mastery: 0.53, blurb: 'Updating belief as evidence arrives', children: [] },
      { id: 'sm-clt', label: 'Central Limit', tier: 'unexplored', mastery: 0.03, blurb: 'Why sample means go normal', children: [] },
    ],
    edges: [
      { source: 'sm-root', target: 'sm-prob' },
      { source: 'sm-root', target: 'sm-dist' },
      { source: 'sm-root', target: 'sm-testing' },
      { source: 'sm-prob', target: 'sm-bayes' },
      { source: 'sm-dist', target: 'sm-clt' },
      { source: 'sm-dist', target: 'sm-testing' },
    ],
  },
];
