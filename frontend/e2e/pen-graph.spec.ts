/**
 * Pen graph regression: the approved botanical renderer still shows the
 * student's real graph. No demo courses, concepts, links or learning events
 * are substituted for the database. Exact source-path/geometry integrity is
 * covered by penGraph.test.ts; these journeys exercise its live integration.
 */
import type { Locator, Page, Request } from "@playwright/test";

import { queryRaw } from "./support/db";
import { expect, test } from "./support/fixtures";
import { USER_ACTIVE } from "./support/stack";

type NodeRow = {
  id: string;
  concept_name: string;
  course_id: string | null;
  mastery_score: number;
  times_studied: number;
};

type CourseRow = { course_id: string; course_code: string | null };
type EdgeRow = { source_node_id: string; target_node_id: string };

// Approved JSs7K / Figma 3457:3774 source fills: fully opaque marks, never
// course colours or an opacity approximation of a mastery state.
const PALETTE = {
  mastered: "#a3b06d",
  learning: "#fcc98a",
  struggling: "#ef908f",
  unexplored: "#decdc1",
  hub: "#6c462f",
};

function colourFor(score: number): string {
  if (score >= 0.95) return PALETTE.mastered;
  if (score >= 0.3) return PALETTE.learning;
  if (score >= 0.1) return PALETTE.struggling;
  return PALETTE.unexplored;
}

async function sourceGraph() {
  const nodes = (await queryRaw(
    `SELECT id, concept_name, course_id, mastery_score, times_studied
       FROM graph_nodes WHERE user_id = $1 ORDER BY id`,
    [USER_ACTIVE],
  )) as NodeRow[];
  const courses = (await queryRaw(
    `SELECT DISTINCT co.course_id, c.course_code
       FROM enrollments e JOIN course_offerings co ON co.id = e.offering_id
       JOIN courses c ON c.id = co.course_id WHERE e.user_id = $1`,
    [USER_ACTIVE],
  )) as CourseRow[];
  const edges = (await queryRaw(
    `SELECT source_node_id, target_node_id FROM graph_edges WHERE user_id = $1`,
    [USER_ACTIVE],
  )) as EdgeRow[];
  const ids = new Set(nodes.map((n) => n.id));
  const enrolled = new Set(courses.map((c) => c.course_id));
  return {
    nodes,
    courses,
    nodeCount: nodes.length + courses.length,
    edgeCount: edges.filter((e) => ids.has(e.source_node_id) && ids.has(e.target_node_id)).length +
      nodes.filter((n) => n.course_id && enrolled.has(n.course_id)).length,
    edges,
  };
}

/** Snapshot the actual learner records, including the saved goal/plan in
 * sessions. Selection, filtering and graph navigation are read-only. */
async function learningState() {
  return queryRaw(
    `SELECT
       (SELECT jsonb_agg(to_jsonb(n) ORDER BY n.id) FROM graph_nodes n WHERE n.user_id = $1) AS nodes,
       (SELECT jsonb_agg(to_jsonb(e) ORDER BY e.id) FROM node_mastery_events e
         JOIN graph_nodes n ON n.id = e.node_id WHERE n.user_id = $1) AS mastery_events,
       (SELECT jsonb_agg(to_jsonb(s) ORDER BY s.id) FROM sessions s WHERE s.user_id = $1) AS sessions`,
    [USER_ACTIVE],
  );
}

function trackLearningMutations(page: Page) {
  const mutations: string[] = [];
  page.on("request", (r: Request) => {
    const path = new URL(r.url()).pathname;
    if (!["GET", "HEAD", "OPTIONS"].includes(r.method()) &&
      /^\/api\/(learn|graph|quiz|notes|documents)\b/.test(path)) {
      mutations.push(`${r.method()} ${path}`);
    }
  });
  return mutations;
}

const nodeById = (scope: Locator, id: string) =>
  scope.locator(`[data-testid="graph-node"][data-node-id=${JSON.stringify(id)}]`);

/** Authored paint paths deliberately ignore pointer events; the node's
 * transparent hit target owns capture. Click the visible mark's actual
 * center with a real device input, rather than targeting an inert path. */
async function pointAtNode(page: Page, node: Locator, touch = false) {
  const mark = node.getByTestId("graph-node-circle");
  const box = await mark.boundingBox();
  expect(box, "the real node mark has painted bounds").not.toBeNull();
  const x = box!.x + box!.width / 2;
  const y = box!.y + box!.height / 2;
  if (touch) await page.touchscreen.tap(x, y);
  else await page.mouse.click(x, y);
}

async function dashboard(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("sapling.kg.mode", "2d");
    localStorage.setItem("sapling_disclaimer_ack", "true");
    localStorage.setItem("sapling_last_session_feedback", String(Date.now()));
    localStorage.setItem("sapling_last_feedback", String(Date.now()));
  });
  await page.goto("/dashboard");
  const main = page.getByTestId("app-shell");
  await expect(main.getByTestId("dashboard-next")).not.toHaveAttribute("data-state", "pending", { timeout: 30_000 });
  await expect(main.locator('svg[data-renderer="pen"]')).toBeVisible();
  return main;
}

/** The wrapper owns its aspect ratio; an in-flow, explicit-height SVG must
 * never make that wrapper retain its previous desktop height after resize. */
async function expectFittedCanvas(canvas: Locator) {
  await expect(canvas).toBeVisible();
  await expect.poll(async () => {
    const box = await canvas.boundingBox();
    return box ? Math.abs(box.height - box.width * 601 / 893) : Infinity;
  }, { message: "map canvas keeps the authored 893:601 ratio within one CSS pixel" }).toBeLessThanOrEqual(1);
  await expect.poll(async () => {
    const box = await canvas.boundingBox();
    const svg = await canvas.locator('svg[data-renderer="pen"]').boundingBox();
    return box && svg ? Math.max(Math.abs(svg.width - box.width), Math.abs(svg.height - box.height)) : Infinity;
  }, { message: "ResizeObserver fits the rendered SVG to the current canvas box" }).toBeLessThanOrEqual(1);
}

async function expectPhoneLegend(main: Locator) {
  const legend = main.getByTestId("graph-legend");
  await expect(legend).toHaveCSS("display", "grid");
  await expect.poll(() => legend.evaluate((el) => getComputedStyle(el).gridTemplateColumns.trim().split(/\s+/).length),
    { message: "phone legend has two computed grid columns" }).toBe(2);
  const entries = legend.locator(":scope > li");
  const boxes = await Promise.all([0, 1, 2, 3].map((index) => entries.nth(index).boundingBox()));
  expect(boxes.every(Boolean), "all four semantic legend entries have bounds").toBe(true);
  expect(Math.abs(boxes[0]!.y - boxes[1]!.y), "first legend row").toBeLessThanOrEqual(1);
  expect(Math.abs(boxes[2]!.y - boxes[3]!.y), "second legend row").toBeLessThanOrEqual(1);
  expect(Math.abs(boxes[0]!.x - boxes[2]!.x), "aligned legend columns").toBeLessThanOrEqual(1);
  expect(boxes[2]!.y).toBeGreaterThan(boxes[0]!.y);
}

test("approved Pen marks retain every live concept, hub, edge and mastery colour", async ({ page }) => {
  const g = await sourceGraph();
  expect(g.nodes.length).toBeGreaterThan(0);
  const main = await dashboard(page);
  const graph = main.getByTestId("graph-container");
  await expect(graph.getByTestId("graph-node")).toHaveCount(g.nodeCount);
  await expect(graph.getByTestId("graph-node-item")).toHaveCount(g.nodeCount);
  await expect(graph.getByTestId("graph-edge")).toHaveCount(g.edgeCount);
  await expect(main.getByTestId("dashboard-map-counts")).toHaveText(`${g.nodes.length} concepts · ${g.courses.length} courses`);

  for (const n of g.nodes) {
    const mark = nodeById(graph, n.id).getByTestId("graph-node-circle");
    await expect(mark).toHaveCount(1);
    expect(await mark.evaluate((el) => el.tagName.toLowerCase())).toBe("path");
    expect((await mark.getAttribute("fill"))?.toLowerCase()).toBe(colourFor(Number(n.mastery_score)));
    await expect(mark).toHaveAttribute("opacity", "1");
    await expect(graph.locator(`[data-testid="graph-node-item"][data-node-id=${JSON.stringify(n.id)}]`)).toHaveText(n.concept_name);
  }
  for (const c of g.courses) {
    const hub = nodeById(graph, `subject_root__${c.course_id}`);
    await expect(hub).toHaveCount(1);
    expect((await hub.getByTestId("graph-node-circle").getAttribute("fill"))?.toLowerCase()).toBe(PALETTE.hub);
  }
  await expect(page.getByTestId("graph-crash-fallback")).toHaveCount(0);
});

test("course filtering and keyboard topic selection preserve learner knowledge, goal and plan", async ({ page }) => {
  const g = await sourceGraph();
  const selected = g.nodes.find((n) => n.course_id)!;
  expect(selected, "rich seed needs a real course-linked concept").toBeTruthy();
  const before = await learningState();
  const mutations = trackLearningMutations(page);
  const main = await dashboard(page);
  const filter = main.getByTestId("dashboard-course-filter");
  await filter.selectOption(selected.course_id!);
  const own = g.nodes.filter((n) => n.course_id === selected.course_id);
  const ownIds = new Set(own.map((n) => n.id));
  const ownEdges = g.edges.filter((e) => ownIds.has(e.source_node_id) && ownIds.has(e.target_node_id)).length + own.length;
  const graph = main.getByTestId("graph-container");
  await expect(graph.getByTestId("graph-node")).toHaveCount(own.length + 1);
  await expect(graph.getByTestId("graph-edge")).toHaveCount(ownEdges);

  // A real pointer click must activate the node after pointer capture. A
  // synthetic fireEvent.click would miss capture retargeting click to SVG.
  const node = nodeById(graph, selected.id);
  await pointAtNode(page, node);
  const detail = main.getByTestId("dashboard-concept");
  await expect(detail).toHaveAttribute("data-node-id", selected.id);
  await detail.getByTestId("dashboard-concept-back").click();
  await expect(detail).toHaveCount(0);

  // Direct SVG keyboard activation uses the same real id as View topics.
  await node.focus();
  await page.keyboard.press("Enter");
  await expect(detail).toHaveAttribute("data-node-id", selected.id);
  await expect(detail.getByRole("heading", { level: 2 })).toHaveText(selected.concept_name);
  const evidence = detail.getByTestId("dashboard-concept-evidence");
  if (Number(selected.times_studied) > 0) {
    await expect(evidence).toContainText(`${selected.times_studied} recorded`);
  } else {
    await expect(evidence).toContainText("No answers recorded yet");
    await expect(evidence).toContainText("a starting estimate, not evidence of what you know");
  }
  await expect(node).toHaveAttribute("data-selected", "true");
  await expect(node.getByTestId("graph-node-selected-ring")).toHaveCount(1);

  await detail.getByTestId("dashboard-concept-back").click();
  await expect(main.getByTestId("dashboard-next")).toBeVisible();
  await expect(graph.locator('[data-testid="graph-node"][data-selected="true"]')).toHaveCount(0);
  await filter.selectOption("all");
  await expect(graph.getByTestId("graph-node")).toHaveCount(g.nodeCount);
  expect(mutations).toEqual([]);
  expect(await learningState()).toEqual(before);
});

test("full map keeps deliberate zoom, reset, keyboard selection and Escape focus return", async ({ page }) => {
  const g = await sourceGraph();
  const before = await learningState();
  const mutations = trackLearningMutations(page);
  const main = await dashboard(page);
  const opener = main.getByTestId("dashboard-open-map");
  await opener.focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByTestId("dashboard-full-map");
  await expect(dialog).toBeVisible();
  await expect(page.getByTestId("graph-container")).toHaveCount(1);
  await expect(dialog.locator('svg[data-renderer="pen"]')).toBeVisible();
  const transform = dialog.getByTestId("graph-transform");
  const initial = await transform.getAttribute("transform");
  await dialog.getByTestId("graph-zoom-in").click();
  await expect(transform).not.toHaveAttribute("transform", initial!);
  await dialog.getByTestId("graph-zoom-reset").click();
  await expect(transform).toHaveAttribute("transform", initial!);

  const selected = g.nodes[0];
  const node = nodeById(dialog, selected.id);
  const positionBeforeDrag = await node.getAttribute("transform");
  const dragBounds = await node.getByTestId("graph-node-circle").boundingBox();
  expect(dragBounds).not.toBeNull();
  const point = { x: dragBounds!.x + dragBounds!.width / 2, y: dragBounds!.y + dragBounds!.height / 2 };
  await page.mouse.move(point.x, point.y);
  await page.mouse.down();
  await page.mouse.move(point.x + 24, point.y + 18, { steps: 5 });
  await page.mouse.up();
  await expect(node).not.toHaveAttribute("transform", positionBeforeDrag!);
  await expect(dialog.getByTestId("dashboard-full-map-concept")).toHaveCount(0);
  await expect(dialog.getByTestId("graph-edge")).toHaveCount(g.edgeCount);
  await dialog.getByTestId("graph-zoom-reset").click();
  await expect(node).toHaveAttribute("transform", positionBeforeDrag!);
  await node.focus();
  await page.keyboard.press("Space");
  await expect(dialog.getByTestId("dashboard-full-map-concept")).toHaveAttribute("data-node-id", selected.id);
  await expect(node).toHaveAttribute("data-selected", "true");
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(opener).toBeFocused();
  await expect(main.locator('svg[data-renderer="pen"]')).toBeVisible();
  expect(mutations).toEqual([]);
  expect(await learningState()).toEqual(before);
});

test("resizing desktop to both phones and back refits the map without losing live nodes or controls", async ({ page }) => {
  const g = await sourceGraph();
  const before = await learningState();
  const mutations = trackLearningMutations(page);
  await page.setViewportSize({ width: 1440, height: 1000 });
  const main = await dashboard(page);
  const expectedIds = [...g.nodes.map((n) => n.id), ...g.courses.map((c) => `subject_root__${c.course_id}`)].sort();

  for (const width of [1440, 390, 320, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    const phone = width < 768;
    const canvas = main.getByTestId(phone ? "dashboard-map-preview" : "dashboard-map-canvas");
    await expectFittedCanvas(canvas);
    const graph = canvas.getByTestId("graph-container");
    await expect(main.getByTestId("graph-container")).toHaveCount(1);
    await expect(graph.getByTestId("graph-node")).toHaveCount(g.nodeCount);
    await expect(graph.getByTestId("graph-edge")).toHaveCount(g.edgeCount);
    expect(await graph.getByTestId("graph-node").evaluateAll((els) => els.map((el) => el.getAttribute("data-node-id")).sort())).toEqual(expectedIds);
    await expect(graph.getByTestId("graph-zoom-in")).toHaveCount(phone ? 0 : 1);
    await expect(graph.getByTestId("graph-zoom-out")).toHaveCount(phone ? 0 : 1);
    if (phone) {
      await expectPhoneLegend(main);
      await expect(canvas.locator('svg[data-renderer="pen"]')).toHaveCSS("touch-action", "pan-y");
    } else {
      await expect(graph.getByTestId("graph-zoom-in")).toBeVisible();
      await expect(graph.getByTestId("graph-zoom-out")).toBeVisible();
    }
    expect(await main.evaluate((el) => el.scrollWidth - el.clientWidth), `${width}px shell has no horizontal overflow`).toBeLessThanOrEqual(1);
  }
  expect(mutations).toEqual([]);
  expect(await learningState()).toEqual(before);
});

for (const width of [390, 320]) {
  test.describe(`Pen graph phone ${width}`, () => {
  test.use({ viewport: { width, height: 740 }, hasTouch: true });
  test(`phone ${width}: Pen preview scrolls, topics retain identity and full map stays usable`, async ({ page }) => {
    const g = await sourceGraph();
    const before = await learningState();
    const mutations = trackLearningMutations(page);
    const main = await dashboard(page);
    const preview = main.getByTestId("dashboard-map-preview");
    await expectFittedCanvas(preview);
    await expectPhoneLegend(main);
    await expect(preview.locator('svg[data-renderer="pen"]')).toHaveCSS("touch-action", "pan-y");
    await expect(preview.getByTestId("graph-node")).toHaveCount(g.nodeCount);
    await expect(preview.getByTestId("graph-zoom-in")).toHaveCount(0);
    await preview.scrollIntoViewIfNeeded();
    const scrollBefore = await main.evaluate((el) => el.scrollTop);
    await preview.hover();
    await page.mouse.wheel(0, 200);
    await expect.poll(() => main.evaluate((el) => el.scrollTop)).toBeGreaterThan(scrollBefore);
    expect(await main.evaluate((el) => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(1);

    const topics = main.getByTestId("dashboard-view-topics");
    await topics.click();
    const list = page.getByTestId("dashboard-topics");
    await expect(list).toBeVisible();
    const selected = g.nodes[0];
    await list.getByTestId(`dashboard-topic-${selected.id}`).click();
    const sheet = page.getByTestId("dashboard-concept-sheet");
    await expect(sheet.getByTestId("dashboard-sheet-concept")).toHaveAttribute("data-node-id", selected.id);
    await expect(sheet.getByTestId("dashboard-sheet-concept-evidence")).toBeVisible();
    await expect(sheet.getByTestId("dashboard-concept-sheet-close")).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(sheet).toHaveCount(0);
    await expect(topics).toBeFocused();

    const opener = main.getByTestId("dashboard-open-map");
    await opener.click();
    const full = page.getByTestId("dashboard-full-map");
    await expect(full).toBeVisible();
    await expect(full.locator('svg[data-renderer="pen"]')).toHaveCSS("touch-action", "none");
    await expect(page.getByTestId("graph-container")).toHaveCount(1);
    await expect(full.getByTestId("graph-node")).toHaveCount(g.nodeCount);
    await expect(full.getByTestId("graph-edge")).toHaveCount(g.edgeCount);
    // Preview taps intentionally do nothing; full-map taps inspect the real
    // learner node through the touch/pointer-capture path.
    await pointAtNode(page, nodeById(full, selected.id), true);
    await expect(full.getByTestId("dashboard-full-map-concept")).toHaveAttribute("data-node-id", selected.id);
    await full.getByTestId("graph-zoom-in").click();
    await full.getByTestId("graph-zoom-reset").click();
    await page.keyboard.press("Escape");
    await expect(full).toHaveCount(0);
    await expect(opener).toBeFocused();
    expect(mutations).toEqual([]);
    expect(await learningState()).toEqual(before);
  });
  });
}
