/**
 * What the quiz offers you when you arrive with nothing in mind.
 *
 * This is a deliberate client-side MIRROR of the backend's one ranking rule:
 *
 *   backend/services/graph_service.py:914-945 — get_recommendations()
 *     filters: mastery_tier in (struggling, learning, unexplored)
 *     order:   mastery_score.asc          (lowest mastery first)
 *     limit:   5
 *
 * The endpoint itself (`GET /api/graph/{user}/recommendations`) returns only
 * `{concept_name, reason}` — no node id, no course, no raw score, no
 * `last_studied_at` — which is not enough to render a card, join to an attempt,
 * or build a queue (R4 §2). The full node list is already loaded for the
 * "pick something specific" list, so the rule is reproduced over that instead of
 * fetching a second, thinner answer. The codebase has precedent for mirroring
 * with a citation (`Learn.tsx::tierForScore` mirrors `learning/bkt.py::tier_for`).
 *
 * TODO(#537-followup: enriched /recommendations) — once the endpoint returns
 * node_id / course_id / mastery_score / last_studied_at, delete this mirror and
 * join on the response instead.
 *
 * One presentation-layer tie-break sits on top (R-7): the primary slot prefers
 * the first candidate the student has actually studied. `unexplored` nodes score
 * 0.0, so a raw `mastery_score.asc` sort always puts never-opened concepts ahead
 * of the struggling ones — a "you're at 29% here, last studied 4 days ago" card
 * is a better opening move than "here is a concept you have never seen". The
 * ordering itself is untouched.
 */

import { levelPhrase } from "@/lib/levels";
import { paletteFor } from "@/lib/data";
import { resolveInitialSelection, type QuizConcept } from "@/lib/quizSelection";
import type { EnrolledCourse } from "@/lib/api";
import type { GraphNode } from "@/lib/types";
import { queueOf } from "./machine";
import { daysAgo, relativeStudied } from "./relativeTime";
import { QUEUE_MAX } from "./session";
import type { AttemptSummary, PlanReason, PlannedConcept, QuizPlan, QuizSession, SkillBand } from "./types";

/** The tiers `get_recommendations` considers worth suggesting. `mastered` and
 *  `subject_root` are excluded by the same filter. */
export const DUE_TIERS: readonly string[] = ["struggling", "learning", "unexplored"] as const;

/** The endpoint's own cap. Applied where parity with it matters; `dueSet` covers
 *  the whole graph on purpose (R-7). */
export const RECOMMENDATION_LIMIT = 5;

export interface Candidate {
  node: GraphNode;
  course: EnrolledCourse | null;
  color: string;
  rationale: string;
  lastAttempt?: AttemptSummary;
  /** Spec §13 A143: the learner model's proposal — why, the skill meter and its band. */
  plan?: CandidatePlan;
}

export interface CandidatePlan {
  reason: PlanReason;
  pKnown: number;
  band: SkillBand;
}

/** The membership half of the rule: is this node one the student owes time to? */
export function isDue(node: GraphNode): boolean {
  return !node.is_subject_root && DUE_TIERS.includes(node.mastery_tier);
}

function byMasteryAsc(a: GraphNode, b: GraphNode): number {
  if (a.mastery_score !== b.mastery_score) return a.mastery_score - b.mastery_score;
  // The backend's secondary order is unspecified; sort by id so a redraw with
  // identical scores never reshuffles the cards under the student's cursor.
  return a.id.localeCompare(b.id);
}

function courseFor(node: GraphNode, courses: EnrolledCourse[]): EnrolledCourse | null {
  if (!node.course_id) return null;
  return courses.find(c => c.course_id === node.course_id) ?? null;
}

/** Same resolution order as `lib/data.ts::apiToGraphNode`, so the quiz's accent
 *  matches the colour the graph already draws this node with. */
export function colorFor(node: GraphNode, course: EnrolledCourse | null): string {
  return node.course_color
    || node.color
    || course?.color
    || paletteFor(course?.course_id || node.course_id || node.subject);
}

/** The most recent COMPLETED attempt on a node — the only one that carries a
 *  score, and therefore the only one that can say "missed 3 last time". */
export function latestCompletedAttempt(
  nodeId: string,
  attempts: AttemptSummary[],
): AttemptSummary | undefined {
  let best: AttemptSummary | undefined;
  for (const a of attempts) {
    if (a.concept_node_id !== nodeId) continue;
    if (a.status !== "completed" || a.score === null || a.total === null) continue;
    const stamp = a.completed_at ?? a.created_at;
    const bestStamp = best ? best.completed_at ?? best.created_at : "";
    if (!best || stamp > bestStamp) best = a;
  }
  return best;
}

function pct(score: number): number {
  return Math.round(score * 100);
}

/** The skill bands in a student's words, mid-sentence: the one ladder's
 *  (`lib/levels.ts`), which the quiz results say the same way
 *  (`results/LearningBlock.tsx`). */
export const BAND_WORDS: Record<SkillBand, string> = {
  novice: levelPhrase("novice"),
  develop: levelPhrase("develop"),
  profic: levelPhrase("profic"),
};

function studiedPhrase(node: GraphNode, now: Date): string {
  const studied = relativeStudied(node.last_studied_at, now);
  return studied === "not studied yet" ? studied : `last studied ${studied}`;
}

/**
 * "29% · struggling · last studied 4 days ago" (§5 B1.2).
 *
 * ONE measure per concept on the quiz home. A concept the learner model's plan
 * proposes (spec §13 A143) reads its skill meter and band — the decayed BKT
 * estimate the plan ranked it by, its reason line states and the quiz results
 * report — never the graph's stored mastery score beside it, which is not
 * decayed and, for a concept never studied, is not the model's prior either.
 * A concept the plan does not propose keeps the graph's score and tier.
 */
export function metaLine(node: GraphNode, now: Date = new Date(), plan?: CandidatePlan): string {
  const when = studiedPhrase(node, now);
  if (plan) return `${skillPercent(plan.pKnown)} · ${BAND_WORDS[plan.band]} · ${when}`;
  return `${pct(node.mastery_score)}% · ${node.mastery_tier} · ${when}`;
}

/** `metaLine` without its number, for a card whose plan line already states
 *  the skill meter: "developing · not studied yet". */
export function planStateLine(node: GraphNode, plan: CandidatePlan, now: Date = new Date()): string {
  return `${BAND_WORDS[plan.band]} · ${studiedPhrase(node, now)}`;
}

/** What the home ranks and shows a concept by: its skill meter when the plan
 *  proposes it, else the graph's mastery score (see `metaLine`). */
export function shownMastery(node: GraphNode, plan?: CandidatePlan): number {
  return plan ? plan.pKnown : node.mastery_score;
}

/**
 * The one-line "why this one" on an alternative row.
 *
 * Never-studied says so; otherwise a recent completed attempt with misses is the
 * most actionable thing we know; otherwise how long it has been.
 */
export function rationaleFor(
  node: GraphNode,
  lastAttempt?: AttemptSummary,
  now: Date = new Date(),
): string {
  const p = `${pct(node.mastery_score)}%`;
  const days = daysAgo(node.last_studied_at, now);
  if (days === null && !node.times_studied) return `${p} · not studied yet`;

  if (lastAttempt && lastAttempt.score !== null && lastAttempt.total !== null) {
    const missed = lastAttempt.total - lastAttempt.score;
    if (missed > 0) return `${p} · missed ${missed} last time`;
  }

  if (days === null) return `${p} · not reviewed recently`;
  if (days === 0) return `${p} · reviewed today`;
  if (days === 1) return `${p} · reviewed yesterday`;
  return `${p} · not reviewed in ${days} days`;
}

/**
 * Every concept worth proposing, weakest first, each with its course, colour and
 * rationale already resolved. NOT capped — `get_recommendations`' `limit=5` is a
 * transport cap on a thin payload, while callers here need the whole set for the
 * due count and the queue. Slice to `RECOMMENDATION_LIMIT` where parity matters.
 */
export function rankCandidates(
  nodes: GraphNode[],
  courses: EnrolledCourse[],
  attempts: AttemptSummary[],
  now: Date = new Date(),
): Candidate[] {
  return nodes
    .filter(isDue)
    .sort(byMasteryAsc)
    .map(node => {
      const course = courseFor(node, courses);
      const lastAttempt = latestCompletedAttempt(node.id, attempts);
      return {
        node,
        course,
        color: colorFor(node, course),
        rationale: rationaleFor(node, lastAttempt, now),
        ...(lastAttempt ? { lastAttempt } : {}),
      };
    });
}

/** The card at the top of quiz home: the weakest concept the student has
 *  actually opened, falling back to the weakest overall (R-7). */
export function primaryOf(candidates: Candidate[]): Candidate | null {
  return candidates.find(c => c.node.times_studied > 0) ?? candidates[0] ?? null;
}

/** "Also worth a look" — the next couple, never repeating the primary. */
export function alternativesOf(
  candidates: Candidate[],
  primary: Candidate | null,
  n = 2,
): Candidate[] {
  return candidates.filter(c => c.node.id !== primary?.node.id).slice(0, n);
}

/**
 * "Review everything due": the same membership filter over the WHOLE scoped
 * graph, not the capped recommendation list. There is no spaced-repetition or
 * days-since concept anywhere in the backend (R4 §3), so "due" means exactly
 * "in one of the three tiers that need work" — nothing is invented here.
 */
export function dueSet(nodes: GraphNode[]): {
  conceptIds: string[];
  count: number;
  courseCount: number;
} {
  const due = nodes.filter(isDue).sort(byMasteryAsc);
  const courses = new Set(due.map(n => n.course_id).filter((id): id is string => Boolean(id)));
  return {
    conceptIds: due.map(n => n.id),
    count: due.length,
    courseCount: courses.size,
  };
}

/**
 * The concept ids a multi-concept session works through, weakest first, capped
 * at `QUEUE_MAX`. `/generate` is per concept (R-4), so "practice this course"
 * and "review everything due" are both queues of single-concept attempts.
 */
export function queueFor(
  scope: "course" | "due",
  nodes: GraphNode[],
  courseId?: string,
): string[] {
  const scoped = scope === "course"
    ? nodes.filter(n => n.course_id === courseId)
    : nodes;
  return scoped.filter(isDue).sort(byMasteryAsc).slice(0, QUEUE_MAX).map(n => n.id);
}

/**
 * The concept a queued session moves to next, named.
 *
 * The queue holds ids and the results screen is handed only the concept it just
 * quizzed, so "Next: {concept}" cannot be built from the session alone — this
 * resolves the id against the loaded graph.
 *
 * `null` covers both "the queue is finished" and "the next id isn't in the
 * loaded (scoped) graph, so we can't name it". That is deliberate: it is a LABEL,
 * and a caller must never use it to decide whether the exit exists — that stays
 * `queueOf(scope).length > queueIndex + 1`, which needs no graph. Guessing a name
 * would be worse than an unnamed button.
 */
export function nextConceptInQueue(
  session: QuizSession,
  nodes: GraphNode[],
): { id: string; name: string } | null {
  const id = queueOf(session.scope)[session.queueIndex + 1];
  if (!id) return null;
  const name = nodes.find(n => n.id === id)?.concept_name?.trim();
  return name ? { id, name } : null;
}

/** What a deep link actually points at, once resolved against the loaded graph. */
export interface EntrySelection {
  conceptId: string | null;
  courseId: string | null;
  /** The link named a concept or topic that isn't in the current scope. §6 wants
   *  a toast and an ordinary home, not a silently ignored link. */
  unresolved: boolean;
}

/**
 * Resolves `?concept=<nodeId>` / `?topic=<name>` against the scoped graph.
 *
 * The id path goes through `quizSelection.resolveInitialSelection` — the same
 * resolver the old picker used, which already answers "unknown id → nothing
 * selected" rather than pre-selecting a node that isn't there. `topic` is the
 * fuzzy legacy form (a concept NAME, from the tree's and dashboard's old links),
 * matched case-insensitively; `concept` wins when both are present.
 */
export function entrySelection(
  entry: { concept?: string; topic?: string; course?: string },
  nodes: GraphNode[],
  courses: EnrolledCourse[] = [],
): EntrySelection {
  const byCourseId = new Map(courses.map(c => [c.course_id, c]));
  const concepts: QuizConcept[] = nodes
    .filter(n => !n.is_subject_root)
    .map(n => ({
      id: n.id,
      name: n.concept_name,
      course_id: n.course_id ?? null,
      course_code: n.course_id ? byCourseId.get(n.course_id)?.course_code ?? null : null,
    }));

  if (entry.concept) {
    const resolved = resolveInitialSelection(concepts, entry.concept);
    return {
      conceptId: resolved.conceptId,
      courseId: resolved.courseId ?? entry.course ?? null,
      unresolved: resolved.conceptId === null,
    };
  }

  if (entry.topic) {
    const wanted = entry.topic.trim().toLowerCase();
    const match = concepts.find(c => c.name.trim().toLowerCase() === wanted);
    return {
      conceptId: match?.id ?? null,
      courseId: match?.course_id ?? entry.course ?? null,
      unresolved: !match,
    };
  }

  return { conceptId: null, courseId: entry.course ?? null, unresolved: false };
}

// ── The learner model's plan (learning-loop spec §13 A143) ──────────────────
//
// With `quiz_concept_plan` on, the backend ranks the concepts from the learner
// model (`GET /api/quiz/plan`, `backend/learning/quiz_plan.py`): reviews whose
// FSRS date has passed first, most overdue first; then concepts the student
// holds an open misconception on; then concepts whose prerequisites are
// proficient but which are not yet. These replace the mirror above — the
// graph's mastery tier — as the home's proposals and its "due" queue. The
// plan is intersected with the scoped graph, so a concept outside the active
// semester never appears.

/** "62%" — the skill meter, as the card and the rows read it. */
export function skillPercent(pKnown: number): string {
  return `${Math.round(pKnown * 100)}%`;
}

/** Why the learner model proposes a concept, in a student's words. */
export function planReasonCopy(reason: PlanReason): string {
  switch (reason) {
    case "due":
      return "Due for review — bring it back before it fades.";
    case "misconception":
      // Never "this round checks it": a round targets the misconception only
      // with quiz_planned_questions on (server-only), in a multiple-choice or
      // mixed format, and only if a tagged distractor survives (#866 K43).
      return "You've mixed this one up before — worth practicing again.";
    default:
      return "Ready to learn — everything it builds on is solid.";
  }
}

/** Why the learner model proposes a concept, in a row's few words (the quiz
 *  home's alternatives, the Dashboard's Today plan). */
export function planReasonShort(reason: PlanReason): string {
  switch (reason) {
    case "due":
      return "due for review";
    case "misconception":
      return "mixed up before";
    default:
      return "ready to learn";
  }
}

/** The short form for an alternative row. */
function planRowCopy(concept: PlannedConcept): string {
  return `skill ${skillPercent(concept.p_known)} · ${planReasonShort(concept.reason)}`;
}

/** The plan's concepts as candidates, in the plan's order, over the scoped
 *  graph only. */
export function rankFromPlan(
  plan: QuizPlan,
  nodes: GraphNode[],
  courses: EnrolledCourse[],
  attempts: AttemptSummary[],
): Candidate[] {
  const byId = new Map(nodes.filter(n => !n.is_subject_root).map(n => [n.id, n]));
  const out: Candidate[] = [];
  for (const concept of plan.concepts) {
    const node = byId.get(concept.node_id);
    if (!node) continue;
    const course = courseFor(node, courses);
    const lastAttempt = latestCompletedAttempt(node.id, attempts);
    out.push({
      node,
      course,
      color: colorFor(node, course),
      rationale: planRowCopy(concept),
      plan: { reason: concept.reason, pKnown: concept.p_known, band: concept.band },
      ...(lastAttempt ? { lastAttempt } : {}),
    });
  }
  return out;
}

/** "Practice this course" from the plan: the course's proposed concepts in
 *  the plan's order, capped at `QUEUE_MAX` — never a concept the learner model
 *  does not propose (not ready, or proficient and not yet due). */
export function courseQueueFromPlan(candidates: Candidate[], courseId: string): string[] {
  return candidates
    .filter(c => c.plan && c.node.course_id === courseId)
    .slice(0, QUEUE_MAX)
    .map(c => c.node.id);
}

/**
 * "Practice this course" on a planned home. The course's own plan (read with
 * its `course_id`) when there is one, else the all-courses plan's concepts of
 * that course. When the learner model proposes none of them (each is
 * proficient and not yet due, or waits on a prerequisite), the tier ranking's
 * queue for the course stands in: the student asked to practise THIS course,
 * and an empty queue would quietly swap the card for an unrelated concept.
 */
export function plannedCourseQueue(
  candidates: Candidate[],
  courseCandidates: Candidate[] | null | undefined,
  nodes: GraphNode[],
  courseId: string,
): string[] {
  const planned = courseQueueFromPlan(courseCandidates ?? candidates, courseId);
  return planned.length > 0 ? planned : queueFor("course", nodes, courseId);
}

/** "Review everything due" from the plan: the concepts whose FSRS review is
 *  due, in the plan's (overdue-first) order, over the scoped graph. */
export function dueFromPlan(
  plan: QuizPlan,
  nodes: GraphNode[],
): { conceptIds: string[]; count: number; courseCount: number } {
  const scoped = new Map(nodes.map(n => [n.id, n]));
  const due = plan.concepts.filter(c => c.reason === "due" && scoped.has(c.node_id));
  const courses = new Set(
    due.map(c => scoped.get(c.node_id)?.course_id).filter((id): id is string => Boolean(id)),
  );
  return { conceptIds: due.map(c => c.node_id), count: due.length, courseCount: courses.size };
}

/**
 * The "pick something specific" list: every concept, grouped under its course.
 *
 * Courses sort by code and concepts by name — this is a browse surface, not a
 * ranking, so alphabetical beats weakest-first for finding a known name (the
 * same choice `quizSelection.ts` already makes for its picker). Courses with no
 * concepts are omitted: unlike the old dropdown, an empty group here would be a
 * heading with nothing under it.
 */
export function groupByCourse(
  nodes: GraphNode[],
  courses: EnrolledCourse[],
): { course: EnrolledCourse; nodes: GraphNode[] }[] {
  const byCourse = new Map<string, GraphNode[]>();
  for (const node of nodes) {
    if (node.is_subject_root || !node.course_id) continue;
    const bucket = byCourse.get(node.course_id);
    if (bucket) bucket.push(node);
    else byCourse.set(node.course_id, [node]);
  }
  return courses
    .filter(c => byCourse.has(c.course_id))
    .sort((a, b) => a.course_code.localeCompare(b.course_code))
    .map(course => ({
      course,
      nodes: (byCourse.get(course.course_id) ?? [])
        .slice()
        .sort((a, b) => a.concept_name.localeCompare(b.concept_name)),
    }));
}
