'use client';

import { useEffect, Suspense } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import { useUser } from '@/context/UserContext';

function CallbackInner() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const { setActiveUser } = useUser();

  useEffect(() => {
    const userId = searchParams.get('user_id');
    const name = searchParams.get('name');
    const avatar = searchParams.get('avatar');
    const isApproved = searchParams.get('is_approved') === 'true';
    const error = searchParams.get('error');

    if (error === 'not_approved' || !isApproved) {
      router.replace('/pending');
      return;
    }

    if (userId && name) {
      setActiveUser(userId, name, avatar || '', true);
      document.cookie = 'sapling_approved=1; path=/; max-age=2592000; SameSite=Lax';
      document.cookie = `sapling_uid=${userId}; path=/; max-age=2592000; SameSite=Lax`;
      router.replace('/dashboard');
    } else {
      router.replace('/signin');
    }
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
