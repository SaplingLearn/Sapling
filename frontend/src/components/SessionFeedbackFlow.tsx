'use client';

import { useState } from 'react';
import { useUser } from '@/context/UserContext';
import { submitFeedback } from '@/lib/api';

interface Props {
  visible: boolean;
  topic?: string;
  sessionId?: string;
  onDismiss: () => void;
}

const EMOJIS = [
  { emoji: '😞', label: 'Poor' },
  { emoji: '😕', label: 'Meh' },
  { emoji: '😐', label: 'Okay' },
  { emoji: '🙂', label: 'Good' },
  { emoji: '😊', label: 'Great' },
];

const SESSION_OPTIONS = [
  'Explanations were unclear',
  'Responses felt too generic',
  'Difficulty felt off',
  'Session went off-track',
  'Something seemed inaccurate',
  'Pacing was too fast / slow',
  'Not enough examples',
];

export default function SessionFeedbackFlow({ visible, topic, sessionId, onDismiss }: Props) {
  const { userId } = useUser();
  const [step, setStep] = useState<'rating' | 'detail' | 'text' | 'done'>('rating');
  const [hovered, setHovered] = useState<number | null>(null);
  const [rating, setRating] = useState<number | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [comment, setComment] = useState('');
  const [closing, setClosing] = useState(false);

  function dismiss() {
    setClosing(true);
    setTimeout(() => {
      onDismiss();
      // reset for next time
      setStep('rating');
      setRating(null);
      setChecked(new Set());
      setComment('');
      setClosing(false);
    }, 280);
  }

  function handleEmojiSelect(index: number) {
    setRating(index);
    // All ratings go through detail → text
    setTimeout(() => setStep('detail'), 300);
  }

  function toggleOption(opt: string) {
    setChecked(prev => {
      const next = new Set(prev);
      next.has(opt) ? next.delete(opt) : next.add(opt);
      return next;
    });
  }

  function handleSubmit() {
    setStep('done');
    submitFeedback({
      user_id: userId,
      type: 'session',
      rating: rating!,
      selected_options: Array.from(checked),
      comment: comment || undefined,
      session_id: sessionId,
      topic: topic || undefined,
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
        zIndex: 9998,
        width: '340px',
        background: 'var(--bg-panel)',
        border: '1px solid var(--border-mid)',
        borderRadius: 'var(--radius-lg)',
        boxShadow: '0 16px 48px rgba(15,23,42,0.14), 0 4px 12px rgba(15,23,42,0.08)',
        animation: closing
          ? 'sfSlideDown 280ms var(--ease-in-out) forwards'
          : 'sfSlideUp 350ms var(--ease-out) forwards',
        overflow: 'hidden',
      }}
    >
      {/* Accent top border */}
      <div style={{ height: '3px', background: 'var(--accent)' }} />

      <div style={{ padding: '18px 18px 18px' }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: '14px' }}>
          <div>
            <p style={{ fontSize: '11px', color: 'var(--accent)', fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: '3px' }}>
              Session Feedback
            </p>
            <h3 style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text)', lineHeight: 1.3, margin: 0 }}>
              {step === 'rating' && 'How was your last learn session?'}
              {step === 'detail' && (rating !== null && rating >= 3 ? 'Any areas for improvement?' : 'What fell short?')}
              {step === 'text' && <>Anything else to add?<br /><span style={{ color: 'var(--text)', fontWeight: 700 }}>We will listen to YOU!</span></>}
              {step === 'done' && 'Thanks for the feedback!'}
            </h3>
          </div>
          {step !== 'done' && (
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
                flexShrink: 0,
                marginLeft: '10px',
              }}
              onMouseEnter={e => (e.currentTarget.style.color = 'var(--text)')}
              onMouseLeave={e => (e.currentTarget.style.color = 'var(--text-dim)')}
            >
              ×
            </button>
          )}
        </div>

        {/* ── Step: rating ── */}
        {step === 'rating' && (
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: '4px' }}>
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
                  gap: '4px',
                  background: hovered === i ? 'var(--bg-subtle)' : 'transparent',
                  border: '1px solid transparent',
                  borderRadius: 'var(--radius-md)',
                  padding: '8px 4px',
                  cursor: 'pointer',
                  transition: 'all var(--dur-fast)',
                  transform: hovered === i ? 'translateY(-2px)' : 'none',
                }}
              >
                <span style={{ fontSize: '24px', lineHeight: 1 }}>{e.emoji}</span>
                <span style={{ fontSize: '10px', color: 'var(--text-dim)', whiteSpace: 'nowrap' }}>{e.label}</span>
              </button>
            ))}
          </div>
        )}

        {/* ── Step: detail (negative rating) ── */}
        {step === 'detail' && (
          <>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '5px', marginBottom: '14px' }}>
              {SESSION_OPTIONS.map(opt => {
                const selected = checked.has(opt);
                return (
                  <button
                    key={opt}
                    onClick={() => toggleOption(opt)}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '9px',
                      background: selected ? 'var(--accent-dim)' : 'var(--bg-subtle)',
                      border: `1px solid ${selected ? 'var(--accent-border)' : 'var(--border-light)'}`,
                      borderRadius: 'var(--radius-sm)',
                      padding: '7px 10px',
                      cursor: 'pointer',
                      textAlign: 'left',
                      transition: 'all var(--dur-fast)',
                    }}
                  >
                    <span
                      style={{
                        width: '15px',
                        height: '15px',
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
                        <svg width="9" height="7" viewBox="0 0 9 7" fill="none">
                          <path d="M1 3.5L3 5.5L8 1" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                        </svg>
                      )}
                    </span>
                    <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>{opt}</span>
                  </button>
                );
              })}
            </div>

            <div style={{ display: 'flex', gap: '8px' }}>
              <button
                onClick={dismiss}
                className="btn-ghost"
                style={{ flex: 1, fontSize: '12px', padding: '7px' }}
              >
                Skip
              </button>
              <button
                onClick={() => setStep('text')}
                className="btn-accent"
                style={{ flex: 2, fontSize: '12px', padding: '7px' }}
              >
                Next →
              </button>
            </div>
          </>
        )}

        {/* ── Step: text ── */}
        {step === 'text' && (
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
                onClick={() => setStep('detail')}
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

        {/* ── Done state ── */}
        {step === 'done' && (
          <div style={{ textAlign: 'center', padding: '4px 0 2px' }}>
            <span style={{ fontSize: '28px' }}>
              {rating !== null && rating >= 3 ? '🌱' : '🙏'}
            </span>
            <p style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '6px' }}>
              {rating !== null && rating >= 3
                ? 'Keep growing!'
                : "We'll use this to improve."}
            </p>
          </div>
        )}
      </div>

      <style>{`
        @keyframes sfSlideUp {
          from { opacity: 0; transform: translateY(14px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        @keyframes sfSlideDown {
          from { opacity: 1; transform: translateY(0); }
          to   { opacity: 0; transform: translateY(10px); }
        }
      `}</style>
    </div>
  );
}
