'use client';

import * as React from 'react';
import Link from 'next/link';
import { DISPLAY, INK } from '@/lib/landing/companionType';
import type { WikiEntry, WikiGroup } from '@/lib/landing/wiki';
import { matchEntries } from './WikiSearch';

/**
 * The contents rail beside every wiki page.
 *
 * On the single page this was a scrollspy over sections in one document.
 * Each topic is its own route now, so "current" is simply the page you are
 * on and the rail is plain links — every other topic one click away without
 * going back to the index.
 *
 * The rail's two tiers keep the sizing the scrollspy version settled on: the
 * group label in the page's heading voice (display face, ink) and the links
 * in the quieter face and grey, both sized in `vh` between a floor and their
 * full size so the whole list fits a laptop window instead of scrolling
 * inside a sticky box most people never think to scroll. `lineHeight` is
 * pinned because the leading is most of a row's height at these sizes.
 *
 * Below 900px the rail does not stack above the article: two dozen links on
 * top of every page would push the page you asked for off the first screen.
 * It folds into a "Contents" disclosure instead (`.wiki-rail-mobile`, see
 * globals.css).
 */

const GROUP: React.CSSProperties = {
  fontFamily: DISPLAY, fontWeight: 500,
  fontSize: 'clamp(14px, 2vh, 18px)', lineHeight: 1.25,
  letterSpacing: '-0.01em', color: INK,
  marginBottom: 'clamp(2px, 0.6vh, 6px)',
};
const LINK: React.CSSProperties = {
  fontSize: 'clamp(11px, 1.45vh, 13.5px)',
  padding: 'clamp(1px, 0.3vh, 3px) 0',
  lineHeight: 1.25,
  transition: 'color 120ms ease',
};

function Contents({ entries, groups, current, idPrefix }: {
  entries: readonly WikiEntry[];
  groups: readonly WikiGroup[];
  current: string;
  idPrefix: string;
}) {
  const [query, setQuery] = React.useState('');
  const hits = matchEntries(entries, query.trim().toLowerCase());
  const shown = groups
    .map((group) => ({ group, items: hits.filter((e) => e.group === group) }))
    .filter((g) => g.items.length > 0);

  return (
    <>
      <input
        type="search"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Escape') setQuery(''); }}
        placeholder="Filter pages"
        aria-label="Filter wiki pages"
        className="wiki-search"
        style={{
          width: '100%', boxSizing: 'border-box', padding: '7px 10px',
          borderRadius: 8, border: '1px solid rgba(42,39,31,0.16)', background: '#fffdf7',
          fontFamily: 'inherit', fontSize: 13, color: '#2b2619', outline: 'none',
        }}
      />

      {shown.length === 0 && (
        <span style={{ fontSize: 13, color: '#8d866f', lineHeight: 1.5 }}>
          Nothing matches “{query.trim()}”.
        </span>
      )}

      {shown.map(({ group, items }) => {
        const labelId = `${idPrefix}-${group.toLowerCase()}`;
        return (
          /* `aria-labelledby` rather than a real heading: the article owns
             the page's heading outline, and five more would compete with it. */
          <div key={group} role="group" aria-labelledby={labelId} style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <span id={labelId} style={GROUP}>{group}</span>
            {items.map((e) => {
              const on = e.slug === current;
              return (
                <Link
                  key={e.slug}
                  href={`/wiki/${e.slug}`}
                  /* The current link drops `cp-navlink` on purpose: that
                     class hovers to near-black, which would pull it out of
                     the accent colour under the cursor. */
                  className={on ? undefined : 'cp-navlink'}
                  aria-current={on ? 'page' : undefined}
                  style={{ ...LINK, color: on ? 'var(--brand-forest)' : '#6f6857', fontWeight: on ? 600 : 400 }}
                >
                  {e.title}
                </Link>
              );
            })}
          </div>
        );
      })}
    </>
  );
}

export function WikiRail({ entries, groups, current }: {
  entries: readonly WikiEntry[];
  groups: readonly WikiGroup[];
  current: string;
}) {
  const here = entries.find((e) => e.slug === current);
  return (
    <>
      <nav
        aria-label="Wiki contents"
        className="wiki-rail"
        style={{
          position: 'sticky', top: 84, maxHeight: 'calc(100vh - 100px)',
          overflowY: 'auto', display: 'flex', flexDirection: 'column',
          gap: 'clamp(5px, 1.5vh, 16px)',
        }}
      >
        <Link href="/wiki" className="cp-navlink" style={{ ...LINK, color: '#6f6857' }}>
          ← All topics
        </Link>
        <Contents entries={entries} groups={groups} current={current} idPrefix="rail" />
      </nav>

      <details className="wiki-rail-mobile">
        <summary>
          <span>Contents</span>
          {here && <span style={{ color: '#6f6857', fontWeight: 400 }}>{here.group} · {here.title}</span>}
        </summary>
        <nav aria-label="Wiki contents" style={{ display: 'flex', flexDirection: 'column', gap: 14, paddingTop: 12 }}>
          <Link href="/wiki" className="cp-navlink" style={{ fontSize: 14, color: '#6f6857' }}>
            ← All topics
          </Link>
          <Contents entries={entries} groups={groups} current={current} idPrefix="rail-mobile" />
        </nav>
      </details>
    </>
  );
}
