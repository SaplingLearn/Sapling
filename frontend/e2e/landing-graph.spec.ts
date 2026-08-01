/**
 * Journey — the landing page's interactive knowledge graph (#344).
 *
 * The graph is the page's whole argument, so this pins that it renders, that
 * picking a course swaps it, and that engaging with it recedes the
 * instructional copy. Test mode (NEXT_PUBLIC_TEST_MODE=1, baked into the
 * Playwright profile build) parks the helical assembly animation, so every
 * assertion below runs against the fully laid-out frame — no waiting on
 * requestAnimationFrame.
 *
 * Selectors: testids from the component
 * (src/components/marketing/graph/KnowledgeGraphDemo.tsx) — `landing-graph`
 * for the section, `landing-graph-chip-<courseId>` for the course picker,
 * `landing-graph-node-<nodeId>` for graph nodes, `landing-graph-copy` for the
 * instructional heading block, `landing-graph-blurb` for the hover blurb.
 * Course/node ids and the `ma-vectors` blurb text are seeded fixture data
 * (src/components/marketing/graph/courseGraphs.ts) — `cs210` is the default
 * (first) course, `ma242` the second. `AssemblingGraph` is keyed by
 * `graph.id`, so switching courses remounts it and the previous course's
 * node elements leave the DOM entirely — asserted below via `toHaveCount(0)`
 * rather than a visibility check.
 */
import { expect, test } from './support/fixtures';

test('landing graph renders, swaps by course, and fades its copy on engagement', async ({ page }) => {
  await page.goto('/');

  const section = page.getByTestId('landing-graph');
  await section.scrollIntoViewIfNeeded();
  await expect(section).toBeVisible();

  // Parked frame: the first course's root node is laid out and visible.
  await expect(page.getByTestId('landing-graph-node-cs-root')).toBeVisible();

  // Picking another course swaps the graph.
  await page.getByTestId('landing-graph-chip-ma242').click();
  await expect(page.getByTestId('landing-graph-node-ma-root')).toBeVisible();
  await expect(page.getByTestId('landing-graph-node-cs-root')).toHaveCount(0);

  // Engaging recedes the copy.
  const copy = page.getByTestId('landing-graph-copy');
  await expect(copy).toHaveAttribute('data-engaged', 'false');
  await page.getByTestId('landing-graph-node-ma-vectors').hover();
  await expect(copy).toHaveAttribute('data-engaged', 'true');
  await expect(page.getByTestId('landing-graph-blurb')).toContainText('Span, basis');
});

test('the deleted scroll section is gone and the CTA still routes', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('#how-it-works')).toHaveCount(0);
  await expect(page.locator('#features')).toHaveCount(0);
  await expect(page.getByTestId('signin-trigger')).toBeVisible();
});
