/**
 * Where the quiz sends you when you leave it (R-10).
 *
 * The old screen pushed `/learn` for Cancel, Exit and Done alike, which dropped
 * a student who arrived from the tree into a tutor session they never asked for.
 * The rule now: go back where you came from, and if that is unknown, go to the
 * tree focused on the concept you were quizzing. Nothing ever lands on `/learn`
 * without a session.
 */

import { isSafeReturnPath } from "./source";
import type { QuizSession, SourceKind } from "./types";

/** The tree honours `?node=<id>` by selecting that node in the detail panel (C1). */
function treeHref(conceptId: string | undefined): string {
  return conceptId ? `/tree?node=${encodeURIComponent(conceptId)}` : "/tree";
}

/** The destination for "Back", for the mid-quiz leave, and for Cancel. */
export function returnToSource(session: QuizSession): string {
  const { returnTo } = session.source;
  // Re-checked at use, not only at parse: a session can come back off
  // localStorage, where anything could have been written.
  if (isSafeReturnPath(returnTo)) return returnTo;
  return treeHref(session.source.conceptId || session.conceptId || undefined);
}

const SOURCE_LABELS: Record<SourceKind, string> = {
  tree: "Back to your tree",
  notes: "Back to your note",
  dashboard: "Back to dashboard",
  nav: "Back to your tree",
  link: "Back to your tree",
  quiz: "Back to your tree",
};

/** The label on the secondary exit. Anything unrecognised reads as the tree,
 *  which is where `returnToSource` falls back to as well. */
export function sourceLabel(kind: SourceKind): string {
  return SOURCE_LABELS[kind] ?? SOURCE_LABELS.tree;
}

/** Where Cancel on quiz home goes: the origin if there was one, else the
 *  dashboard (§5 B1.8) — cancelling out of a quiz you never started should not
 *  drop you on the tree you didn't come from. */
export function cancelTarget(session: QuizSession): string {
  return isSafeReturnPath(session.source.returnTo) ? session.source.returnTo : "/dashboard";
}
