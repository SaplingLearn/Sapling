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

/**
 * The page box: outer border-box, its side padding, and the content inside.
 *
 * 960 rather than the 1180 this started at, and up from a first pass at 860.
 * The three are not interchangeable, and the number that governs is not the
 * box — it is the measure. Spectral at 18px runs about 9.3px per character,
 * so 1116px of content is ~120 characters (which is why 1180 forced 26px type
 * on the reading pages) and even 896px is ~97.
 *
 * What makes 960 work where 1180 did not is that no page spends the full
 * width on running prose. Every reading page opens its rows with a key column
 * — /wiki's rail, the clause titles on /terms and /privacy, the section spine
 * on /about — so the text column lands near 650px and measures in the 70s
 * while the page, its rules and its footer all fill 896. The grids need no
 * help: each is `auto-fit`/`auto-fill` and simply takes another column.
 *
 * There is deliberately ONE of these. A brief two-tier version of this file
 * gave the prose pages their own narrower box, and the result was the drift
 * `CompanionShell` exists to prevent: the content edge jumped as you moved
 * between /about and /team.
 */
export const PAGE_MAX = 960;
export const PAGE_PAD = 32;
export const PAGE_CONTENT = PAGE_MAX - PAGE_PAD * 2;


/**
 * The essay ramp, measured against `PAGE_CONTENT` (796px).
 *
 * It used to be measured against `PAGE_CONTENT` (1116px), which forced a 26px
 * body to keep the line under 90 characters — correct for that box, but the
 * pages read as oversized. The box narrowed instead, so the type could come
 * down to something document-sized: 18px over 796px is ~88 characters, the
 * same measure at a size that no longer shouts.
 */
export const ARTICLE = {
  eyebrow: {
    fontFamily: MONO,
    fontSize: 11,
    letterSpacing: '0.14em',
    textTransform: 'uppercase',
    color: MUTED,
  },
  title: {
    fontFamily: DISPLAY,
    fontWeight: 500,
    fontSize: 'clamp(1.9rem,4vw,2.9rem)',
    lineHeight: 1.12,
    letterSpacing: '-0.02em',
    color: INK,
  },
  deck: {
    fontFamily: SERIF,
    fontStyle: 'italic',
    fontSize: 20,
    lineHeight: 1.5,
    color: '#57503f',
  },
  heading: {
    fontFamily: DISPLAY,
    fontWeight: 500,
    fontSize: 27,
    lineHeight: 1.22,
    letterSpacing: '-0.015em',
    color: INK,
  },
  body: {
    fontFamily: SERIF,
    fontSize: 18,
    lineHeight: 1.62,
    color: BODY,
  },
} as const satisfies Record<string, React.CSSProperties>;
