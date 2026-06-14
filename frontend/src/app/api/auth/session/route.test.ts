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
