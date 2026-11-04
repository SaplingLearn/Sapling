// @vitest-environment jsdom
/**
 * #191 (first half): the OAuth callback must not persist localStorage identity
 * unless GET /api/auth/me confirmed the live session. On a failed /me the
 * sign-in still completes for this tab (context hydrates, navigation happens)
 * but nothing is written to localStorage — the next full load reconciles via
 * the provider's cookie fallback.
 */
import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, cleanup, waitFor } from '@testing-library/react';

let search = '';
const replace = vi.fn();
vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(search),
  useRouter: () => ({ replace }),
}));

const setActiveUser = vi.fn();
const confirmApproved = vi.fn();
vi.mock('@/context/UserContext', () => ({
  useUser: () => ({ setActiveUser, confirmApproved }),
}));

vi.mock('@/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api')>()),
  API_URL: '',
}));

import CallbackPage from './page';
import { PENDING_TOKEN_KEY } from '@/lib/pendingToken';

function stubFetch(
  me: () => Partial<Response> | Promise<Partial<Response>>,
  localSeed: () => Partial<Response> = () => ({ ok: false, status: 404, text: async () => '' }),
) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.includes('/api/auth/local-seed')) {
      return localSeed() as Response;
    }
    if (url.includes('/api/auth/session') && init?.method === 'POST') {
      return { ok: true, status: 200, json: async () => ({}) } as Response;
    }
    if (url.includes('/api/auth/me')) {
      return (await me()) as Response;
    }
    return { ok: true, status: 200, json: async () => ({}) } as Response;
  });
}

describe('#191 callback persistence gate', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('persists identity when /me confirms the session', async () => {
    search = 'user_id=u1&is_approved=true';
    vi.stubGlobal(
      'fetch',
      stubFetch(() => ({
        ok: true,
        status: 200,
        json: async () => ({ onboarding_completed: true, name: 'Nina', avatar_url: 'av' }),
      })),
    );
    render(<CallbackPage />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/dashboard'));
    expect(setActiveUser).toHaveBeenCalledWith('u1', 'Nina', 'av', { persist: true });
  });

  it('hydrates without persisting when /me fails', async () => {
    search = 'user_id=u1&is_approved=true&avatar=g-av';
    vi.stubGlobal(
      'fetch',
      stubFetch(() => ({ ok: false, status: 500, json: async () => ({}) })),
    );
    render(<CallbackPage />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/dashboard'));
    expect(setActiveUser).toHaveBeenCalledWith('u1', '', 'g-av', { persist: false });
  });

  it('still fails cleanly when the session mint itself fails', async () => {
    search = 'user_id=u1&is_approved=true';
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.includes('/api/auth/session') && init?.method === 'POST') {
          return { ok: false, status: 401, json: async () => ({}) } as Response;
        }
        return { ok: true, status: 200, json: async () => ({}) } as Response;
      }),
    );
    render(<CallbackPage />);
    await waitFor(() => expect(replace).toHaveBeenCalled());
    expect(replace.mock.calls[0][0]).toContain('error=');
    expect(setActiveUser).not.toHaveBeenCalled();
  });
});

describe('#715 a new local account waits for its sample data', () => {
  const newAccount = () => ({
    ok: true,
    status: 200,
    json: async () => ({ onboarding_completed: false, name: 'Nina', avatar_url: '' }),
  });
  const seed = (status: number, body: unknown) => () => ({
    ok: status === 200,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
  });

  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    search = 'user_id=user_1&is_approved=true';
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('goes to the hold screen while the seed is pending', async () => {
    vi.stubGlobal('fetch', stubFetch(newAccount, seed(200, { state: 'pending' })));
    render(<CallbackPage />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/setting-up'));
    expect(setActiveUser).toHaveBeenCalledWith('user_1', 'Nina', '', { persist: true });
  });

  it('goes straight to the dashboard once the seed is ready', async () => {
    vi.stubGlobal('fetch', stubFetch(newAccount, seed(200, { state: 'ready' })));
    render(<CallbackPage />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/dashboard'));
  });

  it('keeps /onboarding when the backend is not local (404)', async () => {
    const fetchMock = stubFetch(newAccount, seed(404, { detail: 'Not Found' }));
    vi.stubGlobal('fetch', fetchMock);
    render(<CallbackPage />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/onboarding'));
    expect(fetchMock.mock.calls.some(([u]) => String(u).includes('/api/auth/local-seed'))).toBe(true);
  });

  it('leaves the routing to the opener in popup mode', async () => {
    search = 'user_id=user_1&is_approved=true&popup_id=p1';
    const posted: unknown[] = [];
    class FakeChannel {
      constructor(public name: string) {}
      postMessage(m: unknown) { posted.push(m); }
      close() {}
    }
    vi.stubGlobal('BroadcastChannel', FakeChannel);
    vi.spyOn(window, 'close').mockImplementation(() => {});
    const fetchMock = stubFetch(newAccount, seed(200, { state: 'pending' }));
    vi.stubGlobal('fetch', fetchMock);
    render(<CallbackPage />);
    await waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0]).toMatchObject({ success: true, onboardingCompleted: false });
    expect(replace).not.toHaveBeenCalled();
    expect(fetchMock.mock.calls.some(([u]) => String(u).includes('/api/auth/local-seed'))).toBe(false);
  });
});

describe('#741 an unapproved sign-in hands its pending token to /pending', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('popup mode relays the token to the opener instead of routing', async () => {
    search = 'error=not_approved&popup_id=p1&pending_token=pt-1';
    const posted: unknown[] = [];
    class FakeChannel {
      constructor(public name: string) {}
      postMessage(m: unknown) { posted.push(m); }
      close() {}
    }
    vi.stubGlobal('BroadcastChannel', FakeChannel);
    vi.spyOn(window, 'close').mockImplementation(() => {});
    render(<CallbackPage />);
    await waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0]).toEqual({
      type: 'sapling_signin', success: false, error: 'not_approved', pendingToken: 'pt-1',
    });
    expect(replace).not.toHaveBeenCalled();
  });

  it('same-tab stashes the token and goes to /pending', async () => {
    search = 'error=not_approved&pending_token=pt-2';
    render(<CallbackPage />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/pending'));
    expect(sessionStorage.getItem(PENDING_TOKEN_KEY)).toBe('pt-2');
    expect(setActiveUser).not.toHaveBeenCalled();
  });

  it('without a token keeps the old landing-page error', async () => {
    search = 'error=not_approved';
    render(<CallbackPage />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/?error=not_approved'));
    expect(sessionStorage.getItem(PENDING_TOKEN_KEY)).toBeNull();
  });
});
