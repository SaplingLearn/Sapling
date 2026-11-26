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
import { FadeIn } from '@/components/landing/anim';
import { cn } from "@/lib/cn";

const CAPTIONS = [
  ['Socratic', 'Never hands you the answer. It asks the question that gets you there yourself.'],
  ['Expository', 'Explains it straight: structured, sourced from your materials, at your level.'],
  ['Teachback', 'Flips the desk. You explain, and Sapling names exactly where it breaks down.'],
];

const MOTES: { d: number; s: React.CSSProperties }[] = [
  { d: 0.47, s: { right: '28.6%', top: '4.2%', width: 6.9, height: 6.9, background: '#96B86F', opacity: 0.46, animation: 'nodeFloatA 12.1s ease-in-out -9s infinite' } },
  { d: 0.41, s: { right: '8.9%', top: '56.6%', width: 8.8, height: 8.8, background: '#68951F', opacity: 0.59, boxShadow: '0 0 21px #68951F66', animation: 'nodeFloatB 13.1s ease-in-out -2.1s infinite' } },
  { d: 0.33, s: { right: '8.0%', top: '2.8%', width: 7, height: 7, background: '#68951F', opacity: 0.56, animation: 'nodeFloatB 17.5s ease-in-out -17.2s infinite' } },
  { d: 0.17, s: { right: '12.1%', top: '64.7%', width: 10.5, height: 10.5, background: '#7B9E51', opacity: 0.39, boxShadow: '0 0 25px #7B9E5166', animation: 'nodeFloatA 10s ease-in-out -8.9s infinite' } },
  { d: 0.40, s: { left: '13.5%', top: '94.8%', width: 6.7, height: 6.7, background: '#7B9E51', opacity: 0.56, animation: 'nodeFloatA 15.1s ease-in-out -17.3s infinite' } },
  { d: 0.21, s: { right: '43.6%', top: '5.2%', width: 5.7, height: 5.7, background: '#96B86F', opacity: 0.53, animation: 'nodeFloatB 18.1s ease-in-out -5.2s infinite' } },
  { d: 0.37, s: { right: '10.0%', top: '92.0%', width: 8.1, height: 8.1, background: '#68951F', opacity: 0.58, boxShadow: '0 0 19px #68951F66', animation: 'nodeFloatA 17.8s ease-in-out -16.5s infinite' } },
  { d: 0.22, s: { left: '5.1%', top: '51.6%', width: 4.7, height: 4.7, background: '#B1D28B', opacity: 0.51, animation: 'nodeFloatB 15.6s ease-in-out -1.7s infinite' } },
  { d: 0.46, s: { left: '5.1%', top: '17.7%', width: 7.9, height: 7.9, background: '#597731', opacity: 0.41, boxShadow: '0 0 19px #59773166', animation: 'nodeFloatA 17s ease-in-out -10.1s infinite' } },
  { d: 0.47, s: { left: '35.5%', top: '4.3%', width: 6.5, height: 6.5, background: '#68951F', opacity: 0.56, animation: 'nodeFloatB 14.5s ease-in-out -9.6s infinite' } },
];

/** Viewer distance, and how far each face stands off the prism's axis. */
const PERSPECTIVE = 1600;
const RADIUS = 310;
/**
 * How much the perspective blows the faces up, and the correction for it.
 *
 * A face sitting `RADIUS` closer to the viewer than the prism's origin is
 * drawn `MAG` times larger than its CSS box — but the compositor rasterises
 * the layer at its CSS size and scales the bitmap up afterwards, so every
 * glyph on these three cards was being resampled 24% larger than it was ever
 * drawn. Pushing the prism back by `RADIUS` lands the front face exactly on
 * the perspective origin plane, where the magnification is 1 and the raster
 * is 1:1; `zoom` then scales the whole subtree — box, type and the faces'
 * own translateZ alike — back to the size it occupied before, at full
 * resolution. Measured edge acuity on the front face nearly doubles, and the
 * card's on-screen rect is unchanged at 533x620.
 */
const MAG = PERSPECTIVE / (PERSPECTIVE - RADIUS);

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
    <section id="act-tutor" data-act="3" className="h-[340vh] relative">
      <DragField section="act-tutor" />

      <div
        className="ld-stage sticky top-0 h-screen overflow-hidden flex items-center [background:linear-gradient(180deg,_rgba(234,241,228,0)_0%,_rgba(234,241,228,0.6)_30%,_rgba(234,241,228,0.6)_70%,_rgba(234,241,228,0)_100%)]"
      >
        <div aria-hidden="true" className="absolute inset-0 pointer-events-none overflow-hidden z-0">
          {MOTES.map((m, i) => (
            <span key={i} data-depth={m.d} className="absolute rounded-[99px]" style={{ ...m.s }} />
          ))}
        </div>

        <div className="ld-tutor-grid max-w-305 w-full my-0 mx-auto py-0 px-6 grid grid-cols-[5fr_7fr] gap-8 items-center">
          <div className="ld-tutor-copy relative z-2">
            {/* Wraps only the heading. The [data-tcap] captions
                that follow are driven by the engine's own opacity writes, so
                a second animation on them would fight the scrub. */}
            <FadeIn>
              <h2 className="ld-tutor-h2 m-0 font-display text-[length:clamp(2.4rem,4.8vw,4.2rem)] font-semibold leading-[1.04] tracking-[-0.02em] text-moss-900">
                Three ways to learn this. Your <em className="text-brand-forest">pick.</em>
              </h2>
            </FadeIn>

            <div className="ld-tutor-caps relative mt-5.5 min-h-27.5">
              {CAPTIONS.map(([tag, body], i) => (
                <div key={tag} data-tcap={i} className="absolute inset-0 opacity-0">
                  <span className="font-sans text-sm tracking-[0.01em] text-brand-forest">{tag}</span>
                  <p className="mt-2 mx-0 mb-0 text-moss-700 text-[15.5px] leading-[1.7] max-w-[36ch]">{body}</p>
                </div>
              ))}
            </div>

            {/* the engine fades these in once the act's scroll is spent */}
            <div data-tutor-pills="1" className="ld-tutor-pills flex gap-2 mt-2 opacity-0 pointer-events-none [transition:opacity_400ms_ease]">
              {CAPTIONS.map(([tag], i) => (
                <button
                  key={tag}
                  onClick={() => onSetMode(i)}
                  className={cn("border border-[rgba(68,93,34,0.3)] rounded-[99px] py-[9px] px-4.5 font-sans text-[12.5px] tracking-[0.01em] cursor-pointer [transition:all_250ms]", tutorMode === i ? "bg-brand-forest" : "bg-transparent", tutorMode === i ? "text-bg-panel" : "text-moss-700")}
                >
                  {tag}
                </button>
              ))}
            </div>
          </div>

          <div className="ld-tutor-stage h-[min(66vh,560px)] flex items-center justify-center" style={{ perspective: PERSPECTIVE }}>
            <div className="[transform-style:preserve-3d]" style={{ zoom: MAG, transform: `translateZ(${-RADIUS}px)` }}>
            <div
              ref={carouselRef}
              className="ld-tutor-carousel relative w-[min(430px,44vw)] h-[min(500px,60vh)] [transform-style:preserve-3d] [will-change:transform]"
            >
              {/* ── face 0 · Socratic ── */}
              <div
                data-panel="0"
                data-socratic="1"
                className="absolute inset-0 [backface-visibility:hidden] rounded-xl p-5 box-border overflow-hidden bg-bg-panel border border-paper-200 [box-shadow:0_26px_54px_-22px_rgba(25,31,19,0.3)] grid grid-rows-[auto_minmax(0,1fr)_auto] gap-2.5" style={{ transform: `rotateY(0deg) translateZ(${RADIUS}px)` }}
              >
                <div className="flex items-center justify-between">
                  <span className="font-sans text-sm tracking-[0.01em] text-brand-forest">Socratic mode</span>
                  <span className="font-serif italic text-2xl text-brand-forest">?</span>
                </div>
                <div className="ld-tface-chat min-h-0 flex flex-col justify-between gap-[5px] overflow-hidden">
                  <div className="self-start max-w-[88%] bg-leaf-50 [border-radius:14px_14px_14px_4px] py-2 px-3 text-sm leading-[1.45] text-moss-900">
                    Before rotations: what does the &ldquo;B&rdquo; in BST guarantee about a node&rsquo;s children?
                  </div>
                  <div className="self-end max-w-4/5 bg-brand-forest text-leaf-50 [border-radius:14px_14px_4px_14px] py-2 px-3 text-sm leading-[1.45]">
                    left subtree smaller, right subtree bigger?
                  </div>
                  <div className="self-start max-w-[88%] bg-leaf-50 [border-radius:14px_14px_14px_4px] py-2 px-3 text-sm leading-[1.45] text-moss-900">
                    Right. So what breaks if one side grows far taller?
                  </div>
                  <div className="self-end max-w-4/5 bg-brand-forest text-leaf-50 [border-radius:14px_14px_4px_14px] py-2 px-3 text-sm leading-[1.45]">
                    lookup stops being logarithmic
                  </div>
                </div>
                <div className="flex flex-col gap-[5px] border-t border-t-moss-50 pt-[9px]">
                  <div className="flex items-center gap-1.5">
                    <span className="font-sans text-[9.5px] tracking-[0.01em] text-moss-300">Hint ladder</span>
                    <span className="flex gap-1 ml-0.5">
                      {[true, true, false, false].map((on, i) => (
                        <span key={i} className={cn("w-4.5 h-[3px] rounded-[99px]", on ? "bg-leaf-500" : "bg-moss-100")} />
                      ))}
                    </span>
                    <span className="ml-auto font-sans text-[9px] text-moss-500">2 / 4</span>
                  </div>
                  <span className="ld-tface-note text-xs leading-[1.5] text-moss-400">It escalates only when you stall.</span>
                </div>
              </div>

              {/* ── face 1 · Expository ── */}
              <div
                data-panel="1"
                className="ld-tface-expo absolute inset-0 [backface-visibility:hidden] rounded-xl p-5 box-border overflow-hidden [background:#F6F8F4] border border-paper-200 [box-shadow:0_26px_54px_-22px_rgba(25,31,19,0.3)] grid grid-rows-[auto_auto_auto_minmax(0,1fr)_auto_auto] gap-[9px]"
                style={{ transform: `rotateY(120deg) translateZ(${RADIUS}px)` }}
              >
                <div className="flex items-center justify-between">
                  <span className="font-sans text-sm tracking-[0.01em] text-brand-forest">Expository mode</span>
                  <svg aria-hidden="true" width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="#445D22" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M12 6.5C10.5 5 8.3 4.4 5 4.4c-.6 0-1 .4-1 1v11.4c0 .6.4 1 1 1 3.3 0 5.5.6 7 2.1" />
                    <path d="M12 6.5c1.5-1.5 3.7-2.1 7-2.1.6 0 1 .4 1 1v11.4c0 .6-.4 1-1 1-3.3 0-5.5.6-7 2.1" />
                    <path d="M12 6.5v13.4" />
                  </svg>
                </div>
                <h3 className="m-0 font-display text-xl font-semibold text-moss-900">AVL rotations, plainly.</h3>
                <p className="m-0 text-[12.5px] leading-[1.65] text-moss-700">
                  Every node&rsquo;s <span className="bg-leaf-50 rounded-xs py-0 px-[3px] text-brand-forest font-semibold">balance factor</span> stays in {'{−1, 0, +1}'}. When an insert breaks that, one of four <span className="bg-leaf-50 rounded-xs py-0 px-[3px] text-brand-forest font-semibold">rotations</span> restores it in O(1).
                </p>
                <div className="ld-tface-diagram min-h-0 grid grid-cols-[1fr_auto_1fr] gap-1.5 items-stretch [background:#FDFCF9] border border-paper-200 rounded-[12px] py-[9px] px-2.5 overflow-hidden">
                  <div className="min-h-0 flex flex-col items-center justify-center gap-[5px]">
                    <svg aria-hidden="true" width="100%" height="100%" className="flex-1 min-h-8.5" preserveAspectRatio="xMidYMid meet" viewBox="0 0 120 62">
                      <line x1="82" y1="12" x2="52" y2="34" stroke="#E0E6DA" strokeWidth="1.5" />
                      <line x1="52" y1="34" x2="26" y2="54" stroke="#E0E6DA" strokeWidth="1.5" />
                      <circle cx="82" cy="12" r="9" fill="#E27A63" />
                      <text x="82" y="15.5" textAnchor="middle" className="font-sans" fontSize="8" fill="#FDFCF9">+2</text>
                      <circle cx="52" cy="34" r="7" fill="#7B9E51" />
                      <circle cx="26" cy="54" r="6" fill="#B1D28B" />
                    </svg>
                    <span className="font-sans text-[9px] tracking-[0.01em] text-[#9c4b48]">Left-heavy</span>
                  </div>
                  <span className="self-center font-sans text-xs text-brand-forest">→</span>
                  <div className="min-h-0 flex flex-col items-center justify-center gap-[5px]">
                    <svg aria-hidden="true" width="100%" height="100%" className="flex-1 min-h-8.5" preserveAspectRatio="xMidYMid meet" viewBox="0 0 120 62">
                      <line x1="60" y1="16" x2="34" y2="46" stroke="#7B9E51" strokeWidth="1.5" />
                      <line x1="60" y1="16" x2="88" y2="46" stroke="#7B9E51" strokeWidth="1.5" />
                      <circle cx="60" cy="16" r="9" fill="#445D22" />
                      <text x="60" y="19.5" textAnchor="middle" className="font-sans" fontSize="8" fill="#EAF1E4">0</text>
                      <circle cx="34" cy="46" r="7" fill="#7B9E51" />
                      <circle cx="88" cy="46" r="7" fill="#B1D28B" />
                    </svg>
                    <span className="font-sans text-[9px] tracking-[0.01em] text-brand-forest">After LL rotate</span>
                  </div>
                </div>
                <div className="ld-tface-cases flex items-center gap-[5px]">
                  <span className="font-sans text-[9.5px] tracking-[0.01em] text-moss-300">Four cases</span>
                  {(['LL', 'LR', 'RL', 'RR'] as const).map((t) => {
                    const on = t === 'LL';
                    return (
                      <span
                        key={t}
                        className={cn("flex-1 text-center py-1 px-0 rounded-sm font-sans text-2xs tracking-[0.01em]", on ? "bg-leaf-50" : "bg-bg-panel", on ? "border border-leaf-500" : "border border-paper-200", on ? "text-brand-forest" : "text-moss-400")}
                      >
                        {t}
                      </span>
                    );
                  })}
                </div>
                <div className="flex flex-col gap-[5px] border-t border-t-moss-75 pt-[9px]">
                  <span className="font-sans text-[9.5px] tracking-[0.01em] text-moss-300">Retrieved from your library</span>
                  <div className="flex gap-[5px] flex-wrap">
                    <span className="flex items-center gap-[5px] py-1 px-2 rounded-sm bg-bg-panel border border-moss-100 font-sans text-[8.5px] text-moss-700">
                      <span className="w-[5px] h-[5px] rounded-[99px] bg-leaf-500" />
                      lecture-07.pdf<b className="font-normal text-moss-300">p. 12</b>
                    </span>
                    <span className="flex items-center gap-[5px] py-1 px-2 rounded-sm bg-bg-panel border border-moss-100 font-sans text-[8.5px] text-moss-700">
                      <span className="w-[5px] h-[5px] rounded-[99px] bg-leaf-500" />
                      notes-wk4.md
                    </span>
                  </div>
                </div>
              </div>

              {/* ── face 2 · TeachBack — light like its siblings since the graph act moved off the dark ground ── */}
              <div
                data-panel="2"
                className="ld-tface-teach absolute inset-0 [backface-visibility:hidden] rounded-xl box-border overflow-hidden [background:#FDFCF9] border border-paper-200 [box-shadow:0_26px_54px_-22px_rgba(25,31,19,0.3)] p-4.5 grid grid-rows-[auto_auto_auto_minmax(0,1fr)_auto] gap-2"
                style={{ transform: `rotateY(240deg) translateZ(${RADIUS}px)` }}
              >
                <div className="flex items-center justify-between">
                  <span className="font-sans text-sm tracking-[0.01em] text-brand-forest">Teachback mode</span>
                  <svg aria-hidden="true" width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="#E27A63" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M12 3.5a3 3 0 0 1 3 3v4.5a3 3 0 0 1-6 0V6.5a3 3 0 0 1 3-3z" />
                    <path d="M5.5 10.5v.8a6.5 6.5 0 0 0 13 0v-.8" />
                    <path d="M12 17.8V21" />
                  </svg>
                </div>
                <div className="ld-tface-rec flex items-center gap-2.5">
                  <span className="flex items-end gap-[2.5px] h-6.5">
                    {([['#7B9E51', '1.1s', '0s'], ['#96B86F', '1.3s', '-0.2s'], ['#68951F', '0.9s', '-0.5s'],
                       ['#96B86F', '1.2s', '-0.8s'], ['#7B9E51', '1.0s', '-0.3s'], ['#68951F', '1.4s', '-0.6s'],
                       ['#96B86F', '1.1s', '-0.9s'], ['#7B9E51', '1.25s', '-0.4s'], ['#68951F', '0.95s', '-0.7s']] as const).map(([c, dur, delay], i) => (
                      <span key={i} className="w-[3px] h-full rounded-[2px] [transform-origin:bottom]" style={{ background: c, animation: `waveBar ${dur} ease-in-out ${delay} infinite` }} />
                    ))}
                  </span>
                  <span className="font-sans text-2xs tracking-[0.01em] text-brand-forest">Recording · 0:42</span>
                </div>
                <p className="m-0 text-sm leading-[1.6] text-moss-700">
                  &ldquo;…so you <span className="text-moss-900 font-semibold">rotate left when the right side gets too heavy</span>, and, um, <span className="bg-[rgba(226,122,99,0.16)] border-b-[1.5px] border-b-[#E27A63] rounded-[3px] py-px px-[3px] text-moss-900">the parent just moves down</span>{' '}and it&rsquo;s balanced again…&rdquo;
                </p>
                <div className="ld-tface-cover min-h-0 flex flex-col justify-start gap-[3px] overflow-hidden">
                  <span className="font-sans text-[9.5px] tracking-[0.01em] text-moss-300 mb-0.5">What your explanation covered</span>
                  {([['#68951F', 'Rotation direction', 'Correct'],
                     ['#E27A63', 'Which node becomes root', 'Missing'],
                     ['#c89b5e', 'Subtree reattachment', 'Vague']] as const).map(([c, label, verdict]) => (
                    <div key={label} className="flex items-center gap-2">
                      <span className="w-1.5 h-1.5 rounded-[99px] flex-[0_0_auto]" style={{ background: c }} />
                      <span className="text-[10.5px] text-moss-700">{label}</span>
                      <span className="ml-auto font-sans text-2xs tracking-[0.01em]" style={{ color: c }}>{verdict}</span>
                    </div>
                  ))}
                </div>
                <div className="bg-[rgba(226,122,99,0.12)] border border-[rgba(226,122,99,0.4)] rounded-[12px] py-2 px-[11px]">
                  <span className="font-sans text-xs tracking-[0.01em] text-[#E27A63]">Gap found</span>
                  <p className="mt-[5px] mx-0 mb-0 text-[11.5px] leading-[1.5] text-moss-900">
                    The right child becomes the new root, not the parent.
                  </p>
                  <div className="mt-[7px] flex items-center gap-2">
                    {/* mastery goes DOWN — the gap is new information */}
                    <span className="font-sans text-[9.5px] tracking-[0.01em] text-moss-500">Mastery 24% → 19%</span>
                    <span className="ml-auto font-sans text-[9.5px] tracking-[0.01em] text-brand-forest whitespace-nowrap">Re-explain ↻</span>
                  </div>
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
