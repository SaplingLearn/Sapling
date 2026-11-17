'use client';

import { SaplingWordmark } from '@/components/SaplingWordmark';

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
        <img src="/design/sapling/originals/logo-symbol.svg" alt="" aria-hidden="true" width={46} height={65} />
        <div
          style={{
            marginTop: 13, fontFamily: "var(--font-aleo), 'Aleo', Georgia, serif", fontWeight: 700,
            fontSize: 33, letterSpacing: '-0.025em', color: '#445D22', lineHeight: 1, whiteSpace: 'nowrap',
            animation: 's1Word 2.4s cubic-bezier(0.22,1,0.36,1) both',
          }}
        >
          <SaplingWordmark width={146} />
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
