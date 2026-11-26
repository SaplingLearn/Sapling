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
import { cn } from "@/lib/cn";

/** The four caption stages, in scroll order. */
const CAPTIONS = [
  {
    head: <>A hundred names you don&rsquo;t know <em className="text-brand-forest">yet.</em></>,
    body: "Every concept in your course becomes a node. Right now, they're strangers.",
  },
  {
    head: <>You study. They <em className="text-brand-forest">connect.</em></>,
    body: 'Every quiz, note, and card you touch draws an edge. Structure appears.',
  },
  {
    head: <>Mastery is the <em className="text-brand-forest">color.</em></>,
    body: null,
  },
];

/** Four blurred blobs that read as out-of-focus foliage at the frame edges. */
const FOLIAGE = [
  { style: { left: '-16%', top: '-12%', width: '46vw', height: '40vw', borderRadius: '48% 62% 55% 45%', background: 'radial-gradient(ellipse at 30% 30%, rgba(190,203,176,0.6), rgba(190,203,176,0) 68%)', filter: 'blur(34px)' } },
  { style: { right: '-18%', top: '-8%', width: '44vw', height: '38vw', borderRadius: '55% 45% 60% 50%', background: 'radial-gradient(ellipse at 70% 30%, rgba(198,211,185,0.55), rgba(198,211,185,0) 68%)', filter: 'blur(38px)' } },
  { style: { left: '-14%', bottom: '-14%', width: '44vw', height: '40vw', borderRadius: '60% 50% 45% 62%', background: 'radial-gradient(ellipse at 35% 60%, rgba(190,203,176,0.6), rgba(190,203,176,0) 68%)', filter: 'blur(36px)' } },
  { style: { right: '-15%', bottom: '-12%', width: '46vw', height: '42vw', borderRadius: '50% 60% 52% 48%', background: 'radial-gradient(ellipse at 65% 62%, rgba(198,211,185,0.55), rgba(198,211,185,0) 68%)', filter: 'blur(40px)' } },
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
      className="h-[460vh] relative"
    >
      <div
        className="ld-stage sticky top-0 h-screen overflow-hidden [background:linear-gradient(180deg,_#E0E6DB_0%,_rgba(224,230,219,0.7)_6%,_rgba(224,230,219,0)_16%),_linear-gradient(0deg,_#E0E6DB_0%,_rgba(224,230,219,0.7)_5%,_rgba(224,230,219,0)_14%),_radial-gradient(ellipse_90%_80%_at_50%_42%,_#EDF0E9_0%,_#E6EBE1_62%,_#E0E6DB_100%)]"
      >
        <div
          aria-hidden="true"
          className="absolute inset-0 pointer-events-none z-3 [mask-image:linear-gradient(180deg,_transparent_0%,_#000_14%,_#000_86%,_transparent_100%)] [-webkit-mask-image:linear-gradient(180deg,_transparent_0%,_#000_14%,_#000_86%,_transparent_100%)]"
        >
          {FOLIAGE.map((f, i) => (
            <span key={i} className="absolute" style={{ ...f.style } as React.CSSProperties} />
          ))}
        </div>

        {/* `touch-action` flips with explore mode. The canvas covers the whole
            pinned stage, so `none` outside explore would swallow every
            vertical swipe on a phone and strand the reader inside a 460vh
            act; `pan-y` leaves scrolling to the browser until a tap enters
            explore, which locks body scroll and hands the drag to the orbit. */}
        <canvas
          ref={actCanvasRef}
          className={cn("absolute inset-0 z-1 w-full h-full cursor-grab", exploring ? "touch-none" : "[touch-action:pan-y]")}
        />

        {/* captions — the engine cross-fades these by scroll progress */}
        <div
          ref={cinemaRef}
          className="absolute inset-0 z-4 pointer-events-none [transition:opacity_520ms_ease]"
        >
          {CAPTIONS.map((c, i) => (
            <div key={i} data-cap={i} className="ld-cap absolute left-[max(6vw,32px)] top-1/2 [transform:translateY(-50%)] z-4 max-w-[34ch] opacity-0 pointer-events-none">
              <span aria-hidden="true" className="absolute -left-14.5 -right-18 -top-11.5 -bottom-11.5 pointer-events-none [background:radial-gradient(ellipse_62%_58%_at_38%_50%,_rgba(242,244,240,0.82)_0%,_rgba(242,244,240,0.66)_45%,_rgba(242,244,240,0.28)_72%,_rgba(242,244,240,0)_100%)] [filter:blur(18px)]" />
              <h2 className="relative m-0 font-display text-[length:clamp(2.4rem,4.6vw,4rem)] font-semibold leading-[1.06] tracking-[-0.02em] text-moss-900 [text-shadow:0_2px_26px_rgba(242,244,240,0.85)]">{c.head}</h2>
              {c.body && <p className="relative mt-4 mx-0 mb-0 text-moss-700 text-[15.5px] leading-[1.7] [text-shadow:0_1px_14px_rgba(242,244,240,0.9)]">{c.body}</p>}
              {/* the mastery legend rides along with caption 2 */}
              {i === 2 && (
                <div className="relative mt-5 flex flex-col gap-2.5">
                  {XTIER_ORDER.map((t) => (
                    <div key={t} className="flex items-center gap-2.5">
                      <span
                        className={cn("w-[9px] h-[9px] rounded-[99px]", t === 'mastered' ? "[box-shadow:0_0_10px_rgba(104,149,31,0.6)]" : "")} style={{ background: XTIER[t] }}
                      />
                      <span
                        className={cn("font-sans text-md tracking-[0.01em]", t === 'mastered' ? "text-moss-900" : "text-moss-700")}
                      >
                        {XTIER_LABEL[t]}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}

          {/* the closing caption sits low and centred rather than left-aligned */}
          <div data-cap="3" className="ld-cap-close absolute left-0 right-0 bottom-[9vh] z-4 text-center opacity-0 pointer-events-none">
            <span
              aria-hidden="true"
              className="absolute left-1/2 -top-13 -bottom-13 w-[min(1080px,92vw)] [transform:translateX(-50%)] pointer-events-none [background:radial-gradient(ellipse_54%_62%_at_50%_50%,_rgba(242,244,240,0.82)_0%,_rgba(242,244,240,0.66)_45%,_rgba(242,244,240,0.28)_72%,_rgba(242,244,240,0)_100%)] [filter:blur(18px)]"
            />
            <h2
              className="relative m-0 font-display text-[length:clamp(3rem,7vw,6.4rem)] font-semibold leading-[1.02] tracking-[-0.025em] text-moss-900 [text-shadow:0_3px_34px_rgba(242,244,240,0.85)]"
            >
              See what you <em className="text-brand-forest">know.</em>
            </h2>
            <p className="relative mt-3.5 mx-0 mb-0 text-moss-700 text-lg [text-shadow:0_1px_14px_rgba(242,244,240,0.9)]">
              Your whole semester, one living map, updated as you learn.
            </p>
            <span className="relative inline-flex items-center gap-2 mt-4.5 font-sans text-[12.5px] tracking-[0.01em] text-brand-forest">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#445D22" strokeWidth="2" strokeLinecap="round">
                <path d="M5 9l-3 3 3 3" /><path d="M9 5l3-3 3 3" /><path d="M15 19l-3 3-3-3" />
                <path d="M19 9l3 3-3 3" /><path d="M2 12h20" /><path d="M12 2v20" />
              </svg>
              Drag to orbit · Click to explore
            </span>
          </div>

          {/* stage rail — the engine lights the tick matching the live caption */}
          <div aria-hidden="true" className="absolute right-[max(4vw,24px)] top-1/2 [transform:translateY(-50%)] z-4 flex flex-col gap-3.5">
            {[0, 1, 2, 3].map((i) => (
              <span key={i} data-tick={i} className="w-[5px] h-6.5 rounded-[99px] bg-[rgba(25,31,19,0.14)] [transition:background_300ms]" />
            ))}
          </div>
        </div>

        {/* ── explore HUD ── */}
        {exploring && (
          <div className={cn(node ? 'ld-hud ld-hud--node' : 'ld-hud', "absolute inset-0 z-6 pointer-events-none [animation:panelFade_420ms_ease_520ms_both]")}>
            <div className="ld-hud-course absolute left-[max(3vw,20px)] top-6 flex flex-col gap-1">
              <span className="font-sans text-md tracking-[0.01em] text-brand-forest">{COURSE.code}</span>
              <span className="font-serif text-[21px] font-semibold text-moss-900">{COURSE.name}</span>
            </div>

            <div className="ld-hud-legend absolute left-[max(3vw,20px)] bottom-6.5 flex flex-col gap-[9px] py-3.5 px-4 rounded-[14px] [background:rgba(253,252,249,0.8)] border border-[rgba(25,31,19,0.10)] [backdrop-filter:blur(10px)] pointer-events-auto">
              <span className="font-sans text-2xs text-moss-500 tracking-[0.01em]">
                {COURSE.term} · {Math.max(0, nodes.length - 1)} CONCEPTS MAPPED
              </span>
              {XTIER_ORDER.map((t) => (
                <span key={t} className="flex items-center gap-[9px] text-[11.5px] text-moss-700">
                  <span className="w-[9px] h-[9px] rounded-[99px] flex-[0_0_auto]" style={{ background: XTIER[t] }} />
                  {XTIER_LABEL[t]}
                  <b className="ml-auto font-sans text-2xs font-normal text-moss-500">{counts[t]}</b>
                </span>
              ))}
            </div>

            <span className="ld-hud-hint absolute left-1/2 bottom-6.5 [transform:translateX(-50%)] font-sans text-xs tracking-[0.01em] text-moss-500 whitespace-nowrap">
              Drag to orbit · Scroll to zoom · Click a concept
            </span>

            {node && (
              <div className="ld-hud-inspector absolute right-[max(3vw,20px)] top-19.5 bottom-17.5 w-[min(340px,32vw)] overflow-auto pt-5.5 px-5.5 pb-5 rounded-[18px] [background:rgba(253,252,249,0.92)] border border-[rgba(25,31,19,0.12)] [backdrop-filter:blur(14px)] pointer-events-auto [animation:panelFade_300ms_ease_both]">
                <div className="flex items-center gap-[9px]">
                  <span className="w-2.5 h-2.5 rounded-[99px] flex-[0_0_auto]" style={{ background: XTIER[node.tier] }} />
                  <span className="font-sans text-2xs tracking-[0.01em]" style={{ color: XTIER[node.tier] }}>
                    {XTIER_LABEL[node.tier]}
                  </span>
                  <span className="font-sans text-[9.5px] tracking-[0.01em] text-moss-500">
                    {node.root
                      ? 'Course'
                      : node.hub
                        ? `Unit · ${COURSE.code}`
                        : `${COURSE.code} · ${COURSE.topics[node.topic!].label}`}
                  </span>
                  <button
                    onClick={() => onSelectNode(null)}
                    aria-label="Close concept"
                    type="button"
                    className="ml-auto w-6 h-6 rounded-[99px] border border-[rgba(25,31,19,0.12)] bg-transparent text-moss-700 cursor-pointer text-md leading-none"
                  >
                    ×
                  </button>
                </div>
                <h4 className="mt-3 mx-0 mb-0 font-display text-3xl font-semibold leading-[1.15] text-moss-900">{node.label}</h4>
                <p className="mt-2 mx-0 mb-0 text-md leading-[1.65] text-moss-700">{node.blurb}</p>

                <div className="mt-4 flex items-center gap-2.5">
                  <span className="flex-1 h-1.5 rounded-[99px] bg-[rgba(25,31,19,0.10)] overflow-hidden">
                    <span className="block h-full rounded-[99px] [transition:width_420ms_cubic-bezier(0.22,1,0.36,1)]" style={{ width: `${Math.round(node.mastery * 100)}%`, background: XTIER[node.tier] }} />
                  </span>
                  <span className="font-sans text-xs text-moss-900">{Math.round(node.mastery * 100)}%</span>
                </div>
                <span className="block mt-[5px] font-sans text-2xs tracking-[0.01em] text-moss-500">
                  Mastery score · Updated after every session
                </span>

                <span className="block mt-4.5 font-sans text-2xs tracking-[0.01em] text-moss-500">
                  {neighbours.length} connected {neighbours.length === 1 ? 'concept' : 'concepts'}
                </span>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {neighbours.map((j) => (
                    <button
                      key={j}
                      onClick={() => onSelectNode(j)}
                      type="button"
                      className="ld-expchip flex items-center gap-1.5 py-1.5 px-[11px] rounded-[99px] border border-[rgba(25,31,19,0.14)] [background:rgba(25,31,19,0.04)] text-moss-900 font-sans text-[11.5px] cursor-pointer [transition:all_200ms]"
                    >
                      <span className="w-[7px] h-[7px] rounded-[99px]" style={{ background: XTIER[nodes[j].tier] }} />
                      {nodes[j].label}
                    </button>
                  ))}
                </div>

                <span className="block mt-4.5 font-sans text-2xs tracking-[0.01em] text-moss-500">What Sapling does with this node</span>
                <div className="mt-[9px] flex flex-col gap-2.5">
                  {nodeUses(node, neighbours.length).map((u, i) => (
                    <div key={i} className="flex flex-col gap-[3px] pl-[11px] border-l-2 border-l-[rgba(68,93,34,0.3)]">
                      <span className="font-sans text-2xs tracking-[0.01em] text-brand-forest">{u.tag}</span>
                      <span className="text-sm leading-[1.6] text-moss-700">{u.text}</span>
                    </div>
                  ))}
                </div>

                <div className="mt-4.5 flex gap-2">
                  <button onClick={onQuiz} type="button" className="ld-expquiz flex-1 py-2.5 px-3 rounded-[9px] border-0 [background:#445D22] text-accent-fg font-sans text-[12.5px] font-semibold cursor-pointer [transition:background_200ms]">
                    Quiz me on this
                  </button>
                  <button onClick={onLearn} type="button" className="ld-explearn flex-1 py-2.5 px-3 rounded-[9px] border border-[rgba(25,31,19,0.2)] [background:transparent] text-moss-900 font-sans text-[12.5px] cursor-pointer [transition:background_200ms]">
                    Ask the tutor
                  </button>
                </div>
                <span className="block mt-[9px] font-sans text-2xs tracking-[0.01em] text-moss-500">
                  /learn?topic={encodeURIComponent(node.label)}&amp;mode=socratic
                </span>
              </div>
            )}

            <button
              onClick={onExitExplore}
              type="button"
              className="ld-exitexplore ld-hud-exit absolute right-[max(3vw,20px)] top-6.5 flex items-center gap-2 py-[9px] px-4 rounded-[99px] border border-[rgba(25,31,19,0.14)] [background:rgba(253,252,249,0.85)] text-moss-700 font-sans text-[11.5px] tracking-[0.01em] cursor-pointer pointer-events-auto [transition:all_220ms]"
            >
              ✕ Exit explore
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
      className="relative h-[34vh] [background:linear-gradient(180deg,_#E0E6DB_0%,_rgba(224,230,219,0.75)_20%,_rgba(224,230,219,0.3)_55%,_rgba(224,230,219,0)_100%)]"
    />
  );
}
