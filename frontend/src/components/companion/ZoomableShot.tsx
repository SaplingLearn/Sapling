'use client';

/**
 * A product screenshot that expands when clicked.
 *
 * The clickable panel only — the caller keeps its own <figure> and caption, so
 * /gallery's grid card and /wiki's inline figure can lay out differently while
 * behaving identically.
 *
 * This exists because /wiki is a SERVER component (it exports `metadata`), so
 * it cannot hold the open/closed state a lightbox needs. Rather than convert a
 * whole reference page to a client component for one interaction, the client
 * boundary is drawn here, around the one element that needs it.
 *
 * Each instance owns its own state and renders its own Lightbox, which costs
 * nothing when closed — Lightbox returns null unless open, so twelve of these
 * mount twelve buttons and zero portals.
 */

import { useState } from 'react';
import Image from 'next/image';

import { Lightbox } from '@/components/companion/Lightbox';

export interface ZoomableShotProps {
  src: string;
  /** Screen-reader description. The caller's caption is usually the better one. */
  alt: string;
  title: string;
  /** Shown under the expanded image. */
  caption?: string;
  /** Route badge in the corner, and the expanded view's eyebrow. */
  route?: string;
  /** next/image sizes hint for the thumbnail. */
  sizes?: string;
  /** Corner radius, so a grid card and an inline figure can differ. */
  radius?: number;
}

export function ZoomableShot({
  src,
  alt,
  title,
  caption,
  route,
  sizes = '(max-width: 900px) 100vw, 33vw',
  radius = 14,
}: ZoomableShotProps) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button
        type="button"
        className="cp-shot relative w-full aspect-[16/10] overflow-hidden [background:#ebe6dc] border border-[rgba(42,39,31,0.10)] [box-shadow:0_10px_28px_-16px_rgba(26,24,20,0.45)] p-0 cursor-pointer block"
        onClick={() => setOpen(true)}
        aria-label={`Expand ${title}`}
        style={{ borderRadius: radius }}
      >
        <Image src={src} alt="" fill sizes={sizes} style={{ objectFit: 'cover' }} />
        {route && (
          <span
            className="absolute left-2.5 top-2.5 py-1 px-[9px] rounded-sm bg-[rgba(250,248,243,0.9)] [backdrop-filter:blur(4px)] font-sans text-xs text-ink-600"
          >
            {route}
          </span>
        )}
      </button>

      {/* Mounted only while open. Lightbox calls onClose at the END of its exit
          animation, so unmounting here does not cut the exit off — and a fresh
          instance per open means its exit state cannot survive into the next
          one. Keeping it permanently mounted is what made a reopened shot
          close itself after ~180ms. */}
      {open && (
        <Lightbox
          open
          onClose={() => setOpen(false)}
          src={src}
          alt={alt}
          title={title}
          caption={caption}
          eyebrow={route}
        />
      )}
    </>
  );
}
