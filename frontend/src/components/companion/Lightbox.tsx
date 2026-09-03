'use client';

/**
 * Click-to-expand image viewer for the companion pages.
 *
 * The gallery cards and the wiki's illustrations are product screenshots
 * rendered at roughly a third of their captured size — legible as a thumbnail,
 * useless for actually reading the screen. This opens one at a size worth
 * looking at.
 *
 * Everything modal about it is `useOverlayBehaviour` (Dialog.tsx): portal,
 * scroll lock, focus trap, Escape, focus restore to whatever opened it. Only
 * the geometry and the palette are bespoke — those are the companion paper
 * tones, not the app shell's warm ones. Reusing the hook is the point: this is
 * the fourth overlay in the codebase and the first three already agree.
 *
 * The image is `contain`, never `cover`. A gallery card crops to 16:10 because
 * it is a card; an expanded view that crops is failing at its one job.
 */

import Image from 'next/image';
import { createPortal } from 'react-dom';

import { useOverlayBehaviour } from '@/components/Dialog';

import { MONO, SERIF } from '@/lib/landing/companionType';

export interface LightboxProps {
  open: boolean;
  onClose: () => void;
  src: string;
  /** Describes the screenshot for anyone who cannot see it. */
  alt: string;
  title: string;
  /** Optional second line — the gallery passes the card's own description. */
  caption?: string;
  /** Optional eyebrow, e.g. the route the screenshot was taken on. */
  eyebrow?: string;
}

export function Lightbox({ open, onClose, src, alt, title, caption, eyebrow }: LightboxProps) {
  const { mounted, visible, panelRef, onKeyDown } = useOverlayBehaviour({ open, onClose });

  if (!mounted || !open) return null;

  return createPortal(
    <div
      // The backdrop is the click-out target. `onPointerDown` rather than
      // onClick so a drag that STARTS on the image and releases on the
      // backdrop — selecting, or flinging the panel — does not count as a
      // click-out and close the thing mid-gesture.
      onPointerDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      onKeyDown={onKeyDown}
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 200,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 'clamp(16px, 4vw, 48px)',
        background: visible ? 'rgba(26,24,20,0.62)' : 'rgba(26,24,20,0)',
        backdropFilter: visible ? 'blur(6px)' : 'blur(0px)',
        WebkitBackdropFilter: visible ? 'blur(6px)' : 'blur(0px)',
        // The global prefers-reduced-motion reset in globals.css zeroes these,
        // so there is no media query here on purpose.
        transition: 'background 220ms ease, backdrop-filter 220ms ease',
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        style={{
          position: 'relative',
          width: 'min(1200px, 100%)',
          maxHeight: '100%',
          display: 'flex',
          flexDirection: 'column',
          gap: 14,
          outline: 'none',
          opacity: visible ? 1 : 0,
          transform: visible ? 'scale(1)' : 'scale(0.965)',
          transition: 'opacity 220ms ease, transform 260ms cubic-bezier(0.22, 1, 0.36, 1)',
        }}
      >
        <div
          style={{
            position: 'relative',
            width: '100%',
            aspectRatio: '16 / 10',
            maxHeight: '78vh',
            borderRadius: 14,
            overflow: 'hidden',
            background: '#ebe6dc',
            border: '1px solid rgba(42,39,31,0.14)',
            boxShadow: '0 30px 80px -30px rgba(12,20,16,0.7)',
          }}
        >
          <Image src={src} alt={alt} fill sizes="(max-width: 1240px) 92vw, 1200px" style={{ objectFit: 'contain' }} />
        </div>

        <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
          {eyebrow && (
            <span style={{ fontFamily: MONO, fontSize: 10, letterSpacing: '0.14em', textTransform: 'uppercase', color: '#cfc7b4' }}>
              {eyebrow}
            </span>
          )}
          <span style={{ fontSize: 15, fontWeight: 600, color: '#faf8f3', letterSpacing: '-0.01em' }}>{title}</span>
          {caption && (
            <span style={{ flexBasis: '100%', fontFamily: SERIF, fontSize: 14, lineHeight: 1.6, color: '#d9d3c6' }}>
              {caption}
            </span>
          )}
        </div>

        {/* Click-out is not discoverable, and is unavailable to keyboard and
            most touch users. Escape is handled by the hook; this is the
            visible affordance.

            Inset INSIDE the image rather than hung off the panel corner: at a
            6px overhang most of the button sat on the rounded corner, cutting
            the radius and reading as neither in nor out. A stroked glyph
            rather than the × character, which sits optically high in its line
            box and renders thin next to a screenshot. */}
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="cp-lightbox-close"
          style={{
            position: 'absolute',
            top: 12,
            right: 12,
            width: 32,
            height: 32,
            display: 'grid',
            placeItems: 'center',
            borderRadius: '50%',
            border: '1px solid rgba(250,248,243,0.22)',
            background: 'rgba(26,24,20,0.55)',
            backdropFilter: 'blur(6px)',
            WebkitBackdropFilter: 'blur(6px)',
            color: '#faf8f3',
            cursor: 'pointer',
            padding: 0,
          }}
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" aria-hidden="true">
            <path d="M5 5 19 19M19 5 5 19" />
          </svg>
        </button>
      </div>
    </div>,
    document.body,
  );
}
