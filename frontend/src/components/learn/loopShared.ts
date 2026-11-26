/** Pieces LoopLearn and its panels share (moved out of LoopLearn.tsx). */
import type { LoopHintResponse, StudentConfidence } from "@/lib/api";
import fieldStyles from "./loopShared.module.css";

/** A learning goal's free text, as the goal editor caps it (POST /goal's `text`),
 *  and its target concepts' cap, re-exported beside it for the goal's checks. */
export const LOOP_GOAL_TEXT_MAX = 500;
export { LOOP_GOAL_MAX_TARGETS } from "@/lib/inputLimits";

/** The loop's written-answer field: a textarea carries it to read as a field
 *  (Tailwind's preflight strips a textarea's own border, padding and fill). */
export const FIELD_CLASS = fieldStyles.field;

/** An answer being written. `confidence` (spec §13 A127) is the student's stated
 *  confidence — null until chosen, and a skip sends none. */
/** `reason` is mc_reason's required one-sentence why; `reasoning` is the
 *  optional free/teachback "show your reasoning" field (W2.3; never graded). */
export type Draft = {
  answer: string;
  option: string;
  reason: string;
  reasoning: string;
  confidence: StudentConfidence | null;
};
export type HintView = { denied: string } | { reply: string } | null;

/** The denial a hint card words (#866 K32): POST /hint's reason, made precise by
 *  what the server said — a written attempt that time alone kept from counting
 *  (`wait_s` from /step/attempt) is "too_soon", never "write something"; an H6
 *  gate another genuine try lifts is "h6_attempt"; any other H6 gate never lifts. */
export function hintDenial(denied: string, lifts: LoopHintResponse["lifts"], attemptWaitS: number | undefined): string {
  if (denied === "no_genuine_attempt" && attemptWaitS !== undefined) return "too_soon";
  if (denied === "h6_gate" && lifts === "attempt") return "h6_attempt";
  return denied;
}

/** Focus the first answer control of a check-in or check card: the textarea, or
 *  the options' tab stop (each is marked `data-answer-start`). */
export const focusAnswerStart = (card: HTMLElement | null) => card?.querySelector<HTMLElement>("[data-answer-start]")?.focus();
