/**
 * Journey (#866 K59): a check-item decision is in Admin → Audit log.
 *
 * Approving a learning-loop check item in the review queue
 * (/api/admin/check-items) changes what students are served, and a retire
 * voids their results, so the decision must be on the record staff read for
 * "who did what": the admin_audit_log rows the Audit tab lists. The seeded
 * admin approves one of the rich seed's check items (course assets, seeded in
 * every lane: the review queue is a staff tool, never behind the loop's flag);
 * the row is asserted in the database and on the Audit tab.
 */
import { queryRaw } from "./support/db";
import { expect, test } from "./support/fixtures";
import { mintStorageState } from "./support/session";
import { FRONTEND_URL } from "./support/stack";

const USER_ADMIN = "rich-user-admin"; // seeded with the admin role

test("approving a check item is recorded in Admin → Audit log (#866 K59)", async ({ browser }) => {
  const [item] = await queryRaw(
    "SELECT id, course_id, question_hash FROM check_items ORDER BY id LIMIT 1",
  );
  expect(item, "the rich seed stores the loop's check items").toBeTruthy();

  const adminState = await mintStorageState(USER_ADMIN, "Ada Admin");
  const adminCtx = await browser.newContext({ storageState: adminState });
  try {
    const res = await adminCtx.request.post(
      `${FRONTEND_URL}/api/admin/check-items/${encodeURIComponent(String(item.id))}/approve`,
    );
    expect(res.status(), await res.text()).toBe(200);

    const rows = await queryRaw(
      "SELECT actor_id, target_type, target_id, payload FROM admin_audit_log WHERE action = 'check_item.approve'",
    );
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ actor_id: USER_ADMIN, target_type: "check_item", target_id: item.id });
    expect(rows[0].payload).toMatchObject({
      course_id: item.course_id,
      question_hash: item.question_hash,
      finished: true,
    });

    // The Audit tab lists every admin_audit_log row: the decision is on it.
    const admin = await adminCtx.newPage();
    await admin.goto(`${FRONTEND_URL}/admin`);
    await admin.getByTestId("admin-tab-audit").click();
    await expect(admin.getByText("check_item.approve")).toBeVisible();
  } finally {
    await adminCtx.close();
  }
});
