'use client';

import { useState, useEffect } from 'react';
import { useSearchParams } from 'next/navigation';
import { useUser } from '@/context/UserContext';
import { submitFeedback } from '@/lib/api';

const STORAGE_KEY = 'sapling_feedback_last_shown';
const COOLDOWN_DAYS = 7;
const TRIGGER_DELAY_MS = 45_000; // 45s after page load

const IMPROVEMENT_OPTIONS = [
  'AI explanations could be clearer',
  'Navigation is confusing',
  'Missing features I need',
  'Knowledge graph is hard to read',
  'Quiz difficulty feels off',
  'Performance / loading is slow',
  'Something else',
];

const EMOJIS = [
  { emoji: '😞', label: 'Frustrated' },
  { emoji: '😕', label: 'Unhappy' },
  { emoji: '😐', label: 'Neutral' },
  { emoji: '🙂', label: 'Good' },
  { emoji: '😊', label: 'Loving it' },
];

export default function FeedbackFlow() {
  const searchParams = useSearchParams();
  const testMode = searchParams.get('testFeedback') === 'global';
  const { userId } = useUser();
  const [visible, setVisible] = useState(false);
  const [step, setStep] = useState(1);
  const [rating, setRating] = useState<number | null>(null);
  const [hovered, setHovered] = useState<number | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [comment, setComment] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [closing, setClosing] = useState(false);

  useEffect(() => {
    if (testMode) { setVisible(true); return; }
    const last = localStorage.getItem(STORAGE_KEY);
    if (last) {
      const daysSince = (Date.now() - Number(last)) / (1000 * 60 * 60 * 24);
      if (daysSince < COOLDOWN_DAYS) return;
    }
    const timer = setTimeout(() => setVisible(true), TRIGGER_DELAY_MS);
    return () => clearTimeout(timer);
  }, [testMode]);

  function dismiss() {
    setClosing(true);
    setTimeout(() => {
      setVisible(false);
      setClosing(false);
      localStorage.setItem(STORAGE_KEY, String(Date.now()));
    }, 280);
  }

  function handleEmojiSelect(index: number) {
    setRating(index);
    setTimeout(() => setStep(2), 320);
  }

  function toggleOption(option: string) {
    setChecked(prev => {
      const next = new Set(prev);
      next.has(option) ? next.delete(option) : next.add(option);
      return next;
    });
  }

  function handleSubmit() {
    setSubmitted(true);
    localStorage.setItem(STORAGE_KEY, String(Date.now()));
    submitFeedback({
      user_id: userId,
      type: 'global',
      rating: rating!,
      selected_options: Array.from(checked),
      comment: comment || undefined,
    }).catch(() => {});
    setTimeout(() => dismiss(), 1800);
  }

  if (!visible) return null;

  return (
    <div
      style={{
        position: 'fixed',
        bottom: '28px',
        right: '28px',
        zIndex: 9999,
        width: '360px',
        background: 'var(--bg-panel)',
        border: '1px solid var(--border-mid)',
        borderRadius: 'var(--radius-lg)',
        boxShadow: '0 16px 48px rgba(15,23,42,0.14), 0 4px 12px rgba(15,23,42,0.08)',
        animation: closing
          ? 'feedbackSlideDown 280ms var(--ease-in-out) forwards'
          : 'feedbackSlideUp 350ms var(--ease-out) forwards',
        overflow: 'hidden',
      }}
    >
      {/* Progress bar */}
      <div style={{ height: '3px', background: 'var(--bg-subtle)' }}>
        <div
          style={{
            height: '100%',
            background: 'var(--accent)',
            width: submitted ? '100%' : step === 1 ? '33%' : step === 2 ? '66%' : '100%',
            transition: 'width 400ms var(--ease-out)',
          }}
        />
      </div>

      <div style={{ padding: '20px 20px 20px' }}>
        {/* Header row */}
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: '16px' }}>
          <div>
            <p style={{ fontSize: '11px', color: 'var(--accent)', fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: '4px' }}>
              Quick Feedback
            </p>
            <h3 style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text)', lineHeight: 1.3 }}>
              {submitted
                ? 'Thanks for the feedback!'
                : step === 1
                ? 'How do you feel about Sapling?'
                : step === 2
                ? 'What could be better?'
                : <>Anything else to add?<br /><span style={{ color: 'var(--text)' }}>We will listen to YOU!</span></>}
            </h3>
          </div>
          {!submitted && (
            <button
              onClick={dismiss}
              style={{
                background: 'none',
                border: 'none',
                cursor: 'pointer',
                color: 'var(--text-dim)',
                fontSize: '18px',
                lineHeight: 1,
                padding: '2px 4px',
                borderRadius: 'var(--radius-sm)',
                transition: 'color var(--dur-fast)',
                flexShrink: 0,
                marginLeft: '12px',
              }}
              onMouseEnter={e => (e.currentTarget.style.color = 'var(--text)')}
              onMouseLeave={e => (e.currentTarget.style.color = 'var(--text-dim)')}
            >
              ×
            </button>
          )}
        </div>

        {/* ── Step 1: Emoji rating ── */}
        {!submitted && step === 1 && (
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: '6px' }}>
            {EMOJIS.map((e, i) => (
              <button
                key={i}
                onClick={() => handleEmojiSelect(i)}
                onMouseEnter={() => setHovered(i)}
                onMouseLeave={() => setHovered(null)}
                title={e.label}
                style={{
                  flex: 1,
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  gap: '5px',
                  background: rating === i ? 'var(--accent-dim)' : hovered === i ? 'var(--bg-subtle)' : 'transparent',
                  border: rating === i ? '1px solid var(--accent-border)' : '1px solid transparent',
                  borderRadius: 'var(--radius-md)',
                  padding: '8px 4px',
                  cursor: 'pointer',
                  transition: 'all var(--dur-fast)',
                  transform: hovered === i ? 'translateY(-2px)' : 'none',
                }}
              >
                <span style={{ fontSize: '26px', lineHeight: 1 }}>{e.emoji}</span>
                <span style={{ fontSize: '10px', color: 'var(--text-dim)', whiteSpace: 'nowrap' }}>{e.label}</span>
              </button>
            ))}
          </div>
        )}

        {/* ── Step 2: Improvement checklist ── */}
        {!submitted && step === 2 && (
          <>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginBottom: '16px' }}>
              {IMPROVEMENT_OPTIONS.map(opt => {
                const selected = checked.has(opt);
                return (
                  <button
                    key={opt}
                    onClick={() => toggleOption(opt)}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '10px',
                      background: selected ? 'var(--accent-dim)' : 'var(--bg-subtle)',
                      border: `1px solid ${selected ? 'var(--accent-border)' : 'var(--border-light)'}`,
                      borderRadius: 'var(--radius-sm)',
                      padding: '8px 12px',
                      cursor: 'pointer',
                      textAlign: 'left',
                      transition: 'all var(--dur-fast)',
                    }}
                  >
                    <span
                      style={{
                        width: '16px',
                        height: '16px',
                        borderRadius: '4px',
                        border: `1.5px solid ${selected ? 'var(--accent)' : 'var(--border-mid)'}`,
                        background: selected ? 'var(--accent)' : 'transparent',
                        flexShrink: 0,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        transition: 'all var(--dur-fast)',
                      }}
                    >
                      {selected && (
                        <svg width="10" height="8" viewBox="0 0 10 8" fill="none">
                          <path d="M1 4L3.5 6.5L9 1" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                        </svg>
                      )}
                    </span>
                    <span style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>{opt}</span>
                  </button>
                );
              })}
            </div>
            <div style={{ display: 'flex', gap: '8px' }}>
              <button
                onClick={dismiss}
                className="btn-ghost"
                style={{ flex: 1, fontSize: '13px', padding: '8px' }}
              >
                Skip
              </button>
              <button
                onClick={() => setStep(3)}
                className="btn-accent"
                style={{ flex: 2, fontSize: '13px', padding: '8px' }}
              >
                Next →
              </button>
            </div>
          </>
        )}

        {/* ── Step 3: Text input ── */}
        {!submitted && step === 3 && (
          <>
            <textarea
              value={comment}
              onChange={e => setComment(e.target.value)}
              placeholder="Tell us more... (optional)"
              rows={4}
              style={{
                width: '100%',
                background: 'var(--bg-input)',
                border: '1px solid var(--border)',
                borderRadius: 'var(--radius-md)',
                padding: '10px 12px',
                fontSize: '13px',
                color: 'var(--text)',
                resize: 'none',
                outline: 'none',
                fontFamily: 'inherit',
                lineHeight: 1.5,
                marginBottom: '12px',
                transition: 'border-color var(--dur-fast)',
              }}
              onFocus={e => (e.currentTarget.style.borderColor = 'var(--accent-border)')}
              onBlur={e => (e.currentTarget.style.borderColor = 'var(--border)')}
            />
            <div style={{ display: 'flex', gap: '8px' }}>
              <button
                onClick={() => setStep(2)}
                className="btn-ghost"
                style={{ flex: 1, fontSize: '13px', padding: '8px' }}
              >
                ← Back
              </button>
              <button
                onClick={handleSubmit}
                className="btn-accent"
                style={{ flex: 2, fontSize: '13px', padding: '8px' }}
              >
                Submit
              </button>
            </div>
          </>
        )}

        {/* ── Submitted state ── */}
        {submitted && (
          <div style={{ textAlign: 'center', padding: '8px 0 4px' }}>
            <span style={{ fontSize: '32px' }}>🌱</span>
            <p style={{ fontSize: '13px', color: 'var(--text-muted)', marginTop: '8px' }}>
              Your feedback helps us grow.
            </p>
          </div>
        )}
      </div>

      <style>{`
        @keyframes feedbackSlideUp {
          from { opacity: 0; transform: translateY(16px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        @keyframes feedbackSlideDown {
          from { opacity: 1; transform: translateY(0); }
          to   { opacity: 0; transform: translateY(12px); }
        }
      `}</style>
    </div>
  );
}
