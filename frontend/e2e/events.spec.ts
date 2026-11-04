/**
 * Journey #117 — observability events flow from real app actions into the
 * `events` table and out through the admin analytics API.
 *
 * API-level (no page): as the seeded student (the default storageState the
 * global setup mints for rich-user-active), drive two cheap real actions —
 * a read of a note that does not exist (a ROUTED 404 → the RequestIDMiddleware
 * error.4xx seam) and a note created via POST /api/notes (→ the note.created
 * seam). Two paths that match no route at all are fired too (#690): one from
 * an ANONYMOUS context — scanner-shaped, deliberately NOT recorded — and one as
 * the signed-in student — our own client missing a route, still recorded.
 * This journey pins both. Then, as the seeded
 * admin (rich-user-admin holds the admin role per db/seed_local_rich.py;
 * authenticated via the same support/session.ts test-login helper the
 * multi-user journeys use), poll GET /api/admin/analytics/usage/summary until
 * note.created shows up in by_event_type, and assert the 404 row in
 * GET /api/admin/analytics/errors carries the full payload contract
 * (path / method / status_code / duration_ms).
 *
 * Timing: log_event is fire-and-forget onto an in-process queue; the worker
 * thread flushes ≤1s. So the rollup is polled with expect.poll (≤5s), never
 * a bare sleep. The 404s fire BEFORE the note create: the queue is FIFO, so
 * note.created visible ⇒ the earlier error.4xx rows landed too — and an
 * anonymous unrouted-404 row, had one been enqueued, would have landed with it.
 *
 * Isolation: `events` is NOT in support/db.ts's TRUNCATE_DENYLIST, so the
 * per-test reset starts this test from an empty events table — no from/to
 * scoping needed. A late flush from a prior test could still slip in after
 * the truncate, so the causal assertions key on values unique to THIS test
 * (the missing-note path, the created note's id via queryRaw), not on bare
 * counts.
 *
 * Privacy: the missing-note request carries a query string; the error event must
 * record only the path — the query value must appear nowhere in the
 * analytics payloads.
 */
import { expect, test } from "./support/fixtures";
import { queryRaw } from "./support/db";
import { mintStorageState } from "./support/session";
import { FRONTEND_URL, USER_ACTIVE } from "./support/stack";

const USER_ADMIN = "rich-user-admin"; // seeded with the admin role
// Routed: GET /api/notes/{note_id} answers its own 404 for an unknown id.
const MISSING_NOTE_PATH = "/api/notes/e2e-observability-no-such-note";
// Unrouted: matches nothing. ANONYMOUS (scanner-shaped) → no events row;
// the same miss from a signed-in client (a typo'd /api URL) → a row (#690).
const UNROUTED_PATH = "/api/e2e-observability-no-such-route";
const AUTHED_UNROUTED_PATH = "/api/e2e-observability-authed-no-such-route";
const SECRET_QUERY = "e2e-secret-query-term";

test("app actions land in the events table and surface via /api/admin/analytics", async ({
  request,
  playwright,
}) => {
  // Sanity: the default storageState really authenticates as the student —
  // a pointed failure here beats a cryptic 401 on the note create below.
  const me = await request.get("/api/auth/me");
  expect(me.status(), await me.text()).toBe(200);

  // 1) A routed 404 with a query string → error.4xx (path only, never the
  //    query), and an unrouted 404 → nothing. Both fired first so FIFO
  //    flushing guarantees they land with/before the note.
  // Explicitly EMPTY storageState: Playwright Test hands its `use` options
  // (the student's storageState included) to playwright.request.newContext
  // as defaults, so omitting it would sign this "anonymous" request in.
  const anon = await playwright.request.newContext({
    baseURL: FRONTEND_URL,
    storageState: { cookies: [], origins: [] },
  });
  try {
    const unrouted = await anon.get(UNROUTED_PATH);
    expect(unrouted.status()).toBe(404);
  } finally {
    await anon.dispose();
  }
  const authedUnrouted = await request.get(AUTHED_UNROUTED_PATH);
  expect(authedUnrouted.status()).toBe(404);
  const missing = await request.get(
    `${MISSING_NOTE_PATH}?user_id=${USER_ACTIVE}&q=${SECRET_QUERY}`,
  );
  expect(missing.status(), await missing.text()).toBe(404);

  // 2) One cheap real action through the API → note.created.
  const noteRes = await request.post("/api/notes", {
    data: {
      user_id: USER_ACTIVE,
      course_id: "rich-course-math210", // seeded enrollment of rich-user-active
      title: "E2E observability note",
      body: "Body so has_body is true.",
    },
  });
  expect(noteRes.status(), await noteRes.text()).toBe(200);
  const noteId = ((await noteRes.json()) as { id: string }).id;
  expect(noteId).toBeTruthy();

  // 3) As the seeded admin, poll the rollup until the flush lands.
  const admin = await playwright.request.newContext({
    baseURL: FRONTEND_URL,
    storageState: await mintStorageState(USER_ADMIN, "Ada Admin"),
  });
  try {
    await expect
      .poll(
        async () => {
          const res = await admin.get("/api/admin/analytics/usage/summary");
          if (!res.ok()) return -1; // e.g. transient during flush; keep polling
          const body = (await res.json()) as {
            by_event_type: Array<{ event_type: string; count: number }>;
          };
          return (
            body.by_event_type.find((r) => r.event_type === "note.created")
              ?.count ?? 0
          );
        },
        {
          timeout: 5_000,
          message:
            "note.created should appear in /usage/summary by_event_type " +
            "(the events worker flushes ≤1s)",
        },
      )
      .toBeGreaterThan(0);

    // Causality, not just counts: THIS test's note produced THIS event row
    // (DB assert via support/db.ts, the house pattern). The payload carries
    // ids/booleans only — never the title or body.
    const noteEvents = await queryRaw(
      "SELECT payload FROM events " +
        "WHERE event_type = 'note.created' AND user_id = $1",
      [USER_ACTIVE],
    );
    const mine = noteEvents.find(
      (r) => (r.payload as { note_id?: string }).note_id === noteId,
    );
    expect(mine, `no note.created event for note ${noteId}`).toBeTruthy();
    expect(mine!.payload).toMatchObject({
      note_id: noteId,
      course_id: "rich-course-math210",
      has_body: true,
    });
    expect(JSON.stringify(mine!.payload)).not.toContain("E2E observability note");
    expect(JSON.stringify(mine!.payload)).not.toContain("has_body is true");

    // The ANONYMOUS unrouted 404 was never recorded (#690): note.created is
    // visible and the queue is FIFO, so a row for it would already be here.
    const unroutedRows = await queryRaw(
      "SELECT 1 FROM events WHERE payload->>'path' = $1",
      [UNROUTED_PATH],
    );
    expect(unroutedRows, "an anonymous unrouted 404 must not write an events row").toHaveLength(0);
    // …while the signed-in client's unrouted 404 was, attributed to nobody
    // (no handler ran, so no session was decoded) and with no route template.
    const authedRows = await queryRaw(
      "SELECT event_type, payload FROM events WHERE payload->>'path' = $1",
      [AUTHED_UNROUTED_PATH],
    );
    expect(authedRows, "a signed-in client's unrouted 404 must still be recorded").toHaveLength(1);
    expect(authedRows[0].event_type).toBe("error.4xx");
    expect(authedRows[0].payload).not.toHaveProperty("route");

    // 4) The routed 404 surfaces in /errors with the full payload contract.
    let errBody: {
      errors: Array<{
        event_type: string;
        path?: string;
        method?: string;
        status_code?: number;
        duration_ms?: number;
      }>;
    } = { errors: [] };
    await expect
      .poll(
        async () => {
          const res = await admin.get("/api/admin/analytics/errors");
          if (!res.ok()) return false;
          errBody = (await res.json()) as typeof errBody;
          return errBody.errors.some((e) => e.path === MISSING_NOTE_PATH);
        },
        {
          timeout: 5_000,
          message: `the ${MISSING_NOTE_PATH} 404 should appear in /errors`,
        },
      )
      .toBe(true);

    const errRow = errBody.errors.find((e) => e.path === MISSING_NOTE_PATH)!;
    expect(errRow.event_type).toBe("error.4xx");
    expect(errRow.method).toBe("GET");
    expect(errRow.status_code).toBe(404);
    expect(typeof errRow.duration_ms).toBe("number");

    // The query string never entered any analytics payload.
    expect(JSON.stringify(errBody)).not.toContain(SECRET_QUERY);
  } finally {
    await admin.dispose();
  }
});
