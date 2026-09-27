// @vitest-environment jsdom
/**
 * UserProvider ↔ product analytics: a known session user is identified by
 * UUID only, and signing out (which account deletion also goes through)
 * resets the analytics identity.
 */
import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, waitFor, fireEvent } from '@testing-library/react';

vi.mock('@/lib/api', () => ({
  API_URL: '',
  getMe: vi.fn().mockRejectedValue(new Error('not used in these tests')),
}));

const identifyUser = vi.fn();
const resetAnalytics = vi.fn();
vi.mock('@/lib/analytics', () => ({
  identifyUser: (...a: unknown[]) => identifyUser(...a),
  resetAnalytics: (...a: unknown[]) => resetAnalytics(...a),
}));

import { UserProvider, useUser } from './UserContext';

function Probe() {
  const { userId, signOut } = useUser();
  return (
    <div>
      <span data-testid="probe">{userId || 'out'}</span>
      <button onClick={() => void signOut()}>sign out</button>
    </div>
  );
}

describe('UserProvider analytics identity', () => {
  beforeEach(() => {
    localStorage.clear();
    identifyUser.mockClear();
    resetAnalytics.mockClear();
    window.history.replaceState({}, '', '/dashboard');
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes('/api/users')) return { ok: true, status: 200, json: async () => ({ users: [] }) } as Response;
        if (url.includes('/api/auth/me')) return { ok: true, status: 200, json: async () => ({ roles: [] }) } as Response;
        return { ok: true, status: 200, json: async () => ({}) } as Response;
      }),
    );
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('identifies the hydrated user with the UUID alone', async () => {
    localStorage.setItem('sapling_user', JSON.stringify({ id: 'uuid-123', name: 'Ada Lovelace', avatar: '' }));
    render(
      <UserProvider>
        <Probe />
      </UserProvider>,
    );
    await waitFor(() => expect(identifyUser).toHaveBeenCalled());
    for (const call of identifyUser.mock.calls) expect(call).toEqual(['uuid-123']);
    expect(JSON.stringify(identifyUser.mock.calls)).not.toContain('Ada');
  });

  it('does not identify an anonymous visitor', async () => {
    render(
      <UserProvider>
        <Probe />
      </UserProvider>,
    );
    await waitFor(() => expect(screen.getByTestId('probe').textContent).toBe('out'));
    expect(identifyUser).not.toHaveBeenCalled();
  });

  it('resets analytics on sign-out', async () => {
    localStorage.setItem('sapling_user', JSON.stringify({ id: 'uuid-123', name: 'Ada', avatar: '' }));
    render(
      <UserProvider>
        <Probe />
      </UserProvider>,
    );
    await waitFor(() => expect(screen.getByTestId('probe').textContent).toBe('uuid-123'));
    expect(resetAnalytics).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText('sign out'));
    await waitFor(() => expect(screen.getByTestId('probe').textContent).toBe('out'));
    expect(resetAnalytics).toHaveBeenCalledTimes(1);
  });
});
