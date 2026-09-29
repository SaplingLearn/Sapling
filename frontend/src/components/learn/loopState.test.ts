import { describe, expect, it } from 'vitest';

import { initialLoopState, reduceLoopEvent } from './loopState';

const item = { question_hash: 'qh1', format: 'free' as const, difficulty: 1 as const, prompt: 'p' };

describe('reduceLoopEvent', () => {
  it('starts in probe with no item', () => {
    expect(initialLoopState()).toMatchObject({
      phase: 'probe', item: null, hintOffer: null, leakRedacted: false, budgetPause: null, focusNodeId: null,
    });
  });

  it('phase events move the phase and nothing else', () => {
    const s = reduceLoopEvent({ ...initialLoopState(), item }, { type: 'phase', phase: 'teach' });
    expect(s.phase).toBe('teach');
    expect(s.item).toEqual(item);
  });

  it("a turn's 'hint' phase is the check phase to the UI (the item stays current)", () => {
    const s = reduceLoopEvent({ ...initialLoopState(), phase: 'check', item }, { type: 'phase', phase: 'hint' });
    expect(s.phase).toBe('check');
  });

  it('an unknown phase string changes nothing', () => {
    const start = { ...initialLoopState(), phase: 'teach' as const };
    expect(reduceLoopEvent(start, { type: 'phase', phase: 'bogus' })).toBe(start);
  });

  it('check sets the current item and clears a stale hint offer', () => {
    const s = reduceLoopEvent({ ...initialLoopState(), hintOffer: 1 }, { type: 'check', item });
    expect(s.item).toEqual({ ...item, options: null });
    expect(s.hintOffer).toBeNull();
  });

  it('a partial check event (hash only) keeps the pose it already has for that hash', () => {
    const s0 = reduceLoopEvent(initialLoopState(), { type: 'check', item: { ...item, options: null } });
    const s1 = reduceLoopEvent(s0, { type: 'check', item: { question_hash: 'qh1', format: 'free', difficulty: 1 } });
    expect(s1.item?.prompt).toBe('p');
  });

  it('check null clears the item (graded)', () => {
    expect(reduceLoopEvent({ ...initialLoopState(), item }, { type: 'check', item: null }).item).toBeNull();
  });

  it('hint_offer records the rung; hint_taken clears it', () => {
    const offered = reduceLoopEvent(initialLoopState(), { type: 'hint_offer', rung: 1 });
    expect(offered.hintOffer).toBe(1);
    expect(reduceLoopEvent(offered, { type: 'hint_taken' }).hintOffer).toBeNull();
  });

  it('learner_state is keyed by node_id, overwrites, and focuses the node', () => {
    let s = reduceLoopEvent(initialLoopState(), { type: 'learner_state', state: { node_id: 'n1', p_known: 0.4, band: 'develop' } });
    s = reduceLoopEvent(s, { type: 'learner_state', state: { node_id: 'n1', p_known: 0.6, band: 'develop' } });
    expect(s.learnerState.n1.p_known).toBe(0.6);
    expect(s.focusNodeId).toBe('n1');
  });

  it('done with leak_redacted flips the flag; without it clears', () => {
    const on = reduceLoopEvent(initialLoopState(), { type: 'done', leakRedacted: true });
    expect(on.leakRedacted).toBe(true);
    expect(reduceLoopEvent(on, { type: 'done', leakRedacted: false }).leakRedacted).toBe(false);
  });

  it('a hard budget event pauses; a soft one changes nothing (spec §3.5)', () => {
    const hard = reduceLoopEvent(initialLoopState(), { type: 'budget', level: 'hard', resetAt: '2026-09-27T00:00:00Z' });
    expect(hard.budgetPause).toEqual({ resetAt: '2026-09-27T00:00:00Z', sessionCapped: false });
    expect(reduceLoopEvent(initialLoopState(), { type: 'budget', level: 'soft', resetAt: null }).budgetPause).toBeNull();
    expect(hard.phase).toBe('probe');
  });

  it('A39: session_capped rides the pause', () => {
    const s = reduceLoopEvent(initialLoopState(), { type: 'budget', level: 'hard', resetAt: null, sessionCapped: true });
    expect(s.budgetPause).toEqual({ resetAt: null, sessionCapped: true });
  });

  it('budget_clear lifts the pause (the next successful tutor turn)', () => {
    const hard = reduceLoopEvent(initialLoopState(), { type: 'budget', level: 'hard', resetAt: null });
    expect(reduceLoopEvent(hard, { type: 'budget_clear' }).budgetPause).toBeNull();
  });

  it('reset returns to the initial state but keeps a pause (it is per student, not per session)', () => {
    const s = reduceLoopEvent(
      { ...initialLoopState(), phase: 'teach', item, budgetPause: { resetAt: null, sessionCapped: false } },
      { type: 'reset' },
    );
    expect(s.phase).toBe('probe');
    expect(s.item).toBeNull();
    expect(s.budgetPause).toEqual({ resetAt: null, sessionCapped: false });
  });

  it('reset drops a session-capped pause (a new session starts fresh, A39)', () => {
    const s = reduceLoopEvent(
      { ...initialLoopState(), budgetPause: { resetAt: null, sessionCapped: true } },
      { type: 'reset' },
    );
    expect(s.budgetPause).toBeNull();
  });

  it('never advances the phase on its own', () => {
    const s = reduceLoopEvent(initialLoopState(), { type: 'done', leakRedacted: false });
    expect(s.phase).toBe('probe');
  });
});
