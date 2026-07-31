/**
 * Journey #341 — the knowledge-graph canvas fits its scrollport.
 *
 * /tree sized its graph row with `height: calc(100vh - 240px)` — a magic
 * constant standing in for "the chrome above me". That constant can only be
 * right for ONE of the two shell layouts: `ShellFrame` renders either a
 * sidebar (its `<main>` is the full `100dvh`) or a horizontal `TopNav` above
 * `<main>` (so `<main>` is `100dvh - 56px`). The subtraction is also blind to
 * the density preference, which retunes the TopBar/filter-row padding tokens.
 *
 * This is not a cosmetic overflow: the row's child is the element a
 * `ResizeObserver` watches (Tree.tsx), and its `contentRect` is passed
 * straight through as `<KnowledgeGraph width height>` — so a row that
 * mis-measures the available space renders the graph CANVAS ITSELF at the
 * wrong size. `graph-container` (KnowledgeGraph.tsx) is styled from exactly
 * those two props, which makes its box the honest read of what the canvas
 * believes its size to be.
 *
 * The invariant, layout- and density-agnostic: on /tree the canvas must fit
 * inside the shell scrollport (`app-shell`, the `<main>` that owns
 * `overflow-y: auto` in both layouts) — it may fill it, never overshoot it.
 *
 * Geometry, deliberately: this is the one /tree property that IS about
 * layout, which is why it lives here and not in graph.spec.ts (that spec
 * declares itself data-only and reads no x/y by design).
 */
import { expect, test } from "./support/fixtures";
import { FRONTEND_URL } from "./support/stack";

/** Mirrors LAYOUT_STORAGE_KEY / LayoutPref in frontend/src/lib/useLayoutPref.ts. */
const LAYOUT_KEY = "sapling_layout";
const LAYOUTS = ["sidebar", "topnav"] as const;

/**
 * Sub-pixel slack. Browser layout rounds fractional CSS pixels, so an exact
 * fit can read as ±1px; anything above that is real overflow (the bug this
 * journey covers overshot by tens of pixels).
 */
const SLACK = 1;

test("the knowledge-graph canvas fits the shell scrollport in both layouts (#341)", async ({ page }) => {
  await page.goto(`${FRONTEND_URL}/tree`);
  await expect(page.getByTestId("graph-container")).toBeVisible();

  for (const layout of LAYOUTS) {
    // The layout preference is client-only (localStorage + a reload), so this
    // exercises BOTH ShellFrame branches against the same seeded graph.
    await page.evaluate(
      ([key, value]) => window.localStorage.setItem(key, value),
      [LAYOUT_KEY, layout] as const,
    );
    await page.reload();
    await expect(page.getByTestId("graph-container")).toBeVisible();

    const fit = await page.evaluate(() => {
      const shell = document.querySelector('[data-testid="app-shell"]');
      const canvas = document.querySelector('[data-testid="graph-container"]');
      if (!shell || !canvas) return null;
      const s = shell.getBoundingClientRect();
      const c = canvas.getBoundingClientRect();
      return {
        // How far the canvas's bottom edge falls past the scrollport's.
        overshoot: Math.round(c.bottom - s.bottom),
        // Whether the scrollport scrolls at all — /tree is a fill-the-frame
        // screen, so any scrollable overflow means something is oversized.
        scrollOverflow: shell.scrollHeight - shell.clientHeight,
        canvasHeight: Math.round(c.height),
        shellHeight: Math.round(s.height),
      };
    });

    expect(fit, "app-shell and graph-container must both be present").not.toBeNull();
    expect(
      fit!.canvasHeight,
      `layout "${layout}": the canvas should have a real height`,
    ).toBeGreaterThan(0);
    expect(
      fit!.overshoot,
      `layout "${layout}": the graph canvas (${fit!.canvasHeight}px) overshoots the ` +
        `shell scrollport (${fit!.shellHeight}px) by ${fit!.overshoot}px`,
    ).toBeLessThanOrEqual(SLACK);
    expect(
      fit!.scrollOverflow,
      `layout "${layout}": /tree should fill the scrollport exactly, but it ` +
        `scrolls by ${fit!.scrollOverflow}px`,
    ).toBeLessThanOrEqual(SLACK);
  }
});
