/**
 * One skill ladder (Tutor redesign phase 2; the frontend audit's "How well do
 * I know this?"). The learner model's belief is the one measure, and it has
 * four words:
 *
 *   Not started      no graded answer yet (no measured belief)
 *   Getting started  below 30%
 *   Developing       30% to 79%
 *   Proficient       80% and up
 *
 * "Mastered" is a badge, shown only when the backend's rule says so (belief
 * ≥ 98% and three strong unassisted answers, `learning/bkt.py::is_mastered`);
 * a percentage alone never earns it. The band names stay internal.
 *
 * The Tree, Study and the Dashboard still colour by the knowledge map's stored
 * (undecayed) mastery score and its four tiers (`lib/graph/nodeStyle.ts`);
 * moving them onto this ladder needs the backend to serve the decayed belief
 * on graph nodes, a follow-up.
 */
import { MASTERY_PALETTE } from "@/lib/graph/nodeStyle";

/** The learner model's skill bands (`backend/learning/bkt.py::band`). */
export type SkillBand = "novice" | "develop" | "profic";
export type SkillLevel = "not_started" | SkillBand;

/** `backend/learning/params.py` BAND_NOVICE_MAX / BAND_DEVELOP_MAX. */
export const BAND_NOVICE_MAX = 0.3;
export const BAND_DEVELOP_MAX = 0.8;

export const LEVEL_WORDS: Record<SkillLevel, string> = {
  not_started: "Not started",
  novice: "Getting started",
  develop: "Developing",
  profic: "Proficient",
};

/** The badge's word; never a level of its own. */
export const MASTERED_BADGE = "Mastered";

/** The band a belief falls in, as the backend computes it. */
export function bandFor(p: number): SkillBand {
  if (p < BAND_NOVICE_MAX) return "novice";
  if (p < BAND_DEVELOP_MAX) return "develop";
  return "profic";
}

/** A measured belief's level; no belief (or a non-number) is Not started. */
export function levelFor(p: number | null | undefined): SkillLevel {
  return p == null || !Number.isFinite(p) ? "not_started" : bandFor(p);
}

/** A level as it reads mid-sentence: "still developing", "now proficient". */
export function levelPhrase(level: SkillLevel): string {
  return LEVEL_WORDS[level].toLowerCase();
}

/** Each level's colour, from the app's mastery palette, low to high. */
export const LEVEL_TONE: Record<SkillLevel, string> = {
  not_started: MASTERY_PALETTE.unexplored,
  novice: MASTERY_PALETTE.struggling,
  develop: MASTERY_PALETTE.learning,
  profic: MASTERY_PALETTE.mastered,
};
