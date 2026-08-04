'use client';

/**
 * The feature lab — a gallery card expanded full-bleed.
 *
 * Ported from `Sapling Landing v5.dc.html`. A scrim fades in over 420ms, then
 * a cream panel expands from the clicked card's rect (the FLIP is run by
 * `engine/flip.ts` through `registerPanel`), showing the feature's copy on the
 * left and a live demo on the right, with a rail along the bottom for
 * switching between the eight tools without closing.
 *
 * Escape and a scrim click both close it back down.
 *
 * The demo pane mounts the real interactive demo for the open tool — see
 * lab/, ported from the `FeatureLab` design component the source pulls in
 * through `<dc-import>`.
 */

import { GAL, LAB_KIND } from '@/lib/landing/content';
import { FeatureLabDemo } from './lab';

const MONO: React.CSSProperties = { fontFamily: "'JetBrains Mono',monospace" };

export function FeatureLab({
  index,
  panelRef,
  onClose,
  onPick,
}: {
  /** Which gallery card is open, or -1 for closed. */
  index: number;
  panelRef: (el: HTMLDivElement | null) => void;
  onClose: () => void;
  onPick: (i: number) => void;
}) {
  if (index < 0) return null;
  const g = GAL[index];
  if (!g) return null;

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 80 }}>
      <div
        onClick={onClose}
        style={{ position: 'absolute', inset: 0, background: 'rgba(8,31,20,0.62)', animation: 'panelFade 420ms ease both' }}
      />

      <div
        ref={panelRef}
        style={{ position: 'absolute', inset: 0, background: '#FDFCF9', overflow: 'hidden', display: 'flex', flexDirection: 'column', willChange: 'transform' }}
      >
        <div style={{ flex: 1, minHeight: 0, display: 'grid', gridTemplateColumns: 'minmax(320px,4fr) 7fr', animation: 'panelFade 420ms ease 160ms both' }}>
          <div style={{ padding: 'clamp(28px,5vh,56px) clamp(28px,4vw,56px)', display: 'flex', flexDirection: 'column', borderRight: '1px solid #ECE9DE', overflow: 'auto' }}>
            <span style={{ ...MONO, fontSize: 10.5, letterSpacing: '0.3em', color: '#0C5638', textTransform: 'uppercase' }}>
              {g.num} · {g.kicker}
            </span>
            <h3 style={{ margin: '16px 0 0', fontFamily: "'Playfair Display',serif", fontSize: 'clamp(1.9rem,3.2vw,2.9rem)', fontWeight: 600, lineHeight: 1.06, letterSpacing: '-0.018em', color: '#12201A' }}>
              {g.title}
            </h3>
            <p style={{ margin: '18px 0 0', color: '#33443B', fontSize: 15, lineHeight: 1.75, maxWidth: '44ch' }}>{g.desc}</p>

            <div style={{ marginTop: 26, display: 'flex', flexDirection: 'column', gap: 14 }}>
              {g.bullets.map((b, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
                  <span style={{ flexShrink: 0, width: 22, height: 22, borderRadius: 99, background: '#E6F2E8', display: 'flex', alignItems: 'center', justifyContent: 'center', marginTop: 1 }}>
                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#0C5638" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M20 6L9 17l-5-5" />
                    </svg>
                  </span>
                  <span style={{ fontSize: 14, lineHeight: 1.65, color: '#33443B' }}>{b.t}</span>
                </div>
              ))}
            </div>

            <div style={{ marginTop: 'auto', paddingTop: 28, display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ width: 8, height: 8, borderRadius: 99, background: '#0E9E5A', animation: 'betaGlow 2.2s ease-in-out infinite' }} />
              <span style={{ ...MONO, fontSize: 10, letterSpacing: '0.24em', color: '#61726A' }}>
                TRY IT · THIS ONE ACTUALLY WORKS
              </span>
            </div>
          </div>

          <div style={{ background: '#F1F4F0', padding: 'clamp(20px,3.4vh,40px) clamp(20px,2.6vw,44px)', display: 'flex', alignItems: 'center', justifyContent: 'center', minWidth: 0 }}>
            <div style={{ position: 'relative', width: '100%', height: '100%', maxHeight: 660, borderRadius: 20, overflow: 'hidden', border: '1px solid #E2E6DF', background: '#FDFCF9', boxShadow: '0 30px 70px -30px rgba(18,32,26,0.32)' }}>
              <div style={{ position: 'absolute', inset: 0 }}>
                <FeatureLabDemo kind={LAB_KIND[g.kind]} />
              </div>
            </div>
          </div>
        </div>

        <div
          style={{ flex: '0 0 auto', borderTop: '1px solid #ECE9DE', background: '#F6F8F4', padding: '12px clamp(20px,3vw,40px)', display: 'flex', gap: 10, overflowX: 'auto', animation: 'panelFade 420ms ease 260ms both' }}
        >
          {GAL.map((r, i) => {
            const on = i === index;
            return (
              <button
                key={r.kind}
                data-rail={i}
                type="button"
                onClick={() => onPick(i)}
                className="ld-rail"
                style={{
                  flex: '0 0 auto', display: 'flex', flexDirection: 'column', gap: 2,
                  textAlign: 'left', padding: '9px 15px', borderRadius: 11, cursor: 'pointer',
                  fontFamily: "'DM Sans',sans-serif",
                  transition: 'all 220ms cubic-bezier(0.22,1,0.36,1)',
                  background: on ? '#0C5638' : '#FDFCF9',
                  border: `1px solid ${on ? '#0C5638' : '#E8E5DA'}`,
                  color: on ? '#FDFCF9' : '#33443B',
                }}
              >
                <span style={{ ...MONO, fontSize: 8.5, letterSpacing: '0.22em', color: on ? 'rgba(253,252,249,0.7)' : '#9AA5A0' }}>
                  {r.num}
                </span>
                <span style={{ fontSize: 12.5, fontWeight: 600, whiteSpace: 'nowrap' }}>{r.kicker}</span>
              </button>
            );
          })}
        </div>

        <button
          onClick={onClose}
          aria-label="Close"
          className="ld-labclose"
          style={{ position: 'absolute', top: 20, right: 20, width: 42, height: 42, borderRadius: 99, border: '1px solid rgba(18,32,26,0.12)', background: '#FDFCF9', color: '#12201A', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', transition: 'all 250ms', zIndex: 3, animation: 'panelFade 420ms ease 240ms both' }}
        >
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M18 6L6 18M6 6l12 12" />
          </svg>
        </button>
      </div>
    </div>
  );
}
