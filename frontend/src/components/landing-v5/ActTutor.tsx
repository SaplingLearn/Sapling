'use client';

/**
 * Act III — the tutor.
 *
 * Ported from `Sapling Landing v5.dc.html`. 340vh pinned to a sticky stage.
 * Three tutor panels sit on the faces of a triangular prism —
 * `rotateY(0|120|240deg) translateZ(310px)` inside a `preserve-3d` carousel —
 * and the engine spins it as scroll advances, cross-fading the matching
 * caption on the left. Past the act, the pills take over and the carousel
 * becomes clickable.
 *
 * Engine hooks: `carouselRef` for the spin, `[data-tcap]` for the captions,
 * `[data-tutor-pills]` for the handover, `[data-panel]` for per-face depth
 * cueing, `[data-depth]` for the motes.
 */

import { DragField } from './DragField';

const MONO: React.CSSProperties = { fontFamily: "'JetBrains Mono',monospace" };

const CAPTIONS = [
  ['SOCRATIC', 'Never hands you the answer. It asks the question that gets you there yourself.'],
  ['EXPOSITORY', 'Explains it straight: structured, sourced from your materials, at your level.'],
  ['TEACHBACK', 'Flips the desk. You explain, and Sapling names exactly where it breaks down.'],
];

const MOTES: { d: number; s: React.CSSProperties }[] = [
  { d: 0.47, s: { right: '28.6%', top: '4.2%', width: 6.9, height: 6.9, background: '#6FBF8F', opacity: 0.46, animation: 'nodeFloatA 12.1s ease-in-out -9s infinite' } },
  { d: 0.41, s: { right: '8.9%', top: '56.6%', width: 8.8, height: 8.8, background: '#0E9E5A', opacity: 0.59, boxShadow: '0 0 21px #0E9E5A66', animation: 'nodeFloatB 13.1s ease-in-out -2.1s infinite' } },
  { d: 0.33, s: { right: '8.0%', top: '2.8%', width: 7, height: 7, background: '#0E9E5A', opacity: 0.56, animation: 'nodeFloatB 17.5s ease-in-out -17.2s infinite' } },
  { d: 0.17, s: { right: '12.1%', top: '64.7%', width: 10.5, height: 10.5, background: '#4FA574', opacity: 0.39, boxShadow: '0 0 25px #4FA57466', animation: 'nodeFloatA 10s ease-in-out -8.9s infinite' } },
  { d: 0.40, s: { left: '13.5%', top: '94.8%', width: 6.7, height: 6.7, background: '#4FA574', opacity: 0.56, animation: 'nodeFloatA 15.1s ease-in-out -17.3s infinite' } },
  { d: 0.21, s: { right: '43.6%', top: '5.2%', width: 5.7, height: 5.7, background: '#6FBF8F', opacity: 0.53, animation: 'nodeFloatB 18.1s ease-in-out -5.2s infinite' } },
  { d: 0.37, s: { right: '10.0%', top: '92.0%', width: 8.1, height: 8.1, background: '#0E9E5A', opacity: 0.58, boxShadow: '0 0 19px #0E9E5A66', animation: 'nodeFloatA 17.8s ease-in-out -16.5s infinite' } },
  { d: 0.22, s: { left: '5.1%', top: '51.6%', width: 4.7, height: 4.7, background: '#8FD9A8', opacity: 0.51, animation: 'nodeFloatB 15.6s ease-in-out -1.7s infinite' } },
  { d: 0.46, s: { left: '5.1%', top: '17.7%', width: 7.9, height: 7.9, background: '#2E7D52', opacity: 0.41, boxShadow: '0 0 19px #2E7D5266', animation: 'nodeFloatA 17s ease-in-out -10.1s infinite' } },
  { d: 0.47, s: { left: '35.5%', top: '4.3%', width: 6.5, height: 6.5, background: '#0E9E5A', opacity: 0.56, animation: 'nodeFloatB 14.5s ease-in-out -9.6s infinite' } },
];

/** Common to all three faces of the prism. */
const FACE: React.CSSProperties = {
  position: 'absolute', inset: 0, backfaceVisibility: 'hidden',
  borderRadius: 22, padding: 20, boxSizing: 'border-box', overflow: 'hidden',
};

const PILL_ON = '#0C5638';
const PILL_ON_FG = '#FDFCF9';

export function ActTutor({
  carouselRef,
  tutorMode,
  onSetMode,
}: {
  carouselRef: React.RefObject<HTMLDivElement | null>;
  tutorMode: number;
  onSetMode: (i: number) => void;
}) {
  return (
    <section id="act-tutor" data-act="3" style={{ height: '340vh', position: 'relative' }}>
      <DragField section="act-tutor" />

      <div
        style={{
          position: 'sticky', top: 0, height: '100vh', overflow: 'hidden',
          display: 'flex', alignItems: 'center',
          background: 'linear-gradient(180deg, rgba(230,242,232,0) 0%, rgba(230,242,232,0.6) 30%, rgba(230,242,232,0.6) 70%, rgba(230,242,232,0) 100%)',
        }}
      >
        <div aria-hidden="true" style={{ position: 'absolute', inset: 0, pointerEvents: 'none', overflow: 'hidden', zIndex: 0 }}>
          {MOTES.map((m, i) => (
            <span key={i} data-anim data-depth={m.d} style={{ position: 'absolute', borderRadius: 99, ...m.s }} />
          ))}
        </div>

        <div style={{ maxWidth: 1220, width: '100%', margin: '0 auto', padding: '0 24px', display: 'grid', gridTemplateColumns: '5fr 7fr', gap: 32, alignItems: 'center' }}>
          <div style={{ position: 'relative', zIndex: 2 }}>
            <span style={{ ...MONO, fontSize: 10.5, letterSpacing: '0.34em', color: '#0C5638', textTransform: 'uppercase' }}>AI tutor</span>
            <h2 style={{ margin: '16px 0 0', fontFamily: "'Playfair Display',serif", fontSize: 'clamp(2.4rem,4.8vw,4.2rem)', fontWeight: 600, lineHeight: 1.04, letterSpacing: '-0.02em', color: '#12201A' }}>
              Three ways to learn this. Your <em style={{ color: '#0C5638' }}>pick.</em>
            </h2>

            <div style={{ position: 'relative', marginTop: 22, minHeight: 110 }}>
              {CAPTIONS.map(([tag, body], i) => (
                <div key={tag} data-tcap={i} style={{ position: 'absolute', inset: 0, opacity: 0 }}>
                  <span style={{ ...MONO, fontSize: 10, letterSpacing: '0.28em', color: '#0C5638' }}>{tag}</span>
                  <p style={{ margin: '8px 0 0', color: '#33443B', fontSize: 15.5, lineHeight: 1.7, maxWidth: '36ch' }}>{body}</p>
                </div>
              ))}
            </div>

            {/*
              The engine fades these in once the act's scroll is spent, and
              binds `inert` to the same `docked` flag — opacity alone left the
              buttons focusable while invisible.
            */}
            <div data-tutor-pills="1" inert style={{ display: 'flex', gap: 8, marginTop: 8, opacity: 0, pointerEvents: 'none', transition: 'opacity 400ms ease' }}>
              {CAPTIONS.map(([tag], i) => (
                <button
                  key={tag}
                  type="button"
                  onClick={() => onSetMode(i)}
                  style={{
                    border: '1px solid rgba(12,86,56,0.3)', borderRadius: 99, padding: '9px 18px',
                    ...MONO, fontSize: 10.5, letterSpacing: '0.12em', cursor: 'pointer',
                    background: tutorMode === i ? PILL_ON : 'transparent',
                    color: tutorMode === i ? PILL_ON_FG : '#33443B',
                    transition: 'all 250ms',
                  }}
                >
                  {tag}
                </button>
              ))}
            </div>
          </div>

          <div style={{ perspective: 1600, height: 'min(66vh,560px)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <div
              ref={carouselRef}
              style={{ position: 'relative', width: 'min(430px,44vw)', height: 'min(500px,60vh)', transformStyle: 'preserve-3d', willChange: 'transform' }}
            >
              {/* ── face 0 · Socratic ── */}
              <div
                data-panel="0"
                data-socratic="1"
                style={{ ...FACE, transform: 'rotateY(0deg) translateZ(310px)', background: '#FDFCF9', border: '1px solid #E8E5DA', boxShadow: '0 26px 54px -22px rgba(18,32,26,0.3)', display: 'grid', gridTemplateRows: 'auto minmax(0,1fr) auto', gap: 10 }}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span style={{ ...MONO, fontSize: 10, letterSpacing: '0.22em', color: '#0C5638' }}>SOCRATIC MODE</span>
                  <span style={{ fontFamily: "'Playfair Display',serif", fontStyle: 'italic', fontSize: 22, color: '#0C5638' }}>?</span>
                </div>
                <div style={{ minHeight: 0, display: 'flex', flexDirection: 'column', justifyContent: 'space-between', gap: 5, overflow: 'hidden' }}>
                  <div style={{ alignSelf: 'flex-start', maxWidth: '88%', background: '#E6F2E8', borderRadius: '14px 14px 14px 4px', padding: '8px 12px', fontSize: 12, lineHeight: 1.45, color: '#12201A' }}>
                    Before rotations: what does the &ldquo;B&rdquo; in BST guarantee about a node&rsquo;s children?
                  </div>
                  <div style={{ alignSelf: 'flex-end', maxWidth: '80%', background: '#0C5638', color: '#E6F2E8', borderRadius: '14px 14px 4px 14px', padding: '8px 12px', fontSize: 12, lineHeight: 1.45 }}>
                    left subtree smaller, right subtree bigger?
                  </div>
                  <div style={{ alignSelf: 'flex-start', maxWidth: '88%', background: '#E6F2E8', borderRadius: '14px 14px 14px 4px', padding: '8px 12px', fontSize: 12, lineHeight: 1.45, color: '#12201A' }}>
                    Right. So what breaks if one side grows far taller?
                  </div>
                  <div style={{ alignSelf: 'flex-end', maxWidth: '80%', background: '#0C5638', color: '#E6F2E8', borderRadius: '14px 14px 4px 14px', padding: '8px 12px', fontSize: 12, lineHeight: 1.45 }}>
                    lookup stops being logarithmic
                  </div>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 5, borderTop: '1px solid #EBF1EC', paddingTop: 9 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span style={{ ...MONO, fontSize: 8, letterSpacing: '0.18em', color: '#9AA5A0' }}>HINT LADDER</span>
                    <span style={{ display: 'flex', gap: 4, marginLeft: 2 }}>
                      {[true, true, false, false].map((on, i) => (
                        <span key={i} style={{ width: 18, height: 3, borderRadius: 99, background: on ? '#0E9E5A' : '#DCE7DE' }} />
                      ))}
                    </span>
                    <span style={{ marginLeft: 'auto', ...MONO, fontSize: 9, color: '#61726A' }}>2 / 4</span>
                  </div>
                  <span style={{ fontSize: 11, lineHeight: 1.5, color: '#8B9891' }}>It escalates only when you stall.</span>
                </div>
              </div>

              {/* ── face 1 · Expository ── */}
              <div
                data-panel="1"
                style={{ ...FACE, transform: 'rotateY(120deg) translateZ(310px)', background: '#F6F8F4', border: '1px solid #E8E5DA', boxShadow: '0 26px 54px -22px rgba(18,32,26,0.3)', display: 'grid', gridTemplateRows: 'auto auto auto minmax(0,1fr) auto auto', gap: 9 }}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span style={{ ...MONO, fontSize: 10, letterSpacing: '0.22em', color: '#0C5638' }}>EXPOSITORY MODE</span>
                  <svg aria-hidden="true" width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="#0C5638" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M12 6.5C10.5 5 8.3 4.4 5 4.4c-.6 0-1 .4-1 1v11.4c0 .6.4 1 1 1 3.3 0 5.5.6 7 2.1" />
                    <path d="M12 6.5c1.5-1.5 3.7-2.1 7-2.1.6 0 1 .4 1 1v11.4c0 .6-.4 1-1 1-3.3 0-5.5.6-7 2.1" />
                    <path d="M12 6.5v13.4" />
                  </svg>
                </div>
                <h3 style={{ margin: 0, fontFamily: "'Playfair Display',serif", fontSize: 18, fontWeight: 600, color: '#12201A' }}>AVL rotations, plainly.</h3>
                <p style={{ margin: 0, fontSize: 12.5, lineHeight: 1.65, color: '#33443B' }}>
                  Every node&rsquo;s <span style={{ background: '#E6F2E8', borderRadius: 4, padding: '0 3px', color: '#0C5638', fontWeight: 600 }}>balance factor</span> stays in {'{−1, 0, +1}'}. When an insert breaks that, one of four <span style={{ background: '#E6F2E8', borderRadius: 4, padding: '0 3px', color: '#0C5638', fontWeight: 600 }}>rotations</span> restores it in O(1).
                </p>
                <div style={{ minHeight: 0, display: 'grid', gridTemplateColumns: '1fr auto 1fr', gap: 6, alignItems: 'stretch', background: '#FDFCF9', border: '1px solid #E8E5DA', borderRadius: 12, padding: '9px 10px', overflow: 'hidden' }}>
                  <div style={{ minHeight: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 5 }}>
                    <svg aria-hidden="true" width="100%" height="100%" style={{ flex: 1, minHeight: 34 }} preserveAspectRatio="xMidYMid meet" viewBox="0 0 120 62">
                      <line x1="82" y1="12" x2="52" y2="34" stroke="#DCE7DE" strokeWidth="1.5" />
                      <line x1="52" y1="34" x2="26" y2="54" stroke="#DCE7DE" strokeWidth="1.5" />
                      <circle cx="82" cy="12" r="9" fill="#E27A63" />
                      <text x="82" y="15.5" textAnchor="middle" fontFamily="JetBrains Mono" fontSize="8" fill="#FDFCF9">+2</text>
                      <circle cx="52" cy="34" r="7" fill="#4FA574" />
                      <circle cx="26" cy="54" r="6" fill="#8FD9A8" />
                    </svg>
                    <span style={{ ...MONO, fontSize: 7.5, letterSpacing: '0.14em', color: '#9c4b48' }}>LEFT-HEAVY</span>
                  </div>
                  <span style={{ alignSelf: 'center', ...MONO, fontSize: 11, color: '#0C5638' }}>→</span>
                  <div style={{ minHeight: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 5 }}>
                    <svg aria-hidden="true" width="100%" height="100%" style={{ flex: 1, minHeight: 34 }} preserveAspectRatio="xMidYMid meet" viewBox="0 0 120 62">
                      <line x1="60" y1="16" x2="34" y2="46" stroke="#4FA574" strokeWidth="1.5" />
                      <line x1="60" y1="16" x2="88" y2="46" stroke="#4FA574" strokeWidth="1.5" />
                      <circle cx="60" cy="16" r="9" fill="#0C5638" />
                      <text x="60" y="19.5" textAnchor="middle" fontFamily="JetBrains Mono" fontSize="8" fill="#E6F2E8">0</text>
                      <circle cx="34" cy="46" r="7" fill="#4FA574" />
                      <circle cx="88" cy="46" r="7" fill="#8FD9A8" />
                    </svg>
                    <span style={{ ...MONO, fontSize: 7.5, letterSpacing: '0.14em', color: '#0C5638' }}>AFTER LL ROTATE</span>
                  </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                  <span style={{ ...MONO, fontSize: 8, letterSpacing: '0.18em', color: '#9AA5A0' }}>FOUR CASES</span>
                  {(['LL', 'LR', 'RL', 'RR'] as const).map((t) => {
                    const on = t === 'LL';
                    return (
                      <span
                        key={t}
                        style={{ flex: 1, textAlign: 'center', padding: '4px 0', borderRadius: 6, ...MONO, fontSize: 8.5, letterSpacing: '0.1em', background: on ? '#E6F2E8' : '#FDFCF9', border: `1px solid ${on ? '#0E9E5A' : '#E8E5DA'}`, color: on ? '#0C5638' : '#8B9891' }}
                      >
                        {t}
                      </span>
                    );
                  })}
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 5, borderTop: '1px solid #E3EBE5', paddingTop: 9 }}>
                  <span style={{ ...MONO, fontSize: 8, letterSpacing: '0.2em', color: '#9AA5A0' }}>RETRIEVED FROM YOUR LIBRARY</span>
                  <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
                    <span style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '4px 8px', borderRadius: 6, background: '#FDFCF9', border: '1px solid #DCE7DE', ...MONO, fontSize: 8.5, color: '#33443B' }}>
                      <span style={{ width: 5, height: 5, borderRadius: 99, background: '#0E9E5A' }} />
                      lecture-07.pdf<b style={{ fontWeight: 400, color: '#9AA5A0' }}>p. 12</b>
                    </span>
                    <span style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '4px 8px', borderRadius: 6, background: '#FDFCF9', border: '1px solid #DCE7DE', ...MONO, fontSize: 8.5, color: '#33443B' }}>
                      <span style={{ width: 5, height: 5, borderRadius: 99, background: '#0E9E5A' }} />
                      notes-wk4.md
                    </span>
                  </div>
                </div>
              </div>

              {/* ── face 2 · TeachBack — the only dark face ── */}
              <div
                data-panel="2"
                style={{ ...FACE, transform: 'rotateY(240deg) translateZ(310px)', background: 'linear-gradient(155deg,#153F2B 0%,#0D2B1E 58%,#081F14 100%)', border: '1px solid rgba(143,217,168,0.22)', boxShadow: '0 26px 54px -22px rgba(4,22,14,0.55)', padding: 18, display: 'grid', gridTemplateRows: 'auto auto auto minmax(0,1fr) auto', gap: 8 }}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span style={{ ...MONO, fontSize: 10, letterSpacing: '0.22em', color: '#8FD9A8' }}>TEACHBACK MODE</span>
                  <svg aria-hidden="true" width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="#E27A63" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M12 3.5a3 3 0 0 1 3 3v4.5a3 3 0 0 1-6 0V6.5a3 3 0 0 1 3-3z" />
                    <path d="M5.5 10.5v.8a6.5 6.5 0 0 0 13 0v-.8" />
                    <path d="M12 17.8V21" />
                  </svg>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span style={{ display: 'flex', alignItems: 'flex-end', gap: 2.5, height: 26 }}>
                    {([['#4FA574', '1.1s', '0s'], ['#8FD9A8', '1.3s', '-0.2s'], ['#0E9E5A', '0.9s', '-0.5s'],
                       ['#8FD9A8', '1.2s', '-0.8s'], ['#4FA574', '1.0s', '-0.3s'], ['#0E9E5A', '1.4s', '-0.6s'],
                       ['#8FD9A8', '1.1s', '-0.9s'], ['#4FA574', '1.25s', '-0.4s'], ['#0E9E5A', '0.95s', '-0.7s']] as const).map(([c, dur, delay], i) => (
                      <span data-anim key={i} style={{ width: 3, height: '100%', borderRadius: 2, background: c, transformOrigin: 'bottom', animation: `waveBar ${dur} ease-in-out ${delay} infinite` }} />
                    ))}
                  </span>
                  <span style={{ ...MONO, fontSize: 8.5, letterSpacing: '0.16em', color: '#8FD9A8' }}>RECORDING · 0:42</span>
                </div>
                <p style={{ margin: 0, fontSize: 12, lineHeight: 1.6, color: '#B9D9C4' }}>
                  &ldquo;…so you <span style={{ color: '#E6F2E8' }}>rotate left when the right side gets too heavy</span>, and, um, <span style={{ background: 'rgba(226,122,99,0.16)', borderBottom: '1.5px solid #E27A63', borderRadius: 3, padding: '1px 3px', color: '#F6F8F4' }}>the parent just moves down</span> and it&rsquo;s balanced again…&rdquo;
                </p>
                <div style={{ minHeight: 0, display: 'flex', flexDirection: 'column', justifyContent: 'flex-start', gap: 3, overflow: 'hidden' }}>
                  <span style={{ ...MONO, fontSize: 8, letterSpacing: '0.2em', color: '#5F7A6C', marginBottom: 2 }}>WHAT YOUR EXPLANATION COVERED</span>
                  {([['#0E9E5A', 'Rotation direction', 'CORRECT'],
                     ['#E27A63', 'Which node becomes root', 'MISSING'],
                     ['#c89b5e', 'Subtree reattachment', 'VAGUE']] as const).map(([c, label, verdict]) => (
                    <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ width: 6, height: 6, borderRadius: 99, background: c, flex: '0 0 auto' }} />
                      <span style={{ fontSize: 10.5, color: '#B9D9C4' }}>{label}</span>
                      <span style={{ marginLeft: 'auto', ...MONO, fontSize: 8.5, letterSpacing: '0.14em', color: c }}>{verdict}</span>
                    </div>
                  ))}
                </div>
                <div style={{ background: 'rgba(226,122,99,0.12)', border: '1px solid rgba(226,122,99,0.4)', borderRadius: 12, padding: '8px 11px' }}>
                  <span style={{ ...MONO, fontSize: 9, letterSpacing: '0.2em', color: '#E27A63' }}>GAP FOUND</span>
                  <p style={{ margin: '5px 0 0', fontSize: 11.5, lineHeight: 1.5, color: '#F6F8F4' }}>
                    The right child becomes the new root, not the parent.
                  </p>
                  <div style={{ marginTop: 7, display: 'flex', alignItems: 'center', gap: 8 }}>
                    {/* mastery goes DOWN — the gap is new information */}
                    <span style={{ ...MONO, fontSize: 8, letterSpacing: '0.14em', color: '#B9D9C4' }}>MASTERY 24% → 19%</span>
                    <span style={{ marginLeft: 'auto', ...MONO, fontSize: 8, letterSpacing: '0.14em', color: '#8FD9A8', whiteSpace: 'nowrap' }}>RE-EXPLAIN ↻</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
