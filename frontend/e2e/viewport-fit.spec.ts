/**
 * Journey #341 — shell screens fit their scrollport.
 *
 * Three screens used to size themselves by subtracting a magic constant from
 * `100vh`. That subtraction can only be right for ONE of the two shell
 * layouts: `ShellFrame` renders either a sidebar (its `<main>` is the full
 * `100dvh`) or a horizontal `TopNav` above `<main>` (so `<main>` is
 * `100dvh - 56px`). It is also blind to the density preference, which retunes
 * the padding tokens of the very chrome being subtracted.
 *
 * `<main data-testid="app-shell">` owns `overflow-y: auto` in both layouts,
 * so it — not `<body>` — is the scrollport every assertion here measures
 * against.
 *
 * /tree is the case with a user-visible consequence beyond a stray
 * scrollbar. Its graph row's child is the element a `ResizeObserver` watches,
 * and that `contentRect` is passed straight through as
 * `<KnowledgeGraph width height>`; `graph-container` is styled from exactly
 * those two props, so its box is the honest read of what the canvas believes
 * its size to be. A mis-measured row renders the CANVAS wrong, not just the
 * page around it. Measured on the unfixed build: 480px of canvas in a 664px
 * scrollport, overshooting by 27px under `topnav`.
 *
 * Geometry, deliberately: these are the /tree and /gradebook properties that
 * ARE about layout, which is why they live here and not in graph.spec.ts or
 * gradebook.spec.ts (both declare themselves data-only and read no x/y).
 */
import type { Page } from "@playwright/test";

import { expect, test } from "./support/fixtures";

/** Mirrors LAYOUT_STORAGE_KEY / LayoutPref in frontend/src/lib/useLayoutPref.ts. */
const LAYOUT_KEY = "sapling_layout";
const LAYOUTS = ["sidebar", "topnav"] as const;

/**
 * Sub-pixel slack. Browser layout rounds fractional CSS pixels, so an exact
 * fit can read as ±1px; anything above that is real. The bug this journey
 * covers overshot by tens of pixels.
 */
const SLACK = 1;

/** Switch the client-only layout preference and reload into it. */
async function useLayout(page: Page, layout: (typeof LAYOUTS)[number]) {
  await page.evaluate(
    ([key, value]) => window.localStorage.setItem(key, value),
    [LAYOUT_KEY, layout] as const,
  );
  await page.reload();
}

/** Scrollport-relative geometry of one element, plus the scrollport's own overflow. */
async function measure(page: Page, testId: string) {
  return page.evaluate((id) => {
    const shell = document.querySelector('[data-testid="app-shell"]');
    const el = document.querySelector(`[data-testid="${id}"]`);
    if (!shell || !el) return null;
    const s = shell.getBoundingClientRect();
    const e = el.getBoundingClientRect();
    return {
      // Signed: positive overshoots the scrollport's bottom edge, negative
      // leaves a gap above it. A screen that fills exactly reads 0.
      overshoot: Math.round(e.bottom - s.bottom),
      scrollOverflow: shell.scrollHeight - shell.clientHeight,
      elHeight: Math.round(e.height),
      shellHeight: Math.round(s.height),
    };
  }, testId);
}

/**
 * Read `graph-container` until it stops moving, and hand back the reading
 * that settled. Deliberately not `expect.poll`: the assertions need the
 * settled VALUE, and re-measuring after a poll would reopen the window the
 * poll just closed. Returns the last reading either way, so a timeout still
 * fails on a real number rather than a bare "timed out".
 */
async function settledFit(page: Page, timeoutMs = 5_000) {
  const started = Date.now();
  let last = await measure(page, "graph-container");
  while (last && Math.abs(last.overshoot) > SLACK && Date.now() - started < timeoutMs) {
    await page.waitForTimeout(100);
    last = await measure(page, "graph-container");
  }
  return last;
}

test("the knowledge-graph canvas fills the shell scrollport exactly, in both layouts (#341)", async ({ page }) => {
  await page.goto("/tree");
  await expect(page.getByTestId("graph-container")).toBeVisible();

  for (const layout of LAYOUTS) {
    await useLayout(page, layout);
    await expect(page.getByTestId("graph-container")).toBeVisible();

    // The canvas size is ResizeObserver-driven and starts at a placeholder
    // 900x600 (Tree.tsx's initial state), so wait for the measurement to
    // settle instead of trusting a single frame. This returns the very
    // reading that settled, and every assertion below runs on it —
    // re-measuring afterwards would reopen the window the wait just closed.
    const fit = await settledFit(page);
    expect(fit, "app-shell and graph-container must both be present").not.toBeNull();
    const settled = fit!;
    // Both directions on purpose. Overshoot was the shipped bug; undershoot
    // is what a future regression that breaks `flex: 1` would look like, and
    // a one-sided assertion would wave it through.
    expect(
      settled.overshoot,
      `layout "${layout}": canvas ${settled.elHeight}px vs scrollport ${settled.shellHeight}px — ` +
        `${settled.overshoot > 0 ? "overshoots" : "leaves a gap of"} ${Math.abs(settled.overshoot)}px`,
    ).toBeGreaterThanOrEqual(-SLACK);
    expect(settled.elHeight, `layout "${layout}": the canvas should have a real height`).toBeGreaterThan(0);
    expect(
      settled.scrollOverflow,
      `layout "${layout}": /tree fills the frame, so it should not scroll — scrolls by ${settled.scrollOverflow}px`,
    ).toBeLessThanOrEqual(SLACK);
  }
});

test("the gradebook adds no height beyond what its content needs, in both layouts (#341)", async ({ page }) => {
  await page.goto("/gradebook");
  // Wait for the LOADED grid, not just the chrome. The transcript trigger
  // renders as soon as there is a user, while `loading` still swaps a
  // six-card skeleton in for the real grid — measuring that transient state
  // would make the assertion below depend on fetch timing.
  const grid = page.getByRole("grid", { name: "Courses" });
  await expect(grid).toBeVisible();

  for (const layout of LAYOUTS) {
    await useLayout(page, layout);
    await expect(grid).toBeVisible();

    // Deliberately NOT "the page must not scroll": at topnav the scrollport
    // is 56px shorter, and the seeded gradebook's content genuinely needs
    // more than that — scrolling is the correct answer there. What the fix
    // guarantees is narrower and checkable: the container contributes no
    // height of its OWN beyond what it was given or what its content needs.
    const box = await page.evaluate(() => {
      const shell = document.querySelector('[data-testid="app-shell"]');
      const main = shell?.querySelector("main");
      if (!shell || !main) return null;
      const s = shell.getBoundingClientRect();
      const m = main.getBoundingClientRect();

      // The content's natural height has to be measured from the CHILDREN.
      // `main.scrollHeight` is useless here: it is floored at the element's
      // own client height, so it would grow to match any phantom height and
      // the assertion below could never fail.
      const cs = getComputedStyle(main);
      let bottom = m.top;
      for (const child of Array.from(main.children)) {
        const childStyle = getComputedStyle(child);
        // AmbientOrbs is position:fixed — decorative, and out of flow.
        if (childStyle.position === "fixed" || childStyle.position === "absolute") continue;
        // A trailing margin-bottom adds to the parent's height without
        // appearing in any child's bounding rect, so count it explicitly.
        bottom = Math.max(
          bottom,
          child.getBoundingClientRect().bottom + parseFloat(childStyle.marginBottom || "0"),
        );
      }
      return {
        mainHeight: Math.round(m.height),
        // Space from the screen's <main> down to the scrollport's bottom.
        available: Math.round(s.height - (m.top - s.top)),
        content: Math.round(bottom - m.top + parseFloat(cs.paddingBottom || "0")),
      };
    });
    expect(box, "the gradebook screen should render its own <main>").not.toBeNull();

    const { mainHeight, available, content } = box!;
    const needed = Math.max(available, content);
    // The bug: `minHeight: calc(100vh - var(--row-h))` subtracted a DENSITY
    // token (40/34/48px) as if it were a nav height, so the box was taller
    // than both the space it had AND its content — pure phantom height. On
    // the unfixed build that surfaced as exactly 40px of spurious scroll at
    // the default density, which is `--row-h` to the pixel.
    expect(
      mainHeight,
      `layout "${layout}": <main> is ${mainHeight}px but needs only ${needed}px ` +
        `(${available}px available, ${content}px of content) — ${mainHeight - needed}px is phantom`,
    ).toBeLessThanOrEqual(needed + SLACK);
    // And it must still FILL the space it was given, or `flex-grow` is broken.
    expect(
      mainHeight,
      `layout "${layout}": <main> is ${mainHeight}px and does not fill its ${available}px of space`,
    ).toBeGreaterThanOrEqual(available - SLACK);
  }
});
