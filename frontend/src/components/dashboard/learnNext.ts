/**
 * The Dashboard's "what to study next" read (W8.6/W8.7). With `learning_loop`
 * and `quiz_concept_plan` both on, ONE learner-next read
 * (`GET /api/study/{id}/next`) feeds both Learn-next and the Today plan's quiz
 * item, so neither ranks the graph on its own. Otherwise — the flags off, or
 * that read failing — the graph mastery-tier recommendations, exactly as
 * before, and `next` stays null so the Today plan keeps its tier pick (the
 * same fallback Study Hub Focus takes).
 */
import { getRecommendations } from "@/lib/api";
import { recommendationsFromNext } from "@/lib/learnerNext";
import { getStudyNext, type StudyNext } from "@/lib/studyApi";
import type { Recommendation } from "./LearnNextCard";

export type LearnNext = {
  recommendations: Recommendation[];
  /** The learner-next buckets; null with the flags off or the read failed. */
  next: StudyNext | null;
};

async function graphRecommendations(userId: string, activeSemester: string): Promise<Recommendation[]> {
  try {
    const r = await getRecommendations(userId, activeSemester || undefined);
    return r.recommendations || [];
  } catch {
    return [];
  }
}

export async function fetchLearnNext(
  userId: string,
  activeSemester: string,
  useLearnerNext: boolean,
): Promise<LearnNext> {
  if (useLearnerNext) {
    try {
      const next = await getStudyNext(userId);
      return { recommendations: recommendationsFromNext(next), next };
    } catch {
      // The server could not vouch for the plan (kill switch, 503): fall
      // through to the flag-off read rather than an empty card.
    }
  }
  return { recommendations: await graphRecommendations(userId, activeSemester), next: null };
}
