import type { Metadata } from 'next';
import { CompanionBody, CompanionShell } from '@/components/companion/CompanionShell';
import { Bullets, PageTitle, Prose, SectionHeading } from '@/components/companion/primitives';
import {
  WIKI_DATA_FACTS, WIKI_GRAPH_TERMS, WIKI_LETTERS, WIKI_MODES,
  WIKI_PIPELINE, WIKI_RATINGS, WIKI_TIERS, WIKI_TOC,
} from '@/lib/landing/companionContent';

export const metadata: Metadata = {
  title: 'Wiki',
  description:
    'Exact definitions for the terms and numbers Sapling puts on screen. Every value here is the one the product actually uses.',
};

const SERIF = "'Spectral',Georgia,serif";
const MONO = "'JetBrains Mono',monospace";

/** `dot`/`tone` arrive from the source as CSS declaration strings. */
function cssColor(decl: string): string {
  return decl.replace(/^(background|color):/, '').replace(/;$/, '').trim();
}

function Row({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', gap: 12, padding: '12px 0', borderBottom: '1px solid rgba(42,39,31,0.08)', alignItems: 'baseline' }}>
      {children}
    </div>
  );
}

function Section({ id, title, lede, children }: { id: string; title: string; lede: string; children?: React.ReactNode }) {
  return (
    <section style={{ marginTop: 56, scrollMarginTop: 110 }} id={id}>
      <SectionHeading>{title}</SectionHeading>
      <p style={{ margin: '0 0 20px', fontFamily: SERIF, fontSize: 15, lineHeight: 1.65, color: '#3f3b31' }}>{lede}</p>
      {children}
    </section>
  );
}

export default function WikiPage() {
  return (
    <CompanionShell current="/wiki">
      <CompanionBody>
        <PageTitle>Wiki</PageTitle>
        <Prose delay={80}>
          Exact definitions for the terms and numbers Sapling puts on screen. Every value here is
          the one the product actually uses.
        </Prose>

        <nav aria-label="On this page" style={{ marginTop: 32, display: 'flex', flexWrap: 'wrap', gap: 10, animation: 'fadeUp 700ms ease 140ms both' }}>
          {WIKI_TOC.map((t) => (
            <a key={t.href} href={t.href} style={{ padding: '6px 13px', borderRadius: 99, border: '1px solid rgba(42,39,31,0.16)', fontSize: 12.5, color: '#6f6857' }}>
              {t.title}
            </a>
          ))}
        </nav>

        <Section
          id="graph"
          title="Knowledge graph"
          lede="One node per concept in a course, joined by an edge when learning one depends on the other. Nodes are positioned by unit, so the shape of the graph is the shape of the syllabus."
        >
          {WIKI_GRAPH_TERMS.map((t) => (
            <Row key={t.term}>
              <span style={{ flex: '0 0 150px', fontSize: 14, fontWeight: 600, color: '#1a1814' }}>{t.term}</span>
              <span style={{ fontFamily: SERIF, fontSize: 14.5, lineHeight: 1.6, color: '#3f3b31' }}>{t.def}</span>
            </Row>
          ))}
        </Section>

        <Section
          id="mastery"
          title="Mastery tiers"
          lede="Every node carries a mastery score from 0 to 1, drawn as a ring around it. The score moves on demonstrated understanding, not time spent."
        >
          {WIKI_TIERS.map((t) => (
            <Row key={t.name}>
              <span style={{ flex: '0 0 auto', width: 10, height: 10, borderRadius: 99, background: cssColor(t.dot), alignSelf: 'center' }} />
              <span style={{ flex: '0 0 110px', fontSize: 14, fontWeight: 600, color: '#1a1814' }}>{t.name}</span>
              <span style={{ flex: '0 0 90px', fontFamily: MONO, fontSize: 12, color: '#6f6857' }}>{t.range}</span>
              <span style={{ fontFamily: SERIF, fontSize: 14.5, lineHeight: 1.6, color: '#3f3b31' }}>{t.meaning}</span>
            </Row>
          ))}
        </Section>

        <Section
          id="review"
          title="Spaced review"
          lede="After each card you rate your recall, and that rating sets when the card comes back. Rating a card also writes to the mastery score of the concept it tests."
        >
          {WIKI_RATINGS.map((r) => (
            <Row key={r.label}>
              <span style={{ flex: '0 0 110px', fontSize: 14, fontWeight: 600, color: cssColor(r.tone) }}>{r.label}</span>
              <span style={{ flex: '0 0 60px', fontFamily: MONO, fontSize: 12, color: '#9a9689' }}>key {r.key}</span>
              <span style={{ fontFamily: MONO, fontSize: 13, color: '#3f3b31' }}>due in {r.due}</span>
            </Row>
          ))}
        </Section>

        <Section
          id="tutor"
          title="Tutor modes"
          lede="Three ways to work the same concept. All three are grounded in documents you uploaded, and none of them will hand over an answer."
        >
          {WIKI_MODES.map((m) => (
            <Row key={m.name}>
              <span style={{ flex: '0 0 150px', fontSize: 14, fontWeight: 600, color: '#1a1814' }}>{m.name}</span>
              <span style={{ fontFamily: SERIF, fontSize: 14.5, lineHeight: 1.6, color: '#3f3b31' }}>{m.def}</span>
            </Row>
          ))}
        </Section>

        <Section
          id="ingestion"
          title="Ingestion"
          lede="What happens to a file after you drop it in. Each step is visible in the product, so you can always see why a concept or a date exists."
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
            {WIKI_PIPELINE.map((s) => (
              <div key={s.num} style={{ display: 'flex', gap: 16 }}>
                <span style={{ flex: '0 0 auto', fontFamily: MONO, fontSize: 12, color: '#2D8F5C' }}>{s.num}</span>
                <div>
                  <p style={{ margin: 0, fontSize: 15, fontWeight: 600, color: '#1a1814' }}>{s.title}</p>
                  <p style={{ margin: '4px 0 0', fontFamily: SERIF, fontSize: 14.5, lineHeight: 1.6, color: '#3f3b31' }}>{s.body}</p>
                </div>
              </div>
            ))}
          </div>
        </Section>

        <Section
          id="grades"
          title="Grade scale"
          lede="Category weights come from your syllabus, and every score rolls into one weighted number. These are the letter bands it maps onto."
        >
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
            {WIKI_LETTERS.map((l) => (
              <div key={l.letter} style={{ display: 'flex', alignItems: 'baseline', gap: 8, padding: '8px 14px', borderRadius: 8, border: '1px solid rgba(42,39,31,0.12)', background: '#faf8f3' }}>
                <span style={{ fontSize: 14, fontWeight: 600, color: '#1a1814' }}>{l.letter}</span>
                <span style={{ fontFamily: MONO, fontSize: 12, color: '#6f6857' }}>{l.min}</span>
              </div>
            ))}
          </div>
        </Section>

        <Section id="privacy" title="Your data" lede="">
          <Bullets items={WIKI_DATA_FACTS} />
        </Section>
      </CompanionBody>
    </CompanionShell>
  );
}
