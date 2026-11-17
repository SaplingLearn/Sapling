/**
 * sec2 M1: which cookie carries the session, and the legacy-cookie grace.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

import {
  readSessionCookie,
  sessionCookieName,
  usesHostCookies,
  verifiedSessionCookie,
} from '@/lib/sessionCookie';
import { signSession } from '@/lib/sessionToken';

const SECRET = 'z'.repeat(32);

afterEach(() => vi.unstubAllEnvs());

const req = (url: string, cookie?: string, headers: Record<string, string> = {}) =>
  new NextRequest(url, { headers: { ...headers, ...(cookie ? { cookie } : {}) } });

function b64url(bytes: Uint8Array): string {
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
}

/** A session as the pre-sec2 BFF minted it: no `cookie: "host"` claim. */
async function preSec2Session(userId: string): Promise<string> {
  const now = Math.floor(Date.now() / 1000);
  const payloadB64 = b64url(new TextEncoder().encode(JSON.stringify({
    user_id: userId, exp: now + 3600, typ: 'session', iat: now - 60, iat_precision: 'ms',
  })));
  const key = await crypto.subtle.importKey(
    'raw', new TextEncoder().encode(SECRET), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'],
  );
  const sig = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(payloadB64));
  return `${payloadB64}.${b64url(new Uint8Array(sig))}`;
}

describe('cookie name', () => {
  it('is __Host- over https and plain over http', () => {
    expect(sessionCookieName(req('https://saplinglearn.com/'))).toBe('__Host-sapling_session');
    expect(sessionCookieName(req('http://localhost:3000/'))).toBe('sapling_session');
    expect(sessionCookieName(req('http://localhost:3000/', undefined, { 'x-forwarded-proto': 'https' })))
      .toBe('__Host-sapling_session');
  });

  it('is always __Host- in a deployed environment, even on a stray http request', () => {
    vi.stubEnv('DEPLOY_ENV', 'production');
    expect(usesHostCookies(req('http://saplinglearn.com/'))).toBe(true);
  });
});

describe('reading the session cookie', () => {
  it('prefers __Host- over the legacy name on https', () => {
    expect(readSessionCookie(req('https://saplinglearn.com/', 'sapling_session=old; __Host-sapling_session=new')))
      .toEqual({ token: 'new', legacy: false });
    expect(readSessionCookie(req('https://saplinglearn.com/', 'sapling_session=old')))
      .toEqual({ token: 'old', legacy: true });
  });

  it('over http the plain cookie is the session cookie (not legacy)', () => {
    expect(readSessionCookie(req('http://localhost:3000/', 'sapling_session=tok')))
      .toEqual({ token: 'tok', legacy: false });
    expect(readSessionCookie(req('http://localhost:3000/', '__Host-sapling_session=tok'))).toBeNull();
  });

  it('honours a pre-sec2 session in the legacy cookie, refuses a current one there', async () => {
    vi.stubEnv('SESSION_SECRET', SECRET);
    const old = await preSec2Session('user_1');
    expect(await verifiedSessionCookie(req('https://saplinglearn.com/', `sapling_session=${old}`)))
      .toEqual({ userId: 'user_1', token: old });
    const current = await signSession('attacker');
    expect(await verifiedSessionCookie(req('https://saplinglearn.com/', `sapling_session=${current}`)))
      .toBeNull();
    expect(await verifiedSessionCookie(req('https://saplinglearn.com/', `__Host-sapling_session=${current}`)))
      .toEqual({ userId: 'attacker', token: current });
  });
});
