/**
 * Shared chrome for the in-page product recreations (#344 step 2).
 *
 * Every surface below the hero is a RECREATION of a page Sapling actually
 * ships — an upload queue, a quiz question, a review queue, a tutor exchange,
 * a note, a study room, a gradebook. None of them is an "icon + heading +
 * sentence" card, which the brand guide lists as a hard anti-pattern: a tile
 * has to show the product, not describe it.
 *
 * Two rules are enforced here rather than restated in seven files:
 *
 *  1. **Solid warm paper, hairline borders.** No `.liquid-glass`, no
 *     `backdrop-filter`, no frosted panel — the brand guide's other hard line.
 *     The recipe lives in `.landing-surface*` in globals.css, inside the
 *     `.landing-page` scope (the pre-auth page re-declares the app shell's
 *     token NAMES with different values — `docs/frontend-rhythm-audit.md`).
 *  2. **Colour is state.** The only colours these surfaces carry are
 *     `--state-*` (mastery) and `--grade-*` (letter grades), reached through
 *     `TIER_COLOR` — the same map the knowledge-graph section one viewport
 *     above paints its nodes with, so the page speaks one colour language.
 *     Everything else is a warm neutral off the `--ink` ramp.
 *
 * These are static pictures: no buttons, no inputs, no motion, nothing to
 * click. That is deliberate (the spec's "no per-tile buttons") and it is also
 * what makes `prefers-reduced-motion` / `IS_TEST_MODE` parking a non-issue —
 * there is no frame to park, only the complete one.
 */
import type { ReactNode } from 'react';

import { TIER_COLOR, type MasteryTier } from '../graph/courseGraphs';

/**
 * A mastery status mark. `aria-hidden` because the tier is always spelled out
 * in adjacent text or is decorative repetition of it — a bare "coloured dot"
 * announcement is noise in a screen reader.
 */
export function StateDot({ tier }: { tier: MasteryTier }) {
  return (
    <span aria-hidden className="landing-surface-dot" style={{ background: TIER_COLOR[tier] }} />
  );
}

/** A concept chip: mastery dot + label. Used by upload, notes and quiz. */
export function ConceptChip({ label, tier }: { label: string; tier: MasteryTier }) {
  return (
    <span className="landing-surface-chip">
      <StateDot tier={tier} />
      {label}
    </span>
  );
}

/** The hairline that separates a surface's sections. */
export function SurfaceRule() {
  return <span aria-hidden className="landing-surface-rule" />;
}

/**
 * The window frame every recreation sits in: a titled chrome bar over a body.
 *
 * `title` is the product surface's own name in Title Case (the approved
 * vocabulary — "Tutor", "Notetaker", "Study Rooms", "Gradebook",
 * "Adaptive Quizzes", "Document Library"), rendered as a mono micro-label.
 * `meta` is the small right-hand status the real screen carries in the same
 * spot (a count, a term, an invite code).
 */
export function SurfaceFrame({
  testId,
  title,
  meta,
  children,
}: {
  testId: string;
  title: string;
  meta?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="landing-surface" data-testid={testId}>
      <div className="landing-surface-chrome">
        <span className="landing-surface-title">{title}</span>
        {meta === undefined ? null : <span className="landing-surface-meta">{meta}</span>}
      </div>
      <div className="landing-surface-body">{children}</div>
    </div>
  );
}
