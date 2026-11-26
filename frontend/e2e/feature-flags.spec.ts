/**
 * Journey (#620): an admin gives one student a flag from /admin, and that
 * student's GET /api/flags reflects it; the rule is a real DB row.
 */
import { queryRaw } from "./support/db";
import { expect, killSwitchLane, test } from "./support/fixtures";
import { flagOffLane } from "./support/lane";
import { mintStorageState } from "./support/session";
import { FRONTEND_URL, USER_ACTIVE } from "./support/stack";

const USER_ADMIN = "rich-user-admin"; // seeded with the admin role

test("admin sets a user rule on hide_quiz and the student gets it (#620)", async ({ browser, page }) => {
  // Baseline: the student sees hide_quiz off.
  const before = await page.request.get(`${FRONTEND_URL}/api/flags`);
  expect((await before.json()).flags.hide_quiz).toBe("off");

  const adminState = await mintStorageState(USER_ADMIN, "Ada Admin");
  const adminCtx = await browser.newContext({ storageState: adminState });
  const admin = await adminCtx.newPage();
  await admin.goto(`${FRONTEND_URL}/admin`);
  await admin.getByTestId("admin-tab-flags").click();
  await admin.getByTestId("flag-row-hide_quiz").click();

  // Add a user rule through the API the tab uses (user search needs names
  // that the seed does not guarantee; the rules table is what we assert).
  const res = await admin.request.put(`${FRONTEND_URL}/api/admin/flags/hide_quiz/targets`, {
    data: { target_type: "user", target_id: USER_ACTIVE, variant: "on" },
  });
  expect(res.ok()).toBeTruthy();
  await admin.reload();
  await admin.getByTestId("admin-tab-flags").click();
  await admin.getByTestId("flag-row-hide_quiz").click();
  await expect(admin.getByTestId(`flag-target-row-hide_quiz-user-${USER_ACTIVE}`)).toBeVisible();

  const rows = await queryRaw(
    "select variant from feature_flag_targets where flag_key = $1 and target_type = 'user' and target_id = $2",
    ["hide_quiz", USER_ACTIVE],
  );
  expect(rows).toEqual([{ variant: "on" }]);

  // The cache is cleared on write in the same backend process.
  const after = await page.request.get(`${FRONTEND_URL}/api/flags`);
  expect((await after.json()).flags.hide_quiz).toBe("on");

  // The student check names the rule, in words.
  await admin.getByTestId("flag-explain-input-hide_quiz").fill(USER_ACTIVE);
  await admin.getByTestId("flag-explain-input-hide_quiz").press("Enter");
  await expect(admin.getByTestId("flag-explain-result-hide_quiz")).toContainText("Hidden: this student has their own override");
  await adminCtx.close();
});

test("hiding Quiz removes its Study option and redirects its route (#620)", async ({ browser, page }) => {
  await page.goto(`${FRONTEND_URL}/study`);
  await expect(page.getByRole("navigation", { name: "Study tools" }).getByRole("button", { name: "Quiz" })).toBeVisible();
  await expect(page.getByTestId("nav-link-quiz")).toHaveCount(0);

  // Hide Quiz for everyone, through the API the /admin tab uses.
  const adminState = await mintStorageState(USER_ADMIN, "Ada Admin");
  const adminCtx = await browser.newContext({ storageState: adminState });
  const res = await adminCtx.request.patch(`${FRONTEND_URL}/api/admin/flags/hide_quiz`, {
    data: { default_variant: "on", rollout_percent: 0, rollout_variant: null },
  });
  expect(res.ok()).toBeTruthy();
  await adminCtx.close();

  // Flags load once per page load: a fresh load picks the change up.
  await page.reload();
  await expect(page.getByTestId("nav-link-tree")).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Study tools" }).getByRole("button", { name: "Quiz" })).toHaveCount(0);
  await expect(page.getByTestId("nav-link-quiz")).toHaveCount(0);

  // A typed URL (and anything below it) lands on the dashboard.
  await page.goto(`${FRONTEND_URL}/quiz`);
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByTestId("app-shell")).toBeVisible();
  await expect(page.getByTestId("nav-link-quiz")).toHaveCount(0);
});

test("hiding Study redirects its tool pages too, /flashcards included (#870)", async ({ browser, page }) => {
  // Baseline: Flashcards is a Study page with a top-level path of its own. It
  // renders inside the shell and keeps the Study row in the nav.
  await page.goto(`${FRONTEND_URL}/flashcards`);
  await expect(page.getByTestId("app-shell")).toBeVisible();
  await expect(page.getByTestId("nav-link-study")).toBeVisible();
  await expect(page).toHaveURL(/\/flashcards(\?.*)?$/);

  // Hide Study for everyone, through the API the /admin tab uses.
  const adminState = await mintStorageState(USER_ADMIN, "Ada Admin");
  const adminCtx = await browser.newContext({ storageState: adminState });
  const res = await adminCtx.request.patch(`${FRONTEND_URL}/api/admin/flags/hide_study`, {
    data: { default_variant: "on", rollout_percent: 0, rollout_variant: null },
  });
  expect(res.ok()).toBeTruthy();
  await adminCtx.close();

  const flags = await page.request.get(`${FRONTEND_URL}/api/flags`);
  expect((await flags.json()).flags.hide_study).toBe("on");

  // Every Study URL lands on the dashboard: the hub, the Study Guide below
  // it, Flashcards outside it, and the retired `?mode=` links that redirect
  // to those two pages (a redirect onto a hidden page must not loop or stick).
  // /flashcards was once outside the shell route list: no flags were loaded
  // there, so it rendered with every /api/flashcards call 404ing.
  for (const path of [
    "/study",
    "/study/guide",
    "/flashcards",
    "/flashcards?course=CS101",
    "/study?mode=guide",
    "/study?mode=cards",
  ]) {
    await page.goto(`${FRONTEND_URL}${path}`);
    await expect(page, path).toHaveURL(/\/dashboard$/);
    await expect(page.getByTestId("app-shell"), path).toBeVisible();
    await expect(page.getByTestId("nav-link-tree"), path).toBeVisible();
    await expect(page.getByTestId("nav-link-study"), path).toHaveCount(0);
    await expect(page.getByTestId("error-fallback"), path).toHaveCount(0);
  }
});

// #866 K24: the learning loop's own flags answer under its gate. The student
// gets quiz_concept_plan by their own override, yet in the kill-switch lane the
// LEARNING_LOOP_ENABLED kill switch, and in the flag-off lane their
// learning_loop flag (forced off by SAPLING_FLAG_LEARNING_LOOP), turns it off:
// "Check a student" and the rows must say so, never the stored "On".
test("a learning-loop flag's student check and rows follow the loop's gate in every lane (#866 K24)", async ({ browser }) => {
  const adminState = await mintStorageState(USER_ADMIN, "Ada Admin");
  const adminCtx = await browser.newContext({ storageState: adminState });
  try {
    const res = await adminCtx.request.put(`${FRONTEND_URL}/api/admin/flags/quiz_concept_plan/targets`, {
      data: { target_type: "user", target_id: USER_ACTIVE, variant: "on" },
    });
    expect(res.ok()).toBeTruthy();
    const admin = await adminCtx.newPage();
    await admin.goto(`${FRONTEND_URL}/admin`);
    await admin.getByTestId("admin-tab-flags").click();

    // The rows: what every student gets, whatever is stored.
    await expect(admin.getByTestId("flag-requires-quiz_concept_plan")).toHaveText("Needs Learning loop");
    if (killSwitchLane) {
      await expect(admin.getByTestId("flag-state-learning_loop")).toHaveText("Off");
      await expect(admin.getByTestId("flag-forced-learning_loop")).toHaveText("Kill switch on");
      await expect(admin.getByTestId("flag-forced-quiz_concept_plan")).toHaveText("Kill switch on");
    } else if (flagOffLane) {
      await expect(admin.getByTestId("flag-state-learning_loop")).toHaveText("Off");
      await expect(admin.getByTestId("flag-forced-learning_loop")).toHaveText("Set on the server");
      await expect(admin.getByTestId("flag-state-quiz_concept_plan")).toHaveText("Off");
      await expect(admin.getByTestId("flag-forced-quiz_concept_plan")).toHaveText("Learning loop off");
    } else {
      // the default lane forces the loop on for every student (scripts/e2e-up.sh)
      await expect(admin.getByTestId("flag-state-learning_loop")).toHaveText("On");
      await expect(admin.getByTestId("flag-forced-learning_loop")).toHaveText("Set on the server");
      await expect(admin.getByTestId("flag-forced-quiz_concept_plan")).toHaveCount(0);
    }

    // Check a student: the rule that decided it, under the loop's gate.
    await admin.getByTestId("flag-row-quiz_concept_plan").click();
    await admin.getByTestId("flag-explain-input-quiz_concept_plan").fill(USER_ACTIVE);
    await admin.getByTestId("flag-explain-input-quiz_concept_plan").press("Enter");
    const result = admin.getByTestId("flag-explain-result-quiz_concept_plan");
    if (killSwitchLane) {
      await expect(result).toContainText(
        "Off: the LEARNING_LOOP_ENABLED kill switch turns the learning loop off for everyone",
      );
    } else if (flagOffLane) {
      await expect(result).toContainText(
        "Off: needs Learning loop, which is off for them — forced by the SAPLING_FLAG_LEARNING_LOOP environment variable",
      );
    } else {
      await expect(result).toContainText("On: this student has their own override");
    }
  } finally {
    await adminCtx.close();
  }
});
