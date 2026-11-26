import type { ChatMsg } from "../chat/ChatPanel";
import type { LoopPanelConcept } from "@/lib/api";
import { planGoalReason, planKindLabel } from "./planLabels";

/**
 * The session opener's two template texts (spec §13 A121): the tutor says one
 * of them as the session starts, before the check-in and the plan. They are
 * backend/learning/turn_shape.py's LOOP_PROBE_OPENER and LOOP_PLAN_OPENER,
 * copied exactly; backend/tests/test_loop_opener_frontend_twin.py fails when
 * the two drift apart.
 */
export const PROBE_PHASE_OPENERS: readonly string[] = [
  "Welcome! We'll start with a quick check-in to see where you are, then plan your session together.",
  "Welcome! This course has no check-in questions yet, so we'll go straight to planning your session.",
];

/** The plan's own intro (PlanPanel says it over the plan card). */
export const PLAN_INTRO_COPY = "Here's today's plan. Due reviews come first, then what's new, then related practice.";
/** `plan_v2`: the same, in the board's words. */
export const PLAN_INTRO_COPY_BOARD = "Here's today's plan. Quick reviews come first, then what's new, then practice.";
/** An empty plan: the session went straight to teaching (PlanPanel's empty line). */
export const EMPTY_PLAN_COPY = "Nothing to plan right now — ask the tutor anything.";

/** A concept name is the student's material, not markdown: every ASCII
 *  punctuation mark is escaped so the bubble shows it as written. */
const escapeMarkdown = (text: string) => text.replace(/[\\`*_{}[\]()#+\-.!|~<>]/g, "\\$&");

/** The approved plan as the tutor's turn in the conversation: the intro, then
 *  each concept in order with why it is there (the session panel's words). */
export function planTurnText(plan: LoopPanelConcept[], boardWords = false): string {
  if (plan.length === 0) return EMPTY_PLAN_COPY;
  const rows = plan.map((c, i) => {
    const why = planGoalReason(c.reason) ?? planKindLabel(c.kind, boardWords) ?? "";
    return `${i + 1}. ${escapeMarkdown(c.concept_name || "Concept")}${why ? ` — ${why}` : ""}`;
  });
  return `${boardWords ? PLAN_INTRO_COPY_BOARD : PLAN_INTRO_COPY}\n\n${rows.join("\n")}`;
}

/**
 * The teaching conversation's history, kept true (U2). The log starts with the
 * opener, which promised the check-in and the plan; once the session teaches
 * both are done, and neither was ever a chat row, so the opener read as if they
 * were still ahead and the plan was gone. The opener's row now shows the plan
 * the student approved (`plan`: [] for an empty one), or — when the plan is
 * unknown (its read failed) — is left out rather than describe finished steps.
 * Any other first row (a quiz-ask session's own opener) is kept as it is.
 */
export function withPlanHistory(messages: ChatMsg[], plan: LoopPanelConcept[] | null, boardWords = false): ChatMsg[] {
  const first = messages[0];
  if (!first || first.role !== "assistant" || !PROBE_PHASE_OPENERS.includes(first.content.trim())) return messages;
  if (plan === null) return messages.slice(1);
  return [{ ...first, content: planTurnText(plan, boardWords) }, ...messages.slice(1)];
}
