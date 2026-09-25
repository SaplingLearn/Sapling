'use client';

import * as React from 'react';
import { WIKI_TOC } from '@/lib/landing/companionContent';
import { MONO } from '@/lib/landing/companionType';
import { useWikiSearch } from './WikiSearch';

/**
 * The wiki's contents rail, with a scrollspy.
 *
 * Ported from Canopy's docs outline (`web/src/main.ts::updateActiveHeading`),
 * including the two details that make it feel right rather than merely work:
 * the active section is the LAST one whose top has crossed the line, not the
 * first one intersecting a band — so a short section scrolled past still
 * hands off cleanly; and at the very bottom of the page the last section is
 * forced current, because it can never reach the line on its own.
 *
 * Direct scroll listening rather than an IntersectionObserver per section:
 * the "last one above the line" rule needs all the positions at once, which
 * is one cheap read per frame, and rAF already bounds it to the paint rate.
 *
 * This is the only client component on the page — the page itself stays a
 * server component so it keeps exporting `metadata`.
 */

/**
 * How far down the viewport the line sits. The rail sticks at 84 and the
 * headings carry a matching `scroll-margin-top`, so a section clicked into
 * view lands just below this and reads as current the moment it arrives.
 */
const SPY_LINE = 100;

const LINK: React.CSSProperties = { fontSize: 13.5, padding: '4px 0', transition: 'color 120ms ease' };

/**
 * The group label — "Learn", "Capture", "Semester".
 *
 * Sized to read as a heading rather than as a caption. At 10px these sat
 * below the 13.5px links they head, so the rail read as one undifferentiated
 * column and the grouping did no work. The tracking comes down as the size
 * goes up: 0.14em is tuned for small caps, and left alone it turns a 12.5px
 * label into a line wide enough to wrap inside a 190px rail.
 */
const GROUP: React.CSSProperties = {
  fontFamily: MONO, fontSize: 12.5, letterSpacing: '0.1em', textTransform: 'uppercase',
  color: '#4a4436', fontWeight: 600, marginBottom: 8,
};

export function WikiRail() {
  const [active, setActive] = React.useState('');
  const { query, q, prose } = useWikiSearch();

  React.useEffect(() => {
    // TOC order is DOM order, which is what lets the loop below stop early.
    const ids = WIKI_TOC.flatMap((g) => g.items.map((i) => i.href.slice(1)));
    let scheduled = false;

    const update = () => {
      scheduled = false;
      const sections = ids
        .map((id) => document.getElementById(id))
        .filter((el): el is HTMLElement => el !== null);
      if (sections.length === 0) return;

      let current = sections[0].id;
      for (const el of sections) {
        if (el.getBoundingClientRect().top <= SPY_LINE) current = el.id;
        else break;
      }
      // The last section is usually shorter than the viewport, so it never
      // gets its top above the line. Bottom of the page means it's current.
      if (window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 4) {
        current = sections[sections.length - 1].id;
      }
      setActive(current);
    };

    const onScroll = () => {
      if (scheduled) return;
      scheduled = true;
      requestAnimationFrame(update);
    };

    update();
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll);
    return () => {
      window.removeEventListener('scroll', onScroll);
      window.removeEventListener('resize', onScroll);
    };
  }, []);

  /* A group survives only if something in it matched, so the rail collapses
     to the answer instead of leaving empty headings behind. Matching the
     group name too means "capture" finds the whole Capture set, which is how
     people search a contents list. */
  const groups = WIKI_TOC.map((section) => ({
    group: section.group,
    items: section.items.filter((t) =>
      !q
      || t.title.toLowerCase().includes(q)
      || section.group.toLowerCase().includes(q)
      || (prose[t.href.slice(1)] ?? '').includes(q)),
  })).filter((section) => section.items.length > 0);

  return (
    /* Eighteen entries plus their group labels outgrow a short viewport, and
       a sticky element taller than the screen puts its last items out of
       reach. Bounded and scrollable so every section stays clickable. */
    <aside style={{ position: 'sticky', top: 84, maxHeight: 'calc(100vh - 104px)', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 18 }}>
      {groups.length === 0 && (
        <span style={{ fontSize: 13, color: '#8d866f', lineHeight: 1.5 }}>
          Nothing matches “{query.trim()}”.
        </span>
      )}

      {groups.map((section) => (
        <div key={section.group} style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <span style={GROUP}>
            {section.group}
          </span>
          {section.items.map((t) => {
            const on = active === t.href.slice(1);
            return (
              <a
                key={t.href}
                href={t.href}
                /* The active link drops `cp-navlink` on purpose: that class
                   hovers to near-black, which would pull a current section
                   out of the accent colour under the cursor. */
                className={on ? undefined : 'cp-navlink'}
                aria-current={on ? 'true' : undefined}
                style={{ ...LINK, color: on ? '#1B6C42' : '#6f6857', fontWeight: on ? 600 : 400 }}
              >
                {t.title}
              </a>
            );
          })}
        </div>
      ))}
    </aside>
  );
}
