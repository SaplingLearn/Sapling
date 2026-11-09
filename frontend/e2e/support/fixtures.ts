/**
 * Fixture-extended `test` for the E2E lane (#385). Specs import { test,
 * expect } from here — never from @playwright/test directly — so every test
 * automatically gets DB isolation: TRUNCATE mutable tables + restore the
 * rich seed baseline BEFORE the test runs (support/db.ts). Reset-before
 * (not after) means a crashed or interrupted run can never leak state into
 * the next one — the same posture as the #397 pytest integration fixtures.
 */
import { test as base, expect } from "@playwright/test";

import { resetDb } from "./db";

export const test = base.extend<{ dbReset: void }>({
  dbReset: [
    async ({}, use) => {
      await resetDb();
      await use();
    },
    { auto: true },
  ],
});

export { expect };
