// @vitest-environment jsdom
/**
 * Component tests for the KnowledgeGraph wrapper — the 2D graph slot and its
 * graph-local crash containment (#538).
 *
 * Behavior under test:
 *   1. The 2D graph mounts, with no 2D/3D toggle — even for a profile that
 *      still carries a stale `sapling.kg.mode = "3d"` from the dropped 3D mode.
 *   2. The colour toggle: defaults to `course`, flips to `mastery` (legend
 *      shown), persists, honours a stored choice, and syncs every mounted
 *      graph — while an unknown stored value reads as `course`.
 *   3. A renderer crash shows the placeholder (never another graph) and the
 *      retry button is wired to the boundary's reset.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup, fireEvent, waitFor } from "@testing-library/react";

const mockState = vi.hoisted(() => ({ throw2d: false }));

vi.mock("./KnowledgeGraph2D", async () => {
  const React = await import("react");
  return {
    KnowledgeGraph2D: ({ colorMode }: { colorMode?: string }) => {
      if (mockState.throw2d) throw new Error("2d render boom");
      return React.createElement("div", { "data-testid": "mock-2d", "data-color-mode": colorMode });
    },
  };
});

import { KnowledgeGraph, GRAPH_COLOR_STORAGE_KEY } from "./KnowledgeGraph";

beforeEach(() => {
  mockState.throw2d = false;
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("KnowledgeGraph", () => {
  it("renders the 2D graph with no mode toggle", () => {
    const { queryByTestId } = render(<KnowledgeGraph nodes={[]} edges={[]} />);
    expect(queryByTestId("mock-2d")).not.toBeNull();
    expect(queryByTestId("graph-mode-toggle")).toBeNull();
  });

  it("ignores a stale persisted 3d mode from the dropped 3D graph", () => {
    window.localStorage.setItem("sapling.kg.mode", "3d");
    const { queryByTestId } = render(<KnowledgeGraph nodes={[]} edges={[]} />);
    expect(queryByTestId("mock-2d")).not.toBeNull();
    expect(queryByTestId("graph-mode-toggle")).toBeNull();
  });

  it("defaults to course colours with the toggle off and no legend", () => {
    const { getByTestId, queryByTestId } = render(<KnowledgeGraph nodes={[]} edges={[]} />);
    expect(getByTestId("mock-2d").getAttribute("data-color-mode")).toBe("course");
    expect(getByTestId("graph-color-toggle").getAttribute("aria-pressed")).toBe("false");
    expect(queryByTestId("graph-color-legend")).toBeNull();
  });

  it("toggles to mastery colours, shows the legend, and persists the choice", () => {
    const { getByTestId, queryByTestId } = render(<KnowledgeGraph nodes={[]} edges={[]} />);
    const toggle = getByTestId("graph-color-toggle");
    fireEvent.click(toggle);
    expect(getByTestId("mock-2d").getAttribute("data-color-mode")).toBe("mastery");
    expect(toggle.getAttribute("aria-pressed")).toBe("true");
    expect(getByTestId("graph-color-legend").textContent).toBe(
      "MasteredLearningStrugglingUnexplored",
    );
    expect(window.localStorage.getItem(GRAPH_COLOR_STORAGE_KEY)).toBe("mastery");

    fireEvent.click(toggle);
    expect(getByTestId("mock-2d").getAttribute("data-color-mode")).toBe("course");
    expect(queryByTestId("graph-color-legend")).toBeNull();
    expect(window.localStorage.getItem(GRAPH_COLOR_STORAGE_KEY)).toBe("course");
  });

  it("honours a stored mastery choice and treats an unknown value as course", () => {
    window.localStorage.setItem(GRAPH_COLOR_STORAGE_KEY, "mastery");
    const first = render(<KnowledgeGraph nodes={[]} edges={[]} />);
    expect(first.getByTestId("mock-2d").getAttribute("data-color-mode")).toBe("mastery");
    first.unmount();

    window.localStorage.setItem(GRAPH_COLOR_STORAGE_KEY, "rainbow");
    const second = render(<KnowledgeGraph nodes={[]} edges={[]} />);
    expect(second.getByTestId("mock-2d").getAttribute("data-color-mode")).toBe("course");
  });

  it("flipping one graph flips every mounted graph", () => {
    const { getAllByTestId } = render(
      <>
        <KnowledgeGraph nodes={[]} edges={[]} />
        <KnowledgeGraph nodes={[]} edges={[]} />
      </>,
    );
    fireEvent.click(getAllByTestId("graph-color-toggle")[0]);
    for (const g of getAllByTestId("mock-2d")) {
      expect(g.getAttribute("data-color-mode")).toBe("mastery");
    }
  });

  it("contains a renderer crash behind a placeholder with a working retry", async () => {
    mockState.throw2d = true;
    // React logs boundary-caught errors (and the fallback logs the crash).
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    const { queryByTestId, findByTestId } = render(
      <KnowledgeGraph nodes={[]} edges={[]} />,
    );

    expect(await findByTestId("graph-crash-fallback")).not.toBeNull();
    expect(queryByTestId("mock-2d")).toBeNull();
    expect(
      consoleError.mock.calls.some((c) => c[0] === "[KnowledgeGraph] renderer crashed:"),
    ).toBe(true);

    mockState.throw2d = false;
    fireEvent.click(await findByTestId("graph-crash-retry"));
    await waitFor(() => {
      expect(queryByTestId("mock-2d")).not.toBeNull();
    });
  });
});
