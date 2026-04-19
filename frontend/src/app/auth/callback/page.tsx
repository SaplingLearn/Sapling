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
      router.replace('/auth?error=not_approved');
      return;
    }
    if (approvedParam !== 'true' || !userId || !name) {
      router.replace('/auth?error=signin_failed');
      return;
    }

    setActiveUser(userId, name, avatar || '');
    confirmApproved();

    fetch('/api/auth/session', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ userId, ...(authToken ? { authToken } : {}) }),
    }).catch(() => {});

    const API_URL = process.env.NEXT_PUBLIC_API_URL ?? '';
    fetch(`${API_URL}/api/auth/me?user_id=${encodeURIComponent(userId)}`)
      .then(r => r.json())
      .then(data => {
        router.replace(data.onboarding_completed ? '/dashboard' : '/onboarding');
      })
      .catch(() => router.replace('/dashboard'));
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
