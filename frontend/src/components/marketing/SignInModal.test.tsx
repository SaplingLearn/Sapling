// @vitest-environment jsdom
/**
 * #715: the popup sign-in routes a new account the same way the same-tab
 * callback does. On a local backend (GET /api/auth/local-seed answers) a new
 * account waits on the hold screen while its sample data is copied in;
 * anywhere else (404) it goes to /onboarding exactly as before.
 */
import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor, act } from '@testing-library/react';

const replace = vi.fn();
const push = vi.fn();
vi.mock('next/navigation', () => ({ useRouter: () => ({ replace, push }) }));

const setActiveUser = vi.fn();
vi.mock('@/context/UserContext', () => ({
  useUser: () => ({ setActiveUser }),
}));

import SignInModal from './SignInModal';
import { PENDING_TOKEN_KEY } from '@/lib/pendingToken';

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

  it('starts sign-in with this origin as return_to so a PR preview gets the user back', () => {
    render(<SignInModal open onClose={vi.fn()} />);
    fireEvent.click(screen.getByTestId('signin-google-button'));
    const url = new URL(vi.mocked(window.open).mock.calls[0][0] as string, window.location.href);
    expect(url.pathname).toBe('/api/auth/google');
    expect(url.searchParams.get('return_to')).toBe(window.location.origin);
    expect(url.searchParams.get('popup_id')).toBe(channels[0].name.replace('sapling_signin:', ''));
  });

  it('does not ask when the account is already onboarded', async () => {
    const fetchMock = stubLocalSeed(200, { state: 'pending' });
    await signInThroughPopup(true);
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/dashboard'));
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe('#741 an unapproved popup sign-in goes to /pending', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    channels.length = 0;
    sessionStorage.clear();
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

  function deliver(data: Record<string, unknown>) {
    const onClose = vi.fn();
    render(<SignInModal open onClose={onClose} />);
    fireEvent.click(screen.getByTestId('signin-google-button'));
    channels[0].onmessage?.({ data: { type: 'sapling_signin', ...data } } as MessageEvent);
    return onClose;
  }

  it('stashes the relayed token, closes the modal and routes to /pending', () => {
    const onClose = deliver({ success: false, error: 'not_approved', pendingToken: 'pt-1' });
    expect(sessionStorage.getItem(PENDING_TOKEN_KEY)).toBe('pt-1');
    expect(onClose).toHaveBeenCalled();
    expect(push).toHaveBeenCalledWith('/pending');
    expect(screen.queryByTestId('signin-error')).toBeNull();
  });

  it('without a token keeps the pending-approval error in the modal', async () => {
    const onClose = deliver({ success: false, error: 'not_approved' });
    expect((await screen.findByTestId('signin-error')).textContent).toContain('pending approval');
    expect(onClose).not.toHaveBeenCalled();
    expect(push).not.toHaveBeenCalled();
    expect(sessionStorage.getItem(PENDING_TOKEN_KEY)).toBeNull();
  });
});

describe('#756 sign-in error copy', () => {
  beforeEach(() => {
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

  it('explains a deleted account instead of the generic error', () => {
    render(<SignInModal open onClose={() => {}} errorCode="account_deleted" />);
    const error = screen.getByTestId('signin-error').textContent ?? '';
    expect(error).toContain('This account was deleted.');
    expect(error).toContain('contact support');
  });

  it('shows a popup sign-in refused as account_deleted', () => {
    render(<SignInModal open onClose={() => {}} />);
    fireEvent.click(screen.getByTestId('signin-google-button'));
    act(() => {
      channels[0].onmessage?.({
        data: { type: 'sapling_signin', success: false, error: 'account_deleted' },
      } as MessageEvent);
    });
    expect(screen.getByTestId('signin-error').textContent).toContain('This account was deleted.');
  });

  it("hides the landing's error once the student tries again", () => {
    render(<SignInModal open onClose={() => {}} errorCode="session_expired" />);
    expect(screen.queryByTestId('signin-error')).not.toBeNull();
    fireEvent.click(screen.getByTestId('signin-google-button'));
    expect(screen.queryByTestId('signin-error')).toBeNull();
  });
});

describe('Get started and Welcome back', () => {
  afterEach(cleanup);

  it('says "Welcome back." for Sign In', () => {
    render(<SignInModal open onClose={() => {}} />);
    expect(screen.getByTestId('signin-title').textContent).toBe('Welcome back.');
    expect(screen.getByRole('dialog').getAttribute('aria-labelledby')).toBe('signin-modal-title');
  });

  it('says "Get started." for Get Started', () => {
    render(<SignInModal open onClose={() => {}} variant="start" />);
    expect(screen.getByTestId('signin-title').textContent).toBe('Get started.');
    expect(screen.getByTestId('signin-modal').textContent).not.toContain('Welcome back');
  });
});

describe('a cancelled Google sign-in', () => {
  beforeEach(() => {
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

  it('says so after a same-tab sign-in (the landing passes ?error=cancelled)', () => {
    render(<SignInModal open onClose={() => {}} errorCode="cancelled" />);
    expect(screen.getByTestId('signin-error').textContent).toBe('Sign-in was cancelled.');
  });

  it('says so after a popup sign-in', () => {
    render(<SignInModal open onClose={() => {}} />);
    fireEvent.click(screen.getByTestId('signin-google-button'));
    act(() => {
      channels[0].onmessage?.({
        data: { type: 'sapling_signin', success: false, error: 'cancelled' },
      } as MessageEvent);
    });
    expect(screen.getByTestId('signin-error').textContent).toBe('Sign-in was cancelled.');
    // The button is back, ready to try again.
    expect((screen.getByTestId('signin-google-button') as HTMLButtonElement).disabled).toBe(false);
  });
});

describe('Esc in the sign-in box', () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it('closes the box and nothing else: a page listening for Esc never sees it', () => {
    vi.useFakeTimers();
    // A page's own Esc-for-back, registered before the box opened (as
    // onboarding's was): it must not also act on the press.
    const pageEsc = vi.fn();
    const onPageKey = (e: KeyboardEvent) => { if (e.key === 'Escape' && !e.defaultPrevented) pageEsc(); };
    window.addEventListener('keydown', onPageKey);
    try {
      const onClose = vi.fn();
      render(<SignInModal open onClose={onClose} />);
      fireEvent.keyDown(screen.getByTestId('signin-google-button'), { key: 'Escape' });
      act(() => { vi.advanceTimersByTime(250); });
      expect(onClose).toHaveBeenCalled();
      expect(pageEsc).not.toHaveBeenCalled();
    } finally {
      window.removeEventListener('keydown', onPageKey);
    }
  });
});
