/**
 * `GET /auth/start` (sec2 M2): sets this browser's sign-in nonce cookie and
 * sends the browser to the backend's /api/auth/google with the nonce's
 * binding, so the OAuth handoff can be exchanged only in this browser.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

import { signinBinding } from '@/lib/signinNonce';

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

async function start(url: string, env: Record<string, string> = {}) {
  vi.resetModules();
  for (const [k, v] of Object.entries(env)) vi.stubEnv(k, v);
  const { GET } = await import('./route');
  return GET(new NextRequest(url));
}

function nonceCookie(res: Response, name: string) {
  const raw = res.headers.getSetCookie().find((c) => c.startsWith(`${name}=`));
  if (!raw) return null;
  const [pair, ...attrs] = raw.split(';').map((s) => s.trim());
  return { value: pair.slice(name.length + 1), attrs: attrs.map((a) => a.toLowerCase()) };
}

describe('/auth/start', () => {
  it('on prod: __Host- nonce cookie, and the binding goes to the API host', async () => {
    const res = await start('https://saplinglearn.com/auth/start', { DEPLOY_ENV: 'production' });
    expect(res.status).toBe(302);
    const location = new URL(res.headers.get('location') ?? '');
    expect(location.origin).toBe('https://api.saplinglearn.com');
    expect(location.pathname).toBe('/api/auth/google');
    expect(location.searchParams.get('return_to')).toBe('https://saplinglearn.com');

    const cookie = nonceCookie(res, '__Host-sapling_signin');
    expect(cookie).not.toBeNull();
    expect(cookie!.value).toMatch(/^[A-Za-z0-9_-]{43}$/);
    expect(cookie!.attrs).toEqual(expect.arrayContaining(['path=/', 'secure', 'httponly', 'samesite=lax', 'max-age=600']));
    expect(cookie!.attrs.some((a) => a.startsWith('domain='))).toBe(false);
    // The backend gets only the hash, never the nonce.
    expect(location.searchParams.get('binding')).toBe(await signinBinding(cookie!.value));
    expect(res.headers.get('location')).not.toContain(cookie!.value);
    expect(res.headers.get('cache-control')).toBe('no-store');
  });

  it('a fresh nonce every time', async () => {
    const a = nonceCookie(await start('https://saplinglearn.com/auth/start', { DEPLOY_ENV: 'production' }), '__Host-sapling_signin');
    const b = nonceCookie(await start('https://saplinglearn.com/auth/start', { DEPLOY_ENV: 'production' }), '__Host-sapling_signin');
    expect(a!.value).not.toBe(b!.value);
  });

  it('passes a well-formed popup_id through and drops a malformed one', async () => {
    const ok = new URL((await start('https://saplinglearn.com/auth/start?popup_id=abc-123', { DEPLOY_ENV: 'production' }))
      .headers.get('location') ?? '');
    expect(ok.searchParams.get('popup_id')).toBe('abc-123');
    const bad = new URL((await start('https://saplinglearn.com/auth/start?popup_id=%3Cx%3E', { DEPLOY_ENV: 'production' }))
      .headers.get('location') ?? '');
    expect(bad.searchParams.get('popup_id')).toBeNull();
  });

  it('a staging preview sends its own origin as return_to to the staging API', async () => {
    const preview = 'https://pr-742-frontend-staging.saplinglearn.workers.dev';
    const location = new URL((await start(`${preview}/auth/start`, { DEPLOY_ENV: 'staging' })).headers.get('location') ?? '');
    expect(location.origin).toBe('https://api.staging.saplinglearn.com');
    expect(location.searchParams.get('return_to')).toBe(preview);
  });

  it('local http: plain nonce cookie, same-origin /api/auth/google when no API origin is set', async () => {
    const res = await start('http://localhost:3000/auth/start', { NEXT_PUBLIC_API_URL: '', NODE_ENV: 'development' });
    const location = new URL(res.headers.get('location') ?? '');
    expect(location.origin).toBe('http://localhost:3000');
    expect(location.pathname).toBe('/api/auth/google');
    const cookie = nonceCookie(res, 'sapling_signin');
    expect(cookie).not.toBeNull();
    expect(cookie!.attrs).not.toContain('secure');
    expect(nonceCookie(res, '__Host-sapling_signin')).toBeNull();
  });
});
