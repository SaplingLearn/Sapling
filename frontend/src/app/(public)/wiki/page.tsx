import type { Metadata } from 'next';
import { CompanionShell } from '@/components/companion/CompanionShell';
import { ZoomableShot } from '@/components/companion/ZoomableShot';
import { WikiRail } from './WikiRail';
import {
  WIKI_ACHIEVEMENT_TERMS, WIKI_CALENDAR_SPECS, WIKI_CLASS_TERMS, WIKI_DATA_FACTS,
  WIKI_FLASHCARD_NOTES, WIKI_FLASHCARD_RATINGS, WIKI_GRADE_NOTES, WIKI_GRAPH_TERMS,
  WIKI_GUIDE_SPECS, WIKI_LETTERS, WIKI_MASTERY_FORMULA, WIKI_MASTERY_MOVES, WIKI_MODES,
  WIKI_NOTE_SPECS, WIKI_ONBOARDING_SPECS, WIKI_PIPELINE, WIKI_PROGRESS_TERMS,
  WIKI_QUIZ_SPECS, WIKI_ROOM_SPECS, WIKI_SHOTS, WIKI_TIERS, WIKI_UPLOAD_SPECS,
} from '@/lib/landing/companionContent';
import { ARTICLE, DISPLAY, MONO, SERIF } from '@/lib/landing/companionType';

/**
 * Wiki.
 *
 * A sticky contents rail beside eighteen definition sections, grouped the
 * way the product is: learn, capture, the semester, the people, and you.
 *
 * Three row shapes carry almost all of it — `TermRows` for a name and a
 * definition, `SpecRows` for a name, a value and the reason for the value,
 * and the tier table, which is the only one that needs a swatch. Adding a
 * section should mean adding content and picking a shape, not writing a
 * fourth grid.
 */

export const metadata: Metadata = {
  title: 'Wiki',
  description:
    'Exact definitions for the terms and numbers Sapling puts on screen. Every value here is the one the product actually uses.',
};

/**
 * One right edge, two measures, and the type scaled to each (#604).
 *
 * The page had four right edges — row grids at the full article column, ledes
 * and definitions capped at `PROSE_MEASURE`, screenshots at a hardcoded 560 —
 * so the content edge jittered eighteen times on the way down. Everything now
 * runs to the column.
 *
 * The cap was not arbitrary, though: uncapped prose at the old 14.5/15px ran
 * past 100 characters a line. So the sizes come up with the measure, the way
 * /news/[slug] scales `ARTICLE` to the same box rather than capping it. The
 * page has exactly two prose measures, and one size each, both measured in a
 * browser at 1440px (characters counted off real line boxes, partial last
 * lines excluded) rather than estimated:
 *
 *   PROSE (22px) — the full 870px column: ledes, fact lists, the deck.
 *                  Median 88 characters a line, range 80-92.
 *   DEF   (18px) — the 678px cell right of a row key. Median 83, up to 88.
 *
 * The two multi-column tables — tiers, and how mastery moves — inset their
 * text further and so run shorter, into the 60s. Their cells hold a sentence
 * or two, not running prose, and widening them would cost the row rhythm.
 *
 * Everything else on the page — keys, values, captions, headings — is scaled
 * by the same ~1.24 the body took, so the rows keep their rhythm.
 */
const H2: React.CSSProperties = {
  margin: 0, fontFamily: DISPLAY, fontWeight: 500, fontSize: 32,
  lineHeight: 1.2, letterSpacing: '-0.015em',
};
/**
 * Anchor offset for a jumped-to section.
 *
 * It belongs on the `<section>`, which is what carries the id and is
 * therefore what the browser scrolls to — on the heading it looks right and
 * does nothing, which is how the heading ended up under the nav bar. Matches
 * the rail's own sticky offset so the two line up.
 */
const SECTION: React.CSSProperties = { scrollMarginTop: 84 };
/** Prose that runs the whole article column: ledes, fact lists, the deck. */
const PROSE: React.CSSProperties = {
  fontFamily: SERIF, fontSize: 22, lineHeight: 1.55, color: '#3f3b31',
};
const LEDE: React.CSSProperties = { ...PROSE, margin: '14px 0 0' };
/**
 * Definition text, shared by every row style below.
 *
 * Set against the narrower of the page's two measures: a row key takes
 * `KEY_COL` off the column, so this reads at ~84 characters where the ledes
 * beside it read at ~88.
 */
const DEF: React.CSSProperties = {
  fontFamily: SERIF, fontSize: 18, lineHeight: 1.6, color: '#3f3b31',
};
/** The hairline that separates rows within a section. */
const ROW_TOP = '1px solid rgba(42,39,31,0.08)';
/**
 * The key column every row shape opens with, and the gap after it.
 *
 * Sized off the longest key on the page ("Generation timeout", 18 mono
 * characters) at the scaled-up `KEY` size — the two move together, and what
 * is left is the definition measure.
 */
const KEY_COL = 'minmax(0,172px)';
const ROW_GAP = 20;
/** The green mono key that opens a row. */
const KEY: React.CSSProperties = { fontFamily: MONO, fontSize: 13.5, letterSpacing: '0.06em', color: '#1B6C42' };
/** The value a spec row states, above its reason. */
const VALUE: React.CSSProperties = { fontSize: 17, fontWeight: 600, color: '#1a1814' };

/** `dot`/`tone` come from the source as CSS declaration strings. */
function cssColor(decl: string): string {
  return decl.replace(/^(background|color):/, '').replace(/;$/, '').trim();
}

/**
 * The screen a section is about, when there is one.
 *
 * `ZoomableShot` is the panel — the tinted box, the thumbnail, the route
 * badge and the click-to-expand. The figure and caption stay here, so this
 * page's inline figure and /gallery's grid card can lay out differently
 * while behaving identically.
 *
 * Runs the full article column. It used to cap at 560 — half the available
 * width — which made the widest thing on the page conceptually the narrowest
 * thing on it visually, on a reference page whose job is showing you the
 * screen (#604).
 */
function Shot({ section }: { section: string }) {
  const shot = WIKI_SHOTS[section];
  if (!shot) return null;
  return (
    <figure style={{ margin: '22px 0 0', display: 'flex', flexDirection: 'column', gap: 10 }}>
      {/* Captured at 1440x900 — the same 16:10 as the panel, so it fills
          without cropping. The panel is a client component because the page
          is not: drawing the boundary around the one element that needs
          state keeps `metadata` exportable here. */}
      <ZoomableShot
        src={`/gallery/${shot.slot}.png`}
        alt={`The ${shot.title} screen in Sapling`}
        title={shot.title}
        caption={shot.caption}
        route={shot.route}
        sizes="(max-width: 900px) 100vw, 880px"
        radius={12}
      />
      <figcaption style={{ fontFamily: SERIF, fontSize: 16.5, lineHeight: 1.55, color: '#6f6857' }}>
        {shot.caption}
      </figcaption>
    </figure>
  );
}

function Section({ id, title, lede, children }: {
  id: string; title: string; lede?: React.ReactNode; children: React.ReactNode;
}) {
  return (
    <section id={id} style={SECTION}>
      <h2 style={H2}>{title}</h2>
      {lede ? <p style={LEDE}>{lede}</p> : null}
      <Shot section={id} />
      <div style={{ marginTop: 18 }}>{children}</div>
    </section>
  );
}

/** A name and what it means. */
function TermRows({ rows }: { rows: readonly { term: string; def: string }[] }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
      {rows.map((r) => (
        <div key={r.term} style={{ display: 'grid', gridTemplateColumns: `${KEY_COL} minmax(0,1fr)`, gap: ROW_GAP, padding: '15px 0', borderTop: ROW_TOP }}>
          <span style={KEY}>{r.term}</span>
          <span style={DEF}>{r.def}</span>
        </div>
      ))}
    </div>
  );
}

/** A name, the value the product uses, and why that value. */
function SpecRows({ rows }: { rows: readonly { label: string; value: string; note: string }[] }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
      {rows.map((r) => (
        <div key={r.label} style={{ display: 'grid', gridTemplateColumns: `${KEY_COL} minmax(0,1fr)`, gap: ROW_GAP, padding: '15px 0', borderTop: ROW_TOP }}>
          <span style={KEY}>{r.label}</span>
          <span style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
            <span style={VALUE}>{r.value}</span>
            <span style={DEF}>{r.note}</span>
          </span>
        </div>
      ))}
    </div>
  );
}

/**
 * A checked list of plain statements.
 *
 * Runs the full column rather than a row cell, so it takes the wider of the
 * page's two prose sizes — same edge as the rows above it, same measure as
 * the ledes it reads like.
 */
function FactList({ items }: { items: readonly string[] }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {items.map((d) => (
        <div key={d} style={{ display: 'flex', gap: 14, alignItems: 'flex-start' }}>
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#2D8F5C" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0, marginTop: 5 }}>
            <path d="M20 6L9 17l-5-5" />
          </svg>
          <span style={PROSE}>{d}</span>
        </div>
      ))}
    </div>
  );
}

export default function WikiPage() {
  return (
    <CompanionShell current="/wiki">
      <div>
        {/*
          One stack: eyebrow, the word, the sentence under it.

          This used to be a two-column grid, on the theory that setting the
          title against the deck spread the weight across the full width. It
          did the opposite — a one-word title beside a three-line paragraph
          left its own cell ~85% empty, and the two halves never read as one
          unit (#603). A single column with the title at the companion display
          scale gives the deck something to hang off, and needs no media query
          to collapse because there is nothing to collapse.
        */}
        <header style={{ paddingBottom: 30, borderBottom: '1px solid rgba(42,39,31,0.12)' }}>
          <div style={{ animation: 'fadeUp 700ms ease both' }}>
            <span style={{ display: 'block', fontFamily: MONO, fontSize: 10, letterSpacing: '0.14em', textTransform: 'uppercase', color: '#6f6857' }}>
              Reference
            </span>
            {/* The shared companion display scale, not a local size: at a flat
                48 the word was smaller than the air around it. */}
            <h1 style={{ ...ARTICLE.title, margin: '14px 0 0' }}>
              Wiki
            </h1>
          </div>
          <p style={{ ...PROSE, margin: '18px 0 0', animation: 'fadeUp 700ms ease 140ms both' }}>
            Exact definitions for the terms and numbers Sapling puts on screen.
          </p>
        </header>

        <div style={{ marginTop: 40, display: 'grid', gridTemplateColumns: 'minmax(0,190px) minmax(0,1fr)', gap: 'clamp(24px,4vw,56px)', alignItems: 'start' }}>
          <WikiRail />

          <div style={{ display: 'flex', flexDirection: 'column', gap: 52 }}>
            <Section
              id="graph"
              title="Knowledge graph"
              lede="One node per concept in a course, joined by an edge when the two are related. Each course anchors its own cluster, so a semester reads as a handful of constellations rather than one tangle."
            >
              <TermRows rows={WIKI_GRAPH_TERMS} />
            </Section>

            <Section
              id="mastery"
              title="Mastery tiers"
              lede="Every node carries a mastery score from 0.00 to 1.00, drawn as a ring around it. Four tiers are derived from that score, and they are what the tier filters, the dashboard counts, and the quiz generator all read."
            >
              <div style={{ display: 'flex', flexDirection: 'column' }}>
                {WIKI_TIERS.map((t) => (
                  <div key={t.name} style={{ display: 'grid', gridTemplateColumns: '12px minmax(0,124px) minmax(0,116px) minmax(0,1fr)', gap: 16, alignItems: 'baseline', padding: '15px 0', borderTop: ROW_TOP }}>
                    <span style={{ width: 10, height: 10, borderRadius: 99, background: cssColor(t.dot) }} />
                    <span style={VALUE}>{t.name}</span>
                    <span style={{ fontFamily: MONO, fontSize: 13.5, lineHeight: 1.5, color: '#6f6857', whiteSpace: 'nowrap' }}>{t.range}</span>
                    <span style={DEF}>{t.meaning}</span>
                  </div>
                ))}
              </div>
            </Section>

            <Section
              id="deltas"
              title="How mastery moves"
              lede="Mastery moves on demonstrated understanding, not time spent — which means several things you might expect to move it do not. Every change is appended to your graph with a reason attached."
            >
              {/* The formula reads as an equation, so it gets to look like one. */}
              <div style={{ padding: '16px 18px', borderRadius: 10, background: '#faf8f3', border: '1px solid rgba(42,39,31,0.10)', fontFamily: MONO, fontSize: 15, lineHeight: 1.6, color: '#1a1814', overflowX: 'auto' }}>
                {WIKI_MASTERY_FORMULA}
              </div>
              <p style={{ ...LEDE, marginTop: 14 }}>
                That is one quiz. Around seventeen correct answers in a row take a concept from
                nothing to mastered — roughly three or four full quizzes.
              </p>
              <div style={{ marginTop: 14 }}>
                <div style={{ display: 'flex', flexDirection: 'column' }}>
                  {WIKI_MASTERY_MOVES.map((m) => (
                    <div key={m.source} style={{ display: 'grid', gridTemplateColumns: `${KEY_COL} minmax(0,132px) minmax(0,1fr)`, gap: ROW_GAP, alignItems: 'baseline', padding: '15px 0', borderTop: ROW_TOP }}>
                      <span style={VALUE}>{m.source}</span>
                      <span style={{ fontFamily: MONO, fontSize: 13.5, color: '#1B6C42', whiteSpace: 'nowrap' }}>{m.value}</span>
                      <span style={DEF}>{m.note}</span>
                    </div>
                  ))}
                </div>
              </div>
            </Section>

            <Section
              id="progress"
              title="Progress stats"
              lede="The numbers around the app that describe your movement rather than your position."
            >
              <TermRows rows={WIKI_PROGRESS_TERMS} />
            </Section>

            <Section
              id="quizzes"
              title="Adaptive quizzes"
              lede="A quiz is written fresh each time from your graph, weighted toward the concepts you have mastered least. These are the values the quiz screen builds its selectors from, so it can never offer one the server refuses."
            >
              <SpecRows rows={WIKI_QUIZ_SPECS} />
            </Section>

            <Section
              id="tutor"
              title="Tutor modes"
              lede="Three ways to work the same concept. You pick one per conversation, and it changes the tutor's stance rather than its knowledge — all three read your graph and the documents you uploaded."
            >
              <div style={{ display: 'flex', flexDirection: 'column' }}>
                {WIKI_MODES.map((m) => (
                  <div key={m.name} style={{ display: 'grid', gridTemplateColumns: `${KEY_COL} minmax(0,1fr)`, gap: ROW_GAP, padding: '15px 0', borderTop: ROW_TOP }}>
                    <span style={{ ...KEY, letterSpacing: '0.1em', textTransform: 'uppercase' }}>{m.name}</span>
                    <span style={DEF}>{m.def}</span>
                  </div>
                ))}
              </div>
            </Section>

            <Section
              id="uploads"
              title="Uploads"
              lede="What Sapling accepts, and what it does to read it."
            >
              <SpecRows rows={WIKI_UPLOAD_SPECS} />
            </Section>

            <Section
              id="ingestion"
              title="Ingestion"
              lede="What happens to a file after you drop it in. These five steps stream to your screen as they run, so you can always see why a concept or a date exists."
            >
              {/* Same two columns as a spec row — the step number is the key —
                  so the step bodies read on the same measure as every other
                  definition instead of running the full column. */}
              <div style={{ display: 'flex', flexDirection: 'column' }}>
                {WIKI_PIPELINE.map((p) => (
                  <div key={p.num} style={{ display: 'grid', gridTemplateColumns: `${KEY_COL} minmax(0,1fr)`, gap: ROW_GAP, padding: '15px 0', borderTop: ROW_TOP }}>
                    <span style={{ fontFamily: MONO, fontSize: 13.5, letterSpacing: '0.16em', color: '#2D8F5C', paddingTop: 2 }}>{p.num}</span>
                    <span style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                      <span style={VALUE}>{p.title}</span>
                      <span style={DEF}>{p.body}</span>
                    </span>
                  </div>
                ))}
              </div>
            </Section>

            <Section
              id="notes"
              title="Notetaker"
              lede="Your own writing, turned into concepts on the same tree everything else feeds."
            >
              <SpecRows rows={WIKI_NOTE_SPECS} />
            </Section>

            <Section
              id="flashcards"
              title="Flashcards"
              lede="Flip a card and rate how it went. Three ratings, and what each one actually does."
            >
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px,1fr))', gap: 12 }}>
                {WIKI_FLASHCARD_RATINGS.map((r) => (
                  <div key={r.label} style={{ border: '1px solid rgba(42,39,31,0.10)', borderRadius: 12, padding: 18, background: '#faf8f3', display: 'flex', alignItems: 'center', gap: 9 }}>
                    <span style={{ ...VALUE, color: cssColor(r.tone) }}>{r.label}</span>
                    <span style={{ fontFamily: MONO, fontSize: 12, color: '#6f6857' }}>KEY {r.key}</span>
                  </div>
                ))}
              </div>
              <div style={{ marginTop: 16 }}>
                <FactList items={WIKI_FLASHCARD_NOTES} />
              </div>
            </Section>

            <Section
              id="guide"
              title="Study guide"
              lede="One exam-ready review per course, assembled from what you have already uploaded."
            >
              <SpecRows rows={WIKI_GUIDE_SPECS} />
            </Section>

            <Section
              id="calendar"
              title="Syllabus and calendar"
              lede="The one document every course hands you, turned into a working plan. One upload shows up in three places."
            >
              <SpecRows rows={WIKI_CALENDAR_SPECS} />
            </Section>

            <Section
              id="grades"
              title="Grade scale"
              lede="Your gradebook tracks the grade that goes on your transcript. These are the letter bands a percentage maps onto by default."
            >
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {WIKI_LETTERS.map((l) => (
                  <span key={l.letter} style={{ display: 'flex', alignItems: 'baseline', gap: 8, padding: '8px 14px', borderRadius: 8, background: '#faf8f3', border: '1px solid rgba(42,39,31,0.10)' }}>
                    <b style={{ fontSize: 16, fontWeight: 600, color: '#1a1814' }}>{l.letter}</b>
                    <span style={{ fontFamily: MONO, fontSize: 13, color: '#6f6857' }}>{l.min}</span>
                  </span>
                ))}
              </div>
              <div style={{ marginTop: 18 }}>
                <FactList items={WIKI_GRADE_NOTES} />
              </div>
            </Section>

            <Section
              id="rooms"
              title="Study rooms"
              lede="A chat scoped to the people studying the same thing, next to a comparison of where you each are."
            >
              <SpecRows rows={WIKI_ROOM_SPECS} />
            </Section>

            <Section
              id="class"
              title="Class intelligence"
              lede="The anonymised, class-wide layer. It is the least-finished thing in Sapling, so here is exactly how far it reaches."
            >
              <TermRows rows={WIKI_CLASS_TERMS} />
            </Section>

            <Section
              id="onboarding"
              title="Onboarding"
              lede="The short path from signed in to on the tree."
            >
              <SpecRows rows={WIKI_ONBOARDING_SPECS} />
            </Section>

            <Section
              id="achievements"
              title="Achievements"
              lede="What you earn as you go, and what it unlocks."
            >
              <TermRows rows={WIKI_ACHIEVEMENT_TERMS} />
            </Section>

            <Section id="privacy" title="Your data">
              <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                {WIKI_DATA_FACTS.map((d) => (
                  <div key={d.fact} style={{ display: 'flex', gap: 14, alignItems: 'flex-start' }}>
                    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#2D8F5C" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0, marginTop: 6 }}>
                      <path d="M20 6L9 17l-5-5" />
                    </svg>
                    <span style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                      <span style={{ ...VALUE, lineHeight: 1.5 }}>{d.fact}</span>
                      <span style={PROSE}>{d.detail}</span>
                    </span>
                  </div>
                ))}
              </div>
            </Section>
          </div>
        </div>
      </div>
    </CompanionShell>
  );
}
