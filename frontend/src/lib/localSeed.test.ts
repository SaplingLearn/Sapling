/**
 * #715: where a just-signed-in account goes. On a developer's local backend a
 * new Google account is getting the sample dataset copied onto it, so it waits
 * on the hold screen instead of landing on an empty /onboarding. Anywhere
 * else GET /api/auth/local-seed 404s and the routing is exactly what it was.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { postSignInRoute, SETUP_ROUTE } from './localSeed';

function stubStatus(status: number, body: unknown = {}) {
  const fetchMock = vi.fn(async () => ({
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers(),
    json: async () => body,
    text: async () => JSON.stringify(body),
  }) as unknown as Response);
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe('#715 postSignInRoute', () => {
  it('sends an onboarded account to the dashboard without asking', async () => {
    const fetchMock = stubStatus(200, { state: 'pending' });
    expect(await postSignInRoute(true)).toBe('/dashboard');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each(['pending', 'seeding', 'failed'])('holds a %s account on the setup screen', async (state) => {
    stubStatus(200, { state });
    expect(await postSignInRoute(false)).toBe(SETUP_ROUTE);
  });

  it('sends a seeded account to the dashboard', async () => {
    stubStatus(200, { state: 'ready' });
    expect(await postSignInRoute(false)).toBe('/dashboard');
  });

  it('asks same-origin, with the session cookie', async () => {
    const fetchMock = stubStatus(200, { state: 'ready' });
    await postSignInRoute(false);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('/api/auth/local-seed');
    expect(init.credentials).toBe('include');
  });

  it('keeps today\'s /onboarding route when the backend is not local (404)', async () => {
    stubStatus(404, { detail: 'Not Found' });
    expect(await postSignInRoute(false)).toBe('/onboarding');
  });

  it('falls back to /onboarding on any other failure', async () => {
    stubStatus(500);
    expect(await postSignInRoute(false)).toBe('/onboarding');
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('network'); }));
    expect(await postSignInRoute(false)).toBe('/onboarding');
  });

  it('falls back to /onboarding on an unknown state', async () => {
    stubStatus(200, { state: 'weird' });
    expect(await postSignInRoute(false)).toBe('/onboarding');
  });
});
