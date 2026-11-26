/**
 * #866 K13 regression journey: the retention check on Study, refused by the
 * learning loop's AI budget. The loop answers /posttest/start (and /answer)
 * past its per-minute rate limit with the 429 its handler builds —
 * `{detail: "ai budget reached", reset_at, scope, session_capped}` plus
 * Retry-After. The card used to print the raw "ai budget reached" under the
 * review queue's own pause banner; it now shows the same banner with the
 * reset time, and the next Open that gets through clears it.
 *
 * The 429 is fulfilled at the network, as quiz-errors.spec.ts does for its
 * caps: reaching LEARN_RATE_LIMIT_PER_MIN (1000 in this lane) would need a
 * doctored llm_usage table. Its body is the one
 * backend/services/ai_budget.py::budget_exceeded_handler writes.
 */
import { expect, test } from "./support/fixtures";
import { loopOffLane } from "./support/lane";
import { mintStorageState } from "./support/session";
import { USER_LOOP } from "./support/stack";

const START = "/api/learn/loop/posttest/start";

test("retention check: a budget pause on Open shows the pause banner with its reset time (#866 K13)", async ({ browser }) => {
  test.skip(loopOffLane, "loop path: default lane only");
  const context = await browser.newContext({ storageState: await mintStorageState(USER_LOOP, "Lou Loop") });
  const page = await context.newPage();
  await page.addInitScript(() => {
    localStorage.setItem("sapling_disclaimer_ack", "true");
  });
  try {
    const resetAt = new Date(Date.now() + 45_000).toISOString();
    let refusals = 0;
    await page.route(`**${START}`, async (route) => {
      if (refusals > 0) return route.continue();
      refusals += 1;
      await route.fulfill({
        status: 429,
        contentType: "application/json",
        headers: { "Retry-After": "45" },
        body: JSON.stringify({
          detail: "ai budget reached", reset_at: resetAt, scope: "rate_limit", session_capped: false, request_id: "e2e-k13",
        }),
      });
    });

    await page.goto("/study");
    await expect(page.getByTestId("retention-open")).toBeEnabled();
    await page.getByTestId("retention-open").click();
    const banner = page.getByTestId("retention-budget-paused");
    await expect(banner).toBeVisible();
    await expect(banner).toHaveAttribute("data-reset-at", resetAt);
    await expect(banner).toContainText("paused until");
    await expect(page.getByText("ai budget reached")).toHaveCount(0);
    await expect(page.getByTestId("retention-item")).toHaveCount(0); // nothing was posed
    expect(refusals).toBe(1);

    // The next Open reaches the real route: the pause clears.
    const opened = page.waitForResponse((r) => new URL(r.url()).pathname === START);
    await page.getByTestId("retention-open").click();
    expect((await opened).status()).toBe(200);
    await expect(page.getByTestId("retention-empty")).toBeVisible(); // a freshly seeded learner: nothing aged yet
    await expect(banner).toHaveCount(0);
  } finally {
    await context.close();
  }
});
