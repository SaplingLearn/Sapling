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
 */

import { GALLERY_MINIS } from './galleryMinis';
import { FadeIn } from '@/components/landing/anim';

const MONO: React.CSSProperties = { fontFamily: "'JetBrains Mono',monospace" };

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

const CARD: React.CSSProperties = {
  flex: '0 0 auto', width: 350, borderRadius: 18, background: '#FDFCF9',
  border: '1px solid #E8E5DA', boxShadow: '0 6px 18px -6px rgba(18,32,26,0.14)',
  padding: '10px 10px 14px', display: 'flex', flexDirection: 'column',
  position: 'relative', overflow: 'hidden', cursor: 'pointer', userSelect: 'none',
  transition: 'transform 320ms cubic-bezier(0.22,1,0.36,1)',
};

function Card({ i, ghost }: { i: number; ghost: boolean }) {
  const c = CARDS[i];
  return (
    <article
      data-tk={i}
      aria-hidden={ghost || undefined}
      style={CARD}
      className="ld-galcard"
    >
      <div aria-hidden="true" style={{ position: 'relative', height: 140, borderRadius: 12, overflow: 'hidden', background: '#FDFCF9', border: '1px solid #EBF1EC' }}>
        {GALLERY_MINIS[i]}
      </div>
      <div style={{ padding: '12px 10px 0', display: 'flex', flexDirection: 'column' }}>
        <span style={{ ...MONO, fontSize: 9, letterSpacing: '0.26em', color: '#0C5638' }}>{c.kicker}</span>
        <h3 style={{ margin: '8px 0 0', fontFamily: "'Playfair Display',serif", fontSize: 19, fontWeight: 600, lineHeight: 1.2, letterSpacing: '-0.015em', color: '#12201A' }}>
          {c.title}
        </h3>
        <p style={{ margin: '7px 0 0', fontSize: 12, lineHeight: 1.55, color: '#61726A', maxWidth: '42ch', textWrap: 'pretty' }}>
          {c.desc}
        </p>
      </div>
    </article>
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
      style={{ display: 'flex', gap: 26, width: 'max-content', willChange: 'transform', cursor: 'grab', touchAction: 'pan-y' }}
    >
      {order.map((i) => <Card key={`a${i}`} i={i} ghost={false} />)}
      {order.map((i) => <Card key={`b${i}`} i={i} ghost />)}
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
          <h2 style={{ margin: '16px 0 0', fontFamily: "'Playfair Display',serif", fontSize: 'clamp(2.2rem,4.4vw,3.6rem)', fontWeight: 600, lineHeight: 1.04, letterSpacing: '-0.02em', color: '#12201A' }}>
            The rest of the <em style={{ color: '#0C5638' }}>grove.</em>
          </h2>
          <p style={{ margin: '14px 0 0', color: '#61726A', fontSize: 14, lineHeight: 1.65, maxWidth: '62ch' }}>
            Eight tools covering the whole arc of a course: quizzes and flashcards that test recall,
            notes and study guides that turn your materials into something usable, a tutor that
            talks you through what you missed, and a gradebook and calendar that keep the semester
            honest. Each one writes back to the same graph.
          </p>
        </FadeIn>
      </div>

      <div style={{ position: 'relative', zIndex: 1, marginTop: 28 }}>
        {/* the mask feathers both ends so cards enter and leave rather than pop */}
        <div
          style={{
            position: 'relative', overflow: 'hidden', padding: '12px 0',
            WebkitMaskImage: 'linear-gradient(90deg, transparent 0, #000 5%, #000 95%, transparent 100%)',
            maskImage: 'linear-gradient(90deg, transparent 0, #000 5%, #000 95%, transparent 100%)',
          }}
        >
          <Track trackRef={trackARef} order={TRACK_A} label="Sapling tools, drifting right" onOpen={onOpen} />
        </div>
        <div
          style={{
            position: 'relative', overflow: 'hidden', padding: '12px 0',
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
