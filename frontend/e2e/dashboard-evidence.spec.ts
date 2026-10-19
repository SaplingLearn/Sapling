/**
 * Visual evidence for the Dashboard / Home learning workspace (redesign
 * prompt 07). Gated on DASHBOARD_EVIDENCE_DIR exactly as
 * redesign-evidence.spec.ts is gated on REDESIGN_EVIDENCE_DIR: unset, the
 * normal lane collects and skips it. Set, it writes `<phase>/<step>.png`
 * screenshots there.
 *
 * DASHBOARD_EVIDENCE_PHASE picks the capture set:
 *   - `before`: the integration base's Dashboard (sidebar, arrival, map,
 *     loading/empty/failure) — run against the base build, before the
 *     redesign, so the comparison images come from the same seeded data.
 *   - `after` (default): the same steps plus selection, topic list, the phone
 *     map preview, the phone selected-concept sheet and the full map.
 *
 * Data: the rich seed's rich-user-active (MATH210 + CS101 + BIO110 …) for the
 * arrival/map captures. Loading, empty and failure are produced by holding,
 * emptying or failing the dashboard's own GETs with page.route — nothing is
 * written to the database for them.
 */
import type { Browser, Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

import { expect, killSwitchLane, test } from "./support/fixtures";
import { mintStorageState } from "./support/session";
import { USER_ACTIVE } from "./support/stack";

const OUT_DIR = process.env.DASHBOARD_EVIDENCE_DIR?.trim();
const PHASE = process.env.DASHBOARD_EVIDENCE_PHASE?.trim() === "before" ? "before" : "after";

test.skip(!OUT_DIR, "visual evidence: set DASHBOARD_EVIDENCE_DIR to capture");
test.skip(killSwitchLane, "default lane only");

const DIR = OUT_DIR ? path.join(OUT_DIR, PHASE) : "";

async function signIn(browser: Browser, viewport: { width: number; height: number }, deviceScaleFactor = 1) {
  const context = await browser.newContext({
    storageState: await mintStorageState(USER_ACTIVE, "Rich Active"),
    viewport,
    deviceScaleFactor,
  });
  const page = await context.newPage();
  await page.addInitScript(() => {
    localStorage.setItem("sapling_disclaimer_ack", "true");
    // The shell's global feedback prompts would cover the page in a picture.
    localStorage.setItem("sapling_last_session_feedback", String(Date.now()));
    localStorage.setItem("sapling_last_feedback", String(Date.now()));
  });
  return { context, page };
}

async function shot(page: Page, name: string) {
  await page.waitForTimeout(400); // let transitions and the force layout settle for the picture
  await page.screenshot({ path: path.join(DIR, `${name}.png`) });
}

/** The shell rail, cropped to its own box (the "sidebar unchanged" comparison). */
async function sidebarShot(page: Page, name: string) {
  const box = await page.locator(".fa26-navigation").boundingBox();
  if (!box) return;
  await page.screenshot({
    path: path.join(DIR, `${name}.png`),
    clip: { x: 0, y: 0, width: Math.ceil(box.x + box.width), height: Math.ceil(box.y + box.height) },
  });
}

/** Wait until the dashboard's graph has painted real nodes (or settled empty). */
async function graphReady(page: Page) {
  await expect(page.getByTestId("graph-container").first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(600);
}

test.beforeAll(() => {
  if (DIR) fs.mkdirSync(DIR, { recursive: true });
});

test.describe.configure({ mode: "serial" });

test("arrival, sidebar and map at 1440 / 768 / 390 / 320", async ({ browser }) => {
  test.setTimeout(240_000);
  for (const [w, h] of [[1440, 1000], [768, 1024], [390, 844], [320, 640]] as const) {
    const { context, page } = await signIn(browser, { width: w, height: h });
    try {
      await page.goto("/dashboard");
      if (w >= 768 || PHASE === "before") await graphReady(page);
      else await expect(page.getByTestId("dashboard-map-preview")).toBeVisible({ timeout: 30_000 });
      await shot(page, `01-arrival-${w}`);
      if (w === 1440) await sidebarShot(page, `00-sidebar-${w}`);
      // The whole page in one picture: a tall viewport, same width.
      await page.setViewportSize({ width: w, height: w >= 768 ? 1800 : 2600 });
      await shot(page, `02-arrival-${w}-full`);
    } finally {
      await context.close();
    }
  }
});

test("full map / fullscreen graph", async ({ browser }) => {
  const { context, page } = await signIn(browser, { width: 1440, height: 1000 });
  try {
    await page.goto("/dashboard");
    await graphReady(page);
    if (PHASE === "before") {
      await page.getByRole("button", { name: "Fullscreen graph" }).click();
    } else {
      await page.getByTestId("dashboard-open-map").click();
      await expect(page.getByTestId("dashboard-full-map")).toBeVisible();
    }
    await shot(page, "05-full-map-1440");
  } finally {
    await context.close();
  }
});

test("loading, empty and failure states", async ({ browser }) => {
  test.setTimeout(120_000);
  // Loading: hold the graph GET open.
  {
    const { context, page } = await signIn(browser, { width: 1440, height: 1000 });
    try {
      await page.route(/\/api\/graph\/[^/?]+(\?.*)?$/, () => new Promise(() => {}));
      await page.goto("/dashboard");
      await shot(page, "10-loading-1440");
    } finally {
      await context.close();
    }
  }
  // Empty: a student with no courses and no concepts.
  {
    const { context, page } = await signIn(browser, { width: 1440, height: 1000 });
    try {
      await page.route(/\/api\/graph\/[^/?]+\/courses(\?.*)?$/, (r) =>
        r.request().method() === "GET" ? r.fulfill({ json: { courses: [] } }) : r.continue(),
      );
      await page.route(/\/api\/graph\/[^/?]+(\?.*)?$/, (r) =>
        r.fulfill({ json: { nodes: [], edges: [], stats: { streak: 0 } } }),
      );
      await page.route(/\/api\/learn\/sessions\/[^/?]+(\?.*)?$/, (r) => r.fulfill({ json: { sessions: [] } }));
      await page.route(/\/api\/calendar\/upcoming\/.*/, (r) => r.fulfill({ json: { assignments: [] } }));
      await page.route(/\/api\/notes\/user\/.*/, (r) => r.fulfill({ json: { notes: [] } }));
      await page.goto("/dashboard");
      await page.waitForTimeout(1500);
      await shot(page, "11-empty-1440");
    } finally {
      await context.close();
    }
  }
  // Failure: the graph GET fails.
  {
    const { context, page } = await signIn(browser, { width: 1440, height: 1000 });
    try {
      await page.route(/\/api\/graph\/[^/?]+(\?.*)?$/, (r) => r.fulfill({ status: 503, json: { detail: "unavailable" } }));
      await page.goto("/dashboard");
      await page.waitForTimeout(1500);
      await shot(page, "12-failure-1440");
    } finally {
      await context.close();
    }
  }
});

test("after: selection, topic list, phone sheet and phone full map", async ({ browser }) => {
  test.skip(PHASE !== "after", "redesign-only states");
  test.setTimeout(180_000);
  // Desktop selection (bj5Ap) and the topic list.
  {
    const { context, page } = await signIn(browser, { width: 1440, height: 1000 });
    try {
      await page.goto("/dashboard");
      await graphReady(page);
      const main = page.getByTestId("app-shell");
      await main.getByTestId("dashboard-view-topics").click();
      await expect(page.getByTestId("dashboard-topics")).toBeVisible();
      await shot(page, "20-topic-list-1440");
      await page.getByTestId("dashboard-topics").locator('[data-testid^="dashboard-topic-"][data-node-id]').nth(1).click();
      await expect(main.getByTestId("dashboard-concept")).toBeVisible();
      await page.waitForTimeout(400);
      await shot(page, "21-selected-1440");
      await main.getByTestId("dashboard-concept-practice").focus();
      await shot(page, "22-selected-focus-1440");
    } finally {
      await context.close();
    }
  }
  // Phone: preview, topic list, selected-topic sheet, full map.
  for (const w of [390, 320] as const) {
    const { context, page } = await signIn(browser, { width: w, height: 844 });
    try {
      await page.goto("/dashboard");
      const main = page.getByTestId("app-shell");
      await expect(main.getByTestId("dashboard-map-preview")).toBeVisible({ timeout: 30_000 });
      await main.getByTestId("dashboard-map-preview").scrollIntoViewIfNeeded();
      await shot(page, `30-phone-map-preview-${w}`);
      await main.getByTestId("dashboard-view-topics").click();
      await expect(page.getByTestId("dashboard-topics")).toBeVisible();
      await shot(page, `31-phone-topic-list-${w}`);
      await page.getByTestId("dashboard-topics").locator('[data-testid^="dashboard-topic-"][data-node-id]').nth(1).click();
      await expect(page.getByTestId("dashboard-concept-sheet")).toBeVisible();
      await shot(page, `32-phone-selected-sheet-${w}`);
      await page.keyboard.press("Escape");
      await main.getByTestId("dashboard-open-map").click();
      await expect(page.getByTestId("dashboard-full-map")).toBeVisible();
      await page.waitForTimeout(600);
      await shot(page, `33-phone-full-map-${w}`);
    } finally {
      await context.close();
    }
  }
});

test("after: a loop student's open check-in (Resume check-in)", async ({ browser }) => {
  test.skip(PHASE !== "after", "redesign-only state");
  test.setTimeout(120_000);
  const context = await browser.newContext({
    storageState: await mintStorageState("rich-user-loop", "Lou Loop"),
    viewport: { width: 1440, height: 1000 },
  });
  const page = await context.newPage();
  await page.addInitScript(() => {
    localStorage.setItem("sapling_disclaimer_ack", "true");
    localStorage.setItem("sapling_last_session_feedback", String(Date.now()));
    localStorage.setItem("sapling_last_feedback", String(Date.now()));
  });
  try {
    await page.goto("/learn");
    await expect(page.getByTestId("loop-probe-item")).toBeVisible({ timeout: 60_000 });
    await page.goto("/dashboard");
    await expect(page.getByTestId("app-shell").getByTestId("dashboard-next")).toHaveAttribute("data-state", "loop-open", { timeout: 30_000 });
    await graphReady(page);
    await shot(page, "40-loop-open-1440");
    await page.setViewportSize({ width: 390, height: 844 });
    await shot(page, "41-loop-open-390");
  } finally {
    await context.close();
  }
});

test("after: 200% zoom and a keyboard pass", async ({ browser }) => {
  test.skip(PHASE !== "after", "redesign-only");
  test.setTimeout(120_000);
  // 200 % zoom of a 1440 window = a 720 CSS-px layout at deviceScaleFactor 2.
  const { context, page } = await signIn(browser, { width: 720, height: 500 }, 2);
  try {
    await page.goto("/dashboard");
    const main = page.getByTestId("app-shell");
    await expect(main.getByTestId("dashboard-next")).not.toHaveAttribute("data-state", "pending", { timeout: 30_000 });
    await shot(page, "50-zoom200-arrival");
    const overflow = await main.evaluate((el) => el.scrollWidth - el.clientWidth);
    // Keyboard: Tab from the top of main; record each stop and whether it shows a ring.
    await main.focus();
    const stops: string[] = [];
    for (let i = 0; i < 14; i++) {
      await page.keyboard.press("Tab");
      stops.push(
        await page.evaluate(() => {
          const el = document.activeElement as HTMLElement | null;
          if (!el || el === document.body) return "BODY";
          const cs = getComputedStyle(el);
          const ring = cs.outlineStyle !== "none" && parseFloat(cs.outlineWidth) > 0;
          const label = el.getAttribute("data-testid") || el.getAttribute("aria-label") || (el.textContent || "").trim().slice(0, 40);
          return `${el.tagName}:${label}${ring ? "" : " [NO VISIBLE FOCUS]"}`;
        }),
      );
    }
    fs.writeFileSync(path.join(DIR, "keyboard-report.json"), JSON.stringify({ zoom200HorizontalOverflowPx: overflow, tabStops: stops }, null, 2));
    expect.soft(overflow, "no horizontal overflow at 200% zoom").toBeLessThanOrEqual(1);
    expect.soft(stops.filter((s) => s.includes("[NO VISIBLE FOCUS]")), "every stop shows a focus ring").toEqual([]);
  } finally {
    await context.close();
  }
});
