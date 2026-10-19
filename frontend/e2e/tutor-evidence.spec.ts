/**
 * Visual evidence for redesign prompt 04 (the Clov tutor): real fixture data
 * at 1440 / 768 / 390 / 320 px for the start, check-in, plan approval, active,
 * knowledge check, history, context (goal & plan, map), Stop / interrupted /
 * Retry, offline and budget-pause states.
 *
 * Gated on TUTOR_EVIDENCE_DIR exactly as gallery-shots.spec.ts is gated on
 * GALLERY_SHOTS_DIR: unset, the normal lane collects these and skips them.
 * Set, it writes `<state>-<width>.png` there. It asserts only what it needs
 * to reach each state; the behaviour is pinned by tutor-view.spec.ts and the
 * unit suites.
 */
import type { Browser, Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

import { expect, killSwitchLane, test } from "./support/fixtures";
import { setUserFlag } from "./support/flags";
import { learningParams } from "./support/params";
import { mintStorageState } from "./support/session";
import { USER_CAPPED, USER_LOOP } from "./support/stack";

const OUT_DIR = process.env.TUTOR_EVIDENCE_DIR?.trim();
const WIDTHS = [1440, 768, 390, 320] as const;
/** Must match backend/agents/function_handlers_e2e.py::E2E_GRADER_CORRECT_TOKEN */
const GRADER_CORRECT_TOKEN = "E2E_GRADER_CORRECT";
const WORKING_ATTEMPT = "working: I think it is the value the item names";

test.skip(!OUT_DIR, "visual evidence: set TUTOR_EVIDENCE_DIR to capture");
test.skip(killSwitchLane, "loop path: default lane only");

async function signIn(browser: Browser, userId: string, name: string) {
  const context = await browser.newContext({
    storageState: await mintStorageState(userId, name),
    viewport: { width: 1440, height: 900 },
  });
  const page = await context.newPage();
  await page.addInitScript(() => {
    localStorage.setItem("sapling_disclaimer_ack", "true");
  });
  return { context, page };
}

/** The current state at every width (what the viewport shows), then back to desktop. */
async function shoot(page: Page, state: string) {
  fs.mkdirSync(OUT_DIR!, { recursive: true });
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: width < 768 ? 844 : 900 });
    await page.waitForTimeout(450);
    await page.screenshot({ path: path.join(OUT_DIR!, `${state}-${width}.png`) });
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForTimeout(300);
}

test("tutor evidence: start, check-in, plan, active, check, history, context, interruption, offline", async ({ browser }) => {
  test.setTimeout(420_000);
  const P = await learningParams(["PROBE_SESSION_CAP"]);
  await setUserFlag(browser, "tutor_view", USER_LOOP, "on");
  const { context, page } = await signIn(browser, USER_LOOP, "Lou Loop");
  const root = page.getByTestId("loop-phase");

  await page.goto("/learn?view=tutor");
  await expect(page.getByTestId("tutor-welcome")).toBeVisible();
  await shoot(page, "01-start-welcome");

  await page.getByTestId("tutor-welcome-start").click();
  await expect(page.getByTestId("loop-probe-item")).toBeVisible();
  await shoot(page, "02-check-in");

  let answered = 0;
  while ((await root.getAttribute("data-phase")) === "probe" && answered < Number(P.PROBE_SESSION_CAP)) {
    const item = page.getByTestId("loop-probe-item");
    await expect(item).toBeVisible();
    const qh = await item.getAttribute("data-question-hash");
    const difficulty = Number(await item.getAttribute("data-difficulty"));
    await page.getByTestId("loop-probe-input").fill(difficulty === 1 ? GRADER_CORRECT_TOKEN : WORKING_ATTEMPT);
    await page.getByTestId("loop-probe-submit").click();
    answered += 1;
    await expect.poll(async () => (await root.getAttribute("data-phase")) !== "probe" ||
      (await page.getByTestId("loop-probe-reference").isVisible()) ||
      (await item.getAttribute("data-question-hash")) !== qh).toBe(true);
    if (await page.getByTestId("loop-probe-reference").isVisible()) {
      await page.getByTestId("loop-probe-next").click();
      // /probe/next may end the check-in: wait for the next item or the plan.
      await expect.poll(async () => (await root.getAttribute("data-phase")) !== "probe" ||
        (await item.getAttribute("data-question-hash")) !== qh).toBe(true);
    }
  }
  await expect(root).toHaveAttribute("data-phase", "plan");
  await expect(page.locator("[data-testid^='loop-plan-concept-']").first()).toBeVisible();
  await shoot(page, "03-plan-approval");

  await page.getByTestId("loop-plan-approve").click();
  await expect(root).toHaveAttribute("data-phase", "teach");
  await page.getByTestId("loop-teach-start").click();
  await expect(page.getByTestId("tutor-stop")).toHaveCount(0, { timeout: 30_000 });
  await expect(page.getByTestId("loop-check-me")).toBeEnabled();
  await shoot(page, "04-active");

  await page.getByTestId("tutor-context-goal").click();
  await expect(page.getByTestId("tutor-goal-plan")).toBeVisible();
  await shoot(page, "05-context-goal-plan");
  await page.keyboard.press("Escape").catch(() => {});
  await page.getByTestId("tutor-context-map").click();
  await expect(page.getByTestId("tutor-map")).toBeVisible();
  await shoot(page, "06-context-map");
  await page.getByTestId("tutor-context-materials").click();
  await expect(page.getByTestId("tutor-materials")).toBeVisible();
  await shoot(page, "07-context-materials");
  await page.getByTestId("tutor-context-close").click();

  await page.getByTestId("tutor-history-open").click();
  await expect(page.getByTestId("tutor-history")).toBeVisible();
  await shoot(page, "08-history");
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("tutor-history")).toHaveCount(0);

  // Stop before the reply arrives (held in the browser), then the interrupted turn with Retry.
  let entered = () => {};
  let release = () => {};
  const requested = new Promise<void>((resolve) => { entered = resolve; });
  const held = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/api/learn/loop/chat/stream", async (route) => {
    entered();
    await held;
    try { await route.abort(); } catch { /* already aborted by the page */ }
  });
  await page.getByTestId("tutor-input").fill("Why does the base case come first?");
  await page.getByTestId("tutor-send").click();
  await requested;
  await expect(page.getByTestId("tutor-stop")).toBeVisible();
  await shoot(page, "09-streaming-stop");
  await page.getByTestId("tutor-stop").click();
  await expect(page.getByTestId("tutor-interrupted")).toBeVisible();
  release();
  await page.unroute("**/api/learn/loop/chat/stream");
  await shoot(page, "10-interrupted-retry");
  await page.getByTestId("tutor-retry").click();
  await expect(page.getByTestId("tutor-interrupted")).toHaveCount(0);
  await expect(page.getByTestId("tutor-stop")).toHaveCount(0, { timeout: 30_000 });

  // Offline: the turn says so and nothing is queued.
  await context.setOffline(true);
  await page.getByTestId("tutor-input").fill("Am I still connected?");
  await page.getByTestId("tutor-send").click();
  await expect(page.getByTestId("tutor-interrupted")).toContainText("offline");
  await shoot(page, "11-offline");
  await context.setOffline(false);

  // The explicit knowledge check.
  await page.getByTestId("loop-check-me").click();
  await expect(page.getByTestId("loop-check-prompt")).toBeVisible();
  await shoot(page, "12-knowledge-check");

  // The studio view of the same session, for comparison.
  await page.getByTestId("tutor-menu").click();
  await page.getByTestId("tutor-menu-studio").click();
  await expect(page.getByTestId("loop-heading")).toBeVisible();
  await shoot(page, "13-same-session-in-studio");
  await context.close();
});

test("tutor evidence: budget pause", async ({ browser }) => {
  test.setTimeout(120_000);
  await setUserFlag(browser, "tutor_view", USER_CAPPED, "on");
  const { context, page } = await signIn(browser, USER_CAPPED, "Casey Cap");
  await page.goto("/learn?view=tutor");
  await expect(page.getByTestId("tutor-welcome")).toBeVisible();
  await page.getByTestId("tutor-welcome-start").click();
  await expect(page.getByTestId("loop-budget-paused")).toBeVisible();
  await shoot(page, "14-budget-pause");
  await context.close();
});
