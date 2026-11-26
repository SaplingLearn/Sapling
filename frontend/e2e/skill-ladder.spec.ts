/**
 * skill_ladder (Tutor redesign phase 2: one skill measure). With the learning
 * loop and the student's `skill_ladder` flag on, GET /api/graph gives each
 * concept the learner model's decayed skill (`skill`, null until the concept
 * has a graded answer of its own), and the frontend reads the whole graph on
 * the ladder (frontend/src/lib/levels.ts): Not started / Getting started /
 * Developing / Proficient, never "Mastered" for a level. With the flag off —
 * every other spec — the map's stored score and four tiers, as before.
 *
 * The journey seeds its own learner-model rows for three concepts of one
 * course (the rich seed has none) and turns the flag on for the student only;
 * the per-test reset wipes both.
 */
import type { Page } from "@playwright/test";

import { queryRaw, setUserFlag } from "./support/db";
import { expect, loopOffLane, test } from "./support/fixtures";
import { FRONTEND_URL, USER_ACTIVE } from "./support/stack";

type Seeded = { courseId: string; proficient: string; developing: string; notStarted: string };

/** Three concepts of one course: one proficient (90%), one developing (50%),
 *  one with no graded answer. Evidence "now" and a long stability, so the
 *  read-time decay leaves the numbers as written. */
async function seedSkills(): Promise<Seeded> {
  const rows = await queryRaw(
    `SELECT id, course_id FROM graph_nodes
     WHERE user_id = $1 AND course_id IS NOT NULL ORDER BY course_id, id`,
    [USER_ACTIVE],
  );
  const byCourse = new Map<string, string[]>();
  for (const r of rows) {
    const ids = byCourse.get(String(r.course_id)) ?? [];
    ids.push(String(r.id));
    byCourse.set(String(r.course_id), ids);
  }
  const found = [...byCourse.entries()].find(([, ids]) => ids.length >= 3);
  expect(found, "the rich seed has a course with three concepts").toBeTruthy();
  const [courseId, [proficient, developing, notStarted]] = found!;
  await queryRaw(`DELETE FROM learner_state WHERE user_id = $1`, [USER_ACTIVE]);
  await queryRaw(
    `INSERT INTO learner_state (user_id, node_id, p_known, opps, n_strong_unassisted, fsrs_s, last_evidence_at)
     VALUES ($1, $2, 0.9, 3, 1, 365, now()), ($1, $3, 0.5, 2, 0, 365, now())`,
    [USER_ACTIVE, proficient, developing],
  );
  return { courseId, proficient, developing, notStarted };
}

async function graphNodes(page: Page): Promise<Record<string, Record<string, unknown>>> {
  const res = await page.request.get(`${FRONTEND_URL}/api/graph/${USER_ACTIVE}`);
  expect(res.ok()).toBe(true);
  const body = (await res.json()) as { nodes: Record<string, unknown>[] };
  return Object.fromEntries(body.nodes.map((n) => [String(n.id), n]));
}

test("skill_ladder off: the graph carries no skill (the map's tiers, as before)", async ({ page }) => {
  test.skip(loopOffLane, "the ladder needs the learning loop");
  await seedSkills();
  const nodes = await graphNodes(page);
  expect(Object.values(nodes).some((n) => "skill" in n)).toBe(false);
});

test("skill_ladder on: the graph carries the learner model's skill; the Tree and Study name the ladder's levels", async ({ page }) => {
  test.skip(loopOffLane, "the ladder needs the learning loop");
  const seeded = await seedSkills();
  await setUserFlag("skill_ladder", USER_ACTIVE, "on");

  // The API: a measured concept's decayed skill; a concept with no graded answer is null.
  const nodes = await graphNodes(page);
  expect(nodes[seeded.proficient].skill).toBeCloseTo(0.9, 2);
  expect(nodes[seeded.developing].skill).toBeCloseTo(0.5, 2);
  expect(nodes[seeded.notStarted].skill).toBeNull();
  expect(nodes[seeded.proficient].skill_mastered).toBe(false); // the badge needs ≥ 98% and three strong answers

  // The Tree: its filter says the ladder's words, and filters by them.
  await page.goto("/tree");
  for (const word of ["Proficient", "Developing", "Getting started", "Not started"]) {
    await expect(page.getByRole("button", { name: word, exact: true })).toBeVisible();
  }
  await expect(page.getByRole("button", { name: "Mastered", exact: true })).toHaveCount(0);
  const items = page.getByTestId("graph-container").getByTestId("graph-node-item");
  const node = (id: string) => items.and(page.locator(`[data-node-id=${JSON.stringify(id)}]`));
  await page.getByRole("button", { name: "Proficient", exact: true }).click();
  await expect(node(seeded.proficient)).toHaveCount(1);
  await expect(node(seeded.developing)).toHaveCount(0);
  await page.getByRole("button", { name: "Not started", exact: true }).click();
  await expect(node(seeded.notStarted)).toHaveCount(1);
  await expect(node(seeded.proficient)).toHaveCount(0);

  // Study: the readiness legend counts the course's concepts on the ladder.
  await page.goto(`/study?course=${encodeURIComponent(seeded.courseId)}`);
  await expect(page.getByRole("button", { name: /^\d+ Proficient$/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /^\d+ Mastered$/ })).toHaveCount(0);
});
