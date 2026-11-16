// @vitest-environment jsdom
/**
 * A corrupt `sapling_user` must not strand a signed-in student.
 *
 * The bootstrap effect used to parse the stored copy inside a bare
 * `try/catch {}` and then unconditionally `setUserReady(true); return;` — so
 * a value it could not read STILL took the fast path and returned, skipping
 * the cookie-identified getMe() fallback that exists for exactly this case.
 *
 * Both failure modes are sticky: the bad value stays in localStorage, so
 * every reload repeats the same thing until the student clears site data.
 */
import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, waitFor } from '@testing-library/react';

const getMe = vi.hoisted(() => vi.fn());
vi.mock('@/lib/api', () => ({
  API_URL: '',
  getMe,
  onSessionExpired: () => () => {},
}));

import { UserProvider, useUser } from './UserContext';

function Probe() {
  const { userId, isAuthenticated, userReady } = useUser();
  if (!userReady) return <div data-testid="probe">loading</div>;
  return <div data-testid="probe">{isAuthenticated ? `in:${userId}` : 'out'}</div>;
}

const CORRUPT = [
  ['malformed JSON', '{not json'],
  ['the literal null', 'null'],
  ['a bare number', '5'],
  ['a bare string', '"nobody"'],
  ['an array', '[]'],
  ['an object with no id', '{"name":"Sam"}'],
  ['an object whose id is not a string', '{"id":42}'],
  ['an object with an empty id', '{"id":""}'],
] as const;

describe('a corrupt sapling_user falls back to the session cookie', () => {
  beforeEach(() => {
    localStorage.clear();
    getMe.mockReset();
    window.history.replaceState({}, '', '/dashboard');
  });
  afterEach(() => cleanup());

  it.each(CORRUPT)('recovers the real identity when stored value is %s', async (_label, raw) => {
    localStorage.setItem('sapling_user', raw);
    getMe.mockResolvedValue({ user_id: 'u-real', name: 'Real Student', avatar_url: '' });

    render(<UserProvider><Probe /></UserProvider>);

    // The whole point: the cookie fallback must RUN, not be skipped.
    await waitFor(() => expect(screen.getByTestId('probe').textContent).toBe('in:u-real'));
    expect(getMe).toHaveBeenCalled();
  });

  it.each(CORRUPT)('drops the unusable copy so it is not sticky (%s)', async (_label, raw) => {
    localStorage.setItem('sapling_user', raw);
    getMe.mockRejectedValue(new Error('401'));

    render(<UserProvider><Probe /></UserProvider>);
    await waitFor(() => expect(screen.getByTestId('probe').textContent).toBe('out'));

    // Left in place, the same bad bytes would break the next boot too.
    expect(localStorage.getItem('sapling_user')).not.toBe(raw);
  });

  it('never reports authenticated with no user id', async () => {
    // `5` destructures without throwing, so the old code set
    // isAuthenticated(true) with id undefined: authenticated as nobody.
    localStorage.setItem('sapling_user', '5');
    getMe.mockRejectedValue(new Error('401'));

    render(<UserProvider><Probe /></UserProvider>);
    await waitFor(() => expect(screen.getByTestId('probe').textContent).toBe('out'));
    expect(screen.getByTestId('probe').textContent).not.toContain('in:undefined');
  });

  it('still takes the fast path for a good stored identity', async () => {
    localStorage.setItem('sapling_user', JSON.stringify({ id: 'u1', name: 'Sam', avatar: '' }));

    render(<UserProvider><Probe /></UserProvider>);

    await waitFor(() => expect(screen.getByTestId('probe').textContent).toBe('in:u1'));
    // The fast path is the point of storing it — no network round trip.
    expect(getMe).not.toHaveBeenCalled();
    expect(localStorage.getItem('sapling_user')).toContain('u1');
  });
});
