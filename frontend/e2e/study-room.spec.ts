/**
 * Journey #394 — study room with two browser contexts.
 *
 * Study rooms are the only multi-user surface, and `room_messages.text` is
 * column-encrypted at rest — two signed-in contexts are the only honest way
 * to observe propagation end-to-end (write → encrypt → realtime signal →
 * decrypting re-fetch → render).
 *
 * Room existence: the journey uses the SEEDED room `rich-room-study-group`
 * (db/seed_local_rich.py) — both rich-user-active and rich-user-second are
 * members and three encrypted messages exist. This is the most robust path:
 * no create/join UI dance, deterministic ids, and the per-test reset restores
 * it. (Creating a room via UI/API is covered by the routes, not this journey.)
 *
 * Propagation mechanics (frontend/src/components/screens/Social.tsx):
 * the client subscribes to Supabase Realtime `postgres_changes` on
 * `room_messages` over a websocket. A FOREIGN insert event carries ciphertext
 * `text` (#124), so the client treats it purely as a "something changed"
 * signal and re-fetches through the decrypting REST endpoint
 * (GET /api/social/rooms/{id}/messages). Own sends render optimistically and
 * reconcile from the POST response. There is NO polling fallback — realtime
 * is the only cross-client path, which is why this spec waits for each
 * context's postgres_changes subscription to be confirmed (the server's
 * "Subscribed to PostgreSQL" system frame) before any cross-context send:
 * an insert landing before the receiver's subscription is live would never
 * be delivered. All waits are event-based; zero waitForTimeout.
 *
 * Prerequisites added with this spec (previously the journey was impossible
 * on a migrations-only schema):
 *   - migration 0032: rooms drift columns (topic/course/owner_id/updated_at/
 *     is_public) that routes/social.py selects — without them every room
 *     listing endpoint 500s (bug #405, verified reproducing locally);
 *   - migration 0033: `room_messages` added to the supabase_realtime
 *     publication — without it postgres_changes never fire locally.
 */
import type { Page } from "@playwright/test";

import { expect, test } from "./support/fixtures";
import { mintStorageState } from "./support/session";
import { USER_SECOND } from "./support/stack";

/** Seeded study room both users belong to (db/seed_local_rich.py). */
const ROOM_ID = "rich-room-study-group";

/** A seeded, column-encrypted message — rendering it proves the decrypting
 * read path (not just that rows exist). */
const SEEDED_MESSAGE = "Anyone up for reviewing recursion before the midterm?";

/**
 * Resolves once this page's Realtime postgres_changes subscription for the
 * given room is CONFIRMED live by the server. The confirmation is the
 * Phoenix "system" frame `Subscribed to PostgreSQL` on the channel topic
 * `room:<roomId>` — the moment from which WAL events are guaranteed to be
 * delivered. Must be armed BEFORE navigating so no websocket is missed.
 */
function waitForRoomRealtime(
  page: Page,
  roomId: string,
  timeoutMs = 30_000,
): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    const timer = setTimeout(() => {
      reject(
        new Error(
          `Realtime postgres_changes for room ${roomId} was not confirmed ` +
            `within ${timeoutMs}ms — is room_messages in the ` +
            "supabase_realtime publication (migration 0033)?",
        ),
      );
    }, timeoutMs);
    page.on("websocket", (ws) => {
      if (!ws.url().includes("realtime")) return;
      ws.on("framereceived", (frame) => {
        const text =
          typeof frame.payload === "string"
            ? frame.payload
            : frame.payload.toString("utf-8");
        if (
          text.includes(`room:${roomId}`) &&
          text.includes("Subscribed to PostgreSQL")
        ) {
          clearTimeout(timer);
          resolve();
        }
      });
    });
  });
}

/** Navigate a signed-in page into the seeded room's chat and wait until both
 * the decrypted seeded history is rendered AND realtime is confirmed live. */
async function enterStudyRoom(page: Page): Promise<void> {
  const realtimeReady = waitForRoomRealtime(page, ROOM_ID);
  // Handled at the `await` below; this guard only silences an early timeout
  // rejection from surfacing as an unhandled rejection mid-navigation.
  realtimeReady.catch(() => {});

  await page.goto("/social");
  // Explicitly select the seeded room — the sidebar auto-picks the first room
  // in an unordered listing, and both seeded users belong to two rooms.
  await page.getByTestId(`social-room-item-${ROOM_ID}`).click();
  await expect(page.getByTestId("social-room-name")).toHaveText(
    "CS101 Study Group",
  );

  // Seeded history renders decrypted (room_messages.text is encrypted at
  // rest; the REST read path decrypts).
  await expect(page.getByTestId("social-chat-messages")).toContainText(
    SEEDED_MESSAGE,
  );

  await realtimeReady;
}

test("study room: chat propagates across two contexts and both graphs render", async ({
  page,
  browser,
}) => {
  // Two contexts, several navigations, and two realtime round-trips — give
  // the whole journey more room than the 30s default without ever sleeping.
  test.setTimeout(120_000);

  // Context A is the default fixture page (rich-user-active via the
  // global-setup storageState). Context B signs in rich-user-second through
  // the same #381 test-login seam, minted fresh inside the test.
  const contextB = await browser.newContext({
    storageState: await mintStorageState(USER_SECOND, "Sam Second"),
  });
  try {
    const pageB = await contextB.newPage();

    await enterStudyRoom(page);
    await enterStudyRoom(pageB);

    const logA = page.getByTestId("social-chat-messages");
    const logB = pageB.getByTestId("social-chat-messages");

    // A → B. Unique per-direction markers that cannot collide with seeded copy.
    const fromA = "E2E propagation check: ping from Rich Active";
    await page.getByTestId("social-chat-input").fill(fromA);
    await page.getByTestId("social-chat-send").click();
    // Sender renders its own message (optimistic + POST reconciliation)…
    await expect(logA).toContainText(fromA);
    // …and the OTHER context receives it: realtime insert event → decrypting
    // REST re-fetch → rendered, attributed to the sender.
    await expect(logB).toContainText(fromA, { timeout: 15_000 });
    await expect(
      logB.getByTestId(/^social-chat-message-/).filter({ hasText: fromA }),
    ).toContainText("Rich Active");

    // B → A, the reverse direction.
    const fromB = "E2E propagation check: pong from Sam Second";
    await pageB.getByTestId("social-chat-input").fill(fromB);
    await pageB.getByTestId("social-chat-send").click();
    await expect(logB).toContainText(fromB);
    await expect(logA).toContainText(fromB, { timeout: 15_000 });
    await expect(
      logA.getByTestId(/^social-chat-message-/).filter({ hasText: fromB }),
    ).toContainText("Sam Second");

    // Both knowledge graphs render — one per signed-in user. rich-user-active
    // has seeded nodes/edges; rich-user-second renders the (empty) graph
    // container, which is still the "graph surface works" signal (#382's
    // graph-container is the registered anchor).
    await page.goto("/dashboard");
    await expect(page.getByTestId("graph-container")).toBeVisible();

    await pageB.goto("/dashboard");
    await expect(pageB.getByTestId("graph-container")).toBeVisible();
  } finally {
    await contextB.close();
  }
});
