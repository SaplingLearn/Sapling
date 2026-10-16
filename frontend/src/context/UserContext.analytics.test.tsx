// @vitest-environment jsdom
/**
 * UserProvider ↔ product analytics, against the real lib/analytics.ts and
 * lib/accountSettings.ts (only the network and posthog-js are stubbed).
 *
 * For a signed-in student in the app shell, and only while pageviews may run
 * here (a configured build, the `product_analytics` flag on, no DNT/GPC), it
 * reads user_settings once per page load and the answer drives posthog-js. A
 * failed read is retried on later shell navigations, within a bounded budget.
 * A build without analytics, or a student the flag is off for, costs no
 * settings request. Signed out → stopAnalytics.
 */
import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, waitFor, fireEvent, act } from '@testing-library/react';
import type { PostHog } from 'posthog-js';

const fetchSettings = vi.fn();
vi.mock('@/lib/api', () => ({
  API_URL: '',
  getMe: vi.fn().mockRejectedValue(new Error('not used in these tests')),
  fetchSettings: (...a: unknown[]) => fetchSettings(...a),
}));

let pathname = '/dashboard';
vi.mock('next/navigation', () => ({ usePathname: () => pathname }));

import {
  __analyticsLoadedForTests,
  __resetAnalyticsForTests,
  getAnalyticsState,
  MAX_ACCOUNT_READ_FAILURES,
  setProductAnalyticsFlag,
} from '@/lib/analytics';
import { __resetAccountSettingsForTests } from '@/lib/accountSettings';
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

const load = vi.fn();
const identify = vi.fn();

/** Analytics configured (or not), posthog-js stubbed, the admin flag as given. */
function configure({ configured = true, flag = true } = {}) {
  __resetAnalyticsForTests({
    env: configured ? { NEXT_PUBLIC_POSTHOG_KEY: 'phc_test' } : {},
    load: load as unknown as () => Promise<PostHog>,
  });
  __resetAccountSettingsForTests();
  if (flag) setProductAnalyticsFlag(true);
}

describe('UserProvider analytics', () => {
  beforeEach(() => {
    localStorage.clear();
    pathname = '/dashboard';
    window.history.replaceState({}, '', '/dashboard');
    identify.mockReset();
    load.mockReset().mockImplementation(async () => {
      const ph = {
        init: (_k: string, c: { loaded?: (p: unknown) => void }) => c.loaded?.(ph),
        identify,
        get_distinct_id: () => 'anon',
        get_property: () => undefined,
        reset: vi.fn(),
      };
      return ph;
    });
    fetchSettings.mockReset().mockResolvedValue({ analytics_opt_out: false });
    configure();
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
    __resetAnalyticsForTests();
  });

  function signedIn() {
    localStorage.setItem('sapling_user', JSON.stringify({ id: 'user_1038427', name: 'Ada Lovelace', avatar: '' }));
  }
  function mount() {
    return render(
      <UserProvider>
        <Probe />
      </UserProvider>,
    );
  }
  function navigate(view: ReturnType<typeof mount>, to: string) {
    pathname = to;
    window.history.replaceState({}, '', to);
    view.rerender(
      <UserProvider>
        <Probe />
      </UserProvider>,
    );
  }
  const settle = () => act(async () => new Promise((r) => setTimeout(r, 20)));

  it('reads the preference once and starts posthog-js, identified by the account id alone', async () => {
    signedIn();
    mount();
    await waitFor(() => expect(getAnalyticsState()).toBe('on'));
    await __analyticsLoadedForTests();
    expect(fetchSettings).toHaveBeenCalledTimes(1);
    expect(fetchSettings).toHaveBeenCalledWith('user_1038427');
    expect(identify.mock.calls).toEqual([['user_1038427']]);
  });

  it('an opt-out: off, posthog-js never loaded', async () => {
    fetchSettings.mockResolvedValue({ analytics_opt_out: true });
    signedIn();
    mount();
    await waitFor(() => expect(getAnalyticsState()).toBe('off'));
    expect(load).not.toHaveBeenCalled();
  });

  it('a missing field: unset — not loaded, and not re-read on later navigations', async () => {
    fetchSettings.mockResolvedValue({ theme: 'light' });
    signedIn();
    const view = mount();
    await waitFor(() => expect(getAnalyticsState()).toBe('unset'));
    navigate(view, '/learn');
    navigate(view, '/quiz');
    await settle();
    expect(fetchSettings).toHaveBeenCalledTimes(1);
    expect(load).not.toHaveBeenCalled();
  });

  it('a failed read is retried on the next shell navigation, and stops after the budget', async () => {
    fetchSettings.mockRejectedValue(new Error('500'));
    signedIn();
    const view = mount();
    await waitFor(() => expect(getAnalyticsState()).toBe('unreadable'));
    expect(fetchSettings).toHaveBeenCalledTimes(1);
    const paths = ['/learn', '/quiz', '/study', '/tree', '/library'];
    for (const path of paths) {
      navigate(view, path);
      await settle();
    }
    // One read per navigation while failing, never more than the budget.
    expect(fetchSettings).toHaveBeenCalledTimes(MAX_ACCOUNT_READ_FAILURES);
    expect(getAnalyticsState()).toBe('unreadable');
    expect(load).not.toHaveBeenCalled();
  });

  it('a failed read that later succeeds unsticks the switch', async () => {
    fetchSettings.mockRejectedValueOnce(new Error('500'));
    signedIn();
    const view = mount();
    await waitFor(() => expect(getAnalyticsState()).toBe('unreadable'));
    navigate(view, '/learn');
    await waitFor(() => expect(getAnalyticsState()).toBe('on'));
    expect(fetchSettings).toHaveBeenCalledTimes(2);
  });

  it('makes no settings request when the build runs no analytics', async () => {
    configure({ configured: false });
    signedIn();
    mount();
    await waitFor(() => expect(screen.getByTestId('probe').textContent).toBe('user_1038427'));
    await settle();
    expect(fetchSettings).not.toHaveBeenCalled();
    expect(load).not.toHaveBeenCalled();
  });

  it('makes no settings request while the product_analytics flag is off, and reads once it turns on', async () => {
    configure({ flag: false });
    signedIn();
    mount();
    await waitFor(() => expect(screen.getByTestId('probe').textContent).toBe('user_1038427'));
    await settle();
    expect(fetchSettings).not.toHaveBeenCalled();
    act(() => setProductAnalyticsFlag(true));
    await waitFor(() => expect(getAnalyticsState()).toBe('on'));
    expect(fetchSettings).toHaveBeenCalledTimes(1);
  });

  it('makes no settings request under Do Not Track / GPC', async () => {
    Object.defineProperty(navigator, 'globalPrivacyControl', { value: true, configurable: true });
    try {
      signedIn();
      mount();
      await waitFor(() => expect(screen.getByTestId('probe').textContent).toBe('user_1038427'));
      await settle();
      expect(fetchSettings).not.toHaveBeenCalled();
    } finally {
      delete (navigator as { globalPrivacyControl?: boolean }).globalPrivacyControl;
    }
  });

  it('an anonymous visitor: nothing read, nothing started', async () => {
    mount();
    await waitFor(() => expect(screen.getByTestId('probe').textContent).toBe('out'));
    await settle();
    expect(fetchSettings).not.toHaveBeenCalled();
    expect(getAnalyticsState()).toBe('unknown');
  });

  it('sign-out stops analytics', async () => {
    signedIn();
    mount();
    await waitFor(() => expect(getAnalyticsState()).toBe('on'));
    fireEvent.click(screen.getByText('sign out'));
    await waitFor(() => expect(screen.getByTestId('probe').textContent).toBe('out'));
    expect(getAnalyticsState()).toBe('unknown');
  });

  for (const path of ['/', '/privacy', '/auth/callback', '/onboarding']) {
    it(`signed in on ${path} (outside the app shell): no settings read at all`, async () => {
      pathname = path;
      signedIn();
      mount();
      await waitFor(() => expect(screen.getByTestId('probe').textContent).toBe('user_1038427'));
      await settle();
      expect(fetchSettings).not.toHaveBeenCalled();
      expect(load).not.toHaveBeenCalled();
    });
  }

  it('shell → public → shell: one read; re-entering resumes instead of re-reading', async () => {
    signedIn();
    const view = mount();
    await waitFor(() => expect(getAnalyticsState()).toBe('on'));
    navigate(view, '/privacy');
    navigate(view, '/settings');
    await settle();
    expect(fetchSettings).toHaveBeenCalledTimes(1);
    expect(load).toHaveBeenCalledTimes(1);
  });
});
