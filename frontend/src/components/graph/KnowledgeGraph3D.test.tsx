// @vitest-environment jsdom
/**
 * Component tests for KnowledgeGraph3D — pins the small but
 * load-bearing adapter logic between our GraphNode/GraphEdge shape
 * and the `react-force-graph-3d` library:
 *   1. Renders without crashing on empty data.
 *   2. `graphData` memo produces the {nodes, links:{source,target,strength}} shape.
 *   3. `nodeColor` returns the brand --accent for the highlighted node
 *      and a deterministic hex shade for everything else (hex, not
 *      `hsl(...)`, because Three.js's Color parser only accepts the
 *      comma-separated HSL form and silently renders space-separated
 *      HSL as black).
 *   4. `nodeVal` scales 4..10 with `mastery_score`, and course-root
 *      nodes (`is_subject_root: true`) render at a fixed larger size.
 *   5. `onNodeClick` whitelists the original GraphNode by id so
 *      library-injected fields (x/y/z, vx/vy/vz, fx/fy/fz,
 *      __threeObj, ...) never leak to callers.
 *   6. Renders an sr-only list of focusable buttons that mirror the
 *      node set for keyboard + screen-reader users.
 *   7. Honours `prefers-reduced-motion: reduce` by setting
 *      `cooldownTicks` to 0 (otherwise 120).
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
import { render, cleanup, fireEvent } from "@testing-library/react";

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

import { KnowledgeGraph3D } from "./KnowledgeGraph3D";
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

// Default `matchMedia` stub for jsdom — returns "no preference" for
// every query. Individual tests override it to flip reduced-motion on.
function installDefaultMatchMedia() {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    configurable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
}

beforeEach(() => {
  lastProps = null;
  installDefaultMatchMedia();
});

afterEach(() => {
  cleanup();
});

describe("KnowledgeGraph3D — adapter behavior", () => {
  it("renders without crashing with empty data", () => {
    expect(() =>
      render(<KnowledgeGraph3D nodes={[]} edges={[]} />),
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

    render(<KnowledgeGraph3D nodes={nodes} edges={edges} />);

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

  it("nodeColor returns the brand accent for the highlighted id and a hex shade otherwise", () => {
    render(
      <KnowledgeGraph3D
        nodes={[makeNode({ id: "abc" })]}
        edges={[]}
        highlightId="abc"
      />,
    );

    expect(lastProps).not.toBeNull();
    const nodeColor = lastProps!.nodeColor as (n: object) => string;

    // Highlight branch: brand --accent (#8a9a5b). Pure white disappears
    // against the cream light theme; the accent pops on both themes.
    expect(nodeColor({ id: "abc", color: "#88aa55" })).toBe("#8a9a5b");

    // Non-highlight branch: deterministic 7-char hex from shadeFor.
    // Hex (not hsl) because Three.js parses hex reliably; the modern
    // space-separated `hsl(120 50% 50%)` syntax silently renders BLACK.
    const other = nodeColor({ id: "xyz", color: "#88aa55" });
    expect(other).toMatch(/^#[0-9a-f]{6}$/);
    expect(other.startsWith("hsl(")).toBe(false);
  });

  it("nodeVal scales 4..10 with mastery_score and pins course-root nodes larger", () => {
    render(<KnowledgeGraph3D nodes={[makeNode()]} edges={[]} />);

    expect(lastProps).not.toBeNull();
    const nodeVal = lastProps!.nodeVal as (n: object) => number;

    // Concept nodes scale linearly with mastery.
    expect(nodeVal({ mastery_score: 0 })).toBe(4);
    expect(nodeVal({ mastery_score: 1 })).toBe(10);

    // Course-root nodes anchor the family — fixed larger size that
    // dominates any concept node regardless of mastery.
    expect(nodeVal({ is_subject_root: true, mastery_score: 0 })).toBe(22);
    expect(nodeVal({ is_subject_root: true, mastery_score: 1 })).toBe(22);
  });

  it("onNodeClick whitelists the original GraphNode by id so lib-injected fields never leak", () => {
    const onNodeClick = vi.fn<(n: GraphNode) => void>();
    const original = makeNode({ id: "n1" });
    render(
      <KnowledgeGraph3D
        nodes={[original]}
        edges={[]}
        onNodeClick={onNodeClick}
      />,
    );

    expect(lastProps).not.toBeNull();
    const handler = lastProps!.onNodeClick as (raw: object) => void;

    // Simulate the lib mutating the node with the FULL set of
    // internals it injects — coordinate, velocity, fixed-position
    // pins, and Three.js refs. None of these should leak to the
    // caller; the caller must receive the canonical prop shape.
    const mutated = {
      ...original,
      x: 1,
      y: 2,
      z: 3,
      vx: 0.1,
      vy: 0.2,
      vz: 0.3,
      fx: 4,
      fy: 5,
      fz: 6,
      __threeObj: { uuid: "fake-mesh" },
      __lineObj: { uuid: "fake-line" },
      __indexColor: "#abcdef",
    };
    handler(mutated);

    expect(onNodeClick).toHaveBeenCalledTimes(1);
    const passed = onNodeClick.mock.calls[0][0] as Record<string, unknown>;

    // The whitelist returns the original prop reference — identity-
    // equal to what the caller handed us.
    expect(passed).toBe(original);

    // Defence-in-depth: none of the library-injected fields
    // survive on the object the caller receives.
    for (const k of [
      "x",
      "y",
      "z",
      "vx",
      "vy",
      "vz",
      "fx",
      "fy",
      "fz",
      "__threeObj",
      "__lineObj",
      "__indexColor",
    ]) {
      expect(passed).not.toHaveProperty(k);
    }
    // Canonical GraphNode fields are present.
    expect(passed.id).toBe("n1");
    expect(passed.mastery_score).toBe(0.5);
  });

  it("renders an sr-only list of focusable buttons that mirror the node set", () => {
    const onNodeClick = vi.fn<(n: GraphNode) => void>();
    const nodes: GraphNode[] = [
      makeNode({ id: "a", name: "Alpha" }),
      makeNode({ id: "b", name: "Beta" }),
    ];
    const { container } = render(
      <KnowledgeGraph3D
        nodes={nodes}
        edges={[]}
        onNodeClick={onNodeClick}
      />,
    );

    const list = container.querySelector(
      'ul[aria-label="Knowledge graph nodes"]',
    );
    expect(list).not.toBeNull();
    const buttons = list!.querySelectorAll("button");
    expect(buttons).toHaveLength(2);
    expect(buttons[0].textContent).toBe("Alpha");
    expect(buttons[1].textContent).toBe("Beta");

    // Activating a button calls back with the matching original node.
    fireEvent.click(buttons[1]);
    expect(onNodeClick).toHaveBeenCalledTimes(1);
    expect(onNodeClick.mock.calls[0][0]).toBe(nodes[1]);
  });

  it("renders sr-only list as static text (no buttons) when onNodeClick is undefined", () => {
    // CodeRabbit review: the focusable buttons would be 'dead
    // controls' if no handler is wired. Pin that the component
    // degrades to non-interactive list items in that case so AT
    // users don't get wasted Tab stops with no behaviour.
    const nodes: GraphNode[] = [
      makeNode({ id: "a", name: "Alpha" }),
      makeNode({ id: "b", name: "Beta" }),
    ];
    const { container } = render(
      <KnowledgeGraph3D nodes={nodes} edges={[]} />,
    );

    const list = container.querySelector(
      'ul[aria-label="Knowledge graph nodes"]',
    );
    expect(list).not.toBeNull();
    // No <button> elements at all.
    expect(list!.querySelectorAll("button")).toHaveLength(0);
    // But every node still appears as <li> text — AT users hear the
    // names without the dead-control affordance.
    const items = list!.querySelectorAll("li");
    expect(items).toHaveLength(2);
    expect(items[0].textContent).toBe("Alpha");
    expect(items[1].textContent).toBe("Beta");
  });

  it("sets cooldownTicks to 0 when prefers-reduced-motion is reduce", () => {
    // Override matchMedia to advertise reduced-motion preference for
    // the relevant query only.
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      configurable: true,
      value: vi.fn().mockImplementation((query: string) => ({
        matches: query === "(prefers-reduced-motion: reduce)",
        media: query,
        onchange: null,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    });

    render(<KnowledgeGraph3D nodes={[makeNode()]} edges={[]} />);

    expect(lastProps).not.toBeNull();
    expect(lastProps!.cooldownTicks).toBe(0);
  });
});
