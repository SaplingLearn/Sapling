import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { uploadDocumentStream } from './api';

/**
 * Build a Response that streams the given chunks via a ReadableStream,
 * mimicking what fetch() returns for a real SSE endpoint.
 *
 * Duplicated from sse.test.ts on purpose so this file stays self-contained
 * and the SSE library's own helpers don't have to be exported.
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

const realFetch = globalThis.fetch;

beforeEach(() => {
  globalThis.fetch = vi.fn() as unknown as typeof fetch;
});

afterEach(() => {
  globalThis.fetch = realFetch;
  vi.restoreAllMocks();
});

describe('uploadDocumentStream', () => {
  it('passes the supplied requestId through as the X-Request-ID header', async () => {
    // One result event carrying { id } so the function resolves successfully
    // and the test can assert on the fetch call without unhandled rejections.
    const payload =
      'event: result\ndata: {"type":"result","step":"done","message":"ok","data":{"id":"doc-1"}}\n\n' +
      'event: status\ndata: {"type":"status","step":"done","message":"Saved.","data":{"document_id":"doc-1"}}\n\n';

    const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValue(makeStreamingResponse([payload]));

    await uploadDocumentStream(new FormData(), () => {}, undefined, 'trace-xyz-1234');

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.headers).toEqual({ 'X-Request-ID': 'trace-xyz-1234' });
  });
});
