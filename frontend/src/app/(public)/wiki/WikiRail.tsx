'use client';

import * as React from 'react';
import { WIKI_TOC } from '@/lib/landing/companionContent';
import { useWikiSearch } from './WikiSearch';
import { cn } from "@/lib/cn";

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
    /* Sized to fit rather than bounded and scrolled. `overflowY: auto`
       survives only as a last resort for a window too short for even the
       clamp floors (under ~460px tall); at every ordinary size the content
       is smaller than the box and the scrollbar never appears.
       `.wiki-rail` carries the narrow-width collapse — see globals.css. */
    <nav
      aria-label="Contents"
      className="wiki-rail sticky top-21 max-h-[calc(100vh_-_100px)] overflow-y-auto flex flex-col gap-[clamp(5px,_1.9vh,_18px)] pt-3.5"
    >
      {groups.length === 0 && (
        <span className="text-md text-[#8d866f] leading-[1.5]">
          Nothing matches “{query.trim()}”.
        </span>
      )}

      {groups.map((section) => (
        /* `aria-labelledby` rather than a real <h2>: the groups are headings
           of the rail, but the article column already owns h2 for its
           eighteen sections, and five more would double every entry in the
           document outline. This gives a screen reader the same grouping the
           type now gives the eye, without competing with the page. */
        <div
          key={section.group}
          role="group"
          aria-labelledby={`rail-${section.group.toLowerCase()}`}
          className="flex flex-col gap-0.5"
        >
          <span id={`rail-${section.group.toLowerCase()}`} className="font-display font-medium text-[length:clamp(14px,_2vh,_18px)] leading-[1.25] tracking-[-0.01em] text-ink-800 mb-[clamp(2px,_0.85vh,_8px)]">
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
                className={cn(on ? undefined : 'cp-navlink', "text-[length:clamp(10.5px,_1.5vh,_13.5px)] py-[clamp(1px,_0.4vh,_4px)] px-0 leading-[1.25] [transition:color_120ms_ease]", on ? "text-brand-forest" : "text-text-muted", on ? "font-semibold" : "font-normal")}
                aria-current={on ? 'true' : undefined}
              >
                {t.title}
              </a>
            );
          })}
        </div>
      ))}
    </nav>
  );
}
