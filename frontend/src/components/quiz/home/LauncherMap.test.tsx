// @vitest-environment jsdom
/**
 * Launcher Map pane (W7.10) — course filter, select≠start, real graph only.
 */
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { GraphEdge, GraphNode } from "@/lib/data";

const seen = vi.hoisted(() => ({ props: [] as Record<string, unknown>[] }));
vi.mock("@/components/graph/KnowledgeGraph2D", () => ({
  KnowledgeGraph2D: (props: Record<string, unknown>) => {
    seen.props.push(props);
    const nodes = (props.nodes as GraphNode[]) ?? [];
    return (
      <div data-testid="kg2d">
        {nodes.map(n => (
          <button
            key={n.id}
            type="button"
            data-testid={`kg-activate-${n.id}`}
            onClick={() => (props.onNodeClick as ((n: GraphNode) => void) | undefined)?.(n)}
          >
            {n.name}
          </button>
        ))}
      </div>
    );
  },
}));

import { graphForCourse, LauncherMap } from "./LauncherMap";

const NODES: GraphNode[] = [
  {
    id: "hub-cs",
    name: "CS101",
    subject: "CS101",
    color: "#7b4b99",
    mastery_tier: "learning",
    mastery_score: 0.5,
    course_id: "c-cs",
    is_subject_root: true,
  },
  {
    id: "recursion",
    name: "Recursion",
    subject: "CS101",
    color: "#7b4b99",
    mastery_tier: "struggling",
    mastery_score: 0.3,
    course_id: "c-cs",
  },
  {
    id: "eigenvalues",
    name: "Eigenvalues",
    subject: "MATH210",
    color: "#3e6f8a",
    mastery_tier: "struggling",
    mastery_score: 0.3,
    course_id: "c-math",
  },
];

const EDGES: GraphEdge[] = [
  { source: "hub-cs", target: "recursion", strength: 1 },
  { source: "recursion", target: "eigenvalues", strength: 0.2 },
];

let observed: ((w: number, h: number) => void) | null = null;

beforeEach(() => {
  seen.props = [];
  observed = null;
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(private cb: (entries: { contentRect: { width: number; height: number } }[]) => void) {}
      observe() {
        observed = (w, h) => this.cb([{ contentRect: { width: w, height: h } }]);
      }
      disconnect() {}
    },
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("graphForCourse", () => {
  it("returns the full union when the filter is All", () => {
    expect(graphForCourse(NODES, EDGES, "all")).toEqual({ nodes: NODES, edges: EDGES });
  });

  it("keeps only one course's nodes and edges between them", () => {
    const { nodes, edges } = graphForCourse(NODES, EDGES, "c-cs");
    expect(nodes.map(n => n.id)).toEqual(["hub-cs", "recursion"]);
    expect(edges).toEqual([{ source: "hub-cs", target: "recursion", strength: 1 }]);
  });
});

describe("LauncherMap", () => {
  it("draws a fitted KnowledgeGraph2D of the filtered course graph", () => {
    render(
      <LauncherMap
        nodes={NODES}
        edges={EDGES}
        courseFilter="c-cs"
        highlightId="recursion"
        onPick={vi.fn()}
      />,
    );
    act(() => observed!(320, 360));
    expect(screen.getByTestId("quiz-launcher-map")).toBeTruthy();
    expect(seen.props.at(-1)).toMatchObject({
      width: 320,
      height: 360,
      highlightId: "recursion",
      fit: true,
    });
    expect((seen.props.at(-1)!.nodes as GraphNode[]).map(n => n.id)).toEqual(["hub-cs", "recursion"]);
  });

  it("picks a concept and ignores course hubs — never auto-starts", () => {
    const onPick = vi.fn();
    render(
      <LauncherMap nodes={NODES} edges={EDGES} courseFilter="all" onPick={onPick} />,
    );
    act(() => observed!(400, 360));
    fireEvent.click(screen.getByTestId("kg-activate-hub-cs"));
    expect(onPick).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("kg-activate-eigenvalues"));
    expect(onPick).toHaveBeenCalledTimes(1);
    expect(onPick).toHaveBeenCalledWith("eigenvalues");
  });

  it("shows an honest empty state with no ghost nodes", () => {
    render(
      <LauncherMap nodes={NODES} edges={EDGES} courseFilter="c-gone" onPick={vi.fn()} />,
    );
    expect(screen.getByTestId("quiz-launcher-map-empty")).toHaveTextContent("No concepts on the map");
    expect(screen.queryByTestId("kg2d")).toBeNull();
  });

  it("forwards practicedIds when the caller has them (W3.2 optional)", () => {
    const practiced = new Set(["recursion"]);
    render(
      <LauncherMap
        nodes={NODES}
        edges={EDGES}
        courseFilter="all"
        onPick={vi.fn()}
        practicedIds={practiced}
      />,
    );
    act(() => observed!(400, 360));
    expect(seen.props.at(-1)).toMatchObject({ practicedIds: practiced });
  });
});
