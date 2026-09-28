'use client';

import * as React from 'react';
import { WIKI_TOC } from '@/lib/landing/companionContent';
import { DISPLAY, INK } from '@/lib/landing/companionType';
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

/**
 * The rail's two tiers, sized so the parent outranks its children.
 *
 * The group labels used to be 10px tracked-out mono uppercase in the muted
 * grey — the masthead's eyebrow treatment, borrowed. An eyebrow is a kicker
 * above a title, though, and these are titles: "Learn" governs the six links
 * under it. Set as an eyebrow it came out SMALLER and lighter than the links
 * it governs, which is the hierarchy upside down, and five of them down a
 * narrow column read as five captions rather than five groups.
 *
 * So the label takes the page's own heading voice — Playfair in ink, at the
 * size the article column's h2 would be if you shrank it to rail scale — and
 * the links stay DM Sans in the muted grey. The rail then mirrors the page
 * beside it: display face for a heading, quieter face for its contents. Size
 * and colour both run the same direction, so the tier is legible at a glance
 * without a rule or an indent to prop it up.
 *
 * Both tiers are sized in `vh` between a floor and the size they had, so
 * eighteen links and five group labels fit the viewport instead of scrolling
 * inside the rail. The rail was a flat 781px, which fits a 900px-tall window
 * and nothing shorter — it scrolled on 1366x768 and 1280x720, two of the
 * commonest laptop screens there are, and the scroll was inside a sticky box
 * most people never think to scroll. The heading voice above survives the
 * shrink: the label stays Playfair in ink, it just stops being 18px on a
 * screen that cannot afford 18px.
 *
 * `lineHeight` is pinned rather than left at `normal`: the leading is most of
 * a row's height at these sizes, and an unpinned one varies by font and
 * platform, so the fit would have been measured on one machine and wrong on
 * the next.
 */
const GROUP: React.CSSProperties = {
  fontFamily: DISPLAY, fontWeight: 500,
  fontSize: 'clamp(14px, 2vh, 18px)', lineHeight: 1.25,
  letterSpacing: '-0.01em', color: INK,
  marginBottom: 'clamp(2px, 0.85vh, 8px)',
};
const LINK: React.CSSProperties = {
  fontSize: 'clamp(10.5px, 1.5vh, 13.5px)',
  padding: 'clamp(1px, 0.4vh, 4px) 0',
  lineHeight: 1.25,
  transition: 'color 120ms ease',
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
    /* Sized to fit rather than bounded and scrolled. `overflowY: auto`
       survives only as a last resort for a window too short for even the
       clamp floors (under ~460px tall); at every ordinary size the content
       is smaller than the box and the scrollbar never appears.
       `.wiki-rail` carries the narrow-width collapse — see globals.css. */
    <nav
      aria-label="Contents"
      className="wiki-rail"
      style={{
        position: 'sticky', top: 84, maxHeight: 'calc(100vh - 100px)',
        overflowY: 'auto', display: 'flex', flexDirection: 'column',
        gap: 'clamp(5px, 1.9vh, 18px)',
        /* Both columns start at the same grid row top, but they set Playfair
           at different sizes, so their first lines sit at different baselines
           — the rail's label floated 14px above the section heading beside
           it. Half the leading difference between 18/1.25 here and the h2's
           32/1.2, so the page opens on one line across both columns. */
        paddingTop: 14,
      }}
    >
      {groups.length === 0 && (
        <span style={{ fontSize: 13, color: '#8d866f', lineHeight: 1.5 }}>
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
          style={{ display: 'flex', flexDirection: 'column', gap: 2 }}
        >
          <span id={`rail-${section.group.toLowerCase()}`} style={GROUP}>
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
    </nav>
  );
}
