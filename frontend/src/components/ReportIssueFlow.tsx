'use client';

import { useRef, useState } from 'react';
import { useUser } from '@/context/UserContext';
import { submitIssueReport } from '@/lib/api';
import { supabase } from '@/lib/supabase';

interface Props {
  visible: boolean;
  onDismiss: () => void;
}

const ISSUE_TOPICS = [
  'AI / Learning Assistant',
  'Library / Resources',
  'Study Tools',
  'Calendar',
  'Social / Rooms',
  'Account / Profile',
  'Performance / Speed',
  'UI / Display',
  'Other',
];

export default function ReportIssueFlow({ visible, onDismiss }: Props) {
  const { userId } = useUser();
  const [step, setStep] = useState<'topics' | 'details' | 'done'>('topics');
  const [checked, setChecked] = useState<string | null>(null);
  const [comment, setComment] = useState('');
  const [screenshots, setScreenshots] = useState<File[]>([]);
  const [screenshotPreviews, setScreenshotPreviews] = useState<string[]>([]);
  const [screenshotTypes, setScreenshotTypes] = useState<string[]>([]);
  const [closing, setClosing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  function dismiss() {
    setClosing(true);
    setTimeout(() => {
      onDismiss();
      setStep('topics');
      setChecked(null);
      setComment('');
      setScreenshots([]);
      setScreenshotPreviews([]);
      setScreenshotTypes([]);
      setClosing(false);
    }, 280);
  }

  function toggleTopic(t: string) {
    setChecked(prev => prev === t ? null : t);
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files || []);
    if (!files.length) return;
    setScreenshots(prev => [...prev, ...files].slice(0, 5));
    setScreenshotPreviews(prev => [...prev, ...files.map(f => URL.createObjectURL(f))].slice(0, 5));
    setScreenshotTypes(prev => [...prev, ...files.map(f => f.type)].slice(0, 5));
    if (fileRef.current) fileRef.current.value = '';
  }

  function removeScreenshot(index: number) {
    setScreenshots(prev => prev.filter((_, i) => i !== index));
    setScreenshotPreviews(prev => prev.filter((_, i) => i !== index));
    setScreenshotTypes(prev => prev.filter((_, i) => i !== index));
  }

  async function handleSubmit() {
    setSubmitting(true);
    const urls: string[] = [];
    for (const file of screenshots) {
      const ext = file.name.split('.').pop() || 'png';
      const path = `${userId}/${Date.now()}_${Math.random().toString(36).slice(2)}.${ext}`;
      const { error } = await supabase.storage.from('issues-media-files').upload(path, file);
      if (error) console.error('Upload error:', error);
      if (!error) {
        const { data } = supabase.storage.from('issues-media-files').getPublicUrl(path);
        urls.push(data.publicUrl);
      }
    }
    await submitIssueReport({
      user_id: userId,
      topic: checked!,
      description: comment,
      screenshot_urls: urls,
    }).catch(() => {});
    setSubmitting(false);
    setStep('done');
    setTimeout(() => dismiss(), 2000);
  }

  if (!visible) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        onClick={dismiss}
        style={{
          position: 'fixed',
          inset: 0,
          background: 'rgba(15,23,42,0.45)',
          zIndex: 9997,
          animation: closing ? 'riFadeOut 280ms forwards' : 'riFadeIn 200ms forwards',
        }}
      />

      {/* Modal */}
      <div
        style={{
          position: 'fixed',
          top: '50%',
          left: '50%',
          transform: 'translate(-50%, -50%)',
          zIndex: 9998,
          width: '420px',
          maxHeight: '80vh',
          overflowY: 'auto',
          background: 'var(--bg-panel)',
          border: '1px solid var(--border-mid)',
          borderRadius: 'var(--radius-lg)',
          boxShadow: '0 24px 64px rgba(15,23,42,0.2), 0 8px 24px rgba(15,23,42,0.1)',
          animation: closing ? 'riSlideOut 280ms var(--ease-in-out) forwards' : 'riSlideIn 300ms var(--ease-out) forwards',
        }}
      >
        {/* Accent top border */}
        <div style={{ height: '3px', background: '#dc2626', borderRadius: 'var(--radius-lg) var(--radius-lg) 0 0' }} />

        <div style={{ padding: '22px 22px 22px' }}>
          {/* Header */}
          <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: '18px' }}>
            <div>
              <p style={{ fontSize: '11px', color: '#dc2626', fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: '3px' }}>
                Report an Issue
              </p>
              <h3 style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text)', lineHeight: 1.3, margin: 0 }}>
                {step === 'topics' && "What's the issue about?"}
                {step === 'details' && <>Describe the issue<br />We will listen to YOU!</>}
                {step === 'done' && 'Report submitted!'}
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
                  fontSize: '20px',
                  lineHeight: 1,
                  padding: '2px 4px',
                  borderRadius: 'var(--radius-sm)',
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

          {/* ── Step: topics ── */}
          {step === 'topics' && (
            <>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '5px', marginBottom: '18px' }}>
                {ISSUE_TOPICS.map(t => {
                  const selected = checked === t;
                  return (
                    <button
                      key={t}
                      onClick={() => toggleTopic(t)}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '10px',
                        background: selected ? 'rgba(220,38,38,0.06)' : 'var(--bg-subtle)',
                        border: `1px solid ${selected ? 'rgba(220,38,38,0.4)' : 'var(--border-light)'}`,
                        borderRadius: 'var(--radius-sm)',
                        padding: '8px 11px',
                        cursor: 'pointer',
                        textAlign: 'left',
                        transition: 'all var(--dur-fast)',
                      }}
                    >
                      <span
                        style={{
                          width: '15px',
                          height: '15px',
                          borderRadius: '50%',
                          border: `1.5px solid ${selected ? '#dc2626' : 'var(--border-mid)'}`,
                          background: selected ? '#dc2626' : 'transparent',
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
                      <span style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>{t}</span>
                    </button>
                  );
                })}
              </div>
              <div style={{ display: 'flex', gap: '8px' }}>
                <button onClick={dismiss} className="btn-ghost" style={{ flex: 1, fontSize: '13px', padding: '8px' }}>
                  Cancel
                </button>
                <button
                  onClick={() => setStep('details')}
                  disabled={checked === null}
                  style={{
                    flex: 2,
                    background: checked === null ? 'var(--bg-subtle)' : '#dc2626',
                    border: 'none',
                    borderRadius: 'var(--radius-md)',
                    padding: '8px',
                    fontSize: '13px',
                    color: checked === null ? 'var(--text-dim)' : '#fff',
                    cursor: checked === null ? 'default' : 'pointer',
                    transition: 'all var(--dur-fast)',
                  }}
                >
                  Next →
                </button>
              </div>
            </>
          )}

          {/* ── Step: details ── */}
          {step === 'details' && (
            <>
              <textarea
                value={comment}
                onChange={e => setComment(e.target.value)}
                placeholder="Describe what happened..."
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
                  marginBottom: '4px',
                  transition: 'border-color var(--dur-fast)',
                  boxSizing: 'border-box',
                }}
                onFocus={e => (e.currentTarget.style.borderColor = 'rgba(220,38,38,0.5)')}
                onBlur={e => (e.currentTarget.style.borderColor = 'var(--border)')}
              />
              {comment.length > 0 && comment.trim().length < 50 && (
                <p style={{ fontSize: '11px', color: '#dc2626', margin: '4px 0 12px' }}>
                  Please write at least 50 characters to describe the issue.
                </p>
              )}
              {(comment.length === 0 || comment.trim().length >= 50) && <div style={{ marginBottom: '12px' }} />}

              {/* Screenshot / video upload */}
              <input
                ref={fileRef}
                type="file"
                accept="image/*,video/*"
                multiple
                onChange={handleFileChange}
                style={{ display: 'none' }}
              />
              {screenshotPreviews.length > 0 && (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '6px', marginBottom: '8px' }}>
                  {screenshotPreviews.map((src, i) => (
                    <div key={i} style={{ position: 'relative' }}>
                      {screenshotTypes[i]?.startsWith('video/') ? (
                        <video
                          src={src}
                          style={{ width: '100%', height: '72px', objectFit: 'cover', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-light)' }}
                          muted
                          playsInline
                        />
                      ) : (
                        <img
                          src={src}
                          alt={`Attachment ${i + 1}`}
                          style={{ width: '100%', height: '72px', objectFit: 'cover', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-light)' }}
                        />
                      )}
                      <button
                        onClick={() => removeScreenshot(i)}
                        style={{
                          position: 'absolute',
                          top: '3px',
                          right: '3px',
                          background: 'rgba(15,23,42,0.7)',
                          border: 'none',
                          borderRadius: '50%',
                          width: '18px',
                          height: '18px',
                          color: '#fff',
                          fontSize: '12px',
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          lineHeight: 1,
                        }}
                      >
                        ×
                      </button>
                    </div>
                  ))}
                </div>
              )}
              {screenshots.length < 5 && (
                <button
                  onClick={() => fileRef.current?.click()}
                  style={{
                    width: '100%',
                    marginBottom: '14px',
                    padding: '10px',
                    background: 'var(--bg-subtle)',
                    border: '1px dashed var(--border-mid)',
                    borderRadius: 'var(--radius-md)',
                    fontSize: '12px',
                    color: 'var(--text-dim)',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    gap: '6px',
                    transition: 'all var(--dur-fast)',
                  }}
                  onMouseEnter={e => { e.currentTarget.style.background = 'var(--bg-input)'; e.currentTarget.style.borderColor = 'var(--border)'; }}
                  onMouseLeave={e => { e.currentTarget.style.background = 'var(--bg-subtle)'; e.currentTarget.style.borderColor = 'var(--border-mid)'; }}
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/>
                  </svg>
                  {screenshots.length === 0 ? 'Attach screenshots or videos (optional)' : `Add more (${screenshots.length}/5)`}
                </button>
              )}

              <div style={{ display: 'flex', gap: '8px' }}>
                <button onClick={() => setStep('topics')} className="btn-ghost" style={{ flex: 1, fontSize: '13px', padding: '8px' }}>
                  ← Back
                </button>
                <button
                  onClick={handleSubmit}
                  disabled={comment.trim().length < 50 || submitting}
                  style={{
                    flex: 2,
                    background: comment.trim().length < 50 || submitting ? 'var(--bg-subtle)' : '#dc2626',
                    border: 'none',
                    borderRadius: 'var(--radius-md)',
                    padding: '8px',
                    fontSize: '13px',
                    color: comment.trim().length < 50 || submitting ? 'var(--text-dim)' : '#fff',
                    cursor: comment.trim().length < 50 || submitting ? 'default' : 'pointer',
                    transition: 'all var(--dur-fast)',
                  }}
                >
                  {submitting ? 'Submitting...' : 'Submit Report'}
                </button>
              </div>
            </>
          )}

          {/* ── Done ── */}
          {step === 'done' && (
            <div style={{ textAlign: 'center', padding: '8px 0 4px' }}>
              <span style={{ fontSize: '32px' }}>🙏</span>
              <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '10px', lineHeight: 1.5 }}>
                Thanks for reporting! We&apos;ll look into this and work on a fix.
              </p>
            </div>
          )}
        </div>

        <style>{`
          @keyframes riFadeIn  { from { opacity: 0 } to { opacity: 1 } }
          @keyframes riFadeOut { from { opacity: 1 } to { opacity: 0 } }
          @keyframes riSlideIn { from { opacity: 0; transform: translate(-50%, calc(-50% + 16px)) } to { opacity: 1; transform: translate(-50%, -50%) } }
          @keyframes riSlideOut { from { opacity: 1; transform: translate(-50%, -50%) } to { opacity: 0; transform: translate(-50%, calc(-50% + 10px)) } }
        `}</style>
      </div>
    </>
  );
}
