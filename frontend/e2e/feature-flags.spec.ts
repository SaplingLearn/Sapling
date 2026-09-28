/**
 * Journey (#620): an admin gives one student a flag from /admin, and that
 * student's GET /api/flags reflects it; the rule is a real DB row.
 */
import { queryRaw } from "./support/db";
import { expect, test } from "./support/fixtures";
import { mintStorageState } from "./support/session";
import { FRONTEND_URL, USER_ACTIVE } from "./support/stack";

const USER_ADMIN = "rich-user-admin"; // seeded with the admin role

test("admin sets a user rule on learning_loop and the student gets it (#620)", async ({ browser, page }) => {
  // Baseline: the student sees learning_loop off.
  const before = await page.request.get(`${FRONTEND_URL}/api/flags`);
  expect((await before.json()).flags.learning_loop).toBe("off");

  const adminState = await mintStorageState(USER_ADMIN, "Ada Admin");
  const adminCtx = await browser.newContext({ storageState: adminState });
  const admin = await adminCtx.newPage();
  await admin.goto(`${FRONTEND_URL}/admin`);
  await admin.getByTestId("admin-tab-flags").click();
  await admin.getByTestId("flag-row-learning_loop").click();

  // Add a user rule through the API the tab uses (user search needs names
  // that the seed does not guarantee; the rules table is what we assert).
  const res = await admin.request.put(`${FRONTEND_URL}/api/admin/flags/learning_loop/targets`, {
    data: { target_type: "user", target_id: USER_ACTIVE, variant: "on" },
  });
  expect(res.ok()).toBeTruthy();
  await admin.reload();
  await admin.getByTestId("admin-tab-flags").click();
  await admin.getByTestId("flag-row-learning_loop").click();
  await expect(admin.getByTestId(`flag-target-row-learning_loop-user-${USER_ACTIVE}`)).toBeVisible();

  const rows = await queryRaw(
    "select variant from feature_flag_targets where flag_key = $1 and target_type = 'user' and target_id = $2",
    ["learning_loop", USER_ACTIVE],
  );
  expect(rows).toEqual([{ variant: "on" }]);

  // The cache is cleared on write in the same backend process.
  const after = await page.request.get(`${FRONTEND_URL}/api/flags`);
  expect((await after.json()).flags.learning_loop).toBe("on");

  // The explain box names the rule.
  await admin.getByTestId("flag-explain-input-learning_loop").fill(USER_ACTIVE);
  await admin.getByTestId("flag-explain-input-learning_loop").press("Enter");
  await expect(admin.getByTestId("flag-explain-result-learning_loop")).toContainText("on (user");
  await adminCtx.close();
});
