// @vitest-environment jsdom
/**
 * Component tests for KnowledgeGraph3D — pins the small but
 * load-bearing adapter logic between our GraphNode/GraphEdge shape
 * and the `react-force-graph-3d` library:
 *   1. Renders without crashing on empty data.
 *   2. `graphData` memo produces the {nodes, links:{source,target,strength}} shape.
 *   3. `nodeThreeObject` composes a matte sphere + hidden focus halo +
 *      always-visible SpriteText label per node, sized/colored via the
 *      Task-1 pure helpers (`baseNodeColor`, `nodeRadius`, `labelSpec`).
 *   4. Subject-root nodes get the pinned-larger sphere and bold label;
 *      `highlightId` renders that node's halo persistently.
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
 * render without the eager-resolve dance. `three-spritetext` is mocked
 * too: jsdom has no canvas 2D context, and the real SpriteText paints
 * text onto a canvas texture at construction.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup, fireEvent, act } from "@testing-library/react";
import * as THREE from "three";
import SpriteText from "three-spritetext";
import {
  baseNodeColor,
  labelSpec,
  nodeRadius,
  FALLBACK_THEME,
  NODE_OPACITY,
  DIM_NODE_OPACITY,
  DIM_LABEL_OPACITY,
  LIT_LINK_ALPHA,
  DIM_LINK_ALPHA,
  BASE_LINK_ALPHA,
} from "./graph3dHelpers";

// Capture the props the component passes to ForceGraph3D so tests can
// drive its callbacks. Reset in beforeEach.
let lastProps: Record<string, any> | null = null;
let zoomToFitSpy = vi.fn();

vi.mock("react-force-graph-3d", () => ({
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  default: React.forwardRef((props: any, ref: React.Ref<unknown>) => {
    lastProps = props;
    React.useImperativeHandle(ref, () => ({ zoomToFit: zoomToFitSpy }));
    return null;
  }),
}));

// jsdom has no canvas 2D context, and the real SpriteText paints text
// onto a canvas texture at construction; extending the real
// THREE.Object3D keeps `group.add(...)` happy.
vi.mock("three-spritetext", async () => {
  const three = await vi.importActual<typeof import("three")>("three");
  class SpriteTextMock extends three.Object3D {
    text: string;
    textHeight = 2;
    color = "";
    fontFace = "";
    fontWeight = "";
    material = { opacity: 1, transparent: false };
    constructor(text: string) {
      super();
      this.text = text;
    }
  }
  return { default: SpriteTextMock };
});

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

function partsOf(group: THREE.Group) {
  const meshes = group.children.filter(
    (c): c is THREE.Mesh => (c as THREE.Mesh).isMesh === true,
  );
  const sphere = meshes.find((m) => m.material instanceof THREE.MeshLambertMaterial)!;
  const halo = meshes.find((m) => m.material instanceof THREE.MeshBasicMaterial)!;
  const label = group.children.find(
    (c) => c instanceof SpriteText,
  ) as InstanceType<typeof SpriteText>;
  return { sphere, halo, label };
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
  zoomToFitSpy = vi.fn();
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

  it("nodeThreeObject composes matte sphere + hidden halo + always-visible label", () => {
    render(<KnowledgeGraph3D nodes={[makeNode({ id: "abc", name: "Chain Rule" })]} edges={[]} />);
    expect(lastProps).not.toBeNull();
    const build = lastProps!.nodeThreeObject as (n: object) => THREE.Group;
    const group = build({ ...makeNode({ id: "abc", name: "Chain Rule" }) });
    const { sphere, halo, label } = partsOf(group);

    const mat = sphere.material as THREE.MeshLambertMaterial;
    // jsdom resolves no CSS vars, so the component runs on FALLBACK_THEME.
    expect(`#${mat.color.getHexString()}`).toBe(
      baseNodeColor(makeNode({ id: "abc" }), FALLBACK_THEME),
    );
    expect(mat.transparent).toBe(true);
    expect(mat.opacity).toBeCloseTo(NODE_OPACITY);

    expect(halo.visible).toBe(false); // no hover, no highlight

    expect(label.text).toBe("Chain Rule");
    expect(label.textHeight).toBe(labelSpec(makeNode()).textHeight);
    expect(label.fontWeight).toBe(labelSpec(makeNode()).fontWeight);
    expect(label.color).toBe(FALLBACK_THEME.ink);
    // Label hangs below the sphere, never occludes it.
    expect(label.position.y).toBeLessThan(0);
  });

  it("subject-root nodes get the pinned-larger sphere and bold label", () => {
    render(<KnowledgeGraph3D nodes={[makeNode()]} edges={[]} />);
    const build = lastProps!.nodeThreeObject as (n: object) => THREE.Group;
    const root = makeNode({ id: "r", is_subject_root: true });
    const { sphere, label } = partsOf(build({ ...root }));
    const geo = sphere.geometry as THREE.SphereGeometry;
    expect(geo.parameters.radius).toBeCloseTo(nodeRadius(root));
    expect(label.textHeight).toBe(5);
    expect(label.fontWeight).toBe("700");
  });

  it("highlightId renders that node's halo persistently", () => {
    render(
      <KnowledgeGraph3D nodes={[makeNode({ id: "abc" })]} edges={[]} highlightId="abc" />,
    );
    const build = lastProps!.nodeThreeObject as (n: object) => THREE.Group;
    expect(partsOf(build({ ...makeNode({ id: "abc" }) })).halo.visible).toBe(true);
    expect(partsOf(build({ ...makeNode({ id: "other" }) })).halo.visible).toBe(false);
  });

  it("hovering dims non-neighbors and restores everything on mouse-off", () => {
    const nodes = [makeNode({ id: "a" }), makeNode({ id: "b" }), makeNode({ id: "c" })];
    const edges: GraphEdge[] = [{ source: "a", target: "b", strength: 1 }];
    render(<KnowledgeGraph3D nodes={nodes} edges={edges} />);

    const build = lastProps!.nodeThreeObject as (n: object) => THREE.Group;
    const gA = build({ ...nodes[0] });
    const gB = build({ ...nodes[1] });
    const gC = build({ ...nodes[2] });

    act(() => {
      (lastProps!.onNodeHover as (n: object | null) => void)({ id: "a" });
    });

    // hovered + neighbor stay lit; the stranger dims
    expect((partsOf(gA).sphere.material as THREE.MeshLambertMaterial).opacity).toBeCloseTo(NODE_OPACITY);
    expect((partsOf(gB).sphere.material as THREE.MeshLambertMaterial).opacity).toBeCloseTo(NODE_OPACITY);
    expect((partsOf(gC).sphere.material as THREE.MeshLambertMaterial).opacity).toBeCloseTo(DIM_NODE_OPACITY);
    expect(partsOf(gC).label.material.opacity).toBeCloseTo(DIM_LABEL_OPACITY);
    expect(`#${(partsOf(gC).sphere.material as THREE.MeshLambertMaterial).color.getHexString()}`).toBe(
      FALLBACK_THEME.dim,
    );
    expect(partsOf(gA).halo.visible).toBe(true);
    expect(partsOf(gB).halo.visible).toBe(false);

    act(() => {
      (lastProps!.onNodeHover as (n: object | null) => void)(null);
    });

    expect((partsOf(gC).sphere.material as THREE.MeshLambertMaterial).opacity).toBeCloseTo(NODE_OPACITY);
    expect(partsOf(gC).label.material.opacity).toBeCloseTo(1);
    expect(partsOf(gA).halo.visible).toBe(false);
  });

  it("linkColor lights edges touching the hovered node and dims the rest", () => {
    const nodes = [makeNode({ id: "a" }), makeNode({ id: "b" }), makeNode({ id: "c" })];
    const edges: GraphEdge[] = [
      { source: "a", target: "b", strength: 1 },
      { source: "b", target: "c", strength: 1 },
    ];
    render(<KnowledgeGraph3D nodes={nodes} edges={edges} />);

    // No hover: uniform base alpha.
    let linkColor = lastProps!.linkColor as (l: object) => string;
    expect(linkColor({ source: "a", target: "b" })).toBe(`rgba(138, 131, 114, ${BASE_LINK_ALPHA})`);

    act(() => {
      (lastProps!.onNodeHover as (n: object | null) => void)({ id: "a" });
    });

    linkColor = lastProps!.linkColor as (l: object) => string; // re-keyed accessor
    expect(linkColor({ source: "a", target: "b" })).toBe(`rgba(138, 154, 91, ${LIT_LINK_ALPHA})`);
    expect(linkColor({ source: "b", target: "c" })).toBe(`rgba(138, 131, 114, ${DIM_LINK_ALPHA})`);
    // The library swaps ids for node-object refs once the simulation runs.
    expect(linkColor({ source: { id: "a" }, target: { id: "b" } })).toBe(
      `rgba(138, 154, 91, ${LIT_LINK_ALPHA})`,
    );
  });

  it("keeps the highlightId halo lit while hovering elsewhere", () => {
    const nodes = [makeNode({ id: "a" }), makeNode({ id: "hl" })];
    render(<KnowledgeGraph3D nodes={nodes} edges={[]} highlightId="hl" />);
    const build = lastProps!.nodeThreeObject as (n: object) => THREE.Group;
    const gHl = build({ ...nodes[1] });
    act(() => {
      (lastProps!.onNodeHover as (n: object | null) => void)({ id: "a" });
    });
    expect(partsOf(gHl).halo.visible).toBe(true);
  });

  it("recenter button shares the 2D affordances and calls zoomToFit", () => {
    const { getByTestId } = render(<KnowledgeGraph3D nodes={[makeNode()]} edges={[]} />);
    const btn = getByTestId("graph-zoom-reset");
    expect(btn.getAttribute("title")).toBe("Reset view"); // globals.css hides by this title on the tutor rail
    fireEvent.click(btn);
    expect(zoomToFitSpy).toHaveBeenCalledWith(400, 40);
  });
});
