/**
 * The design tokens code needs as NUMBERS, mirrored from app/globals.css.
 *
 * CSS is the source of truth: in a style or a stylesheet, write the token
 * (`var(--dur)`, `var(--z-modal)`), never these values. This file exists for
 * the sinks where `var()` does not resolve: framer-motion transitions (which
 * take seconds and cubic-bezier arrays), canvas and WebGL drawing, timers
 * that must end with a CSS transition, and z-index math.
 *
 * designTokens.test.ts parses globals.css and fails when a value here and its
 * CSS token drift apart, or when one side gains a token the other lacks.
 * Stagger and spring constants live ONLY here: CSS has no use for them.
 *
 * lib/motion.ts builds the app's framer-motion presets from MOTION; reach
 * for those before composing a transition by hand. Docs:
 * docs/frontend-design-tokens.md.
 */

/** A cubic-bezier as framer-motion takes it (and as CSS writes it). */
export type Bezier = readonly [number, number, number, number];

/** A framer-motion spring. */
export interface SpringTokens {
  readonly type: "spring";
  readonly stiffness: number;
  readonly damping: number;
  readonly mass: number;
}

export const MOTION = {
  /** Seconds, matching the `--dur*` tokens (which are in ms). */
  duration: {
    /** --dur-instant: press feedback. */
    instant: 0.06,
    /** --dur-fast: hovers, small state changes. */
    fast: 0.14,
    /** --dur: the default. */
    base: 0.22,
    /** --dur-slow: a panel or a block of content arriving. */
    slow: 0.42,
    /** --dur-slower: a large surface arriving. */
    slower: 0.6,
  },
  /** Matching the `--ease*` tokens. */
  ease: {
    /** --ease: the app's default curve. */
    standard: [0.2, 0.7, 0.2, 1] as Bezier,
    /** --ease-out: entrances, anything settling into place. */
    out: [0.22, 1, 0.36, 1] as Bezier,
    /** --ease-in: exits. */
    in: [0.4, 0, 1, 1] as Bezier,
    /** --ease-in-out: moving between two resting places. */
    inOut: [0.4, 0, 0.2, 1] as Bezier,
    /** --ease-emphasized: an entrance meant to be noticed. */
    emphasized: [0.2, 0.85, 0.35, 1] as Bezier,
  },
  /** Seconds between siblings of a staggered list (framer `staggerChildren`). */
  stagger: {
    /** Dense lists: options, rows, chips. */
    tight: 0.04,
    /** Cards and sections; the step of globals.css's `.anim-d*` delays. */
    base: 0.08,
  },
  /**
   * How far things travel, TS-only like stagger: px for translations, a factor
   * for scale. Small on purpose: motion here confirms a change, it does not
   * perform one.
   */
  offset: {
    /** A shake's amplitude; an exit's drift. */
    nudge: 4,
    /** How far an entrance rises into place. */
    rise: 8,
    /** The scale an entrance grows from. */
    scaleFrom: 0.96,
    /** The peak of a feedback pulse. */
    pulse: 1.04,
    /** The dip of the reduced-motion feedback pulse (an opacity). */
    blink: 0.7,
  },
  /** framer-motion springs, for what moves with momentum rather than on a clock. */
  spring: {
    /** Settles without overshoot: layout shifts, a panel sliding in. */
    gentle: { type: "spring", stiffness: 260, damping: 32, mass: 1 } as SpringTokens,
    /** Quick and firm: toggles, a selected marker moving between options. */
    snappy: { type: "spring", stiffness: 420, damping: 34, mass: 1 } as SpringTokens,
    /** A visible bounce: a verdict mark, a badge landing. */
    bouncy: { type: "spring", stiffness: 520, damping: 18, mass: 1 } as SpringTokens,
  },
} as const;

/** Matching the `--z-*` tokens, for code that computes a layer. */
export const Z = {
  base: 0,
  raised: 1,
  sticky: 20,
  popover: 100,
  overlay: 150,
  modal: 200,
  toast: 1000,
} as const;

export type ZLayer = keyof typeof Z;

/** `cubic-bezier(a, b, c, d)` for a Bezier, for a CSS string built in code. */
export function cssBezier(points: Bezier): string {
  return `cubic-bezier(${points.join(", ")})`;
}
