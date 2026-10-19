/** The Tutor map is the current learner session's real course graph. Opening
 * and closing it must preserve the unsent conversation and all learning data. */
import type { Page } from "@playwright/test";

import { queryRaw } from "./support/db";
import { expect, killSwitchLane, test } from "./support/fixtures";
import { setUserFlag } from "./support/flags";
import { learningParams } from "./support/params";
import { mintStorageState } from "./support/session";
import { USER_LOOP } from "./support/stack";

const CORRECT = "E2E_GRADER_CORRECT"; // function_handlers_e2e.E2E_GRADER_CORRECT_TOKEN
const WORKING = "working: I think it is the value the item names";
const DRAFT = "Can you explain how this concept connects to my goal? (unsent map draft)";

async function checkInAndApprove(page: Page, cap: number) {
  const phase = page.getByTestId("loop-phase");
  const item = page.getByTestId("loop-probe-item");
  const readProbe = () => phase.evaluate((el) => ({
    phase: el.getAttribute("data-phase"),
    hash: el.querySelector('[data-testid="loop-probe-item"]')?.getAttribute("data-question-hash") ?? null,
    reference: !!el.querySelector('[data-testid="loop-probe-reference"]'),
  }));
  let answered = 0;
  while ((await phase.getAttribute("data-phase")) === "probe" && answered < cap) {
    await expect(item).toBeVisible();
    const hash = await item.getAttribute("data-question-hash");
    const difficulty = Number(await item.getAttribute("data-difficulty"));
    await page.getByTestId("loop-probe-input").fill(difficulty === 1 ? CORRECT : WORKING);
    await page.getByTestId("loop-probe-submit").click();
    answered++;
    await expect.poll(async () => {
      const current = await readProbe();
      return current.phase !== "probe" || current.reference || (current.hash !== null && current.hash !== hash);
    }).toBe(true);
    if ((await readProbe()).reference) {
      await page.getByTestId("loop-probe-next").click();
      await expect.poll(async () => {
        const current = await readProbe();
        return current.phase !== "probe" || (current.hash !== null && current.hash !== hash);
      }).toBe(true);
    }
  }
  await expect(phase).toHaveAttribute("data-phase", "plan");
  await page.getByTestId("loop-plan-approve").click();
  await expect(phase).toHaveAttribute("data-phase", "teach");
}

async function learnerState() {
  return queryRaw(
    `SELECT
       (SELECT jsonb_agg(to_jsonb(s) ORDER BY s.id) FROM sessions s WHERE s.user_id = $1) AS sessions,
       (SELECT jsonb_agg(to_jsonb(n) ORDER BY n.id) FROM graph_nodes n WHERE n.user_id = $1) AS nodes,
       (SELECT jsonb_agg(to_jsonb(e) ORDER BY e.id) FROM node_mastery_events e
         JOIN graph_nodes n ON n.id = e.node_id WHERE n.user_id = $1) AS mastery_events`,
    [USER_LOOP],
  );
}

function tierFill(score: number) {
  return score >= 0.95 ? "#a3b06d" : score >= 0.3 ? "#fcc98a" : score >= 0.1 ? "#ef908f" : "#decdc1";
}

for (const width of [1440, 390]) {
  test(`Tutor map ${width}: real session course and Pen marks preserve the draft, goal and knowledge`, async ({ browser }) => {
    test.skip(killSwitchLane, "Tutor learning loop: default lane only");
    test.setTimeout(240_000);
    await setUserFlag(browser, "tutor_view", USER_LOOP, "on");
    const params = await learningParams(["PROBE_SESSION_CAP"]);
    const context = await browser.newContext({
      storageState: await mintStorageState(USER_LOOP, "Lou Loop"),
      viewport: { width, height: 950 },
    });
    const page = await context.newPage();
    await page.addInitScript(() => {
      localStorage.setItem("sapling_disclaimer_ack", "true");
      localStorage.setItem("sapling.kg.mode", "2d");
      localStorage.setItem("sapling_last_session_feedback", String(Date.now()));
      localStorage.setItem("sapling_last_feedback", String(Date.now()));
    });
    try {
      await page.goto("/learn?view=tutor");
      await expect(page.getByTestId("tutor-welcome")).toBeVisible();
      await page.getByTestId("tutor-welcome-start").click();
      await expect(page.getByTestId("loop-phase")).toHaveAttribute("data-phase", "probe");
      await checkInAndApprove(page, Number(params.PROBE_SESSION_CAP));
      const phase = page.getByTestId("loop-phase");
      const sessionId = (await phase.getAttribute("data-session-id"))!;
      expect(sessionId).toBeTruthy();
      const [session] = (await queryRaw(
        `SELECT co.course_id, c.course_code FROM sessions s
           JOIN course_offerings co ON co.id = s.offering_id
           JOIN courses c ON c.id = co.course_id WHERE s.id = $1 AND s.user_id = $2`,
        [sessionId, USER_LOOP],
      )) as { course_id: string; course_code: string }[];
      expect(session?.course_id).toBeTruthy();
      const nodes = (await queryRaw(
        `SELECT id, concept_name, mastery_score FROM graph_nodes
          WHERE user_id = $1 AND course_id = $2 ORDER BY id`,
        [USER_LOOP, session.course_id],
      )) as { id: string; concept_name: string; mastery_score: number }[];
      expect(nodes.length).toBeGreaterThan(0);
      const input = page.getByTestId("tutor-input");
      await input.fill(DRAFT);
      const before = await learnerState();
      const mutations: string[] = [];
      page.on("request", (request) => {
        const path = new URL(request.url()).pathname;
        if (!["GET", "HEAD", "OPTIONS"].includes(request.method()) && /^\/api\/(learn|graph|quiz)\b/.test(path)) {
          mutations.push(`${request.method()} ${path}`);
        }
      });
      const opener = page.getByTestId("tutor-context-map");
      await opener.click();
      const map = page.getByTestId("tutor-map");
      await expect(map).toBeVisible();
      await expect(map).toContainText(session.course_code);
      await expect(map.locator('svg[data-renderer="pen"]')).toBeVisible();
      const graph = map.getByTestId("graph-container");
      const expectedIds = [...nodes.map((n) => n.id), `subject_root__${session.course_id}`].sort();
      await expect(graph.getByTestId("graph-node")).toHaveCount(expectedIds.length);
      expect(await graph.getByTestId("graph-node").evaluateAll((els) => els.map((el) => el.getAttribute("data-node-id")).sort())).toEqual(expectedIds);
      for (const n of nodes) {
        const mark = graph.locator(`[data-testid="graph-node"][data-node-id=${JSON.stringify(n.id)}]`).getByTestId("graph-node-circle");
        expect((await mark.getAttribute("fill"))?.toLowerCase()).toBe(tierFill(Number(n.mastery_score)));
        await expect(mark).toHaveAttribute("opacity", "1");
      }
      const hub = graph.locator(`[data-testid="graph-node"][data-node-id="subject_root__${session.course_id}"]`);
      expect((await hub.getByTestId("graph-node-circle").getAttribute("fill"))?.toLowerCase()).toBe("#6c462f");
      await expect(map.getByTestId("tutor-map-full")).toHaveAttribute("href", /^\/tree/);
      if (width < 768) {
        await expect(page.getByTestId("tutor-context-sheet")).toBeVisible();
        await page.keyboard.press("Escape");
        await expect(page.getByTestId("tutor-context-sheet")).toHaveCount(0);
      } else {
        await page.getByTestId("tutor-context-close").click();
        await expect(page.getByTestId("tutor-context-panel")).toHaveCount(0);
      }
      await expect(map).toHaveCount(0);
      await expect(opener).toBeFocused();
      await expect(input).toHaveValue(DRAFT);
      await expect(phase).toHaveAttribute("data-session-id", sessionId);
      await expect(phase).toHaveAttribute("data-phase", "teach");
      expect(mutations).toEqual([]);
      expect(await learnerState()).toEqual(before);
    } finally {
      await context.close();
    }
  });
}
