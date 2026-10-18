/**
 * Shared steps and constants for the quiz journeys (#537 D2).
 *
 * Two specs drive the redesigned quiz — `quiz.spec.ts` (the four backend
 * contracts the pre-#537 journey pinned) and `quiz-journeys.spec.ts` (the
 * behaviours the redesign added). Everything they agree on lives here: the
 * seeded fixture's identifiers, the deterministic quiz's own copy, and the
 * handful of multi-step gestures both need (sign in with the disclaimer already
 * acknowledged, walk a question, tab to a control).
 *
 * DETERMINISM. The stack boots with `SAPLING_MODEL_MODE=function` and
 * `SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e` (#391/#392,
 * ADR 0019), so `/api/quiz/generate` runs the real quiz agent against the
 * scripted handler in `backend/agents/function_handlers_e2e.py`: a fixed
 * three-question quiz whose correct labels are B, C, A
 * (`E2E_QUIZ_CORRECT_LABELS`), with derived stems, option texts and
 * explanations. Every literal below is a transcription of that module —
 * `backend/tests/test_e2e_function_handlers.py` pins the Python side.
 * KEEP THE THREE IN SYNC.
 *
 * Anchoring follows docs/frontend-testids.md's `quiz` section: testids for
 * controls, visible copy for the sentences the screens promise. The one
 * exception is `ProgressDots`, whose individual dots carry no testid — the
 * rail's state is read off `.progress-dots__dot--{kind}`, which contract §3
 * declares to be that primitive's public CSS API.
 */
import { expect, type Page } from "@playwright/test";

import { queryRaw } from "./db";

// ── The seeded concept every journey quizzes ──────────────────────────────
//
// db/seed_local_rich.py: "Recursion" for rich-user-active on CS101, seeded at
// mastery 0.25 (tier "struggling") with NO seeded mastery events, so the
// baseline event count is exactly zero after the per-test reset.
export const NODE_ID = "rich-node-cs-recursion";
export const CONCEPT_NAME = "Recursion";
export const SEEDED_MASTERY = 0.25;

/** The abstract course id + code the concept hangs off (db/seed_local_rich.py). */
export const COURSE_ID_CS = "rich-course-cs101";
export const COURSE_CODE_CS = "CS101";

/** Correct option labels, in question order — `E2E_QUIZ_CORRECT_LABELS`
 *  (correct options at indexes 1, 2, 0 → wire labels B, C, A). */
export const CORRECT_LABELS = ["B", "C", "A"] as const;

/** The scripted quiz is always three questions, whatever `num_questions` asked
 *  for — the handler ignores the count so the mastery math stays byte-stable. */
export const QUIZ_LENGTH = CORRECT_LABELS.length;

/** routes/quiz.py + services/quiz_config.py: +0.03 per correct, −0.02 per wrong. */
export const MASTERY_PER_CORRECT = 0.03;
export const MASTERY_PER_WRONG = 0.02;

/** The mastery a `score`-of-`total` submission leaves behind (unclamped here —
 *  the seeded 0.25 baseline never reaches either bound). */
export function masteryAfter(before: number, score: number, total: number): number {
  return before + score * MASTERY_PER_CORRECT - (total - score) * MASTERY_PER_WRONG;
}

/** A wrong label for question `n` — any option that isn't the marked one. */
export function wrongLabelFor(n: number): string {
  return CORRECT_LABELS[n - 1] === "A" ? "B" : "A";
}

// ── The scripted quiz's own copy ──────────────────────────────────────────

export const stemOf = (n: number) =>
  `E2E deterministic question ${n}: which option is marked correct?`;

export const optionTextOf = (n: number, label: string) => `Q${n} option ${label}`;

export const explanationOf = (n: number, label: string) =>
  `Scripted E2E fixture: option ${label} is the marked answer for question ${n}.`;

/** Must match backend/agents/function_handlers_e2e.py::E2E_TUTOR_REPLY — the
 *  same constant tutor.spec.ts and streaming.spec.ts assert on. */
export const TUTOR_REPLY =
  "[e2e-function-model] Deterministic tutor reply: every recursive function " +
  "needs a base case so it can stop calling itself.";

// ── Timeouts ──────────────────────────────────────────────────────────────
//
// Generation runs the real agent plus a best-effort RAG grounding read below
// the model seam; submission runs the synchronous mastery write. Both are
// generous CEILINGS on locator waits, never sleeps — nothing here polls a
// clock.
export const GENERATE_TIMEOUT = 60_000;
export const SUBMIT_TIMEOUT = 30_000;
/** The tutor stream is paced at 150ms/chunk by the seam (#356). */
export const STREAM_TIMEOUT = 30_000;

// ── Gestures ──────────────────────────────────────────────────────────────

/**
 * Model a returning browser that has already seen the AI disclosure.
 *
 * `DisclaimerModal` is a fixed overlay over every authed screen for a browser
 * that has never acknowledged it, and it swallows the clicks these journeys
 * make. It is unrelated chrome, not part of any quiz behaviour — the same
 * pre-ack tutor.spec.ts and the pre-#537 quiz journey used.
 */
export async function preAckDisclaimer(page: Page): Promise<void> {
  await page.addInitScript(() => {
    window.localStorage.setItem("sapling_disclaimer_ack", "true");
  });
}

/** Land on quiz home with its proposal card resolved (the graph, the course
 *  list and the attempt history all have to arrive before the card exists). */
export async function openQuizHome(page: Page, url = "/quiz"): Promise<void> {
  await page.goto(url);
  await expect(page.getByTestId("quiz-proposal")).toBeVisible({ timeout: SUBMIT_TIMEOUT });
}

/**
 * Press the card's Start and wait for the first question.
 *
 * The stem assertion is a LOUD MODE GUARD: the scripted fixture's text proves
 * the backend booted in function mode. A stack accidentally in `real` mode
 * would serve a live-Gemini quiz and fail HERE with a clear signal, rather
 * than three steps later on a coin-flip verdict.
 */
export async function startQuiz(page: Page): Promise<void> {
  const start = page.getByTestId("quiz-start");
  await expect(start).toBeEnabled();
  await start.click();
  await expect(page.getByTestId("quiz-answer-options")).toBeVisible({
    timeout: GENERATE_TIMEOUT,
  });
  await expectOnQuestion(page, 1);
}

/** The question screen is showing question `n` of the scripted quiz. */
export async function expectOnQuestion(page: Page, n: number): Promise<void> {
  await expect(page.getByTestId("quiz-panel")).toContainText(stemOf(n), {
    timeout: GENERATE_TIMEOUT,
  });
}

/** Choose an option and press the footer's primary (Submit). */
export async function chooseAndSubmit(page: Page, label: string): Promise<void> {
  await page.getByTestId(`quiz-answer-option-${label}`).click();
  await page.getByTestId("quiz-submit-answer").click();
}

/**
 * Walk the whole scripted quiz in `at-end` mode (the default feedback mode).
 *
 * `steps` is 1-based question number → the label to choose, so a resumed quiz
 * can start part-way through. Each step re-asserts which question is on screen
 * BEFORE choosing, which is what makes the walk race-free without a sleep: the
 * previous `/answer` round trip is still in flight until the next stem renders.
 *
 * In `at-end` there is no per-question reveal and no "See results" press —
 * recording the LAST answer transitions straight to `submitting`
 * (machine.ts::advanceAfterAnswer). The caller waits on the results screen.
 */
export async function answerAtEnd(
  page: Page,
  steps: { n: number; label: string }[],
): Promise<void> {
  for (const { n, label } of steps) {
    await expectOnQuestion(page, n);
    await chooseAndSubmit(page, label);
  }
}

/** One question in `as-you-go` mode: choose, submit, read the verdict, move on. */
export async function answerAsYouGo(
  page: Page,
  n: number,
  label: string,
  verdict: string,
): Promise<void> {
  await expectOnQuestion(page, n);
  await chooseAndSubmit(page, label);
  await expect(page.getByTestId("quiz-review-verdict")).toContainText(verdict, {
    timeout: SUBMIT_TIMEOUT,
  });
  await page.getByTestId("quiz-next").click();
}

/** Wait for the scored results screen. */
export async function expectResults(page: Page): Promise<void> {
  await expect(page.getByTestId("quiz-results")).toBeVisible({ timeout: SUBMIT_TIMEOUT });
}

// ── Navigation ────────────────────────────────────────────────────────────

/** `pathname + search` as the RENDERER sees it. */
function locationOf(page: Page): Promise<string> {
  return page
    .evaluate(() => window.location.pathname + window.location.search)
    .catch(() => "");
}

/**
 * Wait for the browser to be at exactly `expected` (`pathname + search`).
 *
 * Deliberately NOT `page.waitForURL`: the quiz exits are `router.push` calls,
 * and a push to the route the student is ALREADY on lands so fast that the
 * navigation event can fire between `click()` returning and `waitForURL`
 * attaching its listener — after which it waits forever (its own default
 * timeout is 0, so the failure is a whole test timeout with no diagnosis).
 * `Done` → `/quiz` from `/quiz?concept=…` hit exactly that. Polling
 * `window.location` is event-independent, and a mismatch reports the URL the
 * browser is actually on.
 */
export async function expectLocation(
  page: Page,
  expected: string,
  timeout = 20_000,
): Promise<void> {
  await expect
    .poll(() => locationOf(page), { timeout, message: `expected to land on ${expected}` })
    .toBe(expected);
}

/** Like `expectLocation`, but only about the route — used where the query
 *  string is a separate (and currently unmet) claim. */
export async function expectPathname(
  page: Page,
  expected: string,
  timeout = 20_000,
): Promise<void> {
  await expect
    .poll(() => page.evaluate(() => window.location.pathname).catch(() => ""), {
      timeout,
      message: `expected to land on the ${expected} route`,
    })
    .toBe(expected);
}

/** Wait until the browser's `pathname + search` contains `fragment`, then hand
 *  back the whole thing so the caller can pick the query apart. */
export async function locationContaining(
  page: Page,
  fragment: string,
  timeout = 20_000,
): Promise<string> {
  await expect
    .poll(() => locationOf(page), {
      timeout,
      message: `expected the URL to contain ${fragment}`,
    })
    .toContain(fragment);
  return locationOf(page);
}

// ── Keyboard ──────────────────────────────────────────────────────────────

/** The `data-testid` of whatever currently holds focus, or null. */
export function focusedTestId(page: Page): Promise<string | null> {
  return page.evaluate(
    () => (document.activeElement as HTMLElement | null)?.dataset.testid ?? null,
  );
}

/**
 * Tab forward until `testid` holds focus.
 *
 * A bounded walk rather than a fixed press count: the assertion is "this
 * control is REACHABLE from the keyboard", and pinning the exact number of tab
 * stops would turn every nav or header change into a quiz failure. Throws with
 * the focus trail when the budget runs out, so a genuinely unreachable control
 * fails loudly.
 */
export async function tabUntilFocused(page: Page, testid: string, max = 60): Promise<void> {
  const trail: (string | null)[] = [];
  for (let i = 0; i < max; i++) {
    if ((await focusedTestId(page)) === testid) return;
    await page.keyboard.press("Tab");
    trail.push(await focusedTestId(page));
  }
  throw new Error(
    `Tab never reached [data-testid="${testid}"] within ${max} presses. ` +
      `Focus trail: ${JSON.stringify(trail)}`,
  );
}

// ── Database readbacks ────────────────────────────────────────────────────

/**
 * The attempt rows THIS journey created on a node.
 *
 * The rich seed also carries a completed baseline attempt on Recursion
 * (`rich-qa-cs-recursion-1`). Seeded ids are namespaced `rich-*` and the route
 * mints uuid4 ids, so the NOT LIKE filter isolates the app-written rows.
 */
export async function appAttempts(nodeId = NODE_ID) {
  // `status` is DERIVED by the route (`routes/quiz.py::_attempt_status`), not a
  // column — the storage-level truth is the two timestamps.
  return (await queryRaw(
    `SELECT id, score, total, difficulty, completed_at, abandoned_at
       FROM quiz_attempts
      WHERE concept_node_id = $1 AND id NOT LIKE 'rich-%'
      ORDER BY created_at`,
    [nodeId],
  )) as {
    id: string;
    score: number | null;
    total: number | null;
    difficulty: string;
    completed_at: string | null;
    abandoned_at: string | null;
  }[];
}

/** `graph_nodes.mastery_score` for one node, as a number. */
export async function masteryOf(nodeId = NODE_ID): Promise<number> {
  const rows = await queryRaw("SELECT mastery_score FROM graph_nodes WHERE id = $1", [nodeId]);
  expect(rows, `graph_nodes row for ${nodeId}`).toHaveLength(1);
  return Number(rows[0].mastery_score);
}
