import { afterEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

const URL = 'https://app.saplinglearn.com/api/auth/session';
const ORIGIN = 'https://app.saplinglearn.com';
const SECRET = 'x'.repeat(32);
const NONCE = 'n'.repeat(43);
const BACKEND = 'http://backend:5000';

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.resetModules();
});

async function loadRoute(env: Record<string, string>) {
  vi.resetModules();
  vi.stubEnv('BACKEND_URL', BACKEND);
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
  mintToken({ user_id: userId, exp: inFiveMinutes(), typ: 'handoff', jti: 'j'.repeat(24), bh: 'b'.repeat(43) });

function payloadOf(token: string): Record<string, unknown> {
  const b64 = token.slice(0, token.lastIndexOf('.')).replace(/-/g, '+').replace(/_/g, '/');
  return JSON.parse(atob(b64 + '='.repeat((4 - (b64.length % 4)) % 4)));
}

type Call = { url: string; init: RequestInit };

/** A fake backend: /handoff/exchange answers `exchange` (a user id = 200,
 * a number = that status), /logout answers `logout`. */
function mockBackend(opts: { exchange?: string | number; logout?: number } = {}): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    calls.push({ url: String(url), init: init ?? {} });
    if (String(url).endsWith('/api/auth/handoff/exchange')) {
      const answer = opts.exchange ?? 'user_1';
      if (typeof answer === 'number') return new Response('{}', { status: answer });
      return new Response(JSON.stringify({ user_id: answer }), { status: 200 });
    }
    const status = opts.logout ?? 200;
    return new Response(JSON.stringify({ ok: status === 200 }), { status });
  }));
  return calls;
}

/** Every Set-Cookie header, parsed: name, value and lower-cased attributes. */
function setCookies(res: Response) {
  return res.headers.getSetCookie().map((raw) => {
    const [pair, ...attrs] = raw.split(';').map((s) => s.trim());
    const eq = pair.indexOf('=');
    const map = new Map<string, string>();
    for (const a of attrs) {
      const i = a.indexOf('=');
      map.set((i < 0 ? a : a.slice(0, i)).toLowerCase(), i < 0 ? '' : a.slice(i + 1));
    }
    return { name: pair.slice(0, eq), value: pair.slice(eq + 1), attrs: map, raw };
  });
}

const cookieNamed = (res: Response, name: string) => setCookies(res).filter((c) => c.name === name);

async function exchange(
  authToken: string,
  opts: { url?: string; env?: Record<string, string>; cookie?: string | null } = {},
) {
  const url = opts.url ?? URL;
  const { POST } = await loadRoute({ SESSION_SECRET: SECRET, ...(opts.env ?? {}) });
  const https = url.startsWith('https:');
  const nonceCookie = opts.cookie === undefined
    ? `${https ? '__Host-sapling_signin' : 'sapling_signin'}=${NONCE}`
    : opts.cookie;
  return POST(new NextRequest(url, {
    method: 'POST',
    headers: {
      origin: new globalThis.URL(url).origin,
      'content-type': 'application/json',
      ...(nonceCookie ? { cookie: nonceCookie } : {}),
    },
    body: JSON.stringify({ authToken }),
  }));
}

describe('session route — handoff exchange (#756, sec2 M2)', () => {
  it('exchanges the OAuth handoff for a host-only __Host- session cookie', async () => {
    const calls = mockBackend();
    const token = await handoff('user_1');
    const res = await exchange(token);
    expect(res.status).toBe(200);
    const [cookie] = cookieNamed(res, '__Host-sapling_session');
    expect(payloadOf(cookie.value)).toMatchObject({ user_id: 'user_1', typ: 'session', cookie: 'host' });
    // The __Host- contract: Secure, Path=/, no Domain.
    expect(cookie.attrs.has('secure')).toBe(true);
    expect(cookie.attrs.get('path')).toBe('/');
    expect(cookie.attrs.has('domain')).toBe(false);
    expect(cookie.attrs.has('httponly')).toBe(true);
    expect(cookie.attrs.get('samesite')?.toLowerCase()).toBe('lax');
    // The backend consumed it with this browser's nonce.
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe(`${BACKEND}/api/auth/handoff/exchange`);
    expect(JSON.parse(String(calls[0].init.body))).toEqual({ token, nonce: NONCE });
  });

  it('spends the sign-in nonce cookie', async () => {
    mockBackend();
    const res = await exchange(await handoff('user_1'));
    const [nonce] = cookieNamed(res, '__Host-sapling_signin');
    expect(nonce.value).toBe('');
    expect(nonce.attrs.get('max-age')).toBe('0');
  });

  it('a replay (the backend says already used) is refused, no session', async () => {
    mockBackend({ exchange: 401 });
    const res = await exchange(await handoff('user_1'));
    expect(res.status).toBe(401);
    expect(cookieNamed(res, '__Host-sapling_session')).toHaveLength(0);
  });

  it('a handoff opened in another browser (no nonce cookie) sends no nonce and is refused', async () => {
    const calls = mockBackend({ exchange: 401 });
    const res = await exchange(await handoff('user_1'), { cookie: null });
    expect(res.status).toBe(401);
    expect(JSON.parse(String(calls[0].init.body)).nonce).toBeNull();
    expect(cookieNamed(res, '__Host-sapling_session')).toHaveLength(0);
  });

  it('the plain-named nonce does not count on https (it could be tossed by a sibling subdomain)', async () => {
    const calls = mockBackend({ exchange: 401 });
    await exchange(await handoff('user_1'), { cookie: `sapling_signin=${NONCE}` });
    expect(JSON.parse(String(calls[0].init.body)).nonce).toBeNull();
  });

  it('fails closed (503) when the backend cannot answer', async () => {
    mockBackend({ exchange: 503 });
    const res = await exchange(await handoff('user_1'));
    expect(res.status).toBe(503);
    expect(cookieNamed(res, '__Host-sapling_session')).toHaveLength(0);

    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('network down');
    }));
    expect((await exchange(await handoff('user_1'))).status).toBe(503);
  });

  it('refuses when the backend names a different user than the token', async () => {
    mockBackend({ exchange: 'someone_else' });
    expect((await exchange(await handoff('user_1'))).status).toBe(401);
  });

  it('refuses to re-mint a live session (no extending a session forever)', async () => {
    const calls = mockBackend();
    const session = await mintToken({ user_id: 'user_1', exp: inFiveMinutes() + 86400, typ: 'session' });
    const res = await exchange(session);
    expect(res.status).toBe(401);
    expect(calls).toHaveLength(0);
  });

  it('no longer exchanges an untyped token (a handoff must be a current backend’s)', async () => {
    const calls = mockBackend();
    expect((await exchange(await mintToken({ user_id: 'user_1', exp: inFiveMinutes() }))).status).toBe(401);
    expect(calls).toHaveLength(0);
  });

  it('refuses an expired or forged handoff without calling the backend', async () => {
    const calls = mockBackend();
    const expired = await mintToken({
      user_id: 'user_1', exp: Math.floor(Date.now() / 1000) - 1, typ: 'handoff',
    });
    expect((await exchange(expired)).status).toBe(401);
    const forged = await mintToken(
      { user_id: 'user_1', exp: inFiveMinutes(), typ: 'handoff' }, 'y'.repeat(32),
    );
    expect((await exchange(forged)).status).toBe(401);
    expect(calls).toHaveLength(0);
  });
});

describe('session route — malformed request bodies (testathon hardening)', () => {
  async function postRaw(body: string | undefined) {
    const { POST } = await loadRoute({ SESSION_SECRET: SECRET });
    return POST(new NextRequest(URL, {
      method: 'POST',
      headers: { origin: ORIGIN, 'content-type': 'application/json' },
      ...(body === undefined ? {} : { body }),
    }));
  }

  it('answers 400, not 500, for a body that is not JSON', async () => {
    expect((await postRaw('not json at all')).status).toBe(400);
  });

  it('answers 400, not 500, for an absent body', async () => {
    expect((await postRaw(undefined)).status).toBe(400);
  });

  it('answers 400 for JSON that is not an object', async () => {
    expect((await postRaw('"just a string"')).status).toBe(400);
  });

  it('answers 400 when authToken is the wrong type', async () => {
    expect((await postRaw(JSON.stringify({ authToken: { nested: true } }))).status).toBe(400);
  });
});

describe('session route — legacy domain-wide cookie (sec2 M1 transition)', () => {
  it('signing in on prod deletes the old .saplinglearn.com cookie, never sets a Domain', async () => {
    mockBackend();
    const res = await exchange(await handoff('user_1'), {
      url: 'https://saplinglearn.com/api/auth/session',
      env: { DEPLOY_ENV: 'production' },
    });
    expect(res.status).toBe(200);
    const legacy = cookieNamed(res, 'sapling_session');
    expect(legacy.map((c) => c.attrs.get('domain') ?? null).sort()).toEqual(['.saplinglearn.com', null].sort());
    for (const c of legacy) {
      expect(c.value).toBe('');
      expect(c.attrs.get('max-age')).toBe('0');
    }
    for (const c of setCookies(res).filter((c) => c.name.startsWith('__Host-'))) {
      expect(c.attrs.has('domain')).toBe(false);
    }
  });

  it('on staging deletes the old .staging.saplinglearn.com cookie', async () => {
    mockBackend();
    const res = await exchange(await handoff('user_1'), {
      url: 'https://staging.saplinglearn.com/api/auth/session',
      env: { DEPLOY_ENV: 'staging' },
    });
    expect(cookieNamed(res, 'sapling_session').map((c) => c.attrs.get('domain'))).toContain(
      '.staging.saplinglearn.com',
    );
  });

  it('a preview host gets the __Host- cookie and only a host-only legacy delete', async () => {
    mockBackend();
    const preview = 'https://pr-742-frontend-staging.saplinglearn.workers.dev';
    const res = await exchange(await handoff('user_1'), {
      url: `${preview}/api/auth/session`, env: { DEPLOY_ENV: 'staging' },
    });
    expect(cookieNamed(res, '__Host-sapling_session')).toHaveLength(1);
    expect(cookieNamed(res, 'sapling_session').map((c) => c.attrs.get('domain'))).toEqual([undefined]);
  });

  it('a lookalike host is not inside the legacy domain', async () => {
    mockBackend();
    const res = await exchange(await handoff('user_1'), {
      url: 'https://evilstaging.saplinglearn.com/api/auth/session', env: { DEPLOY_ENV: 'staging' },
    });
    expect(cookieNamed(res, 'sapling_session').map((c) => c.attrs.get('domain'))).toEqual([undefined]);
  });

  it('an overly-broad COOKIE_DOMAIN is never used, even to clear (#190)', async () => {
    const { DELETE } = await loadRoute({ SESSION_SECRET: SECRET, COOKIE_DOMAIN: '.com' });
    mockBackend();
    const res = await DELETE(new NextRequest(URL, { method: 'DELETE' }));
    for (const c of setCookies(res)) expect(c.attrs.get('domain')).not.toBe('.com');
  });
});

describe('session route — local http keeps the plain cookie name', () => {
  it('signs in with a plain sapling_session over http (E2E, local dev)', async () => {
    mockBackend();
    const res = await exchange(await handoff('user_1'), {
      url: 'http://localhost:3000/api/auth/session', env: { NODE_ENV: 'development' },
    });
    expect(res.status).toBe(200);
    const [cookie] = cookieNamed(res, 'sapling_session');
    expect(cookie.value).toBeTruthy();
    expect(cookie.attrs.has('secure')).toBe(false);
    expect(cookie.attrs.has('domain')).toBe(false);
    expect(cookieNamed(res, '__Host-sapling_session')).toHaveLength(0);
  });

  it('is Secure behind a TLS-terminating proxy (x-forwarded-proto), and then __Host-', async () => {
    mockBackend();
    const { POST } = await loadRoute({ SESSION_SECRET: SECRET, NODE_ENV: 'development' });
    const res = await POST(new NextRequest('http://localhost:3000/api/auth/session', {
      method: 'POST',
      headers: {
        origin: 'http://localhost:3000', 'content-type': 'application/json',
        'x-forwarded-proto': 'https', cookie: `__Host-sapling_signin=${NONCE}`,
      },
      body: JSON.stringify({ authToken: await handoff('user_1') }),
    }));
    const [cookie] = cookieNamed(res, '__Host-sapling_session');
    expect(cookie.attrs.has('secure')).toBe(true);
  });
});

describe('session route — minted session lifetime', () => {
  it('mints a 7-day session carrying iat', async () => {
    mockBackend();
    const res = await exchange(await handoff('user_1'));
    const [cookie] = cookieNamed(res, '__Host-sapling_session');
    const payload = payloadOf(cookie.value);
    const now = Math.floor(Date.now() / 1000);
    expect(Math.abs((payload.iat as number) - now)).toBeLessThanOrEqual(2);
    expect((payload.exp as number) - Math.floor(payload.iat as number)).toBe(7 * 86400);
    expect(cookie.attrs.get('max-age')).toBe(String(7 * 86400));
  });

  it('mints iat to the millisecond and exp in whole seconds', async () => {
    mockBackend();
    const spy = vi.spyOn(Date, 'now').mockReturnValue(1_700_000_012_345);
    try {
      // The handoff's exp is checked against the mocked clock too.
      const res = await exchange(await mintToken({
        user_id: 'user_1', exp: 1_700_000_300, typ: 'handoff', jti: 'j'.repeat(24), bh: 'b'.repeat(43),
      }));
      const payload = payloadOf(cookieNamed(res, '__Host-sapling_session')[0].value);
      expect(payload.iat).toBe(1_700_000_012.345);
      expect(payload.iat_precision).toBe('ms');
      expect(payload.exp).toBe(1_700_000_012 + 7 * 86400);
    } finally {
      spy.mockRestore();
    }
  });

  it('marks an iat on a whole second as milliseconds, not a legacy whole-second one', async () => {
    mockBackend();
    const spy = vi.spyOn(Date, 'now').mockReturnValue(1_700_000_012_000);
    try {
      const res = await exchange(await mintToken({
        user_id: 'user_1', exp: 1_700_000_300, typ: 'handoff', jti: 'j'.repeat(24), bh: 'b'.repeat(43),
      }));
      const payload = payloadOf(cookieNamed(res, '__Host-sapling_session')[0].value);
      expect(payload.iat).toBe(1_700_000_012);
      expect(payload.iat_precision).toBe('ms');
    } finally {
      spy.mockRestore();
    }
  });
});

describe('session route — CSRF / same-origin enforcement (#190)', () => {
  it('rejects a cross-origin POST with 403', async () => {
    const { POST } = await loadRoute({ SESSION_SECRET: SECRET });
    const res = await POST(new NextRequest(URL, {
      method: 'POST',
      headers: { origin: 'https://evil.example.org', 'content-type': 'application/json' },
      body: JSON.stringify({ authToken: 'forged' }),
    }));
    expect(res.status).toBe(403);
  });

  it('lets a same-origin POST through the CSRF check', async () => {
    const { POST } = await loadRoute({ SESSION_SECRET: SECRET });
    const res = await POST(new NextRequest(URL, {
      method: 'POST',
      headers: { origin: ORIGIN, 'content-type': 'application/json' },
      body: JSON.stringify({ authToken: 'invalid' }),
    }));
    expect(res.status).toBe(401);
  });
});

describe('session route — sign-out revokes server-side', () => {
  const signOut = async (query = '', cookie = '__Host-sapling_session=tok.sig', url = URL) => {
    const { DELETE } = await loadRoute({ SESSION_SECRET: SECRET });
    return DELETE(new NextRequest(`${url}${query}`, {
      method: 'DELETE',
      headers: cookie ? { cookie } : {},
    }));
  };

  it('calls POST /api/auth/logout with the cookie (under the __Host- name) before clearing it', async () => {
    const calls = mockBackend();
    const res = await signOut();
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe(`${BACKEND}/api/auth/logout`);
    expect(calls[0].init.method).toBe('POST');
    expect((calls[0].init.headers as Record<string, string>).Cookie).toBe('__Host-sapling_session=tok.sig');
    expect(await res.json()).toMatchObject({ ok: true, revoked: true });
    expect(cookieNamed(res, '__Host-sapling_session')[0].value).toBe('');
    // ...and the legacy cookie goes too.
    expect(cookieNamed(res, 'sapling_session').length).toBeGreaterThan(0);
  });

  it('revokes a legacy-cookie session too', async () => {
    const calls = mockBackend();
    await signOut('', 'sapling_session=old.sig');
    expect((calls[0].init.headers as Record<string, string>).Cookie).toBe('__Host-sapling_session=old.sig');
  });

  it('still clears the cookie when the backend refuses or is down', async () => {
    mockBackend({ logout: 503 });
    const res = await signOut();
    expect(await res.json()).toMatchObject({ ok: true, revoked: false });
    expect(cookieNamed(res, '__Host-sapling_session')[0].value).toBe('');

    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('network down');
    }));
    const res2 = await signOut();
    expect(res2.status).toBe(200);
    expect(cookieNamed(res2, '__Host-sapling_session')[0].value).toBe('');
  });

  it('scope=local only drops this cookie (the sign-in callback discarding a half-made session)', async () => {
    const calls = mockBackend();
    const res = await signOut('?scope=local');
    expect(calls).toHaveLength(0);
    expect(cookieNamed(res, '__Host-sapling_session')[0].value).toBe('');
  });

  it('over http clears the plain cookie (the session cookie there)', async () => {
    mockBackend();
    const res = await signOut('', 'sapling_session=tok.sig', 'http://localhost:3000/api/auth/session');
    expect(cookieNamed(res, 'sapling_session')[0].value).toBe('');
    expect(cookieNamed(res, '__Host-sapling_session')).toHaveLength(0);
  });

  it('makes no backend call without a cookie', async () => {
    const calls = mockBackend();
    await signOut('', '');
    expect(calls).toHaveLength(0);
  });

  it('still refuses a cross-origin sign-out', async () => {
    const calls = mockBackend();
    const { DELETE } = await loadRoute({ SESSION_SECRET: SECRET });
    const res = await DELETE(new NextRequest(URL, {
      method: 'DELETE',
      headers: { origin: 'https://evil.example.org', cookie: '__Host-sapling_session=tok.sig' },
    }));
    expect(res.status).toBe(403);
    expect(calls).toHaveLength(0);
  });
});
