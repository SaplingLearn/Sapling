/**
 * What each concept in today's plan is to the student (Tutor V2, wireframe
 * T5): ONE label per concept, from the plan's `kind` (GET /plan, and /status's
 * approved plan; backend `learning/planner.py::PlanKind`). The plan card shows
 * it as the concept's badge and the session panel under the concept's name,
 * so the two can never say different things.
 *
 * `started` is new material the student has already made progress on (a map
 * tier past unexplored), so a concept the skill meter shows at 80% is never
 * called "New".
 */
export const PLAN_KIND: Record<string, { label: string; chip: string }> = {
  review: { label: "Due for review", chip: "chip chip--warn" },
  new: { label: "New", chip: "chip chip--accent" },
  started: { label: "Keep practicing", chip: "chip" },
  sibling: { label: "Related practice", chip: "chip chip--info" },
};

const own = (o: object, k: string) => Object.prototype.hasOwnProperty.call(o, k);

/** The kind's badge, or null for a kind this client does not know. */
export function planKind(kind: string): { label: string; chip: string } | null {
  return own(PLAN_KIND, kind) ? PLAN_KIND[kind] : null;
}

const GOAL_REASON: Record<string, string> = {
  goal: "Your selected goal",
  prerequisite: "Prerequisite for your goal",
};

/**
 * Why a goal session plans the concept (GET /plan `reason`: the goal itself,
 * or a prerequisite of it), or null. A plan without a goal carries no reason —
 * its kind says everything — and any other value is not shown, so no line
 * under a concept can contradict its badge.
 */
export function planGoalReason(reason: string | undefined): string | null {
  return reason && own(GOAL_REASON, reason) ? GOAL_REASON[reason] : null;
}
