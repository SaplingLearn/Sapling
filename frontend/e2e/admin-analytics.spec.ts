/**
 * Admin analytics dashboard journey (#122, over the #121 data layer).
 *
 * The journey: as the seeded student, fire one 404 (→ error.4xx) and create
 * one note (→ note.created) — the same two cheap real actions events.spec.ts
 * uses, FIFO-ordered so the error lands with/before the note. Then, as the
 * seeded admin (rich-user-admin via mintStorageState), poll the rollup API
 * until the queue worker flushes (never a bare sleep), open /admin/analytics
 * in a real browser context, and assert the DASHBOARD renders the data: the
 * events-per-day and errors-per-day charts, the top-event-types entry, the
 * error-feed row for the bogus path, the cost group-by toggle driving its
 * heading, and the range presets re-running the panels. A student visiting
 * the route gets the refusal screen.
 *
 * Isolation: `events` is not in TRUNCATE_DENYLIST, so this test starts from
 * an empty events table; causal assertions key on values unique to this test
 * (the bogus path, the created note's id via queryRaw), not bare counts.
 */
import { expect, test } from "./support/fixtures";
import { queryRaw } from "./support/db";
import { mintStorageState } from "./support/session";
import { FRONTEND_URL, USER_ACTIVE } from "./support/stack";

const USER_ADMIN = "rich-user-admin"; // seeded with the admin role
const BOGUS_PATH = "/api/e2e-analytics-dashboard-no-such-route";

test("admin analytics dashboard renders live usage, errors, and controls (#122)", async ({
  request,
  playwright,
  browser,
  page,
}) => {
  // Sanity: the default storageState authenticates as the student.
  const me = await request.get("/api/auth/me");
  expect(me.status(), await me.text()).toBe(200);

  // 1) Generate rows: a 404 first (FIFO), then one real note create.
  expect((await request.get(BOGUS_PATH)).status()).toBe(404);
  const noteRes = await request.post("/api/notes", {
    data: {
      user_id: USER_ACTIVE,
      course_id: "rich-course-math210", // seeded enrollment of rich-user-active
      title: "E2E dashboard note",
      body: "Body so has_body is true.",
    },
  });
  expect(noteRes.status(), await noteRes.text()).toBe(200);
  const noteId = ((await noteRes.json()) as { id: string }).id;
  expect(noteId).toBeTruthy();

  // 2) Non-admin gate: the student sees the refusal screen, not the panels.
  await page.goto(`${FRONTEND_URL}/admin/analytics`);
  await expect(page.getByText(/don't have admin access/i)).toBeVisible();

  // 3) As the admin, poll the API until the flush lands, then drive the UI.
  const adminState = await mintStorageState(USER_ADMIN, "Ada Admin");
  const adminReq = await playwright.request.newContext({
    baseURL: FRONTEND_URL,
    storageState: adminState,
  });
  const adminCtx = await browser.newContext({ storageState: adminState });
  try {
    await expect
      .poll(
        async () => {
          const res = await adminReq.get("/api/admin/analytics/usage/summary");
          if (!res.ok()) return -1;
          const body = (await res.json()) as {
            by_event_type: Array<{ event_type: string; count: number }>;
          };
          return body.by_event_type.find((r) => r.event_type === "note.created")?.count ?? 0;
        },
        {
          timeout: 5_000,
          message: "note.created should appear in /usage/summary (worker flushes ≤1s)",
        },
      )
      .toBeGreaterThan(0);

    const adminPage = await adminCtx.newPage();
    await adminPage.goto(`${FRONTEND_URL}/admin/analytics`);

    // Charts render from the day series (lazy-loaded components).
    await expect(adminPage.getByRole("img", { name: "Events per day" })).toBeVisible();
    await expect(adminPage.getByRole("img", { name: "Errors per day" })).toBeVisible();
    // The generated rows surface: top-event-types entry + the error-feed row.
    await expect(adminPage.getByText("note.created").first()).toBeVisible();
    await expect(adminPage.getByText(BOGUS_PATH).first()).toBeVisible();

    // The cost group-by toggle drives its heading (and the group_by query).
    await adminPage.getByTestId("admin-analytics-cost-group-model").click();
    await expect(adminPage.getByText("Cost by model")).toBeVisible();

    // A range preset re-runs every panel without breaking the page.
    await adminPage.getByTestId("admin-analytics-range-7d").click();
    await expect(adminPage.getByRole("img", { name: "Events per day" })).toBeVisible();

    // 4) DB causality: THIS test's note produced THIS event row.
    const rows = await queryRaw(
      "SELECT payload FROM events WHERE event_type = 'note.created' AND user_id = $1",
      [USER_ACTIVE],
    );
    const mine = rows.find((r) => (r.payload as { note_id?: string }).note_id === noteId);
    expect(mine, `no note.created event for note ${noteId}`).toBeTruthy();
  } finally {
    await adminCtx.close();
    await adminReq.dispose();
  }
});
