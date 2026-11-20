// What the Tutor shows about the session on screen, from the loop's own
// data (moved out of LoopLearn.tsx unchanged): the plan the panel lists, the
// current concept, the phase line, and the home's first focus.
import type { LoopPanelConcept, LoopPhase, LoopPlanConcept } from "@/lib/api";
import type { GraphNode } from "@/lib/data";
import { retentionHref } from "@/context/RetentionDueContext";
import type { TutorSessionRow } from "./sessions";

/** An approved plan as the server reports it: its concepts and the cursor. */
export type ApprovedPlan = { concepts: LoopPanelConcept[]; cursor: number };

export function dueLink(courseIds: string[]): string {
  return courseIds.length > 0 ? retentionHref(courseIds) : "/study";
}

/** The plan the panel lists: the one on screen, else the approved one /status reported. */
export function panelPlanOf(plan: LoopPlanConcept[] | null, approved: { concepts: LoopPanelConcept[] } | null): LoopPanelConcept[] | null {
  return plan ?? approved?.concepts ?? null;
}

/** The name of `id`, else of the approved plan's current concept. */
export function conceptAt(names: Map<string, string>, id: string | null, approved: ApprovedPlan | null): string | null {
  const at = id ?? cursorNode(approved);
  return at ? names.get(at) ?? null : null;
}

/** The concept the approved plan's cursor is on (a resumed session's current one). */
export function cursorNode(p: ApprovedPlan | null): string | null {
  return p?.concepts[p.cursor]?.node_id ?? null;
}

export function findRow(rows: TutorSessionRow[], id: string | null): TutorSessionRow | null {
  return id ? rows.find((r) => r.id === id) ?? null : null;
}

/** Where an open session is, in words: "Check-in", "Plan · 3 concepts",
 *  "Recursion · concept 2 of 3", "Wrap-up". */
export function phaseText(phase: LoopPhase, plan: LoopPanelConcept[] | null, focus: string | null, names: Map<string, string>): string {
  const n = plan?.length ?? 0;
  if (phase === "probe") return "Check-in";
  if (phase === "plan") return n ? `Plan · ${n} ${n === 1 ? "concept" : "concepts"}` : "Plan";
  if (phase === "close") return "Wrap-up";
  const name = focus ? names.get(focus) : undefined;
  const at = plan && focus ? plan.findIndex((c) => c.node_id === focus) : -1;
  if (name && at >= 0) return `${name} · concept ${at + 1} of ${n}`;
  // an approved plan with no current concept: its cursor is past the end
  return name ?? (n > 0 ? "Plan complete" : "Learning");
}

/** The concept T1 offers as a first focus: the weakest one not yet mastered. */
export function weakestConcept(nodes: GraphNode[]): string | null {
  const open = nodes.filter((n) => !n.is_subject_root && n.mastery_tier !== "mastered");
  open.sort((a, b) => a.mastery_score - b.mastery_score);
  return open[0]?.name ?? null;
}

/** A session the "New session" button should wrap up first: one the student is in. */
export function isOpenPhase(phase: LoopPhase): boolean {
  return phase !== "close";
}
