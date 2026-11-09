/**
 * Journey #289 — the first-run onboarding funnel renders and advances.
 *
 * There was no journey over `/onboarding` at all before this, which is a
 * notable gap: it is the first thing a newly-approved student sees, and it is
 * rendered BARE — its route sits outside `(shell)`, so it has no ShellFrame,
 * no nav and no `<main>` padding to inherit. Nothing else in the suite would
 * notice if it broke.
 *
 * Since #800 the funnel is the Claude Design flow: an intro, then nine
 * screens over six chapters, with Enter / Esc key hints (Next / Back) always
 * on screen. This is deliberately a smoke journey, not a full walkthrough: the steps' own field validation is unit-tested, and
 * a long scripted click-path over a funnel that is still being redesigned
 * (#289 changes its frame; the flow itself is untouched) would break on every
 * copy tweak. What it pins is the part that must not regress — the screen
 * mounts for an un-onboarded user, the nav affordances behave, and the token
 * conversion did not leave the layout collapsed.
 *
 * Signs in as USER_NEW rather than the default USER_ACTIVE because it is the
 * realistic state — onboarding_completed=False. It is NOT a gate: /onboarding
 * sits outside middleware.ts's matcher and Onboarding.tsx only redirects when
 * unauthenticated, so the route would render for any signed-in user. What the
 * seed choice buys is a funnel showing its real first-run content.
 */
import { expect, test } from "./support/fixtures";
import { mintStorageState } from "./support/session";
import { FRONTEND_URL, USER_NEW } from "./support/stack";

test("the onboarding funnel renders for an un-onboarded user (#289)", async ({ browser }) => {
  const storageState = await mintStorageState(USER_NEW, "Rich New");
  const context = await browser.newContext({ storageState });
  const page = await context.newPage();

  try {
    await page.goto(`${FRONTEND_URL}/onboarding`);

    const gate = page.getByTestId("onboarding-gate");
    await expect(gate).toBeVisible();

    // The root must actually occupy the screen: it renders bare (no shell),
    // so a broken layout collapses it, which no unit test would catch.
    const box = await gate.boundingBox();
    expect(box, "the onboarding root should have a layout box").not.toBeNull();
    expect(box!.height, "onboarding must fill the viewport, not collapse").toBeGreaterThan(400);

    // After the intro, the first screen asks for a name, and Next is gated
    // on one.
    const name = page.getByTestId("onboarding-name");
    await expect(name).toBeVisible({ timeout: 15_000 });
    const next = page.getByTestId("onboarding-continue");
    await name.fill("   ");
    await expect(next).toBeDisabled();
    await name.fill("Rich");
    await expect(next).toBeEnabled();

    // Advancing reaches the birthday screen: the cheapest proof the step
    // machine drives the frame.
    await next.click();
    await expect(page.getByTestId("onboarding-dob-month")).toBeVisible();

    // Back (Esc) returns to the name screen with the answer kept.
    await page.getByTestId("onboarding-back").click();
    await expect(page.getByTestId("onboarding-name")).toHaveValue("Rich");
  } finally {
    await context.close();
  }
});
