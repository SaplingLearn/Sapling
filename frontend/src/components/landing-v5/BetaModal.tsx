'use client';

/**
 * Beta signup dialog.
 *
 * A departure from `Sapling Landing v5.dc.html`, added by request: the design
 * wires "Sign up for Beta Testing" to scroll down to the newsletter section
 * instead. Both entry points now open this.
 *
 * It shares `email`/`subscribed` with the inline newsletter through
 * `useLanding`, so signing up here also settles that section into its
 * subscribed state — one signup, not two places to do it.
 *
 * Built on the shared `Dialog`, which brings the portal, scroll lock, Escape,
 * focus restore and aria wiring. Only the contents and palette are local.
 */

import { useId, useRef } from 'react';
import Dialog from '@/components/Dialog';

const MONO: React.CSSProperties = { fontFamily: "'JetBrains Mono',monospace" };

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
  const inputRef = useRef<HTMLInputElement>(null);
  const headingId = useId();
  const valid = email.includes('@') && !subscribing;

  return (
    <Dialog
      open={open}
      onClose={onClose}
      labelledBy={headingId}
      size="md"
      padding="34px"
      // the field, not the close button, is what you came here to use
      initialFocusRef={inputRef}
    >
      {subscribed ? (
        <div style={{ textAlign: 'center', padding: '10px 4px 6px' }}>
          {/* carries headingId too — it is what `aria-labelledby` points at
              once the form is replaced by this state */}
          <h2 id={headingId} style={{ margin: 0, fontFamily: "'Playfair Display',serif", fontSize: 30, fontWeight: 600, color: '#12201A', lineHeight: 1.1 }}>
            You&rsquo;re on the <em style={{ color: '#0C5638' }}>tree.</em>
          </h2>
          <p style={{ margin: '10px 0 0', fontSize: 14, color: '#61726A', fontStyle: 'italic' }}>
            See you in the inbox · The Team
          </p>
          <button
            onClick={onClose}
            type="button"
            className="ld-btn-solid"
            style={{ marginTop: 22, background: '#0C5638', color: '#fff', border: 'none', borderRadius: 6, padding: '13px 26px', fontFamily: "'DM Sans',sans-serif", fontWeight: 600, fontSize: 14, cursor: 'pointer', transition: 'filter 200ms' }}
          >
            Close
          </button>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <span style={{ ...MONO, fontSize: 10, letterSpacing: '0.3em', textTransform: 'uppercase', color: '#0C5638' }}>
            Free through beta
          </span>

          <h2 id={headingId} style={{ margin: '14px 0 0', fontFamily: "'Playfair Display',serif", fontSize: 30, fontWeight: 600, lineHeight: 1.1, letterSpacing: '-0.02em', color: '#12201A' }}>
            Get a seat in the <em style={{ color: '#0C5638' }}>beta.</em>
          </h2>

          <p style={{ margin: '14px 0 0', fontSize: 14.5, lineHeight: 1.7, color: '#33443B' }}>
            Beta testers get every feature free while we build, and a say in what we build next.
            One letter a month, no spam. We&rsquo;re students too.
          </p>

          <form
            onSubmit={(e) => { e.preventDefault(); if (valid) onSubscribe(); }}
            style={{ marginTop: 24, display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}
          >
            <input
              ref={inputRef}
              value={email}
              onChange={(e) => onEmail(e.target.value)}
              disabled={subscribing}
              type="email"
              placeholder="you@school.edu"
              aria-label="Email address"
              className="ld-emailinput"
              style={{ flex: 1, minWidth: 200, background: '#fdfcf9', border: '1px solid rgba(18,32,26,0.14)', borderRadius: 6, padding: '13px 16px', fontFamily: "'DM Sans',sans-serif", fontSize: 14, color: '#12201A', outline: 'none' }}
            />
            <button
              type="submit"
              disabled={!valid}
              className="ld-btn-solid"
              style={{
                background: '#0C5638', color: '#fff', border: 'none', borderRadius: 6,
                padding: '13px 22px', fontFamily: "'DM Sans',sans-serif", fontWeight: 600,
                fontSize: 14, whiteSpace: 'nowrap',
                cursor: valid ? 'pointer' : 'not-allowed',
                opacity: valid ? 1 : 0.5,
                transition: 'filter 200ms, opacity 200ms',
              }}
            >
              {subscribing ? 'Signing you up…' : 'Join the list'}
            </button>
          </form>

          {error && (
            <p role="alert" style={{ margin: '12px 0 0', fontSize: 13, lineHeight: 1.5, color: '#9c4b48' }}>
              {error}
            </p>
          )}

          <p style={{ margin: '18px 0 0', ...MONO, fontSize: 10, letterSpacing: '0.15em', color: '#8B9A92' }}>
            * AVAILABLE EXCLUSIVELY TO BOSTON UNIVERSITY STUDENTS
          </p>
        </div>
      )}
    </Dialog>
  );
}
