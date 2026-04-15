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
    const isNew = searchParams.get('is_new') === 'true';

    if (userId && name) {
      setActiveUser(userId, name, avatar || '');
      if (isNew) {
        // New user — set flag so page.tsx shows onboarding step 1
        sessionStorage.setItem('sapling_onboarding_pending', 'true');
        router.replace('/');
      } else {
        // Existing user — skip onboarding, go straight to dashboard
        sessionStorage.removeItem('sapling_onboarding_pending');
        router.replace('/dashboard');
      }
    } else {
      router.replace('/');
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
