'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useUser } from '@/context/UserContext';
import { getPendingStatus, joinWaitlistFromPending } from '@/lib/api';
import { signInStartPath } from '@/lib/signinStart';
import { statusOf } from '@/lib/errorMessage';
import { clearPendingToken, readPendingToken, stashPendingToken } from '@/lib/pendingToken';

/**
 * The approval gate — where a Google sign-in lands when the account isn't
 * approved yet.
 *
 * The backend can't hand us a session for an unapproved account, so it hands
 * a short-lived pending token instead (`lib/pendingToken.ts`): on the URL as
 * `?t=` for a same-tab sign-in, stashed by the callback/SignInModal for a
 * popup one. With it the page asks whether the sign-in email is already on
 * the waitlist and, if not, offers to put it there — no retyping. Without one
 * (expired, a direct visit, the middleware bouncing a revoked session here)
 * it can only point back to sign-in.
 *
 * #757: once an admin approves the address, the status says so and the page
 * offers a fresh sign-in (the pending token is never a session).
 *
 * The heading changes only for that approved state, so the card doesn't jump
 * while the status loads; otherwise only the body below it changes.
 *
 * The sapling draws itself once and the message steps in behind it
 * (`.pending-*` in globals.css), settling in ~560ms. One-shot CSS animation on
 * purpose — the global prefers-reduced-motion reset collapses CSS animation
 * automatically, where a JS-driven entrance would have to re-implement that
 * guard itself.
 */
type View =
  | { kind: 'loading' }
  | { kind: 'unknown' }
  | { kind: 'status'; email: string; onWaitlist: boolean; justJoined: boolean }
  // #757: approved since this sign-in — only a fresh sign-in can let them in.
  | { kind: 'approved'; email: string };

export default function PendingPage() {
  const router = useRouter();
  const { signOut } = useUser();
  const [view, setView] = useState<View>({ kind: 'loading' });
  const [token, setToken] = useState<string | null>(null);
  const [joining, setJoining] = useState(false);
  const [joinFailed, setJoinFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;

    // A same-tab sign-in arrives as /pending?t=<token>. Stash it, then strip
    // it from the address bar so it doesn't linger in history; a reload reads
    // the stash instead.
    const fromUrl = new URLSearchParams(window.location.search).get('t');
    if (fromUrl) {
      stashPendingToken(fromUrl);
      router.replace('/pending');
    }
    const t = fromUrl || readPendingToken();
    setToken(t);
    if (!t) {
      setView({ kind: 'unknown' });
      return;
    }

    getPendingStatus(t)
      .then((s) => {
        if (cancelled) return;
        if (s.approved) {
          setView({ kind: 'approved', email: s.email });
          return;
        }
        setView({ kind: 'status', email: s.email, onWaitlist: s.on_waitlist, justJoined: false });
      })
      .catch((err) => {
        if (cancelled) return;
        // An expired or invalid token won't get better on a reload.
        if (statusOf(err) === 401) clearPendingToken();
        setView({ kind: 'unknown' });
      });

    return () => {
      cancelled = true;
    };
  // Runs once on arrival: `router` is stable, and re-reading the URL after
  // our own replace would only find it already stripped.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleJoin() {
    if (!token || joining) return;
    setJoining(true);
    setJoinFailed(false);
    try {
      const s = await joinWaitlistFromPending(token);
      setView(s.approved
        ? { kind: 'approved', email: s.email }
        : { kind: 'status', email: s.email, onWaitlist: s.on_waitlist, justJoined: true });
    } catch (err) {
      if (statusOf(err) === 401) {
        // The token expired while they read the page: only a fresh sign-in
        // can mint another.
        clearPendingToken();
        setView({ kind: 'unknown' });
      } else {
        setJoinFailed(true);
      }
    } finally {
      setJoining(false);
    }
  }

  function handleSignInAgain() {
    // Same-tab Google sign-in, as SignInModal's fallback does; the token
    // has done its job.
    clearPendingToken();
    window.location.assign(signInStartPath());
  }

  async function handleSignOut() {
    clearPendingToken();
    await signOut();
    router.replace('/');
  }

  return (
    <div
      data-testid="pending-gate"
      className="min-h-screen flex flex-col items-center justify-center [background:radial-gradient(ellipse_at_top,_var(--accent-soft)_0%,_var(--bg)_60%)] text-text p-6"
    >
      <div
        className="card pending-card p-(--pad-lg) max-w-110 w-full flex flex-col items-center text-center"
      >
        <svg
          width="56"
          height="56"
          viewBox="0 0 24 24"
          aria-hidden="true"
          className="mb-5"
        >
          <path
            className="pending-sprout-body"
            d="M12 22 Q 5 15 5 9 Q 5 3 12 3 Q 19 3 19 9 Q 19 15 12 22 Z"
            fill="var(--accent)"
            opacity={0.2}
          />
          {/* pathLength normalises each stroke to one unit, so the draw
              keyframe can dash it without measuring. Stem and veins are two
              PATHS rather than subpaths of one: a dash pattern restarts its
              phase at every `M`, so subpaths of a single path would all draw
              simultaneously. Split and staggered, the stem leads and the
              leaves follow — the sapling growing rather than a fade. */}
          <path
            className="pending-sprout-stem"
            pathLength={1}
            d="M12 22 V 10"
            stroke="var(--accent)"
            strokeWidth={1.5}
            fill="none"
            strokeLinecap="round"
          />
          <path
            className="pending-sprout-veins"
            pathLength={1}
            d="M12 13 Q 8 10 7 7 M12 14 Q 16 11 17 8"
            stroke="var(--accent)"
            strokeWidth={1.5}
            fill="none"
            strokeLinecap="round"
          />
        </svg>

        <h1
          className="h-serif pending-step anim-d1 text-4xl font-medium mb-2.5"
        >
          {view.kind === 'approved' ? "You're approved" : "Your account isn't approved yet"}
        </h1>

        <div
          className="pending-step anim-d2 flex flex-col items-center gap-4 w-full min-h-18 mb-6"
          aria-live="polite"
          aria-busy={view.kind === 'loading'}
        >
          {view.kind === 'loading' && (
            <p data-testid="pending-loading" className="text-[15px] text-text-dim leading-[1.6] m-0 max-w-85">
              Checking your account…
            </p>
          )}

          {view.kind === 'unknown' && (
            <div data-testid="pending-unknown" className="flex flex-col items-center gap-4 w-full">
              <p className="text-[15px] text-text-dim leading-[1.6] m-0 max-w-85">
                Sapling is letting students in a few at a time. Sign in again to see
                where you stand, or join the waitlist from the home page.
              </p>
              <button
                data-testid="pending-home"
                className="btn btn--primary"
                onClick={() => router.replace('/')}
              >
                Back to home
              </button>
            </div>
          )}

          {view.kind === 'approved' && (
            <div data-testid="pending-approved" className="flex flex-col items-center gap-4 w-full">
              <p className="text-[15px] text-text-dim leading-[1.6] m-0 max-w-85">
                <strong className="text-text font-semibold">{view.email}</strong> has been let in. Sign in
                again to start using Sapling.
              </p>
              <button
                data-testid="pending-signin-again"
                className="btn btn--primary"
                onClick={handleSignInAgain}
              >
                Sign in
              </button>
            </div>
          )}

          {view.kind === 'status' && !view.onWaitlist && (
            <div data-testid="pending-not-on-waitlist" className="flex flex-col items-center gap-4 w-full">
              <p className="text-[15px] text-text-dim leading-[1.6] m-0 max-w-85">
                Sapling is letting students in a few at a time. Join the waitlist as{' '}
                <strong className="text-text font-semibold">{view.email}</strong>{' '}
                and we&apos;ll email you
                when your spot opens.
              </p>
              <button
                data-testid="pending-join"
                className="btn btn--primary"
                onClick={handleJoin}
                disabled={joining}
                aria-busy={joining}
              >
                {joining ? 'Joining…' : 'Join the waitlist'}
              </button>
              {joinFailed && (
                <p
                  data-testid="pending-join-error"
                  role="alert"
                  className="leading-[1.6] m-0 max-w-85 text-md text-err"
                >
                  We couldn&apos;t add you to the waitlist. Please try again.
                </p>
              )}
            </div>
          )}

          {view.kind === 'status' && view.onWaitlist && (
            <div data-testid="pending-on-waitlist" className="flex flex-col items-center gap-4 w-full">
              {view.justJoined && (
                <p
                  data-testid="pending-joined"
                  role="status"
                  className="leading-[1.6] m-0 max-w-85 text-md font-semibold text-accent"
                >
                  Done. You&apos;re on the waitlist.
                </p>
              )}
              <p className="text-[15px] text-text-dim leading-[1.6] m-0 max-w-85">
                You&apos;re on the waitlist as <strong className="text-text font-semibold">{view.email}</strong>.
                We&apos;ll email you when your spot opens.
              </p>
            </div>
          )}
        </div>

        <button
          data-testid="pending-signout"
          className="btn btn--ghost pending-step anim-d3"
          onClick={handleSignOut}
        >
          {view.kind === 'status' || view.kind === 'approved' ? 'Use a different account' : 'Sign out'}
        </button>
      </div>
    </div>
  );
}
