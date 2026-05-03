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
    const avatarParam = searchParams.get('avatar');
    const approvedParam = searchParams.get('is_approved');
    const authToken = searchParams.get('auth_token');
    const error = searchParams.get('error');

    const isPopup =
      typeof window !== 'undefined' &&
      !!window.opener &&
      window.opener !== window;

    const postToOpener = (payload: Record<string, unknown>): boolean => {
      if (!isPopup) return false;
      try {
        window.opener.postMessage(
          { type: 'sapling_signin', ...payload },
          window.location.origin,
        );
      } catch {}
      try { window.close(); } catch {}
      return true;
    };

    const fail = (errCode: string) => {
      if (postToOpener({ success: false, error: errCode })) return;
      router.replace(`/?error=${encodeURIComponent(errCode)}`);
    };

    if (error === 'not_approved' || approvedParam === 'false') {
      fail('not_approved');
      return;
    }
    if (approvedParam !== 'true' || !userId) {
      fail(error || 'signin_failed');
      return;
    }

    (async () => {
      try {
        const sessionRes = await fetch('/api/auth/session', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ userId, ...(authToken ? { authToken } : {}) }),
        });
        if (!sessionRes.ok) {
          fail('signin_failed');
          return;
        }
      } catch {
        fail('signin_failed');
        return;
      }

      let onboardingCompleted = true;
      let name = '';
      let avatar = avatarParam || '';
      try {
        const r = await fetch('/api/auth/me');
        const data = await r.json();
        onboardingCompleted = !!data.onboarding_completed;
        name = data.name || '';
        avatar = data.avatar_url || avatar;
      } catch {
        onboardingCompleted = true;
      }

      if (!isPopup) {
        setActiveUser(userId, name, avatar);
        confirmApproved();
      }

      if (postToOpener({
        success: true,
        userId,
        name,
        avatar,
        onboardingCompleted,
      })) return;

      if (onboardingCompleted) {
        router.replace('/dashboard');
      } else {
        sessionStorage.setItem('sapling_onboarding_pending', '1');
        router.replace('/');
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
