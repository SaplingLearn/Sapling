'use client';

import * as React from 'react';
import { WIKI_TOC } from '@/lib/landing/companionContent';
import { DISPLAY, INK } from '@/lib/landing/companionType';

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
 */
const GROUP: React.CSSProperties = {
  fontFamily: DISPLAY, fontWeight: 500, fontSize: 18, lineHeight: 1.25,
  letterSpacing: '-0.01em', color: INK, marginBottom: 8,
};
const LINK: React.CSSProperties = { fontSize: 14, lineHeight: 1.4, padding: '4px 0', transition: 'color 120ms ease' };

export function WikiRail() {
  const [active, setActive] = React.useState('');

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

  return (
    /* Eighteen entries plus their group labels outgrow a short viewport, and
       a sticky element taller than the screen puts its last items out of
       reach. Bounded and scrollable so every section stays clickable. */
    <nav
      aria-label="Contents"
      style={{
        position: 'sticky', top: 84, maxHeight: 'calc(100vh - 104px)', overflowY: 'auto',
        display: 'flex', flexDirection: 'column', gap: 26,
        /* Both columns start at the same grid row top, but they set Playfair
           at different sizes, so their first lines sit at different baselines
           — the rail's label floated 14px above the section heading beside
           it. Half the leading difference between 18/1.25 here and the h2's
           32/1.2, so the page opens on one line across both columns. */
        paddingTop: 14,
      }}
    >
      {WIKI_TOC.map((section) => (
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
