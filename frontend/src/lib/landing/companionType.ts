/**
 * Type for the companion pages (/news, /about, /wiki, /faq, /team, /gallery).
 *
 * These three stacks were declared verbatim in seven page files. They are the
 * paper-palette counterpart to the app shell's warm tokens — see
 * docs/frontend-rhythm-audit.md on why the two systems stay separate — and
 * having seven copies is how a system drifts without anyone editing it.
 *
 * It also owns the page box. `PAGE_MAX` is the outer border-box every
 * companion page renders into — CompanionShell applies it, pages no longer
 * size themselves — and `ARTICLE` is the /news/[slug] reading scale measured
 * against the `PAGE_CONTENT` inside it. The two travel together on purpose:
 * widen the page and the body type has to grow with it, or the line runs past
 * 100 characters. At 26px on 1116px the measure lands near where 16.5px on
 * 672px did.
 */

export const MONO = "'JetBrains Mono',monospace";
export const SERIF = "'Spectral',Georgia,serif";
export const DISPLAY = "'Playfair Display',Georgia,serif";

/** Ink on the paper palette. */
export const INK = '#1a1814';
export const BODY = '#3f3b31';
export const MUTED = '#6f6857';
export const ACCENT = '#2D8F5C';

/**
 * Cap for running prose inside the shared page box.
 *
 * The box is one width everywhere so the pages line up, but a paragraph is
 * not a grid: /about ran to 133 characters a line and /faq to 148 once they
 * inherited the wider box. `ch` rather than px so the cap tracks whatever
 * size the page sets.
 *
 * Two pages deliberately do not use it, because capping prose inside a box
 * that everything else fills is what gives a page more than one right edge.
 * They scale their type to the measure instead: /news/[slug] via `ARTICLE`
 * (85 characters across 1116px), and /wiki via its own two body sizes (#604 —
 * 22px across the 870px article column, 18px in the 678px cell right of a row
 * key, measured at 88 and 83). Prefer that where a page can carry it; the
 * cap is for prose that has to sit inside a box sized by something else.
 */
export const PROSE_MEASURE = '80ch';

/** The page box: outer border-box, its side padding, and the content inside. */
export const PAGE_MAX = 1180;
export const PAGE_PAD = 32;
export const PAGE_CONTENT = PAGE_MAX - PAGE_PAD * 2;

export const ARTICLE = {
  eyebrow: {
    fontFamily: MONO,
    fontSize: 13,
    letterSpacing: '0.14em',
    textTransform: 'uppercase',
    color: MUTED,
  },
  title: {
    fontFamily: DISPLAY,
    fontWeight: 500,
    fontSize: 'clamp(2.5rem,5vw,4.2rem)',
    lineHeight: 1.08,
    letterSpacing: '-0.02em',
    color: INK,
  },
  deck: {
    fontFamily: SERIF,
    fontStyle: 'italic',
    fontSize: 29,
    lineHeight: 1.45,
    color: '#57503f',
  },
  heading: {
    fontFamily: DISPLAY,
    fontWeight: 500,
    fontSize: 40,
    lineHeight: 1.18,
    letterSpacing: '-0.015em',
    color: INK,
  },
  body: {
    fontFamily: SERIF,
    fontSize: 26,
    lineHeight: 1.62,
    color: BODY,
  },
} as const satisfies Record<string, React.CSSProperties>;
