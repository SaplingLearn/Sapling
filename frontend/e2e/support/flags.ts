/**
 * Turn a #620 feature flag on for one student through the admin API the /admin
 * tab uses (the same path feature-flags.spec.ts drives). The fixtures re-seed
 * before every test, so a spec sets the flags it needs each time.
 */
import type { Browser } from "@playwright/test";
import { expect } from "@playwright/test";

import { mintStorageState } from "./session";
import { FRONTEND_URL } from "./stack";

const USER_ADMIN = "rich-user-admin"; // seeded with the admin role

export async function setUserFlag(browser: Browser, key: string, userId: string, variant: string): Promise<void> {
  const adminCtx = await browser.newContext({ storageState: await mintStorageState(USER_ADMIN, "Ada Admin") });
  const res = await adminCtx.request.put(`${FRONTEND_URL}/api/admin/flags/${key}/targets`, {
    data: { target_type: "user", target_id: userId, variant },
  });
  expect(res.ok(), `PUT /api/admin/flags/${key}/targets`).toBeTruthy();
  await adminCtx.close();
}
