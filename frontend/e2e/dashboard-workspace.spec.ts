/**
 * Journey — the Dashboard / Home learning workspace (redesign prompt 07).
 *
 * The old dashboard.spec only proved a seeded course renders. These pin the
 * redesign's behaviour against the real stack and database:
 *
 *   1. Arrival is READ-ONLY: no loop/notes/graph mutation request leaves the
 *      page and the sessions table does not change; the one primary action
 *      reflects the student's real state.
 *   2. A loop student with an open check-in gets "Resume check-in", which
 *      reopens the SAME session (same id, no new row, no probe route).
 *   3. Selecting a topic (via View topics, by node id) shows its course,
 *      state and evidence; Back restores the next step; nothing is written.
 *   4. Practice is explicit and carries the real topic + course ids.
 *   5. Phone (390 / 320): the next action comes before the map preview, the
 *      page scrolls over the preview, View topics → selected-topic sheet with
 *      Escape + focus return, the full map dialog, and no horizontal overflow.
 *
 * Seeded data (db/seed_local_rich.py): rich-user-active (MATH210, CS101,
 * BIO110, ENG150 …; two legacy tutor sessions, two notes, no open loop
 * session) and rich-user-loop (CS101 loop chain: Binary Numbers → Bitwise
 * Operators → Two's Complement). Testids: docs/frontend-testids.md
 * `dashboard`.
 */
import type { Browser, Page, Request } from "@playwright/test";

import { queryRaw } from "./support/db";
import { expect, killSwitchLane, test } from "./support/fixtures";
import { mintStorageState } from "./support/session";
import { USER_ACTIVE, USER_LOOP } from "./support/stack";

/** A request the dashboard must never make on its own. */
function isMutation(r: Request): boolean {
  const path = new URL(r.url()).pathname;
  if (!path.startsWith("/api/")) return false;
  if (r.method() === "GET" || r.method() === "HEAD" || r.method() === "OPTIONS") return false;
  return /^\/api\/(learn|notes|graph|quiz|calendar|documents)\b/.test(path);
}

async function signIn(browser: Browser, userId: string, name: string, viewport?: { width: number; height: number }) {
  const context = await browser.newContext({
    storageState: await mintStorageState(userId, name),
    ...(viewport ? { viewport } : {}),
  });
  const page = await context.newPage();
  await page.addInitScript(() => {
    localStorage.setItem("sapling_disclaimer_ack", "true");
    localStorage.setItem("sapling_last_session_feedback", String(Date.now()));
    localStorage.setItem("sapling_last_feedback", String(Date.now()));
  });
  return { context, page };
}

const sessionsOf = async (userId: string) =>
  (await queryRaw(`SELECT id FROM sessions WHERE user_id = $1 ORDER BY id`, [userId])) as { id: string }[];

/** The shell's <main> (page-level ids read right after a navigation are
 *  scoped to it: see redesign-evidence.spec.ts::shell). */
const shell = (page: Page) => page.getByTestId("app-shell");

async function settled(page: Page) {
  await expect(shell(page).getByTestId("dashboard-next")).not.toHaveAttribute("data-state", "pending", { timeout: 30_000 });
}

test.describe("dashboard workspace", () => {
  test.skip(killSwitchLane, "loop discovery: default lane only");

  test("arrival is read-only and offers one action from the student's real state", async ({ page }) => {
    const before = await sessionsOf(USER_ACTIVE);
    const mutations: string[] = [];
    page.on("request", (r) => {
      if (isMutation(r)) mutations.push(`${r.method()} ${new URL(r.url()).pathname}`);
    });
    await page.goto("/dashboard");
    await settled(page);
    const next = shell(page).getByTestId("dashboard-next");
    // rich-user-active's seeded sessions are legacy tutor chats: no open loop session.
    await expect(next).toHaveAttribute("data-state", "loop-none");
    await expect(shell(page).getByTestId("dashboard-next-action")).toHaveCount(1);
    await expect(shell(page).getByTestId("dashboard-next-action")).toContainText("Start a check-in");
    // The map counts are the rendered graph's own: one hub per course + concepts.
    const [{ n }] = (await queryRaw(`SELECT count(*)::int AS n FROM graph_nodes WHERE user_id = $1`, [USER_ACTIVE])) as { n: number }[];
    await expect(shell(page).getByTestId("dashboard-map-counts")).toContainText(`${n} concepts`);
    // Real notes, at most two, each opening its own note.
    await expect(shell(page).getByTestId("dashboard-notes").locator('[data-testid^="dashboard-note-"]')).toHaveCount(2);
    await page.waitForTimeout(500);
    expect(mutations).toEqual([]);
    expect(await sessionsOf(USER_ACTIVE)).toEqual(before);
  });

  test("an open check-in is resumed — same session, no new row, no probe route", async ({ browser }) => {
    test.setTimeout(120_000);
    const { context, page } = await signIn(browser, USER_LOOP, "Lou Loop");
    try {
      await page.goto("/learn"); // the Learn controller starts a check-in (the explicit path)
      await expect(page.getByTestId("loop-probe-item")).toBeVisible({ timeout: 60_000 });
      const sessionId = await page.getByTestId("loop-phase").getAttribute("data-session-id");
      expect(sessionId).toBeTruthy();
      const before = await sessionsOf(USER_LOOP);

      const paths: string[] = [];
      page.on("request", (r) => paths.push(`${r.method()} ${new URL(r.url()).pathname}`));
      await page.goto("/dashboard");
      await settled(page);
      await expect(shell(page).getByTestId("dashboard-next")).toHaveAttribute("data-state", "loop-open");
      const action = shell(page).getByTestId("dashboard-next-action");
      await expect(action).toContainText("Resume check-in");
      await expect(action).toHaveAttribute("data-href", `/learn?resume=${sessionId}`);
      expect(paths.filter((p) => !p.startsWith("GET ") && p.includes("/api/learn"))).toEqual([]);
      expect(await sessionsOf(USER_LOOP)).toEqual(before);

      await action.click();
      await expect(page).toHaveURL(/\/learn\?resume=/);
      await expect(page.getByTestId("loop-phase")).toHaveAttribute("data-session-id", sessionId!);
      expect(await sessionsOf(USER_LOOP)).toEqual(before);
      expect(paths.filter((p) => p.includes("/api/learn/loop/start-session"))).toEqual([]);
    } finally {
      await context.close();
    }
  });

  test("selecting a topic shows its context by id; Back restores the next step; Practice keeps the ids", async ({ page }) => {
    const [node] = (await queryRaw(
      `SELECT id, concept_name, course_id FROM graph_nodes WHERE user_id = $1 ORDER BY concept_name LIMIT 1`,
      [USER_ACTIVE],
    )) as { id: string; concept_name: string; course_id: string }[];
    const before = await sessionsOf(USER_ACTIVE);
    const mutations: string[] = [];
    page.on("request", (r) => {
      if (isMutation(r)) mutations.push(new URL(r.url()).pathname);
    });
    await page.goto("/dashboard");
    await settled(page);

    await shell(page).getByTestId("dashboard-view-topics").click();
    const sheet = page.getByTestId("dashboard-topics");
    await expect(sheet).toBeVisible();
    await sheet.getByTestId(`dashboard-topic-${node.id}`).click();
    const detail = shell(page).getByTestId("dashboard-concept");
    await expect(detail).toHaveAttribute("data-node-id", node.id);
    await expect(detail.getByRole("heading", { level: 2 })).toHaveText(node.concept_name);
    await expect(shell(page).getByTestId("dashboard-concept-evidence")).toBeVisible();
    // The canvas marks the same node.
    await expect(shell(page).locator(`[data-testid="graph-node"][data-node-id="${node.id}"]`)).toHaveAttribute("data-selected", "true");

    await shell(page).getByTestId("dashboard-concept-back").click();
    await expect(shell(page).getByTestId("dashboard-next")).toBeVisible();
    await expect(shell(page).locator('[data-testid="graph-node"][data-selected="true"]')).toHaveCount(0);
    expect(mutations).toEqual([]);
    expect(await sessionsOf(USER_ACTIVE)).toEqual(before);

    // Practice is the explicit exit, with the real topic and course ids.
    await shell(page).getByTestId("dashboard-view-topics").click();
    await page.getByTestId("dashboard-topics").getByTestId(`dashboard-topic-${node.id}`).click();
    await shell(page).getByTestId("dashboard-concept-practice").click();
    await expect(page).toHaveURL(new RegExp(`/learn\\?topic=.+&course=${node.course_id}`));
  });

  test("full map: a labelled dialog that closes with Escape and returns focus", async ({ page }) => {
    await page.goto("/dashboard");
    await settled(page);
    const opener = shell(page).getByTestId("dashboard-open-map");
    await opener.focus();
    await page.keyboard.press("Enter");
    const dialog = page.getByRole("dialog", { name: "Your knowledge map" });
    await expect(dialog).toBeVisible();
    await expect(page.getByTestId("graph-container")).toHaveCount(1);
    await expect(dialog.getByTestId("graph-zoom-in")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(opener).toBeFocused();
  });

  for (const width of [390, 320] as const) {
    test(`phone ${width}: next action before the map preview, normal scrolling, topic sheet, no overflow`, async ({ browser }) => {
      const { context, page } = await signIn(browser, USER_ACTIVE, "Rich Active", { width, height: 740 });
      try {
        await page.goto("/dashboard");
        await settled(page);
        const action = shell(page).getByTestId("dashboard-next-action");
        const preview = shell(page).getByTestId("dashboard-map-preview");
        await expect(preview).toBeVisible();
        const a = (await action.boundingBox())!;
        const p = (await preview.boundingBox())!;
        expect(a.y).toBeLessThan(p.y); // phone order: goal → next activity/action → map
        // The preview is a static overview: the page keeps its touch scrolling.
        await expect(preview.getByRole("img", { name: "Knowledge graph" })).toHaveCSS("touch-action", "pan-y");
        await expect(preview.getByTestId("graph-zoom-in")).toHaveCount(0);
        // A wheel over the preview scrolls the shell's scroll container, not the map.
        const scroller = shell(page);
        const top0 = await scroller.evaluate((el) => el.scrollTop);
        await preview.hover();
        await page.mouse.wheel(0, 400);
        await expect.poll(() => scroller.evaluate((el) => el.scrollTop)).toBeGreaterThan(top0);
        // No horizontal page overflow.
        expect(await scroller.evaluate((el) => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(1);

        // View topics → pick → the selected-topic sheet; Escape → focus back to View topics.
        const topics = shell(page).getByTestId("dashboard-view-topics");
        await topics.click();
        const list = page.getByTestId("dashboard-topics");
        await expect(list).toBeVisible();
        await list.locator('[data-testid^="dashboard-topic-"][data-node-id]').first().click();
        const sheet = page.getByTestId("dashboard-concept-sheet");
        await expect(sheet).toBeVisible();
        await expect(sheet.getByTestId("dashboard-sheet-concept-practice")).toBeVisible();
        await expect(sheet.getByTestId("dashboard-sheet-concept-back")).toBeVisible();
        await page.keyboard.press("Escape");
        await expect(sheet).toHaveCount(0);
        await expect(topics).toBeFocused();

        // Open full map deliberately; it closes back to the page.
        await shell(page).getByTestId("dashboard-open-map").click();
        await expect(page.getByTestId("dashboard-full-map")).toBeVisible();
        await page.getByTestId("dashboard-full-map-close").click();
        await expect(page.getByTestId("dashboard-full-map")).toHaveCount(0);
      } finally {
        await context.close();
      }
    });
  }
});
