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

vi.mock('@/lib/api', () => ({ API_URL: '' }));

import CallbackPage from './page';

function stubFetch(me: () => Partial<Response> | Promise<Partial<Response>>) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
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
