'use client';

import * as React from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { DISPLAY, INK, MONO, SERIF } from '@/lib/landing/companionType';
import type { WikiEntry, WikiGroup } from '@/lib/landing/wiki';
import { WikiSearchBox, matchEntries, snippet } from './WikiSearch';

/**
 * The wiki's front page: a search box over a card per topic, grouped.
 *
 * The cards are the whole point of splitting the wiki up. On the single page
 * a topic was a heading somewhere down an eighteen-section scroll; here every
 * topic is visible at once, with the one sentence that says what it covers,
 * and each is one click from its own page.
 *
 * While searching, the groups collapse to the cards that matched and each
 * card says where the hit was, so the answer is on screen before you click.
 */

export function WikiIndex({ entries, groups, legacy, children }: {
  /** The server-rendered masthead the search box sits under. */
  children: React.ReactNode;
  entries: readonly WikiEntry[];
  groups: readonly WikiGroup[];
  /** Old /wiki#<section> id → page slug. */
  legacy: Record<string, string>;
}) {
  const router = useRouter();
  const [query, setQuery] = React.useState('');
  const q = query.trim().toLowerCase();

  /* The single-page wiki addressed topics by hash, and those links are out
     in the world — the FAQ, old messages, bookmarks. The hash never reaches
     the server, so the forward has to happen here. `replace`, so Back does
     not bounce the reader through the index again. */
  React.useEffect(() => {
    const slug = legacy[window.location.hash.slice(1)];
    if (slug) router.replace(`/wiki/${slug}`);
  }, [legacy, router]);

  const hits = matchEntries(entries, q);
  const shown = groups
    .map((group) => ({ group, items: hits.filter((e) => e.group === group) }))
    .filter((g) => g.items.length > 0);

  return (
    <>
      <header style={{ paddingBottom: 42, borderBottom: '1px solid rgba(42,39,31,0.12)' }}>
        {children}
        <WikiSearchBox value={query} onChange={setQuery} style={{ margin: '26px 0 0', animation: 'fadeUp 700ms ease 220ms both' }} />
      </header>

      <div style={{ marginTop: 56, display: 'flex', flexDirection: 'column', gap: 52 }}>
        {shown.length === 0 && (
          <p style={{ margin: 0, fontFamily: SERIF, fontSize: 18, color: '#6f6857' }}>
            Nothing in the wiki matches “{query.trim()}”.
          </p>
        )}

        {shown.map(({ group, items }) => (
          <section key={group} aria-labelledby={`wiki-group-${group.toLowerCase()}`}>
            <h2
              id={`wiki-group-${group.toLowerCase()}`}
              style={{ margin: 0, fontFamily: DISPLAY, fontWeight: 500, fontSize: 28, lineHeight: 1.2, letterSpacing: '-0.015em', color: INK }}
            >
              {group}
            </h2>
            <div className="wiki-cards" style={{ marginTop: 18, display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 14 }}>
              {items.map((e) => {
                const hit = snippet(e, q);
                return (
                  <Link key={e.slug} href={`/wiki/${e.slug}`} className="wiki-card">
                    <span style={{ fontFamily: DISPLAY, fontWeight: 500, fontSize: 20, lineHeight: 1.25, color: INK }}>
                      {e.title}
                    </span>
                    <span style={{ fontFamily: SERIF, fontSize: 16, lineHeight: 1.5, color: '#3f3b31' }}>
                      {e.summary}
                    </span>
                    {hit && (
                      <span style={{ fontFamily: MONO, fontSize: 12.5, lineHeight: 1.55, color: '#6f6857' }}>
                        {hit}
                      </span>
                    )}
                    <span aria-hidden="true" className="wiki-card-arrow" style={{ marginTop: 'auto', fontFamily: MONO, fontSize: 12.5, letterSpacing: '0.08em', color: 'var(--brand-forest)' }}>
                      READ →
                    </span>
                  </Link>
                );
              })}
            </div>
          </section>
        ))}
      </div>
    </>
  );
}
