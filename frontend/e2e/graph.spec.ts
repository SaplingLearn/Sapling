/**
 * Journey #395 — graph render integrity vs the database.
 *
 * Loads /tree (the knowledge-graph view) and asserts the RENDERED graph
 * matches what raw SQL says the database holds (support/db.ts::queryRaw):
 *
 *   - counts — one rendered node per `graph_nodes` row plus one synthesized
 *     subject-root hub per distinct enrolled course, one rendered edge per
 *     `graph_edges` row (both endpoints present) plus one hub spoke per
 *     course-linked node (the shape `graph_service.get_graph` promises);
 *   - mastery classification — each node's DB `mastery_score` maps through
 *     the canonical thresholds (backend/config.py::get_mastery_tier) to the
 *     class the UI renders: the 2D graph encodes the tier as the node
 *     circle's opacity, and the /tree tier filter partitions nodes by the
 *     same field.
 *
 * DATA assertions only. Force-layout geometry is nondeterministic by nature
 * (#383's test mode seeds the PRNG, but positions stay out of scope) —
 * nothing in this spec reads an x/y.
 *
 * Anchoring (docs/frontend-testids.md, graph surface): everything is keyed
 * on registered testids — `graph-node-item` (the graph's hidden a11y list,
 * mirroring the `nodes` prop 1:1), `graph-node`/`graph-node-circle`/
 * `graph-edge` (the 2D SVG render layer), under the `graph-container` root.
 * Nodes are identified by the `data-node-id` attribute those testids carry,
 * NEVER by display text: `graph_nodes` uniqueness is per course
 * (UNIQUE(user_id, course_id, concept_name)), so two courses can
 * legitimately share a concept name — id-keyed assertions make label
 * collisions structurally irrelevant. Label TEXT is still asserted per node
 * (it is part of the rendered data), just keyed by id.
 *
 * FIXED BUG #355: /api/graph used to duplicate the subject-root hub when a
 * user was enrolled in two offerings of the SAME abstract course
 * (subject-root synthesis iterated enrollments, not distinct courses). The
 * rich seed intentionally has rich-user-active in both the F25 and S26
 * offerings of rich-course-cs101, so the exact-count test below is the
 * regression coverage for it — it used to trip on the duplicated
 * `subject_root__rich-course-cs101` hub (+1 node, +5 spokes) — verified live
 * before the fix: PROBE355 nodes_total=18 nodes_unique=17
 * dup_node_ids=["subject_root__rich-course-cs101"] edges_total=25
 * edges_unique=20 dup_edges=5. `graph_service.get_graph` now dedupes subject
 * roots by distinct abstract `course_id` (backend/services/graph_service.py),
 * so this journey runs as a normal (non-fixme) exact-count test.
 */
import type { Locator, Page } from "@playwright/test";

import { queryRaw } from "./support/db";
import { expect, test } from "./support/fixtures";
import { USER_ACTIVE } from "./support/stack";

type Tier = "mastered" | "learning" | "struggling" | "unexplored";

const TIERS: Tier[] = ["mastered", "learning", "struggling", "unexplored"];

/** Mirror of backend/config.py::get_mastery_tier — the one score→tier map. */
function tierFor(score: number): Tier {
  if (score >= 0.75) return "mastered";
  if (score >= 0.45) return "learning";
  if (score >= 0.1) return "struggling";
  return "unexplored";
}

/**
 * Mirror of KnowledgeGraph2D's `masteryOpacity` — how the 2D graph ENCODES
 * the mastery class on the `graph-node-circle` mark. Kept in lockstep with
 * frontend/src/components/KnowledgeGraph2D.tsx (a redesign that retunes
 * these constants updates this table in the same PR).
 */
const TIER_OPACITY: Record<Tier, number> = {
  mastered: 1,
  learning: 0.78,
  struggling: 0.55,
  unexplored: 0.28,
};

/** /tree tier-filter pill labels — the mastery enum surfaced 1:1 (Tree.tsx TIER_META). */
const TIER_PILL: Record<Tier, string> = {
  mastered: "Mastered",
  learning: "Learning",
  struggling: "Struggling",
  unexplored: "Unexplored",
};

/** SVG label for a concept node (KnowledgeGraph2D truncates names >18 chars). */
const conceptLabel = (name: string) =>
  name.length > 18 ? name.slice(0, 17) + "…" : name;

/** Subject-root hub label (graph_service.get_graph): "CODE - Name". */
const rootLabel = (code: string | null, name: string | null) =>
  code ? `${code} - ${name ?? ""}` : (name ?? "");

/** Synthetic id get_graph gives a course's subject-root hub. */
const rootId = (courseId: string) => `subject_root__${courseId}`;

type NodeRow = {
  id: string;
  concept_name: string;
  course_id: string | null;
  mastery_score: number;
};

type CourseRow = {
  course_id: string;
  course_code: string | null;
  course_name: string | null;
};

/**
 * Read the graph's source of truth over raw SQL and derive what a correct
 * render must show. Runs after the per-test truncate + re-seed, so this is
 * exactly the state the page under test reads.
 */
async function graphExpectations() {
  const nodes = (
    (await queryRaw(
      `SELECT id, concept_name, course_id, mastery_score
         FROM graph_nodes
        WHERE user_id = $1
        ORDER BY concept_name`,
      [USER_ACTIVE],
    )) as NodeRow[]
  ).map((r) => ({ ...r, mastery_score: Number(r.mastery_score) }));

  const edges = (await queryRaw(
    `SELECT source_node_id, target_node_id
       FROM graph_edges
      WHERE user_id = $1`,
    [USER_ACTIVE],
  )) as { source_node_id: string; target_node_id: string }[];

  // DISTINCT abstract courses — a correct graph shows ONE subject-root hub
  // per course, however many offerings of it the user is enrolled in.
  const courses = (await queryRaw(
    `SELECT DISTINCT co.course_id, c.course_code, c.course_name
       FROM enrollments e
       JOIN course_offerings co ON co.id = e.offering_id
       JOIN courses c ON c.id = co.course_id
      WHERE e.user_id = $1`,
    [USER_ACTIVE],
  )) as CourseRow[];

  const nodeIds = new Set(nodes.map((n) => n.id));
  const enrolled = new Set(courses.map((c) => c.course_id));
  // get_graph drops edges whose endpoints are not both among the user's nodes…
  const drawableEdges = edges.filter(
    (e) => nodeIds.has(e.source_node_id) && nodeIds.has(e.target_node_id),
  );
  // …and adds one hub→node spoke for every node of an enrolled course.
  const spokes = nodes.filter((n) => n.course_id && enrolled.has(n.course_id));

  return {
    nodes,
    courses,
    expectedNodeCount: nodes.length + courses.length,
    expectedEdgeCount: drawableEdges.length + spokes.length,
  };
}

/** Registered testid handles under the graph surface (docs/frontend-testids.md). */
function graphLocators(page: Page) {
  const container = page.getByTestId("graph-container");
  return {
    /** 2D SVG node groups — one per rendered node; carry data-node-id. */
    svgNodes: container.getByTestId("graph-node"),
    /** 2D SVG edge lines — one per rendered edge. */
    svgEdges: container.getByTestId("graph-edge"),
    /** A11y list entries — mirror the nodes prop 1:1; carry data-node-id. */
    items: container.getByTestId("graph-node-item"),
  };
}

/** Narrow a graph-node-item / graph-node locator to one node id. */
function byNodeId(loc: Locator, id: string) {
  return loc.and(loc.page().locator(`[data-node-id=${JSON.stringify(id)}]`));
}

// Acceptance test for #355 (now fixed): before the fix, the duplicated CS
// subject root made the UI render one node and five hub spokes more than a
// correct payload would, so this ran as test.fixme. Promoted to a normal
// test now that graph_service.get_graph dedupes subject roots by distinct
// abstract course_id.
test("renders exactly one node per DB graph node plus one subject root per enrolled course, and one edge per DB edge plus one hub spoke per course node", async ({ page }) => {
  const g = await graphExpectations();
  expect(g.nodes.length).toBeGreaterThan(0); // journey guard: seeded graph present

  await page.goto("/tree");
  const { svgNodes, svgEdges, items } = graphLocators(page);

  // Node count, at both render layers: the SVG (one graph-node group per
  // node) and the a11y list (one graph-node-item per entry of the same
  // nodes array).
  await expect(svgNodes).toHaveCount(g.expectedNodeCount);
  await expect(items).toHaveCount(g.expectedNodeCount);

  // Edge count: one graph-edge line per DB edge + per subject spoke.
  await expect(svgEdges).toHaveCount(g.expectedEdgeCount);

  // Each subject-root hub renders exactly once per distinct enrolled course
  // (this is the precise regression coverage for #355: before the fix, this
  // read 2 for CS101 for a user enrolled in two offerings of it).
  for (const c of g.courses) {
    await expect(byNodeId(items, rootId(c.course_id))).toHaveCount(1);
    await expect(byNodeId(svgNodes, rootId(c.course_id))).toHaveCount(1);
  }
});

test("renders every DB concept node exactly once, classified by its DB mastery score", async ({ page }) => {
  const g = await graphExpectations();
  expect(g.nodes.length).toBeGreaterThan(0); // journey guard: seeded graph present

  await page.goto("/tree");
  const { svgNodes, svgEdges, items } = graphLocators(page);

  // Every DB concept node renders exactly once — in the SVG and in the a11y
  // list — and shows its own concept name. Keyed by node id, so this holds
  // even if two courses share a concept name. (Concept rows were never
  // affected by #355 — only the synthesized subject-root hub was — so exact
  // counts hold here; the hub's own exact multiplicity is covered by the
  // dedicated test above.)
  for (const n of g.nodes) {
    const item = byNodeId(items, n.id);
    await expect(item).toHaveCount(1);
    await expect(item).toHaveText(n.concept_name);
    await expect(byNodeId(svgNodes, n.id)).toHaveCount(1);
  }

  // Every enrolled course's subject-root hub is present with its course
  // label (≥1 here; the dedicated test above asserts the exact multiplicity
  // — this test stays a presence check so it doesn't duplicate that
  // coverage).
  for (const c of g.courses) {
    const hub = byNodeId(items, rootId(c.course_id)).first();
    await expect(hub).toBeVisible();
    await expect(hub).toHaveText(rootLabel(c.course_code, c.course_name));
  }

  // Edge floor: at least every DB edge + hub spoke is drawn (exact equality
  // is asserted by the dedicated test above; this stays a floor check so a
  // MISSING edge still fails here even independent of hub-count coverage).
  expect(await svgEdges.count()).toBeGreaterThanOrEqual(g.expectedEdgeCount);

  // Mastery classification at the render layer: the 2D graph encodes the
  // tier as the graph-node-circle's opacity (TIER_OPACITY). Read every node
  // group's id, label and circle opacity in one pass — pure DOM data, no
  // geometry — and key the map by node id (a label-keyed map could silently
  // collapse two same-named nodes into one entry and mask a wrong class).
  const rendered = await svgNodes.evaluateAll((els) =>
    els.map((grp) => ({
      id: grp.getAttribute("data-node-id"),
      label: grp.querySelector(":scope > text")?.textContent ?? "",
      opacity:
        grp
          .querySelector('[data-testid="graph-node-circle"]')
          ?.getAttribute("opacity") ?? null,
    })),
  );
  const byId = new Map(rendered.map((r) => [r.id, r]));

  for (const n of g.nodes) {
    const tier = tierFor(n.mastery_score);
    const got = byId.get(n.id);
    expect(got, `node ${n.id} ("${n.concept_name}") is not in the rendered SVG`).toBeDefined();
    expect(
      got!.label,
      `node ${n.id} SVG label should be its (truncated) concept name`,
    ).toBe(conceptLabel(n.concept_name));
    expect(
      Number(got!.opacity),
      `node ${n.id} ("${n.concept_name}", mastery_score ${n.mastery_score}) must render as "${tier}"`,
    ).toBeCloseTo(TIER_OPACITY[tier], 5);
  }
});

test("tier filter partitions nodes exactly by the DB-derived mastery classification", async ({ page }) => {
  const g = await graphExpectations();

  const byTier = new Map<Tier, NodeRow[]>(TIERS.map((t) => [t, []]));
  for (const n of g.nodes) byTier.get(tierFor(n.mastery_score))!.push(n);
  // Journey guard: the rich seed covers every tier; an empty bucket would
  // make this test vacuous for that class.
  for (const tier of TIERS) {
    expect(byTier.get(tier)!.length, `seed has no "${tier}" node`).toBeGreaterThan(0);
  }

  await page.goto("/tree");
  const { items } = graphLocators(page);

  // Selecting each tier must show exactly the concepts whose DB score maps
  // to that tier — and none of the others. Membership is checked by node id.
  // (Subject-root hubs stay visible by design; concept ids never collide
  // with the synthetic subject_root__* ids.)
  for (const tier of TIERS) {
    await page.getByRole("button", { name: TIER_PILL[tier], exact: true }).click();
    for (const n of g.nodes) {
      await expect(
        byNodeId(items, n.id),
        `tier filter "${tier}": node ${n.id} ("${n.concept_name}", score ${n.mastery_score})`,
      ).toHaveCount(tierFor(n.mastery_score) === tier ? 1 : 0);
    }
  }
});
