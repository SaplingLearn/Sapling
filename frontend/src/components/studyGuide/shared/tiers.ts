/**
 * Mastery tier styling for study guides: the backend's four tiers mapped onto
 * the Study hub's status labels and colours, so a guide reads like the rest of
 * Study.
 */
import { SC, ST_LABEL, TC, type Status } from "@/components/study/studyModel";
import type { Tier } from "@/lib/studyGuide/types";

const STATUS: Record<Tier, Status> = {
  mastered: "mastered",
  learning: "progress",
  struggling: "review",
  unexplored: "new",
};

/** "Mastered", "Learning", "Struggling" or "Not Started". */
export const tierLabel = (tier: Tier): string => ST_LABEL[STATUS[tier]];
/** Fill colour for squares, bars and rings. */
export const tierFill = (tier: Tier): string => TC[STATUS[tier]];
/** Text colour for a tier's label. */
export const tierText = (tier: Tier): string => SC[STATUS[tier]];
