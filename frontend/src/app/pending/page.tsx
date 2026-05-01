'use client';

import { useRouter } from 'next/navigation';
import { useUser } from '@/context/UserContext';

export default function PendingPage() {
  const router = useRouter();
  const { signOut } = useUser();

  async function handleSignOut() {
    await signOut();
    router.replace('/');
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'radial-gradient(ellipse at top, var(--accent-soft) 0%, var(--bg) 60%)',
        color: 'var(--text)',
        padding: 24,
      }}
    >
      <svg width="56" height="56" viewBox="0 0 24 24" style={{ marginBottom: 24 }}>
        <path d="M12 22 Q 5 15 5 9 Q 5 3 12 3 Q 19 3 19 9 Q 19 15 12 22 Z" fill="var(--accent)" opacity={0.2} />
        <path d="M12 22 V 10 M12 13 Q 8 10 7 7 M12 14 Q 16 11 17 8" stroke="var(--accent)" strokeWidth={1.5} fill="none" strokeLinecap="round" />
      </svg>
      <h1 className="h-serif" style={{ fontSize: 36, fontWeight: 500, marginBottom: 12, textAlign: 'center' }}>
        You&apos;re on the waitlist
      </h1>
      <p style={{ fontSize: 15, color: 'var(--text-dim)', textAlign: 'center', maxWidth: 420, lineHeight: 1.6, marginBottom: 32 }}>
        We&apos;ll reach out when your access is approved.
      </p>
      <button className="btn" onClick={handleSignOut}>Sign out</button>
    </div>
  );
}
