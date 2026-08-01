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

export interface DemoNode {
  id: string;
  label: string;
  tier: MasteryTier;
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
  nodes: DemoNode[];
  edges: DemoEdge[];
}

export const COURSE_GRAPHS: CourseGraph[] = [
  {
    id: 'cs210',
    code: 'CS 210',
    name: 'Data Structures',
    rootId: 'cs-root',
    nodes: [
      { id: 'cs-root', label: 'CS 210', tier: 'learning', blurb: 'Data Structures — 24 concepts mapped from your syllabus', children: ['cs-arrays', 'cs-recursion', 'cs-complexity'] },
      { id: 'cs-arrays', label: 'Arrays', tier: 'mastered', blurb: 'Contiguous storage and index arithmetic', children: ['cs-sorting'] },
      { id: 'cs-recursion', label: 'Recursion', tier: 'struggling', blurb: 'Base cases, call stack depth, and when to prefer iteration', children: ['cs-trees'] },
      { id: 'cs-complexity', label: 'Big-O', tier: 'learning', blurb: 'Asymptotic bounds for time and space', children: [] },
      { id: 'cs-sorting', label: 'Sorting', tier: 'learning', blurb: 'Comparison sorts and their lower bound', children: [] },
      { id: 'cs-trees', label: 'Trees', tier: 'unexplored', blurb: 'Traversals, balance, and why recursion fits them', children: [] },
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
    nodes: [
      { id: 'ma-root', label: 'MA 242', tier: 'learning', blurb: 'Linear Algebra — 19 concepts mapped from your syllabus', children: ['ma-vectors', 'ma-matrices', 'ma-eigen'] },
      { id: 'ma-vectors', label: 'Vector Spaces', tier: 'mastered', blurb: 'Span, basis, and dimension', children: ['ma-independence'] },
      { id: 'ma-matrices', label: 'Matrices', tier: 'learning', blurb: 'Linear maps written as arrays of numbers', children: ['ma-determinant'] },
      { id: 'ma-eigen', label: 'Eigenvalues', tier: 'struggling', blurb: 'Directions a transformation only scales', children: [] },
      { id: 'ma-independence', label: 'Independence', tier: 'learning', blurb: 'When no vector is redundant', children: [] },
      { id: 'ma-determinant', label: 'Determinant', tier: 'unexplored', blurb: 'Signed volume scaling of a transformation', children: [] },
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
    nodes: [
      { id: 'sm-root', label: 'SM 275', tier: 'learning', blurb: 'Statistics — 21 concepts mapped from your syllabus', children: ['sm-prob', 'sm-dist', 'sm-testing'] },
      { id: 'sm-prob', label: 'Probability', tier: 'mastered', blurb: 'Sample spaces, events, and conditioning', children: ['sm-bayes'] },
      { id: 'sm-dist', label: 'Distributions', tier: 'learning', blurb: 'Shapes that recur across real data', children: ['sm-clt'] },
      // "Hypothesis Tests" was 16 characters — three more than any other label
      // in any fixture, and the widest object in the phone layout by a margin.
      // At the 390px breakpoint it overlapped its sibling "Distributions" by
      // ~21 CSS px of solid text (#344 visual 4, "worse at 390px"), and no
      // legible mobile type scale can separate them: the two labels need
      // 0.6·font·29/2 units of room against a ring that only yields 1.732·ring.
      // Shortening the label is the proportionate fix — not a collision solver.
      { id: 'sm-testing', label: 'p-Values', tier: 'struggling', blurb: 'What a p-value does and does not claim', children: [] },
      { id: 'sm-bayes', label: 'Bayes', tier: 'learning', blurb: 'Updating belief as evidence arrives', children: [] },
      { id: 'sm-clt', label: 'Central Limit', tier: 'unexplored', blurb: 'Why sample means go normal', children: [] },
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
