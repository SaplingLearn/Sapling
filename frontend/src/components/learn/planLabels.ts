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

/** The design board's words for the same kinds (Tutor redesign, `plan_v2`):
 *  started and related practice are both just practice. */
export const PLAN_KIND_BOARD: Record<string, string> = {
  review: "Quick review",
  new: "New",
  started: "Practice",
  sibling: "Practice",
};

/** One label per kind, the board's while `plan_v2` is on, else the badge's.
 *  Every place that names a plan concept's kind asks here with the same
 *  switch (the plan card, the transcript's plan, the session panel), so no two
 *  of them can say different things. */
export function planKindLabel(kind: string, boardWords = false): string | null {
  if (boardWords) return own(PLAN_KIND_BOARD, kind) ? PLAN_KIND_BOARD[kind] : null;
  return planKind(kind)?.label ?? null;
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
