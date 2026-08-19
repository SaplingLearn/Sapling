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
  hexToRgbTriplet,
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

// Exactly the props these tests read. Spelling them out is what lets the
// capture be a precise type instead of the `Record<string, any>` it replaces
// (and that type's @typescript-eslint/no-explicit-any suppression). No index
// signature on purpose: `forwardRef` runs its props type through
// `PropsWithoutRef`, and `Omit` collapses an index-signature type down to
// just the index signature, losing every named key.
type CapturedProps = {
  graphData: {
    nodes: (GraphNode & { x?: number; y?: number; z?: number })[];
    links: { source: unknown; target: unknown; strength: number }[];
  };
  nodeThreeObject: (n: object) => THREE.Group;
  linkColor: (l: object) => string;
  linkWidth: (l: object) => number;
  onNodeClick: (raw: object) => void;
  onNodeHover: (raw: object | null) => void;
  onEngineStop: () => void;
  cooldownTicks: number;
  warmupTicks: number;
};

// Capture the props the component passes to ForceGraph3D so tests can
// drive its callbacks. Reset in beforeEach.
let lastProps: CapturedProps | null = null;
let zoomToFitSpy = vi.fn();
// Drives the auto-fit's bbox-stabilization poll (see handleEngineStop in
// KnowledgeGraph3D.tsx) — tests configure a per-call return sequence via
// `getGraphBboxMock.mockReturnValueOnce(...)`/`mockReturnValue(...)`.
let getGraphBboxMock = vi.fn<() => unknown>();

// jsdom has no canvas 2D context, and the real SpriteText paints text
// onto a canvas texture at construction; extending the real
// THREE.Object3D keeps `group.add(...)` happy.
vi.mock("three-spritetext", async () => {
  const three = await vi.importActual<typeof import("three")>("three");
  // Mirrors the real (text, textHeight, color) constructor. The component
  // passes all three there rather than through setters on purpose: every
  // three-spritetext setter re-runs _genCanvas, so the setter form rasterised
  // each label five times.
  class SpriteTextMock extends three.Object3D {
    text: string;
    textHeight: number;
    color: string;
    fontFace = "";
    fontWeight = "";
    material = { opacity: 1, transparent: false };
    constructor(text: string, textHeight = 2, color = "") {
      super();
      this.text = text;
      this.textHeight = textHeight;
      this.color = color;
    }
  }
  return { default: SpriteTextMock };
});

vi.mock("react-force-graph-3d", () => ({
  // A NAMED function inside forwardRef so the component has a display name,
  // and props are recorded in an EFFECT rather than in the render body:
  // reassigning a module-scope variable during render is a render-phase side
  // effect (react-hooks/globals) that tears under a discarded concurrent
  // render. Testing Library's render/rerender/act all flush passive effects
  // before returning, so tests still observe the props synchronously.
  default: React.forwardRef(function ForceGraph3DMock(
    props: CapturedProps,
    ref: React.Ref<unknown>,
  ) {
    React.useImperativeHandle(ref, () => ({
      zoomToFit: zoomToFitSpy,
      getGraphBbox: getGraphBboxMock,
    }));
    React.useEffect(() => {
      lastProps = props;
    });
    return null;
  }),
}));

// next/dynamic is used to client-only-load react-force-graph-3d; the
// shared passthrough renders the (hoisted, already-resolved) mock module
// synchronously.
vi.mock("next/dynamic", async () =>
  (await import("@/test-utils/mockNextDynamic")).mockNextDynamicModule(),
);

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
  getGraphBboxMock = vi.fn();
  installDefaultMatchMedia();
});

/** Capture rAF callbacks instead of letting jsdom schedule them on a timer
 * (mirrors src/components/marketing/graph/KnowledgeGraphDemo.test.tsx). */
function captureAnimationFrames() {
  const queue: FrameRequestCallback[] = [];
  // Ids handed out per scheduled frame, 1-based. The component stores the
  // most recent one in pollRafIdRef so its unmount cleanup can cancel it —
  // `ids` plus the `cancel` spy is what lets a test assert that.
  const ids: number[] = [];
  const raf = vi
    .spyOn(window, "requestAnimationFrame")
    .mockImplementation((cb: FrameRequestCallback) => {
      const id = queue.push(cb);
      ids.push(id);
      return id;
    });
  const cancel = vi.spyOn(window, "cancelAnimationFrame").mockImplementation(() => {});
  return {
    queue,
    ids,
    cancel,
    /** Run the next queued frame inside `act`. */
    step() {
      const cb = queue.shift();
      expect(cb, "expected a queued animation frame").toBeTruthy();
      act(() => cb!(0));
    },
    restore() {
      raf.mockRestore();
      cancel.mockRestore();
    },
  };
}

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

  it("sets cooldownTicks to 0 and warmupTicks to 200 when prefers-reduced-motion is reduce", () => {
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
    // warmupTicks mirrors KnowledgeGraph2D's sim.tick(200) precedent: run
    // the simulation to a real settled layout synchronously instead of
    // skipping it outright under reduced motion.
    expect(lastProps!.warmupTicks).toBe(200);
  });

  it("uses the full animated cooldown and no synchronous warmup by default (no reduced-motion, not test mode)", () => {
    // installDefaultMatchMedia() (beforeEach) already reports no
    // reduced-motion preference, and this file never stubs
    // NEXT_PUBLIC_TEST_MODE, so IS_TEST_MODE is false here — this is the
    // real animated path a live user with no accessibility preference set
    // actually sees.
    render(<KnowledgeGraph3D nodes={[makeNode()]} edges={[]} />);

    expect(lastProps).not.toBeNull();
    expect(lastProps!.cooldownTicks).toBe(120);
    expect(lastProps!.warmupTicks).toBe(0);
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
    // Resting and dimmed edges are both built from theme.link (--ink-400),
    // never from a hand-copied rgb triplet (final-review P3).
    const baseRgb = hexToRgbTriplet(FALLBACK_THEME.link);
    expect(linkColor({ source: "a", target: "b" })).toBe(`rgba(${baseRgb}, ${BASE_LINK_ALPHA})`);

    act(() => {
      (lastProps!.onNodeHover as (n: object | null) => void)({ id: "a" });
    });

    // Lit links derive from theme.accent (FALLBACK_THEME under jsdom) via
    // hexToRgbTriplet — the same single source the focus halo uses, not a
    // second hardcoded rgb copy that can drift from it (final-review fix:
    // production used to render a forest halo next to sage-colored edges).
    const litRgb = hexToRgbTriplet(FALLBACK_THEME.accent);
    linkColor = lastProps!.linkColor as (l: object) => string; // re-keyed accessor
    expect(linkColor({ source: "a", target: "b" })).toBe(`rgba(${litRgb}, ${LIT_LINK_ALPHA})`);
    expect(linkColor({ source: "b", target: "c" })).toBe(`rgba(${baseRgb}, ${DIM_LINK_ALPHA})`);
    // The library swaps ids for node-object refs once the simulation runs.
    expect(linkColor({ source: { id: "a" }, target: { id: "b" } })).toBe(
      `rgba(${litRgb}, ${LIT_LINK_ALPHA})`,
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
    // Default matchMedia (beforeEach) reports no reduced-motion preference,
    // and this file never stubs NEXT_PUBLIC_TEST_MODE — the real animated
    // path a live user with no accessibility preference set actually sees.
    // Padding is unified to 60 across both zoomToFit call sites (auto-fit
    // and this button) — it used to be 40 here (final-review ride-along).
    const { getByTestId } = render(<KnowledgeGraph3D nodes={[makeNode()]} edges={[]} />);
    const btn = getByTestId("graph-zoom-reset");
    expect(btn.getAttribute("title")).toBe("Reset view"); // globals.css hides by this title on the tutor rail
    fireEvent.click(btn);
    expect(zoomToFitSpy).toHaveBeenCalledWith(400, 60);
  });

  it("recenter button fires an instant (0ms) fit under prefers-reduced-motion", () => {
    // Round: this is a system-initiated camera fly even though the user
    // clicked the button — under reduced motion an animated 400ms fly is
    // itself a motion violation, so the duration must zero out exactly
    // like the auto-fit's gating.
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

    const { getByTestId } = render(<KnowledgeGraph3D nodes={[makeNode()]} edges={[]} />);
    const btn = getByTestId("graph-zoom-reset");
    fireEvent.click(btn);
    expect(zoomToFitSpy).toHaveBeenCalledWith(0, 60);
  });

  it("auto-fits the camera once the graph bbox stabilizes across animation frames (onEngineStop)", () => {
    // Pins the real mechanism (Task 5 round 2, #518 3D graph camera-framing
    // bug): onEngineStop fires before the current tick's node positions are
    // written to the scene, so getGraphBbox() reads a stale/placeholder
    // value for the first frame or two — fitting on that stale value
    // produces a camera far too close once the real layout lands. The fix
    // polls on requestAnimationFrame until two consecutive bbox reads agree
    // before calling zoomToFit, rather than fitting synchronously or after
    // a fixed delay.
    const staleBbox = { x: [-1, 1], y: [-1, 1], z: [-1, 1] };
    const settledBbox = { x: [-50, 60], y: [-30, 40], z: [-40, 20] };
    getGraphBboxMock
      .mockReturnValueOnce(staleBbox) // frame 1: still the pre-layout placeholder
      .mockReturnValueOnce(settledBbox) // frame 2: real layout has landed, differs from frame 1
      .mockReturnValue(settledBbox); // frame 3+: stable — matches the previous read

    const raf = captureAnimationFrames();
    render(<KnowledgeGraph3D nodes={[makeNode()]} edges={[]} />);
    expect(lastProps).not.toBeNull();
    const onEngineStop = lastProps!.onEngineStop as () => void;
    expect(typeof onEngineStop).toBe("function");

    act(() => onEngineStop());
    expect(zoomToFitSpy).not.toHaveBeenCalled(); // schedules a frame, doesn't fit synchronously

    raf.step(); // frame 1 reads staleBbox — no prior read to compare against yet
    expect(zoomToFitSpy).not.toHaveBeenCalled();

    raf.step(); // frame 2 reads settledBbox — differs from frame 1, still not stable
    expect(zoomToFitSpy).not.toHaveBeenCalled();

    raf.step(); // frame 3 reads settledBbox again — matches frame 2: stable, fit now
    expect(zoomToFitSpy).toHaveBeenCalledTimes(1);
    expect(zoomToFitSpy).toHaveBeenCalledWith(400, 60);
    expect(getGraphBboxMock).toHaveBeenCalledTimes(3);

    // Guarded to fire only once per dataset — a second settle (e.g. the
    // library re-triggering onEngineStop, or React re-invoking the
    // memoized callback) must not re-fit the camera out from under a
    // user who has since panned/zoomed, and must not schedule new frames.
    const framesScheduledBeforeSecondCall = raf.queue.length;
    act(() => onEngineStop());
    expect(raf.queue.length).toBe(framesScheduledBeforeSecondCall);
    expect(zoomToFitSpy).toHaveBeenCalledTimes(1);

    raf.restore();
  });

  it("auto-fit stops polling and fits anyway once the frame cap is hit, if the bbox never stabilizes", () => {
    // Safety net: a bbox that keeps changing every frame (never two
    // consecutive equal reads) must not poll forever — it still fits once
    // the frame cap trips, using whatever bbox was last read.
    //
    // A monotonic counter, not Math.random(): random values can repeat and
    // stabilize the poll early, and the read-count assertion below pins the
    // stop to the cap itself — with only "zoomToFit fired once", a MAX_FRAMES
    // regression from 60 to 2 would still pass.
    const MAX_FRAMES = 60; // mirrors handleEngineStop's own cap
    let bboxCounter = 0;
    getGraphBboxMock.mockImplementation(() => ({ x: [0, ++bboxCounter], y: [0, 0], z: [0, 0] }));

    const raf = captureAnimationFrames();
    render(<KnowledgeGraph3D nodes={[makeNode()]} edges={[]} />);
    const onEngineStop = lastProps!.onEngineStop;

    act(() => onEngineStop());
    // Drain every frame the poll schedules (each step may enqueue the next
    // one) until the queue empties — bounded well above the component's own
    // internal frame cap so the test fails loudly instead of hanging if the
    // cap regresses upward.
    for (let i = 0; i < MAX_FRAMES * 4 && raf.queue.length > 0; i++) {
      raf.step();
    }
    expect(zoomToFitSpy).toHaveBeenCalledTimes(1);
    expect(zoomToFitSpy).toHaveBeenCalledWith(400, 60);
    // Exactly one bbox read per frame and exactly MAX_FRAMES frames: the poll
    // stopped at the cap, not at an accidental early stabilization.
    expect(getGraphBboxMock).toHaveBeenCalledTimes(MAX_FRAMES);
    expect(raf.queue.length).toBe(0); // no frame scheduled after the cap-triggered fit

    raf.restore();
  });

  it("cancels the pending bbox-poll frame on unmount", () => {
    // The poll spans up to MAX_FRAMES (~1s at 60fps). Unmounting mid-poll
    // must cancel the scheduled frame rather than leave it to fire against a
    // torn-down instance — pollRafIdRef exists solely so the unmount cleanup
    // can do this, and nothing asserted it until now.
    getGraphBboxMock.mockReturnValue({ x: [0, 1], y: [0, 1], z: [0, 1] });

    const raf = captureAnimationFrames();
    const { unmount } = render(<KnowledgeGraph3D nodes={[makeNode()]} edges={[]} />);
    act(() => lastProps!.onEngineStop());

    // One frame scheduled and never run — the poll is mid-flight.
    expect(raf.ids).toEqual([1]);
    expect(raf.cancel).not.toHaveBeenCalled();

    unmount();

    expect(raf.cancel).toHaveBeenCalledTimes(1);
    expect(raf.cancel).toHaveBeenCalledWith(raf.ids[0]);

    raf.restore();
  });

  it("abandons a stale bbox poll when the dataset changes mid-poll (epoch guard)", () => {
    // Round 3: the bbox-stabilization poll spans multiple frames (up to
    // MAX_FRAMES). If nodes/edges change while an old poll is mid-flight,
    // the stale closure must not fire zoomToFit and clobber the fresh
    // poll's correct fit for the new dataset. A bbox that changes on every
    // read never spontaneously stabilizes, so the stale poll only ever
    // stops via either the epoch guard (fixed) or the MAX_FRAMES safety
    // net (unfixed — proves this test is a real regression check, not a
    // tautology).
    let bboxCounter = 0;
    getGraphBboxMock.mockImplementation(() => ({ x: [0, ++bboxCounter], y: [0, 0], z: [0, 0] }));

    const raf = captureAnimationFrames();
    const nodesA = [makeNode({ id: "a" })];
    const nodesB = [makeNode({ id: "b" })];
    const { rerender } = render(<KnowledgeGraph3D nodes={nodesA} edges={[]} />);
    const onEngineStopA = lastProps!.onEngineStop as () => void;

    act(() => onEngineStopA());
    expect(raf.queue.length).toBe(1); // dataset A's poll scheduled its first frame

    raf.step(); // frame 1 of A's poll — nothing to compare yet, schedules frame 2
    expect(zoomToFitSpy).not.toHaveBeenCalled();
    expect(raf.queue.length).toBe(1);

    // Dataset change: a new nodes array re-triggers the [nodes, edges]
    // reset effect, bumping pollEpochRef out from under A's in-flight poll.
    rerender(<KnowledgeGraph3D nodes={nodesB} edges={[]} />);

    // Drive every remaining frame the STALE (dataset-A) poll scheduled,
    // bounded well above MAX_FRAMES so a regression fails loudly instead
    // of hanging.
    for (let i = 0; i < 100 && raf.queue.length > 0; i++) {
      raf.step();
    }

    // The stale poll belonged to dataset A and must never fire zoomToFit —
    // not even via the MAX_FRAMES safety net — once the epoch moved on.
    expect(zoomToFitSpy).not.toHaveBeenCalled();

    raf.restore();
  });

  it("keeps the linkWidth accessor identity stable across a hover", () => {
    // three-forcegraph treats linkWidth as object-invalidating for links:
    // `if (state._flushObjects || hasAnyPropChanged(['linkThreeObject',
    // 'linkThreeObjectExtend', 'linkWidth'])) state.linkDataMapper.clear();`
    // clear() is digest([]) — it scene.remove()s and disposes EVERY link
    // mesh (all CylinderGeometry here, since the widths are never zero) and
    // rebuilds them all. A hoverId-keyed accessor handed the library a new
    // identity on every pointer enter AND leave, i.e. two full teardowns of
    // the link layer per hover. The spec asks for "no per-hover geometry
    // rebuilds".
    const nodes = [makeNode({ id: "a" }), makeNode({ id: "b" }), makeNode({ id: "c" })];
    const edges: GraphEdge[] = [
      { source: "a", target: "b", strength: 1 },
      { source: "b", target: "c", strength: 1 },
    ];
    render(<KnowledgeGraph3D nodes={nodes} edges={edges} />);

    const linkWidth = lastProps!.linkWidth;
    const linkColorBefore = lastProps!.linkColor;
    const resting = linkWidth({ source: "a", target: "b", strength: 1 });

    act(() => {
      lastProps!.onNodeHover({ id: "a" });
    });

    // Same function object: the library sees no linkWidth change at all.
    expect(lastProps!.linkWidth).toBe(linkWidth);
    // linkColor's identity DID change — that is what triggers the link
    // digest whose onUpdateObj re-reads the width accessor per link, so
    // widths still follow the hover without the clear().
    expect(lastProps!.linkColor).not.toBe(linkColorBefore);
    expect(linkWidth({ source: "a", target: "b", strength: 1 })).toBeCloseTo(resting + 0.6);
    expect(linkWidth({ source: "b", target: "c", strength: 1 })).toBeCloseTo(resting);

    act(() => {
      lastProps!.onNodeHover(null);
    });

    expect(lastProps!.linkWidth).toBe(linkWidth);
    expect(linkWidth({ source: "a", target: "b", strength: 1 })).toBeCloseTo(resting);
  });

  it("nodeThreeObject applies the live focus state to nodes it builds mid-hover", () => {
    // The composition tests above build node objects BEFORE driving
    // onNodeHover, which is the opposite of the real order. In production a
    // dataset refresh while the pointer rests on a node (a tutor
    // graph_update refreshing the Learn rail, a /tree filter change) makes
    // the library rebuild every node object with hover already active, so
    // nodeThreeObject must hand back already-focused objects — otherwise the
    // hovered node keeps its halo while nothing dims, until the pointer
    // moves. The [applyFocus, highlightId] re-assert effect cannot cover it:
    // it runs at commit, before the library rebuilds.
    const nodes = [makeNode({ id: "a" }), makeNode({ id: "b" }), makeNode({ id: "c" })];
    const edges: GraphEdge[] = [{ source: "a", target: "b", strength: 1 }];
    render(<KnowledgeGraph3D nodes={nodes} edges={edges} highlightId="c" />);

    act(() => {
      lastProps!.onNodeHover({ id: "a" });
    });

    // Rebuild AFTER the hover landed — the order the library actually uses.
    const build = lastProps!.nodeThreeObject;
    const gA = partsOf(build({ ...nodes[0] }));
    const gB = partsOf(build({ ...nodes[1] }));
    const gC = partsOf(build({ ...nodes[2] }));

    expect((gA.sphere.material as THREE.MeshLambertMaterial).opacity).toBeCloseTo(NODE_OPACITY);
    expect(gA.halo.visible).toBe(true); // hovered
    // Neighbor stays lit, no halo.
    expect((gB.sphere.material as THREE.MeshLambertMaterial).opacity).toBeCloseTo(NODE_OPACITY);
    expect(gB.halo.visible).toBe(false);
    // The stranger is born dimmed — sphere color, sphere opacity and label
    // opacity all applied, not just the halo.
    const cMat = gC.sphere.material as THREE.MeshLambertMaterial;
    expect(cMat.opacity).toBeCloseTo(DIM_NODE_OPACITY);
    expect(`#${cMat.color.getHexString()}`).toBe(FALLBACK_THEME.dim);
    expect(gC.label.material.opacity).toBeCloseTo(DIM_LABEL_OPACITY);
    // ...while still keeping its persistent highlightId halo, which also
    // pins that highlightRef is mirrored (in an effect) before the library
    // ever calls nodeThreeObject.
    expect(gC.halo.visible).toBe(true);
  });

  it("moves the persistent halo when highlightId changes on a live graph", () => {
    // highlightId is mirrored onto highlightRef in an EFFECT rather than
    // assigned in the render body (react-hooks/refs). The useRef initializer
    // covers first mount, so only a CHANGE while mounted exercises the
    // mirror — which is exactly what the tutor does when it starts
    // discussing a different node mid-conversation. This also pins the
    // ordering: the re-assert effect below is declared after the mirror
    // effect, so it must see the new value, not the old one.
    const nodes = [makeNode({ id: "a" }), makeNode({ id: "b" })];
    // Same array identities on both renders: a caller handing over fresh
    // literals is a dataset change as far as the component is concerned, and
    // that path (full rebuild) is covered by the mid-hover rebuild test
    // above. Here only highlightId moves.
    const edges: GraphEdge[] = [];
    const { rerender } = render(
      <KnowledgeGraph3D nodes={nodes} edges={edges} highlightId="a" />,
    );
    const build = lastProps!.nodeThreeObject;
    const gA = partsOf(build({ ...nodes[0] }));
    const gB = partsOf(build({ ...nodes[1] }));
    expect(gA.halo.visible).toBe(true);
    expect(gB.halo.visible).toBe(false);

    rerender(<KnowledgeGraph3D nodes={nodes} edges={edges} highlightId="b" />);

    // Same objects — a highlightId change must not rebuild geometry, it must
    // restyle what is already in the scene.
    expect(lastProps!.nodeThreeObject).toBe(build);
    expect(gA.halo.visible).toBe(false);
    expect(gB.halo.visible).toBe(true);
  });
});
