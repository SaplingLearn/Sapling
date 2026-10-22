import { afterEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';
import { middleware, config } from './middleware';

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
