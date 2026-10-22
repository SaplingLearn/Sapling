import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { CompanionShell } from '@/components/companion/CompanionShell';
import { DISPLAY, INK, MONO } from '@/lib/landing/companionType';
import {
  WIKI_GROUPS, WIKI_PAGES, getWikiPage, wikiEntries, wikiNeighbours, type WikiPage,
} from '@/lib/landing/wiki';
import { PROSE, WikiBlockView, WikiShot } from '../WikiBlocks';
import { WikiRail } from '../WikiRail';

/**
 * One wiki topic.
 *
 * The rail-plus-article grid the single-page wiki had, with one topic in the
 * article column instead of eighteen. Keeping the grid keeps the column at
 * the width the type in WikiBlocks.tsx was measured against (#604).
 *
 * Every slug is statically generated and anything else is a real 404 (the
 * /careers/[slug] rule, #187).
 */

export function generateStaticParams() {
  return WIKI_PAGES.map((p) => ({ slug: p.slug }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const page = getWikiPage(slug);
  if (!page) return { title: 'Page not found' };
  return {
    title: `${page.title} — Wiki`,
    description: page.summary,
    alternates: { canonical: `/wiki/${page.slug}` },
  };
}

/** Block to block, the gap the single page held at its 22px body. */
const BLOCK_GAP = 26;

function Pager({ dir, page }: { dir: 'prev' | 'next'; page?: WikiPage }) {
  if (!page) return <span />;
  return (
    <Link
      href={`/wiki/${page.slug}`}
      rel={dir}
      className="wiki-card"
      style={{ textAlign: dir === 'next' ? 'right' : 'left', alignItems: dir === 'next' ? 'flex-end' : 'flex-start' }}
    >
      <span style={{ fontFamily: MONO, fontSize: 12.5, letterSpacing: '0.08em', color: '#6f6857' }}>
        {dir === 'prev' ? '← PREVIOUS' : 'NEXT →'}
      </span>
      <span style={{ fontFamily: DISPLAY, fontWeight: 500, fontSize: 19, lineHeight: 1.25, color: INK }}>
        {page.title}
      </span>
    </Link>
  );
}

export default async function WikiTopicPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const page = getWikiPage(slug);
  if (!page) notFound();
  const { prev, next } = wikiNeighbours(page.slug);

  return (
    <CompanionShell current="/wiki">
      <div className="wiki-grid" style={{ display: 'grid', gridTemplateColumns: 'minmax(0,190px) minmax(0,1fr)', gap: 'clamp(24px,4vw,56px)', alignItems: 'start' }}>
        <WikiRail entries={wikiEntries()} groups={WIKI_GROUPS} current={page.slug} />

        <article style={{ minWidth: 0 }}>
          <nav aria-label="Breadcrumb" style={{ fontFamily: MONO, fontSize: 12.5, letterSpacing: '0.1em', textTransform: 'uppercase', color: '#6f6857' }}>
            <Link href="/wiki" className="cp-navlink" style={{ color: '#6f6857' }}>Wiki</Link>
            <span aria-hidden="true" style={{ margin: '0 8px' }}>/</span>
            <span>{page.group}</span>
          </nav>
          <h1 style={{ margin: '14px 0 0', fontFamily: DISPLAY, fontWeight: 500, fontSize: 'clamp(34px, 4.4vw, 46px)', lineHeight: 1.12, letterSpacing: '-0.02em', color: INK }}>
            {page.title}
          </h1>
          {page.lede && <p style={{ ...PROSE, margin: '20px 0 0' }}>{page.lede}</p>}
          <WikiShot slug={page.slug} />

          <div style={{ marginTop: BLOCK_GAP + 8, display: 'flex', flexDirection: 'column', gap: BLOCK_GAP }}>
            {page.blocks.map((b, i) => <WikiBlockView key={i} block={b} />)}
          </div>

          <div className="wiki-pager" style={{ marginTop: 64, paddingTop: 28, borderTop: '1px solid rgba(42,39,31,0.12)', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
            <Pager dir="prev" page={prev} />
            <Pager dir="next" page={next} />
          </div>
        </article>
      </div>
    </CompanionShell>
  );
}
