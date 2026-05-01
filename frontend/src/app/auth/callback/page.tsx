'use client';

import { Suspense, useEffect } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import { useUser } from '@/context/UserContext';

function CallbackInner() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const { setActiveUser, confirmApproved } = useUser();

  useEffect(() => {
    const userId = searchParams.get('user_id');
    const name = searchParams.get('name');
    const avatar = searchParams.get('avatar');
    const approvedParam = searchParams.get('is_approved');
    const authToken = searchParams.get('auth_token');
    const error = searchParams.get('error');

    if (error === 'not_approved' || approvedParam === 'false') {
      router.replace('/?error=not_approved');
      return;
    }
    if (approvedParam !== 'true' || !userId || !name) {
      router.replace('/?error=signin_failed');
      return;
    }

    setActiveUser(userId, name, avatar || '');
    confirmApproved();

    (async () => {
      try {
        const sessionRes = await fetch('/api/auth/session', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ userId, ...(authToken ? { authToken } : {}) }),
        });
        if (!sessionRes.ok) {
          router.replace('/?error=signin_failed');
          return;
        }
      } catch {
        router.replace('/?error=signin_failed');
        return;
      }
      try {
        const r = await fetch(`/api/auth/me?user_id=${encodeURIComponent(userId)}`);
        const data = await r.json();
        if (data.onboarding_completed) {
          router.replace('/dashboard');
        } else {
          sessionStorage.setItem('sapling_onboarding_pending', '1');
          router.replace('/');
        }
      } catch {
        router.replace('/dashboard');
      }
    })();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'var(--bg)',
        color: 'var(--text-dim)',
        fontSize: 14,
      }}
    >
      Signing you in…
    </div>
  );
}

export default function CallbackPage() {
  return (
    <Suspense fallback={<div style={{ minHeight: '100vh', background: 'var(--bg)' }} />}>
      <CallbackInner />
    </Suspense>
  );
}
