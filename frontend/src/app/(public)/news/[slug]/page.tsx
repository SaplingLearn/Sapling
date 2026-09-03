import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { CompanionShell } from '@/components/companion/CompanionShell';
import { JOURNAL_ARTICLES, getArticle, type ArticleBlock } from '@/lib/landing/journalArticles';

/**
 * A Sapling Journal article.
 *
 * Companion-shell page on the warm paper palette, matching /news. Content
 * comes from `journalArticles.ts`; the six slugs are statically generated
 * and anything else is a real 404 (same rule as /careers/[slug], #187).
 */

const MONO = "'JetBrains Mono',monospace";
const SERIF = "'Spectral',Georgia,serif";
const DISPLAY = "'Playfair Display',Georgia,serif";

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
      <h2 style={{ margin: '38px 0 0', fontFamily: DISPLAY, fontWeight: 500, fontSize: 26, lineHeight: 1.25, letterSpacing: '-0.015em', color: '#1a1814' }}>
        {block.text}
      </h2>
    );
  }
  if (block.t === 'ul') {
    return (
      <ul style={{ margin: '20px 0 0', paddingLeft: 22, display: 'flex', flexDirection: 'column', gap: 12 }}>
        {block.items.map((item) => (
          <li key={item} style={{ fontFamily: SERIF, fontSize: 16.5, lineHeight: 1.75, color: '#3f3b31' }}>
            {item}
          </li>
        ))}
      </ul>
    );
  }
  return (
    <p style={{ margin: '20px 0 0', fontFamily: SERIF, fontSize: 16.5, lineHeight: 1.78, color: '#3f3b31' }}>
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
      <main style={{ flex: 1, width: '100%', maxWidth: 720, margin: '0 auto', padding: '140px 24px 90px', boxSizing: 'border-box' }}>
        <Link href="/news" className="cp-navlink" style={{ fontFamily: MONO, fontSize: 10.5, letterSpacing: '0.14em', textTransform: 'uppercase', color: '#6f6857' }}>
          ← The Journal
        </Link>

        <div style={{ marginTop: 26, display: 'flex', alignItems: 'center', gap: 14, lineHeight: 1 }}>
          <span style={{ fontFamily: MONO, fontSize: 10.5, letterSpacing: '0.16em', textTransform: 'uppercase', color: '#2D8F5C' }}>{article.tag}</span>
          <span style={{ fontFamily: MONO, fontSize: 10.5, letterSpacing: '0.06em', color: '#6f6857' }}>{article.date}</span>
          <span style={{ fontFamily: MONO, fontSize: 10.5, letterSpacing: '0.14em', color: '#6f6857' }}>{article.time} READ</span>
        </div>

        <h1 style={{ margin: '18px 0 0', fontFamily: DISPLAY, fontWeight: 500, fontSize: 'clamp(2.1rem,4.6vw,3.1rem)', lineHeight: 1.12, letterSpacing: '-0.02em', color: '#1a1814' }}>
          {article.title}
        </h1>

        <p style={{ margin: '20px 0 0', fontFamily: SERIF, fontStyle: 'italic', fontSize: 18.5, lineHeight: 1.6, color: '#57503f' }}>
          {article.deck}
        </p>

        <div style={{ margin: '28px 0 0', paddingBottom: 28, borderBottom: '1px solid rgba(42,39,31,0.12)', fontFamily: MONO, fontSize: 10.5, letterSpacing: '0.12em', textTransform: 'uppercase', color: '#6f6857' }}>
          By the Sapling team
        </div>

        <article>
          {article.body.map((block, i) => (
            <Block key={i} block={block} />
          ))}
        </article>

        <div style={{ marginTop: 56, borderRadius: 16, background: '#faf8f3', border: '1px solid rgba(42,39,31,0.10)', padding: '24px 26px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 20, flexWrap: 'wrap' }}>
          <p style={{ margin: 0, fontFamily: SERIF, fontSize: 15, lineHeight: 1.6, color: '#3f3b31', maxWidth: '42ch' }}>
            One letter a month, written by the four of us. Get the next one in your inbox.
          </p>
          <Link href="/#newsletter" className="cp-cta" style={{ background: '#1B6C42', color: '#fff', borderRadius: 8, padding: '12px 22px', fontSize: 14, fontWeight: 600, whiteSpace: 'nowrap' }}>
            Get the Journal
          </Link>
        </div>
      </main>
    </CompanionShell>
  );
}
