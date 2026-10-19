// @vitest-environment jsdom
/**
 * #715: the popup sign-in routes a new account the same way the same-tab
 * callback does. On a local backend (GET /api/auth/local-seed answers) a new
 * account waits on the hold screen while its sample data is copied in;
 * anywhere else (404) it goes to /onboarding exactly as before.
 */
import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';

const replace = vi.fn();
vi.mock('next/navigation', () => ({ useRouter: () => ({ replace }) }));

const setActiveUser = vi.fn();
const confirmApproved = vi.fn();
vi.mock('@/context/UserContext', () => ({
  useUser: () => ({ setActiveUser, confirmApproved }),
}));

import SignInModal from './SignInModal';

const channels: FakeChannel[] = [];
class FakeChannel {
  onmessage: ((e: MessageEvent) => void) | null = null;
  closed = false;
  constructor(public name: string) { channels.push(this); }
  postMessage() {}
  close() { this.closed = true; }
}

function stubLocalSeed(status: number, body: unknown) {
  const fetchMock = vi.fn(async () => ({
    ok: status === 200,
    status,
    headers: new Headers(),
    json: async () => body,
    text: async () => JSON.stringify(body),
  }) as unknown as Response);
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

async function signInThroughPopup(onboardingCompleted: boolean) {
  const onClose = vi.fn();
  render(<SignInModal open onClose={onClose} />);
  fireEvent.click(screen.getByTestId('signin-google-button'));
  expect(channels).toHaveLength(1);
  channels[0].onmessage?.({
    data: {
      type: 'sapling_signin', success: true, userId: 'user_1', name: 'Nina',
      avatar: '', onboardingCompleted, profileConfirmed: true,
    },
  } as MessageEvent);
  return onClose;
}

describe('#715 popup sign-in routing', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    channels.length = 0;
    vi.stubGlobal('BroadcastChannel', FakeChannel);
    vi.spyOn(window, 'open').mockImplementation(
      () => ({ closed: false, focus() {}, close() {} }) as unknown as Window,
    );
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('holds a new local account on the setup screen while it is seeded', async () => {
    stubLocalSeed(200, { state: 'seeding' });
    const onClose = await signInThroughPopup(false);
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/setting-up'));
    expect(setActiveUser).toHaveBeenCalledWith('user_1', 'Nina', '', { persist: true });
    expect(onClose).toHaveBeenCalled();
  });

  it('sends a new local account whose seed is ready to the dashboard', async () => {
    stubLocalSeed(200, { state: 'ready' });
    await signInThroughPopup(false);
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/dashboard'));
  });

  it('keeps /onboarding when the backend is not local (404)', async () => {
    stubLocalSeed(404, { detail: 'Not Found' });
    await signInThroughPopup(false);
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/onboarding'));
    expect(replace).toHaveBeenCalledTimes(1);
  });

  it('does not ask when the account is already onboarded', async () => {
    const fetchMock = stubLocalSeed(200, { state: 'pending' });
    await signInThroughPopup(true);
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/dashboard'));
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
