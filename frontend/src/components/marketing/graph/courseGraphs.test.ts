/**
 * Fixture integrity. These graphs are hand-authored, so the failure mode is a
 * typo'd id producing an edge to nowhere — which renders as a line into empty
 * space rather than an error. Pin the invariants instead.
 */
import { describe, it, expect } from 'vitest';

import {
  COURSE_GRAPHS,
  TIER_COLOR,
  TIER_LABEL,
  TIER_ORDER,
  conceptNodes,
  neighbours,
  tierCounts,
  tierForMastery,
  type CourseGraph,
} from './courseGraphs';

const ids = (g: CourseGraph) => new Set(g.nodes.map((n) => n.id));

describe('COURSE_GRAPHS', () => {
  it('ships exactly three courses with distinct ids and codes', () => {
    expect(COURSE_GRAPHS).toHaveLength(3);
    expect(new Set(COURSE_GRAPHS.map((g) => g.id)).size).toBe(3);
    expect(new Set(COURSE_GRAPHS.map((g) => g.code)).size).toBe(3);
  });

  it.each(COURSE_GRAPHS.map((g) => [g.code, g] as const))(
    '%s has unique node ids',
    (_code, g) => {
      expect(ids(g).size).toBe(g.nodes.length);
    },
  );

  it.each(COURSE_GRAPHS.map((g) => [g.code, g] as const))(
    '%s has a root that exists',
    (_code, g) => {
      expect(ids(g).has(g.rootId)).toBe(true);
    },
  );

  it.each(COURSE_GRAPHS.map((g) => [g.code, g] as const))(
    '%s edges reference real nodes',
    (_code, g) => {
      const known = ids(g);
      for (const e of g.edges) {
        expect(known.has(e.source)).toBe(true);
        expect(known.has(e.target)).toBe(true);
      }
    },
  );

  it.each(COURSE_GRAPHS.map((g) => [g.code, g] as const))(
    '%s children reference real nodes',
    (_code, g) => {
      const known = ids(g);
      for (const n of g.nodes) {
        for (const c of n.children) expect(known.has(c)).toBe(true);
      }
    },
  );

  it.each(COURSE_GRAPHS.map((g) => [g.code, g] as const))(
    '%s reaches every node from the root',
    (_code, g) => {
      const adj = new Map<string, string[]>();
      for (const e of g.edges) {
        adj.set(e.source, [...(adj.get(e.source) ?? []), e.target]);
        adj.set(e.target, [...(adj.get(e.target) ?? []), e.source]);
      }
      const seen = new Set([g.rootId]);
      const queue = [g.rootId];
      while (queue.length) {
        for (const nxt of adj.get(queue.shift()!) ?? []) {
          if (!seen.has(nxt)) {
            seen.add(nxt);
            queue.push(nxt);
          }
        }
      }
      expect(seen.size).toBe(g.nodes.length);
    },
  );

  it.each(COURSE_GRAPHS.map((g) => [g.code, g] as const))(
    '%s gives every node a blurb and a known tier',
    (_code, g) => {
      for (const n of g.nodes) {
        expect(n.blurb.length).toBeGreaterThan(0);
        expect(TIER_COLOR[n.tier]).toBeDefined();
      }
    },
  );
});

/**
 * The nodes now carry a numeric `mastery` as well as a `tier`, because the
 * demo draws an arc for it. Two fields that can disagree need one authority:
 * `tierForMastery`, ported from `backend/config.py::get_mastery_tier`. Without
 * this suite a hand-authored node can paint a 90% ring in the struggling red.
 */
describe('COURSE_GRAPHS — mastery scores (#344 step 3)', () => {
  it.each(COURSE_GRAPHS.map((g) => [g.code, g] as const))(
    '%s scores every node in 0–1, agreeing with its tier',
    (_code, g) => {
      for (const n of g.nodes) {
        expect(n.mastery, n.id).toBeGreaterThanOrEqual(0);
        expect(n.mastery, n.id).toBeLessThanOrEqual(1);
        expect(tierForMastery(n.mastery), n.id).toBe(n.tier);
      }
    },
  );

  /**
   * The root's ring and the surface's chrome bar both print the COURSE
   * number, so the root's score has to be the concepts' mean rather than an
   * independently invented figure — otherwise the header contradicts the
   * picture directly under it.
   */
  it.each(COURSE_GRAPHS.map((g) => [g.code, g] as const))(
    '%s roots at the mean of its concepts',
    (_code, g) => {
      const concepts = conceptNodes(g);
      expect(concepts).toHaveLength(g.nodes.length - 1);
      const mean = concepts.reduce((sum, n) => sum + n.mastery, 0) / concepts.length;
      const root = g.nodes.find((n) => n.id === g.rootId)!;
      expect(root.mastery).toBeCloseTo(mean, 6);
    },
  );

  it.each(COURSE_GRAPHS.map((g) => [g.code, g] as const))(
    '%s draws a legible slice of a bigger course',
    (_code, g) => {
      expect(g.conceptCount).toBeGreaterThan(conceptNodes(g).length);
      // The root blurb states the same number in prose ("… — 19 concepts
      // mapped from your syllabus"); a mismatch is the surface arguing with
      // its own detail panel.
      expect(g.nodes.find((n) => n.id === g.rootId)!.blurb).toContain(String(g.conceptCount));
    },
  );

  it.each(COURSE_GRAPHS.map((g) => [g.code, g] as const))(
    '%s shows every tier at least once, so the legend is never a dead row',
    (_code, g) => {
      const counts = tierCounts(g);
      for (const t of TIER_ORDER) expect(counts[t], `${g.id} ${t}`).toBeGreaterThan(0);
      const total = TIER_ORDER.reduce((sum, t) => sum + counts[t], 0);
      expect(total).toBe(conceptNodes(g).length);
    },
  );

  /**
   * The detail panel prints "N connections" and lists them. That count is the
   * number of LINES a visitor can see leaving the node, so it reads `edges`,
   * not the dead `children` field.
   */
  it.each(COURSE_GRAPHS.map((g) => [g.code, g] as const))(
    '%s connects every node to at least one other, counted off the drawn edges',
    (_code, g) => {
      for (const n of g.nodes) {
        const links = neighbours(g, n.id);
        expect(links.length, n.id).toBeGreaterThan(0);
        expect(new Set(links.map((l) => l.id)).size, `${n.id} duplicates`).toBe(links.length);
        expect(links.some((l) => l.id === n.id), `${n.id} self-link`).toBe(false);
      }
    },
  );
});

describe('tierForMastery', () => {
  // The backend's cutoffs, restated as data so a drift in either direction is
  // a failing test rather than a landing page that grades differently from
  // the product.
  it.each([
    [1, 'mastered'],
    [0.75, 'mastered'],
    [0.7499, 'learning'],
    [0.45, 'learning'],
    [0.4499, 'struggling'],
    [0.1, 'struggling'],
    [0.0999, 'unexplored'],
    [0, 'unexplored'],
  ] as const)('scores %s as %s', (score, tier) => {
    expect(tierForMastery(score)).toBe(tier);
  });
});

describe('TIER_LABEL / TIER_ORDER', () => {
  it('names every tier in the product’s own words', () => {
    expect(TIER_LABEL).toEqual({
      mastered: 'Mastered',
      learning: 'Learning',
      struggling: 'Struggling',
      unexplored: 'Unexplored',
    });
  });

  it('orders the legend strongest-first, covering every tier exactly once', () => {
    expect([...TIER_ORDER]).toEqual(['mastered', 'learning', 'struggling', 'unexplored']);
    expect(new Set(TIER_ORDER).size).toBe(Object.keys(TIER_COLOR).length);
  });
});

/**
 * #344 visual 1 — this file shipped a FOURTH inlined copy of the mastery
 * palette (`#1B6C42` / `#D97706` / `#EF4444` / `#9CA3AF`), so the landing page
 * advertised different mastery colours than the product it advertises.
 * globals.css:80-89 declares the canonical set and calls itself the "Single
 * source for the 3 previously-inlined copies in Dashboard / Tree / notetaker".
 *
 * The old assertion here was `toMatch(/^#/)` — which is what let four wrong
 * literals through in the first place. Any hex now fails outright.
 */
describe('TIER_COLOR', () => {
  it('consumes the canonical --state-* tokens, never a literal', () => {
    expect(TIER_COLOR).toEqual({
      mastered: 'var(--state-mastery)',
      learning: 'var(--state-progress)',
      struggling: 'var(--state-struggle)',
      unexplored: 'var(--state-neutral)',
    });
  });

  it.each(Object.entries(TIER_COLOR))('%s is a token reference', (_tier, value) => {
    expect(value).toMatch(/^var\(--state-[a-z]+\)$/);
    expect(value).not.toMatch(/#/);
  });
});
