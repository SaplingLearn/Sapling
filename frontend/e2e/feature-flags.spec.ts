/**
 * Journey (#620): an admin gives one student a flag from /admin, and that
 * student's GET /api/flags reflects it; the rule is a real DB row.
 */
import { queryRaw } from "./support/db";
import { expect, test } from "./support/fixtures";
import { mintStorageState } from "./support/session";
import { FRONTEND_URL, USER_ACTIVE } from "./support/stack";

const USER_ADMIN = "rich-user-admin"; // seeded with the admin role

test("admin sets a user rule on hide_quiz and the student gets it (#620)", async ({ browser, page }) => {
  const adminState = await mintStorageState(USER_ADMIN, "Ada Admin");
  const adminCtx = await browser.newContext({ storageState: adminState });
  const baseline = await adminCtx.request.patch(`${FRONTEND_URL}/api/admin/flags/hide_quiz`, {
    data: { default_variant: "off", rollout_percent: 0, rollout_variant: null },
  });
  expect(baseline.ok()).toBeTruthy();
  // Baseline: the student sees hide_quiz off.
  const before = await page.request.get(`${FRONTEND_URL}/api/flags`);
  expect((await before.json()).flags.hide_quiz).toBe("off");

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

test("hiding a feature drops it from the nav and redirects its route (#620)", async ({ browser, page }) => {
  const adminState = await mintStorageState(USER_ADMIN, "Ada Admin");
  const adminCtx = await browser.newContext({ storageState: adminState });
  // DB reset removes the preceding test's user override, but the backend's
  // in-process flag snapshot outlives that reset. Establish the off baseline
  // through the real admin write, which also invalidates that snapshot.
  const baseline = await adminCtx.request.patch(`${FRONTEND_URL}/api/admin/flags/hide_quiz`, {
    data: { default_variant: "off", rollout_percent: 0, rollout_variant: null },
  });
  expect(baseline.ok()).toBeTruthy();
  await page.goto(`${FRONTEND_URL}/dashboard`);
  // The approved Pen sidebar keeps secondary tools in the account menu.
  // Open that real destination list so absence cannot pass simply because
  // the menu is collapsed.
  await page.getByRole("button", { name: "Account and more tools" }).click();
  await expect(page.getByTestId("nav-link-quiz")).toBeVisible();

  // Hide Quiz for everyone, through the API the /admin tab uses.
  const res = await adminCtx.request.patch(`${FRONTEND_URL}/api/admin/flags/hide_quiz`, {
    data: { default_variant: "on", rollout_percent: 0, rollout_variant: null },
  });
  expect(res.ok()).toBeTruthy();
  await adminCtx.close();

  // Flags load once per page load: a fresh load picks the change up.
  await page.reload();
  await expect(page.getByTestId("nav-link-tree")).toBeVisible();
  await page.getByRole("button", { name: "Account and more tools" }).click();
  await expect(page.getByRole("region", { name: "More tools" })).toBeVisible();
  await expect(page.getByTestId("nav-link-quiz")).toHaveCount(0);

  // A typed URL (and anything below it) lands on the dashboard.
  await page.goto(`${FRONTEND_URL}/quiz`);
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByTestId("app-shell")).toBeVisible();
  await page.getByRole("button", { name: "Account and more tools" }).click();
  await expect(page.getByRole("region", { name: "More tools" })).toBeVisible();
  await expect(page.getByTestId("nav-link-quiz")).toHaveCount(0);
});
