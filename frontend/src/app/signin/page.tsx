'use client';

import { useSearchParams } from 'next/navigation';
import { Suspense } from 'react';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? '';

function SignInInner() {
  const searchParams = useSearchParams();
  const error = searchParams.get('error');

  const errorMessages: Record<string, string> = {
    invalid_domain: 'Only @bu.edu accounts are allowed. Please sign in with your BU email.',
    google_not_configured: 'Google sign-in is not configured. Please contact an administrator.',
  };

  const handleSignIn = () => {
    window.location.href = `${API_URL || 'http://localhost:5000'}/api/auth/google`;
  };

  return (
    <div style={{
      minHeight: '100vh',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      background: '#f0f5f0',
      fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif",
    }}>
      <div style={{
        background: '#ffffff',
        borderRadius: '12px',
        padding: '40px 36px',
        maxWidth: '400px',
        width: '100%',
        boxShadow: '0 4px 24px rgba(0,0,0,0.08)',
        border: '1px solid rgba(107,114,128,0.12)',
        textAlign: 'center',
      }}>
        <img src="/sapling-icon.svg" alt="Sapling" style={{ width: '48px', height: '48px', marginBottom: '16px' }} />
        <h1 style={{
          fontSize: '24px',
          fontWeight: 700,
          color: '#1a5c2a',
          margin: '0 0 8px',
          fontFamily: "var(--font-spectral), 'Spectral', Georgia, serif",
        }}>
          Sapling
        </h1>
        <p style={{ fontSize: '14px', color: '#6b7280', margin: '0 0 28px' }}>
          Sign in with your BU Google account
        </p>

        {error && (
          <div style={{
            padding: '10px 14px',
            background: '#fef2f2',
            border: '1px solid #fca5a5',
            borderRadius: '8px',
            fontSize: '13px',
            color: '#dc2626',
            marginBottom: '20px',
          }}>
            {errorMessages[error] || 'An error occurred during sign-in. Please try again.'}
          </div>
        )}

        <button
          onClick={handleSignIn}
          style={{
            width: '100%',
            padding: '12px 20px',
            background: '#ffffff',
            color: '#374151',
            border: '1px solid rgba(107,114,128,0.25)',
            borderRadius: '8px',
            fontSize: '14px',
            fontWeight: 500,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '10px',
            transition: 'background 0.15s, box-shadow 0.15s',
            fontFamily: 'inherit',
          }}
          onMouseEnter={e => {
            e.currentTarget.style.background = '#f9fafb';
            e.currentTarget.style.boxShadow = '0 2px 8px rgba(0,0,0,0.06)';
          }}
          onMouseLeave={e => {
            e.currentTarget.style.background = '#ffffff';
            e.currentTarget.style.boxShadow = 'none';
          }}
        >
          <svg width="18" height="18" viewBox="0 0 48 48">
            <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
            <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>
            <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>
            <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>
          </svg>
          Sign in with Google
        </button>

        <p style={{ fontSize: '11px', color: '#9ca3af', margin: '20px 0 0' }}>
          Requires a @bu.edu Google account
        </p>
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
