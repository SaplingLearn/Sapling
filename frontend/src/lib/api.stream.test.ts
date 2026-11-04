import { describe, it, expect, vi, afterEach } from 'vitest';

function sseBody(blocks: string[]): ReadableStream {
  const enc = new TextEncoder();
  return new ReadableStream({
    start(c) {
      for (const b of blocks) c.enqueue(enc.encode(b));
      c.close();
    },
  });
}

const ev = (name: string, data: unknown) =>
  `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`;

afterEach(() => vi.restoreAllMocks());

describe('streamChat', () => {
  it('accumulates tokens, surfaces graph deltas, resolves on done', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        sseBody([
          ev('status', { type: 'status', step: 'start', message: '' }),
          ev('token', { type: 'token', step: 'reply', message: '', data: { delta: 'Hel' } }),
          ev('token', { type: 'token', step: 'reply', message: '', data: { delta: 'lo' } }),
          ev('graph_update', {
            type: 'graph_update', step: 'graph', message: '',
            data: { nodes: { new_nodes: [{ name: 'Eigen' }] }, mastery_changes: [] },
          }),
          ev('done', {
            type: 'done', step: 'reply', message: '',
            data: { reply: 'Hello', graph_update: {}, mastery_changes: [] },
          }),
        ]),
        { status: 200 },
      ) as never,
    );

    const { streamChat } = await import('./api');
    const tokens: string[] = [];
    const deltas: unknown[] = [];
    const result = await streamChat('s1', 'u1', 'hi', 'socratic', true, undefined, {
      onToken: (t) => tokens.push(t),
      onGraphUpdate: (d) => deltas.push(d),
    });

    // The pacer may coalesce deltas; the text is what matters.
    expect(tokens.join('')).toBe('Hello');
    expect(deltas).toHaveLength(1);
    expect(result.reply).toBe('Hello');
  });

  it('rejects on a mid-stream error event', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        sseBody([
          ev('token', { type: 'token', step: 'reply', message: '', data: { delta: 'Half' } }),
          ev('error', { type: 'error', step: 'reply', message: 'Interrupted.', data: { request_id: 'r1' } }),
        ]),
        { status: 200 },
      ) as never,
    );
    const { streamChat } = await import('./api');
    await expect(
      streamChat('s1', 'u1', 'hi', 'socratic', true, undefined, { onToken: () => {} }),
    ).rejects.toThrow(/interrupted/i);
  });

  it('preserves request_id from a mid-stream error event on the thrown Error', async () => {
    // ADR 0009: the backend deliberately includes request_id on error events
    // for Logfire correlation. Losing it on the frontend throw makes a
    // user-reported error untraceable — assert it survives as a property
    // AND stays visible in the (still-readable) message.
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        sseBody([
          ev('token', { type: 'token', step: 'reply', message: '', data: { delta: 'Half' } }),
          ev('error', { type: 'error', step: 'reply', message: 'Interrupted.', data: { request_id: 'trace-abc12345' } }),
        ]),
        { status: 200 },
      ) as never,
    );
    const { streamChat } = await import('./api');
    let caught: unknown;
    try {
      await streamChat('s1', 'u1', 'hi', 'socratic', true, undefined, { onToken: () => {} });
    } catch (err) {
      caught = err;
    }
    expect(caught).toBeInstanceOf(Error);
    expect((caught as { requestId?: string }).requestId).toBe('trace-abc12345');
    expect((caught as Error).message).toMatch(/interrupted/i);
    expect((caught as Error).message).toContain('trace-abc');
  });

  it('rejects when the stream never sends done', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        sseBody([ev('token', { type: 'token', step: 'reply', message: '', data: { delta: 'x' } })]),
        { status: 200 },
      ) as never,
    );
    const { streamChat } = await import('./api');
    await expect(
      streamChat('s1', 'u1', 'hi', 'socratic', true, undefined, { onToken: () => {} }),
    ).rejects.toThrow(/without a done/i);
  });

  it('surfaces retryable:false from the error event on the thrown ChatStreamError (#151a)', async () => {
    // The backend marks errors after landed graph/mastery writes with
    // retryable:false — a client fallback would re-run the turn and
    // double-apply them. The flag must survive onto the thrown error so
    // the ladder can skip its JSON rung.
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        sseBody([
          ev('error', {
            type: 'error', step: 'reply', message: 'Interrupted.',
            data: { request_id: 'r1', retryable: false },
          }),
        ]),
        { status: 200 },
      ) as never,
    );
    const { streamChat, ChatStreamError } = await import('./api');
    let caught: unknown;
    try {
      await streamChat('s1', 'u1', 'hi', 'socratic', true, undefined, {});
    } catch (err) {
      caught = err;
    }
    expect(caught).toBeInstanceOf(ChatStreamError);
    expect((caught as InstanceType<typeof ChatStreamError>).retryable).toBe(false);
  });

  // ADR 0030: Sonnet 5.5 sends its post-tool reply in one burst right before
  // `done`. The client reveals it progressively and must not resolve (the
  // caller's cue to swap in the final message) until all of it is out.
  const BURST = 'word '.repeat(80);
  const burstThenDone = () =>
    sseBody([
      ev('progress', { type: 'progress', step: 'search_course_materials', message: 'Calling search_course_materials.' }),
      ev('token', { type: 'token', step: 'reply', message: '', data: { delta: BURST } }),
      ev('done', {
        type: 'done', step: 'reply', message: '',
        data: { reply: BURST, graph_update: {}, mastery_changes: [] },
      }),
    ]);

  it('reports tool-call progress and reveals a burst in steps before resolving', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(burstThenDone(), { status: 200 }) as never);
    const { streamChat } = await import('./api');
    const tokens: string[] = [];
    const steps: string[] = [];
    const result = await streamChat('s1', 'u1', 'hi', 'socratic', true, undefined, {
      onToken: (t) => tokens.push(t),
      onProgress: (s) => steps.push(s),
    });
    expect(steps).toEqual(['search_course_materials']);
    expect(tokens.length).toBeGreaterThan(1);
    expect(tokens.join('')).toBe(BURST);
    expect(result.reply).toBe(BURST);
  });

  it('Stop pressed mid-reveal ends the reveal and rejects as an abort', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(burstThenDone(), { status: 200 }) as never);
    const { streamChat } = await import('./api');
    const controller = new AbortController();
    const tokens: string[] = [];
    const pending = streamChat('s1', 'u1', 'hi', 'socratic', true, undefined, {
      onToken: (t) => {
        tokens.push(t);
        if (tokens.length === 1) controller.abort();
      },
      signal: controller.signal,
    });
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
    // What had arrived is all out, for the caller's interrupted bubble.
    expect(tokens.join('')).toBe(BURST);
  });

  it('flushes queued text before rejecting on a mid-stream error (ADR 0020 partial)', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        sseBody([
          ev('token', { type: 'token', step: 'reply', message: '', data: { delta: BURST } }),
          ev('error', { type: 'error', step: 'reply', message: 'Interrupted.', data: { request_id: 'r1' } }),
        ]),
        { status: 200 },
      ) as never,
    );
    const { streamChat } = await import('./api');
    const tokens: string[] = [];
    await expect(
      streamChat('s1', 'u1', 'hi', 'socratic', true, undefined, { onToken: (t) => tokens.push(t) }),
    ).rejects.toThrow(/interrupted/i);
    expect(tokens.join('')).toBe(BURST);
  });

  it('defaults retryable to true when the error event carries no flag', async () => {
    // Additive-field compatibility: older backends (and the no-writes
    // rungs) omit or set retryable true — the ladder keeps its Rung 3.
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        sseBody([
          ev('error', {
            type: 'error', step: 'reply', message: 'Interrupted.',
            data: { request_id: 'r1' },
          }),
        ]),
        { status: 200 },
      ) as never,
    );
    const { streamChat, ChatStreamError } = await import('./api');
    let caught: unknown;
    try {
      await streamChat('s1', 'u1', 'hi', 'socratic', true, undefined, {});
    } catch (err) {
      caught = err;
    }
    expect(caught).toBeInstanceOf(ChatStreamError);
    expect((caught as InstanceType<typeof ChatStreamError>).retryable).toBe(true);
  });
});

describe('shouldFallBackToJson (the client rung-3 ladder decision, #151a)', () => {
  it('is false for a ChatStreamError marked retryable:false', async () => {
    const { ChatStreamError, shouldFallBackToJson } = await import('./api');
    expect(shouldFallBackToJson(new ChatStreamError('Interrupted.', 'r1', false))).toBe(false);
  });

  it('is true for a ChatStreamError without an explicit flag', async () => {
    const { ChatStreamError, shouldFallBackToJson } = await import('./api');
    expect(shouldFallBackToJson(new ChatStreamError('Interrupted.', 'r1'))).toBe(true);
  });

  it('is false for an HTTP 413 (the JSON fallback fails identically)', async () => {
    const { ApiError, shouldFallBackToJson } = await import('./api');
    expect(shouldFallBackToJson(new ApiError('{"detail":"too large"}', 413))).toBe(false);
    // The streamSSE throw shape: a bare Error with .status attached.
    const streamErr = Object.assign(new Error('{"detail":"too large"}'), { status: 413 });
    expect(shouldFallBackToJson(streamErr)).toBe(false);
    // And the empty-body shape, where only the message carries the status.
    expect(shouldFallBackToJson(new Error('HTTP 413'))).toBe(false);
  });

  it('is true for transport-ish failures with no status', async () => {
    const { shouldFallBackToJson } = await import('./api');
    expect(shouldFallBackToJson(new TypeError('Failed to fetch'))).toBe(true);
    expect(shouldFallBackToJson(new Error('Stream stalled — no data received.'))).toBe(true);
  });
});
