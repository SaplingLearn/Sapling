import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  ApiError,
  extractSyllabus,
  getCourses,
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

  it('uploadAvatar rejects oversized files BEFORE base64-encoding', async () => {
    // CodeRabbit review: don't waste cycles encoding a 50 MB file just
    // to throw it out. The size check must run before readFileAsBase64.
    const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockClear();

    let frInstantiated = false;
    const originalFR = (globalThis as any).FileReader;
    (globalThis as any).FileReader = class {
      constructor() { frInstantiated = true; }
      readAsDataURL() {}
      onload: ((e: any) => void) | null = null;
      onerror: ((e: any) => void) | null = null;
    };

    try {
      // 6 MB > 5 MB cap.
      const oversize = new File([new Uint8Array(6 * 1024 * 1024)], 'big.png', { type: 'image/png' });
      await expect(uploadAvatar('u1', oversize)).rejects.toThrow(/max is 5 MB/);
      // FileReader must NOT have been touched.
      expect(frInstantiated).toBe(false);
      // Network must NOT have been hit.
      expect(fetchMock).not.toHaveBeenCalled();
    } finally {
      (globalThis as any).FileReader = originalFR;
    }
  });
});

describe('fetchJSON error shape', () => {
  it('throws an ApiError carrying the HTTP status, body text preserved', async () => {
    const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValue(
      new Response('{"detail":"Exam not found."}', { status: 404 }),
    );

    // The status is what lets lib/errorMessage branch without pattern-matching
    // the copy; the message stays the raw body so existing callers are unaffected.
    const err = await getCourses('u1').catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(404);
    expect((err as ApiError).message).toBe('{"detail":"Exam not found."}');
  });

  it('still reports a status when the body is empty', async () => {
    const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValue(new Response('', { status: 502 }));

    const err = await getCourses('u1').catch((e: unknown) => e);
    expect((err as ApiError).status).toBe(502);
    expect((err as ApiError).message).toBe('HTTP 502');
  });
});

/**
 * The coded envelope (#537). Quiz routes answer with
 * `{error: {code, message, request_id}, detail, request_id}` and a `Retry-After`
 * header on 429. Before this, fetchJSON kept only the body text and the status,
 * so QUIZ_RATE_LIMITED / QUIZ_DAILY_LIMIT_REACHED / QUIZ_GENERATION_TIMEOUT were
 * indistinguishable to the UI (R1 §H, gap G12).
 */
describe('fetchJSON coded-error envelope', () => {
  function codedResponse(
    body: unknown,
    status: number,
    headers: Record<string, string> = {},
  ): Response {
    return new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json', ...headers },
    });
  }

  it('lifts error.code and error.request_id onto the ApiError', async () => {
    const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValue(
      codedResponse(
        {
          error: {
            code: 'QUIZ_GENERATION_TIMEOUT',
            message: 'Quiz generation timed out.',
            request_id: 'req-1',
          },
          detail: 'Quiz generation timed out.',
          request_id: 'req-1',
        },
        502,
      ),
    );

    const err = (await getCourses('u1').catch((e: unknown) => e)) as ApiError;
    expect(err.code).toBe('QUIZ_GENERATION_TIMEOUT');
    expect(err.requestId).toBe('req-1');
    expect(err.status).toBe(502);
    // The raw body still comes through as the message, unchanged.
    expect(err.message).toContain('QUIZ_GENERATION_TIMEOUT');
  });

  it('parses the whole body onto ApiError.body', async () => {
    const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValue(
      codedResponse(
        { error: { code: 'QUIZ_COUNT_OUT_OF_RANGE', message: 'Between 1 and 10.' } },
        422,
      ),
    );

    const err = (await getCourses('u1').catch((e: unknown) => e)) as ApiError;
    expect(err.body).toEqual({
      error: { code: 'QUIZ_COUNT_OUT_OF_RANGE', message: 'Between 1 and 10.' },
    });
  });

  it('reads whole-second Retry-After off a 429', async () => {
    const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValue(
      codedResponse({ error: { code: 'QUIZ_RATE_LIMITED', message: 'Slow down.' } }, 429, {
        'Retry-After': '37',
      }),
    );

    const err = (await getCourses('u1').catch((e: unknown) => e)) as ApiError;
    expect(err.retryAfterSec).toBe(37);
  });

  it('ignores an HTTP-date Retry-After rather than guessing', async () => {
    const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValue(
      codedResponse({}, 429, { 'Retry-After': 'Wed, 21 Oct 2026 07:28:00 GMT' }),
    );

    const err = (await getCourses('u1').catch((e: unknown) => e)) as ApiError;
    expect(err.retryAfterSec).toBeUndefined();
  });

  it('leaves the coded fields undefined for a legacy {detail} body', async () => {
    const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValue(
      codedResponse({ detail: 'Exam not found.', request_id: 'req-legacy' }, 404),
    );

    const err = (await getCourses('u1').catch((e: unknown) => e)) as ApiError;
    expect(err.code).toBeUndefined();
    expect(err.retryAfterSec).toBeUndefined();
    // The legacy shape still carries a top-level request_id; keep it.
    expect(err.requestId).toBe('req-legacy');
  });

  it('survives a non-JSON body (an HTML 502 from a proxy)', async () => {
    const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValue(new Response('<html>502 Bad Gateway</html>', { status: 502 }));

    const err = (await getCourses('u1').catch((e: unknown) => e)) as ApiError;
    expect(err.body).toBeUndefined();
    expect(err.code).toBeUndefined();
    expect(err.message).toBe('<html>502 Bad Gateway</html>');
  });
});
