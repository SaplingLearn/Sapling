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

/**
 * #344 review #3 — the demo shipped with a single 900×560 viewBox at every
 * width. Playwright's default 1280×720 viewport cannot see the consequence,
 * which is why the journey above passed: at a 390px phone the section's content
 * box is ~332px, so the SVG rendered at a uniform 0.38 scale — 4.6 CSS px
 * concept labels and a 213px-tall smudge, on the device most marketing traffic
 * arrives on. The component now swaps to a phone view below the mobile
 * breakpoint, whose frame is fitted to its content (`-4 -1 364 330`, #344
 * visual 3): 0.91 scale ⇒ 12.8 CSS px labels, 25.5px dots, 301px tall.
 *
 * Asserting in CSS pixels — what a visitor's eye actually gets — rather than on
 * the viewBox attribute, so a different fix that reaches the same legibility
 * still passes.
 */
test('the graph stays legible at a 390px phone viewport (#344)', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');

  const section = page.getByTestId('landing-graph');
  await section.scrollIntoViewIfNeeded();
  await expect(page.getByTestId('landing-graph-node-cs-root')).toBeVisible();

  const metrics = await page.getByTestId('landing-graph-svg').evaluate((el) => {
    const svg = el as unknown as SVGSVGElement;
    const rect = svg.getBoundingClientRect();
    const label = svg.querySelector('text')!;
    // A non-root node — the small dots are what actually got unreadable.
    const dot = svg.querySelector<SVGCircleElement>(
      '[data-testid="landing-graph-node-cs-arrays"] circle',
    )!;
    // The SVG is width:100%, so every user unit renders at this scale.
    const scale = rect.width / svg.viewBox.baseVal.width;
    return {
      heightPx: rect.height,
      labelPx: parseFloat(getComputedStyle(label).fontSize) * scale,
      dotDiameterPx: 2 * dot.r.baseVal.value * scale,
    };
  });

  expect(metrics.labelPx, 'concept labels in CSS px').toBeGreaterThanOrEqual(11);
  expect(metrics.dotDiameterPx, 'non-root node diameter in CSS px').toBeGreaterThanOrEqual(20);
  expect(metrics.heightPx, 'rendered graph height in CSS px').toBeGreaterThan(260);
});

test('the deleted scroll section is gone and the CTA still routes', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('#how-it-works')).toHaveCount(0);
  await expect(page.locator('#features')).toHaveCount(0);
  await expect(page.getByTestId('signin-trigger')).toBeVisible();
});
