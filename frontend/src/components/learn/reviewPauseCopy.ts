// The review queue's pause copy (DueQueue; spec §3.5, §13 A20): which cap paused
// what, and when it lifts, from the 429's `scope` and /review/summary's
// `paused_scope` / `paused_until` (#866 K18). A monthly cap lifts on the 1st,
// weeks away: the copy names it, and formatResetAt prints that reset's date.
import type { LoopBudgetPause } from "@/lib/api";
import { formatResetAt } from "./BudgetPausedBanner";

/** What lifts a cap that holds review concepts, by its scope
 *  (backend services/ai_budget.py `Scope`). */
const LIFTS: Record<string, string> = {
  daily_usd: "your daily AI budget resets",
  daily_tokens: "your daily AI budget resets",
  monthly_usd: "your monthly AI budget resets",
  daily_tutor_calls: "your daily tutor limit resets",
};

/** A 429 "ai budget reached" on /review/answer: the per-minute rate limit on a
 *  check (spec §3.5) — send the answer again then — or the grader cap (#866
 *  K16), until which no check can be graded; flashcards need no grader. */
export function answerPauseMessage(pause: LoopBudgetPause): string {
  if (pause.scope === "daily_grades") {
    return pause.resetAt
      ? `Today's grading limit is reached: checks can't be graded until ${formatResetAt(pause.resetAt)}. Flashcards keep working.`
      : "Today's grading limit is reached: checks can't be graded for now. Flashcards keep working.";
  }
  if (pause.scope === "rate_limit") {
    return pause.resetAt
      ? `Too many AI requests in the last minute. Send this answer again at ${formatResetAt(pause.resetAt)}.`
      : "Too many AI requests in the last minute. Send this answer again in a moment.";
  }
  return pause.resetAt
    ? `AI tutor paused until ${formatResetAt(pause.resetAt)}. Flashcards and review keep working.`
    : "AI tutor paused for now. Flashcards and review keep working.";
}

/** Novice concepts held back at the tutor hard level (`/review/summary`
 *  `paused`, with the cap's scope and reset when the server names them). */
export function pausedConceptsMessage(n: number, scope?: string | null, until?: string | null): string {
  // A server before #866 K18 names no scope: its copy said the daily budget.
  const lifts = scope == null ? LIFTS.daily_usd : LIFTS[scope] ?? "your AI budget resets";
  const when = until ? `until ${formatResetAt(until)}, when ${lifts}` : `until ${lifts}`;
  return `${n} ${n === 1 ? "concept" : "concepts"} paused ${when}. Flashcards and other reviews keep working.`;
}

/** Concepts held back at the grader cap (`/review/summary` `grading_paused`,
 *  #866 K16): their checks wait until it lifts; flashcards keep being served. */
export function gradingPausedMessage(n: number, until?: string | null): string {
  const what = `Checks on ${n} ${n === 1 ? "concept" : "concepts"} wait`;
  const when = until ? `until ${formatResetAt(until)}, when today's grading limit resets` : "until today's grading limit resets";
  return `${what} ${when}. Flashcards keep working.`;
}
