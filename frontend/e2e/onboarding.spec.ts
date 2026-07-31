/**
 * Journey #289 — the first-run onboarding funnel renders and advances.
 *
 * There was no journey over `/onboarding` at all before this, which is a
 * notable gap: it is the first thing a newly-approved student sees, and it is
 * rendered BARE — its route sits outside `(shell)`, so it has no ShellFrame,
 * no nav and no `<main>` padding to inherit. Nothing else in the suite would
 * notice if it broke.
 *
 * This is deliberately a smoke-plus-persistence journey, not a full
 * five-step walkthrough: the steps' own field validation is unit-tested, and
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

    // Step 0 is the welcome step: forward affordance present, Back absent.
    await expect(page.getByTestId("onboarding-continue")).toBeVisible();
    await expect(page.getByTestId("onboarding-back")).toHaveCount(0);

    // The card must actually occupy the screen. #289 converted every
    // hardcoded px in this file to --pad-*/--fs-* tokens; a mistyped var()
    // resolves to nothing and silently collapses the box, which no unit test
    // would catch and which this assertion would.
    const box = await gate.boundingBox();
    expect(box, "the onboarding root should have a layout box").not.toBeNull();
    expect(box!.height, "onboarding must fill the viewport, not collapse").toBeGreaterThan(400);

    const card = await page.evaluate(() => {
      const el = document.querySelector('[data-testid="onboarding-gate"] .card');
      if (!el) return null;
      const r = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      return { w: Math.round(r.width), h: Math.round(r.height), padTop: cs.paddingTop };
    });
    expect(card, "the onboarding card should render").not.toBeNull();
    expect(card!.w, "card should have real width").toBeGreaterThan(200);
    expect(card!.h, "card should have real height").toBeGreaterThan(150);
    // A var() that failed to resolve computes to 0px, not a real length.
    expect(card!.padTop, "card padding must resolve from --pad-*").not.toBe("0px");

    // Advancing off the welcome step reveals Back — the cheapest proof the
    // step machine still drives the frame after the re-home.
    await page.getByTestId("onboarding-continue").click();
    await expect(page.getByTestId("onboarding-back")).toBeVisible();
  } finally {
    await context.close();
  }
});
