// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, fetchJSON, onSessionExpired } from './api';
import {
  POST_SIGNIN_PATH_KEY,
  isReauthRequired,
  onReauthRequired,
  startReauth,
  takePostSignInPath,
} from './reauth';

/** Admin step-up: a 401 `reauth_required` is not a dead session. */
describe('fetchJSON — admin step-up 401', () => {
  const realFetch = globalThis.fetch;
  const expired = vi.fn();
  const reauth = vi.fn();
  let offExpired: () => void = () => {};
  let offReauth: () => void = () => {};

  const answer = (status: number, body: unknown) => {
    globalThis.fetch = vi.fn(async () =>
      new Response(JSON.stringify(body), { status }),
    ) as unknown as typeof fetch;
  };

  beforeEach(() => {
    expired.mockReset();
    reauth.mockReset();
    offExpired = onSessionExpired(expired);
    offReauth = onReauthRequired(reauth);
  });

  afterEach(() => {
    offExpired();
    offReauth();
    globalThis.fetch = realFetch;
  });

  it('notifies the reauth listeners, not the session-expired ones', async () => {
    answer(401, {
      detail: { code: 'reauth_required', message: 'For your security, sign in again to continue.' },
      request_id: 'r1',
    });
    const err = await fetchJSON('/api/admin/accounts/u/wipe', { method: 'POST' }).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(401);
    expect((err as ApiError).code).toBe('reauth_required');
    expect(reauth).toHaveBeenCalledTimes(1);
    expect(expired).not.toHaveBeenCalled();
  });

  it('a plain 401 is still a dead session', async () => {
    answer(401, { detail: 'Session revoked' });
    await fetchJSON('/api/admin/users').catch(() => {});
    expect(expired).toHaveBeenCalledTimes(1);
    expect(reauth).not.toHaveBeenCalled();
  });
});

describe('isReauthRequired', () => {
  it.each([
    [{ detail: { code: 'reauth_required' } }, true],
    [{ error: { code: 'reauth_required' } }, true],
    [{ detail: 'reauth_required' }, false],
    [{ detail: { code: 'not_approved' } }, false],
    [null, false],
    ['reauth_required', false],
  ])('%j → %s', (body, expected) => {
    expect(isReauthRequired(body)).toBe(expected);
  });
});

describe('startReauth / takePostSignInPath', () => {
  const realLocation = window.location;
  const assign = vi.fn();

  beforeEach(() => {
    window.sessionStorage.clear();
    assign.mockReset();
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: {
        origin: 'https://app.saplinglearn.com',
        pathname: '/admin',
        search: '?tab=flags',
        assign,
      },
    });
  });

  afterEach(() => {
    Object.defineProperty(window, 'location', { configurable: true, value: realLocation });
  });

  it('stashes the admin page and goes through Google sign-in on this origin', () => {
    startReauth();
    expect(window.sessionStorage.getItem(POST_SIGNIN_PATH_KEY)).toBe('/admin?tab=flags');
    // sec2 M2: through /auth/start, which sets the sign-in nonce cookie.
    expect(assign).toHaveBeenCalledWith('https://app.saplinglearn.com/auth/start');
  });

  it('returns the stashed admin path once', () => {
    window.sessionStorage.setItem(POST_SIGNIN_PATH_KEY, '/admin/analytics');
    expect(takePostSignInPath()).toBe('/admin/analytics');
    expect(takePostSignInPath()).toBeNull();
  });

  it.each(['//evil.example.org/admin', 'https://evil.example.org', '/dashboard', '/administrator', ''])(
    'refuses %j (only an in-app /admin path)',
    (path) => {
      window.sessionStorage.setItem(POST_SIGNIN_PATH_KEY, path);
      expect(takePostSignInPath()).toBeNull();
    },
  );
});
