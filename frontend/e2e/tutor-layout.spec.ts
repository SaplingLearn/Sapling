/**
 * The Tutor shell's measurements agree (wireframes T1–T3, "AI tutor structure
 * layout V2"), and a session follows the design's anatomy (regions D and F):
 * the phase stepper, one label per planned concept, tutor turns on the page,
 * and a session-panel map that fits under its own key.
 *
 * Geometry, deliberately: these are the sizes the design system fixes, so a
 * stray line-height or padding that makes one control 38px next to a 40px one,
 * or a TopBar that changes height between pages, fails here rather than being
 * spotted by eye. Every number below is the one `learn/tutor/tutor.module.css`
 * documents beside its rule.
 */
import type { Locator, Page } from "@playwright/test";

import { expect, loopOffLane, test } from "./support/fixtures";

/** Sub-pixel slack: layout rounds fractional CSS pixels. */
const SLACK = 1;

async function heights(page: Page, selector: string): Promise<number[]> {
  return page.locator(selector).evaluateAll((els) => els.map((e) => e.getBoundingClientRect().height));
}

async function topBar(page: Page) {
  return page.getByTestId("loop-phase").locator("header").first();
}

async function expectTopBarAgrees(page: Page, expectedHeight: number | null) {
  const header = await topBar(page);
  const box = await header.boundingBox();
  expect(box).not.toBeNull();
  // every action in the TopBar is 32px; the course breadcrumb is text, not an action
  for (const h of await header.locator('[class*="topActs"] > :is(button, a), [class*="topActs"] > div > button').evaluateAll(
    (els) => els.map((e) => e.getBoundingClientRect().height),
  )) {
    expect(Math.abs(h - 32)).toBeLessThanOrEqual(SLACK);
  }
  if (expectedHeight !== null) expect(Math.abs(box!.height - expectedHeight)).toBeLessThanOrEqual(SLACK);
  return box!.height;
}

async function expectNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(SLACK);
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("sapling_disclaimer_ack", "true");
  });
});

test("Tutor home: one 8px rhythm and every control 40px tall", async ({ page }) => {
  test.skip(loopOffLane, "loop path: default lane only");
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/learn");
  const home = page.getByTestId("tutor-home");
  await expect(home).toBeVisible();

  const blocks = await home.evaluate((el) =>
    [...el.children].map((c) => {
      const b = c.getBoundingClientRect();
      return { tag: c.tagName, top: b.top, bottom: b.bottom, height: b.height };
    }),
  );
  // mark 56 · heading 48 · intro 2 × 24 · suggestions 40 · CTA 40
  const [mark, heading, intro, suggest, cta] = blocks;
  expect(mark.height).toBeCloseTo(56, 0);
  expect(heading.height).toBeCloseTo(48, 0);
  expect(intro.height % 24).toBeLessThanOrEqual(SLACK);
  expect(suggest.height).toBeCloseTo(40, 0);
  expect(cta.height).toBeCloseTo(40, 0);
  // the gaps between them: 24 · 16 · 24 · 16
  const gaps = blocks.slice(1, 5).map((b, i) => b.top - blocks[i].bottom);
  expect(gaps.map(Math.round)).toEqual([24, 16, 24, 16]);
  // the suggestions and the CTA are one control height
  for (const h of await heights(page, '[data-testid="tutor-home"] :is(button, a)')) {
    expect(Math.abs(h - 40)).toBeLessThanOrEqual(SLACK);
  }
  // the mark's clover is centred in its circle
  const centred = await home.locator("span svg").first().evaluate((svg) => {
    const s = svg.getBoundingClientRect();
    const c = svg.parentElement!.getBoundingClientRect();
    return [s.left + s.width / 2 - (c.left + c.width / 2), s.top + s.height / 2 - (c.top + c.height / 2)];
  });
  for (const d of centred) expect(Math.abs(d)).toBeLessThanOrEqual(SLACK);
  await expectNoHorizontalOverflow(page);
});

test("the TopBar is one height on every Tutor page, and the sidebar's controls are 36px", async ({ page }) => {
  test.skip(loopOffLane, "loop path: default lane only");
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/learn");
  await expect(page.getByTestId("tutor-home")).toBeVisible();

  // sidebar: New session, the search and every row
  const side = page.getByTestId("tutor-sidebar");
  const sideControls = await side
    .locator('[data-testid="loop-new-session"], label, [data-testid^="tutor-course-"], [data-testid^="tutor-recent-"], [data-testid^="loop-session-"]:not([data-testid="loop-session-picker"])')
    .evaluateAll((els) => els.map((e) => e.getBoundingClientRect().height));
  expect(sideControls.length).toBeGreaterThan(2);
  for (const h of sideControls) expect(Math.abs(h - 36)).toBeLessThanOrEqual(SLACK);

  const home = await expectTopBarAgrees(page, null);
  await page.locator('[data-testid^="tutor-course-"]').first().click();
  await expect(page.getByTestId("tutor-course-page")).toBeVisible();
  await expectTopBarAgrees(page, home);
  await expectNoHorizontalOverflow(page);
  await page.getByTestId("tutor-view-all").click();
  await expect(page.getByTestId("tutor-all-sessions")).toBeVisible();
  await expectTopBarAgrees(page, home);
  // the search and its filters are one height (the sidebar's 36)
  for (const h of await page.getByTestId("tutor-all-sessions").locator('label, [role="group"] button').evaluateAll(
    (els) => els.map((e) => e.getBoundingClientRect().height),
  )) {
    expect(Math.abs(h - 36)).toBeLessThanOrEqual(SLACK);
  }
  await expectNoHorizontalOverflow(page);

  // a session: the TopBar keeps its height, and the session panel starts at its edge
  await page.getByTestId("loop-new-session").click();
  await page.getByTestId("loop-start-guided").click();
  await expect(page.getByTestId("loop-phase")).not.toHaveAttribute("data-session-id", "");
  await expect(page.getByTestId("loop-rail")).toBeVisible();
  await expectTopBarAgrees(page, home);
  const [barBottom, panelTop] = await Promise.all([
    (await topBar(page)).evaluate((e) => e.getBoundingClientRect().bottom),
    page.getByTestId("loop-rail").evaluate((e) => e.getBoundingClientRect().top),
  ]);
  expect(Math.abs(panelTop - barBottom)).toBeLessThanOrEqual(SLACK);
  await expectNoHorizontalOverflow(page);
});

test("phone: the Tutor home fits without horizontal scroll and keeps 40px controls", async ({ page }) => {
  test.skip(loopOffLane, "loop path: default lane only");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/learn");
  await expect(page.getByTestId("tutor-home")).toBeVisible();
  for (const h of await heights(page, '[data-testid="tutor-home"] :is(button, a)')) {
    expect(Math.abs(h - 40)).toBeLessThanOrEqual(SLACK);
  }
  await expectNoHorizontalOverflow(page);
  // the TopBar's title keeps the row: one 36px line, never squeezed by the actions
  const title = (await (await topBar(page)).locator("h1").boundingBox())!;
  expect(title.width).toBeGreaterThan(200);
  expect(title.height).toBeLessThanOrEqual(36 + SLACK);
  // the sidebar opens as a drawer over everything, its head (Tutor, Hide) in view
  await page.getByTestId("tutor-sidebar-show").click();
  await expect(page.getByTestId("tutor-sidebar-hide")).toBeInViewport();
  await page.getByTestId("tutor-sidebar-hide").click();
  await expect(page.getByTestId("tutor-sidebar")).toHaveCount(0);
});

test("a session: the composer's controls are one 32px square and the actions under the turn are 36px", async ({ page }) => {
  test.skip(loopOffLane, "loop path: default lane only");
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/learn");
  await page.getByTestId("loop-start-guided").click();
  // the seeded student's course has no check-in items left: the session opens on its plan
  await page.getByTestId("loop-plan-approve").click();
  await expect(page.getByTestId("loop-phase")).toHaveAttribute("data-phase", "teach");
  await expect(page.getByTestId("loop-check-me")).toBeVisible();
  for (const id of ["tutor-attach", "tutor-send"]) {
    const box = (await page.getByTestId(id).boundingBox())!;
    expect(Math.abs(box.height - 32)).toBeLessThanOrEqual(SLACK);
  }
  expect(Math.abs((await page.getByTestId("tutor-attach").boundingBox())!.width - 32)).toBeLessThanOrEqual(SLACK);
  for (const h of await page.getByTestId("chat-footer").locator('[class*="chatActions"] > :is(button, a)').evaluateAll(
    (els) => els.map((e) => e.getBoundingClientRect().height),
  )) {
    expect(Math.abs(h - 36)).toBeLessThanOrEqual(SLACK);
  }
  await expectNoHorizontalOverflow(page);
});

/** The stepper's step for each loop phase (wireframe D). */
const STEP_FOR_PHASE: Record<string, string> = {
  probe: "Check-in",
  plan: "Plan",
  teach: "Learn",
  check: "Learn",
  feedback: "Learn",
  close: "Wrap-up",
};

/** The stepper agrees with the loop's phase: the current step, the ticks before it. */
async function expectStepperAt(page: Page) {
  const phase = (await page.getByTestId("loop-phase").getAttribute("data-phase"))!;
  const stepper = page.getByTestId("tutor-phase-stepper");
  await expect(stepper).toBeVisible();
  expect(await stepper.evaluate((el) => el.tagName)).toBe("OL");
  const steps = stepper.locator("li");
  await expect(steps).toHaveCount(4);
  const current = stepper.locator('li[aria-current="step"]');
  await expect(current).toHaveCount(1);
  await expect(current).toContainText(STEP_FOR_PHASE[phase]);
  const at = ["Check-in", "Plan", "Learn", "Wrap-up"].indexOf(STEP_FOR_PHASE[phase]);
  await expect(stepper.locator('li[data-state="done"]')).toHaveCount(at);
  // every step's mark is one 22px circle
  for (const h of await stepper.locator("li > span[aria-hidden]").evaluateAll(
    (els) => els.map((e) => [e.getBoundingClientRect().width, e.getBoundingClientRect().height]),
  )) {
    expect(Math.abs(h[0] - 22)).toBeLessThanOrEqual(SLACK);
    expect(Math.abs(h[1] - 22)).toBeLessThanOrEqual(SLACK);
  }
}

/** A tutor turn's text sits on the page: no fill, no border, a bounded measure. */
async function expectOnThePage(text: Locator) {
  const style = await text.evaluate((el) => {
    const s = getComputedStyle(el);
    return { bg: s.backgroundColor, border: s.borderTopWidth, maxWidth: s.maxWidth };
  });
  expect(style.bg).toBe("rgba(0, 0, 0, 0)");
  expect(style.border).toBe("0px");
  expect(style.maxWidth).not.toBe("none");
}

test("a session: the stepper follows the phase, one label per planned concept, turns on the page, a map that fits its key", async ({ page }) => {
  test.skip(loopOffLane, "loop path: default lane only");
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/learn");
  await page.getByTestId("loop-start-guided").click();
  const phase = page.getByTestId("loop-phase");
  // the seeded student's course has no check-in items left: the session opens on its plan
  await expect(phase).toHaveAttribute("data-phase", "plan");
  await expectStepperAt(page);

  // PR #866 U3: each concept carries one label (its kind); outside a goal no
  // reason line sits under it to contradict the badge
  const concepts = page.locator('[data-testid^="loop-plan-concept-"]');
  await expect(concepts.first()).toBeVisible();
  for (const row of await concepts.all()) {
    await expect(row.locator('[data-testid^="loop-plan-kind-"]')).toHaveCount(1);
    await expect(row.locator('[data-testid^="loop-plan-reason-"]')).toHaveCount(0);
  }
  // the plan's intro is a tutor turn on the page, under the tutor's mark
  const intro = page.locator('[class*="pageTurn"]').first();
  await expect(intro).toContainText("Tutor");
  await expectOnThePage(intro.locator('[class*="turnText"]'));

  await page.getByTestId("loop-plan-approve").click();
  await expect(phase).toHaveAttribute("data-phase", "teach");
  await expect(page.getByTestId("loop-check-me")).toBeVisible();
  await expectStepperAt(page);

  // PR #866 U7a: every tutor turn in the conversation sits on the page
  const turns = page.getByTestId("tutor-messages").locator('[data-testid="tutor-turn"]:not([data-visually-hidden])');
  await expect(turns.first()).toBeVisible();
  for (const turn of await turns.all()) await expectOnThePage(turn.locator('[class*="turnText"]'));

  // PR #866 U4: the panel's map is drawn in the colours its key names, with
  // nothing over its nodes, and every node and caption inside it
  const rail = page.getByTestId("loop-rail");
  const map = rail.getByTestId("graph-container");
  await expect(map).toBeVisible();
  await expect(rail.locator('svg[data-color-mode="mastery"]')).toHaveCount(1);
  await expect(rail.getByTestId("graph-color-toggle")).toHaveCount(0);
  await expect(rail.getByTestId("graph-zoom-controls")).toHaveCount(0);
  // Four mastery tiers + W3.2 practiced (outline) row.
  await expect(rail.getByTestId("tutor-map-key").locator("li")).toHaveCount(5);
  await expect(rail.getByTestId("tutor-map-key-practiced")).toBeVisible();
  await expect
    .poll(async () => {
      const box = (await map.boundingBox())!;
      const parts = await map.locator('[data-testid="graph-node"] :is(text, [data-testid="graph-node-circle"])').evaluateAll(
        (els) => els.map((e) => {
          const r = e.getBoundingClientRect();
          return [r.left, r.top, r.right, r.bottom];
        }),
      );
      return parts.length > 0 && parts.every(([l, t, r, b]) =>
        l >= box.x - SLACK && t >= box.y - SLACK && r <= box.x + box.width + SLACK && b <= box.y + box.height + SLACK);
    })
    .toBe(true);
  await expectNoHorizontalOverflow(page);
});
