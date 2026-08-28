'use client';

/**
 * The v5 title screen.
 *
 * Ported from `Sapling Landing v5.dc.html`, then refreshed against the newer
 * `Sapling Landing.html` bundle. The wordmark lockup carried over unchanged;
 * what the refresh moved:
 *
 * - The 01/02/03 Ingest/Map/Recall keys are gone from the hero entirely. The
 *   bottom band is now three columns holding only the info box (left), the
 *   scroll cue (centre) and an empty spacer (right) — the spacer is what keeps
 *   the cue centred on the viewport rather than on the remaining content.
 * - The info box moved from the right edge to the left.
 * - The cue reads SCROLL TO EXPLORE and is flanked by two arrows, the second
 *   offset 0.28s so the pair reads as a fall rather than a blink.
 * - The lede is reworded, and is 500 weight on #2A3B32 rather than regular on
 *   #33443B — it carries more of the row now that the keys are gone.
 *
 * The lede copy is the bundle's, verbatim. It was briefly rewritten to lead on
 * AI context and to list uploadable materials, then reverted by request — so
 * if that idea comes round again, it has been tried here once already.
 * - Both CTAs grew to 16px/30px and 16px/27px padding at 16.5px.
 *
 * The wordmark is Playfair Display 600 in brand forest (#0C5638), not Archivo
 * 800 in ink, and it arrives through a character scramble. The source defines
 * a `heroWipe` clip-path keyframe but never references it. The v4 DOM
 * `.floating-card` rig is gone, replaced by the WebGL scene rendering into
 * `glCanvasRef` behind this content.
 *
 * The grid is `pointer-events:none` so the draggable WebGL scene underneath
 * stays grabbable through the copy; the CTA cluster opts back in.
 *
 * Entrance timing is a `heroRise` cascade of absolute CSS delays running
 * 1.90s → 3.37s, i.e. starting as the 1.9s intro overlay clears. The values
 * are irregular on purpose — they are hand-tuned, not a computed stagger.
 */

const RISE = 'heroRise 900ms cubic-bezier(0.22,1,0.36,1) both';

/** The cue's chevron, repeated either side of the label. */
function CueArrow({ delay }: { delay?: string }) {
  return (
    <svg
      width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#61726A"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
      style={{ animation: 'cueDrop 2.2s ease-in-out infinite', animationDelay: delay }}
    >
      <path d="M12 5v14M6 13l6 6 6-6" />
    </svg>
  );
}

export function Hero({
  heroCanvasRef,
  glCanvasRef,
  heroContentRef,
  heroText0,
  heroText1,
  /**
   * The bottom legibility band, 0..1. This is the layer the info box and the
   * scroll cue sit on; it fades out by half height, so it barely touches the
   * panels. Lowering it costs text contrast and buys almost no card.
   */
  wash = 1,
  /**
   * The rim + panel radials, 0..1 — the layers that actually veil the WebGL
   * cards. This is the knob to turn when a panel reads washed out.
   */
  sceneWash = 1,
  onBeta,
  onSeeHow,
}: {
  heroCanvasRef: React.RefObject<HTMLCanvasElement | null>;
  glCanvasRef: React.RefObject<HTMLCanvasElement | null>;
  heroContentRef: React.RefObject<HTMLDivElement | null>;
  heroText0: string;
  heroText1: string;
  wash?: number;
  sceneWash?: number;
  onBeta: () => void;
  onSeeHow: () => void;
}) {
  const washOpacity = Math.max(0, Math.min(1, wash));
  const sceneOpacity = Math.max(0, Math.min(1, sceneWash));

  return (
    <section style={{ position: 'relative', minHeight: '100vh', overflow: 'hidden' }}>
      {/* soft blooms. The right one is teal, not a mirror of the green left one. */}
      <div aria-hidden="true" style={{ position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 0, overflow: 'hidden' }}>
        <div style={{ position: 'absolute', top: '-10%', left: '-10%', width: '50vw', height: '50vw', maxWidth: 900, maxHeight: 900, borderRadius: '50%', filter: 'blur(64px)', opacity: 0.7, background: 'rgba(46,125,82,0.22)' }} />
        <div style={{ position: 'absolute', top: '20%', right: '-10%', width: '40vw', height: '40vw', maxWidth: 720, maxHeight: 720, borderRadius: '50%', filter: 'blur(64px)', opacity: 0.7, background: 'rgba(43,140,150,0.2)' }} />
      </div>

      {/* 2D constellation backdrop */}
      <canvas ref={heroCanvasRef} aria-hidden="true" style={{ position: 'absolute', inset: 0, zIndex: 0, width: '100%', height: '100%', display: 'block', opacity: 0.88 }} />
      {/* WebGL scene — panels, constellation, growth field. Draggable, so it
          must claim its own touch handling rather than scrolling the page. */}
      <canvas ref={glCanvasRef} aria-hidden="true" style={{ position: 'absolute', inset: 0, zIndex: 1, width: '100%', height: '100%', display: 'block', touchAction: 'none' }} />

      {/* The veils that pull the scene back under the copy. All three carry the
          source bundle's own values; the split into two opacity groups is ours.

          The source packs them into two elements, with the bottom band and the
          two panel radials sharing one `background` shorthand. They are split
          three ways here because they do different jobs and want different
          strengths: the band is a legibility floor for the info box and cue and
          is already zero by half height, while the rim and the two radials are
          what sit on top of the WebGL panels. Scaling both together — the old
          single `wash` prop — meant you could not clear the cards without also
          thinning the text backing.

          CSS paints the first background layer on top, so the source order puts
          the band above the radials; the z-indexes below preserve that. */}
      {/* rim wash — brightest at the edges, zero at 52%/48% */}
      <div aria-hidden="true" style={{ position: 'absolute', inset: 0, zIndex: 2, pointerEvents: 'none', opacity: sceneOpacity, background: 'radial-gradient(ellipse 88% 74% at 52% 48%, rgba(240,244,242,0) 0%, rgba(240,244,242,0.2) 74%, rgba(240,244,242,0.56) 100%)' }} />
      {/* panel radials — these are the ones that land on the cards */}
      <div aria-hidden="true" style={{ position: 'absolute', inset: 0, zIndex: 3, pointerEvents: 'none', opacity: sceneOpacity, background: 'radial-gradient(ellipse 52% 38% at 16% 22%, rgba(240,244,242,0.66) 0%, rgba(240,244,242,0.26) 52%, rgba(240,244,242,0) 76%), radial-gradient(ellipse 40% 30% at 80% 53%, rgba(240,244,242,0.84) 0%, rgba(240,244,242,0.36) 55%, rgba(240,244,242,0) 82%)' }} />
      {/* bottom legibility band — fully faded by half height */}
      <div aria-hidden="true" style={{ position: 'absolute', inset: 0, zIndex: 4, pointerEvents: 'none', opacity: washOpacity, background: 'linear-gradient(0deg, rgba(240,244,242,0.94) 0%, rgba(240,244,242,0.78) 16%, rgba(240,244,242,0.34) 34%, rgba(240,244,242,0) 50%)' }} />
      {/* fractal-noise grain, multiplied at 3.5% — kills banding in the blooms */}
      <div
        aria-hidden="true"
        style={{
          position: 'absolute', inset: 0, zIndex: 5, pointerEvents: 'none',
          opacity: 0.035, mixBlendMode: 'multiply',
          backgroundImage:
            "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.8' numOctaves='3'/></filter><rect width='160' height='160' filter='url(%23n)'/></svg>\")",
        }}
      />

      <div
        ref={heroContentRef}
        className="hero-grid"
        style={{
          position: 'relative', zIndex: 20, minHeight: '100vh', boxSizing: 'border-box',
          display: 'grid', gridTemplateRows: 'auto 1fr auto', gap: 32,
          // horizontal padding must stay equal to the navbar's
          padding: 'min(13.5vh,120px) max(4.2vw,22px) 34px',
          pointerEvents: 'none',
        }}
      >
        {/* ── lockup ── */}
        <div style={{ minWidth: 0 }}>
          <div
            style={{
              // pulls the tagline up into the wordmark's cap space and indents
              // it to the optical left edge of the S — both values are tied to
              // the wordmark's own clamp, so they hold at every size
              margin: '0 0 -0.78em calc(clamp(5rem,14.6vw,17.6rem) * 0.0485)',
              animation: 'heroRise 800ms cubic-bezier(0.22,1,0.36,1) both',
              animationDelay: '1.90s',
            }}
          >
            <span
              style={{
                fontFamily: "'Playfair Display',serif", fontWeight: 600,
                fontSize: 'clamp(17px,1.72vw,29px)', letterSpacing: '0.035em',
                lineHeight: 1, color: '#33443B', display: 'inline-block',
                // reserves the settled width so the scramble can't reflow the line
                minWidth: '11.5em',
              }}
            >
              {heroText0 || ' '}
            </span>
          </div>
          <h1
            aria-label="Sapling"
            style={{
              margin: 0, fontFamily: "'Playfair Display',serif", fontWeight: 600,
              fontSize: 'clamp(5rem,14.6vw,17.6rem)', lineHeight: 0.92,
              letterSpacing: '-0.02em', color: '#0C5638',
              filter: 'drop-shadow(0 0 34px rgba(240,244,242,0.95)) drop-shadow(0 0 14px rgba(240,244,242,0.9))',
            }}
          >
            {heroText1 || ' '}
          </h1>
        </div>

        {/* ── lede row ── */}
        <div
          className="hero-mid"
          style={{
            display: 'grid', gridTemplateColumns: 'auto minmax(0,auto)',
            alignItems: 'center', justifyContent: 'space-between', gap: 'min(4vw,56px)',
          }}
        >
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 16 }}>
            <div
              style={{
                display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap',
                pointerEvents: 'auto', animation: RISE, animationDelay: '2.84s',
              }}
            >
              <button
                onClick={onBeta}
                className="ld-btn-solid"
                style={{
                  background: '#0C5638', color: '#fff', border: 'none', borderRadius: 6,
                  padding: '16px 30px', fontFamily: "'DM Sans',sans-serif", fontWeight: 600,
                  fontSize: 16.5, cursor: 'pointer',
                  animation: 'betaGlow 2.2s ease-in-out infinite', transition: 'filter 200ms',
                }}
              >
                Sign up for Beta Testing
              </button>
              <button
                onClick={onSeeHow}
                className="ld-ghost"
                style={{
                  background: 'rgba(253,252,249,0.82)', color: '#12201A',
                  border: '1px solid rgba(18,32,26,0.16)', borderRadius: 6,
                  padding: '16px 27px', fontFamily: "'DM Sans',sans-serif", fontWeight: 600,
                  fontSize: 16.5, cursor: 'pointer', display: 'inline-flex',
                  alignItems: 'center', gap: 9,
                  backdropFilter: 'blur(8px)', WebkitBackdropFilter: 'blur(8px)',
                  transition: 'all 220ms',
                }}
              >
                See how it works
                <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M5 12h14M13 6l6 6-6 6" />
                </svg>
              </button>
            </div>
            <p style={{ margin: 0, fontFamily: "'JetBrains Mono',monospace", fontSize: 10.5, letterSpacing: '0.15em', color: '#61726A', animation: RISE, animationDelay: '2.96s' }}>
              * AVAILABLE EXCLUSIVELY TO BOSTON UNIVERSITY STUDENTS
            </p>
          </div>

          <p
            className="hero-lede"
            style={{
              margin: 0, maxWidth: '34ch', fontSize: 'clamp(16px,1.22vw,21px)',
              fontWeight: 500, lineHeight: 1.6, color: '#2A3B32', textWrap: 'pretty',
              animation: RISE, animationDelay: '2.64s',
            }}
          >
            Upload a syllabus. Sapling reads your whole course, learns what you know, and drills
            what is slipping. It works from your own coursework and assignments, not the open web,
            and never hands over the answer.
          </p>
        </div>

        {/* ── bottom band ──
            Info box left, cue centre, empty spacer right. The spacer is load
            bearing: it balances the info box's column so the cue lands on the
            viewport's centre line rather than on the centre of the content. */}
        <div
          className="hero-bottom"
          style={{
            display: 'grid', gridTemplateColumns: 'minmax(0,1fr) auto minmax(0,1fr)',
            alignItems: 'end', gap: 'min(3vw,44px)',
          }}
        >
          <div
            className="hero-info"
            style={{
              justifySelf: 'start', display: 'flex', maxWidth: 480, padding: '18px 20px',
              border: '1px solid rgba(18,32,26,0.12)', borderRadius: 5,
              background: 'rgba(253,252,249,0.7)',
              backdropFilter: 'blur(9px)', WebkitBackdropFilter: 'blur(9px)',
              animation: RISE, animationDelay: '3.22s',
            }}
          >
            <p style={{ margin: 0, fontSize: 14, lineHeight: 1.58, color: '#33443B', textWrap: 'pretty' }}>
              Built by students who were tired of studying blind. Every answer cites the slide it
              came from, so you can check the source yourself.{' '}
              <span style={{ color: '#0C5638', fontWeight: 600 }}>Free through beta.</span>
            </p>
          </div>

          <div
            className="hero-cue"
            style={{
              justifySelf: 'center', display: 'flex', flexDirection: 'column',
              alignItems: 'center', gap: 11, paddingBottom: 4,
              animation: 'heroRise 900ms ease both', animationDelay: '3.37s',
            }}
          >
            <div className="hero-scrollcue" style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
              <CueArrow />
              <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10.5, letterSpacing: '0.3em', color: '#61726A' }}>
                SCROLL TO EXPLORE
              </span>
              <CueArrow delay="0.28s" />
            </div>
          </div>

          <div aria-hidden="true" />
        </div>
      </div>
    </section>
  );
}
