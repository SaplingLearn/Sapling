"use client";
/**
 * The app's framer-motion presets, built from MOTION (lib/designTokens.ts).
 *
 * Use:
 *
 *   import { motion, AnimatePresence } from "framer-motion";
 *   import { useMotionPresets } from "@/lib/motion";
 *
 *   const m = useMotionPresets();            // already resolved for reduced motion
 *   <motion.div {...m.fadeUp} />              // an entrance (and exit, inside AnimatePresence)
 *   <motion.ul variants={m.list.container} initial="hidden" animate="shown">
 *     {rows.map(r => <motion.li key={r.id} variants={m.list.item} />)}
 *   </motion.ul>
 *   <motion.div {...m.collapse} />           // inside AnimatePresence: expand on mount, collapse on unmount
 *   <motion.span key={attempt} {...m.pulse(correct ? "correct" : "wrong")} />  // re-key to replay
 *
 * Outside React (or in a test) `motionPresets(reduced)` returns the same set.
 * `MotionProvider` sets the app-wide defaults (MOTION's base duration and
 * curve, and framer's own reduced-motion handling); mount it once around a
 * tree that uses framer-motion.
 *
 * Rules:
 *   - Animate between the states a component already has; never change its
 *     resting layout to make an animation easier. Every preset ends on
 *     identity (no transform, full opacity, natural height), so a component
 *     looks exactly as it did before the preset was added.
 *   - Reduced motion (the OS setting, read through framer's useReducedMotion)
 *     means no movement: entrances become a short opacity fade, a collapse
 *     snaps, a stagger shows its list at once, the verdict pulse is an
 *     opacity blink.
 *   - Durations and curves come from MOTION. A one-off number in a component
 *     is what the hardcode ratchet (scripts/hardcode-ratchet.mjs) is for.
 *
 * docs/frontend-design-tokens.md has the token families and the ratchet.
 */
import { createElement, type ReactNode } from "react";
import {
  MotionConfig,
  MotionGlobalConfig,
  useReducedMotion,
  type Target,
  type TargetAndTransition,
  type Transition,
  type Variants,
} from "framer-motion";
import { IS_TEST_MODE } from "./testMode";
import { MOTION } from "./designTokens";

// Deterministic DOM for browser tests (#383): framer-motion's test seam jumps
// every animation to its last keyframe. The flag is module-scoped, so every
// framer consumer must set it (see screens/Calendar.tsx); importing this
// module does it. No-op in production builds.
if (IS_TEST_MODE) MotionGlobalConfig.skipAnimations = true;

const { duration: D, ease: E, offset: O, stagger: S } = MOTION;

/** Spread onto a `motion.*` element: where it starts, where it rests, how it leaves. */
export interface MotionPreset {
  /** `Target`, not TargetAndTransition: framer's `initial` prop takes no
   *  transition, and the wider type stops `{...preset}` spreading onto a
   *  `motion.*` element (TS2322/TS2590). */
  initial: Target;
  animate: TargetAndTransition;
  exit: TargetAndTransition;
  transition: Transition;
}

/** Keyframes that play on mount; re-key the element to play them again. */
export interface MotionPulse {
  initial: false;
  animate: TargetAndTransition;
  transition: Transition;
}

export type Verdict = "correct" | "wrong";

export interface MotionPresets {
  /** Opacity in and out. */
  fade: MotionPreset;
  /** Opacity in while rising into place; out with a small drift up. */
  fadeUp: MotionPreset;
  /** Opacity in while growing from just under full size: popovers, dialogs, badges. */
  scaleIn: MotionPreset;
  /** Height from 0 to its natural height and back: an expand/collapse region. */
  collapse: MotionPreset;
  /** `variants` for a staggered list: `container` on the parent, `item` on each child. */
  list: { container: Variants; item: Variants };
  /** A one-shot confirmation of a right (a pulse) or wrong (a shake) answer. */
  pulse: (verdict: Verdict) => MotionPulse;
  /** Transitions for a hand-built animation: by speed, plus the springs. */
  transition: {
    fast: Transition;
    base: Transition;
    slow: Transition;
    exit: Transition;
    spring: Record<keyof typeof MOTION.spring, Transition>;
  };
}

const enter = (duration: number): Transition => ({ duration, ease: E.out });
const exitTransition: Transition = { duration: D.fast, ease: E.in };

function fullMotion(): MotionPresets {
  return {
    fade: {
      initial: { opacity: 0 },
      animate: { opacity: 1 },
      exit: { opacity: 0, transition: exitTransition },
      transition: enter(D.base),
    },
    fadeUp: {
      initial: { opacity: 0, y: O.rise },
      animate: { opacity: 1, y: 0 },
      exit: { opacity: 0, y: -O.nudge, transition: exitTransition },
      transition: enter(D.base),
    },
    scaleIn: {
      initial: { opacity: 0, scale: O.scaleFrom },
      animate: { opacity: 1, scale: 1 },
      exit: { opacity: 0, scale: O.scaleFrom, transition: exitTransition },
      transition: enter(D.base),
    },
    collapse: {
      initial: { height: 0, opacity: 0, overflow: "hidden" },
      animate: { height: "auto", opacity: 1, transitionEnd: { overflow: "visible" } },
      exit: { height: 0, opacity: 0, overflow: "hidden", transition: { duration: D.base, ease: E.inOut } },
      transition: { duration: D.base, ease: E.inOut },
    },
    list: {
      container: {
        hidden: {},
        shown: { transition: { staggerChildren: S.tight } },
      },
      item: {
        hidden: { opacity: 0, y: O.rise },
        shown: { opacity: 1, y: 0, transition: enter(D.base) },
      },
    },
    pulse: (verdict) =>
      verdict === "correct"
        ? { initial: false, animate: { scale: [1, O.pulse, 1] }, transition: { duration: D.slow, ease: E.out } }
        : {
            initial: false,
            animate: { x: [0, -O.nudge, O.nudge, -O.nudge / 2, O.nudge / 2, 0] },
            transition: { duration: D.slow, ease: E.inOut },
          },
    transition: {
      fast: enter(D.fast),
      base: enter(D.base),
      slow: enter(D.slow),
      exit: exitTransition,
      spring: MOTION.spring,
    },
  };
}

/** No movement: opacity only, or instant. */
function reducedMotion(): MotionPresets {
  const fadeOnly: MotionPreset = {
    initial: { opacity: 0 },
    animate: { opacity: 1 },
    exit: { opacity: 0, transition: { duration: D.fast } },
    transition: { duration: D.fast, ease: E.standard },
  };
  const instant: Transition = { duration: 0 };
  return {
    fade: fadeOnly,
    fadeUp: fadeOnly,
    scaleIn: fadeOnly,
    collapse: {
      initial: { height: 0, opacity: 0, overflow: "hidden" },
      animate: { height: "auto", opacity: 1, transitionEnd: { overflow: "visible" } },
      exit: { height: 0, opacity: 0, overflow: "hidden", transition: instant },
      transition: instant,
    },
    list: {
      container: { hidden: {}, shown: {} },
      item: {
        hidden: { opacity: 0 },
        shown: { opacity: 1, transition: { duration: D.fast } },
      },
    },
    pulse: () => ({ initial: false, animate: { opacity: [1, O.blink, 1] }, transition: { duration: D.base } }),
    transition: {
      fast: instant,
      base: instant,
      slow: instant,
      exit: instant,
      spring: { gentle: instant, snappy: instant, bouncy: instant },
    },
  };
}

const FULL = fullMotion();
const REDUCED = reducedMotion();

/** The presets for a known reduced-motion setting. */
export function motionPresets(reduced: boolean): MotionPresets {
  return reduced ? REDUCED : FULL;
}

/** The presets for the current user: reduced when the OS asks for less motion. */
export function useMotionPresets(): MotionPresets {
  return motionPresets(Boolean(useReducedMotion()));
}

/**
 * App-wide framer-motion defaults: MOTION's base duration and curve for any
 * `motion.*` element without its own transition, and `reducedMotion="user"`,
 * so framer itself drops transform and layout animation when the OS asks for
 * less motion (a backstop for hand-built animations; the presets already
 * handle it).
 */
export function MotionProvider({ children }: { children: ReactNode }) {
  return createElement(
    MotionConfig,
    { reducedMotion: "user", transition: { duration: D.base, ease: E.standard } },
    children,
  );
}
