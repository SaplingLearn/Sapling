/**
 * The Tutor shell's measurements agree (wireframes T1–T3, "AI tutor structure
 * layout V2").
 *
 * Geometry, deliberately: these are the sizes the design system fixes, so a
 * stray line-height or padding that makes one control 38px next to a 40px one,
 * or a TopBar that changes height between pages, fails here rather than being
 * spotted by eye. Every number below is the one `learn/tutor/tutor.module.css`
 * documents beside its rule.
 */
import type { Page } from "@playwright/test";

import { expect, killSwitchLane, test } from "./support/fixtures";

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
  test.skip(killSwitchLane, "loop path: default lane only");
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
  test.skip(killSwitchLane, "loop path: default lane only");
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
  test.skip(killSwitchLane, "loop path: default lane only");
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
  test.skip(killSwitchLane, "loop path: default lane only");
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
