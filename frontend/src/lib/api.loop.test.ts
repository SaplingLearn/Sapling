import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  ApiError,
  approveLoopPlan,
  answerLoopProbe,
  budgetPauseOf,
  closeLoopSession,
  getLoopPlan,
  getLoopStatus,
  listLoopSessions,
  nextLoopCheck,
  nextLoopProbe,
  postLoopAttempt,
  requestLoopHint,
  requestLoopHintTurn,
  startLoopSession,
  streamLoopChat,
  streamLoopCheckAnswer,
} from './api';

function sseBody(blocks: string[]): ReadableStream {
  const enc = new TextEncoder();
  return new ReadableStream({
    start(c) {
      for (const b of blocks) c.enqueue(enc.encode(b));
      c.close();
    },
  });
}
const ev = (name: string, data: unknown) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`;
const done = ev('done', { type: 'done', step: 'reply', message: '', data: { reply: 'ok', graph_update: {}, mastery_changes: [] } });
const fetchMock = () => globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
const urlOf = (i = 0) => String(fetchMock().mock.calls[i][0]);
const initOf = (i = 0) => fetchMock().mock.calls[i][1] as RequestInit;
const bodyOf = (i = 0) => JSON.parse(String(initOf(i).body));
const json = (v: unknown, status = 200) => new Response(JSON.stringify(v), { status });

afterEach(() => vi.restoreAllMocks());

describe('getLoopStatus', () => {
  it('404 (flag off) resolves inactive instead of throwing', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json({ detail: 'learning loop not enabled' }, 404));
    await expect(getLoopStatus('u')).resolves.toEqual({ active: false });
  });
  it('active passes through', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json({ active: true }));
    await expect(getLoopStatus('u')).resolves.toEqual({ active: true });
  });
  it("a 5xx still throws (fail closed is the caller's job)", async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('boom', { status: 503 }));
    await expect(getLoopStatus('u')).rejects.toBeTruthy();
  });
});

describe('loop JSON clients (routes/learn_loop.py shapes; no model_pref, spec §13 A15/A26)', () => {
  it('listLoopSessions reads GET /sessions and unwraps the list', async () => {
    const sessions = [{ session_id: 's1', topic: 't', started_at: '2026-09-20T10:00:00Z', phase: 'teach' }];
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json({ sessions }));
    await expect(listLoopSessions('u 1', 'c1')).resolves.toEqual(sessions);
    expect(urlOf()).toContain('/api/learn/loop/sessions?user_id=u+1&course_id=c1');
  });

  it('startLoopSession posts user_id, topic and course_id only', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json({ session_id: 's9', initial_message: 'hi', graph_state: {} }));
    const r = await startLoopSession('u', 'c1', 'Intro CS');
    expect(r.session_id).toBe('s9');
    expect(urlOf()).toContain('/api/learn/loop/start-session');
    expect(bodyOf()).toEqual({ user_id: 'u', topic: 'Intro CS', course_id: 'c1' });
  });

  it('nextLoopProbe posts the session and user (the course is the session\'s, HANDOFF-08)', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json({ done: true, phase: 'plan' }));
    await nextLoopProbe('s', 'u');
    expect(urlOf()).toContain('/api/learn/loop/probe/next');
    expect(bodyOf()).toEqual({ session_id: 's', user_id: 'u' });
  });

  it('answerLoopProbe sends LoopCheckAnswerBody field names (option, not selected_option)', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json({ graded: true, correct: true }));
    await answerLoopProbe('s', 'u', 'qh', { option: 'B', reason: 'because', idk: false });
    expect(urlOf()).toContain('/api/learn/loop/probe/answer');
    expect(bodyOf()).toEqual({ session_id: 's', user_id: 'u', question_hash: 'qh', option: 'B', reason: 'because', idk: false });
  });

  it('answerLoopProbe idk sends no answer text', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json({ graded: true, correct: false }));
    await answerLoopProbe('s', 'u', 'qh', { idk: true });
    expect(bodyOf()).toEqual({ session_id: 's', user_id: 'u', question_hash: 'qh', idk: true });
  });

  it('getLoopPlan reads GET /plan by session and user', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json({ concepts: [], order: [] }));
    await getLoopPlan('s', 'u');
    expect(urlOf()).toContain('/api/learn/loop/plan?session_id=s&user_id=u');
  });

  it('approveLoopPlan posts the ids in order', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json({ phase: 'teach', concept_ids: ['b', 'a'] }));
    await approveLoopPlan('s', 'u', ['b', 'a']);
    expect(urlOf()).toContain('/api/learn/loop/plan/approve');
    expect(bodyOf()).toEqual({ session_id: 's', user_id: 'u', concept_ids: ['b', 'a'] });
  });

  it('postLoopAttempt sends attempt_text (LoopAttemptBody)', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json({ genuine: true, counted: true, attempts: 1, independent_s: 50 }));
    await postLoopAttempt('s', 'u', 'qh', 'my work');
    expect(urlOf()).toContain('/api/learn/loop/step/attempt');
    expect(bodyOf()).toEqual({ session_id: 's', user_id: 'u', question_hash: 'qh', attempt_text: 'my work' });
  });

  it('nextLoopCheck posts "Check me" (A27)', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json({ phase: 'teach', check: null, plan_done: true }));
    await expect(nextLoopCheck('s', 'u')).resolves.toEqual({ phase: 'teach', check: null, plan_done: true });
    expect(urlOf()).toContain('/api/learn/loop/check/next');
    expect(bodyOf()).toEqual({ session_id: 's', user_id: 'u' });
  });

  it('requestLoopHint moves the rung (no text)', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json({ denied: 'dwell' }));
    await expect(requestLoopHint('s', 'u', 'qh')).resolves.toEqual({ denied: 'dwell' });
    expect(urlOf()).toContain('/api/learn/loop/hint');
    expect(bodyOf()).toEqual({ session_id: 's', user_id: 'u', question_hash: 'qh' });
  });

  it('requestLoopHintTurn runs the [ACTION: hint] turn over /action', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json({ reply: 'a nudge', phase: 'hint' }));
    await expect(requestLoopHintTurn('s', 'u')).resolves.toMatchObject({ reply: 'a nudge' });
    expect(urlOf()).toContain('/api/learn/loop/action');
    expect(bodyOf()).toEqual({ session_id: 's', user_id: 'u', action_type: 'hint' });
  });

  it('closeLoopSession posts the session and returns the A60 shape', async () => {
    const close = { summary: 'S', self_eval: 'Q?', if_then: 'If a, then b.', concepts: [], misconceptions: [], model_written: false };
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json({ close, model_written: false, close_phase: 'teach' }));
    await expect(closeLoopSession('s', 'u')).resolves.toEqual({ close, model_written: false, close_phase: 'teach' });
    expect(urlOf()).toContain('/api/learn/loop/close');
    expect(bodyOf()).toEqual({ session_id: 's', user_id: 'u' });
  });

  it('no loop client ever sends model_pref', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async () => json({ sessions: [], session_id: 's' }));
    await startLoopSession('u', 'c', 't');
    await nextLoopProbe('s', 'u');
    await approveLoopPlan('s', 'u', ['a']);
    await requestLoopHintTurn('s', 'u');
    for (let i = 0; i < fetchMock().mock.calls.length; i++) {
      expect(String(initOf(i).body ?? '')).not.toContain('model_pref');
    }
  });
});

describe('streamLoopChat', () => {
  it('dispatches phase/check/hint_offer/learner_state/budget and returns leak_redacted', async () => {
    const check = { question_hash: 'qh', format: 'free', difficulty: 2 };
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(sseBody([
      ev('phase', { type: 'phase', step: 'loop', message: '', data: { phase: 'check' } }),
      ev('token', { type: 'token', step: 'reply', message: '', data: { delta: 'Hi' } }),
      ev('check', { type: 'check', step: 'loop', message: '', data: check }),
      ev('hint_offer', { type: 'hint_offer', step: 'loop', message: '', data: { rung: 1 } }),
      ev('learner_state', { type: 'learner_state', step: 'loop', message: '', data: { node_id: 'n', p_known: 0.5, band: 'develop' } }),
      ev('budget', { type: 'budget', step: 'loop', message: '', data: { level: 'hard', reset_at: '2026-09-27T00:00:00Z', scope: 'daily_usd', session_capped: false } }),
      ev('done', { type: 'done', step: 'reply', message: '', data: { reply: 'Hi [redacted]', graph_update: {}, mastery_changes: [], leak_redacted: true } }),
    ])));
    const seen: string[] = [];
    const res = await streamLoopChat('s', 'u', 'm', {
      onToken: (d) => seen.push(`token:${d}`),
      onPhase: (p) => seen.push(`phase:${p}`),
      onCheck: (i) => seen.push(`check:${i.question_hash}`),
      onHintOffer: (r) => seen.push(`offer:${r}`),
      onLearnerState: (s) => seen.push(`state:${s.node_id}:${s.p_known}`),
      onBudget: (b) => seen.push(`budget:${b.level}:${b.reset_at}:${b.session_capped}`),
    });
    expect(seen).toEqual(['phase:check', 'token:Hi', 'check:qh', 'offer:1', 'state:n:0.5', 'budget:hard:2026-09-27T00:00:00Z:false']);
    expect(res.reply).toBe('Hi [redacted]');
    expect(res.leak_redacted).toBe(true);
    expect(urlOf()).toContain('/api/learn/loop/chat/stream');
    expect(bodyOf()).toEqual({ session_id: 's', user_id: 'u', message: 'm' }); // no model_pref (A15/A26)
  });

  it.each(['retry', 'transform'])('A46: retract {reason: %s} reaches onRetract between tokens', async (reason) => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(sseBody([
      ev('token', { type: 'token', step: 'reply', message: '', data: { delta: 'The answer is 4' } }),
      ev('retract', { type: 'retract', step: 'reply', message: '', data: { reason } }),
      ev('token', { type: 'token', step: 'reply', message: '', data: { delta: 'Think about it.' } }),
      done,
    ])));
    const seen: string[] = [];
    await streamLoopChat('s', 'u', 'm', {
      onToken: (d) => seen.push(`token:${d}`),
      onRetract: (r) => seen.push(`retract:${r}`),
    });
    expect(seen).toEqual(['token:The answer is 4', `retract:${reason}`, 'token:Think about it.']);
  });

  it('a budget event without session_capped reads as false (A39)', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(sseBody([
      ev('budget', { type: 'budget', step: 'loop', message: '', data: { level: 'soft', reset_at: null } }),
      done,
    ])));
    const seen: unknown[] = [];
    await streamLoopChat('s', 'u', 'm', { onBudget: (b) => seen.push(b) });
    expect(seen).toEqual([{ level: 'soft', reset_at: null, scope: null, session_capped: false }]);
  });
});

describe('streamLoopCheckAnswer (spec §13 A16: explicit submissions only)', () => {
  it('free text posts the answer to /check/answer/stream, never /chat/stream', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(sseBody([done])));
    await streamLoopCheckAnswer('s', 'u', 'qh', { answer: 'my answer', idk: false });
    expect(urlOf()).toContain('/api/learn/loop/check/answer/stream');
    expect(bodyOf()).toEqual({ session_id: 's', user_id: 'u', question_hash: 'qh', answer: 'my answer', idk: false });
  });
  it('mc_reason posts the option and the reason', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(sseBody([done])));
    await streamLoopCheckAnswer('s', 'u', 'qh', { option: 'B', reason: 'slope is constant', idk: false });
    expect(bodyOf()).toEqual({ session_id: 's', user_id: 'u', question_hash: 'qh', option: 'B', reason: 'slope is constant', idk: false });
  });
  it('idk posts idk: true and no answer text', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(sseBody([done])));
    await streamLoopCheckAnswer('s', 'u', 'qh', { idk: true });
    expect(bodyOf()).toEqual({ session_id: 's', user_id: 'u', question_hash: 'qh', idk: true });
  });
});

describe('budgetPauseOf (spec §3.5 / A20 429 body, A39 session_capped)', () => {
  const body = { detail: 'ai budget reached', reset_at: '2026-09-27T00:00:00Z' };
  it("reads a JSON route's ApiError", () => {
    expect(budgetPauseOf(new ApiError('ai budget reached', 429, { body }))).toEqual({ resetAt: body.reset_at, sessionCapped: false });
  });
  it("reads a stream route's Error (sse.ts: message = raw body, .status set)", () => {
    expect(budgetPauseOf(Object.assign(new Error(JSON.stringify(body)), { status: 429 }))).toEqual({ resetAt: body.reset_at, sessionCapped: false });
  });
  it('carries session_capped when the body says so', () => {
    const capped = { ...body, scope: 'session_requests', session_capped: true };
    expect(budgetPauseOf(new ApiError('x', 429, { body: capped }))).toEqual({ resetAt: body.reset_at, sessionCapped: true });
  });
  it('ignores other statuses and other 429s', () => {
    expect(budgetPauseOf(new ApiError('boom', 503, { body }))).toBeNull();
    expect(budgetPauseOf(new ApiError('slow down', 429, { body: { detail: 'too many requests' } }))).toBeNull();
    expect(budgetPauseOf(Object.assign(new Error('not json'), { status: 429 }))).toBeNull();
    expect(budgetPauseOf(new Error('network'))).toBeNull();
    expect(budgetPauseOf(null)).toBeNull();
  });
});
