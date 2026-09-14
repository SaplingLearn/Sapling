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
 * The page box comes from CompanionShell, so text and artwork both span the
 * one content width every companion page uses. That is why the type comes
 * from `companionType.ts` rather than inline literals: the body has to be
 * sized against that width or the line runs past 100 characters. The scale
 * there puts it near 89.
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
      <div>
        <Link href="/news" className="cp-navlink" style={ARTICLE.eyebrow}>
          ← The Journal
        </Link>

        <div style={{ marginTop: 26, display: 'flex', alignItems: 'center', gap: 14, lineHeight: 1 }}>
          <span style={{ ...ARTICLE.eyebrow, letterSpacing: '0.16em', color: ACCENT }}>{article.tag}</span>
          <span style={{ ...ARTICLE.eyebrow, letterSpacing: '0.06em' }}>{dateLabel(article.publishedAt)}</span>
          <span style={ARTICLE.eyebrow}>{readTime(article.body)} READ</span>
        </div>

        <h1 style={{ ...ARTICLE.title, margin: '20px 0 0' }}>
          {article.title}
        </h1>

        <p style={{ ...ARTICLE.deck, margin: '24px 0 0' }}>
          {article.deck}
        </p>

        {/* Full content width, flush with the body text. The 16/10 box is the
            one the cards use, so motifs crop identically on every surface. */}
        <div style={{ position: 'relative', width: '100%', marginTop: 38, aspectRatio: '16 / 10', borderRadius: 16, overflow: 'hidden', background: '#ebe6dc', border: '1px solid rgba(42,39,31,0.10)' }}>
          <ArticleArt art={article.art} sizes="(max-width: 940px) 100vw, 880px" priority variant="hero" />
        </div>

        <div style={{ ...ARTICLE.eyebrow, margin: '32px 0 0', paddingBottom: 32, borderBottom: '1px solid rgba(42,39,31,0.12)', letterSpacing: '0.12em' }}>
          By the Sapling team
        </div>

        <article>
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
    </CompanionShell>
  );
}
