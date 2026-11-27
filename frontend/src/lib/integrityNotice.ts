/**
 * Learning-loop spec §13 A125: the integrity guard on the AI surfaces outside
 * the loop holds back generated output that would give away the answer to one
 * of the student's open learning checks, and records that check as helped
 * (so it no longer counts as solved unaided). A whole result held back arrives
 * as a 409 whose detail `humanizeError` shows; a list with only some items held
 * back arrives with a `withheld` count — these sentences tell the student.
 */

export function withheldNotice(count: number, noun: "card" | "concept"): string {
  const what = count === 1 ? `1 ${noun} was` : `${count} ${noun}s were`;
  return `${what} held back because ${count === 1 ? "it" : "they"} would give away the answer to an open learning check. That check now counts as helped.`;
}

export const CLEANUP_WITHHELD_NOTICE =
  "Cleanup was held back because it would give away the answer to an open learning check. Your cards are unchanged, and that check now counts as helped.";
