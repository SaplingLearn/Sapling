/**
 * Journey (#392): a tutor conversation persists to `messages`, encrypted.
 *
 * Flow: resume the seeded "Understanding Recursion" session → send a message
 * through the real composer → assert the deterministic reply renders → raw-SQL
 * readback of the two new `messages` rows proving the encryption boundary
 * (`content` at rest is ciphertext, and decrypts to exactly what was sent).
 *
 * Determinism: the stack must be booted with
 *
 *   SAPLING_MODEL_MODE=function \
 *   SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e make e2e-up
 *
 * so `model_for("chat_tutor")` builds a FunctionModel (#391) and the backend
 * self-registers the fixed-reply handler at first dispatch (#392). The spec
 * enters the chat by RESUMING a seeded session — deliberately not via
 * "Start learning": `POST /api/learn/start-session` still runs on the legacy
 * `call_gemini_multiturn` path (routes/learn.py), which the seam does not
 * cover, and this journey must never depend on live Gemini.
 *
 * No token streaming: `sendChat` (src/lib/api.ts) is a plain fetch returning
 * the full `{ reply, ... }` object, so the assertions wait on the rendered
 * reply locator — no SSE handling, no waitForTimeout.
 */
import { expect, test } from "./support/fixtures";
import { queryRaw } from "./support/db";
import { decryptTexts } from "./support/decrypt";

/** Seeded by db/seed_local_rich.py for rich-user-active (4 prior messages). */
const SESSION_ID = "rich-sess-cs-recursion";
const SEEDED_MESSAGE_COUNT = 4;

/** What the student types — asserted verbatim against the decrypted user row. */
const STUDENT_MESSAGE =
  "Why does infinite recursion crash the program? (e2e #392)";

/** Must match backend/agents/function_handlers_e2e.py::E2E_TUTOR_REPLY. */
const TUTOR_REPLY =
  "[e2e-function-model] Deterministic tutor reply: every recursive function " +
  "needs a base case so it can stop calling itself.";

/** Must match backend/agents/function_handlers_e2e.py::E2E_CONCEPT_DESCRIPTION. */
const CONCEPT_DESCRIPTION =
  "[e2e-function-model] Deterministic concept blurb: recursion is when a " +
  "function calls itself on a smaller version of the same problem.";

test("tutor turn renders a reply and persists encrypted to messages", async ({
  page,
}) => {
  // The per-browser AI-disclosure modal (DisclaimerModal) is a fixed overlay
  // that would swallow the composer clicks. Model a returning user who has
  // already acknowledged it — the disclaimer is not this journey's subject,
  // and its "Got it" control carries no testid to dismiss it by.
  await page.addInitScript(() => {
    localStorage.setItem("sapling_disclaimer_ack", "true");
  });

  // ── Reach an active chat by resuming the seeded session ──────────────────
  await page.goto("/learn");
  await page.getByTestId(`tutor-session-resume-${SESSION_ID}`).click();

  // The conversation log mounts with the seeded history (proves resume
  // actually loaded this session's decrypted turns, not an empty chat).
  const log = page.getByTestId("tutor-messages");
  await expect(log).toBeVisible();
  await expect(log).toContainText("Can you explain recursion?");

  // ── Send a message through the real composer ─────────────────────────────
  await page.getByTestId("tutor-input").fill(STUDENT_MESSAGE);
  await page.getByTestId("tutor-send").click();

  // The user turn renders immediately; the deterministic FunctionModel reply
  // replaces the "Thinking…" placeholder when POST /api/learn/chat returns.
  await expect(log).toContainText(STUDENT_MESSAGE);
  await expect(log).toContainText(TUTOR_REPLY);

  // ── Raw-SQL readback: the turn persisted, encrypted (#397 posture) ───────
  const rows = (await queryRaw(
    `SELECT role, content FROM messages
      WHERE session_id = $1
      ORDER BY created_at ASC`,
    [SESSION_ID],
  )) as { role: string; content: string }[];

  // Exactly the seeded baseline plus this turn's user + assistant rows.
  expect(rows).toHaveLength(SEEDED_MESSAGE_COUNT + 2);
  const [userRow, assistantRow] = rows.slice(-2);
  expect(userRow.role).toBe("user");
  expect(assistantRow.role).toBe("assistant");

  // At rest the content column is CIPHERTEXT — never the sent plaintext.
  expect(userRow.content).not.toBe(STUDENT_MESSAGE);
  expect(assistantRow.content).not.toBe(TUTOR_REPLY);

  // And it decrypts (via the backend's own helper) to exactly what was sent
  // and exactly what rendered. Both checks are required: decrypt_if_present
  // echoes plaintext input back, so decrypt-equality alone can't prove
  // encryption — the ciphertext assertions above close that hole.
  const [userPlain, assistantPlain] = await decryptTexts([
    userRow.content,
    assistantRow.content,
  ]);
  expect(userPlain).toBe(STUDENT_MESSAGE);
  expect(assistantPlain).toBe(TUTOR_REPLY);
});

/**
 * Journey (#446): resuming a session surfaces the knowledge-map rail's
 * "Focused concept" card for that session's topic node. The seeded
 * `rich-node-cs-recursion` node (concept "Recursion", db/seed_local_rich.py)
 * carries no stored `description`, so the card falls through to an
 * on-demand `POST /api/graph/{user}/concept-description` call
 * (Learn.tsx's focus-description effect) — exactly the function-mode path
 * that used to 500 (`agents/_providers.py::_dispatch` raised LookupError
 * because `function_handlers_e2e.py` had no `concept_describe` handler
 * registered). No click on the rail is needed: resuming sets `topic` to the
 * session's topic ("Recursion") synchronously, which the rail's `highlightId`
 * memo matches against the already-loaded graph nodes and auto-focuses.
 */
test("resuming a session surfaces the deterministic concept description in the rail", async ({
  page,
}) => {
  await page.addInitScript(() => {
    localStorage.setItem("sapling_disclaimer_ack", "true");
  });

  await page.goto("/learn");
  await page.getByTestId(`tutor-session-resume-${SESSION_ID}`).click();

  // Proves resume actually loaded before asserting on the rail (same signal
  // the tutor-reply journey above uses).
  await expect(page.getByTestId("tutor-messages")).toContainText(
    "Can you explain recursion?",
  );

  await expect(
    page.getByTestId("tutor-focus-concept-description"),
  ).toHaveText(CONCEPT_DESCRIPTION);
});
