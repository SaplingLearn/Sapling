// Pure helpers behind FlashcardImportModal and its source tabs: defaults, the
// commit payload, the commit guard, row edits, and the words the modal renders.
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

/** "1 card" / "12 cards": the preview's count, and the tail of the commit label. */
export function cardCountLabel(n: number): string {
  return `${n} ${cardsNoun(n)}`;
}

export function commitLabel(committing: boolean, cardCount: number): string {
  return committing ? "Importing…" : `Import ${cardCountLabel(cardCount)}`;
}

/** Rows that will not be imported as they stand. */
export function flaggedCountOf(cards: ParsedCard[]): number {
  return cards.length - validCardsOf(cards).length;
}

export function flaggedLabel(n: number): string {
  return n === 1 ? "1 needs a look" : `${n} need a look`;
}

/** Why a row is flagged, or null for a row that will be imported. */
export function flagReason(card: ParsedCard): string | null {
  if (isValid(card)) return null;
  return card.error || "Term or definition is empty";
}

/** One edited row. A row with both sides filled in is no longer flagged. */
export function patchCard(cards: ParsedCard[], idx: number, patch: Partial<ParsedCard>): ParsedCard[] {
  const next = [...cards];
  const merged = { ...next[idx], ...patch };
  if (merged.front && merged.back) merged.error = undefined;
  next[idx] = merged;
  return next;
}

export function removeCard(cards: ParsedCard[], idx: number): ParsedCard[] {
  return cards.filter((_, i) => i !== idx);
}

/** What "Clean up with AI" sends: every row with both sides filled in. */
export function cleanupPayload(cards: ParsedCard[]): ImportCard[] {
  return cards.filter(c => c.front && c.back).map(c => ({ front: c.front, back: c.back }));
}

/** Cards a server import step returned, renumbered from 1. */
export function numberedCards(cards: ImportCard[]): ParsedCard[] {
  return cards.map((c, i) => ({ front: c.front, back: c.back, row: i + 1 }));
}

export function importedMessage(res: { inserted: number; skipped_duplicates: number }): string {
  const skipNote = res.skipped_duplicates > 0
    ? ` ${res.skipped_duplicates} skipped (duplicates).`
    : "";
  return `Imported ${res.inserted} ${cardsNoun(res.inserted)}.${skipNote}`;
}

/** The course's short name as the page shows it: its code, else its name. */
export function courseLabelOf(courses: EnrolledCourse[], courseId: string): string | null {
  const course = courses.find(c => c.course_id === courseId);
  return course ? course.course_code || course.course_name : null;
}

/** The footer's one line: what Import will do, or what it is still waiting for. */
export function importSummary(cardCount: number, courseLabel: string | null, hasCourse: boolean, topic: string): string {
  if (cardCount === 0) return "Nothing to import yet";
  const cards = cardCountLabel(cardCount);
  if (!hasCourse) return `${cards} · pick a course to import`;
  const into = courseLabel ? `${cards} into ${courseLabel}` : cards;
  const name = topic.trim();
  return name ? `${into} · ${name}` : `${into} · add a topic to import`;
}

const TERM_SEPARATOR_WORDS: Record<string, string> = { "\t": "Tab", ",": "a comma", " - ": "a hyphen" };
const CARD_SEPARATOR_WORDS: Record<string, string> = { "\n": "Enter", "\n\n": "a blank line", ";": "a semicolon" };

function separatorWords(words: Record<string, string>, choice: string, custom: string): string {
  if (choice !== "custom") return words[choice] ?? choice;
  return custom ? `“${custom}”` : "your separator";
}

/** A separator pick in the Paste tab: an option value, or "custom" plus its text. */
export interface SeparatorChoice { choice: string; custom: string }

/** The Paste textarea's hint, following the separators currently chosen. */
export function pastePlaceholder(term: SeparatorChoice, card: SeparatorChoice): string {
  const between = separatorWords(TERM_SEPARATOR_WORDS, term.choice, term.custom);
  const after = separatorWords(CARD_SEPARATOR_WORDS, card.choice, card.custom);
  return `Paste your cards here. Use ${between} between term and definition, ${after} between cards.`;
}
