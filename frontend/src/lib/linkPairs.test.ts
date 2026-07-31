/**
 * #111 — the binned link pass must be a drop-in for the all-pairs one.
 *
 * The perf PR claims "no visual change". For this optimisation that claim is
 * checkable rather than aspirational: the fast version has to emit the same
 * pairs, in the same order, with the same distances. Order is part of it —
 * the caller strokes translucent overlapping lines, so a different sequence
 * composites to a different image.
 */
import { describe, it, expect } from 'vitest';

import { linkPairs, linkPairsNaive, type ProjectedPoint } from './linkPairs';

const REACH = 70;

/** Deterministic PRNG, so a failure is reproducible. */
function makeRng(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 0x100000000;
  };
}

/** A cloud shaped like the real one: 226 nodes, scales spanning the projection. */
function cloud(seed: number, count: number, spread: number): ProjectedPoint[] {
  const rnd = makeRng(seed);
  return Array.from({ length: count }, () => ({
    x: (rnd() - 0.5) * spread,
    y: (rnd() - 0.5) * spread,
    sc: 0.7 + rnd() * 1.0,
  }));
}

describe('linkPairs', () => {
  it('matches the all-pairs reference exactly, across many random clouds', () => {
    for (let seed = 1; seed <= 40; seed++) {
      const points = cloud(seed, 226, 1600);
      expect(linkPairs(points, REACH), `seed ${seed}`).toEqual(linkPairsNaive(points, REACH));
    }
  });

  it('matches at densities that stress the binning', () => {
    // Tight cloud: nearly everything is within reach, so buckets are huge.
    const dense = cloud(7, 200, 120);
    expect(linkPairs(dense, REACH)).toEqual(linkPairsNaive(dense, REACH));
    // Sparse cloud: almost nothing links, so most buckets are empty.
    const sparse = cloud(8, 200, 20000);
    expect(linkPairs(sparse, REACH)).toEqual(linkPairsNaive(sparse, REACH));
  });

  it('handles negative coordinates, which the parallax offset produces', () => {
    const shifted = cloud(11, 150, 1200).map((p) => ({ ...p, x: p.x - 3000, y: p.y - 2000 }));
    expect(linkPairs(shifted, REACH)).toEqual(linkPairsNaive(shifted, REACH));
  });

  it('is asymmetric in the same way the original was', () => {
    // The threshold comes from the FIRST point, so a small-scale point can
    // fail to reach a partner that would have reached it. Order must not be
    // silently normalised away.
    const points: ProjectedPoint[] = [
      { x: 0, y: 0, sc: 0.1 }, // reach 7
      { x: 50, y: 0, sc: 2.0 }, // reach 140
    ];
    expect(linkPairs(points, REACH)).toEqual([]);
    expect(linkPairs([points[1], points[0]], REACH)).toEqual([{ i: 0, j: 1, d: 50 }]);
  });

  it('does not duplicate pairs when the grid spans a wide coordinate range', () => {
    // Regression: the grid used to pack (gx, gy) into one integer assuming
    // both stayed inside a bound. A small `reach` makes cells small, so the
    // grid coordinates blow past it, two different cells collide, the same
    // bucket gets visited twice in one 3x3 scan — and the pair is emitted
    // TWICE. Found in review; this is the exact repro.
    const points: ProjectedPoint[] = [
      { x: 0, y: 0, sc: 1 },
      { x: 0, y: 5000, sc: 1 },
      { x: 0.5, y: 5000.4, sc: 1 },
    ];
    expect(linkPairs(points, 1)).toEqual(linkPairsNaive(points, 1));
    expect(linkPairs(points, 1)).toHaveLength(1);

    // And at a range no packed key could have survived at all.
    const far = cloud(31, 120, 4_000_000).map((p) => ({ ...p, sc: 0.02 }));
    expect(linkPairs(far, REACH)).toEqual(linkPairsNaive(far, REACH));
  });

  it('degenerates safely', () => {
    expect(linkPairs([], REACH)).toEqual([]);
    expect(linkPairs([{ x: 0, y: 0, sc: 1 }], REACH)).toEqual([]);
    // A zero reach links nothing and must not divide by a zero cell size.
    expect(linkPairs(cloud(3, 20, 500), 0)).toEqual([]);
    // Coincident points are at distance 0, which is inside any positive reach.
    const stacked = Array.from({ length: 4 }, () => ({ x: 5, y: 5, sc: 1 }));
    expect(linkPairs(stacked, REACH)).toEqual(linkPairsNaive(stacked, REACH));
  });

  it('actually avoids the all-pairs work', () => {
    // Guard against a future "simplification" that quietly restores the
    // double loop: on a sparse cloud the binned version must measure far
    // fewer distances than the naive one would.
    const points = cloud(21, 400, 9000);
    let measured = 0;
    const counting = points.map((p) => ({
      get x() { measured++; return p.x; },
      get y() { return p.y; },
      get sc() { return p.sc; },
    })) as unknown as ProjectedPoint[];
    linkPairs(counting, REACH);
    const allPairs = (points.length * (points.length - 1)) / 2;
    expect(measured).toBeLessThan(allPairs / 4);
  });
});
