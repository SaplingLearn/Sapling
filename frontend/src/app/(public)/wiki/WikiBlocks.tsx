import { ZoomableShot } from '@/components/companion/ZoomableShot';
import { WIKI_SHOTS } from '@/lib/landing/companionContent';
import { MONO, SERIF } from '@/lib/landing/companionType';
import type { WikiBlock } from '@/lib/landing/wiki';

/**
 * The wiki's row shapes, rendered from a page's blocks.
 *
 * These are the shapes the single-page wiki drew inline, lifted out so every
 * /wiki/<slug> page draws them identically. `terms` (a name and a
 * definition), `specs` (a name, a value and the reason for the value),
 * `facts`, `steps` and `prose` carry almost everything; the rest exist
 * because their content genuinely needs a different grid.
 *
 * Two prose measures, and the type scaled to each (#604). A topic page keeps
 * the old page's rail-plus-column grid, so the column is the same 870px at
 * 1440 and the sizes measured there still hold:
 *
 *   PROSE (22px) — the full column: ledes, fact lists. Median 88 characters.
 *   DEF   (18px) — the 678px cell right of a row key. Median 83, up to 88.
 *
 * One size per role, and no role has two:
 *
 *   22px  PROSE   full-column prose
 *   18px  DEF     a row's definition cell, and any detail under a row value
 *   17px  VALUE   what a row states, including a letter grade
 *   16.5  the caption under a figure
 *   13.5  every mono label: keys, ranges, values, step numbers, minimums
 */

export const PROSE: React.CSSProperties = {
  fontFamily: SERIF, fontSize: 22, lineHeight: 1.55, color: '#3f3b31',
};
const DEF: React.CSSProperties = {
  fontFamily: SERIF, fontSize: 18, lineHeight: 1.6, color: '#3f3b31',
};
/** The hairline that separates rows. */
const ROW_TOP = '1px solid rgba(42,39,31,0.08)';
/**
 * The key column every row shape opens with, and the gap after it. Sized off
 * the longest key ("Generation timeout", 18 mono characters) at `KEY` size.
 */
const KEY_COL = 'minmax(0,172px)';
const ROW_GAP = 20;
const ROW: React.CSSProperties = {
  display: 'grid', gridTemplateColumns: `${KEY_COL} minmax(0,1fr)`, gap: ROW_GAP,
  padding: '15px 0', borderTop: ROW_TOP,
};
/** The green mono key that opens a row. */
const KEY: React.CSSProperties = { fontFamily: MONO, fontSize: 13.5, letterSpacing: '0.06em', color: 'var(--brand-forest)' };
/** The value a spec row states, above its reason. */
const VALUE: React.CSSProperties = { fontSize: 17, fontWeight: 600, color: '#1a1814' };
const STACK: React.CSSProperties = { display: 'flex', flexDirection: 'column' };
const TILE: React.CSSProperties = { background: '#faf8f3', border: '1px solid rgba(42,39,31,0.10)' };

/** `dot`/`tone` come from the source as CSS declaration strings. */
function cssColor(decl: string): string {
  return decl.replace(/^(background|color):/, '').replace(/;$/, '').trim();
}

function Check({ top }: { top: number }) {
  return (
    <svg aria-hidden="true" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#597536" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0, marginTop: top }}>
      <path d="M20 6L9 17l-5-5" />
    </svg>
  );
}

/**
 * The screen a page is about, when there is one. `ZoomableShot` is the panel
 * and the click-to-expand; the figure and caption stay here, so this inline
 * figure and /gallery's grid card can lay out differently while behaving
 * identically. Runs the full column (#604).
 */
export function WikiShot({ slug }: { slug: string }) {
  const shot = WIKI_SHOTS[slug];
  if (!shot) return null;
  return (
    <figure style={{ margin: '28px 0 0', display: 'flex', flexDirection: 'column', gap: 10 }}>
      {/* Captured at 1440x900 — the same 16:10 as the panel, so it fills
          without cropping. */}
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

export function WikiBlockView({ block }: { block: WikiBlock }) {
  switch (block.kind) {
    case 'prose':
      return <p style={{ ...PROSE, margin: 0 }}>{block.text}</p>;

    case 'terms':
      return (
        <div style={STACK}>
          {block.rows.map((r) => (
            <div key={r.term} style={ROW}>
              <span style={KEY}>{r.term}</span>
              <span style={DEF}>{r.def}</span>
            </div>
          ))}
        </div>
      );

    case 'specs':
      return (
        <div style={STACK}>
          {block.rows.map((r) => (
            <div key={r.label} style={ROW}>
              <span style={KEY}>{r.label}</span>
              <span style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
                <span style={VALUE}>{r.value}</span>
                <span style={DEF}>{r.note}</span>
              </span>
            </div>
          ))}
        </div>
      );

    /* Same two columns as a spec row — the step number is the key — so the
       step bodies read on the same measure as every other definition. */
    case 'steps':
      return (
        <div style={STACK}>
          {block.rows.map((p) => (
            <div key={p.num} style={ROW}>
              <span style={{ fontFamily: MONO, fontSize: 13.5, letterSpacing: '0.16em', color: 'var(--brand-forest-bright)', paddingTop: 2 }}>{p.num}</span>
              <span style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
                <span style={VALUE}>{p.title}</span>
                <span style={DEF}>{p.body}</span>
              </span>
            </div>
          ))}
        </div>
      );

    /* Runs the full column rather than a row cell, so it takes the wider of
       the two prose sizes. */
    case 'facts':
      return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {block.items.map((d) => (
            <div key={d} style={{ display: 'flex', gap: 14, alignItems: 'flex-start' }}>
              <Check top={5} />
              <span style={PROSE}>{d}</span>
            </div>
          ))}
        </div>
      );

    /* The only table that needs a swatch. */
    case 'tiers':
      return (
        <div style={STACK}>
          {block.rows.map((t) => (
            <div key={t.name} style={{ display: 'grid', gridTemplateColumns: '12px minmax(0,124px) minmax(0,116px) minmax(0,1fr)', gap: 16, alignItems: 'baseline', padding: '15px 0', borderTop: ROW_TOP }}>
              <span style={{ width: 10, height: 10, borderRadius: 99, background: cssColor(t.dot) }} />
              <span style={VALUE}>{t.name}</span>
              <span style={{ fontFamily: MONO, fontSize: 13.5, lineHeight: 1.5, color: '#6f6857', whiteSpace: 'nowrap' }}>{t.range}</span>
              <span style={DEF}>{t.meaning}</span>
            </div>
          ))}
        </div>
      );

    /* The formula reads as an equation, so it gets to look like one. */
    case 'formula':
      return (
        <div style={{ ...TILE, padding: '16px 18px', borderRadius: 10, fontFamily: MONO, fontSize: 15, lineHeight: 1.6, color: '#1a1814', overflowX: 'auto' }}>
          {block.text}
        </div>
      );

    case 'moves':
      return (
        <div style={STACK}>
          {block.rows.map((m) => (
            <div key={m.source} style={{ display: 'grid', gridTemplateColumns: `${KEY_COL} minmax(0,132px) minmax(0,1fr)`, gap: ROW_GAP, alignItems: 'baseline', padding: '15px 0', borderTop: ROW_TOP }}>
              <span style={VALUE}>{m.source}</span>
              <span style={{ fontFamily: MONO, fontSize: 13.5, color: 'var(--brand-forest)', whiteSpace: 'nowrap' }}>{m.value}</span>
              <span style={DEF}>{m.note}</span>
            </div>
          ))}
        </div>
      );

    case 'modes':
      return (
        <div style={STACK}>
          {block.rows.map((m) => (
            <div key={m.name} style={ROW}>
              <span style={{ ...KEY, letterSpacing: '0.1em', textTransform: 'uppercase' }}>{m.name}</span>
              <span style={DEF}>{m.def}</span>
            </div>
          ))}
        </div>
      );

    case 'ratings':
      return (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px,1fr))', gap: 12 }}>
          {block.rows.map((r) => (
            <div key={r.label} style={{ ...TILE, borderRadius: 12, padding: 18, display: 'flex', alignItems: 'center', gap: 9 }}>
              <span style={{ ...VALUE, color: cssColor(r.tone) }}>{r.label}</span>
              <span style={{ fontFamily: MONO, fontSize: 13.5, color: '#6f6857' }}>KEY {r.key}</span>
            </div>
          ))}
        </div>
      );

    case 'letters':
      return (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {block.rows.map((l) => (
            <span key={l.letter} style={{ ...TILE, display: 'flex', alignItems: 'baseline', gap: 8, padding: '8px 14px', borderRadius: 8 }}>
              <b style={VALUE}>{l.letter}</b>
              <span style={{ fontFamily: MONO, fontSize: 13.5, color: '#6f6857' }}>{l.min}</span>
            </span>
          ))}
        </div>
      );

    case 'dataFacts':
      return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {block.rows.map((d) => (
            <div key={d.fact} style={{ display: 'flex', gap: 14, alignItems: 'flex-start' }}>
              <Check top={6} />
              <span style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
                <span style={{ ...VALUE, lineHeight: 1.5 }}>{d.fact}</span>
                <span style={DEF}>{d.detail}</span>
              </span>
            </div>
          ))}
        </div>
      );
  }
}
