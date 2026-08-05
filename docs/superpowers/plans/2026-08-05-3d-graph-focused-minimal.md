# 3D Knowledge Graph "Focused Minimal" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the opt-in 3D knowledge-graph mode to the approved "Focused Minimal" design: matte spheres, always-visible text-sprite labels, hover-focus neighborhood highlighting, and a recenter control.

**Architecture:** All rendering changes live in `frontend/src/components/graph/KnowledgeGraph3D.tsx` plus a new pure-helper module `graph3dHelpers.ts`. We keep `react-force-graph-3d` and switch from accessor-styled default spheres to `nodeThreeObject` custom groups (matte sphere + halo + `three-spritetext` label), registered in a `Map` so hover dim/restore mutates materials imperatively — never rebuilding geometry. Link dimming rides the `linkColor`/`linkWidth` accessors re-keyed on hover state.

**Tech Stack:** React 19 / Next 16, three.js ^0.184, react-force-graph-3d ^1.29, three-spritetext (new), vitest + @testing-library/react (jsdom).

**Spec:** `docs/superpowers/specs/2026-08-05-3d-graph-focused-minimal-design.md`

## Global Constraints

- **Branch/tree**: work on `feat/3d-graph-focused-minimal` in the primary checkout `/home/andresl/Projects/sapling` (worktrees lack `frontend/node_modules`; `next build` breaks on symlinked node_modules). The tree carries unrelated uncommitted flashcard edits (`backend/routes/flashcards.py`, `backend/services/flashcard_import_service.py`, `backend/tests/test_flashcard*`) — NEVER stage or commit them; always `git add` explicit paths.
- **3D stays opt-in**: do not touch `KnowledgeGraph.tsx` (wrapper/toggle), `KnowledgeGraph2D.tsx`, any mount, the landing-page demo, or anything in `backend/`.
- **Colors passed to three.js are always `#rrggbb` hex** — never `hsl(…)` (space-separated HSL silently renders BLACK), never `var(--…)` (three can't resolve CSS vars). Exception: `linkColor` may return `rgba(r, g, b, a)` — three-forcegraph parses the alpha channel.
- **Preserved contracts** (existing tests pin these): sr-only `<ul aria-label="Knowledge graph nodes">` with `graph-node-items`/`graph-node-item`/`graph-node-activate` testids; `onNodeClick` receives the original `GraphNode` prop reference (library-injected `x/y/z/__threeObj/…` never leak); `cooldownTicks` = 120 normally, 0 under `prefers-reduced-motion` or `IS_TEST_MODE`; `dynamic(…, { ssr: false })` for everything touching three.js (client-only state must never flow into SSR-rendered DOM).
- **Bundle**: `three-spritetext` may only be imported from `KnowledgeGraph3D.tsx` (inside the already-lazy client chunk). Never import it (or three) from code that runs server-side.
- **Frontend commands run from `frontend/`**: `npx vitest run <path>` for tests, `npm run lint` before each commit (eslint suppressions are a ratcheted baseline — new code must be clean).
- Commit messages end with:
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`

---

### Task 1: Pure helpers module (`graph3dHelpers.ts`)

Extract the color math that currently lives inside `KnowledgeGraph3D.tsx` into a pure module and add the new helpers the 3D upgrade needs: adjacency, sizing, tier-aware base color, label spec, theme resolution, and the dim constants.

**Files:**
- Create: `frontend/src/components/graph/graph3dHelpers.ts`
- Create: `frontend/src/components/graph/graph3dHelpers.test.ts`
- Modify: `frontend/src/components/graph/KnowledgeGraph3D.tsx` (replace its private `hexToHsl`/`hslToHex`/`shadeFor` with imports; behavior unchanged)

**Interfaces:**
- Consumes: `hashSeed`, `GraphNode`, `GraphEdge` from `@/lib/data`.
- Produces (Tasks 2–4 rely on these exact names):
  - `shadeFor(baseHex: string, nodeId: string): string` (moved verbatim)
  - `mixHex(a: string, b: string, t: number): string`
  - `buildAdjacency(edges: GraphEdge[]): Map<string, Set<string>>`
  - `nodeVal(n: GraphNode): number` / `nodeRadius(n: GraphNode): number`
  - `baseNodeColor(n: GraphNode, theme: GraphTheme): string`
  - `labelSpec(n: GraphNode): { textHeight: number; fontWeight: string }`
  - `type GraphTheme = { ink: string; dim: string; accent: string }`
  - `FALLBACK_THEME: GraphTheme`, `resolveGraphTheme(): GraphTheme`
  - constants `NODE_OPACITY = 0.95`, `DIM_NODE_OPACITY = 0.18`, `DIM_LABEL_OPACITY = 0.12`, `BASE_LINK_ALPHA = 0.45`, `LIT_LINK_ALPHA = 0.85`, `DIM_LINK_ALPHA = 0.06`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/graph/graph3dHelpers.test.ts`:

```ts
// @vitest-environment jsdom
/**
 * Pure-helper tests for the 3D graph's Focused Minimal upgrade.
 * Everything here is deterministic — no three.js, no mocks.
 */
import { describe, it, expect } from "vitest";
import type { GraphNode } from "@/lib/data";
import {
  buildAdjacency,
  mixHex,
  baseNodeColor,
  labelSpec,
  nodeVal,
  nodeRadius,
  resolveGraphTheme,
  FALLBACK_THEME,
  shadeFor,
} from "./graph3dHelpers";

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

describe("buildAdjacency", () => {
  it("maps both directions of every edge", () => {
    const adj = buildAdjacency([{ source: "a", target: "b", strength: 1 }]);
    expect(adj.get("a")?.has("b")).toBe(true);
    expect(adj.get("b")?.has("a")).toBe(true);
    expect(adj.get("c")).toBeUndefined();
  });
});

describe("nodeVal / nodeRadius", () => {
  it("keeps the existing 4..10 mastery scale and 22 for subject roots", () => {
    expect(nodeVal(makeNode({ mastery_score: 0 }))).toBe(4);
    expect(nodeVal(makeNode({ mastery_score: 1 }))).toBe(10);
    expect(nodeVal(makeNode({ is_subject_root: true, mastery_score: 0 }))).toBe(22);
  });
  it("radius follows the library's default sizing (cbrt(val) * 4) so visual scale is unchanged", () => {
    expect(nodeRadius(makeNode({ mastery_score: 0 }))).toBeCloseTo(Math.cbrt(4) * 4);
    expect(nodeRadius(makeNode({ is_subject_root: true }))).toBeCloseTo(Math.cbrt(22) * 4);
  });
});

describe("mixHex", () => {
  it("blends channelwise", () => {
    expect(mixHex("#000000", "#ffffff", 0.5)).toBe("#808080");
    expect(mixHex("#000000", "#ffffff", 0)).toBe("#000000");
    expect(mixHex("#000000", "#ffffff", 1)).toBe("#ffffff");
  });
  it("returns the first color untouched on malformed input", () => {
    expect(mixHex("nope", "#ffffff", 0.5)).toBe("nope");
  });
});

describe("baseNodeColor", () => {
  it("keeps the deterministic per-node shade for explored tiers", () => {
    expect(baseNodeColor(makeNode(), FALLBACK_THEME)).toBe(shadeFor("#88aa55", "n1"));
  });
  it("washes unexplored concept nodes 65% toward the theme dim gray", () => {
    const n = makeNode({ mastery_tier: "unexplored" });
    expect(baseNodeColor(n, FALLBACK_THEME)).toBe(
      mixHex(shadeFor("#88aa55", "n1"), FALLBACK_THEME.dim, 0.65),
    );
  });
  it("never washes subject roots, whatever their tier", () => {
    const n = makeNode({ mastery_tier: "unexplored", is_subject_root: true });
    expect(baseNodeColor(n, FALLBACK_THEME)).toBe(shadeFor("#88aa55", "n1"));
  });
});

describe("labelSpec", () => {
  it("concept labels are small/regular, root labels larger/bold", () => {
    expect(labelSpec(makeNode())).toEqual({ textHeight: 3.2, fontWeight: "400" });
    expect(labelSpec(makeNode({ is_subject_root: true }))).toEqual({
      textHeight: 5,
      fontWeight: "700",
    });
  });
});

describe("resolveGraphTheme", () => {
  it("falls back to the hex constants when CSS vars are absent (jsdom)", () => {
    expect(resolveGraphTheme()).toEqual(FALLBACK_THEME);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `frontend/`): `npx vitest run src/components/graph/graph3dHelpers.test.ts`
Expected: FAIL — "Failed to resolve import ./graph3dHelpers".

- [ ] **Step 3: Write the module**

Create `frontend/src/components/graph/graph3dHelpers.ts`. The `hexToHsl`/`hslToHex`/`shadeFor` bodies are MOVED VERBATIM from `KnowledgeGraph3D.tsx:39-97` (including the hex-not-hsl comment); everything else is new:

```ts
/**
 * Pure helpers for the 3D knowledge graph ("Focused Minimal", spec
 * 2026-08-05). No three.js imports here — everything is deterministic
 * and unit-testable without mocks.
 *
 * Color contract: every function that returns a color returns #rrggbb
 * hex. Three.js's Color.setStyle silently renders space-separated
 * hsl() as BLACK, and cannot resolve CSS var() — resolved hex is the
 * only safe currency (see lib/data.ts).
 */

import { hashSeed, type GraphEdge, type GraphNode } from "@/lib/data";

export const NODE_OPACITY = 0.95;
export const DIM_NODE_OPACITY = 0.18;
export const DIM_LABEL_OPACITY = 0.12;
export const BASE_LINK_ALPHA = 0.45;
export const LIT_LINK_ALPHA = 0.85;
export const DIM_LINK_ALPHA = 0.06;

export type GraphTheme = {
  ink: string; // label text
  dim: string; // dimmed node / unexplored wash
  accent: string; // focus halo + highlighted node
};

// Hex mirrors of the app-shell tokens (globals.css): --ink-600,
// --ink-200, --accent. Used verbatim under SSR/jsdom where
// getComputedStyle can't resolve them.
export const FALLBACK_THEME: GraphTheme = {
  ink: "#3f3b31",
  dim: "#ddd6c6",
  accent: "#8a9a5b",
};

/** Resolve theme tokens to hex once per mount; hex fallbacks otherwise. */
export function resolveGraphTheme(): GraphTheme {
  if (typeof window === "undefined") return FALLBACK_THEME;
  const s = getComputedStyle(document.documentElement);
  const read = (name: string, fb: string) => {
    const raw = s.getPropertyValue(name).trim();
    return /^#[0-9a-f]{6}$/i.test(raw) ? raw : fb;
  };
  return {
    ink: read("--ink-600", FALLBACK_THEME.ink),
    dim: read("--ink-200", FALLBACK_THEME.dim),
    accent: read("--accent", FALLBACK_THEME.accent),
  };
}

/* ── moved verbatim from KnowledgeGraph3D.tsx ─────────────────────── */

function hexToHsl(hex: string): { h: number; s: number; l: number } | null {
  /* [MOVE the exact body from KnowledgeGraph3D.tsx lines 39-58 — do not retype it, cut/paste] */
}

function hslToHex(h: number, s: number, l: number): string {
  /* [MOVE the exact body from KnowledgeGraph3D.tsx lines 60-80] */
}

export function shadeFor(baseHex: string, nodeId: string): string {
  /* [MOVE the exact body from KnowledgeGraph3D.tsx lines 82-97, including the hex-vs-hsl comment] */
}

/* ── new helpers ──────────────────────────────────────────────────── */

/** Channelwise linear blend of two #rrggbb colors; t=0 → a, t=1 → b. */
export function mixHex(a: string, b: string, t: number): string {
  const pa = /^#?([0-9a-f]{6})$/i.exec(a.trim());
  const pb = /^#?([0-9a-f]{6})$/i.exec(b.trim());
  if (!pa || !pb) return a;
  const ca = parseInt(pa[1], 16);
  const cb = parseInt(pb[1], 16);
  const mix = (x: number, y: number) => Math.round(x + (y - x) * t);
  const r = mix((ca >> 16) & 255, (cb >> 16) & 255);
  const g = mix((ca >> 8) & 255, (cb >> 8) & 255);
  const bl = mix(ca & 255, cb & 255);
  return `#${((r << 16) | (g << 8) | bl).toString(16).padStart(6, "0")}`;
}

/** Undirected 1-hop adjacency from the edge list. */
export function buildAdjacency(edges: GraphEdge[]): Map<string, Set<string>> {
  const adj = new Map<string, Set<string>>();
  for (const e of edges) {
    if (!adj.has(e.source)) adj.set(e.source, new Set());
    if (!adj.has(e.target)) adj.set(e.target, new Set());
    adj.get(e.source)!.add(e.target);
    adj.get(e.target)!.add(e.source);
  }
  return adj;
}

/**
 * Same visual scale the old `nodeVal` accessor produced: concepts
 * 4..10 with mastery, subject roots pinned to 22.
 */
export function nodeVal(n: GraphNode): number {
  if (n.is_subject_root) return 22;
  return 4 + (typeof n.mastery_score === "number" ? n.mastery_score : 0) * 6;
}

/**
 * react-force-graph's default sphere radius is cbrt(val) * nodeRelSize
 * (nodeRelSize defaults to 4). Reproducing that mapping keeps our
 * custom spheres exactly the size users see today.
 */
export function nodeRadius(n: GraphNode): number {
  return Math.cbrt(nodeVal(n)) * 4;
}

/**
 * Course-colored deterministic shade; unexplored concept nodes wash
 * 65% toward the theme's dim gray so attention lands on studied
 * material. Subject roots always keep full color.
 */
export function baseNodeColor(n: GraphNode, theme: GraphTheme): string {
  const shaded = shadeFor(n.color || theme.accent, n.id);
  if (n.mastery_tier === "unexplored" && !n.is_subject_root) {
    return mixHex(shaded, theme.dim, 0.65);
  }
  return shaded;
}

export type LabelSpec = { textHeight: number; fontWeight: string };

/** Root labels render larger and bold; concepts small and regular. */
export function labelSpec(n: GraphNode): LabelSpec {
  return n.is_subject_root
    ? { textHeight: 5, fontWeight: "700" }
    : { textHeight: 3.2, fontWeight: "400" };
}
```

The three `[MOVE …]` markers mean literally cut those functions out of `KnowledgeGraph3D.tsx` and paste them here unchanged (add `export` to `shadeFor` only).

- [ ] **Step 4: Rewire `KnowledgeGraph3D.tsx`**

In `KnowledgeGraph3D.tsx`: delete the moved `hexToHsl`/`hslToHex`/`shadeFor` definitions, delete the now-unused `hashSeed` import, and add:

```ts
import { shadeFor } from "./graph3dHelpers";
```

No other change — the component still uses `shadeFor` in its `nodeColor` accessor exactly as before.

- [ ] **Step 5: Run tests to verify they pass**

Run: `npx vitest run src/components/graph/graph3dHelpers.test.ts src/components/graph/KnowledgeGraph3D.test.tsx src/components/graph/KnowledgeGraph3D.testmode.test.tsx`
Expected: ALL PASS (helpers green; both existing component suites untouched-green).

- [ ] **Step 6: Lint and commit**

```bash
npm run lint
git add src/components/graph/graph3dHelpers.ts src/components/graph/graph3dHelpers.test.ts src/components/graph/KnowledgeGraph3D.tsx
git commit -m "refactor(graph-3d): extract pure helpers module for Focused Minimal upgrade

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Custom node objects — matte sphere + halo + always-visible label

Replace accessor-styled default spheres with `nodeThreeObject` groups and register each node's mutable parts in a Map (the registry Tasks 3–4 mutate). Adds the `three-spritetext` dependency.

**Files:**
- Modify: `frontend/package.json` / `package-lock.json` (npm install)
- Modify: `frontend/src/components/graph/KnowledgeGraph3D.tsx`
- Modify: `frontend/src/components/graph/KnowledgeGraph3D.test.tsx`

**Interfaces:**
- Consumes (Task 1): `baseNodeColor`, `nodeRadius`, `labelSpec`, `resolveGraphTheme`, `FALLBACK_THEME`, `NODE_OPACITY`, `GraphTheme`.
- Produces (Tasks 3–4 rely on): component-internal `visualsRef: React.MutableRefObject<Map<string, NodeVisual>>` where `type NodeVisual = { sphereMat: THREE.MeshLambertMaterial; label: SpriteText; halo: THREE.Mesh; baseColor: string }`; `highlightRef`/`hoverRef` string-or-null refs; props `nodeColor`, `nodeVal`, `nodeLabel`, `nodeOpacity`, `nodeResolution` are GONE from `<ForceGraph3D>` (replaced by `nodeThreeObject`).

- [ ] **Step 1: Install the dependency**

```bash
cd frontend && npm install three-spritetext
```

Expected: `three-spritetext` appears in `package.json` dependencies (caret range, matching house style). It pairs with `react-force-graph-3d` (same author) and peer-depends on `three`, already present at ^0.184.

- [ ] **Step 2: Write the failing tests**

In `KnowledgeGraph3D.test.tsx`:

(a) Add a `three-spritetext` mock below the existing `react-force-graph-3d` mock (jsdom has no canvas 2D context, and the real SpriteText paints text onto a canvas texture at construction; extending the real `THREE.Object3D` keeps `group.add(...)` happy):

```tsx
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
```

(b) Add imports at the top:

```tsx
import * as THREE from "three";
import SpriteText from "three-spritetext";
import {
  baseNodeColor,
  labelSpec,
  nodeRadius,
  FALLBACK_THEME,
  NODE_OPACITY,
} from "./graph3dHelpers";
```

(c) Add a shared part-extractor helper next to `makeNode`:

```tsx
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
```

(d) DELETE these now-obsolete tests (their props are removed this task): `"nodeColor returns the brand accent for the highlighted id and a hex shade otherwise"` and `"nodeVal scales 4..10 with mastery_score and pins course-root nodes larger"`. The scale behavior they pinned lives on in `graph3dHelpers.test.ts` (Task 1) and in test (f) below.

(e) Add the composition test:

```tsx
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
```

(f) Add the root-sizing test:

```tsx
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
```

(g) Add the persistent-highlight test:

```tsx
it("highlightId renders that node's halo persistently", () => {
  render(
    <KnowledgeGraph3D nodes={[makeNode({ id: "abc" })]} edges={[]} highlightId="abc" />,
  );
  const build = lastProps!.nodeThreeObject as (n: object) => THREE.Group;
  expect(partsOf(build({ ...makeNode({ id: "abc" }) })).halo.visible).toBe(true);
  expect(partsOf(build({ ...makeNode({ id: "other" }) })).halo.visible).toBe(false);
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `npx vitest run src/components/graph/KnowledgeGraph3D.test.tsx`
Expected: the three new tests FAIL (`nodeThreeObject` is undefined); remaining tests pass.

- [ ] **Step 4: Implement the node objects**

In `KnowledgeGraph3D.tsx`:

(a) Replace the imports block additions:

```tsx
import * as THREE from "three";
import SpriteText from "three-spritetext";
import {
  baseNodeColor,
  labelSpec,
  nodeRadius,
  resolveGraphTheme,
  NODE_OPACITY,
  type GraphTheme,
} from "./graph3dHelpers";
```

(remove the Task-1 `import { shadeFor }` — the component no longer calls it directly).

(b) Inside the component, ABOVE the `graphData` memo, add theme + registry + refs:

```tsx
// Theme tokens resolved to hex once per mount (three.js can't read
// CSS vars). Client-only: this component is dynamic({ssr:false}).
const theme: GraphTheme = React.useMemo(() => resolveGraphTheme(), []);

type NodeVisual = {
  sphereMat: THREE.MeshLambertMaterial;
  label: SpriteText;
  halo: THREE.Mesh;
  baseColor: string;
};
// Mutable registry of every node's restylable parts. Hover/highlight
// mutate materials through this map — never by rebuilding objects.
const visualsRef = React.useRef<Map<string, NodeVisual>>(new Map());
// Refs mirror hover/highlight state so nodeThreeObject (called by the
// library outside React's render) sees current values without being
// re-created — re-creating it would rebuild every node's geometry.
const hoverRef = React.useRef<string | null>(null);
const highlightRef = React.useRef<string | undefined>(highlightId);
highlightRef.current = highlightId;
```

(c) In the `graphData` memo, swap in a fresh registry when the data changes (stale entries from removed nodes must not linger):

```tsx
const graphData = React.useMemo(() => {
  // New data → new registry. Entries repopulate as the library calls
  // nodeThreeObject for each node. (Benign under StrictMode double-
  // invoke: the second call just swaps in another empty map.)
  visualsRef.current = new Map();
  const fgNodes: FG3DNode[] = nodes.map((n) => ({ ...n }));
  const fgLinks: FG3DLink[] = edges.map((e) => ({
    source: e.source,
    target: e.target,
    strength: e.strength,
  }));
  return { nodes: fgNodes, links: fgLinks };
}, [nodes, edges]);
```

(d) DELETE the `nodeColor`, `nodeLabel`, and `nodeVal` callbacks. Add:

```tsx
const nodeThreeObject = React.useCallback(
  (raw: object) => {
    const n = raw as FG3DNode;
    const r = nodeRadius(n);
    const color = baseNodeColor(n, theme);
    const group = new THREE.Group();

    const sphereMat = new THREE.MeshLambertMaterial({
      color,
      transparent: true,
      opacity: NODE_OPACITY,
    });
    group.add(new THREE.Mesh(new THREE.SphereGeometry(r, 24, 24), sphereMat));

    // Focus halo: slightly larger translucent accent sphere, hidden
    // until this node is hovered or is the persistent highlightId.
    const halo = new THREE.Mesh(
      new THREE.SphereGeometry(r * 1.4, 16, 16),
      new THREE.MeshBasicMaterial({
        color: theme.accent,
        transparent: true,
        opacity: 0.28,
        depthWrite: false,
      }),
    );
    halo.visible = n.id === hoverRef.current || n.id === highlightRef.current;
    group.add(halo);

    const spec = labelSpec(n);
    const label = new SpriteText(n.name);
    label.textHeight = spec.textHeight;
    label.fontWeight = spec.fontWeight;
    label.color = theme.ink;
    label.fontFace = '"JetBrains Mono", monospace';
    label.material.transparent = true;
    label.position.set(0, -(r + spec.textHeight + 1.5), 0);
    group.add(label);

    visualsRef.current.set(n.id, { sphereMat, label, halo, baseColor: color });
    return group;
  },
  [theme],
);
```

(e) On the `<ForceGraph3D>` element: remove `nodeLabel`, `nodeColor`, `nodeVal`, `nodeOpacity`, `nodeResolution`; add `nodeThreeObject={nodeThreeObject}`. Everything else (`linkColor`, `linkOpacity`, `linkWidth`, `backgroundColor`, `showNavInfo`, `cooldownTicks`, `enableNodeDrag`, `onNodeClick`) stays as-is this task.

(f) Update the file-header comment: the component now provides custom node objects (matte sphere + halo + SpriteText label) and a mutable visuals registry; the library still owns physics, camera, and picking.

- [ ] **Step 5: Run tests to verify they pass**

Run: `npx vitest run src/components/graph/KnowledgeGraph3D.test.tsx src/components/graph/KnowledgeGraph3D.testmode.test.tsx`
Expected: ALL PASS. (The testmode file needs no new mocks — its stub never invokes `nodeThreeObject`, so no SpriteText is ever constructed.)

- [ ] **Step 6: Lint and commit**

```bash
npm run lint
git add package.json package-lock.json src/components/graph/KnowledgeGraph3D.tsx src/components/graph/KnowledgeGraph3D.test.tsx
git commit -m "feat(graph-3d): matte spheres + always-visible sprite labels + highlight halo

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Hover focus — neighborhood lights up, everything else dims

**Files:**
- Modify: `frontend/src/components/graph/KnowledgeGraph3D.tsx`
- Modify: `frontend/src/components/graph/KnowledgeGraph3D.test.tsx`

**Interfaces:**
- Consumes (Tasks 1–2): `buildAdjacency`, dim constants, `visualsRef`, `hoverRef`, `highlightRef`, `theme`.
- Produces: `<ForceGraph3D>` props `onNodeHover`, hover-keyed `linkColor`/`linkWidth`. Link accessors accept `source`/`target` as either string ids or node objects (the library swaps ids for object refs once the simulation starts).

- [ ] **Step 1: Write the failing tests**

Add to `KnowledgeGraph3D.test.tsx` (extend the top imports with `act` from `@testing-library/react` and `DIM_NODE_OPACITY, DIM_LABEL_OPACITY, LIT_LINK_ALPHA, DIM_LINK_ALPHA, BASE_LINK_ALPHA` from `./graph3dHelpers`):

```tsx
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npx vitest run src/components/graph/KnowledgeGraph3D.test.tsx`
Expected: the three new tests FAIL (`onNodeHover` undefined / base linkColor mismatch); the rest pass.

- [ ] **Step 3: Implement hover focus**

In `KnowledgeGraph3D.tsx`:

(a) Extend the helpers import with `buildAdjacency, BASE_LINK_ALPHA, LIT_LINK_ALPHA, DIM_LINK_ALPHA, DIM_NODE_OPACITY, DIM_LABEL_OPACITY`.

(b) Below the `graphData` memo add:

```tsx
const adjacency = React.useMemo(() => buildAdjacency(edges), [edges]);
// hoverId lives in state ONLY to re-key the link accessors below; the
// node/label/halo restyle happens imperatively via visualsRef.
const [hoverId, setHoverId] = React.useState<string | null>(null);

const applyFocus = React.useCallback(
  (hover: string | null) => {
    hoverRef.current = hover;
    const neighbors = hover ? adjacency.get(hover) : undefined;
    for (const [id, v] of visualsRef.current) {
      const lit = !hover || id === hover || (neighbors?.has(id) ?? false);
      v.sphereMat.color.set(lit ? v.baseColor : theme.dim);
      v.sphereMat.opacity = lit ? NODE_OPACITY : DIM_NODE_OPACITY;
      v.label.material.opacity = lit ? 1 : DIM_LABEL_OPACITY;
      v.halo.visible = id === hover || id === highlightRef.current;
    }
  },
  [adjacency, theme],
);

const handleNodeHover = React.useCallback(
  (raw: object | null) => {
    const id = raw ? (raw as FG3DNode).id : null;
    setHoverId(id);
    applyFocus(id);
  },
  [applyFocus],
);

// Re-assert focus when highlightId/adjacency/theme change (e.g. the
// tutor moves the discussed node while the user isn't hovering).
React.useEffect(() => {
  applyFocus(hoverRef.current);
}, [applyFocus, highlightId]);
```

(c) Replace the static `linkColor`/`linkWidth` props with hover-keyed accessors (defined above the return):

```tsx
const linkEndId = (v: unknown): string =>
  typeof v === "object" && v !== null ? (v as FG3DNode).id : (v as string);

const linkColor = React.useCallback(
  (l: object) => {
    const link = l as FG3DLink;
    if (!hoverId) return `rgba(138, 131, 114, ${BASE_LINK_ALPHA})`;
    const lit = linkEndId(link.source) === hoverId || linkEndId(link.target) === hoverId;
    // Lit links take the sage accent (rgb of #8a9a5b); dimmed links
    // fade to near-invisible warm gray.
    return lit
      ? `rgba(138, 154, 91, ${LIT_LINK_ALPHA})`
      : `rgba(138, 131, 114, ${DIM_LINK_ALPHA})`;
  },
  [hoverId],
);

const linkWidth = React.useCallback(
  (l: object) => {
    const link = l as FG3DLink;
    const base = 0.4 + (link.strength || 0) * 0.6;
    if (!hoverId) return base;
    const lit = linkEndId(link.source) === hoverId || linkEndId(link.target) === hoverId;
    return lit ? base + 0.6 : base;
  },
  [hoverId],
);
```

`FG3DLink`'s `source`/`target` types widen to `string | FG3DNode`. `linkEndId` can live at module scope.

(d) On `<ForceGraph3D>`: `linkColor={linkColor}`, `linkWidth={linkWidth}`, add `onNodeHover={handleNodeHover}`. Keep `linkOpacity={0.4}` exactly as-is — three-forcegraph multiplies it with the color's alpha channel, and keeping it constant preserves today's baseline link look.

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/components/graph/KnowledgeGraph3D.test.tsx src/components/graph/KnowledgeGraph3D.testmode.test.tsx`
Expected: ALL PASS.

- [ ] **Step 5: Lint and commit**

```bash
npm run lint
git add src/components/graph/KnowledgeGraph3D.tsx src/components/graph/KnowledgeGraph3D.test.tsx
git commit -m "feat(graph-3d): hover-focus — 1-hop neighborhood lights, rest dims

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Recenter control (zoomToFit) via ref-forwarding wrapper

`next/dynamic` doesn't forward refs, so the dynamic loader wraps the library component to accept the ref as a plain `fgRef` prop. The button reuses the 2D reset control's `title="Reset view"` — that exact title is what `.learn-map-rail button[title="Reset view"]` in `globals.css` keys on to hide the control on the tutor sidebar — and its `graph-zoom-reset` testid (only one graph implementation mounts at a time, so shared testids never collide; same principle as the sr-only seam).

**Files:**
- Modify: `frontend/src/components/graph/KnowledgeGraph3D.tsx`
- Modify: `frontend/src/components/graph/KnowledgeGraph3D.test.tsx`
- Modify: `frontend/src/components/graph/KnowledgeGraph3D.testmode.test.tsx` (mock parity only)

**Interfaces:**
- Consumes: `ForceGraphMethods`, `ForceGraphProps` types exported by `react-force-graph-3d` (type-only imports — erased at compile, no SSR/bundle effect).
- Produces: `<button data-testid="graph-zoom-reset" title="Reset view">` calling `zoomToFit(400, 40)`.

- [ ] **Step 1: Write the failing test**

In `KnowledgeGraph3D.test.tsx`, replace the `react-force-graph-3d` mock so the stub exposes an imperative handle (declare `let zoomToFitSpy = vi.fn();` next to `let lastProps…`, reset it in `beforeEach` with `zoomToFitSpy = vi.fn();`):

```tsx
vi.mock("react-force-graph-3d", () => ({
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  default: React.forwardRef((props: any, ref: React.Ref<unknown>) => {
    lastProps = props;
    React.useImperativeHandle(ref, () => ({ zoomToFit: zoomToFitSpy }));
    return null;
  }),
}));
```

Add the test:

```tsx
it("recenter button shares the 2D affordances and calls zoomToFit", () => {
  const { getByTestId } = render(<KnowledgeGraph3D nodes={[makeNode()]} edges={[]} />);
  const btn = getByTestId("graph-zoom-reset");
  expect(btn.getAttribute("title")).toBe("Reset view"); // globals.css hides by this title on the tutor rail
  fireEvent.click(btn);
  expect(zoomToFitSpy).toHaveBeenCalledWith(400, 40);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/components/graph/KnowledgeGraph3D.test.tsx`
Expected: new test FAILS ("Unable to find an element by: [data-testid=graph-zoom-reset]"); all others pass.

- [ ] **Step 3: Implement the wrapper + button**

In `KnowledgeGraph3D.tsx`:

(a) Replace the dynamic import with the ref-bridging wrapper:

```tsx
import type { ForceGraphMethods, ForceGraphProps } from "react-force-graph-3d";

// next/dynamic can't forward refs, and we need the instance for
// zoomToFit. The loader wraps the lib component so the ref rides in as
// a regular `fgRef` prop. Type-only imports above are erased at
// compile time — nothing here reaches the server bundle.
type FGRefProp = { fgRef?: React.Ref<ForceGraphMethods | undefined> };
const ForceGraph3D = dynamic(
  () =>
    import("react-force-graph-3d").then((m) => {
      const FG = m.default;
      const WithRef = ({ fgRef, ...rest }: ForceGraphProps & FGRefProp) => (
        <FG {...rest} ref={fgRef} />
      );
      return WithRef;
    }),
  { ssr: false, loading: () => null },
);
```

(b) In the component: `const fgRef = React.useRef<ForceGraphMethods | undefined>(undefined);`, pass `fgRef={fgRef}` on `<ForceGraph3D>`, and add the button as a sibling of the sr-only `<ul>` inside the wrapper div:

```tsx
<button
  type="button"
  data-testid="graph-zoom-reset"
  className="btn btn--ghost btn--sm"
  title="Reset view"
  aria-label="Reset view"
  onClick={() => fgRef.current?.zoomToFit(400, 40)}
  style={{
    position: "absolute",
    right: 12,
    bottom: 12,
    padding: "2px 8px",
    fontSize: 10,
    background: "var(--bg-panel)",
    border: "1px solid var(--border)",
    borderRadius: "var(--r-sm)",
    boxShadow: "var(--shadow-sm)",
    zIndex: 5,
  }}
>
  ⟲
</button>
```

(c) In `KnowledgeGraph3D.testmode.test.tsx`, update the `react-force-graph-3d` mock to the same `React.forwardRef` shape (no spy needed — `() => ({ zoomToFit: () => {} })`) so React doesn't warn about a ref on a plain function component.

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/components/graph/`
Expected: ALL PASS across all graph test files.

- [ ] **Step 5: Lint and commit**

```bash
npm run lint
git add src/components/graph/KnowledgeGraph3D.tsx src/components/graph/KnowledgeGraph3D.test.tsx src/components/graph/KnowledgeGraph3D.testmode.test.tsx
git commit -m "feat(graph-3d): recenter control via ref-forwarding dynamic wrapper

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Full verification — suites, build, E2E lanes, visual pass

Frontend-only change, but the repo's pre-merge gate is the full set. Run everything from the primary checkout.

**Files:** none created; this task is verification + any fixes it forces.

- [ ] **Step 1: Full frontend unit suite + lint**

```bash
cd /home/andresl/Projects/sapling/frontend && npx vitest run && npm run lint
```

Expected: ALL PASS, lint clean. Read the pass/fail counts — never trust exit code alone.

- [ ] **Step 2: Production build (bundle guard)**

```bash
cd /home/andresl/Projects/sapling/frontend && npm run build
```

Expected: build succeeds. `three-spritetext` must appear only in client chunks (it's imported solely from the `dynamic(ssr:false)` component — if the build fails on worker bundle size, something imported it statically; fix the import path, do not raise limits). The authoritative CF Workers build check runs on the PR — watch it there too.

- [ ] **Step 3: Backend hermetic suite (cheap insurance, expected untouched)**

```bash
cd /home/andresl/Projects/sapling/backend && venv/bin/python -m pytest tests/ -q
```

Expected: same green as main; this change touches no backend file.

- [ ] **Step 4: One flock'd E2E cycle (Chapter 1 + oracles)**

The stack is a machine singleton — ONE flock invocation wraps the whole up→test→down cycle. `make e2e-up` does NOT export the function-mode env; copy the exact `SAPLING_MODEL_MODE` / `SAPLING_FUNCTION_HANDLERS` values from `.github/workflows/e2e.yml` into the environment first (read that file; do not guess values). Remove stale red-check artifacts before running (`rm -rf frontend/test-results frontend/e2e/results` if present).

```bash
cd /home/andresl/Projects/sapling
flock /tmp/claude-1000/sapling-e2e-stack.lock bash -c '
  set -e
  export SAPLING_MODEL_MODE=<value from e2e.yml>
  export SAPLING_FUNCTION_HANDLERS=<value from e2e.yml>
  make e2e-up
  rc=0
  (cd frontend && npx playwright test) || rc=$?
  (cd backend && venv/bin/python -m e2e_oracles) || rc=$?
  make e2e-down
  exit $rc
'
```

Expected: Playwright journeys green (including `graph.spec.ts` — its assertions ride the unchanged sr-only seam), oracles exit 0. ALWAYS tear down, even on failure.

- [ ] **Step 5: Manual visual pass**

With the stack up (inside a flock'd session, or `make e2e-up` + browse + `make e2e-down` under one flock): sign in as the seeded student, then on `/tree`, the dashboard panel, and the tutor sidebar flip the `2D/3D` toggle and check against the spec: matte spheres, labels readable at rest, hover lights the neighborhood and dims the rest, halo on hover + on the tutor's highlighted node, ⌖ recenter works on /tree and dashboard and is HIDDEN on the tutor sidebar, reduced-motion (OS setting) freezes layout. Screenshot for the PR.

- [ ] **Step 6: Push and open the PR**

```bash
git push -u origin feat/3d-graph-focused-minimal
gh pr create --title "feat(graph-3d): Focused Minimal visual upgrade — labels, hover focus, recenter" --body "$(cat <<'EOF'
## Summary
- 3D graph mode grows from bare spheres into the approved Focused Minimal design (spec: docs/superpowers/specs/2026-08-05-3d-graph-focused-minimal-design.md)
- matte spheres + always-visible SpriteText labels (roots bold), unexplored tier washed toward warm gray
- hover-focus: 1-hop neighborhood lit, rest dimmed; sage halo on hovered + tutor-highlighted nodes
- ⌖ recenter (zoomToFit) sharing the 2D control's title/testid (auto-hidden on tutor rail)
- new dep three-spritetext, client-chunk only; 3D stays opt-in behind the existing toggle

## Test plan
- [ ] graph3dHelpers unit tests + rewritten KnowledgeGraph3D component tests
- [ ] full frontend suite, lint, next build
- [ ] flock'd E2E cycle: Chapter 1 journeys + oracles green
- [ ] manual visual pass on /tree, dashboard, tutor sidebar (screenshots attached)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Then run `/code-review` on the PR before merging (review gates the merge — never after).

---

## Self-review notes (already applied)

- **Spec coverage**: visual spec → Task 2 (spheres/labels/halo/unexplored wash), hover focus + highlightId → Task 3, recenter + sidebar hiding → Task 4, transparent background / cooldownTicks / drag-off / click contract → untouched by design (Global Constraints), testing section → per-task TDD + Task 5 gate, bundle constraint → Task 2 install + Task 5 build check.
- **Deviation from spec, intentional**: the spec said the recenter button "carries the same class" as the 2D control; the actual `globals.css` rule keys on `title="Reset view"`, so the button carries that title (plus the shared testid). Spec's intent (hidden on tutor rail) is preserved.
- **Type consistency**: `NodeVisual`, `visualsRef`, `hoverRef`/`highlightRef`, `applyFocus`, `linkEndId`, and all helper names/signatures match across Tasks 1–4.
