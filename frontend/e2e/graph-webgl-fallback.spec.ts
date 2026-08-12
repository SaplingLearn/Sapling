/**
 * Journey #538 — a browser without WebGL lands on the dashboard without
 * crashing, even when the persisted graph mode is "3d".
 *
 * THE BUG: the KnowledgeGraph wrapper honoured localStorage's
 * `sapling.kg.mode = "3d"` unconditionally. three.js r163+ THROWS from the
 * WebGLRenderer constructor when `canvas.getContext("webgl2")` returns null,
 * the throw happens in a mount-time layout effect, and the only error
 * boundary above it was the ROOT one (app/layout.tsx) — so the entire app
 * unmounted into the "We hit a snag" fallback. A profile that toggled 3D on
 * a WebGL-capable browser was permanently locked out of the dashboard the
 * moment WebGL went away (disabled, GPU blocklisted, remote desktop, VM).
 *
 * THE FIX (KnowledgeGraph.tsx): probe webgl2 before honouring the persisted
 * "3d" (ignore it — do NOT rewrite it — when unavailable), disable the mode
 * toggle with an explanatory label, and contain any residual renderer crash
 * in a graph-local error boundary that degrades to the 2D graph.
 *
 * Simulation: an init script nulls the webgl/webgl2/experimental-webgl
 * branches of HTMLCanvasElement.getContext BEFORE any app script runs —
 * exactly the API surface three.js probes — and seeds the poisoned
 * `sapling.kg.mode = "3d"` the way a real profile would carry it. 2D canvas
 * contexts stay real (the AtmosphericBackdrop uses one).
 *
 * Anchoring (docs/frontend-testids.md, graph surface): `graph-container`
 * (wrapper root), `graph-node` (2D SVG render layer — the 3D renderer has no
 * such marks, so their presence proves the 2D path), `graph-mode-toggle`.
 */
import { expect, test } from "./support/fixtures";

const KG_MODE_KEY = "sapling.kg.mode";

test.beforeEach(async ({ page }) => {
  await page.addInitScript(
    ([modeKey]) => {
      const orig = HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.getContext = function (
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
});

test("no-WebGL browser with persisted 3d mode lands on the dashboard and gets the 2D graph", async ({
  page,
}) => {
  await page.goto("/dashboard");

  // The graph slot renders — and it is the 2D SVG layer: `graph-node`
  // groups exist only in KnowledgeGraph2D's render (the 3D renderer paints
  // a WebGL canvas and would have thrown before painting anything).
  const container = page.getByTestId("graph-container");
  await expect(container).toBeVisible();
  await expect(container.getByTestId("graph-node").first()).toBeVisible();

  // The whole point of #538: the app must NOT have collapsed into the root
  // error fallback.
  await expect(page.getByText("We hit a snag")).toHaveCount(0);
  await expect(page.getByText("Error creating WebGL context")).toHaveCount(0);

  // The 3D toggle is disabled and says why.
  const toggle = page.getByTestId("graph-mode-toggle");
  await expect(toggle).toBeDisabled();
  await expect(toggle).toHaveAttribute("title", "3D requires WebGL");

  // The preference is IGNORED, not rewritten: back on a WebGL-capable
  // browser this profile still gets its chosen 3D graph.
  expect(
    await page.evaluate((k) => window.localStorage.getItem(k), KG_MODE_KEY),
  ).toBe("3d");
});
