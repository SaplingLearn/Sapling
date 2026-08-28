/**
 * The quiz client — thin `fetchJSON` wrappers over the quiz endpoints
 * (`backend/routes/quiz.py`, mounted at `/api/quiz`).
 *
 * Three of them had no frontend caller at all before #537: `GET /attempts`,
 * `GET /attempts/{id}` and `POST /attempts/{id}/answer` (R1 §H). They are what
 * make resume, history and server-side grading possible, so the quiz leans on
 * all three. `POST /attempts/{id}/abandon` is newer still — it is what closed
 * gap G4, and it is the reason Discard survives a reload.
 *
 * This is the only quiz client. `lib/api.ts` carries the shared `fetchJSON` and
 * the non-quiz routes; its own quiz wrappers went with `QuizPanel`.
 */

import { fetchJSON, describeConcept as describeConceptRaw } from "@/lib/api";
import type {
  AbandonResult,
  AnswerResult,
  AttemptDetail,
  AttemptsPage,
  GenerateResult,
  QuizConfig,
  SubmitResult,
} from "./types";

/** `GET /api/quiz/config` — unauthenticated; the ONLY source of count/difficulty
 *  option lists. Never enumerate those values in client code. */
export const fetchQuizConfig = (): Promise<QuizConfig> =>
  fetchJSON<QuizConfig>("/api/quiz/config");

/**
 * `POST /api/quiz/generate`.
 *
 * `include_answer_key: false` is no longer load-bearing: #546 flipped the
 * server default to `false`, so omitting it would get the same keyless
 * response (no per-option `correct` booleans, no explanations — the shape
 * that makes client-side grading impossible and forces every verdict through
 * `answerQuestion`, where the server grades, per R-2).
 *
 * It stays on the wire anyway, for two reasons: it states the contract this
 * client is written against rather than inheriting whatever the default
 * happens to be, and the backend counts callers that OMIT the flag as
 * flag-unaware stragglers (`quiz.answer_key_flag_omitted`) while it decides
 * whether the parameter can be deleted. Dropping it here would put this
 * client in that count and muddy the signal. Delete this line when the
 * parameter goes (#546).
 *
 * `use_shared_context` and `model_pref` are left at their server defaults —
 * the redesign has no surface for either.
 *
 * `sourceAttemptId` is the client half of G5, "practise the ones you missed":
 * name the attempt and the server re-serves the items that were actually
 * missed, verbatim, generating only what it cannot recover. We deliberately
 * do NOT send question hashes — they are internal and stripped from every
 * response — so the server derives the misses from that attempt's own
 * recorded answers. The response's `source` block says what it did.
 */
export const generateQuiz = (p: {
  userId: string;
  conceptNodeId: string;
  numQuestions: number;
  difficulty: string;
  sourceAttemptId?: string | null;
}): Promise<GenerateResult> =>
  fetchJSON<GenerateResult>("/api/quiz/generate", {
    method: "POST",
    body: JSON.stringify({
      user_id: p.userId,
      concept_node_id: p.conceptNodeId,
      num_questions: p.numQuestions,
      difficulty: p.difficulty,
      include_answer_key: false,
      // Omitted rather than sent as null: every other generate is an ordinary
      // one, and the route's response only carries `source` when asked.
      ...(p.sourceAttemptId ? { source_attempt_id: p.sourceAttemptId } : {}),
    }),
  });

/**
 * `POST /api/quiz/attempts/{id}/answer` — the server-side grader. Idempotent on
 * `(attempt_id, question_index)`: replaying an answer returns the FIRST recorded
 * response with `recorded: false` rather than revising it.
 *
 * `time_ms` and `confidence` are accepted by the route and stored, but nothing
 * ever reads them back and the redesign surfaces neither, so they are
 * deliberately omitted rather than sent as junk.
 * TODO(#537-followup: per-question timing) — send them once something displays
 * them (gap G10).
 */
export const answerQuestion = (
  attemptId: string,
  p: { questionIndex: number; selectedIndex: number; questionId: number },
): Promise<AnswerResult> =>
  fetchJSON<AnswerResult>(`/api/quiz/attempts/${encodeURIComponent(attemptId)}/answer`, {
    method: "POST",
    body: JSON.stringify({
      question_index: p.questionIndex,
      selected_index: p.selectedIndex,
      question_id: p.questionId,
    }),
  });

/**
 * `POST /api/quiz/submit` — the only call that scores the attempt, moves
 * mastery and pays XP. Per-question `/answer` calls do NOT complete an attempt
 * (gap G7), so this is always called at the end.
 *
 * `answers` is belt-and-braces: the route reconciles against `quiz_responses`
 * and a recorded row always wins, so `[]` scores correctly when every question
 * went through `/answer`. We still send the local answers — they cover the
 * questions whose `/answer` call was lost.
 */
export const submitQuiz = (
  attemptId: string,
  answers: { question_id: number; selected_label: string }[],
): Promise<SubmitResult> =>
  fetchJSON<SubmitResult>("/api/quiz/submit", {
    method: "POST",
    body: JSON.stringify({ quiz_id: attemptId, answers }),
  });

/**
 * `POST /api/quiz/attempts/{id}/abandon` — the real Discard (G4; why the route
 * exists is told once, in `backend/routes/quiz.py::abandon_attempt`).
 *
 * Stamps `abandoned_at`, so the listing's derived status flips to `abandoned`
 * and `getAttempt` starts answering `resumable: false` — no reload and no
 * other device offers the attempt again.
 *
 * Idempotent (a repeat is a 200 no-op); 409 on an attempt that was already
 * submitted, since there is nothing there to discard; 404 once the row is gone.
 */
export const abandonAttempt = (attemptId: string): Promise<AbandonResult> =>
  fetchJSON<AbandonResult>(
    `/api/quiz/attempts/${encodeURIComponent(attemptId)}/abandon`,
    { method: "POST" },
  );

/** `GET /api/quiz/attempts` — paginated, user-scoped, newest first. There is no
 *  concept/status filter param (gap G2/G3); filter the page client-side. */
export const listAttempts = (
  userId: string,
  p: { limit?: number; offset?: number } = {},
): Promise<AttemptsPage> => {
  const params = new URLSearchParams({ user_id: userId });
  if (p.limit !== undefined) params.set("limit", String(p.limit));
  if (p.offset !== undefined) params.set("offset", String(p.offset));
  return fetchJSON<AttemptsPage>(`/api/quiz/attempts?${params.toString()}`);
};

/** `GET /api/quiz/attempts/{id}` — resume. A completed or abandoned attempt
 *  answers 200 with `resumable: false` and `questions: []`, so this is not a
 *  results-review endpoint (gap G5). */
export const getAttempt = (attemptId: string): Promise<AttemptDetail> =>
  fetchJSON<AttemptDetail>(`/api/quiz/attempts/${encodeURIComponent(attemptId)}`);

/**
 * `POST /api/graph/{user}/concept-description` — one LLM call for one concept.
 *
 * Reuses the client Learn's focus card already uses (`lib/api.ts::describeConcept`).
 * The second argument the route takes is a human course *label*, not a course id
 * — `build_message` hands the concept name and that label straight to the agent
 * (routes/graph.py:145-190). Called for the primary proposal only (R-8); the
 * callers fall back to a built sentence on failure rather than blocking.
 */
export const describeConcept = (
  userId: string,
  conceptName: string,
  courseLabel?: string,
): Promise<string> =>
  describeConceptRaw(userId, conceptName, courseLabel).then(r => r.description);
