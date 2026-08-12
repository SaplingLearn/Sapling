// @vitest-environment jsdom
/**
 * Component tests for the KnowledgeGraph wrapper — pins the 2D/3D mode
 * selection logic, and (#538) the WebGL2 capability gate + local crash
 * containment that keep a WebGL-less browser from blanking the whole
 * app into the root error fallback:
 *   1. Fresh profile defaults to 2D (pin).
 *   2. Persisted "3d" mode is honoured when WebGL2 is available (pin).
 *   3. Persisted "3d" mode is IGNORED when WebGL2 is unavailable — the
 *      2D graph renders and the crash-prone 3D renderer never mounts.
 *   4. The mode toggle is disabled with an explanatory label when
 *      WebGL2 is unavailable.
 *   5. A 3D renderer that throws at mount (three.js throws
 *      `Error creating WebGL context.` from the WebGLRenderer
 *      constructor) degrades to the 2D graph inline and heals the
 *      persisted mode to "2d" — the error must not escape the wrapper.
 *
 * Mocking strategy: both graph implementations are replaced with
 * sentinels so the tests exercise only the wrapper's selection logic.
 * The 3D sentinel can be armed to throw, mimicking three.js's
 * constructor throw at mount. `next/dynamic` is a passthrough exactly
 * as in KnowledgeGraph3D.test.tsx. WebGL capability is controlled by
 * stubbing HTMLCanvasElement.prototype.getContext.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup, waitFor } from "@testing-library/react";

const mockState = vi.hoisted(() => ({ throw3d: false }));

vi.mock("./KnowledgeGraph2D", async () => {
  const React = await import("react");
  return {
    KnowledgeGraph2D: () =>
      React.createElement("div", { "data-testid": "mock-2d" }),
  };
});

vi.mock("./KnowledgeGraph3D", async () => {
  const React = await import("react");
  return {
    KnowledgeGraph3D: () => {
      if (mockState.throw3d) {
        // Mirrors three.module.js's WebGLRenderer constructor throw.
        throw new Error("Error creating WebGL context.");
      }
      return React.createElement("div", { "data-testid": "mock-3d" });
    },
  };
});

// Same passthrough as KnowledgeGraph3D.test.tsx: render the (mocked)
// dynamic module synchronously instead of next/dynamic's client-only
// loader dance.
type MockComponent = (props: Record<string, unknown>) => React.ReactNode;

vi.mock("next/dynamic", () => ({
  default: (loader: () => Promise<unknown>) => {
    let Resolved: MockComponent = () => null;
    Promise.resolve(loader()).then((mod) => {
      const m = mod as { default?: MockComponent } | MockComponent;
      Resolved =
        typeof m === "function" ? m : (m.default ?? (() => null));
    });
    const Wrapper: MockComponent = (props) => {
      const C = Resolved;
      return C(props);
    };
    return Wrapper;
  },
}));

import { KnowledgeGraph } from "./KnowledgeGraph";

const STORAGE_KEY = "sapling.kg.mode";

/** Stub canvas.getContext to advertise (or deny) WebGL2 support. */
function setWebgl2Available(available: boolean) {
  Object.defineProperty(HTMLCanvasElement.prototype, "getContext", {
    configurable: true,
    writable: true,
    value: vi.fn().mockImplementation((kind: string) => {
      if (kind === "webgl2" && available) {
        // Minimal context shape: the probe may look up
        // WEBGL_lose_context to release the probe context.
        return { getExtension: () => null };
      }
      return null;
    }),
  });
}

beforeEach(() => {
  mockState.throw3d = false;
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("KnowledgeGraph — mode selection", () => {
  it("defaults to the 2D graph on a fresh profile", () => {
    setWebgl2Available(true);
    const { queryByTestId } = render(<KnowledgeGraph nodes={[]} edges={[]} />);
    expect(queryByTestId("mock-2d")).not.toBeNull();
    expect(queryByTestId("mock-3d")).toBeNull();
  });

  it("honours persisted 3d mode when WebGL2 is available", () => {
    setWebgl2Available(true);
    window.localStorage.setItem(STORAGE_KEY, "3d");
    const { queryByTestId } = render(<KnowledgeGraph nodes={[]} edges={[]} />);
    expect(queryByTestId("mock-3d")).not.toBeNull();
    expect(queryByTestId("mock-2d")).toBeNull();
  });
});

describe("KnowledgeGraph — WebGL2 capability gate (#538)", () => {
  it("forces the 2D graph when 3d mode is persisted but WebGL2 is unavailable", () => {
    setWebgl2Available(false);
    window.localStorage.setItem(STORAGE_KEY, "3d");
    const { queryByTestId } = render(<KnowledgeGraph nodes={[]} edges={[]} />);
    // The 3D renderer must never mount — on a real no-WebGL browser it
    // throws from three's WebGLRenderer constructor at mount.
    expect(queryByTestId("mock-3d")).toBeNull();
    expect(queryByTestId("mock-2d")).not.toBeNull();
  });

  it("disables the mode toggle with an explanatory label when WebGL2 is unavailable", () => {
    setWebgl2Available(false);
    const { getByTestId } = render(<KnowledgeGraph nodes={[]} edges={[]} />);
    const toggle = getByTestId("graph-mode-toggle") as HTMLButtonElement;
    expect(toggle.disabled).toBe(true);
    expect(toggle.title.toLowerCase()).toContain("webgl");
  });

  it("keeps the mode toggle enabled when WebGL2 is available", () => {
    setWebgl2Available(true);
    const { getByTestId } = render(<KnowledgeGraph nodes={[]} edges={[]} />);
    const toggle = getByTestId("graph-mode-toggle") as HTMLButtonElement;
    expect(toggle.disabled).toBe(false);
  });
});

describe("KnowledgeGraph — 3D renderer crash containment (#538)", () => {
  it("degrades a crashed 3D renderer to the 2D graph and heals the persisted mode", async () => {
    // WebGL2 probes fine, but the renderer still throws at mount —
    // e.g. GPU process crash or per-page context-limit exhaustion.
    setWebgl2Available(true);
    window.localStorage.setItem(STORAGE_KEY, "3d");
    mockState.throw3d = true;

    // React logs caught boundary errors via console.error; keep the
    // test output pristine without hiding unrelated errors.
    const consoleError = vi
      .spyOn(console, "error")
      .mockImplementation(() => {});

    const { queryByTestId } = render(<KnowledgeGraph nodes={[]} edges={[]} />);

    // The crash must be contained: 2D graph inline, no rethrow.
    await waitFor(() => {
      expect(queryByTestId("mock-2d")).not.toBeNull();
    });
    expect(queryByTestId("mock-3d")).toBeNull();

    // The bad persisted mode heals so the next mount doesn't retry 3D.
    await waitFor(() => {
      expect(window.localStorage.getItem(STORAGE_KEY)).toBe("2d");
    });

    consoleError.mockRestore();
  });
});
