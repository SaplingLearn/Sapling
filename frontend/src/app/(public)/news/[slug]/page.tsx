import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { CompanionShell } from '@/components/companion/CompanionShell';
import { ArticleArt } from '@/components/journal/ArticleArt';
import { ARTICLE, ACCENT, SERIF } from '@/lib/landing/companionType';
import {
  JOURNAL_ARTICLES,
  dateLabel,
  getArticle,
  readTime,
  type ArticleBlock,
} from '@/lib/landing/journalArticles';

/**
 * A Sapling Journal article.
 *
 * Companion-shell page on the warm paper palette, matching /news. Content
 * comes from `journalArticles.ts`; the six slugs are statically generated
 * and anything else is a real 404 (same rule as /careers/[slug], #187).
 *
 * The artwork band sits under the deck rather than above the title: at the
 * 16/10 the cards use, a hero over the title puts the headline below the
 * fold on a laptop, and cropping the motifs to a shorter band cuts their
 * labels off (#601).
 *
 * Why the article has a meta rail
 * -------------------------------
 * `PAGE_MAX` went to 960, so every companion page now renders into 896px of
 * content. The other reading pages absorb that in a key column — /wiki's
 * contents rail, the clause titles on /terms and /privacy — but an article is
 * one column of prose and had nothing to absorb it with. Spectral at 18px runs
 * about 9.3px a character, so 896px is ~97 characters a line, and the type
 * cannot come up to meet the box the way `ARTICLE` did at 1116: the point of
 * the widening was wider pages at the same reading size.
 *
 * So the extra width goes to a rail instead of to the line. The rail carries
 * what is *about* the piece — the way back to the index, the tag, the date,
 * the read time, the byline — and the column carries the piece itself: title,
 * deck, artwork, prose, the closing card. Everything the reader consults on
 * the left, everything they read on the right. Two things fall out of that:
 * the stacked eyebrow row above the headline is gone, and so is the
 * bottom-ruled byline band that used to separate the artwork from the body —
 * a bare hairline marks where the article starts now.
 *
 * `RAIL_COL` is /wiki's 180, not a third number, because this is /wiki's
 * shape: a short left column beside a long scroll, on the same
 * `clamp(24px,3vw,44px)` gutter. /terms' 220 is the other house width and is
 * sized off repeating clause titles, which is not what this column holds. What
 * 180 leaves is 672.6px of prose, measured in a browser at 1440px off real
 * line boxes (partial last lines excluded): 71-75 characters at the longest
 * line, median 66-68, across all seven posts.
 */

export function generateStaticParams() {
  return JOURNAL_ARTICLES.map((a) => ({ slug: a.slug }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const article = getArticle(slug);
  if (!article) return { title: 'Article not found' };
  return {
    title: `${article.title} — The Sapling Journal`,
    description: article.deck,
    alternates: { canonical: `/news/${article.slug}` },
  };
}

const RULE = '1px solid rgba(42,39,31,0.12)';
/** The meta column, and the gutter after it. Both are /wiki's. */
const RAIL_COL = 180;
const RAIL_GAP = 'clamp(24px,3vw,44px)';

/**
 * The rail beside the article.
 *
 * A wrapping flex rather than /wiki's grid, because this one has to fold:
 * `grid-template-columns: 180px 1fr` never wraps, it squeezes, and at a 390px
 * viewport that leaves the article 122px wide. Inline styles cannot carry a
 * media query and this page has no stylesheet of its own, so the collapse has
 * to come out of the primitive. The article cell's 520px basis is the trigger
 * — below ~724px of content the two bases and the gutter no longer fit on one
 * line, so the rail drops above the article and each cell has the width to
 * itself. Same mechanism, same reason, as the clause rows on /terms.
 *
 * The basis is what the fold is *worth*, not what the column ends up: the
 * 999 grow weight below means the article takes essentially all the slack, so
 * 520 and 440 both land at ~673px on a wide screen. What they differ on is the
 * narrowest the column is allowed to get before the rail gives way — 56
 * characters at 520, 47 at 440.
 */
const SPREAD: React.CSSProperties = {
  display: 'flex', flexWrap: 'wrap', alignItems: 'flex-start', gap: RAIL_GAP,
};
const RAIL: React.CSSProperties = {
  flex: `1 1 ${RAIL_COL}px`, maxWidth: '100%', minWidth: 0,
  display: 'flex', flexDirection: 'column', gap: 22,
};
/**
 * Both cells grow, the article a thousand times harder — so side by side the
 * rail holds its 180 to within a quarter-pixel, and once the row wraps the
 * stacked rail still stretches to the article's right edge rather than
 * stopping short of it.
 */
const COLUMN: React.CSSProperties = { flex: '999 1 520px', minWidth: 0 };

function Block({ block }: { block: ArticleBlock }) {
  if (block.t === 'h2') {
    return (
      <h2 style={{ ...ARTICLE.heading, margin: '48px 0 0' }}>
        {block.text}
      </h2>
    );
  }
  if (block.t === 'ul') {
    return (
      <ul style={{ margin: '26px 0 0', paddingLeft: 26, display: 'flex', flexDirection: 'column', gap: 14 }}>
        {block.items.map((item) => (
          <li key={item} style={ARTICLE.body}>
            {item}
          </li>
        ))}
      </ul>
    );
  }
  return (
    <p style={{ ...ARTICLE.body, margin: '26px 0 0' }}>
      {block.text}
    </p>
  );
}

export default async function ArticlePage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const article = getArticle(slug);
  if (!article) notFound();

  return (
    <CompanionShell current="/news">
      <div style={SPREAD}>
        <aside style={RAIL}>
          <Link href="/news" className="cp-navlink" style={ARTICLE.eyebrow}>
            ← The Journal
          </Link>

          {/* These three were a horizontal row above the headline, where they
              read as a caption on the title. Stacked they read as what they
              are: the card the piece is filed under. */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
            <span style={{ ...ARTICLE.eyebrow, letterSpacing: '0.16em', color: ACCENT }}>{article.tag}</span>
            <span style={{ ...ARTICLE.eyebrow, letterSpacing: '0.06em' }}>{dateLabel(article.publishedAt)}</span>
            <span style={ARTICLE.eyebrow}>{readTime(article.body)} READ</span>
          </div>

          <div style={{ ...ARTICLE.eyebrow, letterSpacing: '0.12em' }}>
            By the Sapling team
          </div>
        </aside>

        <div style={COLUMN}>
          <h1 style={{ ...ARTICLE.title, margin: 0 }}>
            {article.title}
          </h1>

          <p style={{ ...ARTICLE.deck, margin: '24px 0 0' }}>
            {article.deck}
          </p>

          {/* The article column, flush with the body text under it. The 16/10
              box is the one the cards use, so motifs crop identically on every
              surface. `sizes` names the fold: below it the figure is the whole
              content width, above it the column's ~673. */}
          <div style={{ position: 'relative', width: '100%', marginTop: 38, aspectRatio: '16 / 10', borderRadius: 16, overflow: 'hidden', background: '#ebe6dc', border: '1px solid rgba(42,39,31,0.10)' }}>
            <ArticleArt art={article.art} sizes="(max-width: 744px) 100vw, 680px" priority variant="hero" />
          </div>

          <article style={{ marginTop: 36, borderTop: RULE }}>
            {article.body.map((block, i) => (
              <Block key={i} block={block} />
            ))}
          </article>

          <div style={{ marginTop: 64, borderRadius: 16, background: '#faf8f3', border: '1px solid rgba(42,39,31,0.10)', padding: '28px 30px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 20, flexWrap: 'wrap' }}>
            <p style={{ margin: 0, fontFamily: SERIF, fontSize: 17, lineHeight: 1.6, color: '#3f3b31', maxWidth: '46ch' }}>
              One letter a month, written by the four of us. Get the next one in your inbox.
            </p>
            <Link href="/#newsletter" className="cp-cta" style={{ background: '#1B6C42', color: '#fff', borderRadius: 8, padding: '12px 22px', fontSize: 14, fontWeight: 600, whiteSpace: 'nowrap' }}>
              Get the Journal
            </Link>
          </div>
        </div>
      </div>
    </CompanionShell>
  );
}
