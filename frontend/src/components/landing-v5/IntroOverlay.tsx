'use client';

/**
 * Loading overlay — the hand-tuned intro lockup.
 *
 * Ported from `Sapling Landing v5.dc.html`. The sequence is causal and the
 * ordering is the whole point: the wordmark sets context first, the stem
 * draws upward, the bud pops the moment the stem tops out, then each leaf
 * unfurls from the joint the stem has already passed, and the rule sweeps
 * out last to close the lockup.
 *
 * All six animations are 2.4s with `both` fill and differ only in their
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
        backgroundColor: '#f0f4f2',
        backgroundImage:
          'radial-gradient(ellipse 100% 70% at 50% 30%, rgba(255,255,255,0.9) 0%, transparent 62%)',
        transition: 'opacity 700ms cubic-bezier(0.22,1,0.36,1)',
        opacity: heroMounted ? 0 : 1,
        pointerEvents: heroMounted ? 'none' : 'auto',
      }}
    >
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
        <svg width="86" height="86" viewBox="0 0 64 64" fill="none" style={{ display: 'block', overflow: 'visible' }}>
          <path
            d="M32 54 L32 28" stroke="#0C5638" strokeWidth="3.5" strokeLinecap="round"
            strokeDasharray="27"
            style={{ animation: 's1Stem 2.4s cubic-bezier(0.25,0.6,0.2,1) both' }}
          />
          <path
            d="M32 38 C32 38 18 34 16 22 C16 22 30 20 32 38Z" fill="#0C5638"
            style={{
              transformBox: 'fill-box', transformOrigin: '100% 100%',
              animation: 's1LeafLo 2.4s linear both',
            }}
          />
          <path
            d="M32 30 C32 30 46 24 50 12 C50 12 36 12 32 30Z" fill="#4FA574"
            style={{
              transformBox: 'fill-box', transformOrigin: '0% 100%',
              animation: 's1LeafHi 2.4s linear both',
            }}
          />
          <circle
            cx="32" cy="26" r="2.5" fill="#0C5638"
            style={{
              transformBox: 'fill-box', transformOrigin: '50% 50%',
              animation: 's1Bud 2.4s cubic-bezier(0.34,1.56,0.64,1) both',
            }}
          />
        </svg>
        <div
          style={{
            marginTop: 13, fontFamily: "'Spectral',Georgia,serif", fontWeight: 700,
            fontSize: 33, letterSpacing: '-0.025em', color: '#0C5638', lineHeight: 1,
            animation: 's1Word 2.4s cubic-bezier(0.22,1,0.36,1) both',
          }}
        >
          Sapling
        </div>
        <div
          style={{
            marginTop: 12, width: 146, height: 1,
            background: 'linear-gradient(90deg, rgba(12,86,56,0.55), rgba(79,165,116,0.25))',
            transformOrigin: 'left center',
            animation: 's1Rule 2.4s cubic-bezier(0.22,1,0.36,1) both',
          }}
        />
        <div
          style={{
            marginTop: 14, display: 'flex', alignItems: 'baseline', gap: 9,
            fontFamily: "'JetBrains Mono',monospace", fontSize: 10,
            letterSpacing: '0.3em', color: '#9AA5A0',
            animation: 's1Word 2.4s cubic-bezier(0.22,1,0.36,1) both',
          }}
        >
          <span>LOADING</span>
          {/* zero-padded to three digits so the lockup never reflows as it counts */}
          <span style={{ color: '#61726A' }}>{String(Math.min(100, loadPct)).padStart(3, '0')}</span>
        </div>
      </div>
    </div>
  );
}
