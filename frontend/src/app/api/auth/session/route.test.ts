import { afterEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

const URL = 'https://app.saplinglearn.com/api/auth/session';
const SECRET = 'x'.repeat(32);

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

async function loadRoute(env: Record<string, string>) {
  vi.resetModules();
  for (const [k, v] of Object.entries(env)) vi.stubEnv(k, v);
  return import('./route');
}

function b64url(bytes: Uint8Array): string {
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
}

/** A token in the backend's wire format (services/session_tokens.py), with an
 * arbitrary payload — `typ: 'handoff'` is what the OAuth callback mints. */
async function mintToken(payload: Record<string, unknown>, secret = SECRET): Promise<string> {
  const payloadB64 = b64url(new TextEncoder().encode(JSON.stringify(payload)));
  const key = await crypto.subtle.importKey(
    'raw', new TextEncoder().encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'],
  );
  const sig = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(payloadB64));
  return `${payloadB64}.${b64url(new Uint8Array(sig))}`;
}

const inFiveMinutes = () => Math.floor(Date.now() / 1000) + 300;

const handoff = (userId: string) =>
  mintToken({ user_id: userId, exp: inFiveMinutes(), typ: 'handoff' });

function payloadOf(token: string): Record<string, unknown> {
  const b64 = token.slice(0, token.lastIndexOf('.')).replace(/-/g, '+').replace(/_/g, '/');
  return JSON.parse(atob(b64 + '='.repeat((4 - (b64.length % 4)) % 4)));
}

describe('session route — only a handoff token is exchanged (#756)', () => {
  async function exchange(authToken: string) {
    const { POST } = await loadRoute({ SESSION_SECRET: SECRET });
    return POST(new NextRequest(URL, {
      method: 'POST',
      headers: { origin: 'https://app.saplinglearn.com', 'content-type': 'application/json' },
      body: JSON.stringify({ authToken }),
    }));
  }

  it('exchanges the OAuth handoff token for a typed session cookie', async () => {
    const res = await exchange(await handoff('user_1'));
    expect(res.status).toBe(200);
    const cookie = res.cookies.get('sapling_session')?.value ?? '';
    expect(payloadOf(cookie)).toMatchObject({ user_id: 'user_1', typ: 'session' });
  });

  it('refuses to re-mint a live session (no extending a session forever)', async () => {
    const session = await mintToken({ user_id: 'user_1', exp: inFiveMinutes() + 86400, typ: 'session' });
    const res = await exchange(session);
    expect(res.status).toBe(401);
    expect(res.cookies.get('sapling_session')).toBeUndefined();
  });

  it('refuses a legacy untyped 30-day session', async () => {
    const thirtyDays = Math.floor(Date.now() / 1000) + 30 * 86400;
    const res = await exchange(await mintToken({ user_id: 'user_1', exp: thirtyDays }));
    expect(res.status).toBe(401);
  });

  it('deploy-order transition: exchanges an untyped SHORT-LIVED token (an old backend’s handoff)', async () => {
    // A frontend deployed before the backend still lets sign-in through.
    const res = await exchange(await mintToken({ user_id: 'user_1', exp: inFiveMinutes() }));
    expect(res.status).toBe(200);
    expect(payloadOf(res.cookies.get('sapling_session')?.value ?? '')).toMatchObject({
      user_id: 'user_1', typ: 'session',
    });
  });

  it('the untyped allowance ends at the handoff ceiling plus skew (660 s)', async () => {
    const now = Math.floor(Date.now() / 1000);
    expect((await exchange(await mintToken({ user_id: 'u', exp: now + 650 }))).status).toBe(200);
    expect((await exchange(await mintToken({ user_id: 'u', exp: now + 700 }))).status).toBe(401);
  });

  it('a typed session is refused however little life it has left', async () => {
    const res = await exchange(await mintToken({ user_id: 'u', exp: inFiveMinutes(), typ: 'session' }));
    expect(res.status).toBe(401);
  });

  it('refuses an expired handoff token', async () => {
    const expired = await mintToken({
      user_id: 'user_1', exp: Math.floor(Date.now() / 1000) - 1, typ: 'handoff',
    });
    expect((await exchange(expired)).status).toBe(401);
  });
});

describe('session route — COOKIE_DOMAIN validation (#190)', () => {
  it('does not scope the cleared cookie to an overly-broad COOKIE_DOMAIN', async () => {
    // Pre-fix: COOKIE_DOMAIN='.com' was applied verbatim → cookie.domain='.com'.
    const { DELETE } = await loadRoute({ SESSION_SECRET: SECRET, COOKIE_DOMAIN: '.com' });
    const res = await DELETE(new NextRequest(URL, { method: 'DELETE' }));
    expect(res.cookies.get('sapling_session')?.domain).toBeUndefined();
  });

  it('keeps a well-formed COOKIE_DOMAIN', async () => {
    const { DELETE } = await loadRoute({
      SESSION_SECRET: SECRET,
      COOKIE_DOMAIN: '.saplinglearn.com',
    });
    const res = await DELETE(new NextRequest(URL, { method: 'DELETE' }));
    expect(res.cookies.get('sapling_session')?.domain).toBe('.saplinglearn.com');
  });
});

describe('session route — CSRF / same-origin enforcement (#190)', () => {
  it('rejects a cross-origin POST with 403', async () => {
    // Pre-fix: no origin check → reaches auth → 401 for the bad token (not 403).
    const { POST } = await loadRoute({ SESSION_SECRET: SECRET });
    const req = new NextRequest(URL, {
      method: 'POST',
      headers: { origin: 'https://evil.example.org', 'content-type': 'application/json' },
      body: JSON.stringify({ authToken: 'forged' }),
    });
    const res = await POST(req);
    expect(res.status).toBe(403);
  });

  it('lets a same-origin POST through the CSRF check', async () => {
    const { POST } = await loadRoute({ SESSION_SECRET: SECRET });
    const req = new NextRequest(URL, {
      method: 'POST',
      headers: { origin: 'https://app.saplinglearn.com', 'content-type': 'application/json' },
      body: JSON.stringify({ authToken: 'invalid' }),
    });
    const res = await POST(req);
    // Not blocked as cross-origin; falls through to auth, which rejects the
    // bad token with 401. The point: same-origin requests aren't 403'd.
    expect(res.status).not.toBe(403);
    expect(res.status).toBe(401);
  });
});

describe('session route — PR preview hosts', () => {
  const PREVIEW = 'https://pr-742-frontend-staging.saplinglearn.workers.dev';

  async function signIn(origin: string) {
    const { POST } = await loadRoute({ SESSION_SECRET: SECRET, DEPLOY_ENV: 'staging' });
    const req = new NextRequest(`${origin}/api/auth/session`, {
      method: 'POST',
      headers: { origin, 'content-type': 'application/json' },
      body: JSON.stringify({ authToken: await handoff('user_1') }),
    });
    return POST(req);
  }

  it('sets a host-only session cookie on a preview host', async () => {
    // A `.staging.saplinglearn.com` Domain from a workers.dev host is dropped
    // by the browser, so the preview would never stay signed in.
    const res = await signIn(PREVIEW);
    expect(res.status).toBe(200);
    const cookie = res.cookies.get('sapling_session');
    expect(cookie?.value).toBeTruthy();
    expect(cookie?.domain).toBeUndefined();
  });

  it('keeps the staging cookie domain on the staging host', async () => {
    const res = await signIn('https://staging.saplinglearn.com');
    expect(res.status).toBe(200);
    expect(res.cookies.get('sapling_session')?.domain).toBe('.staging.saplinglearn.com');
  });

  it('clears the host-only cookie on a preview host', async () => {
    const { DELETE } = await loadRoute({ SESSION_SECRET: SECRET, DEPLOY_ENV: 'staging' });
    const res = await DELETE(new NextRequest(`${PREVIEW}/api/auth/session`, { method: 'DELETE' }));
    expect(res.cookies.get('sapling_session')?.domain).toBeUndefined();
  });

  it('does not treat a lookalike suffix as inside the cookie domain', async () => {
    const res = await signIn('https://evilstaging.saplinglearn.com');
    expect(res.cookies.get('sapling_session')?.domain).toBeUndefined();
  });
});
