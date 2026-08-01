/**
 * Journey: earning XP moves the hero card, the leaderboard and the activity
 * tab (Task 17, closing out the gamification/XP/achievements plan).
 *
 * Unlike upload.spec.ts/quiz.spec.ts, this journey doesn't drive the action
 * that earns XP through the UI — there is no single "do a thing, get XP"
 * control to click, and every real earning path (session/quiz/upload/notes)
 * already has its own journey. Instead it mints XP directly the way the app
 * does, via support/db.ts::awardXp (a port of
 * backend/services/xp_service.py::award_xp), and asserts the READ side:
 * the hero card's total XP goes up, the leaderboard shows the viewer's row,
 * and the activity tab's week-total tile reflects the new event.
 *
 * USER_ACTIVE is the storageState session every spec starts from
 * (global-setup.ts) — the same seeded user awardXp grants to here.
 */
import { awardXp } from "./support/db";
import { expect, test } from "./support/fixtures";
import { USER_ACTIVE } from "./support/stack";

test("earning XP moves the hero card and the leaderboard", async ({ page }) => {
  await page.goto("/achievements");
  await expect(page.getByTestId("gamification-hero")).toBeVisible();
  const before = Number(await page.getByTestId("gamification-total-xp").innerText());

  await awardXp(USER_ACTIVE, "quiz_completed", "quiz", "e2e-quiz-1");
  await page.reload();

  await expect
    .poll(async () => Number(await page.getByTestId("gamification-total-xp").innerText()))
    .toBeGreaterThan(before);

  await page.getByTestId("achievements-tab-leaderboard").click();
  await expect(page.getByTestId("leaderboard-row-you")).toBeVisible();

  await page.getByTestId("achievements-tab-activity").click();
  await expect(page.getByTestId("activity-week-total")).not.toHaveText("0");
});
