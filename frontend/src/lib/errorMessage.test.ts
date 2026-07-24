import { describe, expect, it } from 'vitest';
import { extractErrorDetail, humanizeError, isNotFound, statusOf } from './errorMessage';
import { ApiError } from './api';

const FALLBACK = "Couldn't load that.";

describe('extractErrorDetail', () => {
  it('reads the detail out of a FastAPI error body', () => {
    expect(extractErrorDetail(new Error('{"detail":"Exam not found."}')))
      .toEqual({ detail: 'Exam not found.' });
  });

  it('reads the detail off a bare JSON string', () => {
    expect(extractErrorDetail('{"detail":"Study guide generation failed."}'))
      .toEqual({ detail: 'Study guide generation failed.' });
  });

  it('tolerates whitespace around the body', () => {
    expect(extractErrorDetail('  \n{"detail":"Exam not found."}\n '))
      .toEqual({ detail: 'Exam not found.' });
  });

  it('reads the first msg out of a FastAPI validation detail array', () => {
    const body = JSON.stringify({
      detail: [{ loc: ['query', 'exam_id'], msg: 'field required', type: 'value_error' }],
    });
    expect(extractErrorDetail(new Error(body))).toEqual({ detail: 'field required' });
  });

  it('accepts an already-parsed body object', () => {
    expect(extractErrorDetail({ detail: 'Exam not found.' }))
      .toEqual({ detail: 'Exam not found.' });
  });

  it('ignores a blank or non-string detail', () => {
    expect(extractErrorDetail('{"detail":"   "}')).toEqual({});
    expect(extractErrorDetail('{"detail":42}')).toEqual({});
    expect(extractErrorDetail('{"detail":null}')).toEqual({});
    expect(extractErrorDetail('{"detail":[]}')).toEqual({});
  });

  it('returns nothing for non-JSON, malformed, or empty input', () => {
    expect(extractErrorDetail(new Error('boom'))).toEqual({});
    expect(extractErrorDetail('{not json')).toEqual({});
    expect(extractErrorDetail('')).toEqual({});
    expect(extractErrorDetail(null)).toEqual({});
    expect(extractErrorDetail(undefined)).toEqual({});
    expect(extractErrorDetail(0)).toEqual({});
    expect(extractErrorDetail(['a', 'b'])).toEqual({});
  });
});

describe('statusOf', () => {
  it('reads the bare "HTTP <code>" fetchJSON throws for an empty body', () => {
    expect(statusOf(new Error('HTTP 404'))).toBe(404);
    expect(statusOf('HTTP 502')).toBe(502);
  });

  it('reads a status attached to the thrown value', () => {
    expect(statusOf({ status: 403 })).toBe(403);
    expect(statusOf({ statusCode: 429 })).toBe(429);
  });

  it('reads a status carried inside the JSON body', () => {
    expect(statusOf('{"detail":"Nope.","status":401}')).toBe(401);
    expect(statusOf('{"detail":"Nope.","status_code":409}')).toBe(409);
  });

  it('prefers an attached status over one parsed from the message', () => {
    const err = Object.assign(new Error('HTTP 500'), { status: 404 });
    expect(statusOf(err)).toBe(404);
  });

  it('ignores values that are not plausible HTTP statuses', () => {
    expect(statusOf({ status: 42 })).toBeUndefined();
    expect(statusOf({ status: '404' })).toBeUndefined();
    expect(statusOf('HTTP 4040')).toBeUndefined();
    expect(statusOf('there are 404 items')).toBeUndefined();
  });

  it('returns undefined when no status is recoverable', () => {
    expect(statusOf(new Error('{"detail":"Exam not found."}'))).toBeUndefined();
    expect(statusOf(null)).toBeUndefined();
    expect(statusOf(undefined)).toBeUndefined();
  });
});

describe('humanizeError — status mapping', () => {
  it('maps auth failures to sign-in / permission copy', () => {
    expect(humanizeError('HTTP 401', FALLBACK)).toMatch(/sign in again/i);
    expect(humanizeError('HTTP 403', FALLBACK)).toMatch(/access/i);
  });

  it('maps 404 to not-found copy', () => {
    expect(humanizeError('HTTP 404', FALLBACK)).toMatch(/couldn't find/i);
  });

  it('maps 429 to rate-limit copy', () => {
    expect(humanizeError('HTTP 429', FALLBACK)).toMatch(/too many requests/i);
  });

  it('maps 5xx to try-again-later copy', () => {
    expect(humanizeError('HTTP 500', FALLBACK)).toMatch(/our end/i);
    expect(humanizeError('HTTP 502', FALLBACK)).toMatch(/temporarily unavailable/i);
    expect(humanizeError('HTTP 503', FALLBACK)).toMatch(/temporarily unavailable/i);
    expect(humanizeError('HTTP 504', FALLBACK)).toMatch(/temporarily unavailable/i);
  });

  it('maps the remaining actionable 4xx codes', () => {
    expect(humanizeError('HTTP 400', FALLBACK)).toMatch(/wasn't valid/i);
    expect(humanizeError('HTTP 408', FALLBACK)).toMatch(/too long/i);
    expect(humanizeError('HTTP 409', FALLBACK)).toMatch(/reload/i);
  });

  it('falls back for statuses with no dedicated copy', () => {
    expect(humanizeError('HTTP 418', FALLBACK)).toBe(FALLBACK);
    expect(humanizeError('HTTP 302', FALLBACK)).toBe(FALLBACK);
  });
});

describe('humanizeError — server detail', () => {
  it('surfaces a sentence-like FastAPI detail verbatim', () => {
    expect(humanizeError(new Error('{"detail":"Exam not found."}'), FALLBACK))
      .toBe('Exam not found.');
  });

  it('prefers the detail over the status copy', () => {
    const err = Object.assign(new Error('{"detail":"Exam not found."}'), { status: 404 });
    expect(humanizeError(err, FALLBACK)).toBe('Exam not found.');
  });

  it('falls back to status copy when the detail is not presentable', () => {
    expect(humanizeError({ detail: '[object Object]', status: 502 }, FALLBACK))
      .toMatch(/temporarily unavailable/i);
    expect(humanizeError({ detail: 'x'.repeat(400), status: 500 }, FALLBACK))
      .toMatch(/our end/i);
  });

  it('never leaks a raw body, markup, a stack or [object Object]', () => {
    const cases: unknown[] = [
      new Error('{"error":{"code":"boom"}}'),
      { detail: '{"nested":"payload"}' },
      { detail: '<html><body>502 Bad Gateway</body></html>' },
      { detail: 'Traceback (most recent call last)' },
      { detail: 'Error: boom\n    at loadGuide (Study.tsx:190:7)' },
      { detail: '[object Object]' },
      { detail: '   ' },
      { detail: '!!!' },
    ];
    for (const err of cases) {
      const out = humanizeError(err, FALLBACK);
      expect(out).toBe(FALLBACK);
    }
  });

  it('returns the fallback for anything unrecognizable', () => {
    expect(humanizeError(new Error('kaboom'), FALLBACK)).toBe(FALLBACK);
    expect(humanizeError('kaboom', FALLBACK)).toBe(FALLBACK);
    expect(humanizeError(null, FALLBACK)).toBe(FALLBACK);
    expect(humanizeError(undefined, FALLBACK)).toBe(FALLBACK);
    expect(humanizeError(0, FALLBACK)).toBe(FALLBACK);
    expect(humanizeError(Symbol('nope'), FALLBACK)).toBe(FALLBACK);
    expect(humanizeError({}, FALLBACK)).toBe(FALLBACK);
    expect(humanizeError([1, 2, 3], FALLBACK)).toBe(FALLBACK);
  });
});

describe('isNotFound', () => {
  it('recognizes the study-guide 404, whose status fetchJSON discards', () => {
    expect(isNotFound(new Error('{"detail":"Exam not found."}'))).toBe(true);
    expect(isNotFound(new Error('{"detail":"Exam not found. It may have been deleted."}'))).toBe(true);
  });

  it('recognizes a bare HTTP 404', () => {
    expect(isNotFound(new Error('HTTP 404'))).toBe(true);
    expect(isNotFound({ status: 404 })).toBe(true);
  });

  it('recognizes not-found wording on a plain error', () => {
    expect(isNotFound(new Error('Exam not found'))).toBe(true);
    expect(isNotFound('Course Not Found')).toBe(true);
  });

  it('lets an explicit status override the wording', () => {
    expect(isNotFound({ detail: 'Exam not found.', status: 500 })).toBe(false);
  });

  it('is false for every other failure', () => {
    expect(isNotFound(new Error('{"detail":"Study guide generation failed."}'))).toBe(false);
    expect(isNotFound(new Error('HTTP 502'))).toBe(false);
    expect(isNotFound('Failed to fetch')).toBe(false);
    expect(isNotFound(null)).toBe(false);
    expect(isNotFound(undefined)).toBe(false);
    expect(isNotFound({})).toBe(false);
  });
});

describe('ApiError integration', () => {
  it('branches on the status even when the wording gives nothing away', () => {
    // The whole point of ApiError carrying `status`: a 404 whose copy never
    // says "not found" must still route to guidance rather than a red toast.
    const err = new ApiError('{"detail":"That exam is no longer available."}', 404);
    expect(isNotFound(err)).toBe(true);
    expect(statusOf(err)).toBe(404);
  });

  it('does not treat a non-404 as missing just because it says not found', () => {
    const err = new ApiError('{"detail":"Course material not found for this exam."}', 502);
    expect(isNotFound(err)).toBe(false);
    expect(humanizeError(err, FALLBACK)).toBe('Course material not found for this exam.');
  });

  it('falls back to status copy when the body carries no readable detail', () => {
    expect(humanizeError(new ApiError('', 503), FALLBACK))
      .toBe("That's temporarily unavailable. Try again in a moment.");
    expect(humanizeError(new ApiError('<html>502 Bad Gateway</html>', 502), FALLBACK))
      .toBe("That's temporarily unavailable. Try again in a moment.");
  });
});
