'use client';

import { useRouter } from 'next/navigation';
import { useUser } from '@/context/UserContext';

/**
 * The approval gate — where a student lands after signing up but before an
 * admin approves them.
 *
 * The beat matters here: sign-up ENDS on this screen, so it has to read as
 * "you're in, now wait" rather than a dead end. The sapling draws itself once
 * and the message steps in behind it (`.pending-*` in globals.css), settling
 * in ~560ms. One-shot CSS animation on purpose — the global
 * prefers-reduced-motion reset collapses CSS animation automatically, where a
 * JS-driven entrance would have to re-implement that guard itself.
 */
export default function PendingPage() {
  const router = useRouter();
  const { signOut } = useUser();

  async function handleSignOut() {
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
          You&apos;re on the waitlist
        </h1>
        <p
          className="pending-step anim-d2"
          style={{
            fontSize: 15,
            color: 'var(--text-dim)',
            lineHeight: 1.6,
            marginBottom: 24,
            maxWidth: 340,
          }}
        >
          We&apos;ll reach out when your access is approved.
        </p>
        <button
          data-testid="pending-signout"
          className="btn pending-step anim-d3"
          onClick={handleSignOut}
        >
          Sign out
        </button>
      </div>
    </div>
  );
}
