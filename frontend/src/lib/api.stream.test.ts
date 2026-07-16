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

    expect(tokens).toEqual(['Hel', 'lo']);
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
});
