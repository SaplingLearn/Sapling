// @vitest-environment jsdom
/**
 * The onboarding state the app shell gates on (sign in first, onboarding
 * enforced: 2026-11-12): `onboardingCompleted` comes from GET /api/auth/me,
 * is unknown (null) until it answers and after an account change, and
 * `markOnboarded` sets it when onboarding finishes. Also: the guest draft the
 * removed signed-out onboarding left behind is purged on every load.
 */
import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, waitFor, fireEvent } from '@testing-library/react';

const getMe = vi.hoisted(() => vi.fn());
vi.mock('@/lib/api', () => ({
  API_URL: '',
  getMe: () => getMe(),
  onSessionExpired: () => () => {},
}));

import { UserProvider, useUser } from './UserContext';
import { GUEST_DRAFT_KEY, onboardingDraftKey } from '@/lib/onboardingDraft';

function Probe() {
  const { onboardingCompleted, markOnboarded, setActiveUser, userReady } = useUser();
  return (
    <>
      <div data-testid="onboarded">{userReady ? String(onboardingCompleted) : 'loading'}</div>
      <button onClick={markOnboarded}>mark</button>
      <button onClick={() => setActiveUser('u-2', 'Two', '', { persist: false })}>switch</button>
    </>
  );
}

function stubMe(answer: (url: string) => Promise<unknown> | unknown) {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes('/api/auth/me')) {
      const body = await answer(url);
      return { ok: true, status: 200, json: async () => body } as unknown as Response;
    }
    return { ok: true, status: 200, json: async () => ({}) } as Response;
  }));
}

const mount = () => render(<UserProvider><Probe /></UserProvider>);
const value = () => screen.getByTestId('onboarded').textContent;

describe('UserContext onboarding state', () => {
  beforeEach(() => {
    localStorage.clear();
    getMe.mockReset();
    window.history.replaceState({}, '', '/');
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("reads /me's onboarding_completed for the signed-in account", async () => {
    localStorage.setItem('sapling_user', JSON.stringify({ id: 'u-1', name: 'One', avatar: '' }));
    stubMe(() => ({ user_id: 'u-1', name: 'One', onboarding_completed: false }));
    mount();
    await waitFor(() => expect(value()).toBe('false'));
  });

  it('is unknown until /me answers, and markOnboarded sets it', async () => {
    localStorage.setItem('sapling_user', JSON.stringify({ id: 'u-1', name: 'One', avatar: '' }));
    stubMe(() => new Promise(() => {}));
    mount();
    await waitFor(() => expect(value()).toBe('null'));
    fireEvent.click(screen.getByText('mark'));
    expect(value()).toBe('true');
  });

  it("forgets one account's answer when another signs in", async () => {
    localStorage.setItem('sapling_user', JSON.stringify({ id: 'u-1', name: 'One', avatar: '' }));
    stubMe((url) => (url.includes('u-1') ? { user_id: 'u-1', onboarding_completed: true } : new Promise(() => {})));
    mount();
    await waitFor(() => expect(value()).toBe('true'));
    fireEvent.click(screen.getByText('switch'));
    await waitFor(() => expect(value()).toBe('null'));
  });

  it('takes the answer from the cookie fallback too (#430)', async () => {
    getMe.mockResolvedValueOnce({ user_id: 'u-3', name: 'Three', avatar_url: '', onboarding_completed: true });
    stubMe(() => new Promise(() => {}));
    mount();
    await waitFor(() => expect(value()).toBe('true'));
  });

  it("purges a signed-out visitor's guest onboarding draft on load, and only that", async () => {
    localStorage.setItem(GUEST_DRAFT_KEY, JSON.stringify({ name: 'Guest', screen: 4 }));
    localStorage.setItem(onboardingDraftKey('u-1'), JSON.stringify({ name: 'One', savedAt: Date.now() }));
    localStorage.setItem('sapling_user', JSON.stringify({ id: 'u-1', name: 'One', avatar: '' }));
    stubMe(() => new Promise(() => {}));
    mount();
    await waitFor(() => expect(localStorage.getItem(GUEST_DRAFT_KEY)).toBeNull());
    expect(localStorage.getItem(onboardingDraftKey('u-1'))).not.toBeNull();
  });

  it('purges it for a signed-out visitor as well', async () => {
    localStorage.setItem(GUEST_DRAFT_KEY, JSON.stringify({ name: 'Guest' }));
    getMe.mockRejectedValueOnce(new Error('401'));
    mount();
    await waitFor(() => expect(value()).toBe('null'));
    expect(localStorage.getItem(GUEST_DRAFT_KEY)).toBeNull();
  });
});
