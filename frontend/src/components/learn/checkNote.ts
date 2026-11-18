import type { LoopCheckNext } from "@/lib/api";

// spec §13 A128: the student's own upload is still being drafted into questions
export const PREPARING_COPY = "Preparing practice questions from your upload…";
export const PLAN_DONE_COPY = "That's every concept in today's plan — close the session when you're ready.";
export const NO_ITEM_COPY = "No check is ready for this concept yet — keep going with the tutor.";

/** "A", "A and B", "A, B and C". */
function listNames(names: string[]): string {
  if (names.length <= 1) return names[0] ?? "";
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

/** No check question is ready for these concepts yet (nothing was checked). */
export function checksUnavailableCopy(names: string[]): string {
  return `No check questions are ready yet for ${listNames(names)}. You can keep learning with the tutor, or wrap up the session when you're ready.`;
}

/**
 * What "Check me" says when /check/next posed nothing (`check` null). The
 * fresh-practice notice speaks for itself (null here). Then, in order: the
 * student's upload is still being drafted (A128); the concepts that have no
 * check question yet (`checks_unavailable_node_ids`, named); every concept in
 * the plan done — only when none of them was left unchecked that way; else
 * this concept has no check yet.
 */
export function checkMeNote(r: LoopCheckNext, names: Map<string, string>): string | null {
  if (r.practice_unavailable_node_ids?.length) return null;
  if (r.preparing) return PREPARING_COPY;
  const missing = r.checks_unavailable_node_ids ?? [];
  if (missing.length > 0) {
    return checksUnavailableCopy([...new Set(missing.map((id) => names.get(id) ?? "this concept"))]);
  }
  return r.plan_done ? PLAN_DONE_COPY : NO_ITEM_COPY;
}
