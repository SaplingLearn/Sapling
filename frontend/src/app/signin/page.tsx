'use client';

import { Suspense, useEffect } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import Image from 'next/image';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:5000';

const ERROR_COPY: Record<string, string> = {
  not_approved: 'Your account is pending approval.',
  invalid_domain: 'Sign-in is limited to approved school accounts.',
  google_not_configured: 'Google sign-in is not configured on the server.',
};

function SignInInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const error = searchParams.get('error');

  useEffect(() => {
    let cancelled = false;
    const saved = typeof window !== 'undefined' ? localStorage.getItem('sapling_user') : null;
    if (!saved) return;
    try {
      const { id } = JSON.parse(saved) as { id?: string };
      if (!id || typeof id !== 'string') return;
      fetch('/api/auth/session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ userId: id }),
      }).then(res => {
        if (cancelled) return;
        if (res.ok) {
          router.replace('/dashboard');
          return;
        }
        if (res.status === 403) {
          router.replace('/pending');
        }
      });
    } catch {
      /* ignore */
    }
    return () => {
      cancelled = true;
    };
  }, [router]);

  const errorMessage = error ? (ERROR_COPY[error] ?? `Something went wrong (${error}).`) : null;

  return (
    <div style={{
      minHeight: '100vh',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      background: '#f0f5f0',
      padding: '24px',
    }}>
      <Image
        src="/sapling-word-icon.png"
        alt="Sapling"
        width={140}
        height={40}
        style={{ marginBottom: '32px', objectFit: 'contain' }}
      />

      <div style={{
        background: '#ffffff',
        border: '1px solid #e5e7eb',
        borderRadius: '16px',
        padding: '32px',
        width: '100%',
        maxWidth: '400px',
        boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
      }}>
        {errorMessage ? (
          <>
            <p style={{
              fontSize: '15px',
              color: '#374151',
              textAlign: 'center',
              lineHeight: 1.5,
              marginBottom: '24px',
            }}>
              {errorMessage}
            </p>
            <button
              type="button"
              onClick={() => { window.location.href = `${API_URL}/api/auth/google`; }}
              style={{
                width: '100%',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '12px',
                padding: '12px 20px',
                background: '#ffffff',
                border: '1px solid #d1d5db',
                borderRadius: '10px',
                fontSize: '14px',
                fontWeight: 500,
                color: '#111827',
                cursor: 'pointer',
              }}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden>
                <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4" />
                <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853" />
                <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05" />
                <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335" />
              </svg>
              Try again with Google
            </button>
            <p style={{ marginTop: '16px', textAlign: 'center', fontSize: '13px', color: '#6b7280' }}>
              <a href="/" style={{ color: '#1B6C42', fontWeight: 500 }}>Back to home</a>
            </p>
          </>
        ) : (
          <p style={{ fontSize: '14px', color: '#6b7280', textAlign: 'center' }}>
            Redirecting to sign in…
          </p>
        )}
      </div>
    </div>
  );
}

export default function SignInPage() {
  return (
    <Suspense fallback={<div style={{ minHeight: '100vh', background: '#f0f5f0' }} />}>
      <SignInInner />
    </Suspense>
  );
}
