'use client';

import { useEffect, useState, type CSSProperties } from 'react';
import { useRouter } from 'next/navigation';
import { useUser } from '@/context/UserContext';
import { getPendingStatus, joinWaitlistFromPending } from '@/lib/api';
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
 * The heading is the same in every state, so the card doesn't jump when the
 * status arrives; only the body below it changes.
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
  | { kind: 'status'; email: string; onWaitlist: boolean; justJoined: boolean };

const bodyText: CSSProperties = {
  fontSize: 15,
  color: 'var(--text-dim)',
  lineHeight: 1.6,
  margin: 0,
  maxWidth: 340,
};

const emailStyle: CSSProperties = { color: 'var(--text)', fontWeight: 600 };

const stateStyle: CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'center',
  gap: 16,
  width: '100%',
};

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
      setView({ kind: 'status', email: s.email, onWaitlist: s.on_waitlist, justJoined: true });
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

  async function handleSignOut() {
    clearPendingToken();
    await signOut();
    router.replace('/');
  }

  return (
    <div
      data-testid="pending-gate"
      style={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'radial-gradient(ellipse at top, var(--accent-soft) 0%, var(--bg) 60%)',
        color: 'var(--text)',
        padding: 24,
      }}
    >
      <div
        className="card pending-card"
        style={{
          // .card carries bg/border/radius/shadow but no padding — that part
          // is the caller's job.
          padding: 'var(--pad-lg)',
          maxWidth: 440,
          width: '100%',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          textAlign: 'center',
        }}
      >
        <svg
          width="56"
          height="56"
          viewBox="0 0 24 24"
          aria-hidden="true"
          style={{ marginBottom: 20 }}
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
          className="h-serif pending-step anim-d1"
          style={{ fontSize: 30, fontWeight: 500, marginBottom: 10 }}
        >
          Your account isn&apos;t approved yet
        </h1>

        <div
          className="pending-step anim-d2"
          aria-live="polite"
          aria-busy={view.kind === 'loading'}
          style={{
            ...stateStyle,
            // Reserve about three lines of copy so the card doesn't jump when
            // the status lands.
            minHeight: 72,
            marginBottom: 24,
          }}
        >
          {view.kind === 'loading' && (
            <p data-testid="pending-loading" style={bodyText}>
              Checking your account…
            </p>
          )}

          {view.kind === 'unknown' && (
            <div data-testid="pending-unknown" style={stateStyle}>
              <p style={bodyText}>
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

          {view.kind === 'status' && !view.onWaitlist && (
            <div data-testid="pending-not-on-waitlist" style={stateStyle}>
              <p style={bodyText}>
                Sapling is letting students in a few at a time. Join the waitlist as{' '}
                <strong style={emailStyle}>{view.email}</strong>{' '}
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
                  style={{ ...bodyText, fontSize: 13, color: 'var(--err)' }}
                >
                  We couldn&apos;t add you to the waitlist. Please try again.
                </p>
              )}
            </div>
          )}

          {view.kind === 'status' && view.onWaitlist && (
            <div data-testid="pending-on-waitlist" style={stateStyle}>
              {view.justJoined && (
                <p
                  data-testid="pending-joined"
                  role="status"
                  style={{ ...bodyText, fontSize: 13, fontWeight: 600, color: 'var(--accent)' }}
                >
                  Done. You&apos;re on the waitlist.
                </p>
              )}
              <p style={bodyText}>
                You&apos;re on the waitlist as <strong style={emailStyle}>{view.email}</strong>.
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
          {view.kind === 'status' ? 'Use a different account' : 'Sign out'}
        </button>
      </div>
    </div>
  );
}
