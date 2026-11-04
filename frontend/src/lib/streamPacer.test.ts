import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { createStreamPacer } from './streamPacer';

// A 2,000-char reply delivered in one burst: Claude Sonnet 5.5's shape after
// a tool call (ADR 0030).
const BURST = 'word '.repeat(400);

describe('createStreamPacer', () => {
  // Fake timers move Date.now() in step with the timers they fire.
  const now = () => Date.now();
  const advance = (ms: number) => vi.advanceTimersByTime(ms);

  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => vi.useRealTimers());

  it('types a burst out over about a second and a half, not all at once', () => {
    const out: string[] = [];
    const pacer = createStreamPacer(t => out.push(t), now);
    pacer.push(BURST);

    advance(16);
    expect(out.join('').length).toBeGreaterThan(0);
    expect(out.join('').length).toBeLessThan(BURST.length / 10);

    advance(500);
    const half = out.join('').length;
    expect(half).toBeGreaterThan(BURST.length / 3);
    expect(half).toBeLessThan(BURST.length);

    advance(1500);
    expect(out.join('')).toBe(BURST);
  });

  it('passes a stream that already arrives at typing speed straight through', () => {
    const out: string[] = [];
    const pacer = createStreamPacer(t => out.push(t), now);
    for (let i = 0; i < 20; i++) {
      pacer.push('abcd ');
      advance(16);
      // Everything pushed so far is already out: no backlog builds up.
      expect(out.join('')).toBe('abcd '.repeat(i + 1));
    }
  });

  it('holds the same rate when ticks arrive late (a background tab)', () => {
    const out: string[] = [];
    const pacer = createStreamPacer(t => out.push(t), now);
    pacer.push(BURST);
    // Timers clamped to 1 s: the first tick fires a second late and must
    // release a second's worth.
    vi.setSystemTime(Date.now() + 1000);
    advance(16);
    expect(out.join('').length).toBeGreaterThan(BURST.length / 2);
  });

  it('drain() resolves only after the last character is out', async () => {
    const out: string[] = [];
    const pacer = createStreamPacer(t => out.push(t), now);
    pacer.push(BURST);
    let done = false;
    const drained = pacer.drain().then(() => { done = true; });
    advance(200);
    await Promise.resolve();
    expect(done).toBe(false);
    advance(3000);
    await drained;
    expect(out.join('')).toBe(BURST);
  });

  it('drain() resolves at once when nothing is queued', async () => {
    const pacer = createStreamPacer(() => {}, now);
    await expect(pacer.drain()).resolves.toBeUndefined();
  });

  it('flush() releases the whole backlog synchronously and settles drain()', async () => {
    const out: string[] = [];
    const pacer = createStreamPacer(t => out.push(t), now);
    pacer.push(BURST);
    const drained = pacer.drain();
    pacer.flush();
    expect(out.join('')).toBe(BURST);
    await drained;
  });

  it('never splits a surrogate pair across releases', () => {
    const out: string[] = [];
    const pacer = createStreamPacer(t => out.push(t), now);
    pacer.push('🌱'.repeat(800));
    advance(16);
    advance(16);
    for (const chunk of out) {
      expect(chunk.length % 2).toBe(0);
    }
  });
});
