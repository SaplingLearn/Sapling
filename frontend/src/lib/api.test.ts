import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  extractSyllabus,
  uploadAvatar,
  uploadDocument,
  uploadDocumentStream,
} from './api';

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

  it('sends credentials: include so the cross-origin session cookie is attached', async () => {
    const payload =
      'event: result\ndata: {"type":"result","step":"done","message":"ok","data":{"id":"doc-1"}}\n\n' +
      'event: status\ndata: {"type":"status","step":"done","message":"Saved.","data":{"document_id":"doc-1"}}\n\n';

    const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValue(makeStreamingResponse([payload]));

    await uploadDocumentStream(new FormData(), () => {}, undefined);

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.credentials).toBe('include');
  });
});

/**
 * Cross-origin auth contract: every direct fetch() in api.ts that targets an
 * auth-protected endpoint MUST send credentials: 'include' so the browser
 * attaches the SameSite=None session cookie configured for
 * .saplinglearn.com. fetchJSON and uploadDocumentStream are covered above;
 * these tests pin the same contract on the three remaining FormData
 * uploaders that bypass fetchJSON.
 *
 * Add a new case here when introducing any new direct fetch() to an
 * auth-protected endpoint.
 */
describe('credentials: include on auth-protected multipart uploads', () => {
  function jsonResponse(body: unknown, status = 200): Response {
    return new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    });
  }

  it('uploadDocument (POST /api/documents/upload/sync)', async () => {
    const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValue(jsonResponse({ id: 'doc-1' }));

    await uploadDocument(new FormData());

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.credentials).toBe('include');
  });

  it('extractSyllabus (POST /api/calendar/extract)', async () => {
    const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValue(jsonResponse({ assignments: [] }));

    await extractSyllabus(new FormData(), 'u1');

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.credentials).toBe('include');
  });

  it('uploadAvatar (POST /api/profile/<id>/avatar) — JSON+base64', async () => {
    // FileReader isn't available in vitest's node env; stub the
    // global so readFileAsBase64 resolves synchronously to a known
    // base64 payload. Real browser upload tested in production.
    const originalFR = (globalThis as any).FileReader;
    (globalThis as any).FileReader = class MockFileReader {
      onload: ((e: any) => void) | null = null;
      onerror: ((e: any) => void) | null = null;
      result: string | null = null;
      readAsDataURL(_file: File) {
        this.result = 'data:image/png;base64,ZmFrZQ==';  // base64 of 'fake'
        queueMicrotask(() => this.onload?.({} as any));
      }
    };

    try {
      const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
      fetchMock.mockResolvedValue(jsonResponse({ avatar_url: 'https://x' }));

      const file = new File(['fake'], 'a.png', { type: 'image/png' });
      await uploadAvatar('u1', file);

      const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
      expect(url).toContain('/api/profile/u1/avatar');
      // No more `?user_id=` noise — the backend reads auth from the
      // session cookie.
      expect(url).not.toContain('?user_id=');
      expect(init.method).toBe('POST');
      expect(init.credentials).toBe('include');
      // JSON body, NOT multipart. This is the load-bearing assertion
      // for the `TypeError: Failed to fetch` regression class.
      expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/json');
      const body = JSON.parse(init.body as string);
      expect(body.file_b64).toBe('ZmFrZQ==');
      expect(body.content_type).toBe('image/png');
    } finally {
      (globalThis as any).FileReader = originalFR;
    }
  });
});
