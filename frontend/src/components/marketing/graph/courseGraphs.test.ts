/**
 * Fixture integrity. These graphs are hand-authored, so the failure mode is a
 * typo'd id producing an edge to nowhere — which renders as a line into empty
 * space rather than an error. Pin the invariants instead.
 */
import { describe, it, expect } from 'vitest';

import { COURSE_GRAPHS, TIER_COLOR, type CourseGraph } from './courseGraphs';

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
        expect(TIER_COLOR[n.tier]).toMatch(/^#/);
      }
    },
  );
});
