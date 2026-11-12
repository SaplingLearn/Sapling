/**
 * Journey #289 — the first-run onboarding funnel renders, advances, and is
 * enforced.
 *
 * `/onboarding` renders BARE — its route sits outside `(shell)`, so it has no
 * ShellFrame, no nav and no `<main>` padding to inherit — and it is the first
 * thing a newly approved student sees. Since #800 the funnel is the Claude
 * Design flow: an intro, then nine screens over six chapters.
 *
 * Since the 2026-11-12 onboarding decisions it is also a gate: sign in first
 * (no guest onboarding), and onboarding is enforced. The middleware (and the
 * shell's OnboardingGate behind it) sends an approved student who hasn't
 * finished onboarding from the app to /onboarding, and one who has finished
 * from /onboarding to /dashboard.
 *
 * This stays a smoke journey, not a full walkthrough: each screen's rules
 * (birthday, courses, the legal scroll-to-accept, the save's failures) are
 * unit-tested in Onboarding.test.tsx, and a long scripted click-path would
 * break on every copy tweak. What it pins is the part that must not
 * regress: the gate in both directions, the screen mounting with a real
 * layout box, the step machine driving the frame, and the exits — a Back
 * button and a Sign out that are visible (Back used to be a hidden,
 * tabIndex -1 key hint on phones).
 *
 * USER_NEW is the seeded approved account with onboarding_completed=False;
 * the default storageState (USER_ACTIVE) has finished onboarding.
 */
import { expect, test } from "./support/fixtures";
import { mintStorageState } from "./support/session";
import { FRONTEND_URL, USER_NEW } from "./support/stack";

test("the onboarding funnel renders for an un-onboarded user, with Back and Sign out (#289)", async ({ browser }) => {
  const storageState = await mintStorageState(USER_NEW, "Rich New");
  const context = await browser.newContext({ storageState });
  const page = await context.newPage();

  try {
    await page.goto(`${FRONTEND_URL}/onboarding`);
    await expect(page).toHaveURL(/\/onboarding$/);

    const gate = page.getByTestId("onboarding-gate");
    await expect(gate).toBeVisible();

    // The root must actually occupy the screen: it renders bare (no shell),
    // so a broken layout collapses it, which no unit test would catch.
    const box = await gate.boundingBox();
    expect(box, "the onboarding root should have a layout box").not.toBeNull();
    expect(box!.height, "onboarding must fill the viewport, not collapse").toBeGreaterThan(400);

    // After the intro, the first screen asks for a name, and Next is gated
    // on one. The way out is on screen from the start.
    const name = page.getByTestId("onboarding-name");
    await expect(name).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("onboarding-sign-out")).toBeVisible();
    const next = page.getByTestId("onboarding-continue");
    await name.fill("   ");
    await expect(next).toBeDisabled();
    await name.fill("Rich");
    await expect(next).toBeEnabled();

    // Advancing reaches the birthday screen: the cheapest proof the step
    // machine drives the frame.
    await next.click();
    await expect(page.getByTestId("onboarding-dob-month")).toBeVisible();

    // Back is a real, visible button, reachable from the keyboard, and
    // returns to the name screen with the answer kept.
    const back = page.getByTestId("onboarding-back");
    await expect(back).toBeVisible();
    await back.focus();
    await expect(back).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("onboarding-name")).toHaveValue("Rich");
  } finally {
    await context.close();
  }
});

test("Back and Sign out stay visible on a phone-sized screen", async ({ browser }) => {
  const storageState = await mintStorageState(USER_NEW, "Rich New");
  const context = await browser.newContext({ storageState, viewport: { width: 390, height: 844 } });
  const page = await context.newPage();

  try {
    await page.goto(`${FRONTEND_URL}/onboarding`);
    const name = page.getByTestId("onboarding-name");
    await expect(name).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("onboarding-sign-out")).toBeVisible();
    await name.fill("Rich");
    await page.getByTestId("onboarding-continue").click();
    await expect(page.getByTestId("onboarding-back")).toBeVisible();
  } finally {
    await context.close();
  }
});

test("an un-onboarded student opening the app is sent to /onboarding", async ({ browser }) => {
  const storageState = await mintStorageState(USER_NEW, "Rich New");
  const context = await browser.newContext({ storageState });
  const page = await context.newPage();

  try {
    await page.goto(`${FRONTEND_URL}/dashboard`);
    await expect(page).toHaveURL(/\/onboarding$/);
    await expect(page.getByTestId("onboarding-gate")).toBeVisible();
    await expect(page.getByTestId("app-shell")).toHaveCount(0);
  } finally {
    await context.close();
  }
});

test("an onboarded student opening /onboarding is sent to the dashboard", async ({ page }) => {
  // The default storageState is USER_ACTIVE, who has finished onboarding.
  await page.goto(`${FRONTEND_URL}/onboarding`);
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByTestId("app-shell")).toBeVisible();
  await expect(page.getByTestId("onboarding-gate")).toHaveCount(0);
});
