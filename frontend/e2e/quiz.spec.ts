/**
 * The four BACKEND contracts the quiz lane pins, driven through the #537 UI.
 *
 * The screens were rewritten wholesale (`components/quiz/**` replaced
 * `QuizPanel.tsx` + `screens/Quiz.tsx`), so every anchor here moved with them —
 * but what these tests are FOR did not:
 *
 *   1. #393 — answering a quiz raises mastery in the UI and in the database,
 *      monotonically, and writes exactly one append-only mastery event.
 *   2. #184's successor — a generation that fails leaves the student on a
 *      readable, recoverable screen rather than a blank one.
 *   3. #129 — replaying a completed submission 409s and re-applies nothing.
 *   4. #540 — the option lists are `GET /api/quiz/config`'s, and an adaptive
 *      request reports the concrete difficulty generation actually chose.
 *
 * The redesign's own behaviours (resume, leave-and-return, ask-without-
 * abandoning, missed review, entry points, exits, keyboard) live next door in
 * `quiz-journeys.spec.ts`. Shared fixture constants and gestures are in
 * `support/quiz.ts`, which also carries the function-mode contract note.
 *
 * Every DB assertion reads back over the raw-SQL seam (`support/db.ts`) — a
 * different layer than the one that wrote, so these prove the write hit the
 * database, not the echo.
 *
 * GENERATION BUDGET: `/api/quiz/generate` is rate limited to 8 calls per 300
 * seconds per user, in-process, and the whole lane shares one window (the
 * per-test truncate does not reset it). This file spends THREE of the eight —
 * the mastery journey, the resubmit journey and the adaptive round trip. The
 * failed-generation test spends none (both calls are stubbed). The full
 * accounting, and what to do when a new journey needs a slot, is in
 * `quiz-journeys.spec.ts`'s header.
 */
import { queryRaw } from "./support/db";
import { expect, test } from "./support/fixtures";
import {
  CORRECT_LABELS,
  GENERATE_TIMEOUT,
  NODE_ID,
  QUIZ_LENGTH,
  SEEDED_MASTERY,
  SUBMIT_TIMEOUT,
  answerAtEnd,
  appAttempts,
  expectOnQuestion,
  expectResults,
  masteryAfter,
  masteryOf,
  openQuizHome,
  preAckDisclaimer,
  startQuiz,
} from "./support/quiz";

/** routes/quiz.py: 3 correct of 3 → delta = 3 × 0.03 = +0.09. */
const EXPECTED_DELTA = masteryAfter(0, QUIZ_LENGTH, QUIZ_LENGTH);

/** The whole scripted quiz, answered correctly, in `at-end` order. */
const ALL_CORRECT = CORRECT_LABELS.map((label, i) => ({ n: i + 1, label }));

test("quiz journey: all-correct answers raise mastery in UI and DB, monotonically", async ({
  page,
}) => {
  // Generation includes a best-effort RAG grounding call server-side (below
  // the model seam) before the scripted FunctionModel runs; give the journey
  // room without ever sleeping — every wait below is locator/event-based.
  test.setTimeout(180_000);

  // ── Baseline (post-reset seed), read over the raw-SQL seam ──────────────
  const nodeBefore = await queryRaw(
    "SELECT mastery_score, times_studied FROM graph_nodes WHERE id = $1",
    [NODE_ID],
  );
  expect(nodeBefore).toHaveLength(1);
  const masteryBefore = Number(nodeBefore[0].mastery_score);
  expect(masteryBefore).toBeCloseTo(SEEDED_MASTERY, 10);

  const eventsBefore = await queryRaw(
    "SELECT id FROM node_mastery_events WHERE node_id = $1",
    [NODE_ID],
  );
  expect(eventsBefore).toHaveLength(0);

  // ── Take the quiz through the UI ────────────────────────────────────────
  await preAckDisclaimer(page);

  // The deep link decides which concept the card is about (§6): quiz home
  // arrives already proposing Recursion, one press from starting.
  await openQuizHome(page, `/quiz?concept=${NODE_ID}`);
  const proposal = page.getByTestId("quiz-proposal");
  await expect(proposal).toContainText("Recursion");
  // A bare `?concept=` carries no `from`, so it is a legacy link (§6).
  await expect(proposal).toContainText("Suggested for you");

  await startQuiz(page);

  // ── R-2: in `at-end` (the default) nothing is revealed mid-quiz ─────────
  // Every answer is still RECORDED as it happens via /attempts/{id}/answer —
  // the feedback mode only decides when the verdict is shown. The proof that
  // it was recorded is the score below, which the server computes from the
  // recorded rows.
  await answerAtEnd(page, [ALL_CORRECT[0]]);
  await expectOnQuestion(page, 2);
  await expect(page.getByTestId("quiz-review-verdict")).toBeEmpty();
  await answerAtEnd(page, ALL_CORRECT.slice(1));

  // Recording the LAST answer goes straight to `submitting`, so the results
  // screen renders only after /api/quiz/submit returned — once the score is
  // visible the synchronous mastery write (apply_graph_update) has committed.
  await expectResults(page);
  await expect(page.getByTestId("quiz-results-score")).toHaveText(
    `${QUIZ_LENGTH} of ${QUIZ_LENGTH} correct`,
    { timeout: SUBMIT_TIMEOUT },
  );
  // A clean sweep has nothing to review.
  await expect(page.getByTestId("quiz-results-perfect")).toBeVisible();

  // ── UI mastery: parse the rendered before → after ───────────────────────
  const masteryLine = page.getByTestId("quiz-results-mastery");
  const lineText = (await masteryLine.textContent()) ?? "";
  const match = lineText.match(/(\d+)%\s*→\s*(\d+)%\s*·\s*(\w+)\s*→\s*(\w+)/);
  expect(match, `unparsable mastery line: ${JSON.stringify(lineText)}`).not.toBeNull();
  const uiBefore = Number(match![1]);
  const uiAfter = Number(match![2]);

  // MONOTONICITY (UI): a fully correct quiz never lowers the score.
  expect(uiAfter).toBeGreaterThanOrEqual(uiBefore);
  expect(uiBefore).toBe(Math.round(masteryBefore * 100));

  // ── DB: node score moved, and UI and DB agree ───────────────────────────
  const nodeAfter = await queryRaw(
    "SELECT mastery_score, times_studied, last_studied_at FROM graph_nodes WHERE id = $1",
    [NODE_ID],
  );
  expect(nodeAfter).toHaveLength(1);
  const masteryAfterDb = Number(nodeAfter[0].mastery_score);

  // MONOTONICITY (DB): the persisted score did not drop…
  expect(masteryAfterDb).toBeGreaterThanOrEqual(masteryBefore);
  // …and moved by exactly the all-correct delta (0.25 → 0.34, no clamp).
  expect(masteryAfterDb).toBeCloseTo(SEEDED_MASTERY + EXPECTED_DELTA, 10);
  // UI ↔ DB agreement: the percentages the student saw are the DB state.
  expect(uiAfter).toBe(Math.round(masteryAfterDb * 100));

  // apply_graph_update also bumps the study counters.
  expect(Number(nodeAfter[0].times_studied)).toBe(1);
  expect(nodeAfter[0].last_studied_at).not.toBeNull();

  // ── DB: exactly ONE append-only mastery event, with a non-negative delta ─
  const eventsAfter = await queryRaw(
    "SELECT delta, reason FROM node_mastery_events WHERE node_id = $1 ORDER BY created_at",
    [NODE_ID],
  );
  expect(eventsAfter).toHaveLength(1);
  // MONOTONICITY (event): a correct-only submission records a delta ≥ 0.
  expect(Number(eventsAfter[0].delta)).toBeGreaterThanOrEqual(0);
  expect(Number(eventsAfter[0].delta)).toBeCloseTo(EXPECTED_DELTA, 10);
  expect(eventsAfter[0].reason).toBe(`Quiz: ${QUIZ_LENGTH}/${QUIZ_LENGTH} correct`);

  // ── DB: the attempt row was completed through the app ───────────────────
  const attempts = await appAttempts();
  expect(attempts).toHaveLength(1);
  expect(Number(attempts[0].score)).toBe(QUIZ_LENGTH);
  expect(Number(attempts[0].total)).toBe(QUIZ_LENGTH);
  expect(attempts[0].completed_at).not.toBeNull();
});

/**
 * Successor to the #184 journey ("a zero-question generation must not strand
 * the user on a blank, control-less panel").
 *
 * The original case is no longer reachable: `/api/quiz/generate` 502s with
 * `QUIZ_GENERATION_FAILED` rather than serving an empty quiz (R1 §C), and the
 * reducer maps a zero-question payload onto the same error for belt and braces
 * (machine.ts, GENERATED). What still has to hold is the property #184 was
 * really about — a failed generation leaves a READABLE, RECOVERABLE screen —
 * so the failure is forced at the network layer in the shape the backend
 * actually ships (`{error: {code, message, request_id}}`,
 * services/quiz_errors.py::quiz_error_body) and the mapped copy is asserted
 * verbatim against `QUIZ_ERROR_COPY`.
 *
 * Route interception, not the function-mode seam: the seam's quiz handler is
 * the fixed three-question fixture the mastery journey above depends on, and
 * the mapping under test is purely client-side.
 */
test("a failed generation shows the mapped copy and Retry re-attempts it (#184 successor)", async ({
  page,
}) => {
  test.setTimeout(180_000);

  const REQUEST_ID = "e2e-req-generation-failed";
  await preAckDisclaimer(page);
  await page.route("**/api/quiz/generate", route =>
    route.fulfill({
      status: 502,
      contentType: "application/json",
      body: JSON.stringify({
        error: {
          code: "QUIZ_GENERATION_FAILED",
          message: "The quiz agent returned nothing usable.",
          request_id: REQUEST_ID,
        },
        detail: "The quiz agent returned nothing usable.",
        request_id: REQUEST_ID,
      }),
    }),
  );

  await openQuizHome(page, `/quiz?concept=${NODE_ID}`);
  await page.getByTestId("quiz-start").click();

  // The mapped human sentence — NOT the server's own wording, which for this
  // code is an internal description (§4's copy table).
  const errorCard = page.getByTestId("quiz-error");
  await expect(errorCard).toBeVisible({ timeout: GENERATE_TIMEOUT });
  await expect(errorCard).toContainText(
    "We couldn't put a quiz together for this concept right now. Try again in a moment.",
  );
  // The envelope's request id is surfaced, so a student can quote it.
  await expect(errorCard).toContainText(`Reference ${REQUEST_ID}`);
  // Recoverable, and never a blank panel: a retryable code offers Retry, and
  // Back is always there.
  await expect(page.getByTestId("quiz-error-retry")).toBeVisible();
  await expect(page.getByTestId("quiz-error-back")).toBeVisible();
  // Nothing of the question screen leaked through.
  await expect(page.getByTestId("quiz-answer-options")).toHaveCount(0);
  // The interception never reached the backend, so no attempt row exists.
  expect(await appAttempts()).toHaveLength(0);

  // Retry really re-runs generation from the same concept — it does not merely
  // dismiss the card. The fault is deliberately left in place: proving that the
  // recovered quiz then RUNS would cost a real generation, and the lane's
  // budget (see quiz-journeys.spec.ts's header — 8 per 300s, shared) has none
  // spare. The request going back out is the property #184 was about.
  const retryRequest = page.waitForRequest(
    r => r.url().includes("/api/quiz/generate") && r.method() === "POST",
  );
  await page.getByTestId("quiz-error-retry").click();
  const retryBody = (await retryRequest).postDataJSON() as { concept_node_id: string };
  expect(retryBody.concept_node_id).toBe(NODE_ID);

  // Still the same failure, still readable, still offering the way out — never
  // a blank panel.
  await expect(errorCard).toBeVisible();
  await expect(page.getByTestId("quiz-error-retry")).toBeVisible();
  expect(await appAttempts()).toHaveLength(0);
});

/**
 * Regression (#129): /api/quiz/submit must reject a replay of an already-
 * completed attempt. Before the fix, re-POSTing the same quiz_id re-ran
 * apply_graph_update — a second mastery delta, a duplicate
 * node_mastery_events row, and a streak bump — plus the background
 * quiz-context task and achievements.
 *
 * Lane-level pin: drive the same seeded fixture through the real UI flow,
 * capture the exact wire body the UI sent to /api/quiz/submit
 * ({ quiz_id, answers: [{ question_id, selected_label }] } —
 * backend/models::SubmitQuizBody), then replay it via page.request.post
 * (same-origin, so the sapling_session cookie rides along). The replay must
 * 409, and the DB must be byte-for-byte where the first submit left it.
 *
 * The UI itself has no resubmit affordance to drive (the reducer clears the
 * session on SUBMITTED and refuses EXIT-then-resubmit), so the request-level
 * replay stays the honest way to pin the route's guard.
 */
test("quiz resubmit: replaying a completed submission returns 409 and re-applies no mastery", async ({
  page,
}) => {
  test.setTimeout(180_000);

  await preAckDisclaimer(page);
  await openQuizHome(page, `/quiz?concept=${NODE_ID}`);
  await startQuiz(page);

  // Arm the capture BEFORE the last answer, which is what fires /submit.
  const submitRequestPromise = page.waitForRequest(
    req => req.url().includes("/api/quiz/submit") && req.method() === "POST",
  );

  await answerAtEnd(page, ALL_CORRECT);
  await expectResults(page);
  await expect(page.getByTestId("quiz-results-score")).toHaveText(
    `${QUIZ_LENGTH} of ${QUIZ_LENGTH} correct`,
    { timeout: SUBMIT_TIMEOUT },
  );

  const wireBody = (await submitRequestPromise).postDataJSON() as {
    quiz_id: string;
    answers: Array<{ question_id: number | string; selected_label: string }>;
  };
  expect(wireBody.quiz_id).toBeTruthy();
  expect(wireBody.answers).toHaveLength(QUIZ_LENGTH);

  // First submit's DB state — the baseline the replay must not move.
  const masteryAfterFirst = await masteryOf();
  expect(masteryAfterFirst).toBeCloseTo(SEEDED_MASTERY + EXPECTED_DELTA, 10);

  const eventsAfterFirst = await queryRaw(
    "SELECT id FROM node_mastery_events WHERE node_id = $1",
    [NODE_ID],
  );
  expect(eventsAfterFirst).toHaveLength(1);

  // Replay the SAME submission over the page's cookie jar → 409, not 200.
  const replay = await page.request.post("/api/quiz/submit", { data: wireBody });
  expect(replay.status()).toBe(409);
  // The coded envelope the client would map to "This quiz was already scored."
  const replayBody = (await replay.json()) as { error?: { code?: string } };
  expect(replayBody.error?.code).toBe("QUIZ_ATTEMPT_ALREADY_COMPLETED");

  // The replay re-applied nothing: still exactly ONE mastery event…
  const eventsAfterReplay = await queryRaw(
    "SELECT id FROM node_mastery_events WHERE node_id = $1",
    [NODE_ID],
  );
  expect(eventsAfterReplay).toHaveLength(1);

  // …and the node's score is unchanged from the first submit.
  expect(await masteryOf()).toBeCloseTo(masteryAfterFirst, 10);
});

/**
 * Journey (#540 A1/A2, re-anchored on the #537 Adjust dialog): the option
 * lists are config-driven and adaptive difficulty reports what generation
 * actually chose.
 *
 * The class of bug this pins: a static UI offering values the route rejects
 * ("15 questions" against le=10, "Adaptive" against a concrete-only difficulty
 * check). The two segmented controls must mirror `GET /api/quiz/config` — both
 * the values (their testids are `${testid}-${value}`) and the rendered labels —
 * and an adaptive generate must echo `requested_difficulty: "adaptive"` plus a
 * concrete `resolved_difficulty`: "medium" here, pinned to the all-medium
 * fixture questions in agents/function_handlers_e2e.py (KEEP IN SYNC).
 */
test("the Adjust dialog mirrors /api/quiz/config; adaptive reports its resolved difficulty (#540)", async ({
  page,
}) => {
  test.setTimeout(180_000);

  const cfgResponse = await page.request.get("/api/quiz/config");
  expect(cfgResponse.ok()).toBe(true);
  const cfg = (await cfgResponse.json()) as {
    num_questions: { min: number; max: number; options: number[] };
    difficulties: string[];
  };
  expect(cfg.num_questions.options.length).toBeGreaterThan(0);
  for (const n of cfg.num_questions.options) {
    expect(n).toBeGreaterThanOrEqual(cfg.num_questions.min);
    expect(n).toBeLessThanOrEqual(cfg.num_questions.max);
  }
  expect(cfg.difficulties).toContain("adaptive");

  await preAckDisclaimer(page);
  await openQuizHome(page, `/quiz?concept=${NODE_ID}`);

  await page.getByTestId("quiz-adjust").click();
  const dialog = page.getByTestId("quiz-adjust-dialog");
  await expect(dialog).toBeVisible();

  // Length: exactly the config's options, in order, labelled "{n} questions".
  // An out-of-range value here is the #540 regression.
  const countGroup = page.getByTestId("quiz-seg-count");
  await expect(countGroup.getByRole("radio")).toHaveText(
    cfg.num_questions.options.map(n => `${n} questions`),
  );
  for (const n of cfg.num_questions.options) {
    await expect(page.getByTestId(`quiz-seg-count-${n}`)).toBeVisible();
  }

  // Difficulty: exactly the config's list, values as labels.
  const difficultyGroup = page.getByTestId("quiz-seg-difficulty");
  await expect(difficultyGroup.getByRole("radio")).toHaveText(cfg.difficulties);
  for (const d of cfg.difficulties) {
    await expect(page.getByTestId(`quiz-seg-difficulty-${d}`)).toBeVisible();
  }

  // Pick Adaptive and start from the dialog; capture the real wire round trip.
  await page.getByTestId("quiz-seg-difficulty-adaptive").click();
  await expect(page.getByTestId("quiz-seg-difficulty-adaptive")).toHaveAttribute(
    "aria-checked",
    "true",
  );
  const responsePromise = page.waitForResponse(
    r => r.url().includes("/api/quiz/generate") && r.request().method() === "POST",
  );
  await page.getByTestId("quiz-adjust-start").click();
  const response = await responsePromise;
  expect(response.status()).toBe(200);
  expect(response.request().postDataJSON().difficulty).toBe("adaptive");
  const body = await response.json();
  expect(body.requested_difficulty).toBe("adaptive");
  expect(body.resolved_difficulty).toBe("medium");

  // The pick is surfaced to the student, not just returned on the wire: the
  // question header's chip carries the item's own concrete difficulty.
  await expect(page.getByTestId("quiz-answer-options")).toBeVisible({
    timeout: GENERATE_TIMEOUT,
  });
  await expect(page.getByTestId("quiz-panel")).toContainText("MEDIUM");

  // …and the attempt the route wrote records the requested value.
  const attempts = await queryRaw(
    "SELECT difficulty FROM quiz_attempts WHERE concept_node_id = $1 AND id NOT LIKE 'rich-%'",
    [NODE_ID],
  );
  expect(attempts).toHaveLength(1);
  expect(attempts[0].difficulty).toBe("adaptive");
});
