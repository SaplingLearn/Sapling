/**
 * Manual add-concept journey (#330).
 *
 * As the seeded student on /tree: select the MATH210 course pill (the
 * composer only renders for a single-course filter — "all" gives no course
 * to attribute the node to), add a uniquely named concept, and assert the
 * DB truth (exactly one graph_nodes row for user+course+name) plus the
 * reloaded graph rendering it via the a11y node list. Then re-add the same
 * name CASE-DRIFTED and assert the backend's UNIQUE-backed dedup merged it
 * (merge toast; still one row) instead of duplicating.
 *
 * No DB edge is asserted: with no node selected the composer sends no
 * anchor, so the node lands edge-less by design and the renderer's per-node
 * hub spoke keeps it visually attached (see graph.spec.ts's invariants).
 */
import { expect, test } from "./support/fixtures";
import { queryRaw } from "./support/db";
import { FRONTEND_URL, USER_ACTIVE } from "./support/stack";

const COURSE_ID = "rich-course-math210";
const CONCEPT = "E2E Manual Concept";

test("Tree add-concept persists, renders, and dedups on re-add (#330)", async ({ page }) => {
  await page.goto(`${FRONTEND_URL}/tree`);
  // `exact` matters: the course pill's label is a prefix of the graph node's
  // a11y activate button ("MATH210 - Linear Algebra"), so a loose match is a
  // strict-mode violation once the graph renders.
  await page.getByRole("button", { name: "MATH210", exact: true }).click();

  await page.getByTestId("graph-add-concept").click();
  await page.getByTestId("graph-add-concept-input").fill(CONCEPT);
  await page.getByTestId("graph-add-concept-submit").click();

  // DB truth first (never a bare sleep): exactly one row lands.
  await expect
    .poll(
      async () => {
        const rows = await queryRaw(
          "SELECT id FROM graph_nodes WHERE user_id = $1 AND course_id = $2 AND concept_name = $3",
          [USER_ACTIVE, COURSE_ID, CONCEPT],
        );
        return rows.length;
      },
      { timeout: 5_000, message: "the concept should persist to graph_nodes" },
    )
    .toBe(1);

  const rows = await queryRaw(
    "SELECT id FROM graph_nodes WHERE user_id = $1 AND course_id = $2 AND concept_name = $3",
    [USER_ACTIVE, COURSE_ID, CONCEPT],
  );
  const nodeId = rows[0].id as string;

  // The post-save reload renders the canonical node (a11y list, by id —
  // concept names are only unique per course).
  await expect(
    page.locator(`[data-testid="graph-node-item"][data-node-id="${nodeId}"]`),
  ).toBeAttached();

  // Re-add case-drifted → merge, not duplicate.
  await page.getByTestId("graph-add-concept").click();
  await page.getByTestId("graph-add-concept-input").fill(CONCEPT.toUpperCase());
  await page.getByTestId("graph-add-concept-submit").click();
  await expect(page.getByText(/merged into your existing/i)).toBeVisible();

  const after = await queryRaw(
    "SELECT id FROM graph_nodes WHERE user_id = $1 AND course_id = $2 AND LOWER(concept_name) = LOWER($3)",
    [USER_ACTIVE, COURSE_ID, CONCEPT],
  );
  expect(after).toHaveLength(1);
  expect(after[0].id).toBe(nodeId); // the original row survived the merge
});
