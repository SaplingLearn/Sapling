import { describe, expect, it } from 'vitest';
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
    expect(config.matcher.map((m) => m.source)).toContain('/profile/:path*');
  });

  it('skips router prefetches on every protected route', () => {
    // Each prefetch used to run the /api/auth/me round trip; see the note on
    // `config` in middleware.ts.
    for (const m of config.matcher) {
      expect(m.missing).toEqual(
        expect.arrayContaining([
          { type: 'header', key: 'next-router-prefetch' },
          { type: 'header', key: 'purpose', value: 'prefetch' },
        ]),
      );
    }
  });
});
