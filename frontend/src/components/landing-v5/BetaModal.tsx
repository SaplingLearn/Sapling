'use client';

/**
 * Beta waitlist dialog.
 *
 * This is the modal the previous landing page shipped — recovered rather than
 * reinvented: a two-column card, brand and beta-tester panel on the left,
 * waitlist signup on the right. It used to lead with the newsletter, but
 * the address lands in `newsletter_emails`, which is the beta waitlist
 * (admins grant access from it via /api/admin/allowlist/approve). So the
 * dialog leads with the waitlist, and the newsletter is the footnote.
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
import { SaplingWordmark } from '@/components/SaplingWordmark';
import { HeroCard } from '@/components/marketing/HeroCard';
import { useScrollLock } from '@/lib/useScrollLock';
import { cn } from "@/lib/cn";

/** The three perks of being on the list, each with its own accent dot.
 *  Waitlist perks first, the newsletter's last — phones show only the
 *  first two. */
const PERKS = [
  { dot: '#445D22', title: 'New features, first.', body: 'Every study mode, knowledge tool, and capability before anyone else sees it.' },
  { dot: '#8A63D2', title: 'Your input shapes what we build.', body: 'Early polls, roadmap previews, and a direct line to the people building it.' },
  { dot: '#D97706', title: 'Real notes from the team.', body: "What we're figuring out as we build. Honest, occasional, and worth opening." },
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
        className={cn(`fixed inset-0 z-[100] flex items-center justify-center p-4 ${closing ? 'modal-backdrop-out' : 'modal-backdrop-in'}`, "[background:rgba(12,18,26,0.45)]")}
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
          <h2 id={labelId} className="m-0 font-serif text-5xl leading-[1.1] font-semibold tracking-[-0.02em] text-[#1a1a1a]">
            You&apos;re on the <span className="italic text-brand-forest">waitlist.</span>
          </h2>
          <p className="mt-2.5 mx-0 mb-0 text-[17px] text-[#4b5563] italic">
            We&apos;ll be in touch when your spot opens - The Team
          </p>
        </HeroCard>
      </div>
    );
  }

  // ── form ──
  return (
    <div
      className={cn(`fixed inset-0 z-[100] flex items-center justify-center p-4 ${closing ? 'modal-backdrop-out' : 'modal-backdrop-in'}`, "[background:rgba(12,18,26,0.65)]")}
      onClick={dismiss}
    >
      <HeroCard
        className={`relative w-full ld-betacard ${closing ? 'modal-card-out' : 'modal-card-in'}`}
        style={{
          maxWidth: 'min(1040px, 94vw)', width: '100%',
          display: 'grid', gridTemplateColumns: '1fr 1px 1fr',
          minHeight: 560, maxHeight: 'calc(100vh - 48px)', overflow: 'hidden',
        }}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelId}
      >
        <button
          onClick={dismiss}
          aria-label="Close dialog"
          className="ld-betaclose absolute top-4.5 right-4.5 z-10 w-8 h-8 rounded-lg flex items-center justify-center text-[#4b5563] text-[20px] leading-none [background:none] border-0 cursor-pointer [transition:background_0.15s]"
        >
          ×
        </button>

        {/* ── left: brand + beta tester role ── */}
        <div className="hero-surface ld-beta-left pt-9 px-9 pb-8 flex flex-col gap-5.5">
          <SaplingWordmark width={88} />

          <div>
            <div className="font-sans text-[12.5px] text-[#6b7280] mb-3.5 font-semibold">
              Early access
            </div>
            <h2 className="m-0 font-serif text-[44px] leading-[1.05] font-bold text-[#1a1a1a] tracking-[-0.02em]">
              Learn early.<br />
              <span className="italic font-extrabold text-brand-forest font-serif">Grow</span> with us.
            </h2>
            <p className="mt-3.5 mx-0 mb-0 text-[13.5px] leading-[1.55] text-[#4b5563] max-w-90">
              Sapling is being built alongside the students who&apos;ll use it most. Join early and
              help shape what it becomes.
            </p>
          </div>

          <div className="h-px shrink-0 bg-[rgba(107,114,128,0.15)]" />

          <div>
            <h3 className="mt-0 mx-0 mb-3 font-serif text-2xl font-bold text-[#1a1a1a] tracking-[-0.02em]">
              Beta Tester Role
            </h3>
            <div className="rounded-[12px] px-4 py-3 flex items-center gap-3 bg-ink-100 border border-[#D6D1C6]">
              <div className="w-11 h-11 rounded-full flex items-center justify-center flex-shrink-0 bg-[#374151] text-md font-bold text-accent-fg font-sans tracking-[0.02em]">
                AK
              </div>
              <div className="flex flex-col gap-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-base font-bold text-[#111827] font-sans">Alex Kim</span>
                  <span
                    className="inline-flex items-center py-[3px] px-2.5 rounded-full text-sm font-medium font-sans bg-[rgba(212,175,55,0.08)] text-[#C9A227] border-[1.5px] border-[rgba(212,175,55,0.55)]"
                  >
                    Beta Tester
                  </span>
                </div>
                <span className="text-xs text-[#9CA3AF] font-sans">@alexkim</span>
              </div>
            </div>
            <p className="mt-2.5 mx-0.5 mb-0 text-[12.5px] text-[#6b7280] leading-[1.5] italic">
              The first mark on your profile. A permanent record of showing up early.
            </p>
          </div>
        </div>

        <div className="ld-beta-divider [background:rgba(107,114,128,0.15)] self-stretch" />

        {/* ── right: newsletter ── */}
        <div className="hero-surface ld-beta-right pt-11 px-10.5 pb-9 flex flex-col">
          <h1 id={labelId} className="ld-beta-title m-0 font-serif text-[48px] leading-[1.05] font-semibold tracking-[-0.025em] text-[#1a1a1a]">
            Join the{' '}
            <span className="italic font-extrabold text-brand-forest font-serif">Waitlist</span>
          </h1>
          <p className="mt-3.5 mx-0 mb-0 text-[15px] text-[#4b5563] leading-[1.5]">
            Leave your email and we&apos;ll let you in when your spot opens.
          </p>

          <div className="ld-beta-perks mt-7 flex flex-col gap-4">
            {PERKS.map(({ dot, title, body }) => (
              <div key={title} className="grid grid-cols-[auto_1fr] gap-3 [align-items:start]">
                <div className="w-2 h-2 rounded-[50%] mt-2 shrink-0" style={{ background: dot, boxShadow: `0 0 8px ${dot}55` }} />
                <div>
                  <div className="text-[14.5px] font-semibold text-[#1a1a1a] mb-0.5 tracking-[-0.005em]">{title}</div>
                  <div className="text-[12.5px] text-[#4b5563] leading-[1.5]">{body}</div>
                </div>
              </div>
            ))}
          </div>

          <form onSubmit={submit} className="ld-beta-form mt-auto pt-7">
            <div className="relative mb-2.5">
              <input
                ref={inputRef}
                type="text"
                aria-label="Email address"
                placeholder="you@example.com"
                value={email}
                disabled={subscribing}
                onChange={(e) => { onEmail(e.target.value); setLocalError(''); }}
                className="ld-betainput w-full py-3.5 px-4 text-base [background:rgba(255,255,255,0.6)] border-[1.5px] border-[rgba(107,114,128,0.25)] rounded-md [transition:border-color_0.15s,_box-shadow_0.15s] font-sans text-[#1a1a1a] box-border"
              />
              {(localError || error) && (
                <p role="alert" className="mt-1.5 mx-0 mb-0 text-[11.5px] text-[#dc2626] font-sans">
                  {localError || error}
                </p>
              )}
            </div>
            <button
              type="submit"
              disabled={subscribing}
              className={cn("ld-betasubmit", "w-full py-3.5 px-4 rounded-md text-accent-fg text-base font-semibold tracking-[0.02em] [box-shadow:0_8px_24px_rgba(68,93,34,0.3)] border-0 [transition:all_0.18s] flex items-center justify-center gap-2 font-sans", subscribing ? "[background:#4b5563]" : "[background:var(--brand-forest)]", subscribing ? "cursor-default" : "cursor-pointer")}
            >
              {subscribing ? 'Planting your node…' : <>Join the Waitlist <span className="opacity-70">→</span></>}
            </button>
            <p className="mt-3 mx-0 mb-0 text-[11.5px] text-[#6b7280] text-center leading-[1.5]">
              You&apos;ll also get our occasional newsletter while you wait.
            </p>
          </form>
        </div>
      </HeroCard>
    </div>
  );
}
