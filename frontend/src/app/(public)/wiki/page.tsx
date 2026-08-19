import type { Metadata } from 'next';
import { CompanionShell } from '@/components/companion/CompanionShell';
import {
  WIKI_DATA_FACTS, WIKI_GRAPH_TERMS, WIKI_LETTERS, WIKI_MODES,
  WIKI_PIPELINE, WIKI_RATINGS, WIKI_TIERS, WIKI_TOC,
} from '@/lib/landing/companionContent';

/**
 * Wiki.
 *
 * Ported from `Wiki.dc.html`. A sticky contents rail beside seven definition
 * sections, each laid out for what it holds: two-column term/definition rows
 * for the graph and tutor modes, a four-column row with a tier swatch for
 * mastery, cards for the review intervals, a numbered list for ingestion, and
 * chips for the grade bands.
 */

export const metadata: Metadata = {
  title: 'Wiki',
  description:
    'Exact definitions for the terms and numbers Sapling puts on screen. Every value here is the one the product actually uses.',
  alternates: { canonical: '/wiki' },
};

const MONO = "'JetBrains Mono',monospace";
const SERIF = "'Spectral',Georgia,serif";
const DISPLAY = "'Playfair Display',Georgia,serif";

const H2: React.CSSProperties = {
  margin: 0, fontFamily: DISPLAY, fontWeight: 500, fontSize: 26,
  lineHeight: 1.2, letterSpacing: '-0.015em',
};
/**
 * The offset belongs on the <section>, not the <h2>: the TOC fragments
 * (#graph, #mastery, …) target the sections, so a scroll-margin on the heading
 * is never consulted and every anchor landed under CompanionShell's sticky
 * ~92px header. 100px clears the scrim with a little air.
 */
const SECTION: React.CSSProperties = { scrollMarginTop: 100 };
const LEDE: React.CSSProperties = {
  margin: '12px 0 0', fontFamily: SERIF, fontSize: 15, lineHeight: 1.6,
  color: '#3f3b31', maxWidth: '64ch',
};
/** Definition text, shared by every row style below. */
const DEF: React.CSSProperties = { fontFamily: SERIF, fontSize: 14.5, lineHeight: 1.6, color: '#3f3b31' };
/** The hairline that separates rows within a section. */
const ROW_TOP = '1px solid rgba(42,39,31,0.08)';

export default function WikiPage() {
  return (
    <CompanionShell current="/wiki">
      <div style={{ flex: 1, minWidth: 0, width: '100%', maxWidth: 1060, margin: '0 auto', padding: '64px 32px', boxSizing: 'border-box' }}>
        <span style={{ display: 'block', fontFamily: MONO, fontSize: 10, letterSpacing: '0.14em', textTransform: 'uppercase', color: '#6f6857', animation: 'fadeUp 600ms ease both' }}>
          Reference
        </span>
        <h1 style={{ margin: '14px 0 0', fontFamily: DISPLAY, fontWeight: 500, fontSize: 48, lineHeight: 1.15, letterSpacing: '-0.015em', animation: 'fadeUp 700ms ease 60ms both' }}>
          Wiki
        </h1>
        <p style={{ margin: '24px 0 0', fontFamily: SERIF, fontSize: 16, lineHeight: 1.6, color: '#3f3b31', maxWidth: '62ch', animation: 'fadeUp 700ms ease 140ms both' }}>
          Exact definitions for the terms and numbers Sapling puts on screen. Every value here is
          the one the product actually uses.
        </p>

        <div style={{ marginTop: 44, display: 'grid', gridTemplateColumns: 'minmax(0,190px) minmax(0,1fr)', gap: 'clamp(24px,4vw,56px)', alignItems: 'start' }}>
          <aside style={{ position: 'sticky', top: 84, display: 'flex', flexDirection: 'column', gap: 2 }}>
            <span style={{ fontFamily: MONO, fontSize: 10, letterSpacing: '0.14em', textTransform: 'uppercase', color: '#6f6857', marginBottom: 8 }}>
              Contents
            </span>
            {WIKI_TOC.map((t) => (
              <a key={t.href} href={t.href} className="cp-navlink" style={{ fontSize: 13.5, color: '#6f6857', padding: '5px 0' }}>
                {t.title}
              </a>
            ))}
          </aside>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 52 }}>
            <section id="graph" style={SECTION}>
              <h2 style={H2}>Knowledge graph</h2>
              <p style={LEDE}>
                One node per concept in a course, joined by an edge when learning one depends on the
                other. Nodes are positioned by unit, so the shape of the graph is the shape of the
                syllabus.
              </p>
              <div style={{ marginTop: 18, display: 'flex', flexDirection: 'column', gap: 10 }}>
                {WIKI_GRAPH_TERMS.map((g) => (
                  <div key={g.term} style={{ display: 'grid', gridTemplateColumns: 'minmax(0,140px) minmax(0,1fr)', gap: 18, padding: '12px 0', borderTop: ROW_TOP }}>
                    <span style={{ fontFamily: MONO, fontSize: 11, letterSpacing: '0.06em', color: '#1B6C42' }}>{g.term}</span>
                    <span style={DEF}>{g.def}</span>
                  </div>
                ))}
              </div>
            </section>

            <section id="mastery" style={SECTION}>
              <h2 style={H2}>Mastery tiers</h2>
              <p style={LEDE}>
                Every node carries a mastery score from 0 to 1, drawn as a ring around it. The score
                moves on demonstrated understanding, not time spent.
              </p>
              <div style={{ marginTop: 18, display: 'flex', flexDirection: 'column', gap: 0 }}>
                {WIKI_TIERS.map((t) => (
                  <div key={t.name} style={{ display: 'grid', gridTemplateColumns: '12px minmax(0,104px) minmax(0,86px) minmax(0,1fr)', gap: 14, alignItems: 'baseline', padding: '13px 0', borderTop: ROW_TOP }}>
                    <span style={{ width: 10, height: 10, borderRadius: 99, background: t.dot }} />
                    <span style={{ fontSize: 14, fontWeight: 600, color: '#1a1814' }}>{t.name}</span>
                    <span style={{ fontFamily: MONO, fontSize: 11, lineHeight: 1.5, color: '#6f6857', whiteSpace: 'nowrap' }}>{t.range}</span>
                    <span style={DEF}>{t.meaning}</span>
                  </div>
                ))}
              </div>
            </section>

            <section id="review" style={SECTION}>
              <h2 style={H2}>Spaced review</h2>
              <p style={LEDE}>
                After each card you rate your recall, and that rating sets when the card comes back.
                Rating a card also writes to the mastery score of the concept it tests.
              </p>
              <div style={{ marginTop: 18, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px,1fr))', gap: 12 }}>
                {WIKI_RATINGS.map((r) => (
                  <div key={r.label} style={{ border: '1px solid rgba(42,39,31,0.10)', borderRadius: 12, padding: 16, background: '#faf8f3', display: 'flex', flexDirection: 'column', gap: 6 }}>
                    <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontSize: 14.5, fontWeight: 600, color: '#1a1814' }}>{r.label}</span>
                      <span style={{ fontFamily: MONO, fontSize: 10, color: '#6f6857' }}>KEY {r.key}</span>
                    </span>
                    <span style={{ fontFamily: MONO, fontSize: 12, color: r.tone }}>next in {r.due}</span>
                  </div>
                ))}
              </div>
            </section>

            <section id="tutor" style={SECTION}>
              <h2 style={H2}>Tutor modes</h2>
              <p style={LEDE}>
                Three ways to work the same concept. All three are grounded in documents you
                uploaded, and none of them will hand over an answer.
              </p>
              <div style={{ marginTop: 18, display: 'flex', flexDirection: 'column', gap: 0 }}>
                {WIKI_MODES.map((m) => (
                  <div key={m.name} style={{ display: 'grid', gridTemplateColumns: 'minmax(0,120px) minmax(0,1fr)', gap: 18, padding: '13px 0', borderTop: ROW_TOP }}>
                    <span style={{ fontFamily: MONO, fontSize: 11, letterSpacing: '0.1em', textTransform: 'uppercase', color: '#1B6C42' }}>{m.name}</span>
                    <span style={DEF}>{m.def}</span>
                  </div>
                ))}
              </div>
            </section>

            <section id="ingestion" style={SECTION}>
              <h2 style={H2}>Ingestion</h2>
              <p style={LEDE}>
                What happens to a file after you drop it in. Each step is visible in the product, so
                you can always see why a concept or a date exists.
              </p>
              <div style={{ marginTop: 18, display: 'flex', flexDirection: 'column', gap: 12 }}>
                {WIKI_PIPELINE.map((p) => (
                  <div key={p.num} style={{ display: 'flex', gap: 14, alignItems: 'flex-start' }}>
                    <span style={{ fontFamily: MONO, fontSize: 10, letterSpacing: '0.16em', color: '#2D8F5C', paddingTop: 4, flex: '0 0 auto' }}>{p.num}</span>
                    <span style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                      <span style={{ fontSize: 14.5, fontWeight: 600, color: '#1a1814' }}>{p.title}</span>
                      <span style={{ ...DEF, maxWidth: '60ch' }}>{p.body}</span>
                    </span>
                  </div>
                ))}
              </div>
            </section>

            <section id="grades" style={SECTION}>
              <h2 style={H2}>Grade scale</h2>
              <p style={LEDE}>
                Category weights come from your syllabus, and every score rolls into one weighted
                number. These are the letter bands it maps onto.
              </p>
              <div style={{ marginTop: 18, display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {WIKI_LETTERS.map((l) => (
                  <span key={l.letter} style={{ display: 'flex', alignItems: 'baseline', gap: 7, padding: '7px 12px', borderRadius: 8, background: '#faf8f3', border: '1px solid rgba(42,39,31,0.10)' }}>
                    <b style={{ fontSize: 13, fontWeight: 600, color: '#1a1814' }}>{l.letter}</b>
                    <span style={{ fontFamily: MONO, fontSize: 11, color: '#6f6857' }}>{l.min}</span>
                  </span>
                ))}
              </div>
            </section>

            <section id="privacy" style={SECTION}>
              <h2 style={H2}>Your data</h2>
              <div style={{ marginTop: 14, display: 'flex', flexDirection: 'column', gap: 10 }}>
                {WIKI_DATA_FACTS.map((d) => (
                  <div key={d} style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#2D8F5C" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0, marginTop: 3 }}>
                      <path d="M20 6L9 17l-5-5" />
                    </svg>
                    <span style={{ ...DEF, maxWidth: '62ch' }}>{d}</span>
                  </div>
                ))}
              </div>
            </section>
          </div>
        </div>
      </div>
    </CompanionShell>
  );
}
