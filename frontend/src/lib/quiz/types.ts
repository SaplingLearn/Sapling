/**
 * The shared vocabulary of the quiz redesign (#537) — §2 of
 * `docs/superpowers/specs/2026-08-22-quiz-frontend-contract.md`.
 *
 * Wire shapes here mirror what `backend/routes/quiz.py` actually returns; they
 * are NOT aspirational. Anything the backend does not send (feedback mode, the
 * session/scope model, the phase machine) is marked as a client concept.
 */

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

/**
 * G5: how a "practise the ones you missed" generate was actually assembled.
 *
 * Present only when the request named a `source_attempt_id`, and then always —
 * so the three outcomes stay distinguishable: re-served everything
 * (`regenerated_count === 0`), re-served some, re-served nothing and fell back
 * to generation (`reserved_count === 0`). The results screen labels each
 * honestly instead of promising "the ones you missed" for a quiz that wrote
 * new questions.
 */
export interface GenerateSource {
  attempt_id: string;
  reserved_count: number;
  regenerated_count: number;
}

export interface GenerateResult {
  quiz_id: string;
  questions: WireQuestion[];
  requested_difficulty: string;
  resolved_difficulty: string;
  requested_count: number;
  delivered_count: number;
  source?: GenerateSource;
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
  /** G5: the completed attempt whose misses this session is practising, set by
   *  `PRACTISE_MISSED` and sent on the next generate. `null` for every other
   *  way into a quiz. */
  sourceAttemptId: string | null;
  /** G5: what that generate re-served versus regenerated. `null` unless the
   *  request named a source attempt — which is exactly when the results
   *  eyebrow may claim "the ones you missed, again". */
  reserved: { reservedCount: number; regeneratedCount: number } | null;
}
