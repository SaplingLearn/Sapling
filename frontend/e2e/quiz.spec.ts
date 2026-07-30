/**
 * Journey (#393): answer a quiz through the UI → mastery updates in the UI
 * AND in the database.
 *
 * Mastery is the append-only `node_mastery_events` table since migration
 * 0023 (never a `mastery_events` column): submitting a quiz routes through
 * services/graph_service.py::apply_graph_update, which bumps
 * `graph_nodes.mastery_score` and INSERTs one event row. The UI writes
 * through the real routes; every DB assertion here reads back over the
 * raw-SQL seam (support/db.ts::queryRows) — a different layer than the one
 * that wrote, so the test proves the write hit the database, not the echo.
 *
 * MONOTONICITY — the property no mocked test can falsify: a correct answer
 * never lowers a score. The scoring math in routes/quiz.py is
 * `delta = score*0.03 - (total-score)*0.02`; an all-correct submission must
 * therefore never decrease mastery. Asserted three ways below: on the UI's
 * rendered before→after, on `graph_nodes.mastery_score`, and on the event's
 * `delta` sign.
 *
 * Determinism: the stack boots with SAPLING_MODEL_MODE=function and
 * SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e (#391/#392 /
 * ADR 0019), so /api/quiz/generate runs the real quiz_agent against the
 * scripted handler in backend/agents/function_handlers_e2e.py — a fixed
 * three-question quiz whose correct labels are B, C, A
 * (E2E_QUIZ_CORRECT_LABELS). That sequence is pinned by
 * backend/tests/test_e2e_function_handlers.py; KEEP IN SYNC.
 */
import { queryRaw } from "./support/db";
import { expect, test } from "./support/fixtures";

/** db/seed_local_rich.py: "Recursion" for rich-user-active on CS101 —
 * seeded at mastery 0.25 with NO seeded mastery events, so the baseline
 * event count is exactly zero after the per-test reset. */
const NODE_ID = "rich-node-cs-recursion";
const SEEDED_MASTERY = 0.25;

/** Correct option labels, in question order — the e2e_function_handlers.py
 * contract (correct options at indexes 1, 2, 0 → wire labels B, C, A). */
const CORRECT_LABELS = ["B", "C", "A"] as const;

/** routes/quiz.py: 3 correct of 3 → delta = 3 × 0.03 = +0.09. */
const EXPECTED_DELTA = 3 * 0.03;

/**
 * Journey (#184): a generation that returns ZERO questions must not strand
 * the user on a blank, control-less panel. Before the fix, start() flipped
 * to the active phase unconditionally; with an empty array the entire
 * active branch (including quiz-exit) rendered nothing — a dead end.
 *
 * The empty response is forced at the network layer (route interception),
 * NOT via the function-mode seam: the seam's quiz handler is deliberately a
 * fixed 3-question quiz shared by the mastery journey above, and the guard
 * under test is purely client-side.
 */
test("a zero-question generation stays on the select phase with a warning (#184)", async ({
  page,
}) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("sapling_disclaimer_ack", "true");
  });
  await page.route("**/api/quiz/generate", route =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ quiz_id: "e2e-empty-quiz", questions: [] }),
    }),
  );

  await page.goto(`/quiz?concept=${NODE_ID}`);
  const start = page.getByTestId("quiz-start");
  await expect(start).toBeEnabled();
  await start.click();

  // The warning surfaces and the select phase survives: Start is still
  // there, and the active phase never rendered.
  await expect(
    page.getByText("No questions were generated", { exact: false }),
  ).toBeVisible();
  await expect(page.getByTestId("quiz-start")).toBeVisible();
  await expect(page.getByTestId("quiz-answer-options")).toHaveCount(0);
});

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
  // The AI-disclaimer modal (DisclaimerModal.tsx) opens over /quiz for any
  // browser that has never acknowledged it and intercepts every click.
  // Pre-ack it exactly the way a returning user's browser carries the ack —
  // the disclaimer is unrelated chrome, not part of this journey's scope.
  // (Scoped here rather than in global-setup.ts, which stays verbatim-
  // identical to the #386 branch by sibling-convergence agreement.)
  await page.addInitScript(() => {
    window.localStorage.setItem("sapling_disclaimer_ack", "true");
  });

  // Deep link preselects the course AND the concept (quizSelection.ts), so
  // the select phase arrives ready to start.
  await page.goto(`/quiz?concept=${NODE_ID}`);
  await expect(page.getByTestId("quiz-panel")).toBeVisible();

  const start = page.getByTestId("quiz-start");
  await expect(start).toBeEnabled();
  await start.click();

  // /api/quiz/generate round trip (agent + attempt insert) → active phase.
  await expect(page.getByTestId("quiz-answer-options")).toBeVisible({
    timeout: 60_000,
  });

  // Loud mode guard: the scripted fixture's question text proves the backend
  // booted with SAPLING_MODEL_MODE=function. A stack accidentally in `real`
  // mode would serve a live-Gemini quiz and fail HERE with a clear signal,
  // not three steps later on a coin-flip verdict.
  await expect(page.getByTestId("quiz-panel")).toContainText(
    "E2E deterministic question 1",
  );

  for (const label of CORRECT_LABELS) {
    await page.getByTestId(`quiz-answer-option-${label}`).click();
    await page.getByTestId("quiz-submit-answer").click();
    // The scripted quiz makes every chosen label the correct one — a
    // "Not quite." here means the handler/spec label contract drifted.
    await expect(page.getByTestId("quiz-review-verdict")).toHaveText(
      "Correct.",
    );
    await page.getByTestId("quiz-next").click();
  }

  // The final "See results" click fires /api/quiz/submit; the results phase
  // renders only after the response, so once the score is visible the
  // synchronous mastery write (apply_graph_update) has been committed.
  await expect(page.getByTestId("quiz-results-score")).toHaveText("100%", {
    timeout: 30_000,
  });

  // ── UI mastery: parse the rendered before → after ───────────────────────
  const masteryLine = page.getByTestId("quiz-results-mastery");
  await expect(masteryLine).toContainText("3 / 3 correct");
  const lineText = (await masteryLine.textContent()) ?? "";
  const match = lineText.match(/mastery\s+(\d+)%\s*→\s*(\d+)%/);
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
  const masteryAfter = Number(nodeAfter[0].mastery_score);

  // MONOTONICITY (DB): the persisted score did not drop…
  expect(masteryAfter).toBeGreaterThanOrEqual(masteryBefore);
  // …and moved by exactly the all-correct delta (0.25 → 0.34, no clamp).
  expect(masteryAfter).toBeCloseTo(SEEDED_MASTERY + EXPECTED_DELTA, 10);
  // UI ↔ DB agreement: the percentages the student saw are the DB state.
  expect(uiAfter).toBe(Math.round(masteryAfter * 100));

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
  expect(eventsAfter[0].reason).toBe("Quiz: 3/3 correct");

  // ── DB: the attempt row was completed through the app ───────────────────
  // Scoped to rows the JOURNEY created: the rich seed also has a completed
  // baseline attempt on this node (rich-qa-cs-recursion-1). Seeded ids are
  // namespaced rich-*; the route mints uuid4 ids, so the NOT LIKE filter
  // isolates the app-written row.
  const attempts = await queryRaw(
    "SELECT score, total, completed_at FROM quiz_attempts WHERE concept_node_id = $1 AND id NOT LIKE 'rich-%'",
    [NODE_ID],
  );
  expect(attempts).toHaveLength(1);
  expect(Number(attempts[0].score)).toBe(3);
  expect(Number(attempts[0].total)).toBe(3);
  expect(attempts[0].completed_at).not.toBeNull();
});
