import { afterEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';
import { middleware, config } from './middleware';
import { ONBOARDING_PREFIX, SHELL_PREFIXES } from '@/lib/appRoutes';

const ORIGIN = 'https://app.saplinglearn.com';

function req(path: string): NextRequest {
  // No session cookie → unauthenticated visitor.
  return new NextRequest(`${ORIGIN}${path}`);
}

describe('middleware — /profile gating (#189)', () => {
  it('redirects an unauthenticated /profile/:id request (no longer passes through)', async () => {
    const res = await middleware(req('/profile/some-user-id'));
    // Pre-fix: /profile wasn't protected → NextResponse.next() (status 200, no
    // Location). Post-fix: redirected to sign-in.
    expect(res.headers.get('location')).toBeTruthy();
    expect(res.status).toBe(307);
  });

  it('still lets a genuinely public path pass through (no over-broadening)', async () => {
    const res = await middleware(req('/about'));
    expect(res.headers.get('location')).toBeNull();
  });

  it('lists /profile in config.matcher so middleware actually runs there', () => {
    expect(config.matcher).toContain('/profile/:path*');
  });

  it('config.matcher (a static literal Next requires) covers exactly SHELL_PREFIXES plus /onboarding', () => {
    expect([...config.matcher].sort()).toEqual(
      [...SHELL_PREFIXES, ONBOARDING_PREFIX].map((p) => `${p}/:path*`).sort(),
    );
  });

  it('sends a signed-out visitor to /onboarding through sign-in', async () => {
    const res = await middleware(req('/onboarding'));
    expect(res.headers.get('location')).toBeTruthy();
    expect(res.status).toBe(307);
  });
});

describe('middleware — the Study tools are gated wherever they are served', () => {
  // /flashcards became a (shell) page without joining SHELL_PREFIXES or the
  // matcher, so it was served to signed-out and unapproved visitors.
  it.each(['/flashcards', '/flashcards/deck-1', '/study/guide'])(
    'redirects an unauthenticated %s request',
    async (path) => {
      const res = await middleware(req(path));
      expect(res.status).toBe(307);
      expect(res.headers.get('location')).toBeTruthy();
    },
  );

  it('lists /flashcards in config.matcher so middleware actually runs there', () => {
    // `/x/:path*` also matches the bare `/x`, as for every other entry.
    expect(config.matcher).toContain('/flashcards/:path*');
    expect(config.matcher).toContain('/study/:path*');
  });

  it('does not gate a look-alike path', async () => {
    const res = await middleware(req('/flashcards-import'));
    expect(res.headers.get('location')).toBeNull();
  });
});

describe('middleware — sign-in return origin (PR previews)', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it('starts sign-in at its own /auth/start (which sets the nonce and the return origin)', async () => {
    // API_URL is resolved at import, so load a staging-configured copy.
    vi.resetModules();
    vi.stubEnv('DEPLOY_ENV', 'staging');
    const { middleware: stagingMiddleware } = await import('./middleware');

    const preview = 'https://pr-742-frontend-staging.saplinglearn.workers.dev';
    const res = await stagingMiddleware(new NextRequest(`${preview}/dashboard`));
    const location = new URL(res.headers.get('location') ?? '');
    // sec2 M2: /auth/start sets this browser's sign-in nonce cookie, then
    // hands on to the backend's /api/auth/google with return_to = this origin.
    expect(location.origin).toBe(preview);
    expect(location.pathname).toBe('/auth/start');
  });
});

describe('middleware — host-only session cookie (sec2 M1)', () => {
  const SECRET = 's'.repeat(32);
  const enc = (bytes: Uint8Array) =>
    btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  async function sign(payload: Record<string, unknown>): Promise<string> {
    const payloadB64 = enc(new TextEncoder().encode(JSON.stringify(payload)));
    const key = await crypto.subtle.importKey(
      'raw', new TextEncoder().encode(SECRET), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'],
    );
    const sig = new Uint8Array(await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(payloadB64)));
    return `${payloadB64}.${enc(sig)}`;
  }

  /** The production middleware, with /me answering approved + onboarded. */
  async function prod() {
    vi.resetModules();
    vi.stubEnv('SESSION_SECRET', SECRET);
    vi.stubEnv('DEPLOY_ENV', 'production');
    const fetchSpy = vi.fn(async () => new Response(
      JSON.stringify({ is_approved: true, onboarding_completed: true }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    ));
    vi.stubGlobal('fetch', fetchSpy);
    const { middleware: mw } = await import('./middleware');
    const { signSession } = await import('@/lib/sessionToken');
    const run = (cookie: string) =>
      mw(new NextRequest('https://saplinglearn.com/dashboard', { headers: { cookie } }));
    return { run, fetchSpy, signSession };
  }

  const cookieSentToBackend = (spy: ReturnType<typeof vi.fn>) =>
    ((spy.mock.calls[0] as unknown[])[1] as { headers: Record<string, string> }).headers.Cookie;

  it('reads __Host-sapling_session and forwards it under that name', async () => {
    const { run, fetchSpy, signSession } = await prod();
    const token = await signSession('user_1');
    const res = await run(`__Host-sapling_session=${token}`);
    expect(res.headers.get('location')).toBeNull();
    expect(cookieSentToBackend(fetchSpy)).toBe(`__Host-sapling_session=${token}`);
  });

  it('honours a pre-sec2 session in the legacy domain-wide cookie (nobody is logged out)', async () => {
    const { run, fetchSpy } = await prod();
    const now = Math.floor(Date.now() / 1000);
    const legacy = await sign({ user_id: 'user_1', exp: now + 3600, typ: 'session', iat: now - 60 });
    const res = await run(`sapling_session=${legacy}`);
    expect(res.headers.get('location')).toBeNull();
    expect(cookieSentToBackend(fetchSpy)).toBe(`__Host-sapling_session=${legacy}`);
  });

  it('refuses a current session tossed in under the legacy name by a sibling subdomain', async () => {
    const { run, fetchSpy, signSession } = await prod();
    const res = await run(`sapling_session=${await signSession('attacker')}`);
    expect(new URL(res.headers.get('location') ?? '').searchParams.get('error')).toBe('session_expired');
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('prefers the host-only cookie when both are present', async () => {
    const { run, fetchSpy, signSession } = await prod();
    const token = await signSession('user_1');
    await run(`sapling_session=junk.junk; __Host-sapling_session=${token}`);
    expect(cookieSentToBackend(fetchSpy)).toBe(`__Host-sapling_session=${token}`);
  });
});

describe('middleware — only a definitive /me answer ends the session (#756)', () => {
  const LOCAL = 'http://localhost:3000';
  const SECRET = 's'.repeat(32);

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  async function load() {
    vi.resetModules();
    vi.stubEnv('SESSION_SECRET', SECRET);
    vi.stubEnv('BACKEND_URL', 'http://localhost:5000');
    const { middleware: mw } = await import('./middleware');
    const tokens = await import('@/lib/sessionToken');
    return { mw, ...tokens };
  }

  async function run(me: Response | Error, path = '/dashboard') {
    const { mw, signSession } = await load();
    vi.stubGlobal('fetch', vi.fn(async () => {
      if (me instanceof Error) throw me;
      return me;
    }));
    return mw(new NextRequest(`${LOCAL}${path}`, {
      headers: { cookie: `sapling_session=${await signSession('user_1')}` },
    }));
  }

  const json = (status: number, body: unknown = {}) =>
    new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
  const errorCode = (res: Response) =>
    new URL(res.headers.get('location') ?? `${LOCAL}/`).searchParams.get('error');

  it.each([401, 404])('a %s from /me is an expired session', async (status) => {
    expect(errorCode(await run(json(status)))).toBe('session_expired');
  });

  it.each([500, 502, 503, 429])('a %s from /me lets the request through', async (status) => {
    // Pre-fix: any non-OK /me redirected with session_expired.
    expect((await run(json(status))).headers.get('location')).toBeNull();
  });

  it('a timeout or network error lets the request through', async () => {
    // Pre-fix: the 3 s abort redirected with signin_failed.
    const res = await run(new DOMException('aborted', 'AbortError'));
    expect(res.headers.get('location')).toBeNull();
  });

  it('a non-JSON 200 lets the request through', async () => {
    expect((await run(new Response('<html>', { status: 200 }))).headers.get('location')).toBeNull();
  });

  it('an unapproved account still goes to /pending', async () => {
    const res = await run(json(200, { is_approved: false }));
    expect(new URL(res.headers.get('location') ?? '').pathname).toBe('/pending');
  });

  it.each(['/flashcards', '/study/guide'])('an unapproved account on %s goes to /pending too', async (path) => {
    const res = await run(json(200, { is_approved: false }), path);
    expect(new URL(res.headers.get('location') ?? '').pathname).toBe('/pending');
  });

  it('an expired session on /flashcards is ended like any shell route', async () => {
    expect(errorCode(await run(json(401), '/flashcards'))).toBe('session_expired');
  });

  it('an approved account passes', async () => {
    expect((await run(json(200, { is_approved: true }))).headers.get('location')).toBeNull();
  });

  // Onboarding is enforced (owner decision, 2026-11-12), off the same /me read.
  const pathOf = (res: Response) => {
    const location = res.headers.get('location');
    return location ? new URL(location).pathname : null;
  };

  it('sends an approved account that has not finished onboarding from the app to /onboarding', async () => {
    const res = await run(json(200, { is_approved: true, onboarding_completed: false }));
    expect(pathOf(res)).toBe('/onboarding');
  });

  it('lets an onboarded account into the app', async () => {
    const res = await run(json(200, { is_approved: true, onboarding_completed: true }));
    expect(pathOf(res)).toBeNull();
  });

  it('sends an onboarded account away from /onboarding to the dashboard', async () => {
    const res = await run(json(200, { is_approved: true, onboarding_completed: true }), '/onboarding');
    expect(pathOf(res)).toBe('/dashboard');
  });

  it('lets an account that has not finished onboarding onto /onboarding', async () => {
    const res = await run(json(200, { is_approved: true, onboarding_completed: false }), '/onboarding');
    expect(pathOf(res)).toBeNull();
  });

  it('sends an unapproved account from /onboarding to /pending first', async () => {
    const res = await run(json(200, { is_approved: false, onboarding_completed: false }), '/onboarding');
    expect(pathOf(res)).toBe('/pending');
  });

  it('acts only on a definite answer: no onboarding field lets the request through', async () => {
    expect(pathOf(await run(json(200, { is_approved: true })))).toBeNull();
    expect(pathOf(await run(json(200, { is_approved: true }), '/onboarding'))).toBeNull();
  });

  it('a /me blip on /onboarding lets the request through (#756)', async () => {
    expect(pathOf(await run(json(503), '/onboarding'))).toBeNull();
  });

  it('a handoff token in the cookie is not a session', async () => {
    const { mw, verifySession } = await load();
    const enc = (s: string) => btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
    const payloadB64 = enc(JSON.stringify({ user_id: 'user_1', exp: 9999999999, typ: 'handoff' }));
    const key = await crypto.subtle.importKey(
      'raw', new TextEncoder().encode(SECRET), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'],
    );
    const sig = new Uint8Array(await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(payloadB64)));
    const token = `${payloadB64}.${enc(String.fromCharCode(...sig))}`;
    expect(await verifySession(token)).toBeNull();
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    const res = await mw(new NextRequest(`${LOCAL}/dashboard`, {
      headers: { cookie: `sapling_session=${token}` },
    }));
    expect(errorCode(res)).toBe('session_expired');
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('a session older than 7 days is not a session, whatever its exp', async () => {
    const { verifySession } = await load();
    const enc = (s: string) => btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
    const key = await crypto.subtle.importKey(
      'raw', new TextEncoder().encode(SECRET), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'],
    );
    const sign = async (payload: Record<string, unknown>) => {
      const payloadB64 = enc(JSON.stringify(payload));
      const sig = new Uint8Array(await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(payloadB64)));
      return `${payloadB64}.${enc(String.fromCharCode(...sig))}`;
    };
    const now = Math.floor(Date.now() / 1000);
    const day = 86400;
    // iat 8 days ago, exp still in the future.
    expect(await verifySession(await sign({ user_id: 'u', iat: now - 8 * day, exp: now + day, typ: 'session' })))
      .toBeNull();
    // A pre-iat 30-day cookie minted 8 days ago (dated exp - 30 days).
    expect(await verifySession(await sign({ user_id: 'u', exp: now + 22 * day }))).toBeNull();
    // ...but one minted yesterday still verifies.
    expect(await verifySession(await sign({ user_id: 'u', exp: now + 29 * day }))).toEqual({ userId: 'u' });
    // An iat in the future is refused.
    expect(await verifySession(await sign({ user_id: 'u', iat: now + 3600, exp: now + day }))).toBeNull();
    // A millisecond iat (what both minters issue) verifies.
    expect(await verifySession(await sign({ user_id: 'u', iat: now - 0.655, exp: now + day, typ: 'session' })))
      .toEqual({ userId: 'u' });
  });
});
