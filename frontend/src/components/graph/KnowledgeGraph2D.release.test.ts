import { describe, expect, it } from 'vitest';
import { followersOf, releaseVelocity } from './KnowledgeGraph2D';

const TICK = 1000 / 60;

describe('releaseVelocity (dragged node momentum)', () => {
  it('carries the pointer speed on, converted to per-tick units', () => {
    const [vx, vy] = releaseVelocity({ t: 1000, vx: 0.3, vy: -0.15 }, 1020, false);
    expect(vx).toBeCloseTo(0.3 * TICK);
    expect(vy).toBeCloseTo(-0.15 * TICK);
  });

  it('is zero when the pointer had stopped before letting go', () => {
    expect(releaseVelocity({ t: 1000, vx: 1, vy: 1 }, 1200, false)).toEqual([0, 0]);
  });

  it('is zero under prefers-reduced-motion', () => {
    expect(releaseVelocity({ t: 1000, vx: 1, vy: 1 }, 1010, true)).toEqual([0, 0]);
  });

  it('is zero with no drag samples', () => {
    expect(releaseVelocity(null, 1000, false)).toEqual([0, 0]);
  });

  it('clamps a wild throw but keeps its direction', () => {
    const [vx, vy] = releaseVelocity({ t: 1000, vx: 30, vy: 40 }, 1010, false);
    expect(Math.hypot(vx, vy)).toBeCloseTo(28);
    expect(vy / vx).toBeCloseTo(40 / 30);
  });
});

describe('followersOf (what a dragged concept pulls along)', () => {
  const links = [
    { source: 'root', target: 'a', anchor: true },
    { source: 'leaf', target: 'a' },
    { source: 'a', target: 'b' },
    { source: 'b', target: 'c' },
  ];

  it('frees the dragged node and concepts up to two links away, each led by the node it was reached through', () => {
    expect(followersOf('leaf', links)).toEqual(
      new Map([
        ['leaf', null],
        ['a', 'leaf'],
        ['b', 'a'],
      ]),
    );
  });

  it('never frees a course root through its spoke', () => {
    expect(followersOf('a', links).has('root')).toBe(false);
  });

  it('accepts links whose ends d3 has already resolved to nodes', () => {
    const resolved = [{ source: { id: 'x' }, target: { id: 'y' } }];
    expect(followersOf('x', resolved)).toEqual(new Map([['x', null], ['y', 'x']]));
  });
});
