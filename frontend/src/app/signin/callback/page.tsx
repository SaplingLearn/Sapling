'use client';

import { useEffect, Suspense } from 'react';
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
      router.replace('/signin?error=not_approved');
      return;
    }

    if (approvedParam !== 'true' || !userId || !name) {
      router.replace('/signin?error=signin_failed');
      return;
    }

    setActiveUser(userId, name, avatar || '');
    fetch('/api/auth/session', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ userId, ...(authToken ? { authToken } : {}) }),
    }).then(res => {
      if (res.ok) {
        confirmApproved();
        router.replace('/dashboard');
      } else if (res.status === 403) {
        router.replace('/signin?error=not_approved');
      } else {
        router.replace('/signin?error=signin_failed');
      }
    }).catch(() => {
      router.replace('/signin?error=signin_failed');
    });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div style={{
      minHeight: '100vh',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      background: '#f0f5f0',
      color: '#6b7280',
      fontSize: '14px',
    }}>
      Signing you in...
    </div>
  );
}

export default function CallbackPage() {
  return (
    <Suspense fallback={<div style={{ minHeight: '100vh', background: '#f0f5f0' }} />}>
      <CallbackInner />
    </Suspense>
  );
}
