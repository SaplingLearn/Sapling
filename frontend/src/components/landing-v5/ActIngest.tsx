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
import { cn } from "@/lib/cn";

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
  { d: 0.25, s: { right: '7.6%', top: '28.1%', width: 5.1, height: 5.1, background: '#B1D28B', opacity: 0.51, animation: 'nodeFloatB 14.9s ease-in-out -11.9s infinite' } },
  { d: 0.37, s: { right: '5.0%', top: '67.2%', width: 7.3, height: 7.3, background: '#68951F', opacity: 0.46, animation: 'nodeFloatB 16s ease-in-out -10.6s infinite' } },
  { d: 0.47, s: { right: 6, top: '50.1%', width: 4.9, height: 4.9, background: '#96B86F', opacity: 0.41, animation: 'nodeFloatB 11.1s ease-in-out -4.1s infinite' } },
  { d: 0.20, s: { right: '27.6%', top: '91.8%', width: 6.4, height: 6.4, background: '#96B86F', opacity: 0.39, animation: 'nodeFloatA 14s ease-in-out -10.4s infinite' } },
  { d: 0.28, s: { right: '12.4%', top: '53.8%', width: 10.8, height: 10.8, background: '#96B86F', opacity: 0.48, boxShadow: '0 0 26px #96B86F66', animation: 'nodeFloatA 19.3s ease-in-out -4.9s infinite' } },
  { d: 0.23, s: { left: '7.0%', top: '92.2%', width: 6.2, height: 6.2, background: '#96B86F', opacity: 0.47, animation: 'nodeFloatA 9.6s ease-in-out -3.7s infinite' } },
  { d: 0.28, s: { right: '2.8%', top: '46.4%', width: 6.5, height: 6.5, background: '#96B86F', opacity: 0.43, animation: 'nodeFloatA 19.9s ease-in-out -15.7s infinite' } },
  { d: 0.38, s: { left: '11.1%', top: '93.8%', width: 9.4, height: 9.4, background: '#96B86F', opacity: 0.47, boxShadow: '0 0 23px #96B86F66', animation: 'nodeFloatB 19.3s ease-in-out -14.1s infinite' } },
  { d: 0.32, s: { right: '5.1%', top: '15.3%', width: 4.2, height: 4.2, background: '#96B86F', opacity: 0.42, animation: 'nodeFloatA 12.7s ease-in-out -2.7s infinite' } },
  { d: 0.29, s: { left: '3.0%', top: '80.8%', width: 7.4, height: 7.4, background: '#96B86F', opacity: 0.35, animation: 'nodeFloatB 11.5s ease-in-out -0.8s infinite' } },
  { d: 0.37, s: { right: '12.4%', top: '63.0%', width: 6.6, height: 6.6, background: '#B1D28B', opacity: 0.52, animation: 'nodeFloatB 16.2s ease-in-out -2.7s infinite' } },
  { d: 0.18, s: { left: '2.9%', top: '45.0%', width: 10.9, height: 10.9, background: '#96B86F', opacity: 0.37, boxShadow: '0 0 26px #96B86F66', animation: 'nodeFloatB 10.9s ease-in-out -8.4s infinite' } },
  { d: 0.36, s: { left: '44.0%', top: '4.5%', width: 5, height: 5, background: '#B1D28B', opacity: 0.57, animation: 'nodeFloatB 12.6s ease-in-out -4.8s infinite' } },
  { d: 0.35, s: { left: '11.2%', top: '43.9%', width: 8.8, height: 8.8, background: '#96B86F', opacity: 0.4, boxShadow: '0 0 21px #96B86F66', animation: 'nodeFloatA 15.2s ease-in-out -13.9s infinite' } },
];

/** The heading. Rendered twice — pinned in the stage from tablet up,
 *  and in the phone intro that scrolls in ahead of the act. */
function IngestHeading() {
  return (
    <FadeIn>
      <h2 className="m-0 font-display text-[length:clamp(2.2rem,4.2vw,3.5rem)] font-semibold leading-[1.05] tracking-[-0.02em] text-moss-900">
        Drop in the whole <em className="text-brand-forest">course.</em>
      </h2>
    </FadeIn>
  );
}

/** The pitch, shared by the same two placements. */
const PITCH = (
  <>
    Ask ChatGPT for practice and you get generic exercises off the internet, then an
    empty box again. It forgets. Sapling works only from{' '}
    <em className="not-italic text-moss-900 font-semibold">your class&rsquo;s</em>{' '}
    material: your professor&rsquo;s slides, the syllabus, lecture notes.
  </>
);

function TileHead({ label, i }: { label: string; i: number }) {
  return (
    <div className="flex items-baseline justify-between">
      <span className="font-sans text-xs tracking-[0.01em] text-brand-forest">{label}</span>
      <div data-tilecount={i} className="font-serif text-[21px] font-semibold leading-none text-moss-900">+0</div>
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
    <>
    {/* Phone only: globals.css shows this ≤640px and hides .ld-ingest-head.
        A pinned stage is one screen, and with the heading and pitch in it the
        scene drew at under half size. Here they scroll in ahead of the act,
        which then pins with the whole screen for the scene. It sits outside
        the section so the act's scrub progress, measured from the section's
        own top, is untouched. */}
    <div className="ld-ingest-intro hidden relative pt-3 px-4.5 pb-0">
      <IngestHeading />
      <p className="mt-4 mx-0 mb-0 text-moss-500 text-[14.5px] leading-[1.65]">{PITCH}</p>
    </div>

    <section id="act-ingest" data-act="2" className="h-[320vh] relative">
      {/* holds no clusters, but the element has to exist — see DragField */}
      <DragField section="act-ingest" />

      <div className="ld-stage sticky top-0 h-screen overflow-hidden flex items-center">
        <div aria-hidden="true" className="absolute inset-0 pointer-events-none overflow-hidden z-0">
          {MOTES.map((m, i) => (
            <span key={i} data-depth={m.d} className="absolute rounded-[99px]" style={{ ...m.s }} />
          ))}
        </div>

        <div ref={ingestSceneRef} className="ld-ingest-scene relative max-w-295 w-full my-0 mx-auto py-0 px-6 flex flex-col gap-6.5">
          <div className="ld-ingest-head flex-[0_0_auto] flex flex-col items-stretch gap-5">
            {/* The heading is ours to animate; the chips, tiles and doc lines
                below are the engine's, addressed by [data-chip] and
                [data-ingest-tile]. Keep the fade off those subtrees. */}
            <IngestHeading />
            <div className="ld-ingest-copy w-full grid grid-cols-[minmax(0,1fr)_minmax(0,520px)] gap-y-3.5 gap-x-[clamp(28px,5vw,72px)] [align-items:start]">
              <p className="ld-ingest-p1 m-0 max-w-[44ch] text-moss-500 text-[14.5px] leading-[1.68]">
                {PITCH}
              </p>
              <p className="ld-ingest-p2 m-0 max-w-[52ch] text-moss-500 text-[14.5px] leading-[1.68]">
                And every student who adds their documents makes the AI understand the course
                better. One person&rsquo;s lecture notes fill a gap in another&rsquo;s slides, so the model
                learns what this professor actually emphasizes, how they word questions, which
                concepts they keep returning to. The more your class contributes, the sharper the
                context gets for everyone in it.
              </p>
            </div>
          </div>

          <div ref={ingestStageRef} className="ld-ingest-stage relative flex-[0_0_auto] h-[min(376px,_44vh)]">
            <div
              data-ingest-fit="1"
              className="ld-ingest-fit absolute left-0 right-0 top-0 h-94 [transform-origin:top_left] grid grid-cols-[minmax(0,1fr)_minmax(0,520px)] gap-[clamp(28px,5vw,72px)] items-stretch"
            >
              {/* ── the document ── */}
              <div
                data-ingest-doc="1"
                data-tilt="1"
                className="ld-ingest-doc relative h-full max-w-85 box-border flex flex-col [background:#FDFCF9] border border-paper-200 rounded-[14px] pt-5.5 px-5.5 pb-6 [box-shadow:0_30px_80px_rgba(25,31,19,0.16)]"
              >
                <div className="flex items-center justify-between">
                  <span className="font-sans text-sm tracking-[0.01em] text-moss-500">CS 112 · syllabus.pdf</span>
                  <span className="w-2 h-2 rounded-[99px] bg-leaf-500" />
                </div>
                <div className="relative flex-1 min-h-0 mt-3.5 overflow-hidden">
                  {/* OCR scan bar sweeping the page */}
                  <span
                    aria-hidden="true"
                    className="absolute -left-5.5 -right-5.5 h-6.5 z-2 pointer-events-none [background:linear-gradient(180deg,_rgba(104,149,31,0)_0%,_rgba(104,149,31,0.13)_60%,_rgba(104,149,31,0.55)_96%,_rgba(104,149,31,0)_100%)] [animation:scanSweep_4.2s_cubic-bezier(0.6,0,0.4,1)_infinite]"
                  />
                  {DOC_LINES.map(([pre, bold, post], i) => (
                    <span
                      key={i}
                      data-docline={i}
                      className="block h-[17px] leading-[17px] text-[8.5px] text-moss-400 whitespace-nowrap overflow-hidden [transition:opacity_200ms_ease]"
                    >
                      {pre}<b className="font-semibold text-moss-700 [box-shadow:inset_0_-4px_0_rgba(104,149,31,0.18)]">{bold}</b>{post}
                    </span>
                  ))}
                </div>
                <div className="mt-3.5 pt-3 border-t border-t-moss-50 flex items-center justify-between">
                  <span className="flex items-center gap-1.5 font-sans text-[9.5px] tracking-[0.01em] text-brand-forest">
                    <span className="w-[5px] h-[5px] rounded-[99px] bg-leaf-500 [animation:ocrBlink_1.4s_ease-in-out_infinite]" />
                    OCR · 4 pages
                  </span>
                  <span className="font-sans text-[9.5px] tracking-[0.01em] text-moss-300">12 concepts found</span>
                </div>
              </div>

              {/* ── destinations ── */}
              <div className="ld-ingest-tiles relative w-full grid grid-cols-[1fr_1fr] [grid-auto-rows:1fr] gap-4">
                <div data-ingest-tile="0" className="bg-bg-panel border border-paper-200 rounded-lg py-3.5 px-[15px] min-h-37.5 relative overflow-hidden flex flex-col gap-[9px] [transition:transform_220ms_ease,_box-shadow_220ms_ease]">
                  <TileHead label="Graph" i={0} />
                  <div aria-hidden="true" className="ld-ingest-graph relative flex-1 rounded-md [background:#F6F8F4] border border-moss-50 overflow-hidden">
                    <svg width="100%" height="100%" viewBox="0 0 230 84" preserveAspectRatio="xMidYMid meet">
                      <line x1="115" y1="42" x2="52" y2="20" stroke="rgba(68,93,34,0.24)" />
                      <line x1="115" y1="42" x2="44" y2="64" stroke="rgba(68,93,34,0.24)" />
                      <line x1="115" y1="42" x2="186" y2="24" stroke="rgba(68,93,34,0.24)" />
                      <line x1="115" y1="42" x2="176" y2="66" stroke="rgba(68,93,34,0.14)" />
                      <circle cx="115" cy="42" r="8" fill="#68951F" />
                      <text x="115" y="45" textAnchor="middle" className="font-sans" fontSize="6.5" fill="#FDFCF9">112</text>
                      <circle cx="52" cy="20" r="4.5" fill="#7B9E51" /><text x="52" y="12" textAnchor="middle" className="font-sans" fontSize="7" fill="#91978B">Trees</text>
                      <circle cx="44" cy="64" r="4.5" fill="#7B9E51" /><text x="44" y="78" textAnchor="middle" className="font-sans" fontSize="7" fill="#91978B">Hashing</text>
                      <circle cx="186" cy="24" r="4.5" fill="#7B9E51" /><text x="186" y="16" textAnchor="middle" className="font-sans" fontSize="7" fill="#91978B">Graphs</text>
                      <circle cx="176" cy="66" r="4" fill="#C7CBC2" /><text x="176" y="79" textAnchor="middle" className="font-sans" fontSize="7" fill="#9FA49A">DP</text>
                    </svg>
                    <span className="absolute left-[9px] bottom-1.5 font-sans text-[8.5px] tracking-[0.01em] text-moss-300">
                      Mastery 0%  ·  Unexplored
                    </span>
                  </div>
                </div>

                <div data-ingest-tile="1" className="bg-bg-panel border border-paper-200 rounded-lg py-3.5 px-[15px] min-h-37.5 relative overflow-hidden flex flex-col gap-[9px] [transition:transform_220ms_ease,_box-shadow_220ms_ease]">
                  <TileHead label="Flashcards" i={1} />
                  <div aria-hidden="true" className="flex-1 flex flex-col gap-1.5">
                    <div className="flex-1 rounded-[9px] bg-moss-25 border border-moss-75 py-2 px-2.5 flex flex-col gap-[3px] justify-center">
                      <span className="font-sans text-[8px] tracking-[0.01em] text-moss-300">Front · Auto-generated</span>
                      <span className="font-serif text-xs font-semibold leading-[1.25] text-moss-900">What does Big-O actually bound?</span>
                    </div>
                    <div className="flex gap-1">
                      {([['Forgot', 'rgba(178,88,85,0.4)', 'rgba(178,88,85,0.08)', '#9c4b48'],
                         ['Hard', 'rgba(200,155,94,0.4)', 'rgba(200,155,94,0.08)', '#8a6636'],
                         ['Easy', 'rgba(90,120,52,0.4)', 'rgba(90,120,52,0.08)', '#4a622b']] as const).map(([t, bd, bg, fg]) => (
                        <span key={t} className="flex-1 text-center py-[3px] px-0 rounded-[5px] font-sans text-[6.5px]" style={{ border: `1px solid ${bd}`, background: bg, color: fg }}>{t}</span>
                      ))}
                    </div>
                  </div>
                </div>

                <div data-ingest-tile="2" className="bg-bg-panel border border-paper-200 rounded-lg py-3.5 px-[15px] min-h-37.5 relative overflow-hidden flex flex-col gap-[9px] [transition:transform_220ms_ease,_box-shadow_220ms_ease]">
                  <TileHead label="Calendar" i={2} />
                  <div aria-hidden="true" className="flex-1 flex flex-col gap-1 justify-center">
                    {([['#b25855', 'Oct 14', 'Midterm · in class'],
                       ['#68951F', 'Oct 18', 'PS 3 · Gradescope'],
                       ['#7B9E51', 'Dec 09', 'Final · cumulative']] as const).map(([c, d, t]) => (
                      <div key={d} className="flex items-center gap-[7px] py-1 px-[7px] rounded-sm bg-moss-25 border border-moss-50">
                        <span className="w-[3px] h-[15px] rounded-[2px] flex-[0_0_auto]" style={{ background: c }} />
                        <span className="font-sans text-[8px] tracking-[0.01em] text-moss-300 flex-[0_0_auto]">{d}</span>
                        <span className="text-[8.5px] text-moss-700 whitespace-nowrap overflow-hidden text-ellipsis">{t}</span>
                      </div>
                    ))}
                    <span className="font-sans text-[8px] tracking-[0.01em] text-brand-forest pl-0.5">Synced to Google calendar</span>
                  </div>
                </div>

                <div data-ingest-tile="3" className="bg-bg-panel border border-paper-200 rounded-lg py-3.5 px-[15px] min-h-37.5 relative overflow-hidden flex flex-col gap-[9px] [transition:transform_220ms_ease,_box-shadow_220ms_ease]">
                  <TileHead label="Quiz bank" i={3} />
                  <div aria-hidden="true" className="flex-1 flex flex-col gap-[5px] justify-center">
                    <span className="text-[9px] leading-[1.35] text-moss-900 font-semibold">Worst-case lookup in a hash map with chaining?</span>
                    <div className="flex flex-col gap-[3px]">
                      <span className="flex gap-[5px] py-[3px] px-[7px] rounded-[5px] border border-paper-300 bg-moss-25 text-[8px] text-moss-500">
                        <b className="font-sans text-[7px] font-normal text-moss-300">A.</b>O(1)
                      </span>
                      <span className="flex gap-[5px] py-[3px] px-[7px] rounded-[5px] border border-leaf-500 bg-leaf-50 text-[8px] text-brand-forest font-semibold">
                        <b className="font-sans text-[7px] font-normal text-leaf-500">B.</b>O(n)
                      </span>
                    </div>
                    <span className="font-sans text-[8px] tracking-[0.01em] text-moss-300">Difficulty adapts to your answers</span>
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
                    className={cn("absolute left-0 top-0 z-5 opacity-0 py-1.5 px-3 rounded-[99px] font-sans text-[12.5px] tracking-[0.01em] whitespace-nowrap [will-change:transform]", dark ? "bg-brand-forest" : "bg-bg-panel", dark ? "" : "border border-moss-100", dark ? "text-leaf-50" : "text-moss-700", dark ? "[box-shadow:0_8px_24px_rgba(68,93,34,0.3)]" : "[box-shadow:0_8px_24px_rgba(25,31,19,0.12)]")}
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
    </>
  );
}
