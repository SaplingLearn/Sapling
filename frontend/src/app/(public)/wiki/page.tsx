import type { Metadata } from 'next';
import { CompanionShell } from '@/components/companion/CompanionShell';
import { ZoomableShot } from '@/components/companion/ZoomableShot';
import { WikiRail } from './WikiRail';
import { WikiSearchBox, WikiSearchProvider } from './WikiSearch';
import {
  WIKI_ACHIEVEMENT_TERMS, WIKI_CALENDAR_SPECS, WIKI_CLASS_TERMS, WIKI_DATA_FACTS,
  WIKI_FLASHCARD_NOTES, WIKI_FLASHCARD_RATINGS, WIKI_GRADE_NOTES, WIKI_GRAPH_TERMS,
  WIKI_GUIDE_SPECS, WIKI_LETTERS, WIKI_MASTERY_FORMULA, WIKI_MASTERY_MOVES, WIKI_MODES,
  WIKI_NOTE_SPECS, WIKI_ONBOARDING_SPECS, WIKI_PIPELINE, WIKI_PROGRESS_TERMS,
  WIKI_QUIZ_SPECS, WIKI_ROOM_SPECS, WIKI_SHOTS, WIKI_TIERS, WIKI_UPLOAD_SPECS,
} from '@/lib/landing/companionContent';

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
    <figure className="mt-5.5 mx-0 mb-0 flex flex-col gap-2.5">
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
      <figcaption className="font-serif text-[16.5px] leading-[1.55] text-text-muted">
        {shot.caption}
      </figcaption>
    </figure>
  );
}

function Section({ id, title, lede, children }: {
  id: string; title: string; lede?: React.ReactNode; children: React.ReactNode;
}) {
  return (
    <section id={id} className="[scroll-margin-top:84px]">
      <h2 className="m-0 font-display font-medium text-5xl leading-[1.2] tracking-[-0.015em]">{title}</h2>
      {lede ? <p className="font-serif text-2xl leading-[1.55] text-ink-600 mt-5 mx-0 mb-0">{lede}</p> : null}
      <Shot section={id} />
      <div className="mt-6.5">{children}</div>
    </section>
  );
}

/** A name and what it means. */
function TermRows({ rows }: { rows: readonly { term: string; def: string }[] }) {
  return (
    <div className="flex flex-col">
      {rows.map((r) => (
        <div key={r.term} className="grid grid-cols-[minmax(0,172px)_minmax(0,1fr)] gap-5 py-[15px] px-0 border-t border-t-[rgba(42,39,31,0.08)]">
          <span className="font-sans text-[13.5px] tracking-[0.06em] text-brand-forest">{r.term}</span>
          <span className="font-serif text-xl leading-[1.6] text-ink-600">{r.def}</span>
        </div>
      ))}
    </div>
  );
}

/** A name, the value the product uses, and why that value. */
function SpecRows({ rows }: { rows: readonly { label: string; value: string; note: string }[] }) {
  return (
    <div className="flex flex-col">
      {rows.map((r) => (
        <div key={r.label} className="grid grid-cols-[minmax(0,172px)_minmax(0,1fr)] gap-5 py-[15px] px-0 border-t border-t-[rgba(42,39,31,0.08)]">
          <span className="font-sans text-[13.5px] tracking-[0.06em] text-brand-forest">{r.label}</span>
          <span className="flex flex-col gap-[7px]">
            <span className="text-[17px] font-semibold text-ink-800">{r.value}</span>
            <span className="font-serif text-xl leading-[1.6] text-ink-600">{r.note}</span>
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
    <div className="flex flex-col gap-3">
      {items.map((d) => (
        <div key={d} className="flex gap-3.5 items-start">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#597536" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" className="shrink-0 mt-[5px]">
            <path d="M20 6L9 17l-5-5" />
          </svg>
          <span className="font-serif text-2xl leading-[1.55] text-ink-600">{d}</span>
        </div>
      ))}
    </div>
  );
}

export default function WikiPage() {
  return (
    <CompanionShell current="/wiki">
      {/* One provider over both slots: the box lives in the masthead, the
          results in the rail below it, and the eighteen sections between
          them stay server-rendered children that pass straight through. */}
      <WikiSearchProvider>
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
        <header className="pb-10.5 border-b border-b-[rgba(42,39,31,0.12)]">
          <div className="[animation:fadeUp_700ms_ease_both]">
            <span className="block font-sans text-[12.5px] text-text-muted">
              Reference
            </span>
            {/* The shared companion display scale, not a local size: at a flat
                48 the word was smaller than the air around it. */}
            <h1 className="font-display font-medium text-[length:clamp(1.9rem,4vw,2.9rem)] leading-[1.12] tracking-[-0.02em] text-ink-800 mt-4 mx-0 mb-0">
              Wiki
            </h1>
          </div>
          <p className="font-serif text-2xl leading-[1.55] text-ink-600 mt-5 mx-0 mb-0 [animation:fadeUp_700ms_ease_140ms_both]">
            Exact definitions for the terms and numbers Sapling puts on screen.
          </p>
          {/* Under the deck, not in the rail: here it reads as "search this
              reference" against the page's own title, where in the rail it
              read as a filter on the list it happened to sit above. It
              still drives the rail — see WikiSearch.tsx. */}
          <WikiSearchBox style={{ margin: '26px 0 0', animation: 'fadeUp 700ms ease 220ms both' }} />
        </header>

        <div className="wiki-grid mt-14 grid grid-cols-[minmax(0,190px)_minmax(0,1fr)] gap-[clamp(24px,4vw,56px)] [align-items:start]">
          <WikiRail />

          <div className="flex flex-col gap-19">
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
              <div className="flex flex-col">
                {WIKI_TIERS.map((t) => (
                  <div key={t.name} className="grid grid-cols-[12px_minmax(0,124px)_minmax(0,116px)_minmax(0,1fr)] gap-4 items-baseline py-[15px] px-0 border-t border-t-[rgba(42,39,31,0.08)]">
                    <span className="w-2.5 h-2.5 rounded-[99px]" style={{ background: cssColor(t.dot) }} />
                    <span className="text-[17px] font-semibold text-ink-800">{t.name}</span>
                    <span className="font-sans text-[13.5px] leading-[1.5] text-text-muted whitespace-nowrap">{t.range}</span>
                    <span className="font-serif text-xl leading-[1.6] text-ink-600">{t.meaning}</span>
                  </div>
                ))}
              </div>
            </Section>

            <Section
              id="deltas"
              title="How mastery moves"
              lede="Mastery moves on demonstrated understanding, not time spent, which means several things you might expect to move it do not. Every change is appended to your graph with a reason attached."
            >
              {/* The formula reads as an equation, so it gets to look like one. */}
              <div className="py-4 px-4.5 rounded-md bg-ink-0 border border-[rgba(42,39,31,0.10)] font-sans text-[15px] leading-[1.6] text-ink-800 overflow-x-auto">
                {WIKI_MASTERY_FORMULA}
              </div>
              <p className="font-serif text-2xl leading-[1.55] text-ink-600 mx-0 mb-0 mt-3.5">
                That is one quiz. Around seventeen correct answers in a row take a concept from
                nothing to mastered, roughly three or four full quizzes.
              </p>
              <div className="mt-3.5">
                <div className="flex flex-col">
                  {WIKI_MASTERY_MOVES.map((m) => (
                    <div key={m.source} className="grid grid-cols-[minmax(0,172px)_minmax(0,132px)_minmax(0,1fr)] gap-5 items-baseline py-[15px] px-0 border-t border-t-[rgba(42,39,31,0.08)]">
                      <span className="text-[17px] font-semibold text-ink-800">{m.source}</span>
                      <span className="font-sans text-[13.5px] text-brand-forest whitespace-nowrap">{m.value}</span>
                      <span className="font-serif text-xl leading-[1.6] text-ink-600">{m.note}</span>
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
              lede="Three ways to work the same concept. You pick one per conversation, and it changes the tutor's stance rather than its knowledge; all three read your graph and the documents you uploaded."
            >
              <div className="flex flex-col">
                {WIKI_MODES.map((m) => (
                  <div key={m.name} className="grid grid-cols-[minmax(0,172px)_minmax(0,1fr)] gap-5 py-[15px] px-0 border-t border-t-[rgba(42,39,31,0.08)]">
                    <span className="font-sans text-[13.5px] tracking-[0.06em] text-brand-forest">{m.name}</span>
                    <span className="font-serif text-xl leading-[1.6] text-ink-600">{m.def}</span>
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
              <div className="flex flex-col">
                {WIKI_PIPELINE.map((p) => (
                  <div key={p.num} className="grid grid-cols-[minmax(0,172px)_minmax(0,1fr)] gap-5 py-[15px] px-0 border-t border-t-[rgba(42,39,31,0.08)]">
                    <span className="font-sans text-[13.5px] tracking-[0.16em] text-brand-forest-bright pt-0.5">{p.num}</span>
                    <span className="flex flex-col gap-[7px]">
                      <span className="text-[17px] font-semibold text-ink-800">{p.title}</span>
                      <span className="font-serif text-xl leading-[1.6] text-ink-600">{p.body}</span>
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
              <div className="grid grid-cols-[repeat(auto-fit,_minmax(160px,1fr))] gap-3">
                {WIKI_FLASHCARD_RATINGS.map((r) => (
                  <div key={r.label} className="border border-[rgba(42,39,31,0.10)] rounded-[12px] p-4.5 bg-ink-0 flex items-center gap-[9px]">
                    <span className="text-[17px] font-semibold text-ink-800" style={{ color: cssColor(r.tone) }}>{r.label}</span>
                    <span className="font-sans text-[13.5px] text-text-muted">KEY {r.key}</span>
                  </div>
                ))}
              </div>
              <div className="mt-4">
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
              <div className="flex flex-wrap gap-2">
                {WIKI_LETTERS.map((l) => (
                  <span key={l.letter} className="flex items-baseline gap-2 py-2 px-3.5 rounded-[8px] bg-ink-0 border border-[rgba(42,39,31,0.10)]">
                    <b className="text-[17px] font-semibold text-ink-800">{l.letter}</b>
                    <span className="font-sans text-[13.5px] text-text-muted">{l.min}</span>
                  </span>
                ))}
              </div>
              <div className="mt-4.5">
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
              <div className="flex flex-col gap-4">
                {WIKI_DATA_FACTS.map((d) => (
                  <div key={d.fact} className="flex gap-3.5 items-start">
                    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#597536" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" className="shrink-0 mt-1.5">
                      <path d="M20 6L9 17l-5-5" />
                    </svg>
                    <span className="flex flex-col gap-[7px]">
                      <span className="text-[17px] font-semibold text-ink-800 leading-[1.5]">{d.fact}</span>
                      <span className="font-serif text-xl leading-[1.6] text-ink-600">{d.detail}</span>
                    </span>
                  </div>
                ))}
              </div>
            </Section>
          </div>
        </div>
      </div>
      </WikiSearchProvider>
    </CompanionShell>
  );
}
