/**
 * Shared plumbing for the #537 D3 lanes (`quiz-integration.spec.ts`,
 * `quiz-errors.spec.ts`).
 *
 * Deliberately NOT `support/quiz.ts` — that file belongs to the D2 journeys and
 * two agents editing one helper module is a merge conflict on every run. The
 * overlap is a five-line sign-in-adjacent init script; duplicating it is
 * cheaper than sharing it.
 *
 * Everything here is either a constant pinned to a backend fixture (and marked
 * KEEP IN SYNC) or a wait-free interaction helper. No bare sleeps: every wait
 * below is a locator or an `expect.poll`.
 */
import { expect, type Page } from "@playwright/test";

// ── Seeded fixtures (db/seed_local_rich.py) ────────────────────────────────

/** "Recursion" on CS101 for rich-user-active — seeded at mastery 0.25 with one
 *  completed baseline attempt (`rich-qa-cs-recursion-1`, 6/10). */
export const NODE_RECURSION = "rich-node-cs-recursion";
export const NODE_RECURSION_NAME = "Recursion";
export const SEEDED_RECURSION_MASTERY = 0.25;
/** The seeded attempt already on that node — the Recent-quizzes baseline. */
export const SEEDED_RECURSION_ATTEMPT = "rich-qa-cs-recursion-1";

/** "DNA Replication" on BIO110 — enrolled ONLY in Fall 2025, which makes it the
 *  out-of-scope deep-link target when the active semester is Spring 2026. */
export const NODE_BIO_DNA = "rich-node-bio-dna";
export const NODE_BIO_DNA_NAME = "DNA Replication";

export const NOTE_CS_WEEK1 = "rich-note-cs-week1";
export const NOTE_CS_WEEK1_TITLE = "Week 1 — Variables";

export const COURSE_CS = "rich-course-cs101";

// ── Function-mode fixtures (backend/agents/function_handlers_e2e.py) ───────

/** `E2E_QUIZ_CORRECT_LABELS` — correct options at indexes 1, 2, 0. KEEP IN SYNC
 *  with the handler module and `backend/tests/test_e2e_function_handlers.py`. */
export const CORRECT_LABELS = ["B", "C", "A"] as const;
/** The scripted quiz is always three questions, whatever `num_questions` asked
 *  for (the handler says so explicitly). Requesting 3 keeps `delivered_count ===
 *  requested_count`, so the "only N were ready" toast stays out of the way of
 *  journeys that are not about it. */
export const SCRIPTED_QUESTION_COUNT = 3;
/** Stem prefix of the scripted questions — the loud guard that the stack really
 *  booted with SAPLING_MODEL_MODE=function. */
export const scriptedStem = (n: number) => `E2E deterministic question ${n}`;

/** Must match `E2E_TUTOR_REPLY`. */
export const TUTOR_REPLY =
  "[e2e-function-model] Deterministic tutor reply: every recursive function " +
  "needs a base case so it can stop calling itself.";

// ── Browser priming ────────────────────────────────────────────────────────

export interface PrimeOptions {
  /** `sapling_quiz_prefs.feedback`. Defaults to the app default, "at-end". */
  feedback?: "as-you-go" | "at-end";
  /** `sapling_quiz_prefs.count`. Defaults to the scripted question count. */
  count?: number;
  /** `sapling_active_semester` — the empty string is "All semesters" (#360).
   *  Omit to leave the key unwritten, which is also All semesters. */
  semester?: string;
}

/**
 * The state a returning student's browser is in before a quiz journey starts.
 *
 * Three localStorage keys, all of them app contracts rather than test hooks:
 *   - `sapling_disclaimer_ack` — the AI-disclosure modal (DisclaimerModal.tsx)
 *     is a fixed overlay that swallows every click on /quiz for a browser that
 *     has never acknowledged it. It is unrelated chrome for these journeys.
 *   - `sapling_quiz_prefs` (`lib/quiz/session.ts::PREFS_KEY`) — pins length and
 *     feedback mode so the journeys don't depend on `/api/quiz/config`'s
 *     default landing on a particular number.
 *   - `sapling_active_semester` (`lib/useActiveSemester.ts`) — the same key the
 *     Courses & Semesters hub writes (semester-scope.spec.ts drives that hub;
 *     here the scope IS the fixture, not the thing under test).
 */
export async function primeQuizBrowser(page: Page, opts: PrimeOptions = {}): Promise<void> {
  const payload = {
    prefs: JSON.stringify({
      count: opts.count ?? SCRIPTED_QUESTION_COUNT,
      difficulty: "medium",
      feedback: opts.feedback ?? "at-end",
    }),
    semester: opts.semester ?? null,
  };
  await page.addInitScript(
    ({ prefs, semester }: { prefs: string; semester: string | null }) => {
      window.localStorage.setItem("sapling_disclaimer_ack", "true");
      window.localStorage.setItem("sapling_quiz_prefs", prefs);
      if (semester !== null) {
        window.localStorage.setItem("sapling_active_semester", semester);
      }
    },
    payload,
  );
}

// ── Driving a quiz ─────────────────────────────────────────────────────────

/**
 * Click one answer row and prove it took.
 *
 * `AnswerOption` maps `disabled` to `aria-disabled` only — the DOM button stays
 * enabled and focusable by design (a revealed row must remain readable), so
 * Playwright's actionability check will NOT wait out the in-flight `/answer`
 * that makes the row inert. The retry block is that missing wait: click, verify
 * `aria-checked`, and try again if the press landed inside the dead window.
 */
export async function chooseOption(page: Page, label: string): Promise<void> {
  const option = page.getByTestId(`quiz-answer-option-${label}`);
  await expect(async () => {
    await option.click();
    await expect(option).toHaveAttribute("aria-checked", "true", { timeout: 1_000 });
  }).toPass({ timeout: 20_000 });
}

/**
 * Answer the whole scripted quiz in "at the end" mode: no verdict is shown
 * between items, so the footer button stays "Submit" and the last press goes
 * straight to scoring.
 *
 * Each iteration gates on the stem of the question it is about to answer, which
 * is what makes the loop safe: the option testids are stable across items, so
 * without the gate a fast loop could press question 2's "B" while question 1 is
 * still on screen.
 */
export async function answerAtEnd(page: Page, labels: readonly string[]): Promise<void> {
  const panel = page.getByTestId("quiz-panel");
  for (let i = 0; i < labels.length; i++) {
    await expect(panel).toContainText(scriptedStem(i + 1), { timeout: 30_000 });
    await chooseOption(page, labels[i]);
    await page.getByTestId("quiz-submit-answer").click();
  }
}

/** The same walk in "as you go" mode: every answer reveals a verdict and the
 *  footer becomes Next / See results. */
export async function answerAsYouGo(page: Page, labels: readonly string[]): Promise<void> {
  const panel = page.getByTestId("quiz-panel");
  for (let i = 0; i < labels.length; i++) {
    await expect(panel).toContainText(scriptedStem(i + 1), { timeout: 30_000 });
    await chooseOption(page, labels[i]);
    await page.getByTestId("quiz-submit-answer").click();
    await expect(page.getByTestId("quiz-review-verdict")).not.toBeEmpty();
    await page.getByTestId("quiz-next").click();
  }
}

// ── Faked backend envelopes (quiz-errors.spec.ts) ──────────────────────────

/**
 * The exact body every `/api/quiz/*` failure carries
 * (`backend/services/quiz_errors.py::quiz_error_body`, applied by main.py's
 * three global handlers): a machine-readable `error` object, the legacy
 * top-level `detail`, and the request id in both places.
 *
 * `detail` mirrors `error.message` because `QuizAPIError` sets its HTTPException
 * detail to the student-readable sentence — a fake that disagreed with itself
 * would let a frontend regression that reads the wrong field pass.
 */
export function quizErrorBody(code: string, message: string, requestId: string) {
  return {
    error: { code, message, request_id: requestId },
    detail: message,
    request_id: requestId,
  };
}

export interface FulfillableError {
  status: number;
  contentType: string;
  headers?: Record<string, string>;
  body: string;
}

/** `quizErrorBody` packaged for `route.fulfill`. `retryAfterSec` adds the
 *  `Retry-After` header the 429 raise site sets (and the header the copy's
 *  "{n} seconds" is filled from). */
export function quizErrorFulfill(
  status: number,
  code: string,
  message: string,
  opts: { requestId?: string; retryAfterSec?: number } = {},
): FulfillableError {
  const requestId = opts.requestId ?? `e2e-${code.toLowerCase()}`;
  return {
    status,
    contentType: "application/json",
    ...(opts.retryAfterSec !== undefined
      ? { headers: { "Retry-After": String(opts.retryAfterSec) } }
      : {}),
    body: JSON.stringify(quizErrorBody(code, message, requestId)),
  };
}

/** A `GraphNode` shaped the way `GET /api/graph/{user}` returns them. */
export function fakeNode(
  id: string,
  name: string,
  mastery: number,
  tier: string,
  courseId: string,
): Record<string, unknown> {
  return {
    id,
    concept_name: name,
    mastery_score: mastery,
    mastery_tier: tier,
    times_studied: 3,
    last_studied_at: "2026-03-01T12:00:00Z",
    subject: "CS101",
    course_id: courseId,
    course_color: "#4f86f7",
    is_subject_root: false,
  };
}
