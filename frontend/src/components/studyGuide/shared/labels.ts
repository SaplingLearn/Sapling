/**
 * The words both study-guide screens use for a guide's choices and counts,
 * so the home and the reader never say the same thing two ways.
 */
import type { Depth, Goal } from "@/lib/studyGuide/types";

export const GOAL_LABEL: Record<Goal, string> = {
  practice: "Practice",
  review: "Review",
  exam_prep: "Exam prep",
};

export const DEPTH_LABEL: Record<Depth, string> = {
  cram: "Cram sheet",
  standard: "Standard",
  deep: "Deep review",
};

/**
 * The one label a card has room for beside what the guide is for: its depth
 * when that is not the usual one, otherwise its goal.
 */
export const focusLabel = (goal: Goal, depth: Depth): string =>
  depth === "standard" ? GOAL_LABEL[goal] : DEPTH_LABEL[depth];

/** "1 section", "2 sections". */
export const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** "2 new lectures", or nothing when the class has added none since. */
export const newLecturesText = (count: number): string => (count > 0 ? plural(count, "new lecture") : "");
