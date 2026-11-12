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

describe('middleware — sign-in return origin (PR previews)', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it('sends its own origin as return_to on the Google sign-in redirect', async () => {
    // API_URL is resolved at import, so load a staging-configured copy.
    vi.resetModules();
    vi.stubEnv('DEPLOY_ENV', 'staging');
    const { middleware: stagingMiddleware } = await import('./middleware');

    const preview = 'https://pr-742-frontend-staging.saplinglearn.workers.dev';
    const res = await stagingMiddleware(new NextRequest(`${preview}/dashboard`));
    const location = new URL(res.headers.get('location') ?? '');
    expect(location.origin).toBe('https://api.staging.saplinglearn.com');
    expect(location.pathname).toBe('/api/auth/google');
    expect(location.searchParams.get('return_to')).toBe(preview);
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
});
