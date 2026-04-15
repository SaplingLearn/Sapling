'use client';

import { useRouter } from 'next/navigation';
import Image from 'next/image';

export default function PendingPage() {
  const router = useRouter();

  async function handleSignOut() {
    localStorage.removeItem('sapling_user');
    await fetch('/api/auth/session', { method: 'DELETE' });
    router.replace('/signin');
  }

  return (
    <div style={{
      minHeight: '100vh',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      background: 'var(--bg-base, #0d1117)',
      color: 'var(--brand-text1, #e6edf3)',
      padding: '24px',
    }}>
      <Image
        src="/sapling-word-icon.png"
        alt="Sapling"
        width={140}
        height={40}
        style={{ marginBottom: '40px', objectFit: 'contain' }}
      />
      <h1 style={{
        fontSize: '28px',
        fontWeight: 600,
        marginBottom: '12px',
        textAlign: 'center',
        letterSpacing: '-0.02em',
      }}>
        You&apos;re on the waitlist
      </h1>
      <p style={{
        fontSize: '15px',
        color: 'var(--brand-text2, #8b949e)',
        textAlign: 'center',
        maxWidth: '340px',
        lineHeight: 1.6,
        marginBottom: '40px',
      }}>
        We&apos;ll reach out when your access is approved.
      </p>
      <button
        onClick={handleSignOut}
        style={{
          background: 'transparent',
          border: '1px solid rgba(255,255,255,0.15)',
          color: 'var(--brand-text2, #8b949e)',
          padding: '10px 24px',
          borderRadius: '8px',
          fontSize: '14px',
          cursor: 'pointer',
          transition: 'border-color 0.2s, color 0.2s',
        }}
        onMouseEnter={e => {
          (e.currentTarget as HTMLButtonElement).style.borderColor = 'rgba(255,255,255,0.35)';
          (e.currentTarget as HTMLButtonElement).style.color = 'var(--brand-text1, #e6edf3)';
        }}
        onMouseLeave={e => {
          (e.currentTarget as HTMLButtonElement).style.borderColor = 'rgba(255,255,255,0.15)';
          (e.currentTarget as HTMLButtonElement).style.color = 'var(--brand-text2, #8b949e)';
        }}
      >
        Sign out
      </button>
    </div>
  );
}
