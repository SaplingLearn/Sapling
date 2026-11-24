/**
 * W8.7: Dashboard Learn-next from the shared learner-next buckets (W8.6 /
 * GET /api/study/{id}/next). Same due → misconception → ready order as Study
 * Hub Focus and the quiz plan (before its per-course cap). Pure — no fetch.
 */
import { planReasonCopy } from "@/lib/quiz/proposals";
import type { PlannedConcept } from "@/lib/quiz/types";
import type { StudyNext } from "@/lib/studyApi";

/** One Learn-next row (graph /recommendations or a learner-next concept). */
export type LearnerNextRecommendation = {
  concept_name: string;
  reason?: string;
  node_id?: string | null;
  course_id?: string | null;
};

/** Flatten uncapped buckets into up to `limit` Learn-next rows. */
export function recommendationsFromNext(
  next: StudyNext,
  limit = 3,
): LearnerNextRecommendation[] {
  const ordered: PlannedConcept[] = [
    ...next.due,
    ...next.misconceptions,
    ...next.ready,
  ];
  return ordered.slice(0, limit).map((c) => ({
    concept_name: c.concept_name,
    reason: planReasonCopy(c.reason),
    node_id: c.node_id,
    course_id: c.course_id,
  }));
}
