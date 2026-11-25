/**
 * W8.6/W8.7: the Dashboard's reads of the shared learner-next buckets
 * (GET /api/study/{id}/next) — Learn-next and the Today plan's quiz item. Same
 * due → misconception → ready order as Study Hub Focus and the quiz plan
 * (before its per-course cap). Pure — no fetch.
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

/** The buckets flattened in proposal order: due → misconceptions → ready. */
export function orderedNext(next: StudyNext): PlannedConcept[] {
  return [...next.due, ...next.misconceptions, ...next.ready];
}

/** The first proposed concept `inScope` accepts (e.g. on the Dashboard's
 *  semester-scoped map), or null when none is — the learner model proposing
 *  nothing in scope is an answer, not a cue to rank the graph instead. */
export function firstNextIn(
  next: StudyNext,
  inScope: (nodeId: string) => boolean,
): PlannedConcept | null {
  return orderedNext(next).find((c) => inScope(c.node_id)) ?? null;
}

/** Flatten uncapped buckets into up to `limit` Learn-next rows. */
export function recommendationsFromNext(
  next: StudyNext,
  limit = 3,
): LearnerNextRecommendation[] {
  return orderedNext(next).slice(0, limit).map((c) => ({
    concept_name: c.concept_name,
    reason: planReasonCopy(c.reason),
    node_id: c.node_id,
    course_id: c.course_id,
  }));
}
