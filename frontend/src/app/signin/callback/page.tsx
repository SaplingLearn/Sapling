'use client';

import { useEffect, useState, Suspense } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import { useUser } from '@/context/UserContext';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? '';
// If NEXT_PUBLIC_API_URL is not configured, falling back to a relative
// "/api/auth/google" would 404 (it's a backend endpoint, not a frontend
// route). Sending the user to "/signin" is the only safe client-resolvable
// recovery, since the middleware handles re-launching OAuth from there.
const TRY_AGAIN_HREF = API_URL ? `${API_URL}/api/auth/google` : '/signin';

function CallbackInner() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const { setActiveUser, confirmApproved } = useUser();
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    const userId = searchParams.get('user_id');
    const name = searchParams.get('name');
    const avatar = searchParams.get('avatar');
    const approvedParam = searchParams.get('is_approved');
    const authToken = searchParams.get('auth_token');
    const error = searchParams.get('error');

    if (error === 'not_approved' || approvedParam === 'false') {
      router.replace('/pending');
      return;
    }

    if (approvedParam !== 'true') {
      setErrorMsg('Sign-in failed. Please try again.');
      return;
    }

    if (userId && name) {
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
          router.replace('/pending');
        } else {
          setErrorMsg('Unable to complete sign-in. Please try again.');
        }
      }).catch(() => {
        setErrorMsg('Unable to reach the server. Please try again.');
      });
    } else {
      setErrorMsg('Sign-in failed. Please try again.');
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  if (errorMsg) {
    return (
      <div style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexDirection: 'column',
        gap: '16px',
        background: '#f0f5f0',
        padding: '24px',
      }}>
        <p style={{ color: '#374151', fontSize: '15px', textAlign: 'center' }}>{errorMsg}</p>
        <a
          href={TRY_AGAIN_HREF}
          style={{
            padding: '10px 24px',
            background: '#1a5c2a',
            color: '#fff',
            borderRadius: '8px',
            fontSize: '14px',
            fontWeight: 500,
            textDecoration: 'none',
          }}
        >
          Try again
        </a>
      </div>
    );
  }

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
