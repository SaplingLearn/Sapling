import { describe, expect, it } from 'vitest';
import { extractErrorDetail, statusOf } from './errorMessage';

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
