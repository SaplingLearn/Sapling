// @vitest-environment jsdom
/**
 * #715: the hold screen a new local account waits on while the backend copies
 * the sample dataset onto it. It polls GET /api/auth/local-seed; `ready` goes
 * to the dashboard, `failed` shows why and lets the developer continue to
 * onboarding anyway (while still polling: the backend retries on a backoff),
 * and a non-local backend (404) never holds anyone here.
 */
import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, waitFor, act } from '@testing-library/react';

const replace = vi.fn();
vi.mock('next/navigation', () => ({ useRouter: () => ({ replace }) }));

const refreshProfile = vi.fn().mockResolvedValue(undefined);
vi.mock('@/context/UserContext', () => ({ useUser: () => ({ refreshProfile }) }));

import SettingUpPage from './page';

type Answer = { status: number; body: unknown };

function stubAnswers(...answers: Answer[]) {
  const queue = [...answers];
  const fetchMock = vi.fn(async () => {
    const next = queue.length > 1 ? queue.shift()! : queue[0];
    return {
      ok: next.status === 200,
      status: next.status,
      headers: new Headers(),
      json: async () => next.body,
      text: async () => JSON.stringify(next.body),
    } as unknown as Response;
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

describe('#715 setting-up hold screen', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('says what is happening while it waits', async () => {
    stubAnswers({ status: 200, body: { state: 'seeding' } });
    render(<SettingUpPage />);
    expect(screen.getByTestId('setup-gate').textContent).toContain('Setting up your sample data');
    expect(screen.queryByTestId('setup-error')).toBeNull();
  });

  it('polls until the seed is ready, then goes to the dashboard', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const fetchMock = stubAnswers(
      { status: 200, body: { state: 'pending' } },
      { status: 200, body: { state: 'seeding' } },
      { status: 200, body: { state: 'ready' } },
    );
    render(<SettingUpPage />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(replace).not.toHaveBeenCalled();
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(replace).not.toHaveBeenCalled();
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/dashboard'));
    // The seed completed onboarding server-side; the context re-reads /me.
    expect(refreshProfile).toHaveBeenCalled();
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('/api/auth/local-seed');
    expect(init.credentials).toBe('include');
  });

  it('shows the error and a way on to onboarding when the seed failed', async () => {
    stubAnswers({ status: 200, body: { state: 'failed', error: 'RuntimeError: boom' } });
    render(<SettingUpPage />);
    await waitFor(() => expect(screen.getByTestId('setup-error').textContent).toContain('RuntimeError: boom'));
    const link = screen.getByTestId('setup-continue');
    expect(link.getAttribute('href')).toBe('/onboarding');
    expect(replace).not.toHaveBeenCalled();
  });

  it('keeps polling after a failure, since the backend retries, and moves on once ready', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const fetchMock = stubAnswers(
      { status: 200, body: { state: 'failed', error: 'RuntimeError: boom' } },
      { status: 200, body: { state: 'seeding' } },
      { status: 200, body: { state: 'ready' } },
    );
    render(<SettingUpPage />);
    await waitFor(() => expect(screen.getByTestId('setup-error')).toBeTruthy());
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    // A retry in flight does not take the way out away mid-read.
    expect(screen.getByTestId('setup-continue')).toBeTruthy();
    expect(replace).not.toHaveBeenCalled();
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/dashboard'));
    expect(refreshProfile).toHaveBeenCalled();
  });

  it('never holds anyone on a non-local backend (404)', async () => {
    stubAnswers({ status: 404, body: { detail: 'Not Found' } });
    render(<SettingUpPage />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/onboarding'));
  });

  it('sends a signed-out visitor to the landing page (401)', async () => {
    stubAnswers({ status: 401, body: { detail: 'Not authenticated' } });
    render(<SettingUpPage />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/'));
  });

  it('keeps polling through a transient failure', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const fetchMock = stubAnswers(
      { status: 502, body: {} },
      { status: 200, body: { state: 'ready' } },
    );
    render(<SettingUpPage />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/dashboard'));
  });

  it('stops polling once it unmounts', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const fetchMock = stubAnswers({ status: 200, body: { state: 'pending' } });
    const { unmount } = render(<SettingUpPage />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    unmount();
    await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
