/**
 * The daily review queue's wire types (learning loop PKG-12:
 * backend/routes/learn_loop.py /review/*). The clients are lib/api.ts's
 * getReviewNext / answerReview / getReviewSummary, and lib/api.ts re-exports
 * these, so callers import them from "@/lib/api" as before. Kept in their own
 * file so the review contract can grow without pushing lib/api.ts past its
 * size ceiling (max-lines-baseline.json).
 */
import type { WithCrisisSupport } from '@/lib/crisisSupport';
import type { StudentConfidence } from '@/lib/api';

export interface ReviewSr {
  stage: 'acquire' | 'relearn' | 'done';
  correct: number;
  target: number;
}
export interface ReviewItemPayload {
  kind: 'flashcard' | 'check';
  id: string;
  cost_s: number;
  sr: ReviewSr;
  // check items
  node_id?: string | null;
  concept_name?: string | null;
  format?: 'free' | 'mc_reason' | null;
  difficulty?: number | null;
  prompt?: string | null;
  // mc_reason only: the stored options in stored order; correctness is never marked (A22)
  options?: { letter: string; text: string }[] | null;
  // flashcards
  topic?: string | null;
  front?: string | null;
  back?: string | null;
  /** #866 K14: a card never rated yet (A74's pool) — a new card, not a due review. */
  new?: boolean;
}
export interface ReviewNextResponse {
  item: ReviewItemPayload | null;
  remaining_budget_s: number;
  session_id: string;
  retention_target: number;
  // everything due today; in_budget = what today's remaining budget covers. A null
  // item with due_total > 0 means the budget is spent, not that nothing is due.
  due_total: number;
  /** #866 K14: the never-rated cards among `due_total` (new cards, not due reviews). */
  new_total?: number;
  in_budget: number;
}
export interface ReviewAnswerBody {
  user_id: string;
  session_id: string;
  course_id?: string;
  kind: 'flashcard' | 'check';
  item_id: string;
  answer?: string;
  selected_option?: string;
  reason?: string;
  rating?: number;
  /** Spec §13 A127: a check's stated confidence, only when chosen (never a flashcard's). */
  confidence?: StudentConfidence;
}
export interface ReviewAnswerResponse extends WithCrisisSupport {
  correct: boolean | null;
  hint: string | null;
  next_due_at: string | null;
  rating: number | null;
  remaining_budget_s: number;
  sr: ReviewSr | Record<string, never>;
  unavailable: boolean;
  // A33: the answer read as instructions to the grader — ask for it in the
  // student's own words (nothing was recorded; the item stays answerable)
  refused: boolean;
}
export interface ReviewSummaryResponse {
  due: { flashcard: number; check: number };
  /** #866 K14: the never-rated cards among `due.flashcard`. */
  new?: number;
  in_budget: number;
  unservable: number;
  /** Novice concepts held back at the tutor hard level (A20). */
  paused: number;
  /** #866 K18: the cap that holds them (`monthly_usd`, `daily_usd`, …) and when it
   *  lifts; null when nothing is paused. Absent from a server before the fix. */
  paused_scope?: string | null;
  paused_until?: string | null;
  budget_min: number;
  remaining_budget_s: number;
  retention_target: number;
}
