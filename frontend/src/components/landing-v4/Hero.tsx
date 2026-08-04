'use client';

/**
 * Hero — 100vh, centred, over the animated point-cloud canvas.
 *
 * Ported from `Sapling Landing v4.dc.html`. The four `.floating-card`
 * surfaces are positioned here but *transformed* by the engine each frame
 * (float + scroll parallax + mouse tilt), which is why they carry
 * data-base-rot / data-float-delay / data-float-dur rather than CSS
 * animations. They are hidden below 1024px by the media query.
 */

import type { RefObject } from 'react';

const TIERS: [string, string][] = [
  ['#0E9E5A', 'Mastered'],
  ['#4FA574', 'Learning'],
  ['#E27A63', 'Needs work'],
  ['#9CA3AF', 'Unexplored'],
];

const MICRO_LABEL: React.CSSProperties = {
  fontSize: 11, color: '#61726A', textTransform: 'uppercase', letterSpacing: '0.06em',
};

const CARD: React.CSSProperties = {
  position: 'absolute', background: '#fdfcf9', border: '1px solid #E8E5DA',
  borderRadius: 16, boxShadow: '0 8px 30px rgba(18,32,26,0.08)',
};

/** Glow that keeps hero copy legible over the moving point cloud. */
const GLOW_SM = '0 0 4px rgba(246,248,244,0.98), 0 0 12px rgba(246,248,244,0.88)';

const CHECKS = [
  'Full context on every course you take',
  'Remembers what you got wrong',
  'Never hands over the answer',
];

function Check() {
  return (
    <svg
      width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#0E9E5A"
      strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}
    >
      <path d="M5 12l5 5L20 7" />
    </svg>
  );
}

export interface HeroProps {
  heroCanvasRef: RefObject<HTMLCanvasElement | null>;
  heroContentRef: RefObject<HTMLDivElement | null>;
  heroMounted: boolean;
  heroText1: string;
  heroText2: string;
  onBeta: () => void;
  onSeeHow: () => void;
}

export function Hero({
  heroCanvasRef, heroContentRef, heroMounted, heroText1, heroText2, onBeta, onSeeHow,
}: HeroProps) {
  const o = heroMounted ? 1 : 0;
  const rise = heroMounted ? 'translateY(0)' : 'translateY(25px)';

  return (
    <section
      data-screen-label="Hero"
      style={{
        position: 'relative', minHeight: '100vh',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}
    >
      <div aria-hidden="true" style={{ position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 0, overflow: 'hidden' }}>
        <div style={{ position: 'absolute', top: '-10%', left: '-10%', width: '50vw', height: '50vw', maxWidth: 900, maxHeight: 900, borderRadius: '50%', filter: 'blur(64px)', opacity: 0.7, background: 'rgba(46,125,82,0.22)' }} />
        <div style={{ position: 'absolute', top: '20%', right: '-10%', width: '40vw', height: '40vw', maxWidth: 720, maxHeight: 720, borderRadius: '50%', filter: 'blur(64px)', opacity: 0.7, background: 'rgba(43,140,150,0.2)' }} />
      </div>

      <canvas
        ref={heroCanvasRef as RefObject<HTMLCanvasElement>}
        style={{ position: 'absolute', inset: 0, zIndex: 0, width: '100%', height: '100%' }}
      />

      <div style={{ position: 'absolute', inset: 0, zIndex: 10, pointerEvents: 'none' }}>
        {/* legend */}
        <div
          className="floating-card" data-base-rot="10" data-float-delay="1000" data-float-dur="6000"
          style={{ ...CARD, top: '24%', right: '12%', width: 208, padding: 20, opacity: o, transition: 'opacity 0.6s ease 1.0s' }}
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {TIERS.map(([c, label]) => (
              <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ width: 8, height: 8, borderRadius: 99, background: c, display: 'inline-block' }} />
                <span style={MICRO_LABEL}>{label}</span>
              </div>
            ))}
          </div>
        </div>

        {/* flashcard */}
        <div
          className="floating-card" data-base-rot="-10" data-float-delay="1500" data-float-dur="5200"
          style={{ ...CARD, top: '24%', left: '12%', width: 182, padding: 16, display: 'flex', flexDirection: 'column', gap: 10, opacity: o, transition: 'opacity 0.6s ease 1.4s' }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={MICRO_LABEL}>Card 3 of 12</span>
            <span style={{ width: 8, height: 8, borderRadius: 99, background: '#E27A63', display: 'inline-block' }} />
          </div>
          <div style={{ background: '#F6F8F4', border: '1px solid #ECE9DE', borderRadius: 12, padding: '12px 11px', display: 'flex', flexDirection: 'column', gap: 5 }}>
            <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 8, letterSpacing: '0.2em', color: '#9AA5A0' }}>FRONT</span>
            <span style={{ fontFamily: "'Playfair Display',serif", fontSize: 13, fontWeight: 600, lineHeight: 1.35, color: '#12201A' }}>
              What does λ scale?
            </span>
          </div>
          <div style={{ display: 'flex', gap: 5 }}>
            {[
              ['Forgot', 'rgba(226,122,99,0.45)'],
              ['Hard', 'rgba(200,155,94,0.45)'],
              ['Easy', 'rgba(14,158,90,0.5)'],
            ].map(([label, border]) => (
              <span key={label} style={{ flex: 1, textAlign: 'center', padding: '5px 0', borderRadius: 7, border: `1px solid ${border}`, fontSize: 10, color: '#61726A' }}>
                {label}
              </span>
            ))}
          </div>
        </div>

        {/* mastery bars */}
        <div
          className="floating-card" data-base-rot="-7" data-float-delay="2000" data-float-dur="6400"
          style={{ ...CARD, bottom: '34%', right: '14%', width: 196, padding: 16, display: 'flex', flexDirection: 'column', gap: 12, opacity: o, transition: 'opacity 0.6s ease 1.6s' }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={MICRO_LABEL}>PY 205</span>
            <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11, color: '#0C5638' }}>61%</span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
            {[
              ['Kinematics', '84%', '#0E9E5A'],
              ['Momentum', '52%', '#4FA574'],
              ['Torque', '21%', '#E27A63'],
            ].map(([label, w, c]) => (
              <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ flex: 1, height: 5, borderRadius: 99, background: '#ECE9DE', overflow: 'hidden' }}>
                  <span style={{ display: 'block', width: w, height: '100%', borderRadius: 99, background: c }} />
                </span>
                <span style={{ fontSize: 11, color: '#61726A', width: 62 }}>{label}</span>
              </div>
            ))}
          </div>
        </div>

        {/* actions */}
        <div
          className="floating-card" data-base-rot="7" data-float-delay="500" data-float-dur="4500"
          style={{ ...CARD, bottom: '34%', left: '14%', width: 176, padding: 16, display: 'flex', flexDirection: 'column', gap: 8, opacity: o, transition: 'opacity 0.6s ease 1.2s' }}
        >
          <div style={{ background: '#F6F8F4', border: '1px solid #ECE9DE', borderRadius: 12, padding: '8px 0', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#61726A" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M9 3h6M10 3v6l-5 10a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-10V3" />
            </svg>
            <span style={{ fontSize: 11, color: '#61726A' }}>Quick Quiz</span>
          </div>
          <div style={{ background: '#F6F8F4', border: '1px solid #ECE9DE', borderRadius: 12, padding: '8px 0', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#61726A" strokeWidth="1" strokeLinecap="butt" strokeLinejoin="miter">
              <path d="M6 8.5h12M6 13h6M23.5 2H23c-3 0.5 -8 0.75 -11 0.75S4 2.5 1 2H0.5v21.5h0.25l0.154 -0.154A15.692 15.692 0 0 1 12 18.75c3 0 8 0.25 11 0.75h0.5V2Z" />
            </svg>
            <span style={{ fontSize: 11, color: '#61726A' }}>Study Room</span>
          </div>
        </div>
      </div>

      <div
        ref={heroContentRef as RefObject<HTMLDivElement>}
        style={{
          position: 'relative', zIndex: 20, display: 'flex', flexDirection: 'column',
          alignItems: 'center', textAlign: 'center', maxWidth: 900, padding: '0 24px',
        }}
      >
        <h1
          style={{
            position: 'relative', margin: 0, padding: '0 16px 32px',
            fontFamily: "'Playfair Display',serif", fontSize: 'clamp(3.5rem, 10vw, 10rem)',
            fontWeight: 600, lineHeight: 1.15, letterSpacing: '-0.02em', color: '#0C5638',
            textShadow:
              '0 0 6px rgba(246,248,244,0.98), 0 0 18px rgba(246,248,244,0.92), 0 0 40px rgba(246,248,244,0.72)',
            opacity: o, transform: rise,
            transition: 'all 700ms cubic-bezier(0.22,1,0.36,1) 300ms', minHeight: '1.2em',
          }}
        >
          {heroText1 || ' '}
        </h1>
        <p
          style={{
            position: 'relative', margin: 0, fontFamily: "'Playfair Display',serif",
            fontSize: 'clamp(1.5rem, 3vw, 2.25rem)', color: '#61726A', maxWidth: '36rem',
            lineHeight: 1.5, letterSpacing: '-0.01em', fontWeight: 500,
            textShadow:
              '0 0 5px rgba(246,248,244,0.98), 0 0 15px rgba(246,248,244,0.9), 0 0 32px rgba(246,248,244,0.68)',
            opacity: o, transform: rise,
            transition: 'all 700ms cubic-bezier(0.22,1,0.36,1) 500ms', minHeight: '1.4em',
          }}
        >
          {heroText2 || ' '}
        </p>

        <p
          style={{
            position: 'relative', margin: '20px 0 0', color: '#33443B', fontWeight: 600,
            fontSize: 15.5, lineHeight: 1.68, maxWidth: '48ch', textWrap: 'pretty',
            textShadow:
              '0 0 4px rgba(246,248,244,0.98), 0 0 12px rgba(246,248,244,0.9), 0 0 26px rgba(246,248,244,0.62)',
            opacity: o, transform: rise, transition: 'all 700ms cubic-bezier(0.22,1,0.36,1) 620ms',
          }}
        >
          Drop in your syllabus and notes, and{' '}
          <b style={{ fontWeight: 700, color: '#12201A' }}>Sapling&apos;s AI learns your whole course</b>. Every
          quiz, card, and deadline comes from{' '}
          <b style={{ fontWeight: 700, color: '#0C5638' }}>your material</b>, never generic exercises off the
          internet.
        </p>

        <div
          style={{
            position: 'relative', marginTop: 16, display: 'flex', alignItems: 'center',
            justifyContent: 'center', gap: '8px 22px', flexWrap: 'wrap',
            opacity: o, transform: rise, transition: 'all 700ms cubic-bezier(0.22,1,0.36,1) 700ms',
          }}
        >
          {CHECKS.map((t) => (
            <span key={t} style={{ display: 'flex', alignItems: 'center', gap: 7, fontSize: 13.5, color: '#61726A', textShadow: GLOW_SM }}>
              <Check />
              {t}
            </span>
          ))}
        </div>

        <div
          style={{
            position: 'relative', marginTop: 30, display: 'flex', alignItems: 'center',
            justifyContent: 'center', gap: 14, flexWrap: 'wrap',
            opacity: o, transform: heroMounted ? 'translateY(0)' : 'translateY(25px)',
            transition: 'all 700ms cubic-bezier(0.22,1,0.36,1) 820ms',
          }}
        >
          <button
            onClick={onBeta}
            className="v4-btn-solid"
            style={{
              background: '#0C5638', color: '#fff', border: 'none', borderRadius: 6,
              padding: '14px 28px', fontFamily: "'DM Sans',sans-serif", fontWeight: 600,
              fontSize: 15.5, cursor: 'pointer', animation: 'betaGlow 2.2s ease-in-out infinite',
              transition: 'filter 200ms',
            }}
          >
            Sign up for Beta Testing
          </button>
          <button
            onClick={onSeeHow}
            className="v4-btn-ghost"
            style={{
              background: 'rgba(253,252,249,0.8)', color: '#12201A',
              border: '1px solid rgba(18,32,26,0.16)', borderRadius: 6, padding: '14px 24px',
              fontFamily: "'DM Sans',sans-serif", fontWeight: 600, fontSize: 15.5,
              cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 9,
              transition: 'all 220ms',
            }}
          >
            See how it works
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M5 12h14M13 6l6 6-6 6" />
            </svg>
          </button>
        </div>
      </div>

      <div
        style={{
          position: 'absolute', bottom: 26, left: '50%',
          animation: 'floatIndicator 2.5s ease-in-out infinite',
          display: 'flex', flexDirection: 'column', alignItems: 'center',
          opacity: o, transition: 'opacity 1s ease 1.2s',
        }}
      >
        <span style={{ display: 'block', width: 1, height: 44, background: 'linear-gradient(180deg, transparent, rgba(12,86,56,0.4), transparent)' }} />
        <span
          style={{
            fontFamily: "'JetBrains Mono',monospace", fontSize: 11, letterSpacing: '0.4em',
            color: '#61726A', opacity: 0.7, marginTop: 10, textShadow: GLOW_SM,
          }}
        >
          SEE WHAT&apos;S INSIDE
        </span>
      </div>
    </section>
  );
}
