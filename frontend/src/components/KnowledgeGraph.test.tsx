// @vitest-environment jsdom
/**
 * Component tests for KnowledgeGraph (3D) — pins the small but
 * load-bearing adapter logic between our GraphNode/GraphEdge shape
 * and the `react-force-graph-3d` library:
 *   1. Renders without crashing on empty data.
 *   2. `graphData` memo produces the {nodes, links:{source,target,strength}} shape.
 *   3. `nodeColor` returns "#ffffff" for the highlighted node and an
 *      `hsl(...)` shade for everything else.
 *   4. `nodeVal` scales 4..10 with `mastery_score`.
 *   5. `onNodeClick` strips lib-mutated x/y/z before handing the node back.
 *
 * Mocking strategy: we replace `react-force-graph-3d` with a stub that
 * captures the props the component passes (so tests can call back into
 * the callbacks). `next/dynamic` is replaced with a passthrough that
 * synchronously returns the (already-mocked) ForceGraph3D module —
 * vitest's hoisted `vi.mock` ensures the mock module is in place before
 * `next/dynamic`'s loader runs, so the component sees the mock at first
 * render without the eager-resolve dance.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup } from "@testing-library/react";

// Capture the props the component passes to ForceGraph3D so tests can
// drive its callbacks. Reset in beforeEach.
let lastProps: Record<string, any> | null = null;

vi.mock("react-force-graph-3d", () => ({
  default: (props: any) => {
    lastProps = props;
    return null;
  },
}));

// next/dynamic is used to client-only-load react-force-graph-3d. In
// tests we want the mock module above to render synchronously, so we
// replace `dynamic(loader)` with a component that calls the resolved
// module's default export directly. Because the mock for
// react-force-graph-3d is hoisted, `loader()` resolves immediately and
// our require fallback grabs the same object the runtime would.
vi.mock("next/dynamic", () => ({
  default: (loader: any) => {
    // Resolve the loader once, synchronously where possible. Vitest's
    // module mocks resolve as already-fulfilled promises, so we read
    // the .then callback synchronously via `.then()` and stash the
    // component. The wrapper below renders whatever's been resolved.
    let Resolved: any = () => null;
    Promise.resolve(loader()).then((mod: any) => {
      Resolved = mod?.default ?? mod;
    });
    const Wrapper = (props: any) => {
      // Re-resolve at render time too — covers the (rare) case where
      // the microtask hasn't flushed yet on first paint.
      const C = Resolved;
      return C ? C(props) : null;
    };
    return Wrapper;
  },
}));

import { KnowledgeGraph } from "./KnowledgeGraph";
import type { GraphEdge, GraphNode } from "@/lib/data";

function makeNode(over: Partial<GraphNode> = {}): GraphNode {
  return {
    id: "n1",
    name: "Node 1",
    subject: "Math",
    color: "#88aa55",
    mastery_tier: "learning",
    mastery_score: 0.5,
    course_id: "c1",
    ...over,
  };
}

beforeEach(() => {
  lastProps = null;
});

afterEach(() => {
  cleanup();
});

describe("KnowledgeGraph (3D) — adapter behavior", () => {
  it("renders without crashing with empty data", () => {
    expect(() =>
      render(<KnowledgeGraph nodes={[]} edges={[]} />),
    ).not.toThrow();
    // The mock should still have received props (graphData with empty
    // arrays) — sanity check that the dynamic-import wrapper got past
    // the loading=null fallback.
    expect(lastProps).not.toBeNull();
    expect(lastProps!.graphData).toEqual({ nodes: [], links: [] });
  });

  it("passes graphData with the correct {nodes, links} shape", () => {
    const nodes: GraphNode[] = [
      makeNode({ id: "a", name: "A" }),
      makeNode({ id: "b", name: "B" }),
    ];
    const edges: GraphEdge[] = [
      { source: "a", target: "b", strength: 0.7 },
    ];

    render(<KnowledgeGraph nodes={nodes} edges={edges} />);

    expect(lastProps).not.toBeNull();
    const { graphData } = lastProps!;
    expect(graphData.nodes).toHaveLength(2);
    expect(graphData.nodes[0].id).toBe("a");
    expect(graphData.nodes[1].id).toBe("b");
    // Links should carry exactly source/target/strength — nothing else
    // leaks through. Equality on a single link covers the shape.
    expect(graphData.links).toEqual([
      { source: "a", target: "b", strength: 0.7 },
    ]);
    // The clone discipline: graphData.nodes must be fresh objects, not
    // the caller's references — otherwise the lib's in-place mutation
    // of x/y/z poisons the parent's array.
    expect(graphData.nodes[0]).not.toBe(nodes[0]);
  });

  it("nodeColor returns white for the highlighted id and an hsl() shade otherwise", () => {
    render(
      <KnowledgeGraph
        nodes={[makeNode({ id: "abc" })]}
        edges={[]}
        highlightId="abc"
      />,
    );

    expect(lastProps).not.toBeNull();
    const nodeColor = lastProps!.nodeColor as (n: object) => string;

    // Highlight branch: exact white.
    expect(nodeColor({ id: "abc", color: "#88aa55" })).toBe("#ffffff");

    // Non-highlight branch: deterministic hsl(...) string from shadeFor.
    const other = nodeColor({ id: "xyz", color: "#88aa55" });
    expect(other.startsWith("hsl(")).toBe(true);
  });

  it("nodeVal scales 4..10 with mastery_score (0 -> 4, 1 -> 10)", () => {
    render(<KnowledgeGraph nodes={[makeNode()]} edges={[]} />);

    expect(lastProps).not.toBeNull();
    const nodeVal = lastProps!.nodeVal as (n: object) => number;

    expect(nodeVal({ mastery_score: 0 })).toBe(4);
    expect(nodeVal({ mastery_score: 1 })).toBe(10);
  });

  it("onNodeClick strips x/y/z coordinate fields before handing the node to the caller", () => {
    const onNodeClick = vi.fn<(n: GraphNode) => void>();
    render(
      <KnowledgeGraph
        nodes={[makeNode({ id: "n1" })]}
        edges={[]}
        onNodeClick={onNodeClick}
      />,
    );

    expect(lastProps).not.toBeNull();
    const handler = lastProps!.onNodeClick as (raw: object) => void;

    // Simulate the lib mutating the node with simulation coords.
    const mutated = {
      ...makeNode({ id: "n1" }),
      x: 1,
      y: 2,
      z: 3,
    };
    handler(mutated);

    expect(onNodeClick).toHaveBeenCalledTimes(1);
    const passed = onNodeClick.mock.calls[0][0] as Record<string, unknown>;
    expect(passed).not.toHaveProperty("x");
    expect(passed).not.toHaveProperty("y");
    expect(passed).not.toHaveProperty("z");
    // Other GraphNode fields survive the strip.
    expect(passed.id).toBe("n1");
    expect(passed.mastery_score).toBe(0.5);
  });
});
