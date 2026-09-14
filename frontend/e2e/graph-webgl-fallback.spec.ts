/**
 * Journey #538 — WebGL capability and the knowledge-graph mode toggle.
 *
 * THE BUG: the KnowledgeGraph wrapper honoured localStorage's
 * `sapling.kg.mode = "3d"` unconditionally. three.js r163+ THROWS from the
 * WebGLRenderer constructor when `canvas.getContext("webgl2")` returns null,
 * the throw happens in a mount-time layout effect, and the only error
 * boundary above it was the ROOT one (app/layout.tsx) — so the entire app
 * unmounted into the root error fallback. A profile that toggled 3D on a
 * WebGL-capable browser was permanently locked out of the dashboard the
 * moment WebGL went away (disabled, GPU blocklisted, remote desktop, VM).
 *
 * THE FIX (KnowledgeGraph.tsx): the wrapper derives the EFFECTIVE mode from
 * the persisted wish + a WebGL2 capability probe — ignoring (never
 * rewriting) a "3d" wish the browser can't honour — marks the toggle
 * aria-disabled with the reason reachable, and contains residual renderer
 * crashes in a graph-local boundary.
 *
 * Test 1 simulates the no-WebGL browser: an init script nulls the
 * webgl/webgl2/experimental-webgl branches of HTMLCanvasElement.getContext
 * BEFORE any app script runs — exactly the API surface three.js probes —
 * and seeds the poisoned `"3d"` mode the way a real profile would carry it.
 * 2D canvas contexts stay real (the AtmosphericBackdrop uses one).
 *
 * Test 2 pins the POSITIVE path in a real browser: with genuine WebGL2
 * (headless Chromium's SwiftShader), the toggle must stay enabled — a probe
 * regression that false-negatives in real Chromium would otherwise disable
 * the 3D feature for every user with every suite green.
 *
 * Anchoring (docs/frontend-testids.md): `graph-container`, `graph-node`
 * (2D SVG render layer — the 3D renderer has no such marks, so their
 * presence proves the 2D path), `graph-mode-toggle`, `error-fallback`
 * (root crash surface — asserted ABSENT), `graph-crash-fallback` (graph-
 * local crash surface — asserted absent too: capability gating must not
 * even reach the boundary).
 */
import { expect, test } from "./support/fixtures";

// Mirrors GRAPH_MODE_STORAGE_KEY in
// frontend/src/components/graph/KnowledgeGraph.tsx — e2e specs cannot
// import from src/, so keep these in lockstep.
const KG_MODE_KEY = "sapling.kg.mode";

test("no-WebGL browser with persisted 3d mode lands on the dashboard and gets the 2D graph", async ({
  page,
}) => {
  await page.addInitScript(
    ([modeKey]) => {
      const orig = HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.getContext = function (
        this: HTMLCanvasElement,
        kind: string,
        ...rest: unknown[]
      ) {
        if (kind === "webgl" || kind === "webgl2" || kind === "experimental-webgl") {
          return null;
        }
        return (orig as (this: HTMLCanvasElement, k: string, ...a: unknown[]) => unknown).call(
          this,
          kind,
          ...rest,
        );
      } as typeof HTMLCanvasElement.prototype.getContext;
      // The poisoned profile state: 3D chosen back when WebGL worked.
      window.localStorage.setItem(modeKey, "3d");
    },
    [KG_MODE_KEY],
  );

  await page.goto("/dashboard");

  // The graph slot renders — and it is the 2D SVG layer: `graph-node`
  // groups exist only in KnowledgeGraph2D's render (the 3D renderer paints
  // a WebGL canvas and would have thrown before painting anything).
  const container = page.getByTestId("graph-container");
  await expect(container).toBeVisible();
  await expect(container.getByTestId("graph-node").first()).toBeVisible();

  // The whole point of #538: neither the root error surface nor even the
  // graph-local crash surface may appear — the capability gate keeps the
  // crash from ever happening, rather than merely containing it.
  await expect(page.getByTestId("error-fallback")).toHaveCount(0);
  await expect(page.getByTestId("graph-crash-fallback")).toHaveCount(0);

  // The 3D toggle is aria-disabled (still focusable for keyboard/SR users)
  // and says why.
  const toggle = page.getByTestId("graph-mode-toggle");
  await expect(toggle).toHaveAttribute("aria-disabled", "true");
  await expect(toggle).toHaveAttribute("title", "3D requires WebGL");

  // The preference is IGNORED, not rewritten: back on a WebGL-capable
  // browser this profile still gets its chosen 3D graph.
  expect(
    await page.evaluate((k) => window.localStorage.getItem(k), KG_MODE_KEY),
  ).toBe("3d");

  // End-state re-assert: the graph is still standing after everything
  // above — a late async crash (chunk timing) can't slip in after the
  // early negative checks and leave the spec green.
  await expect(container.getByTestId("graph-node").first()).toBeVisible();
  await expect(page.getByTestId("error-fallback")).toHaveCount(0);
});

test("WebGL-capable browser keeps the 3D toggle enabled", async ({ page }) => {
  // No init script: headless Chromium has real WebGL2 via SwiftShader. A
  // capability-probe regression that false-negatives in a real browser
  // would silently disable 3D for every user — this is the only
  // real-browser assertion of the positive path.
  await page.goto("/dashboard");

  const toggle = page.getByTestId("graph-mode-toggle");
  await expect(toggle).toBeVisible();
  await expect(toggle).not.toHaveAttribute("aria-disabled", "true");
  await expect(toggle).toHaveAttribute("title", "Switch to 3D graph");
});
