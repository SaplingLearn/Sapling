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

import { useCallback, useEffect, useState } from 'react';
import Image from 'next/image';
import { createPortal } from 'react-dom';

import { useOverlayBehaviour } from '@/components/Dialog';

import { cn } from "@/lib/cn";

/** Exit animation duration. Keep in step with globals.css. */
const EXIT_MS = 180;

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
  /**
   * Closing runs an exit animation before the parent unmounts us.
   *
   * The parent closes by dropping this component from the tree, so without an
   * exit phase the panel simply vanishes. `requestClose` starts the animation
   * instead, and the real `onClose` fires when it ends. Every dismissal goes
   * through it — backdrop, Escape (via the hook), and the button — so there is
   * one exit path rather than three.
   */
  const [closing, setClosing] = useState(false);
  const requestClose = useCallback(() => setClosing(true), []);

  // A timer rather than onAnimationEnd, deliberately. The panel renders
  // through a portal, and a synthesized `animationend` does not reach React's
  // handler there (jsdom has no AnimationEvent at all, so it cannot even be
  // tested) — and an animation that never runs, as in a backgrounded tab,
  // emits no event, which would leave the viewer unclosable. A timer has none
  // of that: it always fires, and it is trivially testable.
  //
  // MUST match the .cp-lightbox-panel--closing duration in globals.css. A few
  // ms of slack so the last frame paints before the node goes.
  useEffect(() => {
    // `open` as well as `closing`: a closed instance must never hold a pending
    // close. Callers are expected to mount this only while open (see
    // ZoomableShot) so the exit state cannot leak between opens — this guard
    // is the belt to that braces.
    if (!open || !closing) return;
    const t = setTimeout(onClose, EXIT_MS);
    return () => clearTimeout(t);
  }, [open, closing, onClose]);

  // `visible` is deliberately unused: the entrance is a CSS keyframe on
  // insertion, not a transition driven by that flag. See .cp-lightbox in
  // globals.css for why.
  const { mounted, panelRef, onKeyDown } = useOverlayBehaviour({
    open,
    onClose: requestClose,
  });

  if (!mounted || !open) return null;

  return createPortal(
    <div
      // The backdrop is the click-out target. `onPointerDown` rather than
      // onClick so a drag that STARTS on the image and releases on the
      // backdrop — selecting, or flinging the panel — does not count as a
      // click-out and close the thing mid-gesture.
      onPointerDown={(e) => {
        if (e.target === e.currentTarget) requestClose();
      }}
      onKeyDown={onKeyDown}
      className={cn(`cp-lightbox${closing ? ' cp-lightbox--closing' : ''}`, "fixed inset-0 z-200 flex items-center justify-center p-[clamp(16px,_4vw,_48px)] [background:rgba(26,24,20,0.62)] [backdrop-filter:blur(6px)] [-webkit-backdrop-filter:blur(6px)]")}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        className={cn(`cp-lightbox-panel${closing ? ' cp-lightbox-panel--closing' : ''}`, "relative w-[min(1200px,_100%)] max-h-full flex flex-col gap-3.5 outline-none")}
      >
        <div
          className="relative w-full aspect-[16/10] max-h-[78vh] rounded-[14px] overflow-hidden bg-ink-100 border border-[rgba(42,39,31,0.14)] [box-shadow:0_30px_80px_-30px_rgba(12,20,16,0.7)]"
        >
          <Image src={src} alt={alt} fill sizes="(max-width: 1240px) 92vw, 1200px" style={{ objectFit: 'contain' }} />
        </div>

        <div className="flex items-baseline gap-3 flex-wrap">
          {eyebrow && (
            <span className="font-sans text-sm text-[#cfc7b4]">
              {eyebrow}
            </span>
          )}
          <span className="text-[15px] font-semibold text-ink-0 tracking-[-0.01em]">{title}</span>
          {caption && (
            <span className="basis-full font-serif text-base leading-[1.6] text-[#d9d3c6]">
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
          onClick={requestClose}
          aria-label="Close"
          className="cp-lightbox-close absolute top-3 right-3 w-8 h-8 grid place-items-center rounded-[50%] border border-[rgba(250,248,243,0.22)] [background:rgba(26,24,20,0.55)] [backdrop-filter:blur(6px)] [-webkit-backdrop-filter:blur(6px)] text-ink-0 cursor-pointer p-0"
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
