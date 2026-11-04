'use client';

import { LeafI } from './LeafI';

/**
 * Loading overlay — the hand-tuned intro lockup.
 *
 * Ported from `Sapling Landing v5.dc.html`. The sequence is causal and the
 * ordering is the whole point: the wordmark sets context first, the stem
 * grows upward, then each leaf unfurls from the joint the stem has already
 * passed, and the rule sweeps out last to close the lockup.
 *
 * All five animations are 2.4s with `both` fill and differ only in their
 * keyframe offsets — see the s1* keyframes in globals.css, whose
 * per-keyframe timing functions give the leaves their weight.
 *
 * v5 adds the LOADING readout under the rule. It is honest about being
 * decorative: nothing is actually being measured, and the counter is
 * driven by `useLanding`'s ragged +4..+12 tick rather than real progress.
 */

export function IntroOverlay({
  heroMounted,
  introGone,
  loadPct,
}: {
  heroMounted: boolean;
  introGone: boolean;
  loadPct: number;
}) {
  return (
    <div
      aria-hidden="true"
      style={{
        position: 'fixed', inset: 0, zIndex: 60,
        // dropped from the layout entirely once the fade has finished, so it
        // can never intercept a pointer or cost a paint
        display: introGone ? 'none' : 'flex',
        alignItems: 'center', justifyContent: 'center',
        backgroundColor: '#f2f4f0',
        backgroundImage:
          'radial-gradient(ellipse 100% 70% at 50% 30%, rgba(255,255,255,0.9) 0%, transparent 62%)',
        transition: 'opacity 700ms cubic-bezier(0.22,1,0.36,1)',
        opacity: heroMounted ? 0 : 1,
        pointerEvents: heroMounted ? 'none' : 'auto',
      }}
    >
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
        {/* The watercolor sprout (public/sapling-icon.svg, the favicon), drawn
            in place so its parts can animate. Ids are prefixed: this SVG is
            inline in the page, so they share one id namespace with it. */}
        <svg width="86" height="86" viewBox="0 0 64 64" fill="none" style={{ display: 'block', overflow: 'visible' }}>
          <defs>
            <filter id="introCut" x="-25%" y="-25%" width="150%" height="150%">
              <feTurbulence type="fractalNoise" baseFrequency="0.09" numOctaves={3} seed={4} result="n" />
              <feDisplacementMap in="SourceGraphic" in2="n" scale={1.6} xChannelSelector="R" yChannelSelector="G" />
            </filter>
            <filter id="introCut2" x="-25%" y="-25%" width="150%" height="150%">
              <feTurbulence type="fractalNoise" baseFrequency="0.11" numOctaves={3} seed={9} result="n" />
              <feDisplacementMap in="SourceGraphic" in2="n" scale={1.4} xChannelSelector="R" yChannelSelector="G" />
            </filter>
            <linearGradient id="introLeafL" x1="0" y1="18" x2="0" y2="46" gradientUnits="userSpaceOnUse">
              <stop offset="0" stopColor="#C5D8B2" /><stop offset="0.5" stopColor="#85A165" stopOpacity="0.95" /><stop offset="1" stopColor="#5B753B" />
            </linearGradient>
            <linearGradient id="introLeafR" x1="0" y1="10" x2="0" y2="40" gradientUnits="userSpaceOnUse">
              <stop offset="0" stopColor="#E1ECD7" /><stop offset="0.5" stopColor="#A4BD89" stopOpacity="0.95" /><stop offset="1" stopColor="#6A8549" />
            </linearGradient>
            <linearGradient id="introStem" x1="0" y1="28" x2="0" y2="54" gradientUnits="userSpaceOnUse">
              <stop offset="0" stopColor="#A4BD89" /><stop offset="1" stopColor="#5B753B" />
            </linearGradient>
          </defs>
          {/* stem: bends right at the crown and continues up into the right leaf */}
          <path
            d="M37.5 24.6 C38.3 24.2 39 24.8 38.8 25.6 C38.6 26.2 38 26.6 37.4 27 C35.9 27.9 34.4 29.3 33.7 31.2 C33.2 34.5 33.3 38.5 33.4 42.8 C33.5 46.6 33.7 50.2 33.5 53.7 C33.4 55.2 32.7 56.1 31.9 56 C31 55.9 30.6 55 30.7 53.6 C30.9 49.9 30.8 46 30.8 42 C30.9 37.9 30.8 34 31 30.8 C31.4 28.2 33.1 26.3 35.2 25.4 C36 25 36.8 24.8 37.5 24.6Z"
            fill="url(#introStem)"
            style={{ animation: 's1Stem 2.4s cubic-bezier(0.25,0.6,0.2,1) both' }}
          />
          <path
            d="M32 38 C32 38 18 34 16 22 C16 22 30 20 32 38Z" fill="url(#introLeafL)" filter="url(#introCut)"
            style={{
              transformBox: 'fill-box', transformOrigin: '100% 100%',
              animation: 's1LeafLo 2.4s linear both',
            }}
          />
          <path
            d="M32 30 C32 30 46 24 50 12 C50 12 36 12 32 30Z" fill="url(#introLeafR)" filter="url(#introCut2)"
            style={{
              transformBox: 'fill-box', transformOrigin: '0% 100%',
              animation: 's1LeafHi 2.4s linear both',
            }}
          />
        </svg>
        <div
          style={{
            marginTop: 13, fontFamily: "var(--font-aleo), 'Aleo', Georgia, serif", fontWeight: 700,
            fontSize: 33, letterSpacing: '-0.025em', color: '#445D22', lineHeight: 1, whiteSpace: 'nowrap',
            animation: 's1Word 2.4s cubic-bezier(0.22,1,0.36,1) both',
          }}
        >
          Sapl<LeafI />ng
        </div>
        <div
          style={{
            marginTop: 12, width: 146, height: 1,
            background: 'linear-gradient(90deg, rgba(68,93,34,0.55), rgba(123,158,81,0.25))',
            transformOrigin: 'left center',
            animation: 's1Rule 2.4s cubic-bezier(0.22,1,0.36,1) both',
          }}
        />
        <div
          style={{
            marginTop: 14, display: 'flex', alignItems: 'baseline', gap: 9,
            fontFamily: "var(--font-plex-mono), 'IBM Plex Mono', ui-monospace, monospace", fontSize: 10,
            letterSpacing: '0.3em', color: '#9FA49A',
            animation: 's1Word 2.4s cubic-bezier(0.22,1,0.36,1) both',
          }}
        >
          <span>LOADING</span>
          {/* zero-padded to three digits so the lockup never reflows as it counts */}
          <span style={{ color: '#697062' }}>{String(Math.min(100, loadPct)).padStart(3, '0')}</span>
        </div>
      </div>
    </div>
  );
}
