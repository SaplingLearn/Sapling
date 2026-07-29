/**
 * Streaming fallback-ladder journeys (#356, ADR 0020) — the browser-lane
 * promotion of PR #349's remaining manual smoke items:
 *
 *   item 6 — the stream failing to OPEN falls back to the JSON turn
 *            transparently (client Rung 3); the user sees a normal reply.
 *   items 4+5 — Stop mid-stream keeps the partial reply, marks the bubble
 *            interrupted, offers Retry (ADR 0020), and persists NOTHING;
 *            Retry then completes the turn and persists exactly one pair.
 *   item 7 — switching sessions mid-stream aborts the stream and leaves no
 *            stale bubble in the other session's transcript.
 *
 * (Item 3 — the SERVER-side Rung-1 legacy fallback — deliberately has no
 * journey here: the legacy gemini_service seam has no function-mode gate by
 * design (fallback-only, slated for deletion in #151), so it cannot run
 * deterministically in this lane. Its live proof is
 * backend/tests/test_streaming_rung1_live.py; its mechanics are pinned
 * hermetically in test_chat_stream.py / test_learn_stream_routes.py.)
 *
 * Mid-stream windows are real: the function-mode seam paces streamed replay
 * (agents/function_handlers_e2e.py sets a 150ms inter-chunk delay at import),
 * and a message carrying E2E_SLOW_STREAM_TRIGGER gets the LONG deterministic
 * reply — ~40 paced chunks ≈ a 6-second stream to act inside. Stack boot:
 *
 *   SAPLING_MODEL_MODE=function \
 *   SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e make e2e-up
 */
import { expect, test } from "./support/fixtures";
import { queryRaw } from "./support/db";
import { decryptTexts } from "./support/decrypt";

/** Seeded by db/seed_local_rich.py for rich-user-active. */
const SESSION_ID = "rich-sess-cs-recursion";
const SEEDED_MESSAGE_COUNT = 4;
const MATH_SESSION_ID = "rich-sess-math-vectors";
const MATH_SEEDED_MESSAGE_COUNT = 2;

/** Must match backend/agents/function_handlers_e2e.py::E2E_TUTOR_REPLY. */
const TUTOR_REPLY =
  "[e2e-function-model] Deterministic tutor reply: every recursive function " +
  "needs a base case so it can stop calling itself.";

/** Must match backend/agents/function_handlers_e2e.py::E2E_SLOW_STREAM_TRIGGER. */
const SLOW_TRIGGER = "E2E_SLOW_STREAM";

/** Must match backend/agents/function_handlers_e2e.py::E2E_TUTOR_SLOW_REPLY. */
const SLOW_REPLY =
  "[e2e-function-model] Deterministic SLOW tutor reply for mid-stream " +
  "journeys. Recursion solves a problem by reducing it to a smaller copy " +
  "of itself, and every recursive function needs two ingredients: a base " +
  "case that stops the descent, and a recursive step that makes real " +
  "progress toward that base case on every call. Picture the call stack " +
  "as a tower of postponed promises: each frame waits for the smaller " +
  "problem beneath it to resolve before it can finish its own work. When " +
  "the base case finally answers, the tower unwinds in reverse order and " +
  "every waiting frame completes with the value it was promised. If the " +
  "recursive step ever fails to shrink the problem, the tower grows " +
  "without bound until the runtime refuses to add another frame and the " +
  "program crashes with a stack overflow. That is the whole discipline in " +
  "one sentence: shrink toward a base case you are certain to reach. This " +
  "is the final sentence of the slow deterministic reply.";

/** Rendered within the first few paced chunks — the "stream is live" gate. */
const SLOW_REPLY_PREFIX = "[e2e-function-model] Deterministic SLOW";
/** Rendered only when the stream ran to completion — the completion sentinel. */
const SLOW_REPLY_TAIL = "final sentence of the slow deterministic reply";

const STUDENT_SLOW_MESSAGE = `Walk me through this ${SLOW_TRIGGER} please (e2e #356)`;
const STUDENT_MESSAGE = "What breaks without a base case? (e2e #356 item 6)";

async function messageRows(sessionId: string) {
  return (await queryRaw(
    `SELECT role, content FROM messages
      WHERE session_id = $1
      ORDER BY created_at ASC`,
    [sessionId],
  )) as { role: string; content: string }[];
}

async function openSeededSession(page: import("@playwright/test").Page, sessionId: string) {
  await page.getByTestId(`tutor-session-resume-${sessionId}`).click();
  await expect(page.getByTestId("tutor-messages")).toBeVisible();
}

test.beforeEach(async ({ page }) => {
  // The per-browser AI-disclosure modal would swallow composer clicks; model
  // a returning user who has already acknowledged it (same as tutor.spec.ts).
  await page.addInitScript(() => {
    localStorage.setItem("sapling_disclaimer_ack", "true");
  });
});

test("stream that fails to open falls back to the JSON turn transparently (#356 item 6)", async ({
  page,
}) => {
  // Kill the SSE route at the network layer: the client's ladder must degrade
  // to the non-streaming JSON turn with no user-visible error (Rung 3).
  await page.route("**/api/learn/chat/stream", route => route.abort());

  await page.goto("/learn");
  await openSeededSession(page, SESSION_ID);

  await page.getByTestId("tutor-input").fill(STUDENT_MESSAGE);
  await page.getByTestId("tutor-send").click();

  const log = page.getByTestId("tutor-messages");
  await expect(log).toContainText(STUDENT_MESSAGE);
  await expect(log).toContainText(TUTOR_REPLY);
  // Transparent means transparent: no interrupted chrome, no error bubble.
  await expect(page.getByTestId("tutor-interrupted")).toHaveCount(0);

  // Exactly one user+assistant pair persisted, by the JSON route.
  const rows = await messageRows(SESSION_ID);
  expect(rows).toHaveLength(SEEDED_MESSAGE_COUNT + 2);
  const [userRow, assistantRow] = rows.slice(-2);
  expect(userRow.role).toBe("user");
  expect(assistantRow.role).toBe("assistant");
  const [userPlain, assistantPlain] = await decryptTexts([
    userRow.content,
    assistantRow.content,
  ]);
  expect(userPlain).toBe(STUDENT_MESSAGE);
  expect(assistantPlain).toBe(TUTOR_REPLY);
});

test("Stop mid-stream keeps the partial, marks it interrupted, persists nothing; Retry completes (#356 items 4+5, ADR 0020)", async ({
  page,
}) => {
  await page.goto("/learn");
  await openSeededSession(page, SESSION_ID);

  await page.getByTestId("tutor-input").fill(STUDENT_SLOW_MESSAGE);
  await page.getByTestId("tutor-send").click();

  const log = page.getByTestId("tutor-messages");
  // Wait for live streamed text (the paced window is ~6s), then Stop.
  await expect(log).toContainText(SLOW_REPLY_PREFIX);
  await page.getByTestId("tutor-stop").click();

  // ADR 0020: the partial stays visible, marked interrupted, with Retry.
  await expect(page.getByTestId("tutor-interrupted")).toBeVisible();
  await expect(page.getByTestId("tutor-retry")).toBeVisible();
  await expect(log).toContainText(SLOW_REPLY_PREFIX);
  await expect(log).not.toContainText(SLOW_REPLY_TAIL);

  // Item 4's persistence contract: an interrupted turn writes NOTHING — no
  // phantom partial assistant row, and no orphaned user row either.
  expect(await messageRows(SESSION_ID)).toHaveLength(SEEDED_MESSAGE_COUNT);

  // Retry re-sends the same turn (safe precisely because nothing persisted)
  // and this time it runs to completion.
  await page.getByTestId("tutor-retry").click();
  await expect(log).toContainText(SLOW_REPLY_TAIL, { timeout: 30_000 });
  await expect(page.getByTestId("tutor-interrupted")).toHaveCount(0);

  const rows = await messageRows(SESSION_ID);
  expect(rows).toHaveLength(SEEDED_MESSAGE_COUNT + 2);
  const [userRow, assistantRow] = rows.slice(-2);
  expect(userRow.role).toBe("user");
  expect(assistantRow.role).toBe("assistant");
  const [userPlain, assistantPlain] = await decryptTexts([
    userRow.content,
    assistantRow.content,
  ]);
  expect(userPlain).toBe(STUDENT_SLOW_MESSAGE);
  expect(assistantPlain).toBe(SLOW_REPLY);
});

test("switching sessions mid-stream aborts the stream and leaves no stale bubble (#356 item 7)", async ({
  page,
}) => {
  // Collect stream-request failures as they happen; asserted eventually via
  // poll below (the abort races the navigation, so a one-shot waitForEvent
  // registered after the click could miss it).
  const failedStreams: string[] = [];
  page.on("requestfailed", request => {
    if (request.url().includes("/api/learn/chat/stream")) {
      failedStreams.push(request.failure()?.errorText ?? "failed");
    }
  });

  await page.goto("/learn");
  await openSeededSession(page, SESSION_ID);

  await page.getByTestId("tutor-input").fill(STUDENT_SLOW_MESSAGE);
  await page.getByTestId("tutor-send").click();
  await expect(page.getByTestId("tutor-messages")).toContainText(SLOW_REPLY_PREFIX);

  // Mid-stream: leave the chat and open the OTHER seeded session.
  await page.getByTestId("tutor-back-to-learn").click();
  await page.getByTestId(`tutor-session-resume-${MATH_SESSION_ID}`).click();

  // The math transcript renders; the recursion session's streamed text must
  // NOT bleed into it (no stale bubble, interrupted or otherwise).
  const log = page.getByTestId("tutor-messages");
  await expect(log).toContainText("What is a dot product?");
  await expect(log).not.toContainText(SLOW_REPLY_PREFIX);
  await expect(page.getByTestId("tutor-interrupted")).toHaveCount(0);

  // The SSE request was actually torn down (no leaked stream)…
  await expect.poll(() => failedStreams.length, { timeout: 5_000 }).toBeGreaterThan(0);

  // …and the interrupted turn persisted nothing to either session.
  expect(await messageRows(SESSION_ID)).toHaveLength(SEEDED_MESSAGE_COUNT);
  expect(await messageRows(MATH_SESSION_ID)).toHaveLength(MATH_SEEDED_MESSAGE_COUNT);
});
