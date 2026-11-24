/**
 * Knowledge Tree node → tool deep links (W8.2 coherence spine).
 *
 * Reuses the same builders as Study's `useToolNav` / Quiz entry
 * (`learnHrefForNode`, `buildQuizHref`, `flashcardsHref`, `studyGuideHref`) —
 * one concept id, no forked ranking. Guide stamps `?concept=` (or `?course=`
 * for a subject root) the same way Teach/Quiz do.
 */
import { learnHrefForNode, type GraphNode } from "@/lib/data";
import { buildQuizHref } from "@/lib/quiz/source";
import { flashcardsHref, studyGuideHref } from "@/lib/toolHrefs";

export type TreeNodeActionKey = "teach" | "quiz" | "cards" | "guide";

export type TreeNodeRef = Pick<GraphNode, "id" | "name" | "course_id" | "is_subject_root">;

/** Where Quiz (and similar) should return: this node's open panel, or the bare tree for a course root. */
export function treeReturnTo(node: Pick<TreeNodeRef, "id" | "is_subject_root">): string {
  return node.is_subject_root ? "/tree" : `/tree?node=${encodeURIComponent(node.id)}`;
}

/** Course id on the node, or peeled from a subject-root id. */
export function treeNodeCourseId(node: TreeNodeRef): string | null {
  if (node.course_id) return node.course_id;
  if (node.is_subject_root) {
    const peeled = node.id.replace(/^subject_root__/, "");
    return peeled || null;
  }
  return null;
}

/** Learn / Tutor: topic + concept id for a concept; course-scoped, no topic for a root. */
export function treeTeachHref(node: TreeNodeRef): string {
  return learnHrefForNode(node);
}

/** Quiz home on this concept (or the course for a root), tagged `from=tree`. */
export function treeQuizHref(node: TreeNodeRef): string {
  const returnTo = treeReturnTo(node);
  if (node.is_subject_root) {
    const courseId = treeNodeCourseId(node);
    return buildQuizHref(
      courseId ? { course: courseId } : {},
      { kind: "tree", returnTo },
    );
  }
  return buildQuizHref(
    { concept: node.id },
    { kind: "tree", returnTo, conceptId: node.id },
  );
}

/**
 * Flashcards for this concept's deck (`start` begins when empty), or the
 * course's Flashcards home for a subject root.
 */
export function treeCardsHref(node: TreeNodeRef): string {
  const courseId = treeNodeCourseId(node);
  if (node.is_subject_root) return flashcardsHref(courseId);
  return flashcardsHref(courseId, [node.name], { start: true });
}

/**
 * Study Guides home scoped to this concept id (or the course for a subject
 * root) — same `concept` / `course` keys Teach and Quiz use.
 */
export function treeGuideHref(node: TreeNodeRef): string {
  if (node.is_subject_root) {
    const courseId = treeNodeCourseId(node);
    return studyGuideHref(courseId ? { course: courseId } : undefined);
  }
  return studyGuideHref({ concept: node.id });
}

export type TreeNodeAction = {
  key: TreeNodeActionKey;
  label: string;
  href: string;
  /** Primary CTA styling (Teach). */
  primary?: boolean;
};

/**
 * Actions offered for a selected tree node.
 *
 * Always: Teach (Learn) + Quiz (when quiz is shown).
 * When `learning_loop` is on and Study is shown: Cards + Guide — the W8.2 spine.
 */
export function treeNodeActions(
  node: TreeNodeRef,
  opts: { loopOn: boolean; quizShown: boolean; studyShown: boolean },
): TreeNodeAction[] {
  const teachLabel = opts.loopOn ? "Teach" : "Learn this";
  const quizLabel = opts.loopOn ? "Quiz" : "Quick quiz";
  const out: TreeNodeAction[] = [
    { key: "teach", label: teachLabel, href: treeTeachHref(node), primary: true },
  ];
  if (opts.quizShown) {
    out.push({ key: "quiz", label: quizLabel, href: treeQuizHref(node) });
  }
  if (opts.loopOn && opts.studyShown) {
    out.push({ key: "cards", label: "Cards", href: treeCardsHref(node) });
    out.push({ key: "guide", label: "Guide", href: treeGuideHref(node) });
  }
  return out;
}
