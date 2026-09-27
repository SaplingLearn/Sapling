// @vitest-environment jsdom
/**
 * UserProvider ↔ product analytics. For a signed-in student it starts an
 * account read (beginAccountRead), fetches user_settings and hands the
 * answer back with that read's generation (applyAccountAnalytics). A failed
 * read hands nothing back — fail closed. Signed out → stopAnalytics. A build
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

let pathname = '/dashboard';
vi.mock('next/navigation', () => ({ usePathname: () => pathname }));

const beginAccountRead = vi.fn<(userId: string) => number>(() => 7);
const needsAccountRead = vi.fn<(userId: string) => boolean>(() => true);
const resumeAnalytics = vi.fn();
const applyAccountAnalytics = vi.fn();
const stopAnalytics = vi.fn();
const isAnalyticsConfigured = vi.fn(() => true);
vi.mock('@/lib/analytics', () => ({
  beginAccountRead: (userId: string) => beginAccountRead(userId),
  applyAccountAnalytics: (...a: unknown[]) => applyAccountAnalytics(...a),
  stopAnalytics: () => stopAnalytics(),
  needsAccountRead: (userId: string) => needsAccountRead(userId),
  resumeAnalytics: () => resumeAnalytics(),
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

describe('UserProvider analytics', () => {
  beforeEach(() => {
    localStorage.clear();
    for (const m of [beginAccountRead, applyAccountAnalytics, stopAnalytics, resumeAnalytics]) m.mockClear();
    needsAccountRead.mockReset().mockReturnValue(true);
    pathname = '/dashboard';
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

  it('starts a read, fetches the preference, and applies it with that read\'s generation', async () => {
    signedIn();
    mount();
    await waitFor(() => expect(applyAccountAnalytics).toHaveBeenCalled());
    expect(beginAccountRead).toHaveBeenCalledWith('uuid-123');
    expect(fetchSettings).toHaveBeenCalledWith('uuid-123');
    expect(beginAccountRead.mock.invocationCallOrder[0]).toBeLessThan(fetchSettings.mock.invocationCallOrder[0]);
    expect(applyAccountAnalytics).toHaveBeenLastCalledWith(7, 'uuid-123', false);
    expect(JSON.stringify(applyAccountAnalytics.mock.calls)).not.toContain('Ada');
  });

  it('passes an opt-out, or a missing field, through as-is', async () => {
    fetchSettings.mockResolvedValue({ analytics_opt_out: true });
    signedIn();
    const first = mount();
    await waitFor(() => expect(applyAccountAnalytics).toHaveBeenLastCalledWith(7, 'uuid-123', true));
    first.unmount();
    fetchSettings.mockResolvedValue({ theme: 'light' });
    mount();
    await waitFor(() => expect(applyAccountAnalytics).toHaveBeenLastCalledWith(7, 'uuid-123', undefined));
  });

  it('fails closed: a failed settings read applies nothing', async () => {
    fetchSettings.mockRejectedValue(new Error('500'));
    signedIn();
    mount();
    await waitFor(() => expect(fetchSettings).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 20));
    expect(beginAccountRead).toHaveBeenCalled();
    expect(applyAccountAnalytics).not.toHaveBeenCalled();
  });

  it('makes no settings request, and calls nothing, when the build runs no analytics', async () => {
    isAnalyticsConfigured.mockReturnValue(false);
    signedIn();
    mount();
    await waitFor(() => expect(screen.getByTestId('probe').textContent).toBe('uuid-123'));
    await new Promise((r) => setTimeout(r, 20));
    expect(fetchSettings).not.toHaveBeenCalled();
    expect(beginAccountRead).not.toHaveBeenCalled();
    expect(applyAccountAnalytics).not.toHaveBeenCalled();
  });

  it('an anonymous visitor: stopAnalytics, no settings read', async () => {
    mount();
    await waitFor(() => expect(stopAnalytics).toHaveBeenCalled());
    expect(screen.getByTestId('probe').textContent).toBe('out');
    expect(fetchSettings).not.toHaveBeenCalled();
    expect(beginAccountRead).not.toHaveBeenCalled();
  });

  it('sign-out stops analytics', async () => {
    signedIn();
    mount();
    await waitFor(() => expect(applyAccountAnalytics).toHaveBeenCalled());
    expect(stopAnalytics).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText('sign out'));
    await waitFor(() => expect(screen.getByTestId('probe').textContent).toBe('out'));
    expect(stopAnalytics).toHaveBeenCalled();
  });

  for (const path of ['/', '/privacy', '/auth/callback', '/onboarding']) {
    it(`signed in on ${path} (outside the app shell): no settings read at all`, async () => {
      pathname = path;
      signedIn();
      mount();
      await waitFor(() => expect(screen.getByTestId('probe').textContent).toBe('uuid-123'));
      await new Promise((r) => setTimeout(r, 20));
      expect(fetchSettings).not.toHaveBeenCalled();
      expect(beginAccountRead).not.toHaveBeenCalled();
      expect(stopAnalytics).not.toHaveBeenCalled();
    });
  }

  it('shell → public → shell: one read; re-entering resumes instead of re-reading', async () => {
    signedIn();
    const view = mount();
    await waitFor(() => expect(applyAccountAnalytics).toHaveBeenCalledTimes(1));
    needsAccountRead.mockReturnValue(false); // the answer is known now
    pathname = '/privacy';
    view.rerender(
      <UserProvider>
        <Probe />
      </UserProvider>,
    );
    pathname = '/settings';
    view.rerender(
      <UserProvider>
        <Probe />
      </UserProvider>,
    );
    await waitFor(() => expect(resumeAnalytics).toHaveBeenCalled());
    expect(fetchSettings).toHaveBeenCalledTimes(1);
  });
});
