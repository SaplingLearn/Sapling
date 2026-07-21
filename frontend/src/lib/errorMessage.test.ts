import { describe, expect, it } from 'vitest';
import { extractErrorDetail } from './errorMessage';

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
