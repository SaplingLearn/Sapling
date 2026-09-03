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
import { MONO } from '@/lib/landing/companionType';

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
        className="cp-shot"
        onClick={() => setOpen(true)}
        aria-label={`Expand ${title}`}
        style={{
          position: 'relative',
          width: '100%',
          aspectRatio: '16 / 10',
          borderRadius: radius,
          overflow: 'hidden',
          background: '#ebe6dc',
          border: '1px solid rgba(42,39,31,0.10)',
          boxShadow: '0 10px 28px -16px rgba(26,24,20,0.45)',
          padding: 0,
          cursor: 'pointer',
          display: 'block',
        }}
      >
        <Image src={src} alt="" fill sizes={sizes} style={{ objectFit: 'cover' }} />
        {route && (
          <span
            style={{
              position: 'absolute',
              left: 10,
              top: 10,
              padding: '4px 9px',
              borderRadius: 6,
              background: 'rgba(250,248,243,0.9)',
              backdropFilter: 'blur(4px)',
              fontFamily: MONO,
              fontSize: 9,
              letterSpacing: '0.14em',
              textTransform: 'uppercase',
              color: '#3f3b31',
            }}
          >
            {route}
          </span>
        )}
      </button>

      <Lightbox
        open={open}
        onClose={() => setOpen(false)}
        src={src}
        alt={alt}
        title={title}
        caption={caption}
        eyebrow={route}
      />
    </>
  );
}
