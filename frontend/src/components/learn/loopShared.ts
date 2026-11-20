/** Pieces LoopLearn and its panels share (moved out of LoopLearn.tsx). */
import type React from "react";
import type { StudentConfidence } from "@/lib/api";

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
export type Draft = { answer: string; option: string; reason: string; confidence: StudentConfidence | null };
export type HintView = { denied: string } | { reply: string } | null;

/** Focus the first answer control of a check-in or check card: the textarea, or
 *  the options' tab stop (each is marked `data-answer-start`). */
export const focusAnswerStart = (card: HTMLElement | null) => card?.querySelector<HTMLElement>("[data-answer-start]")?.focus();
