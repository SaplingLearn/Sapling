'use client';

/**
 * Act I — the knowledge graph, as scroll cinema.
 *
 * Ported from `Sapling Landing v5.dc.html`. A 460vh section whose inner
 * sticky 100vh stage holds a canvas the engine draws the graph into. Four
 * captions cross-fade across the scroll; clicking the canvas swaps the whole
 * act into an orbitable explore mode with a concept inspector.
 *
 * The canvas is the only thing that moves per frame, and the engine owns it.
 * Everything here is either static chrome or React state that changes at
 * human speed.
 */

import {
  COURSE, XTIER, XTIER_LABEL, XTIER_ORDER, nodeUses,
  type MasteryTier,
} from '@/lib/landing/course';
import type { BuiltGraph } from '@/lib/landing/engine/graph';

const CAP_LABEL = "The graph";

/** The four caption stages, in scroll order. */
const CAPTIONS = [
  {
    eyebrow: null,
    head: <>A hundred names you don&rsquo;t know <em style={{ color: '#0C5638' }}>yet.</em></>,
    body: "Every concept in your course becomes a node. Right now, they're strangers.",
  },
  {
    eyebrow: CAP_LABEL,
    head: <>You study. They <em style={{ color: '#0C5638' }}>connect.</em></>,
    body: 'Every quiz, note, and card you touch draws an edge. Structure appears.',
  },
  {
    eyebrow: CAP_LABEL,
    head: <>Mastery is the <em style={{ color: '#0C5638' }}>color.</em></>,
    body: null,
  },
];

/** The glow plate behind each caption, so copy stays legible over the graph. */
const CAP_SCRIM: React.CSSProperties = {
  position: 'absolute', left: -58, right: -72, top: -46, bottom: -46,
  pointerEvents: 'none',
  background:
    'radial-gradient(ellipse 62% 58% at 38% 50%, rgba(240,244,242,0.82) 0%, rgba(240,244,242,0.66) 45%, rgba(240,244,242,0.28) 72%, rgba(240,244,242,0) 100%)',
  filter: 'blur(18px)',
};

const CAP_BOX: React.CSSProperties = {
  position: 'absolute', left: 'max(6vw,32px)', top: '50%',
  transform: 'translateY(-50%)', zIndex: 4, maxWidth: '34ch',
  opacity: 0, pointerEvents: 'none',
};

const EYEBROW: React.CSSProperties = {
  position: 'relative', display: 'inline-block',
  fontFamily: "'JetBrains Mono',monospace", fontSize: 10.5,
  letterSpacing: '0.34em', color: '#0C5638', textTransform: 'uppercase',
  textShadow: '0 1px 10px rgba(240,244,242,0.9)',
};

const CAP_H2: React.CSSProperties = {
  position: 'relative', margin: '18px 0 0', fontFamily: "'Playfair Display',serif",
  fontSize: 'clamp(2.4rem,4.6vw,4rem)', fontWeight: 600, lineHeight: 1.06,
  letterSpacing: '-0.02em', color: '#12201A',
  textShadow: '0 2px 26px rgba(240,244,242,0.85)',
};

const CAP_P: React.CSSProperties = {
  position: 'relative', margin: '16px 0 0', color: '#33443B',
  fontSize: 15.5, lineHeight: 1.7, textShadow: '0 1px 14px rgba(240,244,242,0.9)',
};

const MONO_TINY: React.CSSProperties = {
  fontFamily: "'JetBrains Mono',monospace", fontSize: 8.5,
  letterSpacing: '0.22em', color: '#61726A',
};

/** Four blurred blobs that read as out-of-focus foliage at the frame edges. */
const FOLIAGE = [
  { style: { left: '-16%', top: '-12%', width: '46vw', height: '40vw', borderRadius: '48% 62% 55% 45%', background: 'radial-gradient(ellipse at 30% 30%, rgba(176,206,189,0.6), rgba(176,206,189,0) 68%)', filter: 'blur(34px)' } },
  { style: { right: '-18%', top: '-8%', width: '44vw', height: '38vw', borderRadius: '55% 45% 60% 50%', background: 'radial-gradient(ellipse at 70% 30%, rgba(186,214,197,0.55), rgba(186,214,197,0) 68%)', filter: 'blur(38px)' } },
  { style: { left: '-14%', bottom: '-14%', width: '44vw', height: '40vw', borderRadius: '60% 50% 45% 62%', background: 'radial-gradient(ellipse at 35% 60%, rgba(176,206,189,0.6), rgba(176,206,189,0) 68%)', filter: 'blur(36px)' } },
  { style: { right: '-15%', bottom: '-12%', width: '46vw', height: '42vw', borderRadius: '50% 60% 52% 48%', background: 'radial-gradient(ellipse at 65% 62%, rgba(186,214,197,0.55), rgba(186,214,197,0) 68%)', filter: 'blur(40px)' } },
];

export function ActGraph({
  actCanvasRef,
  cinemaRef,
  graph,
  exploring,
  expNode,
  onSelectNode,
  onExitExplore,
  onQuiz,
  onLearn,
}: {
  actCanvasRef: React.RefObject<HTMLCanvasElement | null>;
  cinemaRef: React.RefObject<HTMLDivElement | null>;
  /** Null until the engine has mounted and published its instance. */
  graph: BuiltGraph | null;
  exploring: boolean;
  expNode: number | null;
  onSelectNode: (i: number | null) => void;
  onExitExplore: () => void;
  onQuiz: () => void;
  onLearn: () => void;
}) {
  const nodes = graph?.nodes ?? [];
  // node 0 is the course itself, so it doesn't count toward the tally
  const counts = XTIER_ORDER.reduce((acc, t) => {
    acc[t] = nodes.filter((n, i) => i > 0 && n.tier === t).length;
    return acc;
  }, {} as Record<MasteryTier, number>);

  const node = expNode !== null && nodes[expNode] ? nodes[expNode] : null;
  const neighbours = node && graph ? [...new Set(graph.adj[expNode!] ?? [])] : [];

  return (
    <section
      id="act-graph"
      data-act="1"
      style={{ height: '460vh', position: 'relative' }}
    >
      <div
        style={{
          position: 'sticky', top: 0, height: '100vh', overflow: 'hidden',
          // the first two gradients feather the top and bottom edges so the act
          // dissolves into the light sections rather than butting against them
          background:
            'linear-gradient(180deg, #DCE7DF 0%, rgba(220,231,223,0.7) 6%, rgba(220,231,223,0) 16%), linear-gradient(0deg, #DCE7DF 0%, rgba(220,231,223,0.7) 5%, rgba(220,231,223,0) 14%), radial-gradient(ellipse 90% 80% at 50% 42%, #EAF1EC 0%, #E2ECE5 62%, #DCE7DF 100%)',
        }}
      >
        <div
          aria-hidden="true"
          style={{
            position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 3,
            // fade the blobs out before the stage edge clips their blur —
            // a hard-clipped blur reads as a straight line across the seam
            maskImage: 'linear-gradient(180deg, transparent 0%, #000 14%, #000 86%, transparent 100%)',
            WebkitMaskImage: 'linear-gradient(180deg, transparent 0%, #000 14%, #000 86%, transparent 100%)',
          }}
        >
          {FOLIAGE.map((f, i) => (
            <span key={i} style={{ position: 'absolute', ...f.style } as React.CSSProperties} />
          ))}
        </div>

        <canvas
          ref={actCanvasRef}
          style={{
            position: 'absolute', inset: 0, zIndex: 1, width: '100%', height: '100%',
            cursor: 'grab', touchAction: 'none',
          }}
        />

        {/* captions — the engine cross-fades these by scroll progress */}
        <div
          ref={cinemaRef}
          style={{ position: 'absolute', inset: 0, zIndex: 4, pointerEvents: 'none', transition: 'opacity 520ms ease' }}
        >
          {CAPTIONS.map((c, i) => (
            <div key={i} data-cap={i} style={CAP_BOX}>
              <span aria-hidden="true" style={CAP_SCRIM} />
              {c.eyebrow && <span style={EYEBROW}>{c.eyebrow}</span>}
              <h2 style={CAP_H2}>{c.head}</h2>
              {c.body && <p style={CAP_P}>{c.body}</p>}
              {/* the mastery legend rides along with caption 2 */}
              {i === 2 && (
                <div style={{ position: 'relative', marginTop: 20, display: 'flex', flexDirection: 'column', gap: 10 }}>
                  {XTIER_ORDER.map((t) => (
                    <div key={t} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <span
                        style={{
                          width: 9, height: 9, borderRadius: 99, background: XTIER[t],
                          // only the mastered dot glows
                          boxShadow: t === 'mastered' ? '0 0 10px rgba(14,158,90,0.6)' : undefined,
                        }}
                      />
                      <span
                        style={{
                          fontFamily: "'JetBrains Mono',monospace", fontSize: 11,
                          letterSpacing: '0.14em',
                          color: t === 'mastered' ? '#12201A' : '#33443B',
                        }}
                      >
                        {XTIER_LABEL[t].toUpperCase()}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}

          {/* the closing caption sits low and centred rather than left-aligned */}
          <div data-cap="3" style={{ position: 'absolute', left: 0, right: 0, bottom: '9vh', zIndex: 4, textAlign: 'center', opacity: 0, pointerEvents: 'none' }}>
            <span
              aria-hidden="true"
              style={{
                position: 'absolute', left: '50%', top: -52, bottom: -52,
                width: 'min(1080px,92vw)', transform: 'translateX(-50%)', pointerEvents: 'none',
                background: 'radial-gradient(ellipse 54% 62% at 50% 50%, rgba(240,244,242,0.82) 0%, rgba(240,244,242,0.66) 45%, rgba(240,244,242,0.28) 72%, rgba(240,244,242,0) 100%)',
                filter: 'blur(18px)',
              }}
            />
            <h2
              style={{
                position: 'relative', margin: 0, fontFamily: "'Playfair Display',serif",
                fontSize: 'clamp(3rem,7vw,6.4rem)', fontWeight: 600, lineHeight: 1.02,
                letterSpacing: '-0.025em', color: '#12201A', textShadow: '0 3px 34px rgba(240,244,242,0.85)',
              }}
            >
              See what you <em style={{ color: '#0C5638' }}>know.</em>
            </h2>
            <p style={{ position: 'relative', margin: '14px 0 0', color: '#33443B', fontSize: 16, textShadow: '0 1px 14px rgba(240,244,242,0.9)' }}>
              Your whole semester, one living map, updated as you learn.
            </p>
            <span style={{ position: 'relative', display: 'inline-flex', alignItems: 'center', gap: 8, marginTop: 18, fontFamily: "'JetBrains Mono',monospace", fontSize: 10.5, letterSpacing: '0.22em', color: '#0C5638' }}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#0C5638" strokeWidth="2" strokeLinecap="round">
                <path d="M5 9l-3 3 3 3" /><path d="M9 5l3-3 3 3" /><path d="M15 19l-3 3-3-3" />
                <path d="M19 9l3 3-3 3" /><path d="M2 12h20" /><path d="M12 2v20" />
              </svg>
              DRAG TO ORBIT · CLICK TO EXPLORE
            </span>
          </div>

          {/* stage rail — the engine lights the tick matching the live caption */}
          <div aria-hidden="true" style={{ position: 'absolute', right: 'max(4vw,24px)', top: '50%', transform: 'translateY(-50%)', zIndex: 4, display: 'flex', flexDirection: 'column', gap: 14 }}>
            {[0, 1, 2, 3].map((i) => (
              <span key={i} data-tick={i} style={{ width: 5, height: 26, borderRadius: 99, background: 'rgba(18,32,26,0.14)', transition: 'background 300ms' }} />
            ))}
          </div>
        </div>

        {/* ── explore HUD ── */}
        {exploring && (
          <div style={{ position: 'absolute', inset: 0, zIndex: 6, pointerEvents: 'none', animation: 'panelFade 420ms ease 520ms both' }}>
            <div style={{ position: 'absolute', left: 'max(3vw,20px)', top: 24, display: 'flex', flexDirection: 'column', gap: 4 }}>
              <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11, letterSpacing: '0.28em', color: '#0C5638' }}>{COURSE.code}</span>
              <span style={{ fontFamily: "'Playfair Display',serif", fontSize: 21, fontWeight: 600, color: '#12201A' }}>{COURSE.name}</span>
            </div>

            <div style={{ position: 'absolute', left: 'max(3vw,20px)', bottom: 26, display: 'flex', flexDirection: 'column', gap: 9, padding: '14px 16px', borderRadius: 14, background: 'rgba(253,252,249,0.8)', border: '1px solid rgba(18,32,26,0.10)', backdropFilter: 'blur(10px)', pointerEvents: 'auto' }}>
              <span style={{ ...MONO_TINY, letterSpacing: '0.24em' }}>
                {COURSE.term} · {Math.max(0, nodes.length - 1)} CONCEPTS MAPPED
              </span>
              {XTIER_ORDER.map((t) => (
                <span key={t} style={{ display: 'flex', alignItems: 'center', gap: 9, fontSize: 11.5, color: '#33443B' }}>
                  <span style={{ width: 9, height: 9, borderRadius: 99, flex: '0 0 auto', background: XTIER[t] }} />
                  {XTIER_LABEL[t]}
                  <b style={{ marginLeft: 'auto', fontFamily: "'JetBrains Mono',monospace", fontSize: 10, fontWeight: 400, color: '#61726A' }}>{counts[t]}</b>
                </span>
              ))}
            </div>

            <span style={{ position: 'absolute', left: '50%', bottom: 26, transform: 'translateX(-50%)', fontFamily: "'JetBrains Mono',monospace", fontSize: 9, letterSpacing: '0.22em', color: '#61726A' }}>
              DRAG TO ORBIT · SCROLL TO ZOOM · CLICK A CONCEPT
            </span>

            {node && (
              <div style={{ position: 'absolute', right: 'max(3vw,20px)', top: 78, bottom: 70, width: 'min(340px,32vw)', overflow: 'auto', padding: '22px 22px 20px', borderRadius: 18, background: 'rgba(253,252,249,0.92)', border: '1px solid rgba(18,32,26,0.12)', backdropFilter: 'blur(14px)', pointerEvents: 'auto', animation: 'panelFade 300ms ease both' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
                  <span style={{ width: 10, height: 10, borderRadius: 99, flex: '0 0 auto', background: XTIER[node.tier] }} />
                  <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 8.5, letterSpacing: '0.24em', color: XTIER[node.tier] }}>
                    {XTIER_LABEL[node.tier].toUpperCase()}
                  </span>
                  <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 8, letterSpacing: '0.16em', color: '#61726A' }}>
                    {node.root
                      ? 'COURSE'
                      : node.hub
                        ? `UNIT · ${COURSE.code}`
                        : `${COURSE.code} · ${COURSE.topics[node.topic!].label.toUpperCase()}`}
                  </span>
                  <button
                    onClick={() => onSelectNode(null)}
                    aria-label="Close concept"
                    type="button"
                    style={{ marginLeft: 'auto', width: 24, height: 24, borderRadius: 99, border: '1px solid rgba(18,32,26,0.12)', background: 'transparent', color: '#33443B', cursor: 'pointer', fontSize: 13, lineHeight: 1 }}
                  >
                    ×
                  </button>
                </div>
                <h4 style={{ margin: '12px 0 0', fontFamily: "'Playfair Display',serif", fontSize: 26, fontWeight: 600, lineHeight: 1.15, color: '#12201A' }}>{node.label}</h4>
                <p style={{ margin: '8px 0 0', fontSize: 13, lineHeight: 1.65, color: '#33443B' }}>{node.blurb}</p>

                <div style={{ marginTop: 16, display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span style={{ flex: 1, height: 6, borderRadius: 99, background: 'rgba(18,32,26,0.10)', overflow: 'hidden' }}>
                    <span style={{ display: 'block', height: '100%', borderRadius: 99, transition: 'width 420ms cubic-bezier(0.22,1,0.36,1)', width: `${Math.round(node.mastery * 100)}%`, background: XTIER[node.tier] }} />
                  </span>
                  <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11, color: '#12201A' }}>{Math.round(node.mastery * 100)}%</span>
                </div>
                <span style={{ display: 'block', marginTop: 5, ...MONO_TINY, letterSpacing: '0.16em', color: '#61726A' }}>
                  MASTERY SCORE · UPDATED AFTER EVERY SESSION
                </span>

                <span style={{ display: 'block', marginTop: 18, ...MONO_TINY }}>
                  {neighbours.length} CONNECTED {neighbours.length === 1 ? 'CONCEPT' : 'CONCEPTS'}
                </span>
                <div style={{ marginTop: 8, display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                  {neighbours.map((j) => (
                    <button
                      key={j}
                      onClick={() => onSelectNode(j)}
                      type="button"
                      className="ld-expchip"
                      style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 11px', borderRadius: 99, border: '1px solid rgba(18,32,26,0.14)', background: 'rgba(18,32,26,0.04)', color: '#12201A', fontFamily: "'DM Sans',sans-serif", fontSize: 11.5, cursor: 'pointer', transition: 'all 200ms' }}
                    >
                      <span style={{ width: 7, height: 7, borderRadius: 99, background: XTIER[nodes[j].tier] }} />
                      {nodes[j].label}
                    </button>
                  ))}
                </div>

                <span style={{ display: 'block', marginTop: 18, ...MONO_TINY }}>WHAT SAPLING DOES WITH THIS NODE</span>
                <div style={{ marginTop: 9, display: 'flex', flexDirection: 'column', gap: 10 }}>
                  {nodeUses(node, neighbours.length).map((u, i) => (
                    <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: 3, paddingLeft: 11, borderLeft: '2px solid rgba(12,86,56,0.3)' }}>
                      <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 8.5, letterSpacing: '0.16em', color: '#0C5638' }}>{u.tag}</span>
                      <span style={{ fontSize: 12, lineHeight: 1.6, color: '#33443B' }}>{u.text}</span>
                    </div>
                  ))}
                </div>

                <div style={{ marginTop: 18, display: 'flex', gap: 8 }}>
                  <button onClick={onQuiz} type="button" className="ld-expquiz" style={{ flex: 1, padding: '10px 12px', borderRadius: 9, border: 'none', background: '#0C5638', color: '#fff', fontFamily: "'DM Sans',sans-serif", fontSize: 12.5, fontWeight: 600, cursor: 'pointer', transition: 'background 200ms' }}>
                    Quiz me on this
                  </button>
                  <button onClick={onLearn} type="button" className="ld-explearn" style={{ flex: 1, padding: '10px 12px', borderRadius: 9, border: '1px solid rgba(18,32,26,0.2)', background: 'transparent', color: '#12201A', fontFamily: "'DM Sans',sans-serif", fontSize: 12.5, cursor: 'pointer', transition: 'background 200ms' }}>
                    Ask the tutor
                  </button>
                </div>
                <span style={{ display: 'block', marginTop: 9, ...MONO_TINY, letterSpacing: '0.1em', color: '#61726A' }}>
                  /learn?topic={encodeURIComponent(node.label)}&amp;mode=socratic
                </span>
              </div>
            )}

            <button
              onClick={onExitExplore}
              type="button"
              className="ld-exitexplore"
              style={{ position: 'absolute', right: 'max(3vw,20px)', top: 26, display: 'flex', alignItems: 'center', gap: 8, padding: '9px 16px', borderRadius: 99, border: '1px solid rgba(18,32,26,0.14)', background: 'rgba(253,252,249,0.85)', color: '#33443B', fontFamily: "'JetBrains Mono',monospace", fontSize: 9.5, letterSpacing: '0.2em', cursor: 'pointer', pointerEvents: 'auto', transition: 'all 220ms' }}
            >
              ✕ EXIT EXPLORE
            </button>
          </div>
        )}
      </div>
    </section>
  );
}

/** The band that eases the act's tinted ground back to the page colour.
 *  Transparent at the bottom for the same reason the descent band is
 *  transparent at the top: the sections beyond sit on the washed page
 *  ground, and a solid edge against it shows as a line. */
export function RiseBand() {
  return (
    <div
      aria-hidden="true"
      style={{
        position: 'relative', height: '34vh',
        background:
          'linear-gradient(180deg, #DCE7DF 0%, rgba(220,231,223,0.75) 20%, rgba(220,231,223,0.3) 55%, rgba(220,231,223,0) 100%)',
      }}
    />
  );
}
