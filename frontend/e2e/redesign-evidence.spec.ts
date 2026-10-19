/**
 * Integrated evidence for redesign prompt 05: the Library → Learn → Clov tutor
 * journey at 1440 / 390 / 320 px and 200 % zoom, plus a keyboard-only pass of
 * each surface (Tab order with visible focus, Escape and focus return for
 * every sheet, dialog and menu, radio arrow keys where an option set renders).
 *
 * Gated on REDESIGN_EVIDENCE_DIR exactly as tutor-evidence.spec.ts is gated on
 * TUTOR_EVIDENCE_DIR: unset, the normal lane collects and skips it. Set, it
 * writes `<step>-<width>.png` and `keyboard-report.json` there. Checks are
 * soft (expect.soft) so ONE run reports every finding instead of stopping at
 * the first; the report records what was observed either way.
 */
import type { Browser, Locator, Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

import { expect, killSwitchLane, test } from "./support/fixtures";
import { queryRaw } from "./support/db";
import { setUserFlag } from "./support/flags";
import { mintStorageState } from "./support/session";
import { USER_ACTIVE } from "./support/stack";

/** The shell's <main>: until React reveals a streamed
 *  shell page, the server's copy sits in a hidden `<div hidden id="S:N">`
 *  outside it (see upload.spec.ts::appShellUpload). Only page-level ids read
 *  right after a navigation are scoped: sheets and dialogs portal to <body>. */
function shell(page: Page) {
  return page.getByTestId("app-shell");
}

const OUT_DIR = process.env.REDESIGN_EVIDENCE_DIR?.trim();
const MATH_COURSE = "rich-course-math210";
const MATH_DOC = "rich-doc-math-notes";

test.skip(!OUT_DIR, "visual + keyboard evidence: set REDESIGN_EVIDENCE_DIR to capture");
test.skip(killSwitchLane, "loop path: default lane only");

type Focus = { label: string; tag: string; focusVisible: boolean; indicator: boolean; inDialog: boolean };
const report: Record<string, unknown> = {};

async function signIn(browser: Browser, viewport: { width: number; height: number }, deviceScaleFactor = 1) {
  const context = await browser.newContext({
    storageState: await mintStorageState(USER_ACTIVE, "Avery Active"),
    viewport,
    deviceScaleFactor,
  });
  const page = await context.newPage();
  await page.addInitScript(() => {
    localStorage.setItem("sapling_disclaimer_ack", "true");
    // The shell's global prompts are out of scope here and would cover the
    // page: the session pulse opens on every client-side exit from /learn
    // (SessionFeedbackGlobal) and the general pulse after 45 s (FeedbackFlow).
    // Both honour a recent cooldown stamp.
    localStorage.setItem("sapling_last_session_feedback", String(Date.now()));
    localStorage.setItem("sapling_last_feedback", String(Date.now()));
  });
  return { context, page };
}

async function shot(page: Page, name: string) {
  await page.waitForTimeout(250); // let sheet/drawer transitions settle for the picture
  await page.screenshot({ path: path.join(OUT_DIR!, `${name}.png`) });
}

async function focused(page: Page): Promise<Focus> {
  return page.evaluate(() => {
    const el = document.activeElement as HTMLElement | null;
    if (!el || el === document.body) return { label: "body", tag: "BODY", focusVisible: false, indicator: false, inDialog: false };
    // A ring on the element, or on a near ancestor that draws it for the
    // element (e.g. a composer box around a borderless textarea).
    const ringed = (node: Element) => {
      const cs = getComputedStyle(node);
      return (cs.outlineStyle !== "none" && parseFloat(cs.outlineWidth) > 0) || (cs.boxShadow !== "none" && cs.boxShadow !== "");
    };
    // Ancestors count by OUTLINE only: a resting box-shadow (a card) is not focus.
    const outlined = (node: Element) => {
      const cs = getComputedStyle(node);
      return cs.outlineStyle !== "none" && parseFloat(cs.outlineWidth) > 0;
    };
    let ring = ringed(el);
    for (let up = el.parentElement, i = 0; !ring && up && i < 3; up = up.parentElement, i++) ring = outlined(up);
    const label =
      el.getAttribute("data-testid") ||
      el.getAttribute("aria-label") ||
      (el.textContent || "").replace(/\s+/g, " ").trim().slice(0, 48) ||
      el.tagName;
    return {
      label,
      tag: el.tagName,
      focusVisible: el.matches(":focus-visible"),
      indicator: ring,
      inDialog: !!el.closest('[role="dialog"]'),
    };
  });
}

/** Tab `n` times from the current focus; every stop must show a focus indicator.
 *  (A BODY stop is the document edge, where Tab leaves for the browser UI.) */
async function tabWalk(page: Page, key: string, n: number) {
  const stops: Focus[] = [];
  for (let i = 0; i < n; i++) {
    await page.keyboard.press("Tab");
    stops.push(await focused(page));
  }
  report[`${key}:tab-order`] = stops.map((s) => `${s.tag}:${s.label}${s.tag === "BODY" || s.indicator ? "" : " [NO VISIBLE FOCUS]"}`);
  const invisible = stops.filter((s) => s.tag !== "BODY" && !s.indicator).map((s) => s.label);
  expect.soft(invisible, `${key}: every Tab stop shows a focus indicator`).toEqual([]);
}

const focusInside = (surface: Locator) =>
  surface.evaluate((el) => el.contains(document.activeElement)).catch(() => false);

/**
 * Open with the keyboard; for a dialog/sheet, wait for focus to move inside
 * (it moves after mount); Escape; the surface closes and focus returns to the
 * opener (focus return may land a frame later, so both are polled).
 */
async function escapeReturns(
  page: Page,
  key: string,
  opener: Locator,
  surface: Locator,
  { modal = true }: { modal?: boolean } = {},
) {
  await opener.focus();
  await page.keyboard.press("Enter");
  await expect(surface).toBeVisible();
  if (modal) {
    await expect.soft.poll(() => focusInside(surface), { message: `${key}: focus moves inside on open`, timeout: 3_000 }).toBe(true);
  }
  const inside = await focused(page);
  await page.keyboard.press("Escape");
  await expect.soft(surface, `${key}: Escape closes`).toBeHidden({ timeout: 3_000 });
  const openerId = await opener.getAttribute("data-testid");
  await expect.soft.poll(async () => (await focused(page)).label, { message: `${key}: focus returns to the opener`, timeout: 3_000 }).toBe(openerId);
  report[`${key}:escape`] = { focusOnOpen: inside, focusAfterEscape: await focused(page), opener: openerId };
  // Leave nothing open for the next step if Escape failed.
  if (await surface.isVisible().catch(() => false)) await page.keyboard.press("Escape");
}

/** The phase's primary answer/send control is reachable: inside the viewport
 *  after scrolling it into view, and not covered (by the nav, a bar, a sheet). */
async function primaryControlReachable(page: Page, key: string) {
  const candidates = ["tutor-input", "loop-attempt-submit", "loop-probe-submit", "loop-plan-approve"];
  for (const id of candidates) {
    const el = page.getByTestId(id);
    if ((await el.count()) === 0 || !(await el.first().isVisible())) continue;
    await el.first().scrollIntoViewIfNeeded();
    const result = await el.first().evaluate((node) => {
      const r = node.getBoundingClientRect();
      const x = r.left + r.width / 2;
      const y = r.top + Math.min(r.height / 2, 20);
      const hit = document.elementFromPoint(x, y);
      return {
        top: Math.round(r.top),
        bottom: Math.round(r.bottom),
        height: Math.round(r.height),
        viewport: window.innerHeight,
        uncovered: !!hit && (node === hit || node.contains(hit) || hit.contains(node)),
      };
    });
    report[`${key}:primary-control`] = { id, ...result };
    expect.soft(result.bottom <= result.viewport && result.top >= 0, `${key}: ${id} inside the viewport`).toBe(true);
    expect.soft(result.uncovered, `${key}: ${id} not covered by another layer`).toBe(true);
    return;
  }
  report[`${key}:primary-control`] = "none of the phase controls rendered";
}

/** Approve the plan with the keyboard when the session is waiting on it. */
async function approvePlanByKeyboard(page: Page) {
  const approve = page.getByTestId("loop-plan-approve");
  if ((await approve.count()) === 0) return;
  await approve.focus();
  await page.keyboard.press("Enter");
  await expect(shell(page).getByTestId("loop-phase")).toHaveAttribute("data-phase", "teach", { timeout: 15_000 });
}

async function noHorizontalScroll(page: Page, key: string) {
  const dims = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  report[`${key}:overflow`] = dims;
  expect.soft(dims.scrollWidth, `${key}: no horizontal page scroll`).toBeLessThanOrEqual(dims.clientWidth + 1);
}

async function waitForSession(page: Page) {
  const root = shell(page).getByTestId("loop-phase");
  await expect(root).not.toHaveAttribute("data-session-id", "", { timeout: 30_000 });
  return root;
}

test.beforeAll(() => {
  fs.mkdirSync(OUT_DIR!, { recursive: true });
});

// Merged after EVERY test: a failed test restarts the worker (and this module).
test.afterEach(() => {
  const file = path.join(OUT_DIR!, "keyboard-report.json");
  let prior: Record<string, unknown> = {};
  try {
    prior = JSON.parse(fs.readFileSync(file, "utf8"));
  } catch {
    prior = {};
  }
  fs.writeFileSync(file, JSON.stringify({ ...prior, ...report }, null, 2));
});

test("desktop 1440: Library → Learn → tutor → Library, keyboard only", async ({ browser }) => {
  test.setTimeout(180_000);
  await setUserFlag(browser, "tutor_view", USER_ACTIVE, "on");
  const { context, page } = await signIn(browser, { width: 1440, height: 900 });

  // Library
  await page.goto("/library");
  await expect(shell(page).getByTestId(`library-doc-${MATH_DOC}`)).toBeVisible();
  await shot(page, "01-library-list-1440");
  await page.locator("body").focus();
  await tabWalk(page, "library-1440", 24);
  await escapeReturns(page, "library-1440-upload-modal", shell(page).getByTestId("library-upload"), page.getByTestId("upload-modal"));
  const row = shell(page).getByTestId(`library-doc-${MATH_DOC}`);
  await row.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("library-detail-panel")).toBeVisible();
  await expect.soft(row).toHaveAttribute("aria-pressed", "true");
  await shot(page, "02-library-detail-1440");

  // Library → Learn (keyboard on the Ask Clov link)
  await page.getByTestId("library-detail-ask-clov").focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/learn/);
  await waitForSession(page);
  await expect(shell(page).getByTestId("loop-heading")).toBeVisible();
  await shot(page, "03-learn-studio-1440");
  await page.locator("body").focus();
  await tabWalk(page, "learn-1440", 24);
  const option = page.locator('[data-testid^="loop-probe-option-"]');
  if ((await option.count()) > 1) {
    await option.first().focus();
    await page.keyboard.press("ArrowDown");
    report["learn-1440:radio-arrow"] = await focused(page);
  } else {
    report["learn-1440:radio-arrow"] = "no mc_reason option set served by the fixture item (free-text probe)";
  }
  await escapeReturns(page, "learn-1440-new-session-confirm", page.getByTestId("loop-new-session"), page.getByTestId("loop-new-session-confirm"));
  await shot(page, "03b-learn-plan-1440");
  await approvePlanByKeyboard(page);
  await shot(page, "03c-learn-teach-1440");

  // Learn → tutor
  await page.getByTestId("loop-view-tutor").focus();
  await page.keyboard.press("Enter");
  await expect(shell(page).getByTestId("loop-phase")).toHaveAttribute("data-view", "tutor");
  await shot(page, "04-tutor-active-1440");
  await page.locator("body").focus();
  await tabWalk(page, "tutor-1440", 24);
  await primaryControlReachable(page, "tutor-1440");
  await escapeReturns(page, "tutor-1440-menu", page.getByTestId("tutor-menu"), page.getByTestId("tutor-menu-studio"), { modal: false });
  await escapeReturns(page, "tutor-1440-history", page.getByTestId("tutor-history-open"), page.getByTestId("tutor-history-sheet"));
  // The desktop context is a panel beside the column (not modal): its Close returns focus.
  const chip = page.getByTestId("tutor-context-materials");
  await chip.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("tutor-materials")).toBeVisible();
  await shot(page, "05-tutor-materials-1440");
  await page.getByTestId("tutor-context-close").focus();
  await page.keyboard.press("Enter");
  await expect.soft.poll(async () => (await focused(page)).label, { message: "tutor-1440 context: Close returns focus to the chip", timeout: 3_000 }).toBe("tutor-context-materials");
  report["tutor-1440-context:close"] = await focused(page);

  // Tutor → Library (Materials link keeps the course)
  await chip.focus();
  await page.keyboard.press("Enter");
  await page.getByTestId("tutor-materials-library").focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(new RegExp(`/library\\?course=${MATH_COURSE}`));
  await expect(shell(page).getByTestId("library-course-filter")).toHaveValue(MATH_COURSE);
  await shot(page, "06-library-course-from-tutor-1440");

  // REPORT-ONLY probe of a known gap (not asserted): the browser Back button
  // returns to the URL the loop left after consuming ?course= — without it.
  const sessionBefore = await queryRaw(`SELECT count(*)::int AS n FROM sessions WHERE user_id = $1 AND mode <> 'review'`, [USER_ACTIVE]);
  await page.goBack();
  await expect(shell(page).getByTestId("loop-phase")).toBeVisible();
  await page.waitForTimeout(3_000);
  const backRoot = shell(page).getByTestId("loop-phase");
  const sessionAfter = await queryRaw(`SELECT count(*)::int AS n FROM sessions WHERE user_id = $1 AND mode <> 'review'`, [USER_ACTIVE]);
  report["back-from-library:observed"] = {
    url: page.url(),
    sessionId: await backRoot.getAttribute("data-session-id"),
    phase: await backRoot.getAttribute("data-phase"),
    view: await backRoot.getAttribute("data-view"),
    welcome: await page.getByTestId("tutor-welcome").isVisible().catch(() => false),
    sessionsBefore: sessionBefore[0]?.n,
    sessionsAfter: sessionAfter[0]?.n,
  };
  await shot(page, "10-back-from-library-1440");
  await context.close();
});

for (const width of [390, 320] as const) {
  test(`phone ${width}: the same journey; sheets close on Escape and return focus`, async ({ browser }) => {
    test.setTimeout(180_000);
    await setUserFlag(browser, "tutor_view", USER_ACTIVE, "on");
    const { context, page } = await signIn(browser, { width, height: 844 });

    await page.goto("/library");
    const row = shell(page).getByTestId(`library-doc-${MATH_DOC}`);
    await expect(row).toBeVisible();
    await shot(page, `01-library-list-${width}`);
    await noHorizontalScroll(page, `library-${width}`);
    await escapeReturns(page, `library-${width}-detail-sheet`, row, page.getByTestId("library-detail"));
    await row.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("library-detail-panel")).toBeVisible();
    await shot(page, `02-library-detail-sheet-${width}`);
    await page.getByTestId("library-detail-ask-clov").focus();
    await page.keyboard.press("Enter");

    await expect(page).toHaveURL(/\/learn/);
    await waitForSession(page);
    await shot(page, `03-learn-studio-${width}`);
    await noHorizontalScroll(page, `learn-${width}`);
    await escapeReturns(page, `learn-${width}-route-sheet`, page.getByTestId("loop-route-trigger"), page.getByTestId("loop-rail"));
    await primaryControlReachable(page, `learn-${width}`);
    await approvePlanByKeyboard(page);
    await shot(page, `03b-learn-teach-${width}`);

    await page.getByTestId("loop-view-tutor").focus();
    await page.keyboard.press("Enter");
    await expect(shell(page).getByTestId("loop-phase")).toHaveAttribute("data-view", "tutor");
    await shot(page, `04-tutor-active-${width}`);
    await noHorizontalScroll(page, `tutor-${width}`);
    await primaryControlReachable(page, `tutor-${width}`);
    await escapeReturns(page, `tutor-${width}-context-sheet`, page.getByTestId("tutor-context-materials"), page.getByTestId("tutor-context-sheet"));
    await page.getByTestId("tutor-context-materials").focus();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("tutor-materials")).toBeVisible();
    await shot(page, `05-tutor-materials-sheet-${width}`);
    await page.getByTestId("tutor-materials-library").focus();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(new RegExp(`/library\\?course=${MATH_COURSE}`));
    await expect(shell(page).getByTestId("library-course-filter")).toHaveValue(MATH_COURSE);
    await shot(page, `06-library-course-from-tutor-${width}`);
    await context.close();
  });
}

test("200% zoom (1440 CSS px at 2x → 720 px layout): no horizontal page scroll on the three surfaces", async ({ browser }) => {
  test.setTimeout(120_000);
  await setUserFlag(browser, "tutor_view", USER_ACTIVE, "on");
  const { context, page } = await signIn(browser, { width: 720, height: 450 }, 2);
  await page.goto("/library");
  await expect(shell(page).getByTestId(`library-doc-${MATH_DOC}`)).toBeVisible();
  await shot(page, "07-zoom200-library");
  await noHorizontalScroll(page, "zoom200-library");
  await page.goto(`/learn?course=${MATH_COURSE}`);
  await waitForSession(page);
  await shot(page, "08-zoom200-learn");
  await noHorizontalScroll(page, "zoom200-learn");
  // The course rides along: a bare /learn?view=tutor opens the default course.
  await page.goto(`/learn?course=${MATH_COURSE}&view=tutor`);
  await expect(shell(page).getByTestId("loop-phase")).toHaveAttribute("data-view", "tutor");
  await shot(page, "09-zoom200-tutor");
  await noHorizontalScroll(page, "zoom200-tutor");
  await escapeReturns(page, "zoom200-tutor-context-sheet", page.getByTestId("tutor-context-materials"), page.getByTestId("tutor-context-sheet"));
  await context.close();
});
