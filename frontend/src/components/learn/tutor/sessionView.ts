// What the Tutor shows about the session on screen, from the loop's own
// data (moved out of LoopLearn.tsx unchanged): the plan the panel lists, the
// current concept, the phase line, and the home's first focus.
import type { EnrolledCourse, LoopGoal, LoopPanelConcept, LoopPhase, LoopPlanConcept } from "@/lib/api";
import type { GraphNode } from "@/lib/data";
import { retentionHref } from "@/context/RetentionDueContext";
import { sessionTitle, type TutorSessionRow } from "./sessions";

/** An approved plan as the server reports it: its concepts and the cursor. */
export type ApprovedPlan = { concepts: LoopPanelConcept[]; cursor: number };

export function dueLink(courseIds: string[]): string {
  return courseIds.length > 0 ? retentionHref(courseIds) : "/study";
}

/** The plan the panel lists: while planning, the proposal on screen; once a
 *  plan is approved, that plan as the server last reported it (a feedback turn's
 *  band repair can add a concept to it, #866 K08), else the proposal. */
export function panelPlanOf(phase: LoopPhase, plan: LoopPlanConcept[] | null, approved: { concepts: LoopPanelConcept[] } | null): LoopPanelConcept[] | null {
  return phase === "plan" ? plan ?? approved?.concepts ?? null : approved?.concepts ?? plan ?? null;
}

/** The concept the session is on (#866 K08): the approved plan's cursor, which
 *  the server moves (null once the plan is done); with no plan approved, the
 *  concept the last turn named. */
export function currentConcept(approved: ApprovedPlan | null, focus: string | null): string | null {
  return approved ? cursorNode(approved) : focus;
}

/** Where a graded check left the plan, for its verdict's note (#866 K08):
 *  undefined while the next check stays on the graded concept; the next
 *  concept's name once the cursor moved on; null once the plan has no next. */
export function nextAfterVerdict(approved: ApprovedPlan | null, graded: string | null, names: Map<string, string>): string | null | undefined {
  if (!approved || !graded) return undefined;
  const at = cursorNode(approved);
  if (at === graded) return undefined;
  return at ? names.get(at) ?? "the next concept" : null;
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

/** Where the Learn step is in the approved plan ("2 of 4"), shown beside
 *  the stepper's Learn step; null outside teaching or off the plan. */
export function learnProgressOf(phase: LoopPhase, plan: LoopPanelConcept[] | null, focus: string | null): string | null {
  if (phase === "probe" || phase === "plan" || phase === "close") return null;
  const n = plan?.length ?? 0;
  const at = plan && focus ? plan.findIndex((c) => c.node_id === focus) : -1;
  return at >= 0 && n > 1 ? `${at + 1} of ${n}` : null;
}

/** The concept T1 offers as a first focus: the weakest one not yet mastered. */
export function weakestConcept(nodes: GraphNode[]): { id: string; name: string } | null {
  const open = nodes.filter((n) => !n.is_subject_root && n.mastery_tier !== "mastered");
  open.sort((a, b) => a.mastery_score - b.mastery_score);
  return open[0] ? { id: open[0].id, name: open[0].name } : null;
}

/** A session on one concept (#866 K05): its goal is that concept, confirmed by
 *  the student's click on it — never a name matched to a concept. */
export const conceptGoal = (id: string): LoopGoal => ({ text: "", target_node_ids: [id] });

/** The goal a deep link asks for: its concepts, when the link names the course
 *  on screen (the server still checks they are that course's). `concept` is one
 *  node id, or several joined by commas (Send to tutor's linked concepts). */
export function linkGoal(link: { concept: string; course: string }, courseId: string | null): LoopGoal | undefined {
  const ids = [...new Set(link.concept.split(",").map((id) => id.trim()).filter(Boolean))];
  return ids.length > 0 && link.course && link.course === courseId ? { text: "", target_node_ids: ids } : undefined;
}

/** A session the "New session" button should wrap up first: one the student is in. */
export function isOpenPhase(phase: LoopPhase): boolean {
  return phase !== "close";
}

/** The TopBar's title for the view on screen (a session's: its row's name). */
export function tutorTopTitle(
  view: string,
  course: EnrolledCourse | null,
  readOnly: { topic: string } | null,
  sessionRow: TutorSessionRow | null,
  sessionId: string | null,
): string {
  if (view === "home" || view === "goal") return "New session";
  if (view === "all") return "All sessions";
  if (view === "course") return course ? `${course.course_code ? `${course.course_code} · ` : ""}${course.course_name}` : "Course";
  if (readOnly) return readOnly.topic || "Earlier session";
  return sessionRow ? sessionTitle(sessionRow, course ?? undefined) : sessionId ? "Guided session" : "Tutor";
}

