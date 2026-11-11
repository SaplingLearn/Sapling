// Pure label helpers for the tutor screen (screens/Learn.tsx), split out of
// its render so each branch is unit-testable on its own.

import type { EnrolledCourse } from "@/lib/api";
import type { GraphNode } from "@/lib/data";

// The chat header's subtitle: "CS101 · Socratic Tutor · 4 Messages" — the
// course prefix only when the session's course has a code.
export function sessionSubtitle(courseCode: string | undefined, modeName: string, messageCount: number): string {
  return `${courseCode ? `${courseCode} · ` : ""}${modeName} Tutor · ${messageCount} Messages`;
}

// The knowledge-map focus card's heading: the focused concept, else the
// course it anchors on, else the session topic.
export function focusCardTitle(
  focusConcept: GraphNode | null,
  cardCourse: EnrolledCourse | null,
  topic: string,
): string {
  return focusConcept ? focusConcept.name : (cardCourse?.course_name ?? topic);
}

// The focus card's description: a concept's stored description, else its
// AI-fetched blurb (`descCache`, keyed by node id), else the connected-
// concepts sentence; a course-anchored card counts the course's concepts.
export function focusCardDescription(
  focusConcept: GraphNode | null,
  descCache: Record<string, string>,
  neighborCount: number,
  courseConceptCount: number,
): string {
  return focusConcept
    ? (focusConcept.description
        ?? descCache[focusConcept.id]
        ?? `${neighborCount} connected concepts · this is where your session is anchored on the course map.`)
    : `${courseConceptCount} concepts in this course · pick one to anchor your session.`;
}
