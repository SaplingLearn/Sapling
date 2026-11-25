"use client";
/**
 * One motion language for the W7 answer kits (Sort, Sequence, Rank, Label,
 * Build, Position, Connect, Highlight, Compare, Dialogue, Explain, Calculate),
 * built from lib/motion's presets so every kit moves the same way:
 *
 *   - `piece(id, tone, movable)`: a card that travels between the tray and a
 *     slot glides there. Each piece carries a layoutId scoped to this kit's
 *     mount, so framer animates its remount from the box it just left, and
 *     the pieces it leaves behind close the gap the same way. Once the answer
 *     is marked (`movable` false) nothing glides: the tray's exit must not
 *     drag the placed cards with it.
 *   - `mark(tone)`: once marked, a right piece pulses and a wrong one shakes
 *     (`pulse("correct" | "wrong")`). Only on the CHANGE: a kit that mounts
 *     with its verdict already set (a revisited question) stays still.
 *   - `arrive(isNew, step)`: something added after the kit is on screen (a
 *     chat reply, a concept link, a pairing) fades up; what was there on
 *     first paint does not move.
 *   - `list`: the stagger for a block of rows that appears together (the
 *     Explain rubric).
 *
 * `KitPiece` is the placeable card the tray kits share (Sort, Sequence, Rank,
 * Label, Build, Position): a `<button>` with `piece()` spread on it and its
 * tone written as the block's `--<tone>` modifier class.
 *
 * Selection, hover and press are CSS ("W7 kits: one motion language" in
 * question.css), on the motion tokens. Reduced motion: the presets turn
 * instant or opacity-only, and the CSS is collapsed by the global reset.
 *
 * Nothing here changes where a piece rests: the layout animation tweens from
 * the old box to the new box the layout already gives it, and the pulse ends
 * on identity.
 */
import { useId, type ReactNode } from "react";
import {
  motion,
  type HTMLMotionProps,
  type Target,
  type TargetAndTransition,
  type Transition,
  type Variants,
} from "framer-motion";
import { MOTION } from "@/lib/designTokens";
import { useMotionPresets, type Verdict } from "@/lib/motion";

export type KitTone = "plain" | "lift" | "right" | "wrong";
export type KitVerdict = "correct" | "incorrect" | null | undefined;

const PULSE_OF: Record<KitTone, Verdict | null> = {
  plain: null,
  lift: null,
  right: "correct",
  wrong: "wrong",
};

/** The tone a whole-field kit (Explain, Calculate, Dialogue) takes from its verdict. */
export function toneOfVerdict(verdict: KitVerdict): KitTone {
  if (verdict === "correct") return "right";
  if (verdict === "incorrect") return "wrong";
  return "plain";
}

/** What a kit spreads onto a `motion.*` element. */
export interface KitMotionProps {
  initial: false | Target;
  animate?: TargetAndTransition;
  transition?: Transition;
  layout?: "position";
  layoutId?: string;
}

export interface KitMotion {
  piece: (id: string, tone: KitTone, movable: boolean) => KitMotionProps;
  mark: (tone: KitTone) => KitMotionProps;
  arrive: (isNew: boolean, step?: number) => KitMotionProps;
  list: { container: Variants; item: Variants };
}

export function useKitMotion(): KitMotion {
  const m = useMotionPresets();
  // Scopes the layoutIds to this mount: the next question's "a" card must
  // never fly in from where the last question's "a" card sat.
  const scope = useId();

  const mark = (tone: KitTone): KitMotionProps => {
    const verdict = PULSE_OF[tone];
    if (!verdict) return { initial: false };
    const pulse = m.pulse(verdict);
    return { initial: false, animate: pulse.animate, transition: pulse.transition };
  };

  return {
    mark,
    piece: (id, tone, movable) => {
      const marked = mark(tone);
      if (!movable) return marked;
      return {
        ...marked,
        layout: "position",
        layoutId: `${scope}${id}`,
        transition: { ...marked.transition, layout: m.transition.spring.snappy },
      };
    },
    arrive: (isNew, step = 0) =>
      isNew
        ? {
            // lib/motion types a preset's `initial` as TargetAndTransition,
            // which framer's `initial` prop (a Target: no keyframes, no
            // transition) does not accept; fadeUp's is a plain Target.
            initial: m.fadeUp.initial as Target,
            animate: m.fadeUp.animate,
            transition: { ...m.fadeUp.transition, delay: step * MOTION.stagger.base },
          }
        : { initial: false },
    list: m.list,
  };
}

export interface KitPieceProps
  extends Omit<HTMLMotionProps<"button">, "type" | "className" | "children"> {
  kit: KitMotion;
  /** The piece's id inside its kit (the layoutId's tail). */
  pieceId: string;
  /** The card's BEM block, e.g. `quiz-sort__card`; the tone is its modifier. */
  block: string;
  tone: KitTone;
  /** False once the answer is marked: the piece stops gliding. */
  movable: boolean;
  children: ReactNode;
}

export function KitPiece({ kit, pieceId, block, tone, movable, children, ...rest }: KitPieceProps) {
  return (
    <motion.button
      {...kit.piece(pieceId, tone, movable)}
      {...rest}
      type="button"
      className={`${block} ${block}--${tone}`}
    >
      {children}
    </motion.button>
  );
}
