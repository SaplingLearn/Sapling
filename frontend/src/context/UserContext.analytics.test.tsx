// @vitest-environment jsdom
/**
 * UserProvider ↔ product analytics. It is the ONE owner of the account
 * preference: for a signed-in student it holds capture, reads
 * user_settings.analytics_opt_out, and only then resolves (opt-out stored,
 * or identified by UUID alone). A failed read leaves capture held — fail
 * closed. An anonymous visitor releases capture at once. Signing out (which
 * account deletion also goes through) resets the analytics identity. A build
 * without analytics makes no settings request and calls nothing.
 */
import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, waitFor, fireEvent } from '@testing-library/react';

const fetchSettings = vi.fn();
vi.mock('@/lib/api', () => ({
  API_URL: '',
  getMe: vi.fn().mockRejectedValue(new Error('not used in these tests')),
  fetchSettings: (...a: unknown[]) => fetchSettings(...a),
}));

const holdAnalytics = vi.fn();
const releaseAnonymousAnalytics = vi.fn();
const resolveAccountAnalytics = vi.fn();
const resetAnalytics = vi.fn();
const isAnalyticsConfigured = vi.fn(() => true);
vi.mock('@/lib/analytics', () => ({
  holdAnalytics: () => holdAnalytics(),
  releaseAnonymousAnalytics: () => releaseAnonymousAnalytics(),
  resolveAccountAnalytics: (...a: unknown[]) => resolveAccountAnalytics(...a),
  resetAnalytics: (...a: unknown[]) => resetAnalytics(...a),
  isAnalyticsConfigured: () => isAnalyticsConfigured(),
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
    for (const m of [holdAnalytics, releaseAnonymousAnalytics, resolveAccountAnalytics, resetAnalytics]) m.mockClear();
    isAnalyticsConfigured.mockReset().mockReturnValue(true);
    fetchSettings.mockReset().mockResolvedValue({ analytics_opt_out: false });
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

  function signedIn() {
    localStorage.setItem('sapling_user', JSON.stringify({ id: 'uuid-123', name: 'Ada Lovelace', avatar: '' }));
  }
  function mount() {
    return render(
      <UserProvider>
        <Probe />
      </UserProvider>,
    );
  }

  it('holds capture, reads the preference, then resolves with the UUID alone', async () => {
    signedIn();
    mount();
    await waitFor(() => expect(resolveAccountAnalytics).toHaveBeenCalled());
    expect(holdAnalytics).toHaveBeenCalled();
    expect(fetchSettings).toHaveBeenCalledWith('uuid-123');
    expect(holdAnalytics.mock.invocationCallOrder[0]).toBeLessThan(fetchSettings.mock.invocationCallOrder[0]);
    for (const call of resolveAccountAnalytics.mock.calls) expect(call).toEqual(['uuid-123', false]);
    expect(JSON.stringify(resolveAccountAnalytics.mock.calls)).not.toContain('Ada');
    expect(releaseAnonymousAnalytics).not.toHaveBeenCalled();
  });

  it("passes an account opt-out through", async () => {
    fetchSettings.mockResolvedValue({ analytics_opt_out: true });
    signedIn();
    mount();
    await waitFor(() => expect(resolveAccountAnalytics).toHaveBeenCalledWith('uuid-123', true));
  });

  it('tolerates a backend without the field (pre-#677)', async () => {
    fetchSettings.mockResolvedValue({ theme: 'light' });
    signedIn();
    mount();
    await waitFor(() => expect(resolveAccountAnalytics).toHaveBeenCalledWith('uuid-123', undefined));
  });

  it('fails closed: a failed settings read never resolves, so capture stays held', async () => {
    fetchSettings.mockRejectedValue(new Error('500'));
    signedIn();
    mount();
    await waitFor(() => expect(fetchSettings).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 20));
    expect(holdAnalytics).toHaveBeenCalled();
    expect(resolveAccountAnalytics).not.toHaveBeenCalled();
    expect(releaseAnonymousAnalytics).not.toHaveBeenCalled();
  });

  it('makes no settings request, and calls nothing, when the build runs no analytics', async () => {
    isAnalyticsConfigured.mockReturnValue(false);
    signedIn();
    mount();
    await waitFor(() => expect(screen.getByTestId('probe').textContent).toBe('uuid-123'));
    await new Promise((r) => setTimeout(r, 20));
    expect(fetchSettings).not.toHaveBeenCalled();
    expect(holdAnalytics).not.toHaveBeenCalled();
    expect(resolveAccountAnalytics).not.toHaveBeenCalled();
    expect(releaseAnonymousAnalytics).not.toHaveBeenCalled();
  });

  it('releases capture for an anonymous visitor, without a settings read', async () => {
    mount();
    await waitFor(() => expect(releaseAnonymousAnalytics).toHaveBeenCalled());
    expect(screen.getByTestId('probe').textContent).toBe('out');
    expect(fetchSettings).not.toHaveBeenCalled();
    expect(holdAnalytics).not.toHaveBeenCalled();
    expect(resolveAccountAnalytics).not.toHaveBeenCalled();
  });

  it('resets analytics on sign-out, then treats the visitor as anonymous', async () => {
    signedIn();
    mount();
    await waitFor(() => expect(resolveAccountAnalytics).toHaveBeenCalled());
    expect(resetAnalytics).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText('sign out'));
    await waitFor(() => expect(screen.getByTestId('probe').textContent).toBe('out'));
    expect(resetAnalytics).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(releaseAnonymousAnalytics).toHaveBeenCalled());
  });
});
