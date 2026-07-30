// @vitest-environment jsdom
/**
 * #191 (second half): a lingering `localStorage.sapling_user` with no live
 * session must not leave the client believing it is authenticated. The
 * provider's existing profile fetch (`/api/auth/me?user_id=`) already runs on
 * every authed mount; a definitive 401/404 from it clears the stale identity.
 * Transient failures (network down, 5xx) must NOT sign the user out.
 */
import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, waitFor } from '@testing-library/react';

vi.mock('@/lib/api', () => ({
  API_URL: '',
  getMe: vi.fn().mockRejectedValue(new Error('not used in these tests')),
}));

import { UserProvider, useUser } from './UserContext';

function Probe() {
  const { userId, isAuthenticated, userReady } = useUser();
  if (!userReady) return <div data-testid="probe">loading</div>;
  return <div data-testid="probe">{isAuthenticated ? `in:${userId}` : 'out'}</div>;
}

function stubFetch(me: () => Promise<Partial<Response>> | Partial<Response>) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes('/api/users')) {
      return { ok: true, status: 200, json: async () => ({ users: [] }) } as Response;
    }
    if (url.includes('/api/auth/me')) {
      return (await me()) as Response;
    }
    return { ok: true, status: 200, json: async () => ({}) } as Response;
  });
}

const seed = () =>
  localStorage.setItem(
    'sapling_user',
    JSON.stringify({ id: 'stale-1', name: 'Stale', avatar: '' }),
  );

describe('#191 stale identity reconciliation', () => {
  beforeEach(() => {
    localStorage.clear();
    window.history.replaceState({}, '', '/');
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('clears localStorage identity on a definitive 401', async () => {
    seed();
    vi.stubGlobal(
      'fetch',
      stubFetch(() => ({ ok: false, status: 401, json: async () => ({}) })),
    );
    render(
      <UserProvider>
        <Probe />
      </UserProvider>,
    );
    await waitFor(() => expect(screen.getByTestId('probe').textContent).toBe('out'));
    expect(localStorage.getItem('sapling_user')).toBeNull();
  });

  it('clears on 404 (user row gone — the stale-session family)', async () => {
    seed();
    vi.stubGlobal(
      'fetch',
      stubFetch(() => ({ ok: false, status: 404, json: async () => ({}) })),
    );
    render(
      <UserProvider>
        <Probe />
      </UserProvider>,
    );
    await waitFor(() => expect(screen.getByTestId('probe').textContent).toBe('out'));
    expect(localStorage.getItem('sapling_user')).toBeNull();
  });

  it('keeps the session on a network failure', async () => {
    seed();
    vi.stubGlobal(
      'fetch',
      stubFetch(() => Promise.reject(new Error('offline'))),
    );
    render(
      <UserProvider>
        <Probe />
      </UserProvider>,
    );
    await waitFor(() => expect(screen.getByTestId('probe').textContent).toBe('in:stale-1'));
    // Give the profile fetch a tick to (wrongly) clear; it must not.
    await new Promise(r => setTimeout(r, 20));
    expect(screen.getByTestId('probe').textContent).toBe('in:stale-1');
    expect(localStorage.getItem('sapling_user')).not.toBeNull();
  });

  it('keeps the session on a 5xx (server blip is not a sign-out)', async () => {
    seed();
    vi.stubGlobal(
      'fetch',
      stubFetch(() => ({ ok: false, status: 503, json: async () => ({}) })),
    );
    render(
      <UserProvider>
        <Probe />
      </UserProvider>,
    );
    await waitFor(() => expect(screen.getByTestId('probe').textContent).toBe('in:stale-1'));
    await new Promise(r => setTimeout(r, 20));
    expect(screen.getByTestId('probe').textContent).toBe('in:stale-1');
    expect(localStorage.getItem('sapling_user')).not.toBeNull();
  });
});
