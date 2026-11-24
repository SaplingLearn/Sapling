/** Pieces LoopLearn and its panels share (moved out of LoopLearn.tsx). */
import type React from "react";
import type { LoopHintResponse, StudentConfidence } from "@/lib/api";

export const BAND_LABEL: Record<string, string> = { novice: "Getting started", develop: "Developing", profic: "Proficient" };

export const FIELD_STYLE: React.CSSProperties = {
  width: "100%",
  padding: "10px 12px",
  fontSize: 14,
  lineHeight: 1.45,
  border: "1px solid var(--border)",
  borderRadius: "var(--r-md)",
  background: "var(--bg-input)",
  resize: "vertical",
  boxSizing: "border-box",
};

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
