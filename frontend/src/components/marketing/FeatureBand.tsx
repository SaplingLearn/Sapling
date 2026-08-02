/**
 * A full-width feature band: one recreated product surface on one side, the
 * claim on the other (#344 step 2, spec sections 2/3/5).
 *
 * Purely presentational. It owns three things and nothing else:
 *
 *  1. **The alternation.** `surfaceSide` decides which column the surface lands
 *     in at ≥ 900px. The DOM order is always copy-then-surface — a screen
 *     reader and every phone get the claim before the illustration of it, and
 *     the desktop flip is a `grid-column` swap, not a source reorder.
 *  2. **Atmospheric continuity.** The hero, the graph section and the CTA all
 *     carry mesh blobs; three bands and a bento between the last two would
 *     otherwise be a flat hole in the middle of the page, and the cut in and out
 *     of it reads as a seam. One low-opacity blob per band, parked behind the
 *     COPY column (never behind the surface, which has to stay crisp).
 *  3. **The type ramp.** Mono eyebrow → Playfair headline → DM Sans body, the
 *     same three-step the graph section above it uses.
 *
 * No motion of its own. The entrance is the page's existing `.landing-fade-up`
 * (an IntersectionObserver in `(public)/page.tsx` that strips the opacity class
 * on first intersect) — which means with JS off, or an observer that never
 * fires, the band renders complete rather than invisible, and the global
 * `prefers-reduced-motion` reset in globals.css collapses the transition.
 */
import type { ReactNode } from 'react';

/** Which column the product surface occupies on a wide viewport. */
export type BandSide = 'left' | 'right';

export interface FeatureBandProps {
  /** Anchor id + testid suffix, e.g. `upload`. */
  id: string;
  /** Mono micro-label. Title Case; rendered uppercase by CSS. */
  eyebrow: string;
  /** The claim. Playfair, one or two lines. */
  headline: string;
  /** One sentence under it. Addresses the student as "you". */
  body: string;
  /** The recreated product surface. */
  surface: ReactNode;
  surfaceSide: BandSide;
}

export default function FeatureBand({
  id,
  eyebrow,
  headline,
  body,
  surface,
  surfaceSide,
}: FeatureBandProps) {
  const blobSide = surfaceSide === 'left' ? { right: '-12%' } : { left: '-12%' };

  return (
    <section
      id={`band-${id}`}
      data-testid={`landing-band-${id}`}
      data-surface-side={surfaceSide}
      aria-labelledby={`band-${id}-headline`}
      className="landing-section landing-band relative z-10"
    >
      <div aria-hidden className="absolute inset-0 pointer-events-none z-0">
        <div
          className={`sapling-mesh-blob sapling-mesh-blob--${surfaceSide === 'left' ? '2' : '3'}`}
          style={{
            top: '8%',
            bottom: 'auto',
            width: '30vw',
            height: '30vw',
            opacity: 0.16,
            ...blobSide,
          }}
        />
      </div>

      <div
        className={`landing-band-grid landing-band--surface-${surfaceSide} relative z-[1] max-w-7xl mx-auto px-6 lg:px-12 landing-fade-up`}
      >
        <div className="landing-band-copy">
          <span className="landing-eyebrow" data-testid={`landing-band-${id}-eyebrow`}>
            {eyebrow}
          </span>
          <h2 id={`band-${id}-headline`} className="landing-band-headline">
            {headline}
          </h2>
          <p className="landing-band-body">{body}</p>
        </div>

        <div className="landing-band-surface">{surface}</div>
      </div>
    </section>
  );
}
