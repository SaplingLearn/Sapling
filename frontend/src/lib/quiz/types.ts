/**
 * The shared vocabulary of the quiz redesign (#537) — §2 of
 * `docs/superpowers/specs/2026-08-22-quiz-frontend-contract.md`.
 *
 * Wire shapes here mirror what `backend/routes/quiz.py` actually returns; they
 * are NOT aspirational. Anything the backend does not send (feedback mode, the
 * session/scope model, the phase machine) is marked as a client concept.
 */

import type { GamificationMe } from "@/lib/types";
import type { QuizError } from "./errors";

/** `GET /api/quiz/config` — the ONLY source of option lists (never enumerate
 *  counts or difficulties in code; `services/quiz_config.py::quiz_config_payload`). */
export interface QuizConfig {
  num_questions: { min: number; max: number; options: number[] };
  difficulties: string[];
  question_types: string[];
}

/** Client concept (R-2): the backend records every answer as it happens; this
 *  only decides when the verdict is shown. There is no `/config` list for it. */
export type FeedbackMode = "as-you-go" | "at-end";

/** Persisted under `sapling_quiz_prefs`. `null` means "no stored preference —
 *  fall back to the config-derived default". */
export interface QuizPrefs {
  count: number | null;
  difficulty: string | null;
  feedback: FeedbackMode;
}

/** An answer option as the keyless projection sends it (`include_answer_key: false`
 *  strips `correct`; quiz.py::_strip_answer_key). */
export interface WireOption {
  label: string;
  text: string;
}

export interface WireQuestion {
  id: number;
  question: string;
  options: WireOption[];
  concept_tested?: string;
  difficulty: string;
}

export interface GenerateResult {
  quiz_id: string;
  questions: WireQuestion[];
  requested_difficulty: string;
  resolved_difficulty: string;
  requested_count: number;
  delivered_count: number;
}

export interface AnswerResult {
  question_index: number;
  question_id: number;
  is_correct: boolean;
  /** -1 for a malformed item with no correct option (quiz.py:1637-1647). */
  correct_index: number;
  explanation: string;
  next_question: WireQuestion | null;
  /** false = idempotent replay or a lost race; the answer still stands. */
  recorded: boolean;
}

/** What the `quiz_completed` award paid. Free to send — the server already
 *  holds all three — and none of them is reconstructable client-side.
 *
 *  All three are `null` TOGETHER when the XP write failed and the server
 *  swallowed it (XP must never fail the submit that earned it). That is the
 *  signal to omit the XP line, not to render a zero: `xp_awarded: 0` is a
 *  real, different answer, reachable three ways — a disabled rule, a
 *  zero-amount rule, and an idempotent replay — and `duplicate` is what tells
 *  the replay apart from a misconfigured rule. */
export interface SubmitAward {
  /** The amount written to the `xp_events` ledger by this submit. */
  xp_awarded: number | null;
  /** Whether this award crossed a level boundary. Without it, a migrated
   *  client cannot detect a level-up except by re-adding the `/me` round trip
   *  this whole block exists to remove. */
  leveled_up: boolean | null;
  /** True when the ledger already had this award (a retried submit). */
  duplicate: boolean | null;
}

/** G8: the XP line, inline in the submit reply — what the award paid plus the
 *  same `GET /api/gamification/me` snapshot, taken right after it (both built
 *  by `backend/services/gamification_service.py`, so they cannot disagree).
 *
 *  The two halves fail independently, and neither ever invents a number. If
 *  the SNAPSHOT read fails the block carries the award half ALONE — the card
 *  fields are absent, not zeroed. Narrow on a card field before reading one:
 *
 *      if (g && g.total_xp !== undefined) { ...render the card... }
 *
 *  The award half survives that failure on purpose: it cost no query, and the
 *  `/me` fallback that would otherwise supply it is aimed at the same database
 *  that just failed.
 *
 *  READ THIS BEFORE MIGRATING OFF `useGamificationDelta` (R-9a).
 *  `xp_awarded` is the `quiz_completed` ledger amount — NOT the student's
 *  total XP change across the submit. A badge earned by the same quiz pays
 *  its own `xp_reward`, which lands in `total_xp` here but not in
 *  `xp_awarded`. Today's line renders `after - before` from two `/me` reads
 *  and therefore INCLUDES that badge XP; a client that drops the pre-session
 *  read and renders `xp_awarded` will show the smaller number on those
 *  submits. Deliberate — the ledger amount is the one value the server can
 *  name without guessing. If the badge delta must survive the migration, the
 *  server needs an `xp_before` field; that call has not been made. */
export type SubmitGamification =
  | (SubmitAward & GamificationMe)
  | (SubmitAward & { [K in keyof GamificationMe]?: undefined });

export interface SubmitResult {
  score: number;
  total: number;
  mastery_before: number;
  mastery_after: number;
  results: {
    question_id: string;
    selected: string;
    correct: boolean;
    correct_answer: string;
    explanation: string;
  }[];
  /** Optional while `useGamificationDelta` still reads `/me` around the
   *  submit (R-9); the client migration to this field is a later pass. */
  gamification?: SubmitGamification | null;
}

export type AttemptStatus = "completed" | "abandoned" | "in_progress";

export interface AttemptSummary {
  quiz_id: string;
  status: AttemptStatus;
  concept_node_id: string;
  concept_name: string;
  course_id: string | null;
  score: number | null;
  total: number | null;
  difficulty: string;
  mastery_before: number | null;
  mastery_after: number | null;
  mastery_delta: number | null;
  created_at: string;
  completed_at: string | null;
}

export interface AttemptsPage {
  total: number;
  limit: number;
  offset: number;
  attempts: AttemptSummary[];
}

export interface AttemptDetail {
  quiz_id: string;
  status: AttemptStatus;
  resumable: boolean;
  difficulty: string;
  concept_node_id: string;
  /** Always keyless; `[]` once the attempt is no longer resumable. */
  questions: WireQuestion[];
  responses: {
    question_index: number;
    selected_index: number;
    is_correct: boolean;
    answered_at: string;
  }[];
  score: number | null;
  total: number | null;
  created_at: string;
}

/**
 * `POST /api/quiz/attempts/{id}/abandon` (G4). Idempotent: a second call
 * answers with the stamp already on the row rather than re-writing it.
 *
 * `status` is DERIVED server-side from the timestamps, exactly as the read
 * paths derive it, and `abandoned_at` is nullable for the same reason: the
 * route reports the state it actually observed. It never substitutes its own
 * clock for a write it did not make, so a claim it lost to a concurrent
 * writer that then left the row open reads back `in_progress` / `null`
 * instead of a fabricated success. Read `status`, not the timestamp.
 */
export interface AbandonResult {
  quiz_id: string;
  status: AttemptStatus;
  abandoned_at: string | null;
}

export type SourceKind = "tree" | "dashboard" | "notes" | "nav" | "link" | "quiz";

export interface QuizSource {
  kind: SourceKind;
  returnTo?: string;
  conceptId?: string;
  noteId?: string;
}

export type QuizIntent = "practice" | "review";

/** Multi-concept scopes run as a queue of single-concept attempts (R-4):
 *  `/generate` is per `concept_node_id`, so a course/due session is a queue. */
export type QuizScope =
  | { kind: "concept"; conceptId: string }
  | { kind: "course"; courseId: string; queue: string[] }
  | { kind: "due"; queue: string[] }
  | { kind: "missed"; conceptId: string; missedCount: number };

export interface QuizItem {
  index: number;
  question: WireQuestion;
  selectedIndex: number | null;
  verdict: { isCorrect: boolean; correctIndex: number; explanation: string } | null;
  flagged: boolean;
}

export type Phase =
  | "home"
  | "configuring"
  | "generating"
  | "active"
  | "answered"
  | "confirm-leave"
  | "submitting"
  | "results"
  | "paused"
  | "error";

export interface QuizSession {
  intent: QuizIntent;
  scope: QuizScope;
  source: QuizSource;
  config: { count: number; difficulty: string; feedback: FeedbackMode };
  conceptId: string;
  courseId: string | null;
  attemptId: string | null;
  items: QuizItem[];
  /** Index of the current item. */
  cursor: number;
  /** Position in `scope.queue` (0 for concept/missed scopes). */
  queueIndex: number;
  phase: Phase;
  error: QuizError | null;
  result: SubmitResult | null;
  xp: { before: number; after: number; streak: number } | null;
  /** `delivered_count < requested_count` on the generate that produced `items`. */
  deliveredShort: boolean;
}
