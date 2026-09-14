// @vitest-environment jsdom
/**
 * Component tests for the KnowledgeGraph wrapper — the 2D/3D mode selection,
 * the WebGL2 capability gate, and the graph-local crash containment (#538).
 *
 * Behavior under test:
 *   1. Fresh profile defaults to 2D (pin).
 *   2. Persisted "3d" is honoured when WebGL2 is available (pin), and the
 *      toggle switches modes.
 *   3. Persisted "3d" is IGNORED (not rewritten) when WebGL2 is unavailable —
 *      the crash-prone 3D renderer never mounts.
 *   4. Without WebGL2 the toggle is aria-disabled but stays focusable, keeps
 *      its action name, and points at a "requires WebGL" description —
 *      native `disabled` would hide the reason from keyboard/SR users.
 *   5. A "3d" broadcast (SYNC_EVENT) at a WebGL-less instance must not mount
 *      3D — the gate applies to the listener path, not just mount.
 *   6. A 3D crash re-probes capability instead of rewriting the preference:
 *      capability gone → 2D mounts, localStorage keeps "3d"; capability fine
 *      (transient crash) → placeholder with a wired retry; a 2D crash shows
 *      the placeholder rather than remounting what just threw.
 *
 * Mocking strategy: both graph implementations are sentinels; the 3D one
 * throws from a LAYOUT EFFECT when armed — matching the real crash phase
 * (react-kapsule constructs three's WebGLRenderer in its mount
 * useLayoutEffect; three throws from that constructor without WebGL2).
 * WebGL capability is a vi.spyOn stub over getContext reading a mutable
 * `env`, so tests can model capability changing AFTER the probe cached its
 * verdict. next/dynamic uses the shared passthrough helper.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup, fireEvent, act, waitFor } from "@testing-library/react";

const mockState = vi.hoisted(() => ({ throw3d: false, throw2d: false }));

vi.mock("./KnowledgeGraph2D", async () => {
  const React = await import("react");
  return {
    KnowledgeGraph2D: () => {
      if (mockState.throw2d) throw new Error("2d render boom");
      return React.createElement("div", { "data-testid": "mock-2d" });
    },
  };
});

vi.mock("./KnowledgeGraph3D", async () => {
  const React = await import("react");
  return {
    KnowledgeGraph3D: () => {
      // Real crash phase: three's WebGLRenderer constructor throws inside
      // react-kapsule's mount useLayoutEffect, not during render.
      React.useLayoutEffect(() => {
        if (mockState.throw3d) {
          throw new Error("Error creating WebGL context.");
        }
      });
      return React.createElement("div", { "data-testid": "mock-3d" });
    },
  };
});

vi.mock("next/dynamic", async () =>
  (await import("@/test-utils/mockNextDynamic")).mockNextDynamicModule(),
);

import {
  KnowledgeGraph,
  GRAPH_MODE_STORAGE_KEY,
  GRAPH_MODE_SYNC_EVENT,
  probeWebgl2,
} from "./KnowledgeGraph";

/** Mutable capability the getContext stub reads at CALL time — lets a test
 * model WebGL dying after the probe cached its verdict. */
const env = { webgl2: true };

function stubGetContext() {
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(((
    kind: string,
  ) => {
    if (kind === "webgl2" && env.webgl2) {
      // Minimal context shape: the probe may look up WEBGL_lose_context
      // to release the probe context.
      return { getExtension: () => null };
    }
    return null;
  }) as unknown as HTMLCanvasElement["getContext"]);
}

/** Set capability AND re-prime the module-level probe cache from it. */
function setWebgl2(available: boolean) {
  env.webgl2 = available;
  probeWebgl2(true);
}

beforeEach(() => {
  mockState.throw3d = false;
  mockState.throw2d = false;
  window.localStorage.clear();
  stubGetContext();
  setWebgl2(true);
});

afterEach(() => {
  cleanup();
  // Actually restores getContext — the stub is installed via vi.spyOn, which
  // (unlike a defineProperty swap) registers with restoreAllMocks.
  vi.restoreAllMocks();
});

function silenceBoundaryLogs() {
  // React logs boundary-caught errors (and our fallback logs the crash)
  // via console.error; keep test output pristine.
  return vi.spyOn(console, "error").mockImplementation(() => {});
}

describe("KnowledgeGraph — mode selection", () => {
  it("defaults to the 2D graph on a fresh profile", () => {
    const { queryByTestId } = render(<KnowledgeGraph nodes={[]} edges={[]} />);
    expect(queryByTestId("mock-2d")).not.toBeNull();
    expect(queryByTestId("mock-3d")).toBeNull();
  });

  it("honours persisted 3d mode when WebGL2 is available", () => {
    window.localStorage.setItem(GRAPH_MODE_STORAGE_KEY, "3d");
    const { queryByTestId } = render(<KnowledgeGraph nodes={[]} edges={[]} />);
    expect(queryByTestId("mock-3d")).not.toBeNull();
    expect(queryByTestId("mock-2d")).toBeNull();
  });

  it("toggle switches 2D → 3D when WebGL2 is available", () => {
    const { getByTestId, queryByTestId } = render(
      <KnowledgeGraph nodes={[]} edges={[]} />,
    );
    const toggle = getByTestId("graph-mode-toggle");
    expect(toggle.getAttribute("aria-disabled")).not.toBe("true");
    fireEvent.click(toggle);
    expect(queryByTestId("mock-3d")).not.toBeNull();
    expect(window.localStorage.getItem(GRAPH_MODE_STORAGE_KEY)).toBe("3d");
  });
});

describe("KnowledgeGraph — WebGL2 capability gate (#538)", () => {
  it("forces the 2D graph when 3d mode is persisted but WebGL2 is unavailable, without rewriting the preference", () => {
    setWebgl2(false);
    window.localStorage.setItem(GRAPH_MODE_STORAGE_KEY, "3d");
    const { queryByTestId } = render(<KnowledgeGraph nodes={[]} edges={[]} />);
    expect(queryByTestId("mock-3d")).toBeNull();
    expect(queryByTestId("mock-2d")).not.toBeNull();
    // Ignored, NOT rewritten — the preference survives for WebGL-capable
    // browsers on this profile.
    expect(window.localStorage.getItem(GRAPH_MODE_STORAGE_KEY)).toBe("3d");
  });

  it("marks the toggle aria-disabled but keeps it focusable with the reason reachable", () => {
    setWebgl2(false);
    const { getByTestId, queryByTestId } = render(
      <KnowledgeGraph nodes={[]} edges={[]} />,
    );
    const toggle = getByTestId("graph-mode-toggle") as HTMLButtonElement;

    // aria-disabled, NOT native disabled: native disabled removes the
    // control from the tab order, making the reason unreachable to
    // keyboard/SR users.
    expect(toggle.getAttribute("aria-disabled")).toBe("true");
    expect(toggle.disabled).toBe(false);
    toggle.focus();
    expect(document.activeElement).toBe(toggle);

    // The accessible NAME stays the action; the REASON hangs off
    // aria-describedby.
    const describedBy = toggle.getAttribute("aria-describedby");
    expect(describedBy).toBeTruthy();
    const desc = document.getElementById(describedBy!);
    expect(desc?.textContent ?? "").toContain("WebGL");

    // Clicking an aria-disabled control is a no-op.
    fireEvent.click(toggle);
    expect(queryByTestId("mock-3d")).toBeNull();
    expect(window.localStorage.getItem(GRAPH_MODE_STORAGE_KEY)).not.toBe("3d");
  });

  it("gates the sync-event path: a broadcast '3d' at a WebGL-less instance keeps 2D mounted", () => {
    setWebgl2(false);
    const { queryByTestId } = render(<KnowledgeGraph nodes={[]} edges={[]} />);
    act(() => {
      window.dispatchEvent(
        new CustomEvent(GRAPH_MODE_SYNC_EVENT, { detail: "3d" }),
      );
    });
    expect(queryByTestId("mock-3d")).toBeNull();
    expect(queryByTestId("mock-2d")).not.toBeNull();
  });
});

describe("KnowledgeGraph — 3D renderer crash containment (#538)", () => {
  it("recovers a stale capability verdict: crash re-probes, 2D mounts, preference intact", async () => {
    // WebGL verdict cached as available, then capability dies BEFORE mount
    // (GPU process crash) — the stale cache lets 3D mount and throw.
    window.localStorage.setItem(GRAPH_MODE_STORAGE_KEY, "3d");
    mockState.throw3d = true;
    env.webgl2 = false; // capability gone; cache still says available

    const consoleError = silenceBoundaryLogs();
    const { queryByTestId, getByTestId } = render(
      <KnowledgeGraph nodes={[]} edges={[]} />,
    );

    // Contained and downgraded via re-probe: fresh boundary mounts 2D.
    await waitFor(() => {
      expect(queryByTestId("mock-2d")).not.toBeNull();
    });
    expect(queryByTestId("mock-3d")).toBeNull();

    // The preference is NEVER rewritten by a crash.
    expect(window.localStorage.getItem(GRAPH_MODE_STORAGE_KEY)).toBe("3d");

    // The re-probe also fixes the toggle's disabled reason.
    expect(getByTestId("graph-mode-toggle").getAttribute("aria-disabled")).toBe(
      "true",
    );
    consoleError.mockRestore();
  });

  it("contains a transient 3D crash (capability fine): placeholder with a working retry, preference intact", async () => {
    window.localStorage.setItem(GRAPH_MODE_STORAGE_KEY, "3d");
    mockState.throw3d = true; // transient: capability stays available

    const consoleError = silenceBoundaryLogs();
    const { queryByTestId, findByTestId } = render(
      <KnowledgeGraph nodes={[]} edges={[]} />,
    );

    // Placeholder, not a component that could rethrow inside the errored
    // boundary's own fallback render.
    const fallback = await findByTestId("graph-crash-fallback");
    expect(fallback).not.toBeNull();
    expect(queryByTestId("mock-2d")).toBeNull();
    expect(window.localStorage.getItem(GRAPH_MODE_STORAGE_KEY)).toBe("3d");

    // The boundary's reset is wired: once the transient condition clears,
    // retry remounts the 3D renderer in place.
    mockState.throw3d = false;
    fireEvent.click(await findByTestId("graph-crash-retry"));
    await waitFor(() => {
      expect(queryByTestId("mock-3d")).not.toBeNull();
    });
    consoleError.mockRestore();
  });

  it("contains a 2D crash behind the same placeholder instead of remounting what just threw", async () => {
    mockState.throw2d = true;

    const consoleError = silenceBoundaryLogs();
    const { queryByTestId, findByTestId } = render(
      <KnowledgeGraph nodes={[]} edges={[]} />,
    );

    expect(await findByTestId("graph-crash-fallback")).not.toBeNull();
    expect(queryByTestId("mock-2d")).toBeNull();

    // Retry works here too once the condition clears.
    mockState.throw2d = false;
    fireEvent.click(await findByTestId("graph-crash-retry"));
    await waitFor(() => {
      expect(queryByTestId("mock-2d")).not.toBeNull();
    });
    consoleError.mockRestore();
  });
});
