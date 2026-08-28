'use client';

/**
 * Act II — ingest.
 *
 * Ported from `Sapling Landing v5.dc.html`. A 320vh section pinned to a
 * sticky 100vh stage: a syllabus document on the left, four destination
 * tiles on the right, and twelve concept chips that fly from a line of the
 * document to the tile that consumes it as scroll advances.
 *
 * Every moving part is engine-driven through data attributes, which is why
 * this file is almost entirely static markup:
 *
 *   [data-ingest-fit]   the stage's scale, fitted to the viewport
 *   [data-ingest-doc]   the document's tilt
 *   [data-docline]      per-line opacity, dimmed once its chip has left
 *   [data-chip]         the flight, positioned from measured line/tile rects
 *   [data-tilecount]    the +N counter on each destination
 *   [data-depth]        parallax on the decorative node field
 *
 * The measure pass reads those rects; nothing here reads layout itself.
 */

import { DragField } from './DragField';
import { FadeIn } from '@/components/landing/anim';

/** Syllabus lines. The bold span is the concept a chip carries away. */
const DOC_LINES: [string, string, string][] = [
  ['Wk 1 · ', 'Binary search trees', ': insert, search'],
  ['Wk 2 · ', 'Big-O notation', ': growth rates'],
  ['', 'Midterm · Oct 14', ': in class, Ch. 1 to 6'],
  ['Wk 4 · ', 'Recursion', ': base cases, stack depth'],
  ['Wk 5 · ', 'Hash maps', ': collisions, load factor'],
  ['Wk 6 · ', 'Graph traversal', ': BFS, DFS'],
  ['', 'PS 3 · due Fri', ' 11:59pm, Gradescope'],
  ['Wk 8 · ', 'Dynamic programming', ': memo tables'],
  ['Wk 9 · ', 'Heaps', ' and priority queues'],
  ['Wk 10 · ', 'Memoization', ' vs tabulation'],
  ['', 'Final · Dec 9', ': cumulative, 3 hrs'],
  ['Wk 12 · ', "Dijkstra's algorithm", ': shortest paths'],
];

/** label, destination tile, source line. Tile 0 (the graph) gets the dark chip. */
const CHIPS: [string, number, number][] = [
  ['Binary search trees', 0, 0],
  ['Big-O notation', 1, 1],
  ['Midterm · Oct 14', 2, 2],
  ['Recursion', 3, 3],
  ['Hash maps', 0, 4],
  ['Graph traversal', 1, 5],
  ['PS 3 · due Fri', 2, 6],
  ['Dynamic programming', 0, 7],
  ['Heaps', 3, 8],
  ['Memoization', 1, 9],
  ['Final · Dec 9', 2, 10],
  ["Dijkstra's algorithm", 3, 11],
];

/** Decorative float field. `d` is the parallax depth the engine reads. */
const MOTES: { d: number; s: React.CSSProperties }[] = [
  { d: 0.25, s: { right: '7.6%', top: '28.1%', width: 5.1, height: 5.1, background: '#8FD9A8', opacity: 0.51, animation: 'nodeFloatB 14.9s ease-in-out -11.9s infinite' } },
  { d: 0.37, s: { right: '5.0%', top: '67.2%', width: 7.3, height: 7.3, background: '#0E9E5A', opacity: 0.46, animation: 'nodeFloatB 16s ease-in-out -10.6s infinite' } },
  { d: 0.47, s: { right: 6, top: '50.1%', width: 4.9, height: 4.9, background: '#6FBF8F', opacity: 0.41, animation: 'nodeFloatB 11.1s ease-in-out -4.1s infinite' } },
  { d: 0.20, s: { right: '27.6%', top: '91.8%', width: 6.4, height: 6.4, background: '#6FBF8F', opacity: 0.39, animation: 'nodeFloatA 14s ease-in-out -10.4s infinite' } },
  { d: 0.28, s: { right: '12.4%', top: '53.8%', width: 10.8, height: 10.8, background: '#6FBF8F', opacity: 0.48, boxShadow: '0 0 26px #6FBF8F66', animation: 'nodeFloatA 19.3s ease-in-out -4.9s infinite' } },
  { d: 0.23, s: { left: '7.0%', top: '92.2%', width: 6.2, height: 6.2, background: '#6FBF8F', opacity: 0.47, animation: 'nodeFloatA 9.6s ease-in-out -3.7s infinite' } },
  { d: 0.28, s: { right: '2.8%', top: '46.4%', width: 6.5, height: 6.5, background: '#6FBF8F', opacity: 0.43, animation: 'nodeFloatA 19.9s ease-in-out -15.7s infinite' } },
  { d: 0.38, s: { left: '11.1%', top: '93.8%', width: 9.4, height: 9.4, background: '#6FBF8F', opacity: 0.47, boxShadow: '0 0 23px #6FBF8F66', animation: 'nodeFloatB 19.3s ease-in-out -14.1s infinite' } },
  { d: 0.32, s: { right: '5.1%', top: '15.3%', width: 4.2, height: 4.2, background: '#6FBF8F', opacity: 0.42, animation: 'nodeFloatA 12.7s ease-in-out -2.7s infinite' } },
  { d: 0.29, s: { left: '3.0%', top: '80.8%', width: 7.4, height: 7.4, background: '#6FBF8F', opacity: 0.35, animation: 'nodeFloatB 11.5s ease-in-out -0.8s infinite' } },
  { d: 0.37, s: { right: '12.4%', top: '63.0%', width: 6.6, height: 6.6, background: '#8FD9A8', opacity: 0.52, animation: 'nodeFloatB 16.2s ease-in-out -2.7s infinite' } },
  { d: 0.18, s: { left: '2.9%', top: '45.0%', width: 10.9, height: 10.9, background: '#6FBF8F', opacity: 0.37, boxShadow: '0 0 26px #6FBF8F66', animation: 'nodeFloatB 10.9s ease-in-out -8.4s infinite' } },
  { d: 0.36, s: { left: '44.0%', top: '4.5%', width: 5, height: 5, background: '#8FD9A8', opacity: 0.57, animation: 'nodeFloatB 12.6s ease-in-out -4.8s infinite' } },
  { d: 0.35, s: { left: '11.2%', top: '43.9%', width: 8.8, height: 8.8, background: '#6FBF8F', opacity: 0.4, boxShadow: '0 0 21px #6FBF8F66', animation: 'nodeFloatA 15.2s ease-in-out -13.9s infinite' } },
];

const MONO: React.CSSProperties = { fontFamily: "'JetBrains Mono',monospace" };
const TILE: React.CSSProperties = {
  background: '#FDFCF9', border: '1px solid #E8E5DA', borderRadius: 16,
  padding: '14px 15px', minHeight: 150, position: 'relative', overflow: 'hidden',
  display: 'flex', flexDirection: 'column', gap: 9,
  transition: 'transform 220ms ease, box-shadow 220ms ease',
};
const TILE_LABEL: React.CSSProperties = { ...MONO, fontSize: 9, letterSpacing: '0.24em', color: '#0C5638' };
const TILE_COUNT: React.CSSProperties = { fontFamily: "'Playfair Display',serif", fontSize: 21, fontWeight: 600, lineHeight: 1, color: '#12201A' };
/** Underline that marks a concept inside the document. */
const MARK: React.CSSProperties = { fontWeight: 600, color: '#33443B', boxShadow: 'inset 0 -4px 0 rgba(14,158,90,0.18)' };

function TileHead({ label, i }: { label: string; i: number }) {
  return (
    <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
      <span style={TILE_LABEL}>{label}</span>
      <div data-tilecount={i} style={TILE_COUNT}>+0</div>
    </div>
  );
}

export function ActIngest({
  ingestSceneRef,
  ingestStageRef,
}: {
  ingestSceneRef: React.RefObject<HTMLDivElement | null>;
  ingestStageRef: React.RefObject<HTMLDivElement | null>;
}) {
  return (
    <section id="act-ingest" data-act="2" style={{ height: '320vh', position: 'relative' }}>
      {/* holds no clusters, but the element has to exist — see DragField */}
      <DragField section="act-ingest" />

      <div style={{ position: 'sticky', top: 0, height: '100vh', overflow: 'hidden', display: 'flex', alignItems: 'center' }}>
        <div aria-hidden="true" style={{ position: 'absolute', inset: 0, pointerEvents: 'none', overflow: 'hidden', zIndex: 0 }}>
          {MOTES.map((m, i) => (
            <span key={i} data-depth={m.d} style={{ position: 'absolute', borderRadius: 99, ...m.s }} />
          ))}
        </div>

        <div ref={ingestSceneRef} style={{ position: 'relative', maxWidth: 1180, width: '100%', margin: '0 auto', padding: '0 24px', display: 'flex', flexDirection: 'column', gap: 26 }}>
          <div style={{ flex: '0 0 auto', display: 'flex', flexDirection: 'column', alignItems: 'stretch', gap: 20 }}>
            {/* The heading is ours to animate; the chips, tiles and doc lines
                below are the engine's, addressed by [data-chip] and
                [data-ingest-tile]. Keep the fade off those subtrees. */}
            <FadeIn>
              <span style={{ ...MONO, fontSize: 10.5, letterSpacing: '0.34em', color: '#0C5638', textTransform: 'uppercase' }}>Ingest</span>
              <h2 style={{ margin: '14px 0 0', fontFamily: "'Playfair Display',serif", fontSize: 'clamp(2.2rem,4.2vw,3.5rem)', fontWeight: 600, lineHeight: 1.05, letterSpacing: '-0.02em', color: '#12201A' }}>
                Drop in the whole <em style={{ color: '#0C5638' }}>course.</em>
              </h2>
            </FadeIn>
            <div style={{ width: '100%', display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,520px)', gap: '14px clamp(28px,5vw,72px)', alignItems: 'start' }}>
              <p style={{ margin: 0, maxWidth: '44ch', color: '#61726A', fontSize: 14.5, lineHeight: 1.68 }}>
                Ask ChatGPT for practice and you get generic exercises off the internet, then an
                empty box again. It forgets. Sapling works only from{' '}
                <em style={{ fontStyle: 'normal', color: '#12201A', fontWeight: 600 }}>your class&rsquo;s</em>{' '}
                material: your professor&rsquo;s slides, the syllabus, lecture notes.
              </p>
              <p style={{ margin: 0, maxWidth: '52ch', color: '#61726A', fontSize: 14.5, lineHeight: 1.68 }}>
                And every student who adds their documents makes the AI understand the course
                better. One person&rsquo;s lecture notes fill a gap in another&rsquo;s slides, so the model
                learns what this professor actually emphasizes, how they word questions, which
                concepts they keep returning to. The more your class contributes, the sharper the
                context gets for everyone in it.
              </p>
            </div>
          </div>

          <div ref={ingestStageRef} style={{ position: 'relative', flex: '0 0 auto', height: 'min(376px, 44vh)' }}>
            <div
              data-ingest-fit="1"
              style={{
                position: 'absolute', left: 0, right: 0, top: 0, height: 376,
                transformOrigin: 'top left', display: 'grid',
                gridTemplateColumns: 'minmax(0,1fr) minmax(0,520px)',
                gap: 'clamp(28px,5vw,72px)', alignItems: 'stretch',
              }}
            >
              {/* ── the document ── */}
              <div
                data-ingest-doc="1"
                data-tilt="1"
                style={{ position: 'relative', height: '100%', maxWidth: 340, boxSizing: 'border-box', display: 'flex', flexDirection: 'column', background: '#FDFCF9', border: '1px solid #E8E5DA', borderRadius: 14, padding: '22px 22px 24px', boxShadow: '0 30px 80px rgba(18,32,26,0.16)' }}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span style={{ ...MONO, fontSize: 10, letterSpacing: '0.2em', color: '#61726A' }}>CS 112 · SYLLABUS.PDF</span>
                  <span style={{ width: 8, height: 8, borderRadius: 99, background: '#0E9E5A' }} />
                </div>
                <div style={{ position: 'relative', flex: 1, minHeight: 0, marginTop: 14, overflow: 'hidden' }}>
                  {/* OCR scan bar sweeping the page */}
                  <span
                    aria-hidden="true"
                    style={{ position: 'absolute', left: -22, right: -22, height: 26, zIndex: 2, pointerEvents: 'none', background: 'linear-gradient(180deg, rgba(14,158,90,0) 0%, rgba(14,158,90,0.13) 60%, rgba(14,158,90,0.55) 96%, rgba(14,158,90,0) 100%)', animation: 'scanSweep 4.2s cubic-bezier(0.6,0,0.4,1) infinite' }}
                  />
                  {DOC_LINES.map(([pre, bold, post], i) => (
                    <span
                      key={i}
                      data-docline={i}
                      style={{ display: 'block', height: 17, lineHeight: '17px', fontSize: 8.5, color: '#8B9891', whiteSpace: 'nowrap', overflow: 'hidden', transition: 'opacity 200ms ease' }}
                    >
                      {pre}<b style={MARK}>{bold}</b>{post}
                    </span>
                  ))}
                </div>
                <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid #EBF1EC', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span style={{ display: 'flex', alignItems: 'center', gap: 6, ...MONO, fontSize: 8, letterSpacing: '0.16em', color: '#0C5638' }}>
                    <span style={{ width: 5, height: 5, borderRadius: 99, background: '#0E9E5A', animation: 'ocrBlink 1.4s ease-in-out infinite' }} />
                    OCR · 4 PAGES
                  </span>
                  <span style={{ ...MONO, fontSize: 8, letterSpacing: '0.16em', color: '#9AA5A0' }}>12 CONCEPTS FOUND</span>
                </div>
              </div>

              {/* ── destinations ── */}
              <div style={{ position: 'relative', width: '100%', display: 'grid', gridTemplateColumns: '1fr 1fr', gridAutoRows: '1fr', gap: 16 }}>
                <div data-ingest-tile="0" style={TILE}>
                  <TileHead label="GRAPH" i={0} />
                  <div aria-hidden="true" style={{ position: 'relative', flex: 1, borderRadius: 10, background: '#F6F8F4', border: '1px solid #EBF1EC', overflow: 'hidden' }}>
                    <svg width="100%" height="100%" viewBox="0 0 230 84" preserveAspectRatio="xMidYMid meet">
                      <line x1="115" y1="42" x2="52" y2="20" stroke="rgba(12,86,56,0.24)" />
                      <line x1="115" y1="42" x2="44" y2="64" stroke="rgba(12,86,56,0.24)" />
                      <line x1="115" y1="42" x2="186" y2="24" stroke="rgba(12,86,56,0.24)" />
                      <line x1="115" y1="42" x2="176" y2="66" stroke="rgba(12,86,56,0.14)" />
                      <circle cx="115" cy="42" r="8" fill="#0E9E5A" />
                      <text x="115" y="45" textAnchor="middle" fontFamily="JetBrains Mono" fontSize="6.5" fill="#FDFCF9">112</text>
                      <circle cx="52" cy="20" r="4.5" fill="#4FA574" /><text x="52" y="12" textAnchor="middle" fontFamily="DM Sans" fontSize="7" fill="#8B9891">Trees</text>
                      <circle cx="44" cy="64" r="4.5" fill="#4FA574" /><text x="44" y="78" textAnchor="middle" fontFamily="DM Sans" fontSize="7" fill="#8B9891">Hashing</text>
                      <circle cx="186" cy="24" r="4.5" fill="#4FA574" /><text x="186" y="16" textAnchor="middle" fontFamily="DM Sans" fontSize="7" fill="#8B9891">Graphs</text>
                      <circle cx="176" cy="66" r="4" fill="#C3CCC6" /><text x="176" y="79" textAnchor="middle" fontFamily="DM Sans" fontSize="7" fill="#9AA5A0">DP</text>
                    </svg>
                    <span style={{ position: 'absolute', left: 9, bottom: 6, ...MONO, fontSize: 7, letterSpacing: '0.14em', color: '#9AA5A0' }}>
                      MASTERY 0%  ·  UNEXPLORED
                    </span>
                  </div>
                </div>

                <div data-ingest-tile="1" style={TILE}>
                  <TileHead label="FLASHCARDS" i={1} />
                  <div aria-hidden="true" style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 6 }}>
                    <div style={{ flex: 1, borderRadius: 9, background: '#F6F8F4', border: '1px solid #E3EBE5', padding: '8px 10px', display: 'flex', flexDirection: 'column', gap: 3, justifyContent: 'center' }}>
                      <span style={{ ...MONO, fontSize: 6.5, letterSpacing: '0.2em', color: '#9AA5A0' }}>FRONT · AUTO-GENERATED</span>
                      <span style={{ fontFamily: "'Playfair Display',serif", fontSize: 11, fontWeight: 600, lineHeight: 1.25, color: '#12201A' }}>What does Big-O actually bound?</span>
                    </div>
                    <div style={{ display: 'flex', gap: 4 }}>
                      {([['FORGOT', 'rgba(178,88,85,0.4)', 'rgba(178,88,85,0.08)', '#9c4b48'],
                         ['HARD', 'rgba(200,155,94,0.4)', 'rgba(200,155,94,0.08)', '#8a6636'],
                         ['EASY', 'rgba(58,125,78,0.4)', 'rgba(58,125,78,0.08)', '#2f6640']] as const).map(([t, bd, bg, fg]) => (
                        <span key={t} style={{ flex: 1, textAlign: 'center', padding: '3px 0', borderRadius: 5, border: `1px solid ${bd}`, background: bg, ...MONO, fontSize: 6.5, color: fg }}>{t}</span>
                      ))}
                    </div>
                  </div>
                </div>

                <div data-ingest-tile="2" style={TILE}>
                  <TileHead label="CALENDAR" i={2} />
                  <div aria-hidden="true" style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 4, justifyContent: 'center' }}>
                    {([['#b25855', 'OCT 14', 'Midterm · in class'],
                       ['#0E9E5A', 'OCT 18', 'PS 3 · Gradescope'],
                       ['#4FA574', 'DEC 09', 'Final · cumulative']] as const).map(([c, d, t]) => (
                      <div key={d} style={{ display: 'flex', alignItems: 'center', gap: 7, padding: '4px 7px', borderRadius: 6, background: '#F6F8F4', border: '1px solid #EBF1EC' }}>
                        <span style={{ width: 3, height: 15, borderRadius: 2, background: c, flex: '0 0 auto' }} />
                        <span style={{ ...MONO, fontSize: 6.5, letterSpacing: '0.1em', color: '#9AA5A0', flex: '0 0 auto' }}>{d}</span>
                        <span style={{ fontSize: 8.5, color: '#33443B', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{t}</span>
                      </div>
                    ))}
                    <span style={{ ...MONO, fontSize: 6.5, letterSpacing: '0.14em', color: '#0C5638', paddingLeft: 2 }}>SYNCED TO GOOGLE CALENDAR</span>
                  </div>
                </div>

                <div data-ingest-tile="3" style={TILE}>
                  <TileHead label="QUIZ BANK" i={3} />
                  <div aria-hidden="true" style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 5, justifyContent: 'center' }}>
                    <span style={{ fontSize: 9, lineHeight: 1.35, color: '#12201A', fontWeight: 600 }}>Worst-case lookup in a hash map with chaining?</span>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                      <span style={{ display: 'flex', gap: 5, padding: '3px 7px', borderRadius: 5, border: '1px solid #E3E0D5', background: '#F6F8F4', fontSize: 8, color: '#61726A' }}>
                        <b style={{ ...MONO, fontSize: 7, fontWeight: 400, color: '#9AA5A0' }}>A.</b>O(1)
                      </span>
                      <span style={{ display: 'flex', gap: 5, padding: '3px 7px', borderRadius: 5, border: '1px solid #0E9E5A', background: '#E6F2E8', fontSize: 8, color: '#0C5638', fontWeight: 600 }}>
                        <b style={{ ...MONO, fontSize: 7, fontWeight: 400, color: '#0E9E5A' }}>B.</b>O(n)
                      </span>
                    </div>
                    <span style={{ ...MONO, fontSize: 6.5, letterSpacing: '0.14em', color: '#9AA5A0' }}>DIFFICULTY ADAPTS TO YOUR ANSWERS</span>
                  </div>
                </div>
              </div>

              {/* ── flying concept chips ── */}
              {CHIPS.map(([label, dest, line], i) => {
                const dark = dest === 0;
                return (
                  <span
                    key={i}
                    data-chip={i}
                    data-dest={dest}
                    data-line={line}
                    style={{
                      position: 'absolute', left: 0, top: 0, zIndex: 5, opacity: 0,
                      padding: '6px 12px', borderRadius: 99,
                      background: dark ? '#0C5638' : '#FDFCF9',
                      border: dark ? undefined : '1px solid #DCE7DE',
                      color: dark ? '#E6F2E8' : '#33443B',
                      ...MONO, fontSize: 10.5, letterSpacing: '0.08em', whiteSpace: 'nowrap',
                      boxShadow: dark ? '0 8px 24px rgba(12,86,56,0.3)' : '0 8px 24px rgba(18,32,26,0.12)',
                      willChange: 'transform',
                    }}
                  >
                    {label}
                  </span>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
