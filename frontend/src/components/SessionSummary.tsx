'use client';

import { SessionSummary as SessionSummaryType } from '@/lib/types';

interface Props {
  summary: SessionSummaryType;
  onDashboard: () => void;
  onNewSession: () => void;
}

export default function SessionSummary({ summary, onDashboard, onNewSession }: Props) {
  const hasGains = summary.mastery_changes.some(mc => mc.after > mc.before);
  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.35)',
        backdropFilter: 'blur(4px)',
        WebkitBackdropFilter: 'blur(4px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 100,
      }}
    >
      <div
        className="panel animate-scale-in"
        style={{
          padding: '32px',
          width: '480px',
          maxWidth: '90vw',
        }}
      >
        <div style={{ marginBottom: '24px' }}>
          <p style={{ fontSize: '11px', fontWeight: 600, color: 'var(--accent)', textTransform: 'uppercase', letterSpacing: '0.09em', marginBottom: '6px' }}>
            {hasGains ? '✦ Great work' : 'Complete'}
          </p>
          <h2 style={{ fontSize: '22px', fontWeight: 700, color: 'var(--text)', letterSpacing: '-0.02em', margin: 0 }}>
            Session complete
          </h2>
        </div>

        <div style={{ marginBottom: '20px' }}>
          <p className="label" style={{ marginBottom: '8px' }}>Concepts Covered</p>
          {summary.concepts_covered.length > 0 ? (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
              {summary.concepts_covered.map((c, i) => (
                <span
                  key={c}
                  className="animate-fade-in"
                  style={{
                    padding: '3px 10px',
                    background: 'var(--accent-dim)',
                    border: '1px solid var(--accent-border)',
                    borderRadius: '4px',
                    fontSize: '13px',
                    color: 'var(--accent)',
                    fontWeight: 500,
                    animationDelay: `${i * 55}ms`,
                  }}
                >
                  {c}
                </span>
              ))}
            </div>
          ) : (
            <p style={{ color: 'var(--text-dim)', fontSize: '14px' }}>No concepts recorded</p>
          )}
        </div>

        {summary.mastery_changes.length > 0 && (
          <div style={{ marginBottom: '20px' }}>
            <p className="label" style={{ marginBottom: '8px' }}>Mastery Changes</p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              {summary.mastery_changes.map((mc, i) => {
                const delta = Math.round((mc.after - mc.before) * 100);
                const positive = delta >= 0;
                return (
                  <div key={mc.concept} className="animate-fade-in" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', animationDelay: `${i * 60}ms` }}>
                    <span style={{ fontSize: '14px', color: 'var(--text)' }}>{mc.concept}</span>
                    <span className={positive ? 'animate-celebrate-pop' : ''} style={{ fontSize: '14px', fontWeight: 700, color: positive ? '#16a34a' : '#dc2626', letterSpacing: '-0.01em', animationDelay: `${i * 60 + 200}ms` }}>
                      {positive ? '+' : ''}{delta}%
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        <div style={{ marginBottom: '24px' }}>
          <p className="label" style={{ marginBottom: '8px' }}>Time Spent</p>
          <p style={{ fontSize: '20px', fontWeight: 700, color: 'var(--text)', letterSpacing: '-0.02em' }}>
            {summary.time_spent_minutes} {summary.time_spent_minutes === 1 ? 'minute' : 'minutes'}
          </p>
        </div>

        {summary.recommended_next.length > 0 && (
          <div style={{ marginBottom: '24px' }}>
            <p className="label" style={{ marginBottom: '8px' }}>Recommended Next</p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
              {summary.recommended_next.map(c => (
                <div key={c} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <span aria-hidden="true" style={{ fontSize: '13px', color: 'var(--text-dim)' }}>→</span>
                  <span style={{ fontSize: '14px', color: 'var(--text-muted)' }}>{c}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        <div style={{ display: 'flex', gap: '12px' }}>
          <button
            onClick={onDashboard}
            className="btn-ghost"
            style={{ flex: 1 }}
          >
            Dashboard
          </button>
          <button
            onClick={onNewSession}
            className="btn-accent"
            style={{ flex: 1 }}
          >
            New Session
          </button>
        </div>
      </div>
    </div>
  );
}
