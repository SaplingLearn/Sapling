'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useUser } from '@/context/UserContext';
import { getLocalSeedStatus } from '@/lib/api';
import { statusOf } from '@/lib/errorMessage';

const POLL_MS = 2000;

/**
 * #715: the hold screen a NEW account waits on after signing in to a
 * developer's local stack, while the backend copies the rich sample dataset
 * onto it (services/local_seed_watcher.py). Polls GET /api/auth/local-seed:
 * `ready` → the dashboard (the seed completed onboarding server-side);
 * `failed` → the error plus "Continue anyway" to /onboarding. A 404 means the
 * backend is not local, so there is nothing to wait for — straight on to
 * /onboarding; a 401 means no session — back to the landing page. Anything
 * else (a restarting dev backend) just keeps polling.
 *
 * Rendered bare, outside (shell): no middleware gate and no onboarding bounce
 * applies here, and the post-sign-in routing (lib/localSeed.ts) only sends
 * accounts here when the backend said to.
 */
export default function SettingUpPage() {
  const router = useRouter();
  const { refreshProfile } = useUser();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const poll = async () => {
      try {
        const status = await getLocalSeedStatus();
        if (cancelled) return;
        if (status.state === 'ready') {
          // Re-read /api/auth/me so the context matches the seeded account.
          await refreshProfile();
          if (!cancelled) router.replace('/dashboard');
          return;
        }
        if (status.state === 'failed') {
          setError(status.error || 'The sample data could not be created.');
          return;
        }
      } catch (err) {
        if (cancelled) return;
        const code = statusOf(err);
        if (code === 404) {
          router.replace('/onboarding');
          return;
        }
        if (code === 401) {
          router.replace('/');
          return;
        }
      }
      timer = setTimeout(poll, POLL_MS);
    };

    void poll();
    return () => {
      cancelled = true;
      if (timer !== undefined) clearTimeout(timer);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div
      data-testid="setup-gate"
      style={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 10,
        padding: 24,
        textAlign: 'center',
        background: 'var(--bg)',
        color: 'var(--text-dim)',
        fontSize: 14,
      }}
    >
      {error === null ? (
        <>
          <div role="status">Setting up your sample data…</div>
          <div style={{ fontSize: 12.5, color: 'var(--text-muted)' }}>
            Copying the local demo courses onto your account. This takes a few seconds.
          </div>
        </>
      ) : (
        <>
          <div style={{ color: 'var(--text)' }}>Your sample data could not be set up.</div>
          <div
            data-testid="setup-error"
            role="alert"
            style={{ color: 'var(--err)', fontSize: 12.5, maxWidth: 520, wordBreak: 'break-word' }}
          >
            {error}
          </div>
          <a
            data-testid="setup-continue"
            href="/onboarding"
            style={{ marginTop: 6, color: 'var(--accent)', textDecoration: 'underline' }}
          >
            Continue anyway
          </a>
        </>
      )}
    </div>
  );
}
