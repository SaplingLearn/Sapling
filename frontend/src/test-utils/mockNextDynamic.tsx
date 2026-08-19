/**
 * Shared `next/dynamic` passthrough mock for vitest (jsdom) component tests.
 *
 * `dynamic(loader)` is called at MODULE EVALUATION of the component under
 * test, and vitest's hoisted `vi.mock` modules resolve as already-fulfilled
 * promises — so the `.then` below settles on the microtask queue long before
 * any test's first `render()`. By first paint, `Resolved` is populated and
 * the wrapper renders it; the `null` branch only covers the (unobserved in
 * practice) pre-resolution window.
 *
 * The resolved component is rendered via `createElement`, NEVER invoked as a
 * plain function — mock components are real components and may use hooks;
 * a direct `C(props)` call would splice their hooks into the CALLER's hook
 * order and corrupt both.
 *
 * Usage (the factory must be async so the helper can be imported inside the
 * hoisted mock):
 *
 *   vi.mock("next/dynamic", async () =>
 *     (await import("@/test-utils/mockNextDynamic")).mockNextDynamicModule(),
 *   );
 */
import React from "react";

type AnyProps = Record<string, unknown>;
type LoadedModule =
  | { default?: React.ComponentType<AnyProps> }
  | React.ComponentType<AnyProps>;

export function mockNextDynamicModule() {
  return {
    default: (loader: () => Promise<LoadedModule>) => {
      let Resolved: React.ComponentType<AnyProps> | null = null;
      const pending = Promise.resolve(loader()).then((mod) => {
        Resolved =
          typeof mod === "function" ? mod : (mod.default ?? null);
      });
      function DynamicPassthrough(props: AnyProps) {
        // Loaders that target a real (non-vi.mocked) module can resolve
        // after first paint — re-render once resolution lands (the
        // AdminAnalytics chart passthrough needed exactly this).
        const [, force] = React.useReducer((n: number) => n + 1, 0);
        React.useEffect(() => {
          let live = true;
          if (!Resolved) void pending.then(() => live && force());
          return () => {
            live = false;
          };
        }, []);
        const C = Resolved;
        return C ? React.createElement(C, props) : null;
      }
      return DynamicPassthrough;
    },
  };
}
