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
 * The graph: with the learning loop on for the student, `GET /api/graph`
 * gives each concept its `skill` (the decayed belief once it has a graded
 * answer, else null) and `skill_mastered` (the badge). `applySkill` (run by
 * `getGraph`) then makes that skill each node's score and tier, so the Tree,
 * Study, the Dashboard, the Quiz home and the Tutor colour, sort and count by
 * one measure; `tierWord` names a tier in the ladder's words. With the loop
 * off the graph has no skill, and everything reads the map's stored
 * (undecayed) score and its four tiers (`lib/graph/nodeStyle.ts`) as before.
 */
import { MASTERY_PALETTE, TIER_LABEL, type MasteryTier } from "@/lib/graph/nodeStyle";

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

/** The map tier each level is coloured as (low to high), so every surface's
 *  tier-keyed palette, legend and count serves the ladder unchanged. */
export const LEVEL_TIER: Record<SkillLevel, MasteryTier> = {
  not_started: "unexplored",
  novice: "struggling",
  develop: "learning",
  profic: "mastered",
};
const TIER_LEVEL: Record<MasteryTier, SkillLevel> = {
  unexplored: "not_started",
  struggling: "novice",
  learning: "develop",
  mastered: "profic",
};

/** A node from a graph that carries the learner model's skill (the loop is
 *  on): the key is there, null included. */
export function carriesSkill(node: object): boolean {
  return Object.prototype.hasOwnProperty.call(node, "skill");
}

/** Whether a graph is on the ladder (any concept carries a skill). */
export function graphUsesSkill(nodes: readonly object[]): boolean {
  return nodes.some(carriesSkill);
}

/** A tier's word: the ladder's on a skill graph ("Proficient" for the top
 *  tier, never "Mastered"), else the map's own. */
export function tierWord(tier: MasteryTier, skill: boolean): string {
  return skill ? LEVEL_WORDS[TIER_LEVEL[tier]] : TIER_LABEL[tier];
}

/** A node's state mid-sentence ("developing", "not started"): the ladder's
 *  on a skill graph, else the map tier's own lowercase name. */
export function nodeStateWord(node: { mastery_tier: string }): string {
  const tier = node.mastery_tier as MasteryTier;
  return carriesSkill(node) && tier in TIER_LEVEL ? levelPhrase(TIER_LEVEL[tier]) : node.mastery_tier;
}

type SkillNode = {
  id?: string;
  mastery_score: number;
  mastery_tier: string;
  skill?: number | null;
  course_id?: string | null;
  is_subject_root?: boolean;
  map_mastery_score?: number;
  map_mastery_tier?: string;
};
type TierCounts = { mastered?: number; learning?: number; struggling?: number; unexplored?: number };

/**
 * `getGraph`'s normaliser: on a skill graph each concept's `mastery_score`
 * and `mastery_tier` become its skill's (a concept not started is 0 and
 * unexplored), the map's own stay as `map_mastery_score` / `map_mastery_tier`;
 * a course hub's score is its concepts' mean again, and `stats` counts the
 * new tiers (and says `skill: true`). A graph with no skill is returned as it came.
 */
export function applySkill<G extends { nodes: SkillNode[]; stats?: TierCounts & Record<string, unknown> }>(graph: G): G {
  if (!graph?.nodes || !graphUsesSkill(graph.nodes)) return graph;
  const concepts = graph.nodes.filter((n) => !n.is_subject_root);
  for (const n of concepts) {
    if (!carriesSkill(n)) continue;
    n.map_mastery_score = n.mastery_score;
    n.map_mastery_tier = n.mastery_tier;
    n.mastery_score = n.skill ?? 0;
    n.mastery_tier = LEVEL_TIER[levelFor(n.skill)];
  }
  for (const root of graph.nodes.filter((n) => n.is_subject_root)) {
    const own = concepts.filter((n) => n.course_id && n.course_id === root.course_id);
    if (own.length > 0) root.mastery_score = own.reduce((sum, n) => sum + n.mastery_score, 0) / own.length;
  }
  if (graph.stats) {
    const counts: Required<TierCounts> = { mastered: 0, learning: 0, struggling: 0, unexplored: 0 };
    for (const n of concepts) if (n.mastery_tier in counts) counts[n.mastery_tier as keyof TierCounts] += 1;
    Object.assign(graph.stats, counts, { skill: true });
  }
  return graph;
}
