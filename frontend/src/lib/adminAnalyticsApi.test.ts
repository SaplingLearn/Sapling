import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { adminErrors, adminLlmCost, adminUsageByUser, adminUsageSummary } from './api';

/** The #121 data layer's wrapper contract: each helper hits its
 * /api/admin/analytics endpoint and forwards only the params the caller set,
 * so the backend's defaults (last 30 days, group_by=feature, no bucket)
 * stay server-owned. */

const realFetch = globalThis.fetch;

const okJson = () =>
  new Response(JSON.stringify({}), { status: 200, headers: { 'Content-Type': 'application/json' } });

beforeEach(() => {
  globalThis.fetch = vi.fn().mockResolvedValue(okJson()) as unknown as typeof fetch;
});

afterEach(() => {
  globalThis.fetch = realFetch;
  vi.restoreAllMocks();
});

function calledURL(): URL {
  const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
  expect(fetchMock).toHaveBeenCalledTimes(1);
  return new URL(fetchMock.mock.calls[0][0] as string, 'http://test.local');
}

const FROM = '2026-07-01T00:00:00+00:00';
const TO = '2026-08-01T00:00:00+00:00';

describe('adminUsageSummary', () => {
  it('hits the endpoint bare when no params are given', async () => {
    await adminUsageSummary();
    const url = calledURL();
    expect(url.pathname).toBe('/api/admin/analytics/usage/summary');
    expect(url.search).toBe('');
  });

  it('forwards from/to/bucket', async () => {
    await adminUsageSummary({ from: FROM, to: TO, bucket: 'day' });
    const url = calledURL();
    expect(url.searchParams.get('from')).toBe(FROM);
    expect(url.searchParams.get('to')).toBe(TO);
    expect(url.searchParams.get('bucket')).toBe('day');
  });
});

describe('adminUsageByUser', () => {
  it('forwards range and pagination', async () => {
    await adminUsageByUser({ from: FROM, to: TO, limit: 25, offset: 100 });
    const url = calledURL();
    expect(url.pathname).toBe('/api/admin/analytics/usage/by-user');
    expect(url.searchParams.get('limit')).toBe('25');
    expect(url.searchParams.get('offset')).toBe('100');
  });
});

describe('adminLlmCost', () => {
  it('forwards group_by and bucket', async () => {
    await adminLlmCost({ from: FROM, to: TO, group_by: 'model', bucket: 'day' });
    const url = calledURL();
    expect(url.pathname).toBe('/api/admin/analytics/llm/cost');
    expect(url.searchParams.get('group_by')).toBe('model');
    expect(url.searchParams.get('bucket')).toBe('day');
  });

  it('omits group_by when unset so the server default (feature) applies', async () => {
    await adminLlmCost({ from: FROM, to: TO });
    expect(calledURL().searchParams.has('group_by')).toBe(false);
  });
});

describe('adminErrors', () => {
  it('forwards range, pagination, and bucket', async () => {
    await adminErrors({ from: FROM, to: TO, limit: 10, offset: 20, bucket: 'day' });
    const url = calledURL();
    expect(url.pathname).toBe('/api/admin/analytics/errors');
    expect(url.searchParams.get('limit')).toBe('10');
    expect(url.searchParams.get('offset')).toBe('20');
    expect(url.searchParams.get('bucket')).toBe('day');
  });
});
