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

describe('session route — malformed request bodies (testathon hardening)', () => {
  async function postRaw(body: string | undefined) {
    const { POST } = await loadRoute({ SESSION_SECRET: SECRET });
    return POST(new NextRequest(URL, {
      method: 'POST',
      headers: { origin: 'https://app.saplinglearn.com', 'content-type': 'application/json' },
      ...(body === undefined ? {} : { body }),
    }));
  }

  it('answers 400, not 500, for a body that is not JSON', async () => {
    // `request.json()` throws here; the throw used to escape the handler.
    const res = await postRaw('not json at all');
    expect(res.status).toBe(400);
  });

  it('answers 400, not 500, for an absent body', async () => {
    const res = await postRaw(undefined);
    expect(res.status).toBe(400);
  });

  it('answers 400 for JSON that is not an object', async () => {
    const res = await postRaw('"just a string"');
    expect(res.status).toBe(400);
  });

  it('answers 400 when authToken is the wrong type', async () => {
    const res = await postRaw(JSON.stringify({ authToken: { nested: true } }));
    expect(res.status).toBe(400);
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

describe('session route — minted session lifetime', () => {
  it('mints a 7-day session carrying iat', async () => {
    const { POST } = await loadRoute({ SESSION_SECRET: SECRET });
    const res = await POST(new NextRequest(URL, {
      method: 'POST',
      headers: { origin: 'https://app.saplinglearn.com', 'content-type': 'application/json' },
      body: JSON.stringify({ authToken: await handoff('user_1') }),
    }));
    const cookie = res.cookies.get('sapling_session');
    const payload = payloadOf(cookie?.value ?? '');
    const now = Math.floor(Date.now() / 1000);
    expect(Math.abs((payload.iat as number) - now)).toBeLessThanOrEqual(2);
    expect((payload.exp as number) - Math.floor(payload.iat as number)).toBe(7 * 86400);
    expect(cookie?.maxAge).toBe(7 * 86400);
  });

  it('mints iat to the millisecond and exp in whole seconds', async () => {
    // A whole-second iat cannot tell a session minted earlier in a sign-out's
    // own second from one minted after it (backend auth_guard.issued_before).
    const { POST } = await loadRoute({ SESSION_SECRET: SECRET });
    const authToken = await handoff('user_1');
    const spy = vi.spyOn(Date, 'now').mockReturnValue(1_700_000_012_345);
    try {
      const res = await POST(new NextRequest(URL, {
        method: 'POST',
        headers: { origin: 'https://app.saplinglearn.com', 'content-type': 'application/json' },
        body: JSON.stringify({ authToken }),
      }));
      const payload = payloadOf(res.cookies.get('sapling_session')?.value ?? '');
      expect(payload.iat).toBe(1_700_000_012.345);
      expect(payload.iat_precision).toBe('ms');
      expect(payload.exp).toBe(1_700_000_012 + 7 * 86400);
    } finally {
      spy.mockRestore();
    }
  });

  it('marks an iat on a whole second as milliseconds, not a legacy whole-second one', async () => {
    // JSON.stringify writes 1700000012.000 as the integer 1700000012; the
    // backend reads such an iat as legacy (anywhere in its second) unless the
    // token says it is to the millisecond (auth_guard.issued_before).
    const { POST } = await loadRoute({ SESSION_SECRET: SECRET });
    const authToken = await handoff('user_1');
    const spy = vi.spyOn(Date, 'now').mockReturnValue(1_700_000_012_000);
    try {
      const res = await POST(new NextRequest(URL, {
        method: 'POST',
        headers: { origin: 'https://app.saplinglearn.com', 'content-type': 'application/json' },
        body: JSON.stringify({ authToken }),
      }));
      const payload = payloadOf(res.cookies.get('sapling_session')?.value ?? '');
      expect(payload.iat).toBe(1_700_000_012);
      expect(payload.iat_precision).toBe('ms');
    } finally {
      spy.mockRestore();
    }
  });
});

describe('session route — Secure cookie', () => {
  async function signInOver(url: string, headers: Record<string, string> = {}) {
    const { POST } = await loadRoute({ SESSION_SECRET: SECRET, NODE_ENV: 'development' });
    const origin = new globalThis.URL(url).origin;
    return POST(new NextRequest(url, {
      method: 'POST',
      headers: { origin, 'content-type': 'application/json', ...headers },
      body: JSON.stringify({ authToken: await handoff('user_1') }),
    }));
  }

  it('is Secure on an https request even outside a production build', async () => {
    const res = await signInOver('https://app.saplinglearn.com/api/auth/session');
    expect(res.cookies.get('sapling_session')?.secure).toBe(true);
  });

  it('is Secure behind a TLS-terminating proxy (x-forwarded-proto)', async () => {
    const res = await signInOver('http://localhost:3000/api/auth/session', {
      'x-forwarded-proto': 'https',
    });
    expect(res.cookies.get('sapling_session')?.secure).toBe(true);
  });

  it('stays non-Secure on plain-http local dev', async () => {
    const res = await signInOver('http://localhost:3000/api/auth/session');
    expect(res.cookies.get('sapling_session')?.secure).toBeFalsy();
  });
});

describe('session route — sign-out revokes server-side', () => {
  const realFetch = globalThis.fetch;
  afterEach(() => {
    globalThis.fetch = realFetch;
  });

  function mockBackend(status = 200) {
    const calls: { url: string; init: RequestInit }[] = [];
    globalThis.fetch = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      calls.push({ url: String(url), init: init ?? {} });
      return new Response(JSON.stringify({ ok: status === 200 }), { status });
    }) as unknown as typeof fetch;
    return calls;
  }

  const signOut = async (query = '', cookie = 'sapling_session=tok.sig') => {
    const { DELETE } = await loadRoute({ SESSION_SECRET: SECRET, BACKEND_URL: 'http://backend:5000' });
    return DELETE(new NextRequest(`${URL}${query}`, {
      method: 'DELETE',
      headers: cookie ? { cookie } : {},
    }));
  };

  it('calls POST /api/auth/logout with the cookie before clearing it', async () => {
    const calls = mockBackend();
    const res = await signOut();
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe('http://backend:5000/api/auth/logout');
    expect(calls[0].init.method).toBe('POST');
    expect((calls[0].init.headers as Record<string, string>).Cookie).toBe('sapling_session=tok.sig');
    expect(await res.json()).toMatchObject({ ok: true, revoked: true });
    expect(res.cookies.get('sapling_session')?.value).toBe('');
  });

  it('still clears the cookie when the backend refuses or is down', async () => {
    mockBackend(503);
    const res = await signOut();
    expect(await res.json()).toMatchObject({ ok: true, revoked: false });
    expect(res.cookies.get('sapling_session')?.value).toBe('');

    globalThis.fetch = vi.fn(async () => {
      throw new TypeError('network down');
    }) as unknown as typeof fetch;
    const res2 = await signOut();
    expect(res2.status).toBe(200);
    expect(res2.cookies.get('sapling_session')?.value).toBe('');
  });

  it('scope=local only drops this cookie (the sign-in callback discarding a half-made session)', async () => {
    const calls = mockBackend();
    const res = await signOut('?scope=local');
    expect(calls).toHaveLength(0);
    expect(res.cookies.get('sapling_session')?.value).toBe('');
  });

  it('makes no backend call without a cookie', async () => {
    const calls = mockBackend();
    await signOut('', '');
    expect(calls).toHaveLength(0);
  });

  it('still refuses a cross-origin sign-out', async () => {
    const calls = mockBackend();
    const { DELETE } = await loadRoute({ SESSION_SECRET: SECRET, BACKEND_URL: 'http://backend:5000' });
    const res = await DELETE(new NextRequest(URL, {
      method: 'DELETE',
      headers: { origin: 'https://evil.example.org', cookie: 'sapling_session=tok.sig' },
    }));
    expect(res.status).toBe(403);
    expect(calls).toHaveLength(0);
  });
});
