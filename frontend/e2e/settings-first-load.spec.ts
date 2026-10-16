/**
 * Journey: a first-ever /settings load creates the settings row without a
 * 500 (#674).
 *
 * Settings.tsx loads `GET /api/profile/{id}/settings` and
 * `GET /api/profile/{id}` in parallel (Promise.all). Both reach
 * routes/profile.py::_get_or_create_settings; for a user with no
 * `user_settings` row both SELECTs came back empty, both INSERTed, and the
 * loser's PostgREST 409 surfaced as a 500 (the logscan oracle's finding on
 * the first journey that opened /settings). The fix is an ON CONFLICT DO
 * NOTHING create, so both calls must now answer 200 and exactly one row must
 * exist afterwards.
 *
 * The seeded USER_ACTIVE has no `user_settings` row after the per-test reset,
 * which is what makes this the race's first-load path — the precondition is
 * asserted, so a seed change that pre-creates the row fails loudly here
 * instead of silently turning this into a warm-load test.
 */
import { queryRaw } from "./support/db";
import { expect, test } from "./support/fixtures";
import { USER_ACTIVE } from "./support/stack";

const settingsRows = async () =>
  Number(
    (
      await queryRaw("SELECT count(*)::int AS n FROM user_settings WHERE user_id = $1", [
        USER_ACTIVE,
      ])
    )[0].n,
  );

test("first /settings load answers 200 on both parallel profile calls (#674)", async ({
  page,
}) => {
  expect(await settingsRows(), "precondition: no user_settings row yet").toBe(0);

  const profileStatuses: { url: string; status: number }[] = [];
  page.on("response", (res) => {
    const path = new URL(res.url()).pathname;
    if (path === `/api/profile/${USER_ACTIVE}` || path === `/api/profile/${USER_ACTIVE}/settings`) {
      profileStatuses.push({ url: path, status: res.status() });
    }
  });

  const settingsLoaded = page.waitForResponse(
    (res) => new URL(res.url()).pathname === `/api/profile/${USER_ACTIVE}/settings`,
  );
  const profileLoaded = page.waitForResponse(
    (res) => new URL(res.url()).pathname === `/api/profile/${USER_ACTIVE}`,
  );
  await page.goto("/settings");
  await Promise.all([settingsLoaded, profileLoaded]);

  expect(profileStatuses.length).toBeGreaterThanOrEqual(2);
  for (const { url, status } of profileStatuses) {
    expect(status, `${url} must not 500 on a first load`).toBe(200);
  }
  expect(await settingsRows()).toBe(1);
});
