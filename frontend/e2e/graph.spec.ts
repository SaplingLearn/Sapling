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
 * How the UI is counted (per #395: "choose something robust and justify
 * it"): the 2D graph draws into the single `<svg aria-label="Knowledge
 * graph">` inside the registered `graph-container` testid
 * (docs/frontend-testids.md registers the graph surface on the wrapper only,
 * not the 2D/3D internals). Inside it every node renders exactly one <text>
 * label and every edge exactly one <line>, and the component mirrors its
 * `nodes` prop 1:1 into a visually-hidden accessibility list
 * (`<ul aria-label="Knowledge graph nodes">`). Counting those is counting
 * the rendered data layer — structural/ARIA handles under the testid root,
 * no CSS-class or copy anchoring, no geometry. Node identity is matched by
 * concept name, which is seeded DB data, not UI copy.
 *
 * KNOWN BUG #355: /api/graph duplicates the subject-root hub when a user is
 * enrolled in two offerings of the SAME abstract course (subject-root
 * synthesis iterates enrollments, not distinct courses). The rich seed
 * intentionally has rich-user-active in both the F25 and S26 offerings of
 * rich-course-cs101, so the exact-count test below trips on the duplicated
 * `subject_root__rich-course-cs101` hub (+1 node, +5 spokes). That is this
 * journey catching precisely the defect class it exists for — the correct
 * assertion is kept and the test is marked fixme(#355) rather than relaxed.
 * The companion tests assert everything #355 does not corrupt.
 */
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
 * the mastery class on the rendered node circle. Kept in lockstep with
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

/** Whole-string matcher for Locator.filter({ hasText }) — no substring hits. */
const exactText = (s: string) =>
  new RegExp(`^${s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`);

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

/** Locators under the registered graph surface (docs/frontend-testids.md). */
function graphLocators(page: import("@playwright/test").Page) {
  const container = page.getByTestId("graph-container");
  const svg = container.locator('svg[aria-label="Knowledge graph"]');
  return {
    svg,
    labels: svg.locator("text"), // exactly one per rendered node
    lines: svg.locator("line"), // exactly one per rendered edge
    srItems: container.locator('ul[aria-label="Knowledge graph nodes"] > li'), // 1:1 with the nodes prop
  };
}

// Marked fixme, NOT relaxed: red today solely because of open bug #355 (see
// header). The duplicated CS subject root makes the UI render one node and
// five hub spokes more than a correct payload would. Un-fixme when #355
// lands — the assertions below are the acceptance test for it.
test.fixme("renders exactly one node per DB graph node plus one subject root per enrolled course, and one edge per DB edge plus one hub spoke per course node", async ({ page }) => {
  const g = await graphExpectations();
  expect(g.nodes.length).toBeGreaterThan(0); // journey guard: seeded graph present

  await page.goto("/tree");
  const { labels, lines, srItems } = graphLocators(page);

  // Node count, at both render layers: the SVG (one <text> per node) and the
  // accessibility list (one <li> per entry of the same nodes array).
  await expect(labels).toHaveCount(g.expectedNodeCount);
  await expect(srItems).toHaveCount(g.expectedNodeCount);

  // Edge count: one <line> per DB edge + per subject spoke.
  await expect(lines).toHaveCount(g.expectedEdgeCount);

  // Each subject-root hub renders exactly once per distinct enrolled course
  // (the precise duplication #355 causes: this reads 2 for CS101 today).
  for (const c of g.courses) {
    await expect(
      labels.filter({ hasText: exactText(rootLabel(c.course_code, c.course_name)) }),
    ).toHaveCount(1);
  }
});

test("renders every DB concept node exactly once, classified by its DB mastery score", async ({ page }) => {
  const g = await graphExpectations();
  expect(g.nodes.length).toBeGreaterThan(0); // journey guard: seeded graph present

  await page.goto("/tree");
  const { svg, labels, lines, srItems } = graphLocators(page);

  // Every DB concept node renders exactly once — in the SVG and in the
  // accessibility list. (Concept rows are what #355 does NOT duplicate, so
  // exact counts hold here; hub multiplicity lives in the fixme test above.)
  for (const n of g.nodes) {
    await expect(
      labels.filter({ hasText: exactText(conceptLabel(n.concept_name)) }),
    ).toHaveCount(1);
    await expect(
      srItems.filter({ hasText: exactText(n.concept_name) }),
    ).toHaveCount(1);
  }

  // Every enrolled course's subject-root hub is present (≥1 — exact
  // multiplicity is the #355-blocked assertion above).
  for (const c of g.courses) {
    await expect(
      labels.filter({ hasText: exactText(rootLabel(c.course_code, c.course_name)) }).first(),
    ).toBeVisible();
  }

  // Edge floor: at least every DB edge + hub spoke is drawn (exact equality
  // is #355-blocked — the duplicate hub adds surplus spokes, but a MISSING
  // edge must still fail here).
  expect(await lines.count()).toBeGreaterThanOrEqual(g.expectedEdgeCount);

  // Mastery classification at the render layer: the 2D graph encodes the
  // tier as the main circle's opacity (TIER_OPACITY). Read every node
  // group's label + main-circle opacity in one pass — pure DOM data, no
  // geometry. A node group is the only <g> with a direct <text> child; its
  // main circle is the LAST direct <circle> (glow/highlight rings precede
  // it in source order).
  const rendered = await svg.evaluate((el) =>
    Array.from(el.querySelectorAll("g"))
      .filter((grp) => grp.querySelector(":scope > text"))
      .map((grp) => {
        const circles = grp.querySelectorAll(":scope > circle");
        const main = circles[circles.length - 1];
        return {
          label: grp.querySelector(":scope > text")?.textContent ?? "",
          opacity: main?.getAttribute("opacity") ?? null,
        };
      }),
  );
  const opacityByLabel = new Map(rendered.map((r) => [r.label, r.opacity]));

  for (const n of g.nodes) {
    const tier = tierFor(n.mastery_score);
    const got = opacityByLabel.get(conceptLabel(n.concept_name));
    expect(
      got,
      `node "${n.concept_name}" (mastery_score ${n.mastery_score} → ${tier}) has no rendered opacity`,
    ).not.toBeNull();
    expect(
      Number(got),
      `node "${n.concept_name}" (mastery_score ${n.mastery_score}) must render as "${tier}"`,
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
  const { labels } = graphLocators(page);

  // Selecting each tier must show exactly the concepts whose DB score maps
  // to that tier — and none of the others. (Subject-root hubs stay visible
  // by design; concept-name matching skips them.)
  for (const tier of TIERS) {
    await page.getByRole("button", { name: TIER_PILL[tier], exact: true }).click();
    for (const n of g.nodes) {
      await expect(
        labels.filter({ hasText: exactText(conceptLabel(n.concept_name)) }),
        `tier filter "${tier}": node "${n.concept_name}" (score ${n.mastery_score})`,
      ).toHaveCount(tierFor(n.mastery_score) === tier ? 1 : 0);
    }
  }
});
