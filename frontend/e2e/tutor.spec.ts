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
 * enters the chat by RESUMING a seeded session — keeping the journey off the
 * greeting turn entirely, so its assertions are exactly one send → one reply.
 * (Since #349 the composer streams over SSE with a JSON fallback ladder; the
 * seam replays the same constant on both lanes, so the assertions just wait
 * on the rendered reply locator either way — no SSE handling here.)
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
 * Journey (#164): the Dashboard "Where you left off" card deep-links into the
 * exact session with its history hydrated. The bug being pinned: Learn read
 * only `topic`/`mode`/`course`/`suggest` off the URL, so the `?resume=` the
 * card pushes (and Tree's session rows, now unified on the same param) was
 * silently dropped — the card landed on the "Start a session" picker, a dead
 * button in effect. Entry is via the REAL dashboard card, not a direct URL,
 * so the whole caller → param → resume wiring is on the hook.
 */
test("dashboard 'Where you left off' card resumes the exact session (#164)", async ({
  page,
}) => {
  await page.addInitScript(() => {
    localStorage.setItem("sapling_disclaimer_ack", "true");
  });

  await page.goto("/dashboard");
  await page.getByTestId(`dashboard-resume-${SESSION_ID}`).click();
  await expect(page).toHaveURL(/\/learn\?/);

  // The seeded conversation hydrates — both an early and a late seeded turn,
  // proving the full history loaded rather than a fresh chat on the topic.
  const log = page.getByTestId("tutor-messages");
  await expect(log).toContainText("Can you explain recursion?");
  await expect(log).toContainText(
    "The base case is the condition where the function stops calling itself.",
  );

  // And it's the chat view, not the session picker the bug used to strand
  // users on (the picker's resume row only exists on the entry screen).
  await expect(page.getByTestId(`tutor-session-resume-${SESSION_ID}`)).toHaveCount(0);
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

/**
 * Journey (#151a): the greeting turn — "Start learning" through the real
 * entry screen streams the deterministic chat_tutor greeting (the streamed
 * opener + JSON opener now share one agent pipeline; the seam replays the
 * same constant on both lanes). Sessions are LAZY (PENDING_SESSIONS): the
 * greeting alone persists NO session row — it materializes on the first
 * chat turn — so the DB asserts run after a follow-up message.
 */
test("greeting turn streams the deterministic reply; session materializes on first chat", async ({
  page,
}) => {
  await page.addInitScript(() => {
    localStorage.setItem("sapling_disclaimer_ack", "true");
  });
  const TOPIC = "Greeting journey topic (e2e #151a)";

  await page.goto("/learn");
  await page.getByTestId("tutor-topic-picker").click();
  await page.getByTestId("tutor-topic-search").fill(TOPIC);
  await page.keyboard.press("Enter"); // no concept matches → picks the custom topic
  await page.getByTestId("tutor-start").click();

  // The deterministic greeting renders — and lazily: no session row yet.
  const log = page.getByTestId("tutor-messages");
  await expect(log).toContainText(TUTOR_REPLY);
  const before = (await queryRaw(
    `SELECT id FROM sessions WHERE topic = $1`, [TOPIC],
  )) as { id: string }[];
  expect(before).toHaveLength(0);

  // First chat turn materializes the session: row + greeting + user +
  // assistant all persist (_consume_pending, then the streamed turn).
  await page.getByTestId("tutor-input").fill("Follow-up question (e2e #151a)");
  await page.getByTestId("tutor-send").click();
  await expect
    .poll(async () => {
      const rows = (await queryRaw(
        `SELECT m.role FROM messages m
           JOIN sessions s ON s.id = m.session_id
          WHERE s.topic = $1
          ORDER BY m.created_at ASC`,
        [TOPIC],
      )) as { role: string }[];
      return rows.map((r) => r.role);
    })
    .toEqual(["assistant", "user", "assistant"]);
});
