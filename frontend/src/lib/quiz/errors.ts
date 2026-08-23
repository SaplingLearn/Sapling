/**
 * The one place a thrown quiz request becomes something a student can read.
 *
 * The backend already ships a machine-readable envelope on every `/api/quiz/*`
 * path — `{error: {code, message, request_id}, detail, request_id}` plus a
 * `Retry-After` header on 429 (`backend/services/quiz_errors.py::quiz_error_body`,
 * applied by main.py's three global handlers). Until #537 the frontend threw all
 * of that away and rendered one generic sentence per status, so
 * `QUIZ_RATE_LIMITED`, `QUIZ_DAILY_LIMIT_REACHED` and `QUIZ_GENERATION_TIMEOUT`
 * were indistinguishable (R1 §H, gap G12).
 *
 * `lib/api.ts::fetchJSON` now parses the envelope onto `ApiError`; this module
 * turns that into `QuizError` — the shape the machine stores and the screens
 * render. Copy is the contract's §4 table, verbatim.
 */

import { ApiError } from "@/lib/api";

export type QuizErrorCode =
  | "QUIZ_DIFFICULTY_INVALID"
  | "QUIZ_QUESTION_INVALID"
  | "QUIZ_COUNT_OUT_OF_RANGE"
  | "QUIZ_VALIDATION_ERROR"
  | "QUIZ_NOT_AUTHORIZED"
  | "QUIZ_CONCEPT_NOT_FOUND"
  | "QUIZ_ATTEMPT_NOT_FOUND"
  | "QUIZ_ATTEMPT_ALREADY_COMPLETED"
  | "QUIZ_ATTEMPT_ABANDONED"
  | "QUIZ_ATTEMPT_NOT_RESUMABLE"
  | "QUIZ_RATE_LIMITED"
  | "QUIZ_DAILY_LIMIT_REACHED"
  | "QUIZ_GENERATION_TIMEOUT"
  | "QUIZ_GENERATION_FAILED"
  | "QUIZ_INTERNAL_ERROR"
  | "QUIZ_HTTP_ERROR"
  | "NETWORK"
  | "UNKNOWN";

export interface QuizError {
  code: QuizErrorCode;
  message: string;
  retryable: boolean;
  retryAfterSec?: number;
  requestId?: string;
}

const GENERIC_INVALID = "Something about this request wasn't valid. Reload and try again.";
const GENERIC_SERVER = "Something went wrong on our side. Try again in a moment.";

export const QUIZ_ERROR_COPY: Record<QuizErrorCode, string> = {
  // `{n}` is filled from `Retry-After`, else the default below.
  QUIZ_RATE_LIMITED: "You're quizzing fast — give it {n} seconds and try again.",
  QUIZ_DAILY_LIMIT_REACHED: "You've used today's quiz allowance. It resets tomorrow.",
  QUIZ_GENERATION_TIMEOUT:
    "Writing this quiz took too long. Try again — it usually works the second time.",
  QUIZ_GENERATION_FAILED:
    "We couldn't put a quiz together for this concept right now. Try again in a moment.",
  QUIZ_CONCEPT_NOT_FOUND: "That concept isn't on your tree any more. Pick another one.",
  QUIZ_ATTEMPT_NOT_FOUND: "We couldn't find that quiz. Start a new one.",
  QUIZ_ATTEMPT_ALREADY_COMPLETED: "This quiz was already scored. Your results are on your tree.",
  QUIZ_ATTEMPT_ABANDONED: "That quiz expired after a day. Start a fresh one.",
  QUIZ_ATTEMPT_NOT_RESUMABLE: "This quiz can't be resumed. Start a new one.",
  QUIZ_QUESTION_INVALID: "That answer didn't line up with the question. Reload and try again.",
  // The server sentence wins for this one — it carries the real bounds, and the
  // bounds live in `/api/quiz/config`, never in client code. This is only the
  // fallback for a body that arrived without a message.
  QUIZ_COUNT_OUT_OF_RANGE: "That quiz length isn't allowed. Pick a different number of questions.",
  QUIZ_DIFFICULTY_INVALID: GENERIC_INVALID,
  QUIZ_VALIDATION_ERROR: GENERIC_INVALID,
  QUIZ_NOT_AUTHORIZED: "Please sign in again to keep quizzing.",
  QUIZ_INTERNAL_ERROR: GENERIC_SERVER,
  QUIZ_HTTP_ERROR: GENERIC_SERVER,
  UNKNOWN: GENERIC_SERVER,
  NETWORK: "You look offline. Check your connection and try again.",
};

/** Every code, in declaration order — handy for exhaustiveness tests. */
export const QUIZ_ERROR_CODES = Object.keys(QUIZ_ERROR_COPY) as QuizErrorCode[];

const RETRYABLE: ReadonlySet<QuizErrorCode> = new Set<QuizErrorCode>([
  "QUIZ_RATE_LIMITED",
  "QUIZ_GENERATION_TIMEOUT",
  "QUIZ_GENERATION_FAILED",
  "QUIZ_INTERNAL_ERROR",
  "QUIZ_HTTP_ERROR",
  "UNKNOWN",
  "NETWORK",
]);

/** Used when a 429 arrives without a `Retry-After` header (an in-process rate
 *  limiter behind more than one worker can do that — R1 §D). */
const DEFAULT_RETRY_AFTER_SEC = 60;

function isQuizErrorCode(value: unknown): value is QuizErrorCode {
  return typeof value === "string" && value in QUIZ_ERROR_COPY;
}

/**
 * Status → code for responses that carry no `error.code`: everything off the
 * quiz router (graph, gamification), and any proxy/edge error in front of it.
 *
 * Deliberately conservative. An uncoded 404 becomes `QUIZ_HTTP_ERROR`, not
 * `QUIZ_ATTEMPT_NOT_FOUND` — R1 §D is explicit that `QUIZ_HTTP_ERROR` "must not
 * be read as a domain state", and inventing one from a bare status is exactly
 * that mistake in reverse.
 */
function codeForStatus(status: number | undefined): QuizErrorCode {
  if (status === undefined) return "UNKNOWN";
  if (status === 401 || status === 403) return "QUIZ_NOT_AUTHORIZED";
  if (status === 429) return "QUIZ_RATE_LIMITED";
  if (status >= 500) return "QUIZ_INTERNAL_ERROR";
  if (status >= 400) return "QUIZ_HTTP_ERROR";
  return "UNKNOWN";
}

const NETWORK_WORDING = /failed to fetch|networkerror|network request failed|load failed/i;

/** A transport failure never reached a server, so it has no status and no code.
 *  `fetch` rejects with a `TypeError` in every browser; the wording check is the
 *  safety net for the ones that wrap it. */
function isNetworkFailure(err: unknown): boolean {
  if (err instanceof ApiError) return false;
  if (err instanceof TypeError) return true;
  return err instanceof Error && NETWORK_WORDING.test(err.message);
}

/** The server's own sentence for this error, when the envelope carried one. */
function serverMessage(err: ApiError): string | undefined {
  const body = err.body;
  if (body === null || typeof body !== "object") return undefined;
  const error = (body as { error?: unknown }).error;
  if (error === null || typeof error !== "object") return undefined;
  const message = (error as { message?: unknown }).message;
  return typeof message === "string" && message.trim() ? message.trim() : undefined;
}

function copyFor(code: QuizErrorCode, err: ApiError | null, retryAfterSec?: number): string {
  if (code === "QUIZ_RATE_LIMITED") {
    return QUIZ_ERROR_COPY.QUIZ_RATE_LIMITED.replace(
      "{n}",
      String(retryAfterSec ?? DEFAULT_RETRY_AFTER_SEC),
    );
  }
  if (code === "QUIZ_COUNT_OUT_OF_RANGE") {
    // The 422 handler rewrites this message to name the real min/max
    // (main.py:227 → quiz_errors.validation_error_code), so it beats our copy.
    return (err && serverMessage(err)) ?? QUIZ_ERROR_COPY.QUIZ_COUNT_OUT_OF_RANGE;
  }
  return QUIZ_ERROR_COPY[code];
}

/**
 * Anything thrown by a quiz call → the error the UI renders.
 *
 * Never throws and never returns an empty message: an unrecognised rejection
 * degrades to `UNKNOWN` with the generic server sentence.
 */
export function describeQuizError(err: unknown): QuizError {
  if (isNetworkFailure(err)) {
    return { code: "NETWORK", message: QUIZ_ERROR_COPY.NETWORK, retryable: true };
  }

  if (err instanceof ApiError) {
    const code = isQuizErrorCode(err.code) ? err.code : codeForStatus(err.status);
    const out: QuizError = {
      code,
      message: copyFor(code, err, err.retryAfterSec),
      retryable: RETRYABLE.has(code),
    };
    if (err.retryAfterSec !== undefined) out.retryAfterSec = err.retryAfterSec;
    if (err.requestId !== undefined) out.requestId = err.requestId;
    return out;
  }

  return { code: "UNKNOWN", message: QUIZ_ERROR_COPY.UNKNOWN, retryable: true };
}
