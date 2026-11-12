/**
 * Saved flashcard sets: a named selection of a course's concepts plus a couple
 * of study options (the Flashcards home screen's shelf).
 *
 * A set owns no cards. It stores concept NAMES; the page matches cards to
 * them by topic, so a set keeps working as cards are added and removed.
 *
 * Limits are enforced by the server (name 1-80 characters, 1-100 concepts,
 * `SET_NAME_MAX` / `SET_CONCEPTS_MAX` below); a rejected write throws the
 * `ApiError` `fetchJSON` builds, for the caller to surface.
 */
import { fetchJSON } from "@/lib/api";

/** The server's limits on a saved set (backend/services/flashcards/sets.py:
 *  NAME_MAX, CONCEPTS_MAX). The page holds a set to them before it is sent. */
export const SET_NAME_MAX = 80;
export const SET_CONCEPTS_MAX = 100;

export interface FlashcardSetOptions {
  only_due: boolean;
  shuffle: boolean;
}

export interface FlashcardSet {
  id: string;
  name: string;
  course_id: string;
  /** Concept names, as they were when the set was saved. */
  concepts: string[];
  options: FlashcardSetOptions;
  /** The exam the set was made for, when it came from an exam's quick pick. */
  exam_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface NewFlashcardSet {
  name: string;
  course_id: string;
  concepts: string[];
  options?: FlashcardSetOptions;
  exam_id?: string | null;
}

export type FlashcardSetPatch = Partial<Pick<NewFlashcardSet, "name" | "concepts" | "options" | "exam_id">>;

const BASE = "/api/flashcards/sets";

export const listFlashcardSets = (userId: string, courseId: string) =>
  fetchJSON<{ sets: FlashcardSet[] }>(
    `${BASE}/${encodeURIComponent(userId)}?course_id=${encodeURIComponent(courseId)}`,
  );

export const createFlashcardSet = (userId: string, set: NewFlashcardSet) =>
  fetchJSON<{ set: FlashcardSet }>(BASE, {
    method: "POST",
    body: JSON.stringify({ user_id: userId, ...set }),
  });

export const updateFlashcardSet = (userId: string, setId: string, patch: FlashcardSetPatch) =>
  fetchJSON<{ set: FlashcardSet }>(`${BASE}/${encodeURIComponent(setId)}`, {
    method: "PATCH",
    body: JSON.stringify({ user_id: userId, ...patch }),
  });

export const deleteFlashcardSet = (userId: string, setId: string) =>
  fetchJSON<{ deleted: boolean }>(
    `${BASE}/${encodeURIComponent(setId)}?user_id=${encodeURIComponent(userId)}`,
    { method: "DELETE" },
  );

// ── describe a set ───────────────────────────────────────────────────────────

/** The longest description the server takes (and the shortest is 3). */
export const SUGGEST_MIN = 3;
export const SUGGEST_MAX = 300;

export interface SuggestedConcept {
  name: string;
  course_id: string | null;
  /** "named": the description names it; "model": a model judged it fits. */
  source: "named" | "model";
  confidence: number;
}

export interface FlashcardSetSuggestion {
  /** A name for the set, from the description. */
  name: string;
  concepts: SuggestedConcept[];
  /** How many of the course's concepts were weighed. */
  considered: number;
  backend: "jev" | "flash_lite" | "function" | "none" | "mixed";
}

/**
 * The concepts a described set should hold ("pointers and recursion for the
 * midterm"). A suggestion only: nothing is saved. 422 when the description is
 * under 3 or over 300 characters; 429 past 10 asks a minute.
 */
export const suggestFlashcardSet = (userId: string, description: string, courseId: string) =>
  fetchJSON<FlashcardSetSuggestion>(`${BASE}/suggest`, {
    method: "POST",
    body: JSON.stringify({ user_id: userId, description, course_id: courseId }),
  });
