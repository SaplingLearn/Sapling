// Pure helpers behind FlashcardImportModal: defaults, the commit payload,
// the commit guard, and the labels/styles the modal renders.
import type React from "react";
import type { EnrolledCourse, ImportCard } from "@/lib/api";
import { isValid, type ParsedCard } from "@/lib/flashcardParsers";

/** The course a fresh session starts on: the caller's default, else the first course. */
export function initialCourseId(defaultCourseId: string | undefined, courses: EnrolledCourse[]): string {
  return defaultCourseId ?? courses[0]?.course_id ?? "";
}

export function validCardsOf(cards: ParsedCard[]): ParsedCard[] {
  return cards.filter(isValid);
}

/** Front/back pairs to import; with `reverse`, each card is followed by its flip. */
export function buildFinalCards(validCards: ParsedCard[], reverse: boolean): ImportCard[] {
  const base = validCards.map(c => ({ front: c.front, back: c.back }));
  if (!reverse) return base;
  return base.flatMap(c => [c, { front: c.back, back: c.front }]);
}

/** The warning that blocks a commit, or null when it may proceed. */
export function commitBlocker(courseId: string, topic: string, cardCount: number): string | null {
  if (!courseId) return "Pick a course first.";
  if (!topic.trim()) return "Add a topic name.";
  if (cardCount === 0) return "No valid cards to import.";
  return null;
}

export function isCommitDisabled(committing: boolean, cardCount: number, courseId: string, topic: string): boolean {
  return committing || cardCount === 0 || !courseId || !topic.trim();
}

function cardsNoun(n: number): string {
  return `card${n === 1 ? "" : "s"}`;
}

export function commitLabel(committing: boolean, cardCount: number): string {
  return committing ? "Importing…" : `Import ${cardCount} ${cardsNoun(cardCount)}`;
}

export function importedMessage(res: { inserted: number; skipped_duplicates: number }): string {
  const skipNote = res.skipped_duplicates > 0
    ? ` ${res.skipped_duplicates} skipped (duplicates).`
    : "";
  return `Imported ${res.inserted} ${cardsNoun(res.inserted)}.${skipNote}`;
}

export function courseOptions(courses: EnrolledCourse[]) {
  return courses.map(c => ({
    value: c.course_id,
    label: c.course_code || c.course_name,
    description: c.course_code ? c.course_name : undefined,
  }));
}

export function tabButtonStyle(active: boolean): React.CSSProperties {
  return {
    padding: "8px 14px", fontSize: 13, fontWeight: active ? 600 : 500,
    color: active ? "var(--accent)" : "var(--text-dim)",
    background: "transparent",
    borderBottom: active ? "2px solid var(--accent)" : "2px solid transparent",
  };
}
