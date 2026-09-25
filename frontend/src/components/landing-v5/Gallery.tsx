'use client';

/**
 * The gallery — two marquee rails of bespoke feature cards.
 *
 * Ported from `Sapling Landing v5.dc.html`. Eight cards ride two tracks
 * drifting in opposite directions; the engine's marquee controller owns the
 * transform and the drag-to-scrub, and clicking a card opens the feature lab
 * via a FLIP from the card's own rect.
 *
 * The cards and section rhythm run a notch smaller than the source — the
 * original two full-size rails stacked past any normal viewport height, and
 * keeping both rows was chosen over one bigger rail.
 *
 * Each track lists its cards TWICE. That duplication is the loop: the marquee
 * translates by exactly half the track width and wraps, so the second copy is
 * already in place when the first scrolls out. Removing it leaves a visible
 * gap on every cycle. The duplicates are `aria-hidden`, and only the first
 * copy is reachable by keyboard.
 *
 * The card visuals live in galleryMinis.tsx, generated from the source.
 *
 * Below 900px the cards shrink again, via `--gal-scale` (set in globals.css
 * per breakpoint) driving a CSS `transform: scale()` on `.ld-galcard` — see
 * `SLOT`/`CARD` below. Scaling the whole card, rather than resizing its
 * width and leaving the illustration pane's height fixed, is what keeps the
 * eight animated minis proportional instead of squashed at narrow widths
 * (#624); it also keeps the marquee's own transform, hit-testing, and FLIP
 * open untouched, since `getBoundingClientRect()` already reports the
 * scaled, on-screen box. `SLOT` mirrors that scale into a real layout size
 * so the marquee's width/gap measurements — and the wrap seam they depend
 * on — stay correct at every width.
 */

import { GALLERY_MINIS } from './galleryMinis';
import { FadeIn } from '@/components/landing/anim';

const MONO: React.CSSProperties = { fontFamily: "var(--font-jetbrains), 'JetBrains Mono', ui-monospace, monospace" };

/** Card copy, indexed by `data-tk`. Distinct from the lab panels' copy in content.ts. */
const CARDS = [
  { kicker: 'ADAPTIVE QUIZZES', title: <>Questions that <em style={{ color: '#0C5638', fontStyle: 'italic' }}>re-tune.</em></>, desc: 'Difficulty moves with every answer, and each result writes mastery back to your graph.' },
  { kicker: 'SPACED REPETITION', title: <>Knows what to review, <em style={{ color: '#0C5638', fontStyle: 'italic' }}>and when.</em></>, desc: 'Forgot, Hard, Easy: ten minutes, a day, four days. Sapling schedules; you show up.' },
  { kicker: 'NOTETAKER', title: <>Notes that <em style={{ color: '#0C5638', fontStyle: 'italic' }}>think.</em></>, desc: 'Write normally. Sapling summarizes, pulls the concepts, and links them to your graph.' },
  { kicker: 'STUDY GUIDES', title: <>Built from your <em style={{ color: '#0C5638', fontStyle: 'italic' }}>gaps.</em></>, desc: 'Pick a course and an exam. The guide is assembled from your own library, weighted to weak concepts.' },
  { kicker: 'STUDY ROOMS', title: <>Learn <em style={{ color: '#0C5638', fontStyle: 'italic' }}>together.</em></>, desc: 'Live rooms with chat and a side-by-side graph that shows exactly who knows what.' },
  { kicker: 'GRADEBOOK', title: <>Know your <em style={{ color: '#0C5638', fontStyle: 'italic' }}>real grade.</em></>, desc: 'Syllabus weights become categories. Every score rolls into a live grade and letter.' },
  { kicker: 'CALENDAR', title: <>A syllabus becomes a <em style={{ color: '#0C5638', fontStyle: 'italic' }}>semester.</em></>, desc: 'Upload once. Every exam, pset, and quiz is extracted, dated, and synced to Google Calendar.' },
  { kicker: 'AI TUTOR', title: <>It asks. <em style={{ color: '#0C5638', fontStyle: 'italic' }}>You answer.</em></>, desc: 'Socratic, expository, or teachback. It never hands over the solution, it walks you to it.' },
];

/** Track A drifts right, track B drifts left. */
const TRACK_A = [0, 1, 2, 3];
const TRACK_B = [7, 6, 5, 4];

const MOTES: { d: number; s: React.CSSProperties }[] = [
  { d: 0.38, s: { right: '5.4%', top: '63.7%', width: 8, height: 8, background: '#4FA574', opacity: 0.58, boxShadow: '0 0 20px #4FA57466', animation: 'nodeFloatA 16s ease-in-out -6s infinite' } },
  { d: 0.43, s: { left: '15.2%', top: '17.6%', width: 4.2, height: 4.2, background: '#6FBF8F', opacity: 0.4, animation: 'nodeFloatB 13s ease-in-out -3s infinite' } },
  { d: 0.34, s: { left: '13.1%', top: '88.7%', width: 9.4, height: 9.4, background: '#8FD9A8', opacity: 0.46, boxShadow: '0 0 22px #8FD9A866', animation: 'nodeFloatA 18s ease-in-out -11s infinite' } },
  { d: 0.40, s: { left: '12.4%', top: '50.2%', width: 10.9, height: 10.9, background: '#4FA574', opacity: 0.48, boxShadow: '0 0 26px #4FA57466', animation: 'nodeFloatB 15s ease-in-out -8s infinite' } },
  { d: 0.27, s: { right: '9.2%', top: '65.0%', width: 7, height: 7, background: '#6FBF8F', opacity: 0.36, animation: 'nodeFloatA 12s ease-in-out -2s infinite' } },
  { d: 0.45, s: { left: '5.4%', top: '81.7%', width: 9.3, height: 9.3, background: '#4FA574', opacity: 0.44, boxShadow: '0 0 23px #4FA57466', animation: 'nodeFloatB 17s ease-in-out -14s infinite' } },
  { d: 0.42, s: { right: '41.3%', top: '6.1%', width: 5.8, height: 5.8, background: '#8FD9A8', opacity: 0.59, animation: 'nodeFloatA 14s ease-in-out -5s infinite' } },
  { d: 0.47, s: { right: '7.9%', top: '59.7%', width: 6.4, height: 6.4, background: '#2E7D52', opacity: 0.53, animation: 'nodeFloatB 19s ease-in-out -9s infinite' } },
  { d: 0.18, s: { left: '12.0%', top: '37.7%', width: 8, height: 8, background: '#0E9E5A', opacity: 0.53, boxShadow: '0 0 20px #0E9E5A66', animation: 'nodeFloatA 11s ease-in-out -7s infinite' } },
  { d: 0.42, s: { left: '4.5%', top: '13.5%', width: 7, height: 7, background: '#8FD9A8', opacity: 0.48, animation: 'nodeFloatB 16s ease-in-out -12s infinite' } },
  { d: 0.27, s: { right: '7.0%', top: '57.4%', width: 8, height: 8, background: '#2E7D52', opacity: 0.46, boxShadow: '0 0 20px #2E7D5266', animation: 'nodeFloatA 13s ease-in-out -4s infinite' } },
];

/**
 * Natural (desktop, scale 1) card footprint. All eight cards measure the
 * same height — the description copy was written to a consistent length —
 * so it's safe to fix it here rather than measure post-render. Card size
 * and pane size (166, matching the source) are fixed — they don't grow to
 * fit content; oversized minis get shrunk to fit instead (`MINI_FIT`).
 */
const CARD_W = 372;
const MINI_H = 166;
const CARD_H = 314;

/**
 * Most minis fit the 166px pane at their natural (unscaled) height — the
 * pane's `overflow: hidden` never engages for them. The AI Tutor mini (three
 * chat bubbles plus a hint row) runs to ~188px, taller than the pane, so it
 * was losing its hint row and "NEVER THE ANSWER" tag to that same clip
 * (#624). Rather than grow the pane (and every other card with it) or leave
 * it cropped, it gets a uniform `transform: scale()` down to the exact
 * factor that makes its natural height fit — scaling both axes together, not
 * just height, is what keeps the chat bubbles undistorted instead of
 * squashed. Keyed by `CARDS` index; add an entry here if a future mini ever
 * runs long, rather than resizing the pane.
 */
const MINI_FIT: Partial<Record<number, { naturalH: number; scale: number }>> = {
  7: { naturalH: 188, scale: MINI_H / 188 },
};

const CARD: React.CSSProperties = {
  width: CARD_W, height: CARD_H, borderRadius: 20, background: '#FDFCF9',
  border: '1px solid #E8E5DA', boxShadow: '0 6px 18px -6px rgba(18,32,26,0.14)',
  padding: '12px 12px 18px', display: 'flex', flexDirection: 'column',
  position: 'relative', overflow: 'hidden', cursor: 'pointer', userSelect: 'none',
  transformOrigin: 'top left',
  transition: 'transform 320ms cubic-bezier(0.22,1,0.36,1)',
};

/**
 * The flex item the marquee actually measures. It's sized in lockstep with
 * `--gal-scale` (set per breakpoint in globals.css) so `offsetWidth` always
 * matches what's on screen; the card inside is scaled with a CSS transform
 * rather than shrunk via width, so the illustration, type, and every
 * keyframe animation shrink together instead of the illustration getting
 * squashed against a fixed-height pane (the mistake the v4 grove cards
 * made — see the note above `.landing-dc .gal-rail` in globals.css).
 */
const SLOT: React.CSSProperties = {
  flex: '0 0 auto',
  width: `calc(${CARD_W}px * var(--gal-scale, 1))`,
  height: `calc(${CARD_H}px * var(--gal-scale, 1))`,
};

function Card({ i, ghost }: { i: number; ghost: boolean }) {
  const c = CARDS[i];
  const fit = MINI_FIT[i];
  return (
    <div style={SLOT}>
      <article
        data-tk={i}
        aria-hidden={ghost || undefined}
        style={CARD}
        className="ld-galcard"
      >
        <div aria-hidden="true" style={{ position: 'relative', height: MINI_H, borderRadius: 13, overflow: 'hidden', background: '#FDFCF9', border: '1px solid #EBF1EC' }}>
          {fit ? (
            <div style={{ height: fit.naturalH, width: '100%', transform: `scale(${fit.scale})`, transformOrigin: 'top center' }}>
              {GALLERY_MINIS[i]}
            </div>
          ) : (
            GALLERY_MINIS[i]
          )}
        </div>
        <div style={{ padding: '15px 12px 0', display: 'flex', flexDirection: 'column' }}>
          <span style={{ ...MONO, fontSize: 9.5, letterSpacing: '0.28em', color: '#0C5638' }}>{c.kicker}</span>
          <h3 style={{ margin: '10px 0 0', fontFamily: "var(--font-playfair), 'Playfair Display', Georgia, serif", fontSize: 22, fontWeight: 600, lineHeight: 1.2, letterSpacing: '-0.015em', color: '#12201A' }}>
            {c.title}
          </h3>
          <p style={{ margin: '9px 0 0', fontSize: 12.5, lineHeight: 1.6, color: '#61726A', maxWidth: '40ch', textWrap: 'pretty' }}>
            {c.desc}
          </p>
        </div>
      </article>
    </div>
  );
}

function Track({
  trackRef, order, label, onOpen,
}: {
  trackRef: React.RefObject<HTMLDivElement | null>;
  order: number[];
  label: string;
  onOpen: (i: number, el: HTMLElement | null) => void;
}) {
  return (
    <div
      ref={trackRef}
      aria-label={label}
      onClick={(e) => {
        const card = (e.target as HTMLElement).closest<HTMLElement>('[data-tk]');
        if (card) onOpen(Number(card.dataset.tk), card);
      }}
      style={{ display: 'flex', gap: 'calc(26px * var(--gal-scale, 1))', width: 'max-content', willChange: 'transform', cursor: 'grab', touchAction: 'pan-y' }}
    >
      {order.map((i) => <Card key={`a${i}`} i={i} ghost={false} />)}
      {order.map((i) => <Card key={`b${i}`} i={i} ghost />)}
    </div>
  );
}

/**
 * The margin note pointing down at the rails.
 *
 * The cards open the feature lab on click, and nothing in the section says
 * so: they drift, which reads as decoration, and a drifting thing is the last
 * thing a visitor tries to click. This is the nudge — deliberately in a hand,
 * off the grid, and tilted, so it reads as someone's annotation ON the page
 * rather than as another element OF it. Straighten it and it stops being an
 * aside and starts being a label nobody believes.
 *
 * The arrow is one open curve with two barbs rather than a filled head: a
 * solid triangle reads as UI iconography, which is the register this is
 * trying to step out of.
 *
 * Hidden below 900px via `.ld-handnote` (globals.css) — the header column and
 * the rails stack there, so "down and to the left" stops pointing at the
 * cards and the note would land on the copy it is meant to sit beside.
 */
function HandNote() {
  return (
    <div
      className="ld-handnote"
      style={{
        position: 'relative', flex: '0 0 auto', paddingBottom: 6,
        display: 'flex', flexDirection: 'column', alignItems: 'center',
      }}
    >
      <span
        style={{
          fontFamily: "var(--font-caveat), cursive",
          fontSize: 27, fontWeight: 600, lineHeight: 1.15, color: '#0C5638',
          transform: 'rotate(-4.5deg)', transformOrigin: '100% 100%',
          whiteSpace: 'nowrap',
        }}
      >
        click to demo the features!
      </span>
      <svg
        aria-hidden="true"
        width="118"
        height="90"
        viewBox="0 0 118 90"
        fill="none"
        style={{ marginTop: -2, overflow: 'visible' }}
      >
        {/* the sweep: centred under the sentence rather than hung off its
            right end, so it drops out of the middle of the line and falls
            away to the left, reaching down far enough that the head lands
            over the rail rather than in the gap above it */}
        <path
          d="M104 5 C97 28, 86 40, 68 52 C55 61, 42 68, 27 76"
          stroke="#0C5638"
          strokeWidth="2.1"
          strokeLinecap="round"
          opacity="0.85"
        />
        {/* two barbs straddling the incoming direction, drawn slightly uneven
            so the head looks written rather than constructed */}
        <path d="M27 76 L47 71" stroke="#0C5638" strokeWidth="2.1" strokeLinecap="round" opacity="0.85" />
        <path d="M27 76 L38 59" stroke="#0C5638" strokeWidth="2.1" strokeLinecap="round" opacity="0.85" />
      </svg>
    </div>
  );
}

export function Gallery({
  trackARef,
  trackBRef,
  onOpen,
}: {
  trackARef: React.RefObject<HTMLDivElement | null>;
  trackBRef: React.RefObject<HTMLDivElement | null>;
  onOpen: (i: number, el: HTMLElement | null) => void;
}) {
  return (
    <section id="gallery" style={{ position: 'relative', padding: 'clamp(44px,7vh,92px) 0 clamp(30px,4.5vh,60px)', zIndex: 1, isolation: 'isolate' }}>
      <div aria-hidden="true" style={{ position: 'absolute', inset: 0, pointerEvents: 'none', overflow: 'hidden', zIndex: 0 }}>
        {MOTES.map((m, i) => (
          <span key={i} data-depth={m.d} style={{ position: 'absolute', borderRadius: 99, ...m.s }} />
        ))}
      </div>

      <div style={{ position: 'relative', zIndex: 1, maxWidth: 1220, margin: '0 auto', padding: '0 24px', display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 24, flexWrap: 'wrap' }}>
        <FadeIn>
          <span style={{ ...MONO, fontSize: 11, letterSpacing: '0.32em', color: '#0C5638', textTransform: 'uppercase', fontWeight: 500 }}>
            And much more
          </span>
          <h2 style={{ margin: '16px 0 0', fontFamily: "var(--font-playfair), 'Playfair Display', Georgia, serif", fontSize: 'clamp(2.2rem,4.4vw,3.6rem)', fontWeight: 600, lineHeight: 1.04, letterSpacing: '-0.02em', color: '#12201A' }}>
            The rest of the <em style={{ color: '#0C5638' }}>grove.</em>
          </h2>
          <p style={{ margin: '14px 0 0', color: '#61726A', fontSize: 14, lineHeight: 1.65, maxWidth: '62ch' }}>
            Eight tools covering the whole arc of a course: quizzes and flashcards that test recall,
            notes and study guides that turn your materials into something usable, a tutor that
            talks you through what you missed, and a gradebook and calendar that keep the semester
            honest. Each one writes back to the same graph.
          </p>
        </FadeIn>

        {/* the right end of the header row, bottom-aligned: the note lands in
            the gap between the copy and the first rail, which is the only
            place its arrow can point at cards without covering any */}
        <FadeIn>
          <HandNote />
        </FadeIn>
      </div>

      <div style={{ position: 'relative', zIndex: 1, marginTop: 28 }}>
        {/* the mask feathers both ends so cards enter and leave rather than pop */}
        <div
          style={{
            position: 'relative', overflow: 'hidden', padding: '16px 0',
            WebkitMaskImage: 'linear-gradient(90deg, transparent 0, #000 5%, #000 95%, transparent 100%)',
            maskImage: 'linear-gradient(90deg, transparent 0, #000 5%, #000 95%, transparent 100%)',
          }}
        >
          <Track trackRef={trackARef} order={TRACK_A} label="Sapling tools, drifting right" onOpen={onOpen} />
        </div>
        <div
          style={{
            position: 'relative', overflow: 'hidden', padding: '16px 0',
            WebkitMaskImage: 'linear-gradient(90deg, transparent 0, #000 5%, #000 95%, transparent 100%)',
            maskImage: 'linear-gradient(90deg, transparent 0, #000 5%, #000 95%, transparent 100%)',
          }}
        >
          <Track trackRef={trackBRef} order={TRACK_B} label="Sapling tools, drifting left" onOpen={onOpen} />
        </div>
      </div>
    </section>
  );
}
