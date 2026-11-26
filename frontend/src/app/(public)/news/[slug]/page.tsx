import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { CompanionShell } from '@/components/companion/CompanionShell';
import { ArticleArt } from '@/components/journal/ArticleArt';
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
      <h2 className="font-display font-medium text-[27px] leading-[1.22] tracking-[-0.015em] text-ink-800 mt-12 mx-0 mb-0">
        {block.text}
      </h2>
    );
  }
  if (block.t === 'ul') {
    return (
      <ul className="mt-6.5 mx-0 mb-0 pl-6.5 flex flex-col gap-3.5">
        {block.items.map((item) => (
          <li key={item} className="font-serif text-xl leading-[1.62] text-ink-600">
            {item}
          </li>
        ))}
      </ul>
    );
  }
  return (
    <p className="font-serif text-xl leading-[1.62] text-ink-600 mt-6.5 mx-0 mb-0">
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
        <Link href="/news" className="cp-navlink font-sans text-md text-text-muted">
          ← The Journal
        </Link>

        <div className="mt-6.5 flex items-center gap-3.5 leading-none">
          <span className="font-sans text-md tracking-[0.16em] text-brand-forest-bright">{article.tag}</span>
          <span className="font-sans text-md text-text-muted tracking-[0.06em]">{dateLabel(article.publishedAt)}</span>
          <span className="font-sans text-md text-text-muted">{readTime(article.body)} READ</span>
        </div>

        <h1 className="font-display font-medium text-[length:clamp(1.9rem,4vw,2.9rem)] leading-[1.12] tracking-[-0.02em] text-ink-800 mt-5 mx-0 mb-0">
          {article.title}
        </h1>

        <p className="font-serif italic text-[20px] leading-[1.5] text-[#57503f] mt-6 mx-0 mb-0">
          {article.deck}
        </p>

        {/* Full content width, flush with the body text. The 16/10 box is the
            one the cards use, so motifs crop identically on every surface. */}
        <div className="relative w-full mt-9.5 aspect-[16/10] rounded-lg overflow-hidden bg-ink-100 border border-[rgba(42,39,31,0.10)]">
          <ArticleArt art={article.art} sizes="(max-width: 940px) 100vw, 880px" priority variant="hero" />
        </div>

        <div className="font-sans text-md text-text-muted mt-8 mx-0 mb-0 pb-8 border-b border-b-[rgba(42,39,31,0.12)] tracking-[0.12em]">
          By the Sapling team
        </div>

        <article>
          {article.body.map((block, i) => (
            <Block key={i} block={block} />
          ))}
        </article>

        <div className="mt-16 rounded-lg bg-ink-0 border border-[rgba(42,39,31,0.10)] py-7 px-7.5 flex items-center justify-between gap-5 flex-wrap">
          <p className="m-0 font-serif text-[17px] leading-[1.6] text-ink-600 max-w-[46ch]">
            One letter a month, written by the four of us. Get the next one in your inbox.
          </p>
          <Link href="/#newsletter" className="cp-cta [background:var(--brand-forest)] text-accent-fg rounded-[8px] py-3 px-5.5 text-base font-semibold whitespace-nowrap">
            Get the Journal
          </Link>
        </div>
      </div>
    </CompanionShell>
  );
}
