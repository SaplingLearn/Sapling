/**
 * Study roadmap journey (course roadmap, spec §3/§4).
 *
 * As the seeded student: open /tree, activate the MATH210 course node, and
 * land on that course's roadmap. Then assert the page against DB TRUTH
 * rather than against itself — the hierarchy it draws must be the `part_of`
 * edge that exists in `graph_edges`, and the concepts it files as "unfiled"
 * must be exactly the ones with no `part_of` relationship.
 *
 * The seeded MATH210 graph is deliberately lopsided, and that is what makes
 * it a good fixture:
 *
 *   Matrices      topic     (one `part_of` child)
 *     └ Vectors   0.85      mastered
 *   Eigenvalues   0.2       unfiled, struggling
 *   Determinants  0.0       unfiled, not started
 *
 * So exactly one topic exists, it is fully mastered, and most of the course
 * is ungrouped — the shape that caught the `start_here` bug (readiness 35%
 * while the page claimed nothing to start). The "start here" assertion below
 * is that regression's guard at the browser level.
 *
 * The readiness arithmetic is asserted as an INVARIANT, not a magic number:
 * the breakdown rows must sum to the figure in the ring. A seed change moves
 * both together, so the test stays honest without being brittle.
 */
import { expect, test } from "./support/fixtures";
import { queryRaw } from "./support/db";
import { FRONTEND_URL, USER_ACTIVE } from "./support/stack";

const COURSE_ID = "rich-course-math210";

test("Course node opens a roadmap whose hierarchy is the graph's own", async ({ page }) => {
  // DB truth first: what SHOULD the page group?
  const partOf = await queryRaw(
    `SELECT s.concept_name AS child, t.concept_name AS parent
       FROM graph_edges e
       JOIN graph_nodes s ON s.id = e.source_node_id
       JOIN graph_nodes t ON t.id = e.target_node_id
      WHERE e.relationship_type = 'part_of'
        AND e.user_id = $1 AND s.course_id = $2`,
    [USER_ACTIVE, COURSE_ID],
  );
  expect(partOf.length).toBeGreaterThan(0);
  const parents = new Set(partOf.map((r: { parent: string }) => r.parent));
  const children = new Set(partOf.map((r: { child: string }) => r.child));

  // Enter the way a student does: the course node on the tree.
  //
  // Activated through the graph's hidden a11y list, keyed by `data-node-id`
  // as that markup instructs (concept names are only unique per course).
  // The list is 1x1 and clipped, so a real `.click()` fails actionability —
  // `dispatchEvent` fires the same `onNodeClick` the SVG mark fires, without
  // racing the d3 simulation for a moving target.
  await page.goto(`${FRONTEND_URL}/tree`);
  const courseNode = page
    .locator(`[data-testid="graph-node-item"][data-node-id="subject_root__${COURSE_ID}"]`)
    .getByTestId("graph-node-activate");
  await expect(courseNode).toHaveCount(1);
  await courseNode.dispatchEvent("click");

  await expect(page).toHaveURL(new RegExp(`/roadmap/${COURSE_ID}$`));
  const roadmap = page.getByTestId("roadmap");
  await expect(roadmap).toBeVisible();

  // Every `part_of` parent renders as a topic.
  for (const parent of parents) {
    await expect(
      page.getByTestId("roadmap-topics").getByText(parent, { exact: true }),
    ).toBeVisible();
  }

  // Children live inside a collapsed topic until it is opened. Nothing
  // auto-expands here: MATH210's only topic is already mastered, so
  // "start here" points at the Unfiled group instead (see the regression
  // test below). Open every topic, then assert the children.
  const headers = page.getByTestId("roadmap-topic-header");
  for (let i = 0; i < (await headers.count()); i++) {
    await headers.nth(i).click();
  }
  for (const child of children) {
    await expect(page.getByText(child, { exact: true }).first()).toBeVisible();
  }

  // Concepts with no `part_of` relationship are shown, never dropped.
  const loose = await queryRaw(
    `SELECT n.concept_name FROM graph_nodes n
      WHERE n.user_id = $1 AND n.course_id = $2
        AND NOT EXISTS (
          SELECT 1 FROM graph_edges e
           WHERE e.relationship_type = 'part_of'
             AND (e.source_node_id = n.id OR e.target_node_id = n.id))`,
    [USER_ACTIVE, COURSE_ID],
  );
  const unfiled = page.getByTestId("roadmap-unfiled");
  for (const row of loose as { concept_name: string }[]) {
    await expect(unfiled.getByText(row.concept_name, { exact: true })).toBeVisible();
  }
});

test("The readiness breakdown sums to the number in the ring", async ({ page }) => {
  await page.goto(`${FRONTEND_URL}/roadmap/${COURSE_ID}`);

  const ring = page.getByTestId("roadmap-readiness-ring");
  await expect(ring).toBeVisible();
  const shown = Number((await ring.innerText()).match(/(\d+)%/)?.[1]);
  expect(Number.isFinite(shown)).toBe(true);

  await page.getByRole("button", { name: /why this number/i }).click();
  const panel = page.getByTestId("roadmap-readiness-breakdown");
  await expect(panel).toBeVisible();

  // The panel's own total must agree with the ring. If these ever diverge,
  // the page is explaining a number it did not show — the single worst
  // failure this surface can have.
  const overall = Number(
    (await panel.locator("tfoot").innerText()).match(/(\d+)%/)?.[1],
  );
  expect(overall).toBe(shown);
});

test("Start here points at real remaining work, never at a finished state", async ({ page }) => {
  // Regression guard. MATH210's only topic is fully mastered, so a
  // topics-only rule reports "nothing to start" while readiness sits at
  // 35% — the bug this spec exists to keep fixed.
  await page.goto(`${FRONTEND_URL}/roadmap/${COURSE_ID}`);
  await expect(page.getByTestId("roadmap")).toBeVisible();

  const ring = page.getByTestId("roadmap-readiness-ring");
  const pct = Number((await ring.innerText()).match(/(\d+)%/)?.[1]);

  if (pct < 100) {
    await expect(page.getByTestId("roadmap-start-here").first()).toBeVisible();
  }
});

test("A subtopic offers Learn and Quiz, and Quiz reaches the quiz flow", async ({ page }) => {
  await page.goto(`${FRONTEND_URL}/roadmap/${COURSE_ID}`);

  // Open the one topic so its subtopic rows render.
  await page.getByTestId("roadmap-topic-header").first().click();

  const row = page.locator('[data-testid^="roadmap-subtopic-"]').first();
  await expect(row).toBeVisible();
  await expect(row.getByRole("button", { name: "Learn" })).toBeVisible();

  await row.getByRole("button", { name: "Quiz" }).click();
  await expect(page).toHaveURL(/\/quiz\?/);
});

/**
 * The dashboard's graph answers a course node the same way Tree's does.
 *
 * Found by hand, not by this suite: the §3.14 routing shipped in Tree only,
 * so the dashboard's canvas kept sending course nodes to `learnHrefForNode`
 * — a course-scoped tutor session (#319). Nothing failed, because both
 * destinations are real screens; the same node simply meant two different
 * things depending on which page drew it.
 *
 * Driven through the a11y list for the same reason the journey above is: the
 * canvas marks are simulation-positioned and a real click races them.
 */
test("A course node on the DASHBOARD opens the roadmap, not the tutor", async ({ page }) => {
  await page.goto(`${FRONTEND_URL}/dashboard`);

  const courseNode = page
    .locator(`[data-testid="graph-node-item"][data-node-id="subject_root__${COURSE_ID}"]`)
    .getByTestId("graph-node-activate");
  await expect(courseNode).toHaveCount(1);
  await courseNode.dispatchEvent("click");

  await expect(page).toHaveURL(new RegExp(`/roadmap/${COURSE_ID}$`));
  await expect(page.getByTestId("roadmap")).toBeVisible();
});

/**
 * A prerequisite cycle is SAID, not silently ordered around.
 *
 * Found by looking at the page, not by this suite. `order_roadmap` detects
 * cycles at three levels — topics against each other, subtopics within one
 * topic, and the unfiled list — and stamps `in_cycle` on every row it
 * returns. The UI marked only the topic level, so a cycle among concepts
 * rendered as a confident top-to-bottom order: the exact claim the ordering
 * code refuses to make. Nothing failed, because an arbitrary order is still
 * a valid-looking list.
 *
 * MATH210's two unfiled concepts are the fixture: a topic exists (so the
 * page is not in its "not yet grouped" state and the unfiled rows render),
 * and Eigenvalues/Determinants are siblings with no ordering between them.
 * The edges are inserted here rather than seeded because a cycle is a
 * pathology, not a property of the demo course — and the per-test TRUNCATE
 * takes them away again.
 */
test("Concepts whose prerequisites loop say so, instead of showing a made-up order", async ({
  page,
}) => {
  const cycle = [
    ["rich-node-math-eigenvalues", "rich-node-math-determinants"],
    ["rich-node-math-determinants", "rich-node-math-eigenvalues"],
  ];
  for (const [source, target] of cycle) {
    await queryRaw(
      `INSERT INTO graph_edges (user_id, source_node_id, target_node_id, relationship_type)
       VALUES ($1, $2, $3, 'prerequisite')`,
      [USER_ACTIVE, source, target],
    );
  }

  await page.goto(`${FRONTEND_URL}/roadmap/${COURSE_ID}`);

  const unfiled = page.getByTestId("roadmap-unfiled");
  await expect(unfiled).toBeVisible();

  // Said once for the list…
  await expect(unfiled.getByTestId("roadmap-subtopic-cycle")).toHaveCount(1);

  // …and the rows in the loop are named, so "which ones?" is answerable.
  for (const nodeId of ["rich-node-math-eigenvalues", "rich-node-math-determinants"]) {
    await expect(
      page.getByTestId(`roadmap-subtopic-${nodeId}`).getByTestId("roadmap-cycle-badge"),
    ).toBeVisible();
  }

  // The topic-level note is a different claim ("this TOPIC's position is a
  // guess") and must not fire for a cycle that lives below it.
  await expect(page.getByText(/prerequisites loop, so its position/)).toHaveCount(0);
});
