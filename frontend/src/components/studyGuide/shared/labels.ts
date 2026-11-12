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

/** "1 section", "2 sections". */
export const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** "2 new lectures", or nothing when the class has added none since. */
export const newLecturesText = (count: number): string => (count > 0 ? plural(count, "new lecture") : "");
