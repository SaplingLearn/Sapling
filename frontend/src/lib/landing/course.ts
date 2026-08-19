/**
 * The one hard-coded course graph the whole v4 landing page is built on.
 *
 * Ported verbatim from `Sapling Landing v4.dc.html`. This is not decorative
 * filler: Act I's projected 3D graph, explore mode, and the gallery all
 * render this same data. Seven units, 42 concepts (7 topics x 5 subs, plus
 * the 7 topic nodes themselves), each carrying a mastery tier and score.
 *
 * Node positions (`at`) are authored in the source's own 3D space and are
 * projected to screen space by the scroll engine — treat them as fixed
 * layout, not as tunable values.
 */

export type MasteryTier = 'mastered' | 'learning' | 'struggling' | 'unexplored';

/**
 * The four tier colours. Non-negotiable — every act keys off these exact
 * values.
 *
 * `unexplored` is byte-identical to the app's `--state-neutral` /
 * `--fallback-muted` (#9a9a9a) today, but it is kept literal here for the
 * same reason `--fallback-muted` exists in globals.css: it is a distinct
 * concept, so a future change to the app's neutral state must not silently
 * move a landing-page mastery tier.
 */
export const XTIER: Record<MasteryTier, string> = {
  mastered: '#0E9E5A',
  learning: '#4FA574',
  struggling: '#E27A63',
  unexplored: '#9a9a9a',
};

export const XTIER_LABEL: Record<MasteryTier, string> = {
  mastered: 'Mastered',
  learning: 'Learning',
  struggling: 'Struggling',
  unexplored: 'Unexplored',
};

/** Legend / filter order. Deliberately best-to-worst, not alphabetical. */
export const XTIER_ORDER: MasteryTier[] = ['mastered', 'learning', 'struggling', 'unexplored'];

/** Anything the graph can render a mastery ring for. */
export interface GraphNode {
  label: string;
  tier: MasteryTier;
  /** 0..1. Drives the ring fill and the review queue position. */
  mastery: number;
  blurb: string;
}

export type SubTopic = GraphNode;

export interface Topic extends GraphNode {
  /** Authored position in the source's 3D space: [x, y, z]. */
  at: [number, number, number];
  subs: SubTopic[];
}

export interface Course {
  code: string;
  name: string;
  term: string;
  blurb: string;
  topics: Topic[];
}

export const COURSE: Course = {
  code: 'CS 112',
  name: 'Data Structures & Algorithms',
  term: 'FALL 2026',
  blurb:
    'Everything your syllabus, uploads, and sessions have taught Sapling about this course: 42 concepts across 7 units.',
  topics: [
    {
      label: 'Trees',
      tier: 'learning',
      mastery: 0.61,
      at: [-430, -170, 90],
      blurb: 'Hierarchies with a single root, the shape half this course reduces to.',
      subs: [
        {
          label: 'Binary search trees',
          tier: 'mastered',
          mastery: 0.91,
          blurb: 'Ordered structure: everything left is smaller, everything right is larger.',
        },
        {
          label: 'AVL rotations',
          tier: 'struggling',
          mastery: 0.24,
          blurb: 'Four cases, LL, LR, RL and RR, that restore height balance after an insert.',
        },
        {
          label: 'Red-black trees',
          tier: 'struggling',
          mastery: 0.19,
          blurb: 'Balance amortized through color invariants instead of strict height.',
        },
        {
          label: 'Traversals',
          tier: 'mastered',
          mastery: 0.88,
          blurb: 'In-order, pre-order, post-order: each reads the same tree differently.',
        },
        {
          label: 'Heaps',
          tier: 'learning',
          mastery: 0.57,
          blurb: 'Partial order that makes the extreme element O(1) to find.',
        },
      ],
    },
    {
      label: 'Graphs',
      tier: 'learning',
      mastery: 0.54,
      at: [70, -300, -150],
      blurb: 'Nodes and edges with no root, so traversal order becomes a real choice.',
      subs: [
        {
          label: 'BFS',
          tier: 'mastered',
          mastery: 0.86,
          blurb: 'Level-by-level with a queue; shortest path on unweighted edges.',
        },
        {
          label: 'DFS',
          tier: 'mastered',
          mastery: 0.82,
          blurb: 'Follow one path to exhaustion, by recursion or an explicit stack.',
        },
        {
          label: 'Dijkstra',
          tier: 'learning',
          mastery: 0.48,
          blurb: 'Greedy shortest path with a priority queue; no negative edges.',
        },
        {
          label: 'Topological sort',
          tier: 'struggling',
          mastery: 0.27,
          blurb: 'Linear order on a DAG where every edge points forward.',
        },
        {
          label: 'Union-find',
          tier: 'unexplored',
          mastery: 0.04,
          blurb: 'Disjoint sets with path compression, the backbone of Kruskal.',
        },
      ],
    },
    {
      label: 'Sorting',
      tier: 'mastered',
      mastery: 0.79,
      at: [470, -130, 60],
      blurb: 'Comparison sorts, their trade-offs, and the n log n lower bound.',
      subs: [
        {
          label: 'Merge sort',
          tier: 'mastered',
          mastery: 0.93,
          blurb: 'Divide, sort halves, merge: stable and reliably n log n.',
        },
        {
          label: 'Quick sort',
          tier: 'mastered',
          mastery: 0.84,
          blurb: 'Partition around a pivot; fast in practice, quadratic in the worst case.',
        },
        {
          label: 'Heap sort',
          tier: 'learning',
          mastery: 0.63,
          blurb: 'Build a heap, then extract repeatedly: in place, not stable.',
        },
        {
          label: 'Counting sort',
          tier: 'learning',
          mastery: 0.55,
          blurb: 'Beats the comparison bound by not comparing at all.',
        },
        {
          label: 'Stability',
          tier: 'mastered',
          mastery: 0.8,
          blurb: 'Whether equal keys keep their original relative order.',
        },
      ],
    },
    {
      label: 'Recursion',
      tier: 'struggling',
      mastery: 0.33,
      at: [-140, 300, 210],
      blurb: 'Your weakest unit. Base cases and stack depth account for most misses.',
      subs: [
        {
          label: 'Base cases',
          tier: 'struggling',
          mastery: 0.31,
          blurb: 'The stopping condition; get it wrong and everything else is noise.',
        },
        {
          label: 'Call stack depth',
          tier: 'struggling',
          mastery: 0.22,
          blurb: 'Every frame costs memory, which is why deep recursion overflows.',
        },
        {
          label: 'Backtracking',
          tier: 'learning',
          mastery: 0.5,
          blurb: 'Try, recurse, undo: search that explores and retracts.',
        },
        {
          label: 'Memoization',
          tier: 'learning',
          mastery: 0.58,
          blurb: 'Cache subproblem answers so the same work never repeats.',
        },
        {
          label: 'Tail calls',
          tier: 'unexplored',
          mastery: 0.06,
          blurb: 'When the recursive call is last, the frame can be reused.',
        },
      ],
    },
    {
      label: 'Complexity',
      tier: 'learning',
      mastery: 0.66,
      at: [490, 160, -190],
      blurb: 'How cost grows, the vocabulary the rest of the course argues in.',
      subs: [
        {
          label: 'Big-O notation',
          tier: 'mastered',
          mastery: 0.9,
          blurb: 'Upper bound on growth, constants discarded.',
        },
        {
          label: 'Recurrences',
          tier: 'learning',
          mastery: 0.52,
          blurb: 'Cost expressed in terms of itself; solve to get a closed form.',
        },
        {
          label: 'Master theorem',
          tier: 'struggling',
          mastery: 0.29,
          blurb: 'A shortcut for divide-and-conquer recurrences in three cases.',
        },
        {
          label: 'Amortized analysis',
          tier: 'learning',
          mastery: 0.61,
          blurb: 'Average over a sequence, which is why a doubling array is still O(1).',
        },
        {
          label: 'Lower bounds',
          tier: 'unexplored',
          mastery: 0.08,
          blurb: 'Proving no algorithm can do better, not just that yours does not.',
        },
      ],
    },
    {
      label: 'Hashing',
      tier: 'learning',
      mastery: 0.59,
      at: [230, 250, 140],
      blurb: 'Constant-time lookup, paid for with a good hash and collision policy.',
      subs: [
        {
          label: 'Hash maps',
          tier: 'mastered',
          mastery: 0.87,
          blurb: 'Key to bucket in one step; the workhorse of the course.',
        },
        {
          label: 'Collision handling',
          tier: 'struggling',
          mastery: 0.26,
          blurb: 'Chaining versus open addressing: space traded for locality.',
        },
        {
          label: 'Load factor',
          tier: 'learning',
          mastery: 0.54,
          blurb: 'Occupancy ratio that triggers a resize before probes get long.',
        },
        {
          label: 'Bloom filters',
          tier: 'unexplored',
          mastery: 0.03,
          blurb: 'Probabilistic membership: false positives, never false negatives.',
        },
        {
          label: 'LRU cache',
          tier: 'learning',
          mastery: 0.47,
          blurb: 'Hash map plus a linked list, for eviction in O(1).',
        },
      ],
    },
    {
      label: 'Dynamic programming',
      tier: 'struggling',
      mastery: 0.36,
      at: [-300, 150, -260],
      blurb: 'Overlapping subproblems solved once. Most students fight the table, not the idea.',
      subs: [
        {
          label: 'Optimal substructure',
          tier: 'learning',
          mastery: 0.49,
          blurb: 'The property that makes DP legal in the first place.',
        },
        {
          label: 'Knapsack',
          tier: 'struggling',
          mastery: 0.28,
          blurb: 'Weight-capacity table; the canonical two-dimensional DP.',
        },
        {
          label: 'Edit distance',
          tier: 'struggling',
          mastery: 0.21,
          blurb: 'Insert, delete, substitute: string alignment as a grid.',
        },
        {
          label: 'Longest subsequence',
          tier: 'learning',
          mastery: 0.44,
          blurb: 'Order-preserving, not contiguous, and that is the distinction people miss.',
        },
        {
          label: 'Greedy vs DP',
          tier: 'unexplored',
          mastery: 0.05,
          blurb: 'When a local choice is provably safe, and when it is not.',
        },
      ],
    },
  ],
};

export interface NodeUse {
  tag: string;
  text: string;
}

/**
 * What the product actually does with a node — the three panels explore
 * mode shows when you select one. Copy is tier-dependent, so a mastered
 * node and an unexplored node say genuinely different things.
 *
 * @param degree Number of neighbours the node is linked to.
 */
export function nodeUses(node: GraphNode, degree: number): NodeUse[] {
  const t = node.tier;
  // A leaf node has degree 1, and the graph does contain them, so the fixed
  // plural read "its 1 neighbours" on screen.
  const neighbours = degree === 1 ? '1 neighbour' : degree + ' neighbours';
  return [
    {
      tag: 'TUTOR RETRIEVAL',
      text:
        'A /learn session on ' +
        node.label +
        ' pulls this node plus its ' +
        neighbours +
        ' into context, then retrieves the chunks of your ' +
        COURSE.code +
        ' uploads that mention them.',
    },
    {
      tag: 'QUIZ TARGETING',
      text:
        t === 'mastered'
          ? 'Adaptive quizzes spend few questions here. It is already above the 0.75 mastery cut-off, so the generator spends them on weaker nodes.'
          : 'POST /api/quiz/generate takes this node id. Every answer writes a mastery delta back onto it, which moves the ring you are looking at.',
    },
    {
      tag: t === 'unexplored' ? 'NOT SCHEDULED YET' : 'REVIEW SCHEDULING',
      text:
        t === 'unexplored'
          ? 'Nothing has touched this node yet. It appears the moment a note, upload, or quiz mentions the concept.'
          : 'Spaced repetition draws cards from the lowest-mastery linked concepts first, and at ' +
            Math.round(node.mastery * 100) +
            '% this sits ' +
            (node.mastery < 0.45 ? 'near the front' : 'mid-queue') +
            '.',
    },
  ];
}
