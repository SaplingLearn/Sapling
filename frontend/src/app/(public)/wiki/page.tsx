import type { Metadata } from 'next';
import { CompanionShell } from '@/components/companion/CompanionShell';
import { WIKI_GROUPS, WIKI_PAGES, wikiEntries } from '@/lib/landing/wiki';
import { ARTICLE, MONO } from '@/lib/landing/companionType';
import { PROSE } from './WikiBlocks';
import { WikiIndex } from './WikiIndex';

/**
 * Wiki index.
 *
 * The wiki used to be this one page: eighteen definition sections down a
 * single scroll. Each topic now has its own page at /wiki/<slug>
 * ([slug]/page.tsx), and this is the front door — the masthead, a search
 * over every page's text, and a card per topic grouped the way the product
 * is. Topics live in lib/landing/wiki.ts.
 */

export const metadata: Metadata = {
  title: 'Wiki',
  description:
    'Exact definitions for the terms and numbers Sapling puts on screen. Every value here is the one the product actually uses.',
  alternates: { canonical: '/wiki' },
};

export default function WikiPage() {
  const legacy = Object.fromEntries(
    WIKI_PAGES.flatMap((p) => (p.legacyId ? [[p.legacyId, p.slug]] : [])),
  );

  return (
    <CompanionShell current="/wiki">
      {/* The masthead is server-rendered and passed through; the search box
          and the cards share state, so they live in the one client
          component that wraps it. This page stays a server component and
          keeps exporting `metadata`. One stack — eyebrow, the word, the
          sentence under it — because a two-column masthead left the title's
          cell ~85% empty (#603). */}
      <WikiIndex entries={wikiEntries()} groups={WIKI_GROUPS} legacy={legacy}>
        <div style={{ animation: 'fadeUp 700ms ease both' }}>
          <span style={{ display: 'block', fontFamily: MONO, fontSize: 12.5, letterSpacing: '0.1em', textTransform: 'uppercase', color: '#6f6857' }}>
            Reference
          </span>
          <h1 style={{ ...ARTICLE.title, margin: '16px 0 0' }}>
            Wiki
          </h1>
        </div>
        <p style={{ ...PROSE, margin: '20px 0 0', animation: 'fadeUp 700ms ease 140ms both' }}>
          Exact definitions for the terms and numbers Sapling puts on screen, one topic to a page.
        </p>
      </WikiIndex>
    </CompanionShell>
  );
}
