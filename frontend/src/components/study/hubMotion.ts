/**
 * The clock of an exam-tab switch. Everything that changes with the tab (the
 * tab's underline, the readiness figure and what is around it, the Up Next
 * block, the roadmap) starts on the same frame and runs on this one duration
 * and this one curve, so the page changes once rather than in pieces.
 *
 * Inside it, content is swapped in two parts so an old thing and the new
 * thing in its place are never both readable: what goes fades out first
 * (HUB_OUT), what comes fades in after (HUB_IN). What stays and moves runs
 * the whole length underneath (HUB_WHOLE), so the motion never stops.
 */

/** How long a switch takes, start to rest. */
export const HUB_SWITCH_MS = 320;
/** What arrives new on the roadmap starts this much into the second part, and still ends with the rest. */
export const HUB_STAGGER_MS = 40;
/** The fraction of the switch by which everything old is gone. */
export const HUB_OUT_UNTIL = 0.42;
/** The fraction of the switch at which the new starts to show. Never before HUB_OUT_UNTIL. */
export const HUB_IN_FROM = 0.44;
/** The app's `--ease` (globals.css; hubMotion.test.ts pins the two together). */
export const HUB_EASE_POINTS = [0.2, 0.7, 0.2, 1] as const;
export const HUB_EASE = `cubic-bezier(${HUB_EASE_POINTS.join(", ")})`;

const IN_FROM_MS = Math.round(HUB_SWITCH_MS * HUB_IN_FROM);

/** When one piece of a switch runs: Web Animations `delay` and `duration`, in ms. */
export interface HubPhase { delay: number; duration: number }
/** What stays and moves: slides, the tab's line, heights (and the figure's count). */
export const HUB_WHOLE: HubPhase = { delay: 0, duration: HUB_SWITCH_MS };
/** What goes, and the old copy of a crossfade. */
export const HUB_OUT: HubPhase = { delay: 0, duration: Math.round(HUB_SWITCH_MS * HUB_OUT_UNTIL) };
/** The new copy of a crossfade. Ends with the switch. */
export const HUB_IN: HubPhase = { delay: IN_FROM_MS, duration: HUB_SWITCH_MS - IN_FROM_MS };
/** What arrives new on the roadmap: a beat into the second part, ending with the switch too. */
export const HUB_IN_LATE: HubPhase = { delay: IN_FROM_MS + HUB_STAGGER_MS, duration: HUB_SWITCH_MS - IN_FROM_MS - HUB_STAGGER_MS };

/** True when the student asked for less motion: every change then lands at once. */
export const reducedMotion = () =>
  typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/**
 * A CSS cubic-bezier as a function of time, 0..1 to 0..1. The curve is given
 * by x(u) and y(u); the progress at time t is y at the u where x(u) = t,
 * found by bisection (x only ever grows for control points within 0..1).
 */
export function cubicBezier(x1: number, y1: number, x2: number, y2: number): (t: number) => number {
  const at = (u: number, p1: number, p2: number) => 3 * (1 - u) * (1 - u) * u * p1 + 3 * (1 - u) * u * u * p2 + u * u * u;
  return t => {
    if (t <= 0) return 0;
    if (t >= 1) return 1;
    let lo = 0;
    let hi = 1;
    for (let i = 0; i < 24; i++) {
      const mid = (lo + hi) / 2;
      if (at(mid, x1, x2) < t) lo = mid; else hi = mid;
    }
    return at((lo + hi) / 2, y1, y2);
  };
}

export const hubEase = cubicBezier(...HUB_EASE_POINTS);

/**
 * The whole number a count shows `elapsed` ms into going from `from` to `to`:
 * `from` at the start, exactly `to` from HUB_SWITCH_MS on, eased in between.
 */
export function countAt(from: number, to: number, elapsed: number): number {
  if (elapsed >= HUB_SWITCH_MS) return to;
  return Math.round(from + (to - from) * hubEase(Math.max(0, elapsed) / HUB_SWITCH_MS));
}
