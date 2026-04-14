'use client';

import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import Image from 'next/image';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:5000';

function SignInInner() {
  const searchParams = useSearchParams();
  const error = searchParams.get('error');

  return (
    <div style={{
      minHeight: '100vh',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      background: 'var(--bg-base, #0d1117)',
      padding: '24px',
    }}>
      <Image
        src="/sapling-word-icon.png"
        alt="Sapling"
        width={140}
        height={40}
        style={{ marginBottom: '40px', objectFit: 'contain' }}
      />

      {error === 'not_approved' && (
        <div style={{
          marginBottom: '24px',
          padding: '12px 20px',
          borderRadius: '8px',
          background: 'rgba(234, 179, 8, 0.12)',
          border: '1px solid rgba(234, 179, 8, 0.3)',
          color: '#ca8a04',
          fontSize: '14px',
          textAlign: 'center',
          maxWidth: '360px',
        }}>
          Your account is pending approval.
        </div>
      )}

      <div style={{
        background: 'var(--bg-panel, #161b22)',
        border: '1px solid rgba(255,255,255,0.08)',
        borderRadius: '16px',
        padding: '40px',
        width: '100%',
        maxWidth: '380px',
      }}>
        <h2 style={{
          fontSize: '22px',
          fontWeight: 600,
          color: 'var(--brand-text1, #e6edf3)',
          textAlign: 'center',
          marginBottom: '8px',
          letterSpacing: '-0.02em',
        }}>
          Welcome back
        </h2>
        <p style={{
          fontSize: '14px',
          color: 'var(--brand-text2, #8b949e)',
          textAlign: 'center',
          marginBottom: '28px',
        }}>
          Sign in to continue
        </p>

        <button
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
            transition: 'box-shadow 0.2s',
          }}
          onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.boxShadow = '0 2px 8px rgba(0,0,0,0.12)'; }}
          onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.boxShadow = 'none'; }}
        >
          <svg width="18" height="18" viewBox="0 0 24 24">
            <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4" />
            <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853" />
            <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05" />
            <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335" />
          </svg>
          Continue with Google
        </button>
      </div>
    </div>
  );
}

export default function SignInPage() {
  return (
    <Suspense fallback={<div style={{ minHeight: '100vh', background: '#0d1117' }} />}>
      <SignInInner />
    </Suspense>
  );
}
