'use client';

/**
 * Beta access + newsletter dialog.
 *
 * This is the modal the previous landing page shipped — recovered rather than
 * reinvented, so what runs here is what has been on staging: a two-column
 * card, brand and beta-tester panel on the left, newsletter pitch and signup
 * on the right.
 *
 * A departure from `Sapling Landing v5.dc.html`, which wires both beta CTAs
 * to scroll down to the newsletter section instead. Requested.
 *
 * Not built on the shared `Dialog`: that caps at 760px (`size="xl"`) and this
 * card is `min(1040px, 94vw)` with a two-column grid. The behaviour `Dialog`
 * would have brought — scroll lock, Escape, focus move, `aria-modal` — is
 * wired explicitly below instead.
 *
 * One behavioural change from the original: it POSTed and then showed success
 * unconditionally, swallowing failures in an empty `catch`. Submission now
 * goes through `useLanding`'s `subscribe`, which only reports success on a
 * 2xx and surfaces a readable message otherwise.
 */

import { useEffect, useId, useRef, useState } from 'react';
import Image from 'next/image';
import { HeroCard } from '@/components/marketing/HeroCard';
import { useScrollLock } from '@/lib/useScrollLock';

const PLAYFAIR = "var(--font-playfair), 'Playfair Display', Georgia, serif";
const SPECTRAL = "var(--font-spectral), 'Spectral', Georgia, serif";
const JETBRAINS = "var(--font-jetbrains), 'JetBrains Mono', monospace";
const DM = "var(--font-dm-sans), 'DM Sans', sans-serif";

/** The three newsletter perks, each with its own accent dot. */
const PERKS = [
  { dot: '#1B6C42', title: 'New features, first.', body: 'Every study mode, knowledge tool, and capability before anyone else sees it.' },
  { dot: '#D97706', title: 'Real notes from the team.', body: "What we're figuring out as we build. Honest, occasional, and worth opening." },
  { dot: '#8A63D2', title: 'Your input shapes what we build.', body: 'Early polls, roadmap previews, and a direct line to the people building it.' },
];

export function BetaModal({
  open,
  email,
  subscribed,
  subscribing,
  error,
  onEmail,
  onSubscribe,
  onClose,
}: {
  open: boolean;
  email: string;
  subscribed: boolean;
  subscribing: boolean;
  error: string | null;
  onEmail: (v: string) => void;
  onSubscribe: () => void;
  onClose: () => void;
}) {
  const [closing, setClosing] = useState(false);
  const [localError, setLocalError] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const labelId = useId();

  useScrollLock(open);

  // play the exit animation before unmounting, and never close mid-request
  const dismiss = () => {
    if (subscribing) return;
    setClosing(true);
    setTimeout(() => { setClosing(false); setLocalError(''); onClose(); }, 200);
  };

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') dismiss(); };
    document.addEventListener('keydown', onKey);
    const t = setTimeout(() => inputRef.current?.focus(), 60);
    return () => { document.removeEventListener('keydown', onKey); clearTimeout(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, subscribing]);

  if (!open) return null;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = email.trim();
    const [local, domain] = trimmed.split('@');
    if (!local || !domain || !domain.includes('.')) {
      setLocalError('Enter a valid email (e.g. you@example.com)');
      return;
    }
    setLocalError('');
    onSubscribe();
  };

  // ── success ──
  if (subscribed) {
    return (
      <div
        className={`fixed inset-0 z-[100] flex items-center justify-center p-4 ${closing ? 'modal-backdrop-out' : 'modal-backdrop-in'}`}
        style={{ background: 'rgba(12,18,26,0.45)' }}
        onClick={dismiss}
      >
        <HeroCard
          className={closing ? 'modal-card-out' : 'modal-card-in'}
          style={{ padding: '40px 52px', textAlign: 'center' }}
          onClick={(e) => e.stopPropagation()}
          role="dialog"
          aria-modal="true"
          aria-labelledby={labelId}
        >
          <h2 id={labelId} style={{ margin: 0, fontFamily: PLAYFAIR, fontSize: 32, lineHeight: 1.1, fontWeight: 600, letterSpacing: '-0.02em', color: '#1a1a1a' }}>
            You&apos;re on the <span style={{ fontStyle: 'italic', color: 'var(--brand-forest)' }}>tree.</span>
          </h2>
          <p style={{ margin: '10px 0 0', fontSize: 17, color: '#4b5563', fontStyle: 'italic' }}>
            See you in the inbox - The Team
          </p>
        </HeroCard>
      </div>
    );
  }

  // ── form ──
  return (
    <div
      className={`fixed inset-0 z-[100] flex items-center justify-center p-4 ${closing ? 'modal-backdrop-out' : 'modal-backdrop-in'}`}
      style={{ background: 'rgba(12,18,26,0.65)' }}
      onClick={dismiss}
    >
      {/*
        Below `md` this collapses to one column and scrolls. The unconditional
        `1fr 1px 1fr` with `min-height:560px` + `overflow:hidden` squeezed both
        columns to ~45vw on a phone and CLIPPED the taller one, so the email
        field and the submit button could sit outside the visible card with no
        way to reach them. `min-h` is therefore also gated to `md` and up.
      */}
      <HeroCard
        className={`relative w-full grid grid-cols-1 md:grid-cols-[1fr_1px_1fr] md:min-h-[560px] overflow-y-auto ${closing ? 'modal-card-out' : 'modal-card-in'}`}
        style={{
          maxWidth: 'min(1040px, 94vw)', width: '100%',
          maxHeight: 'calc(100vh - 48px)',
        }}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelId}
      >
        <button
          onClick={dismiss}
          aria-label="Close dialog"
          className="ld-betaclose"
          style={{
            position: 'absolute', top: 18, right: 18, zIndex: 10,
            width: 32, height: 32, borderRadius: 16,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: '#4b5563', fontSize: 20, lineHeight: 1,
            background: 'none', border: 'none', cursor: 'pointer',
            transition: 'background 0.15s',
          }}
        >
          ×
        </button>

        {/* ── left: brand + beta tester role ── */}
        <div className="hero-surface" style={{ padding: '36px 36px 32px', display: 'flex', flexDirection: 'column', gap: 22 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <Image src="/sapling-icon.svg" alt="Sapling" width={22} height={22} />
            <span style={{ fontFamily: SPECTRAL, fontWeight: 700, fontSize: 17, color: 'var(--brand-forest)', letterSpacing: '-0.02em' }}>Sapling</span>
          </div>

          <div>
            <div style={{ fontFamily: JETBRAINS, fontSize: 10.5, color: '#6b7280', letterSpacing: '0.22em', marginBottom: 14, textTransform: 'uppercase', fontWeight: 600 }}>
              Early access
            </div>
            <h2 style={{ margin: 0, fontFamily: PLAYFAIR, fontSize: 44, lineHeight: 1.05, fontWeight: 700, color: '#1a1a1a', letterSpacing: '-0.02em' }}>
              Learn early.<br />
              <span style={{ fontStyle: 'italic', fontWeight: 800, color: 'var(--brand-forest)', fontFamily: PLAYFAIR }}>Grow</span> with us.
            </h2>
            <p style={{ margin: '14px 0 0', fontSize: 13.5, lineHeight: 1.55, color: '#4b5563', maxWidth: 360 }}>
              Sapling is being built alongside the students who&apos;ll use it most. Join early and
              help shape what it becomes.
            </p>
          </div>

          <div style={{ height: 1, flexShrink: 0, background: 'rgba(107,114,128,0.15)' }} />

          <div>
            <h3 style={{ margin: '0 0 12px', fontFamily: PLAYFAIR, fontSize: 22, fontWeight: 700, color: '#1a1a1a', letterSpacing: '-0.02em' }}>
              Beta Tester Role
            </h3>
            <div className="rounded-xl px-4 py-3 flex items-center gap-3" style={{ background: '#EBE6DC', border: '1px solid #D6D1C6' }}>
              <div className="w-11 h-11 rounded-full flex items-center justify-center flex-shrink-0" style={{ background: '#374151', fontSize: 13, fontWeight: 700, color: '#fff', fontFamily: DM, letterSpacing: '0.02em' }}>
                AK
              </div>
              <div className="flex flex-col gap-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span style={{ fontSize: 14, fontWeight: 700, color: '#111827', fontFamily: DM }}>Alex Kim</span>
                  <span
                    style={{
                      display: 'inline-flex', alignItems: 'center', padding: '3px 10px',
                      borderRadius: 9999, fontSize: 10, fontWeight: 500, fontFamily: JETBRAINS,
                      letterSpacing: '0.1em', textTransform: 'uppercase',
                      background: 'rgba(212,175,55,0.08)', color: '#C9A227',
                      border: '1.5px solid rgba(212,175,55,0.55)',
                    }}
                  >
                    Beta Tester
                  </span>
                </div>
                <span style={{ fontSize: 11, color: '#9CA3AF', fontFamily: DM }}>@alexkim</span>
              </div>
            </div>
            <p style={{ margin: '10px 2px 0', fontSize: 12.5, color: '#6b7280', lineHeight: 1.5, fontStyle: 'italic' }}>
              The first mark on your profile. A permanent record of showing up early.
            </p>
          </div>
        </div>

        {/*
          The divider column. In the single-column layout it flattens into a
          1px horizontal rule between the two panes, which is the right
          reading of it there — hence no responsive handling.
        */}
        <div style={{ background: 'rgba(107,114,128,0.15)', alignSelf: 'stretch', minHeight: 1 }} />

        {/* ── right: newsletter ── */}
        <div className="hero-surface" style={{ padding: '44px 42px 36px', display: 'flex', flexDirection: 'column' }}>
          <div style={{ fontFamily: JETBRAINS, fontSize: 10, color: '#D97706', letterSpacing: '0.3em', textTransform: 'uppercase', fontWeight: 500, marginBottom: 10 }}>
            ● Issue 001 dropping soon
          </div>
          <h1 id={labelId} style={{ margin: 0, fontFamily: PLAYFAIR, fontSize: 48, lineHeight: 1.05, fontWeight: 600, letterSpacing: '-0.025em', color: '#1a1a1a' }}>
            Join the<br />
            <span style={{ fontStyle: 'italic', fontWeight: 800, color: 'var(--brand-forest)', fontFamily: PLAYFAIR }}>Newsletter</span>
          </h1>
          <p style={{ margin: '14px 0 0', fontSize: 15, color: '#4b5563', lineHeight: 1.5 }}>
            Hear fun stories from students like you.
          </p>

          <div style={{ marginTop: 28, display: 'flex', flexDirection: 'column', gap: 16 }}>
            {PERKS.map(({ dot, title, body }) => (
              <div key={title} style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: 12, alignItems: 'start' }}>
                <div style={{ width: 8, height: 8, borderRadius: '50%', background: dot, boxShadow: `0 0 8px ${dot}55`, marginTop: 8, flexShrink: 0 }} />
                <div>
                  <div style={{ fontSize: 14.5, fontWeight: 600, color: '#1a1a1a', marginBottom: 2, letterSpacing: '-0.005em' }}>{title}</div>
                  <div style={{ fontSize: 12.5, color: '#4b5563', lineHeight: 1.5 }}>{body}</div>
                </div>
              </div>
            ))}
          </div>

          <form onSubmit={submit} style={{ marginTop: 'auto', paddingTop: 28 }}>
            <div style={{ position: 'relative', marginBottom: 10 }}>
              <input
                ref={inputRef}
                // Was `type="text"` while labelled and validated as an email:
                // no keyboard hint on mobile, no browser autofill, no native
                // format check.
                type="email"
                autoComplete="email"
                inputMode="email"
                aria-label="Email address"
                placeholder="you@example.com"
                value={email}
                disabled={subscribing}
                onChange={(e) => { onEmail(e.target.value); setLocalError(''); }}
                className="ld-betainput"
                style={{
                  width: '100%', padding: '14px 16px', fontSize: 14,
                  background: 'rgba(255,255,255,0.6)',
                  border: '1.5px solid rgba(107,114,128,0.25)', borderRadius: 10,
                  transition: 'border-color 0.15s, box-shadow 0.15s',
                  fontFamily: DM, color: '#1a1a1a', boxSizing: 'border-box',
                }}
              />
              {(localError || error) && (
                <p role="alert" style={{ margin: '6px 0 0', fontSize: 11.5, color: '#dc2626', fontFamily: DM }}>
                  {localError || error}
                </p>
              )}
            </div>
            <button
              type="submit"
              disabled={subscribing}
              className="ld-betasubmit"
              style={{
                width: '100%', padding: '14px 16px', borderRadius: 10,
                background: subscribing ? '#4b5563' : 'var(--brand-forest)', color: '#fff',
                fontSize: 14, fontWeight: 600, letterSpacing: '0.02em',
                boxShadow: '0 8px 24px rgba(27,108,66,0.3)',
                border: 'none', cursor: subscribing ? 'default' : 'pointer',
                transition: 'all 0.18s', display: 'flex', alignItems: 'center',
                justifyContent: 'center', gap: 8, fontFamily: DM,
              }}
            >
              {subscribing ? 'Planting your node…' : <>Sign Me Up <span style={{ opacity: 0.7 }}>→</span></>}
            </button>
            <p style={{ margin: '12px 0 0', fontSize: 11.5, color: '#6b7280', textAlign: 'center', lineHeight: 1.5 }}>
              By joining the newsletter, you&apos;ll also be added to the beta waitlist.
            </p>
          </form>
        </div>
      </HeroCard>
    </div>
  );
}
