import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { streamSSE, type SSEEvent } from './sse';

/**
 * Build a Response that streams the given chunks via a ReadableStream,
 * mimicking what fetch() returns for a real SSE endpoint.
 */
function makeStreamingResponse(
  chunks: string[],
  init: { status?: number; headers?: Record<string, string> } = {},
): Response {
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      const enc = new TextEncoder();
      for (const c of chunks) controller.enqueue(enc.encode(c));
      controller.close();
    },
  });
  return new Response(stream, {
    status: init.status ?? 200,
    headers: init.headers ?? { 'Content-Type': 'text/event-stream' },
  });
}

async function collect<T>(gen: AsyncGenerator<T>): Promise<T[]> {
  const out: T[] = [];
  for await (const v of gen) out.push(v);
  return out;
}

const realFetch = globalThis.fetch;

beforeEach(() => {
  // Each test installs its own mock; ensure we start clean.
  globalThis.fetch = vi.fn() as unknown as typeof fetch;
});

afterEach(() => {
  globalThis.fetch = realFetch;
  vi.restoreAllMocks();
});

function mockFetchResponse(res: Response): void {
  (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(res);
}

describe('streamSSE', () => {
  it('parses two event:progress blocks separated by \\n\\n (happy path)', async () => {
    const payload =
      'event: progress\ndata: {"step":1}\n\n' +
      'event: progress\ndata: {"step":2}\n\n';
    mockFetchResponse(makeStreamingResponse([payload]));

    const events = await collect(streamSSE<{ step: number }>('/x', { method: 'POST' }));

    expect(events).toHaveLength(2);
    expect(events[0]).toEqual<SSEEvent<{ step: number }>>({
      event: 'progress',
      data: { step: 1 },
    });
    expect(events[1]).toEqual<SSEEvent<{ step: number }>>({
      event: 'progress',
      data: { step: 2 },
    });
  });

  it('defaults event name to "message" when event: is omitted', async () => {
    const payload = 'data: {"hello":"world"}\n\n';
    mockFetchResponse(makeStreamingResponse([payload]));

    const events = await collect(streamSSE<{ hello: string }>('/x', { method: 'POST' }));

    expect(events).toHaveLength(1);
    expect(events[0].event).toBe('message');
    expect(events[0].data).toEqual({ hello: 'world' });
  });

  it('joins multiple data: lines with \\n; JSON-parses when valid, falls back to raw string otherwise', async () => {
    // Valid JSON split across two data: lines.
    const jsonPayload = 'event: chunk\ndata: {"a":\ndata: 1}\n\n';
    mockFetchResponse(makeStreamingResponse([jsonPayload]));
    const jsonEvents = await collect(streamSSE<{ a: number }>('/x', { method: 'POST' }));
    expect(jsonEvents).toHaveLength(1);
    expect(jsonEvents[0]).toEqual({ event: 'chunk', data: { a: 1 } });

    // Non-JSON multi-line: the parser falls back to the raw joined string.
    const rawPayload = 'event: log\ndata: line one\ndata: line two\n\n';
    mockFetchResponse(makeStreamingResponse([rawPayload]));
    const rawEvents = await collect(streamSSE<string>('/x', { method: 'POST' }));
    expect(rawEvents).toHaveLength(1);
    expect(rawEvents[0]).toEqual({ event: 'log', data: 'line one\nline two' });
  });

  it('handles \\r\\n line endings the same as \\n', async () => {
    const payload =
      'event: progress\r\ndata: {"step":1}\r\n\r\n' +
      'event: progress\r\ndata: {"step":2}\r\n\r\n';
    mockFetchResponse(makeStreamingResponse([payload]));

    const events = await collect(streamSSE<{ step: number }>('/x', { method: 'POST' }));

    expect(events).toHaveLength(2);
    expect(events[0]).toEqual({ event: 'progress', data: { step: 1 } });
    expect(events[1]).toEqual({ event: 'progress', data: { step: 2 } });
  });

  it('ignores comment lines starting with ":"', async () => {
    const payload =
      ': this is a heartbeat comment\n' +
      'event: progress\n' +
      ': another comment\n' +
      'data: {"step":1}\n\n';
    mockFetchResponse(makeStreamingResponse([payload]));

    const events = await collect(streamSSE<{ step: number }>('/x', { method: 'POST' }));

    expect(events).toHaveLength(1);
    expect(events[0]).toEqual({ event: 'progress', data: { step: 1 } });
  });

  it('reassembles a single event split mid-JSON across multiple chunks', async () => {
    // Split the payload so the JSON value is broken across reads.
    const chunks = [
      'event: progress\ndata: {"foo":',
      '"bar","n":42}\n\n',
    ];
    mockFetchResponse(makeStreamingResponse(chunks));

    const events = await collect(streamSSE<{ foo: string; n: number }>('/x', { method: 'POST' }));

    expect(events).toHaveLength(1);
    expect(events[0]).toEqual({
      event: 'progress',
      data: { foo: 'bar', n: 42 },
    });
  });

  it('flushes a trailing block even when the stream ends without a final blank line', async () => {
    // No "\n\n" at the end — generator should still yield the buffered block.
    const payload = 'event: done\ndata: {"x":1}';
    mockFetchResponse(makeStreamingResponse([payload]));

    const events = await collect(streamSSE<{ x: number }>('/x', { method: 'POST' }));

    expect(events).toHaveLength(1);
    expect(events[0]).toEqual({ event: 'done', data: { x: 1 } });
  });

  it('throws on a non-2xx response and yields no events', async () => {
    const errorBody = 'upload failed: file too large';
    mockFetchResponse(
      makeStreamingResponse([errorBody], {
        status: 413,
        headers: { 'Content-Type': 'text/plain' },
      }),
    );

    const gen = streamSSE('/x', { method: 'POST' });
    await expect(collect(gen)).rejects.toThrow(errorBody);
  });

  it('correctly splits events separated by \\r\\n\\r\\n with no junk leaking between blocks', async () => {
    const payload =
      'event: a\r\ndata: {"i":1}\r\n\r\n' +
      'event: b\r\ndata: {"i":2}\r\n\r\n';
    mockFetchResponse(makeStreamingResponse([payload]));

    const events = await collect(streamSSE<{ i: number }>('/x', { method: 'POST' }));

    expect(events).toHaveLength(2);
    expect(events[0]).toEqual({ event: 'a', data: { i: 1 } });
    expect(events[1]).toEqual({ event: 'b', data: { i: 2 } });
  });
});
