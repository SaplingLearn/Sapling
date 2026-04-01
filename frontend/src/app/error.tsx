'use client';

export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      padding: '64px 24px',
      textAlign: 'center',
      minHeight: 'calc(100vh - 48px)',
      fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif",
    }}>
      <h2 style={{ fontSize: '18px', fontWeight: 600, color: '#111827', marginBottom: '8px' }}>
        Something went wrong
      </h2>
      <p style={{ fontSize: '14px', color: '#6b7280', marginBottom: '24px', maxWidth: '440px', lineHeight: 1.6 }}>
        {error.message || 'An unexpected error occurred. Please try again.'}
      </p>
      <button
        onClick={reset}
        style={{
          padding: '10px 24px',
          background: '#1a5c2a',
          color: '#ffffff',
          border: 'none',
          borderRadius: '7px',
          fontSize: '14px',
          fontWeight: 600,
          cursor: 'pointer',
        }}
      >
        Try Again
      </button>
    </div>
  );
}
