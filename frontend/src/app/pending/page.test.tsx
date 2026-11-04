// @vitest-environment jsdom
/**
 * #290 — the approval gate needs a surface and a confirmation beat.
 *
 * The page used to float a sprout, a headline, a paragraph and a button
 * directly on a radial gradient: signing up ended in silence rather than a
 * "you're in" moment. These tests pin the three things that fix has to keep
 * true — the content sits on a real `.card` surface, the beat plays exactly
 * once, and both E2E anchors survive the redesign untouched.
 *
 * #741 — an unapproved sign-in lands here with a short-lived pending token
 * and the page tells them where they stand: on the waitlist already, or not
 * yet (with a one-click join under their sign-in email). Without a usable
 * token it can only send them back to sign in.
 */
import React from 'react';
import fs from 'node:fs';
import path from 'node:path';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';

const replace = vi.fn();
const signOut = vi.fn().mockResolvedValue(undefined);

vi.mock('next/navigation', () => ({ useRouter: () => ({ replace }) }));
vi.mock('@/context/UserContext', () => ({ useUser: () => ({ signOut }) }));

import PendingPage from './page';
import { PENDING_TOKEN_KEY } from '@/lib/pendingToken';

type Answer = { status: number; body?: unknown } | 'network';

/** Stubs fetch for the two pending endpoints; records each call's path + body. */
function stubPending(answers: { status?: Answer; join?: Answer[] }) {
  const joins = [...(answers.join ?? [])];
  const calls: { path: string; body: unknown }[] = [];
  const respond = (a: Answer | undefined) => {
    if (!a || a === 'network') throw new TypeError('Failed to fetch');
    return {
      ok: a.status >= 200 && a.status < 300,
      status: a.status,
      headers: new Headers(),
      json: async () => a.body,
      text: async () => JSON.stringify(a.body ?? { detail: 'nope' }),
    } as unknown as Response;
  };
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ path: url, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    if (url.endsWith('/api/auth/pending/status')) return respond(answers.status);
    if (url.endsWith('/api/auth/pending/join')) return respond(joins.shift());
    throw new Error(`unexpected fetch ${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);
  return calls;
}

const notOnList = { status: 200, body: { email: 'nina@bu.edu', on_waitlist: false } };
const onList = { status: 200, body: { email: 'nina@bu.edu', on_waitlist: true } };

beforeEach(() => {
  sessionStorage.clear();
  window.history.replaceState(null, '', '/pending');
});

afterEach(() => {
  cleanup();
  replace.mockClear();
  signOut.mockClear();
  vi.unstubAllGlobals();
});

describe('#290 approval gate', () => {
  it('keeps both E2E anchors', () => {
    render(<PendingPage />);
    expect(screen.getByTestId('pending-gate')).toBeTruthy();
    expect(screen.getByTestId('pending-signout')).toBeTruthy();
  });

  it('still signs out and returns to the landing page', async () => {
    sessionStorage.setItem(PENDING_TOKEN_KEY, 'tok');
    stubPending({ status: onList });
    render(<PendingPage />);
    await screen.findByTestId('pending-on-waitlist');
    fireEvent.click(screen.getByTestId('pending-signout'));
    await waitFor(() => expect(signOut).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/'));
    // The next person on this browser must not inherit the token.
    expect(sessionStorage.getItem(PENDING_TOKEN_KEY)).toBeNull();
  });

  it('puts the message on a card surface instead of floating on the gradient', () => {
    render(<PendingPage />);
    const gate = screen.getByTestId('pending-gate');
    const card = gate.querySelector('.card');
    expect(card, 'the gate content should sit inside a .card surface').toBeTruthy();
    // .card supplies bg/border/radius/shadow but no padding — that is the
    // caller's job, and an unpadded card is the bug in a different costume.
    expect(
      (card as HTMLElement).style.padding,
      'the card must set its own padding',
    ).not.toBe('');
    // The sign-out control must live INSIDE the new surface, not beside it.
    // (pending-gate is the page root, so it contains the card, not vice versa.)
    expect(card!.contains(screen.getByTestId('pending-signout'))).toBe(true);
  });

  it('plays the confirmation beat exactly once', () => {
    const css = fs.readFileSync(path.resolve(__dirname, '../globals.css'), 'utf8');
    const rules = css.match(/\.pending-[\w-]+[^{]*\{[^}]*\}/g) ?? [];
    expect(rules.length, 'the beat should be defined in globals.css').toBeGreaterThan(0);
    for (const rule of rules) {
      expect(rule, `a confirmation beat must be finite:\n${rule}`).not.toMatch(/infinite/);
    }
    // Finite also means it ENDS in the resting state: every staggered step
    // needs a fill mode, or it flashes at its pre-animation value first.
    const stepped = rules.filter((r) => /animation-delay|animation:[^;]*\dms\s+\S+\s+\d/.test(r));
    for (const rule of stepped) {
      expect(rule, `a delayed step needs a fill mode:\n${rule}`).toMatch(/both|backwards/);
    }
  });
});

describe('#741 waitlist standing from the pending token', () => {
  it('shows a brief loading state while the status is in flight', async () => {
    sessionStorage.setItem(PENDING_TOKEN_KEY, 'tok');
    stubPending({ status: onList });
    render(<PendingPage />);
    expect(screen.getByTestId('pending-loading')).toBeTruthy();
    await screen.findByTestId('pending-on-waitlist');
    expect(screen.queryByTestId('pending-loading')).toBeNull();
  });

  it('reads ?t= first, stashes it, and strips it from the address bar', async () => {
    window.history.replaceState(null, '', '/pending?t=url-tok');
    sessionStorage.setItem(PENDING_TOKEN_KEY, 'stale');
    const calls = stubPending({ status: notOnList });
    render(<PendingPage />);
    await screen.findByTestId('pending-not-on-waitlist');
    expect(sessionStorage.getItem(PENDING_TOKEN_KEY)).toBe('url-tok');
    expect(replace).toHaveBeenCalledWith('/pending');
    expect(calls[0]).toEqual({ path: '/api/auth/pending/status', body: { token: 'url-tok' } });
  });

  it('falls back to the stashed token on a reload and leaves the URL alone', async () => {
    sessionStorage.setItem(PENDING_TOKEN_KEY, 'stashed');
    const calls = stubPending({ status: notOnList });
    render(<PendingPage />);
    await screen.findByTestId('pending-not-on-waitlist');
    expect(calls[0].body).toEqual({ token: 'stashed' });
    expect(replace).not.toHaveBeenCalled();
  });

  it('offers to join under the sign-in email when not on the waitlist', async () => {
    sessionStorage.setItem(PENDING_TOKEN_KEY, 'tok');
    stubPending({ status: notOnList });
    render(<PendingPage />);
    const state = await screen.findByTestId('pending-not-on-waitlist');
    expect(screen.getByRole('heading').textContent).toBe("Your account isn't approved yet");
    expect(state.textContent).toContain('nina@bu.edu and we');
    expect(screen.getByTestId('pending-join').textContent).toBe('Join the waitlist');
    expect(screen.getByTestId('pending-signout').textContent).toBe('Use a different account');
  });

  it('says they are already on the waitlist, with no join button', async () => {
    sessionStorage.setItem(PENDING_TOKEN_KEY, 'tok');
    stubPending({ status: onList });
    render(<PendingPage />);
    const state = await screen.findByTestId('pending-on-waitlist');
    expect(screen.getByRole('heading').textContent).toBe("Your account isn't approved yet");
    expect(state.textContent).toContain("You're on the waitlist as nina@bu.edu.");
    expect(state.textContent).toContain("We'll email you when your spot opens.");
    expect(screen.queryByTestId('pending-join')).toBeNull();
    // Arrived already on the list: no "just joined" confirmation.
    expect(screen.queryByTestId('pending-joined')).toBeNull();
  });

  it('joins the waitlist and moves to the on-waitlist state with a confirmation', async () => {
    sessionStorage.setItem(PENDING_TOKEN_KEY, 'tok');
    const calls = stubPending({ status: notOnList, join: [onList] });
    render(<PendingPage />);
    fireEvent.click(await screen.findByTestId('pending-join'));
    await screen.findByTestId('pending-on-waitlist');
    expect(screen.getByTestId('pending-joined').textContent).toContain("You're on the waitlist");
    expect(screen.queryByTestId('pending-join')).toBeNull();
    expect(calls[1]).toEqual({ path: '/api/auth/pending/join', body: { token: 'tok' } });
  });

  it('shows an inline error when the join fails, and a retry can still succeed', async () => {
    sessionStorage.setItem(PENDING_TOKEN_KEY, 'tok');
    stubPending({ status: notOnList, join: [{ status: 500 }, onList] });
    render(<PendingPage />);
    fireEvent.click(await screen.findByTestId('pending-join'));
    expect((await screen.findByTestId('pending-join-error')).getAttribute('role')).toBe('alert');
    // Still on the not-on-waitlist state, button live again for the retry.
    expect(screen.getByTestId('pending-not-on-waitlist')).toBeTruthy();
    await waitFor(() =>
      expect((screen.getByTestId('pending-join') as HTMLButtonElement).disabled).toBe(false),
    );
    fireEvent.click(screen.getByTestId('pending-join'));
    await screen.findByTestId('pending-on-waitlist');
    expect(screen.queryByTestId('pending-join-error')).toBeNull();
  });

  it('drops to the sign-in-again state when the token expires mid-join', async () => {
    sessionStorage.setItem(PENDING_TOKEN_KEY, 'tok');
    stubPending({ status: notOnList, join: [{ status: 401 }] });
    render(<PendingPage />);
    fireEvent.click(await screen.findByTestId('pending-join'));
    await screen.findByTestId('pending-unknown');
    expect(sessionStorage.getItem(PENDING_TOKEN_KEY)).toBeNull();
  });

  it('with no token, points back to sign-in without calling the backend', async () => {
    const calls = stubPending({});
    render(<PendingPage />);
    const state = await screen.findByTestId('pending-unknown');
    expect(screen.getByRole('heading').textContent).toBe("Your account isn't approved yet");
    expect(state.textContent).toContain('Sign in again');
    expect(calls).toHaveLength(0);
    fireEvent.click(screen.getByTestId('pending-home'));
    expect(replace).toHaveBeenCalledWith('/');
  });

  it('treats a rejected token as unknown and forgets it', async () => {
    sessionStorage.setItem(PENDING_TOKEN_KEY, 'expired');
    stubPending({ status: { status: 401 } });
    render(<PendingPage />);
    await screen.findByTestId('pending-unknown');
    expect(sessionStorage.getItem(PENDING_TOKEN_KEY)).toBeNull();
  });

  it('treats a network failure as unknown but keeps the token for a reload', async () => {
    sessionStorage.setItem(PENDING_TOKEN_KEY, 'tok');
    stubPending({ status: 'network' });
    render(<PendingPage />);
    await screen.findByTestId('pending-unknown');
    expect(sessionStorage.getItem(PENDING_TOKEN_KEY)).toBe('tok');
  });
});
