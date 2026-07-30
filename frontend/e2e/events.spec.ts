/**
 * Journey #117 — observability events flow from real app actions into the
 * `events` table and out through the admin analytics API.
 *
 * API-level (no page): as the seeded student (the default storageState the
 * global setup mints for rich-user-active), drive two cheap real actions —
 * a bogus /api path (→ the RequestIDMiddleware error.4xx seam) and a note
 * created via POST /api/notes (→ the note.created seam). Then, as the seeded
 * admin (rich-user-admin holds the admin role per db/seed_local_rich.py;
 * authenticated via the same support/session.ts test-login helper the
 * multi-user journeys use), poll GET /api/admin/analytics/usage/summary until
 * note.created shows up in by_event_type, and assert the 404 row in
 * GET /api/admin/analytics/errors carries the full payload contract
 * (path / method / status_code / duration_ms).
 *
 * Timing: log_event is fire-and-forget onto an in-process queue; the worker
 * thread flushes ≤1s. So the rollup is polled with expect.poll (≤5s), never
 * a bare sleep. The 404 fires BEFORE the note create: the queue is FIFO, so
 * note.created visible ⇒ the earlier error.4xx row landed too.
 *
 * Isolation: `events` is NOT in support/db.ts's TRUNCATE_DENYLIST, so the
 * per-test reset starts this test from an empty events table — no from/to
 * scoping needed. A late flush from a prior test could still slip in after
 * the truncate, so the causal assertions key on values unique to THIS test
 * (the bogus path, the created note's id via queryRaw), not on bare counts.
 *
 * Privacy: the bogus request carries a query string; the error event must
 * record only the path — the query value must appear nowhere in the
 * analytics payloads.
 */
import { expect, test } from "./support/fixtures";
import { queryRaw } from "./support/db";
import { mintStorageState } from "./support/session";
import { FRONTEND_URL, USER_ACTIVE } from "./support/stack";

const USER_ADMIN = "rich-user-admin"; // seeded with the admin role
const BOGUS_PATH = "/api/e2e-observability-no-such-route";
const SECRET_QUERY = "e2e-secret-query-term";

test("app actions land in the events table and surface via /api/admin/analytics", async ({
  request,
  playwright,
}) => {
  // Sanity: the default storageState really authenticates as the student —
  // a pointed failure here beats a cryptic 401 on the note create below.
  const me = await request.get("/api/auth/me");
  expect(me.status(), await me.text()).toBe(200);

  // 1) A 404 with a query string → error.4xx (path only, never the query).
  //    Fired first so FIFO flushing guarantees it lands with/before the note.
  const bogus = await request.get(`${BOGUS_PATH}?q=${SECRET_QUERY}`);
  expect(bogus.status()).toBe(404);

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

    // 4) The 404 surfaces in /errors with the full payload contract.
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
          return errBody.errors.some((e) => e.path === BOGUS_PATH);
        },
        {
          timeout: 5_000,
          message: `the ${BOGUS_PATH} 404 should appear in /errors`,
        },
      )
      .toBe(true);

    const errRow = errBody.errors.find((e) => e.path === BOGUS_PATH)!;
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
