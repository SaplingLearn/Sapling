/**
 * Tutor V2 starts a session on what the student chose, and manages its
 * sessions (PR #866 audit K05, K30, K31). Default lane only: in the
 * kill-switch and flag-off lanes /learn is the legacy screen, which these
 * paths do not touch (a map link's extra `concept` parameter is ignored there).
 *
 *  1. K05 — "Start with X" on the Tutor home, and a map concept's Learn link
 *     (`/learn?topic=X&concept=<node id>&course=<course>`, learnHrefForNode),
 *     start a session whose goal is X: sessions.loop_state.goal names the node,
 *     and the scope line says so — never a whole-course session titled X. A
 *     note's Send to tutor starts on the note's linked concepts the same way.
 *  2. K30 — "Set a goal" shows the goal editor before anything starts: no
 *     session row, nothing posed. Saving starts the session on the goal, so its
 *     check-in burns no item (probe.unavailable stays empty).
 *  3. K31 — every session's list renames a session (sessions.topic) and deletes
 *     it (the row is gone), as the legacy Learn screen's recent sessions do.
 */
import type { Browser, Page } from "@playwright/test";

import { expect, loopOffLane, test } from "./support/fixtures";
import { queryRaw } from "./support/db";
import { mintStorageState } from "./support/session";
import { USER_LOOP } from "./support/stack";

const COURSE = "rich-course-cs101";
const JOURNEY_TIMEOUT_MS = 120_000;

async function signIn(browser: Browser) {
  const context = await browser.newContext({ storageState: await mintStorageState(USER_LOOP, "Lou Loop") });
  const page = await context.newPage();
  await page.addInitScript(() => {
    localStorage.setItem("sapling_disclaimer_ack", "true");
  });
  return { context, page };
}

async function nodeId(name: string): Promise<string> {
  const [row] = await queryRaw("SELECT id FROM graph_nodes WHERE user_id = $1 AND course_id = $2 AND concept_name = $3", [
    USER_LOOP, COURSE, name,
  ]);
  expect(row, `seeded concept ${name}`).toBeTruthy();
  return String(row.id);
}

/** The session the check-in materialised (its first /probe/next writes the row). */
async function startedSession(page: Page): Promise<{ id: string; state: Record<string, unknown> }> {
  await expect(page.getByTestId("loop-probe-item")).toBeVisible();
  const id = await page.getByTestId("loop-phase").getAttribute("data-session-id");
  expect(id).toBeTruthy();
  let state: Record<string, unknown> = {};
  await expect.poll(async () => {
    const [row] = await queryRaw("SELECT loop_state FROM sessions WHERE id = $1", [id]);
    state = (row?.loop_state ?? {}) as Record<string, unknown>;
    return !!row;
  }).toBe(true);
  return { id: id!, state };
}

const goalTargets = (state: Record<string, unknown>) =>
  ((state.goal as { target_node_ids?: string[] } | undefined)?.target_node_ids ?? []);

test.describe("Tutor V2: a session on what the student chose", () => {
  test.skip(loopOffLane, "loop path: default lane only");
  test.setTimeout(JOURNEY_TIMEOUT_MS);

  test("K05: Start with X starts a session whose goal is X", async ({ browser }) => {
    const { context, page } = await signIn(browser);
    try {
      await page.goto("/learn");
      const startWith = page.getByTestId("tutor-home-start-with");
      await expect(startWith).toBeVisible();
      const name = ((await startWith.textContent()) ?? "").replace(/^Start with\s*/, "").trim();
      expect(name).not.toBe("");
      await startWith.click();
      const { state } = await startedSession(page);
      expect(goalTargets(state)).toEqual([await nodeId(name)]);
      await expect(page.getByTestId("loop-goal-summary")).toContainText(name);
      await expect(page.getByTestId("loop-goal-summary")).not.toContainText("whole course");
    } finally {
      await context.close();
    }
  });

  test("K05: a map concept's Learn link starts a session on that concept", async ({ browser }) => {
    const { context, page } = await signIn(browser);
    try {
      const name = "Two's Complement";
      const id = await nodeId(name);
      const link = new URLSearchParams({ topic: name, concept: id, mode: "socratic", course: COURSE });
      await page.goto(`/learn?${link}`);
      const { state } = await startedSession(page);
      expect(goalTargets(state)).toEqual([id]);
      await expect(page.getByTestId("loop-goal-summary")).toContainText(name);
    } finally {
      await context.close();
    }
  });

  test("K05: Send to tutor starts a session on the note's linked concepts", async ({ browser }) => {
    const { context, page } = await signIn(browser);
    try {
      const linked = ["Bitwise Operators", "Two's Complement"];
      await page.goto("/notetaker");
      await page.getByRole("button", { name: /Create your first note/ }).click();
      await page.getByRole("dialog").filter({ hasText: "Which course is this for?" }).getByRole("button").first().click();
      await page.getByPlaceholder("Untitled note").fill("Bit tricks");
      for (const name of linked) {
        await page.getByRole("button", { name: "Link concept" }).click();
        const picker = page.getByRole("dialog").filter({ hasText: "Pick a concept to link" });
        await picker.getByRole("button", { name: new RegExp(`^${name}\\b`) }).click();
        await expect(picker).toHaveCount(0);
        await expect(page.getByLabel(`Unlink ${name}`)).toBeVisible();
      }
      await page.getByRole("button", { name: "Send to tutor" }).click();
      await expect(page).toHaveURL(/\/learn\?/, { timeout: 30_000 });
      const { state } = await startedSession(page);
      expect([...goalTargets(state)].sort()).toEqual((await Promise.all(linked.map(nodeId))).sort());
      for (const name of linked) await expect(page.getByTestId("loop-goal-summary")).toContainText(name);
    } finally {
      await context.close();
    }
  });

  test("K30: Set a goal comes before the session, so its check-in burns nothing", async ({ browser }) => {
    const { context, page } = await signIn(browser);
    try {
      const sessionIds = async () =>
        (await queryRaw("SELECT id FROM sessions WHERE user_id = $1", [USER_LOOP])).map((r) => String(r.id)).sort();
      await page.goto("/learn");
      await expect(page.getByTestId("tutor-home")).toBeVisible();
      const before = await sessionIds();
      await page.getByTestId("tutor-home-goal").click();
      const editor = page.getByRole("form", { name: "Learning goal" });
      await expect(editor).toBeVisible();
      await expect(page.getByTestId("loop-phase")).toHaveAttribute("data-view", "goal");
      await expect(page.getByTestId("loop-phase")).toHaveAttribute("data-session-id", "");
      expect(await sessionIds()).toEqual(before); // nothing started, nothing posed
      await editor.getByRole("checkbox", { name: "Bitwise Operators", exact: true }).check();
      await editor.getByTestId("loop-goal-save").click();
      const { state } = await startedSession(page);
      expect(goalTargets(state)).toEqual([await nodeId("Bitwise Operators")]);
      const probe = (state.probe ?? {}) as { unavailable?: string[] };
      expect(probe.unavailable ?? []).toEqual([]); // no item posed before the goal and burnt by it
      await expect(page.getByTestId("loop-goal-summary")).toContainText("Bitwise Operators");
    } finally {
      await context.close();
    }
  });

  test("K31: every session's list renames and deletes a session", async ({ browser }) => {
    const { context, page } = await signIn(browser);
    try {
      await page.goto("/learn");
      await page.getByTestId("loop-start-guided").click();
      const { id } = await startedSession(page);
      await page.getByTestId("tutor-view-all").click();
      const list = page.getByTestId("tutor-all-sessions");
      await expect(list.getByTestId(`tutor-session-row-${id}`)).toBeVisible();

      await list.getByTestId(`tutor-session-rename-${id}`).click();
      const field = list.getByTestId(`tutor-session-name-${id}`);
      await field.fill("Bits before Friday");
      await field.press("Enter");
      await expect(list.getByTestId(`tutor-session-row-${id}`)).toContainText("Bits before Friday");
      await expect.poll(async () => (await queryRaw("SELECT topic FROM sessions WHERE id = $1", [id]))[0]?.topic)
        .toBe("Bits before Friday");

      const del = list.getByTestId(`tutor-session-delete-${id}`);
      await del.click();
      await expect(del).toHaveText("Confirm delete");
      await del.click();
      await expect(list.getByTestId(`tutor-session-row-${id}`)).toHaveCount(0);
      await expect.poll(async () => (await queryRaw("SELECT id FROM sessions WHERE id = $1", [id])).length).toBe(0);
      await expect(page.getByTestId("loop-phase")).toHaveAttribute("data-session-id", "");
    } finally {
      await context.close();
    }
  });
});

test.describe("Tutor V2: skill meters read as the map does", () => {
  test.skip(loopOffLane, "loop path: default lane only");
  test.setTimeout(JOURNEY_TIMEOUT_MS);

  // K21: the course page's progress meters take the map's tier for each concept
  // (mastered / learning / struggling / unexplored), never the retired 0.75 / 0.45 cuts.
  test("K21: every progress meter on the course page names its concept's map tier", async ({ browser }) => {
    const { context, page } = await signIn(browser);
    try {
      await page.goto("/learn");
      await page.getByTestId(`tutor-course-${COURSE}`).click();
      const coursePage = page.getByTestId("tutor-course-page");
      await expect(coursePage).toBeVisible();
      const meters = coursePage.locator("[data-tier]");
      await expect(meters.first()).toBeVisible();
      const rows = await queryRaw(
        "SELECT concept_name, mastery_tier FROM graph_nodes WHERE user_id = $1 AND course_id = $2",
        [USER_LOOP, COURSE],
      );
      const tierOf = new Map(rows.map((r) => [String(r.concept_name), String(r.mastery_tier)]));
      const shown = await meters.evaluateAll((els) => els.map((el) => ({
        name: el.querySelector("span")?.getAttribute("title") ?? "",
        tier: el.getAttribute("data-tier") ?? "",
      })));
      expect(shown.length).toBeGreaterThan(0);
      for (const { name, tier } of shown) expect(tier, name).toBe(tierOf.get(name));
    } finally {
      await context.close();
    }
  });
});
