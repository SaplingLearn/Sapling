# Feature · KnowledgeGraph (Cross-Cutting)

> Covers: `src/components/KnowledgeGraph.tsx` (453 lines). A d3-force-simulation-driven SVG graph used by `/dashboard`, `/learn`, `/tree`, and `/social` (RoomOverview). This is the visual anchor of the whole product — preserving its look and feel is non-negotiable for the rebuild.

---

## 1. Overview

A React/D3 interop component that renders an SVG graph of `nodes` + `edges` with:
- **Matte flat fill** per course; opacity drives the mastery tier (`masteryOpacity(tier)` → `1.0 / 0.75 / 0.55 / 0.28 / 1.0`).
- **Subject-root nodes** (`is_subject_root: true`) are larger (R=22) and labeled in the course's text color.
- **Hover tooltip** (name, subject color chip, mastery %, last studied).
- **Click → `onNodeClick(node)`** handler.
- **Drag** to reposition; dragged node becomes `fixed` (`d.fx`/`d.fy`) until released.
- **Zoom/pan** via `d3.zoom` (scale range 0.3–3).
- **Drift animation**: each node has a per-node `sin/cos` micro-oscillation applied on top of the simulation position via RAF. Gives the graph a "living" feel even when the simulation has settled.
- **Animated tier transitions** (500ms fade for fill-opacity when `mastery_tier` changes).
- **Animated entry** for new nodes (`opacity 0→1`, 400ms).
- **Highlight ring** for `highlightId` — a separate effect so changing the target doesn't restart the simulation.
- **Comparison outline rings** (when `comparison.partnerNodes` provided): 4-color code for you-vs-partner mastery overlap.
- **Exports** with `React.memo` so parents can safely re-render without reseeding the sim.

The simulation forces (`KnowledgeGraph.tsx:138-148`):
- `center` (strength 0.04)
- `x` / `y` pull to center (strength 0.03 each)
- `link`: distance `55 + (1 - strength) * 40`, strength `strength * 0.8`
- `charge`: -120
- `collide`: `radius + 8`
- `alphaDecay`: 0.04

---

## 2. Props

```ts
interface KnowledgeGraphProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  width: number;
  height: number;
  animate?: boolean;                 // enable entry / tier transitions
  highlightId?: string;              // concept to ring
  interactive?: boolean;             // zoom, drag, hover, click
  onNodeClick?: (node: GraphNode) => void;
  comparison?: { partnerNodes: GraphNode[] };
  courseColorMap?: Record<string, string>;
}
```

Consumer conventions:
- **Dashboard**: `interactive=true`, `animate=false`, no comparison.
- **Tree**: `interactive=true`, no `animate`.
- **Learn**: `interactive=true`, `animate=true`, `highlightId=suggestNode?.id ?? topicNode?.id`.
- **Social / RoomOverview**: `interactive=true`, `comparison={partnerNodes}` when a partner is selected.

---

## 3. Key engineering decisions

### 3.1 Topology keys vs visual updates

`nodeIdsKey = nodes.map(n => n.id).join('|')` (same for edges). The main `useEffect` only reseeds the simulation when these keys or `width`/`height`/`animate`/`interactive`/`onNodeClick`/`comparison` change. Mastery/color updates go through a **second effect** that updates `fill` / `fill-opacity` / `stroke` attributes in place without touching the sim (`KnowledgeGraph.tsx:371-399`).

This is why a `/learn` chat turn that calls `getGraph` (refreshing mastery scores) does not cause the nodes to fly around.

### 3.2 Stable onNodeClick via ref

Because `onNodeClick` is in the main effect's dep array, consumers pass a ref-backed stable callback (see `features/learn.md` §2.12 — `nodeClickPayloadRef`). Dashboard's callback is wrapped in `useCallback`.

### 3.3 `nodesRef` / `courseColorMapRef`

The click/hover handlers close over `nodes` at subscription time. Without refs, clicking a node after a mastery refresh would show stale data in the tooltip. Both are updated via `useEffect(() => {nodesRef.current = nodes}, [nodes])` (`KnowledgeGraph.tsx:79-82`).

### 3.4 Drift animation

Each node has random `freqX/freqY/phaseX/phaseY/amp`. The RAF loop (`driftTick`, `KnowledgeGraph.tsx:349-359`) computes `dx/dy` offsets and calls `render()` each frame. During drag, the dragged node's offsets zero out so the user sees direct control, not drift.

### 3.5 Highlight ring separation

A standalone effect (`KnowledgeGraph.tsx:403-417`) removes any existing `.highlight-ring` and inserts a new one before the node's main circle. This runs on `highlightId` changes only — doesn't restart the simulation.

### 3.6 SVG structure

```
<svg>
  <g class="graph-container">       // zoom transform target
    <g class="links">                // lines (rendered first)
    <g class="labels">               // text (rendered before nodes → drawn under circles)
    <g class="nodes">                // circles + optional rings
      <g class="node">
        [<circle> comparison outline if any]
        <circle class="main-circle"> <!-- the matte orb -->
        [<circle class="highlight-ring"> if highlighted]
```

Labels are appended *before* nodes (`KnowledgeGraph.tsx:191-205` / `207-214`) so the circles paint on top of the text (so the label never overlaps the circle center).

### 3.7 Left-in `console.log`

`KnowledgeGraph.tsx:106` has a `console.log('[KG] main effect fired', ...)` — production trace noise. Flag for cleanup.

---

## 4. Visual encoding

| Property | Encoded |
|---|---|
| Node radius | Subject roots: 22. Concepts: `getNodeRadius(mastery_score)` (from `lib/graphUtils.ts`). |
| Fill color | `getCourseColor(subject, override).fill` — matte flat per course. |
| Fill opacity | `masteryOpacity(tier)`: mastered=1.0 / learning=0.75 / struggling=0.55 / unexplored=0.28 / subject_root=1.0. |
| Stroke color | Same as fill. |
| Stroke width | Subject root: 2.5. Concept: 1.5. |
| Stroke opacity | Subject root: 0.7. Concept: 0.4. |
| Label color | Subject root: course text color. Concept: `#374151`. |
| Label font | DM Sans 13px (root) / 11px (concept), weight 600/400. |
| Label y-offset | `radius + 17` (root) / `radius + 15` (concept). |
| Edge stroke | `rgba(107,114,128,0.2)`, width `0.5 + strength*1.2`, round caps. |
| Comparison outline | +5 to radius; stroke width 2; colors per matrix in §3 of `features/social.md`. |
| Highlight ring | +8 to radius; stroke `rgba(26,92,42,0.55)`; width 2. |

---

## 5. Interaction surface

| Gesture | Behavior |
|---|---|
| Hover | Tooltip with name / subject dot / mastery % / last studied. Stroke opacity/width increase. |
| Click | Calls `onNodeClick(node)`. |
| Drag | Sets `d.fx`/`d.fy` during drag; clears on end. |
| Scroll/pinch | Zoom (scale 0.3–3). |
| Drag background | Pan (via `d3.zoom`). |

---

## 6. Edge cases

1. **`edges` filtered to valid nodes** (`simLinks` filter at `KnowledgeGraph.tsx:129-136`) — defensive, tolerates stale edges that reference removed nodes.
2. **`svg.selectAll('*').remove()` on every main-effect run** — wipes everything. Because the topology keys make reruns rare, this is cheap; but a rebuild using a different React/D3 binding (react-force-graph, vis-network) should consider incremental updates.
3. **Drift is always on** — no prop to disable. If the rebuild adds a "reduce motion" accessibility setting, drift should be gated.
4. **Tooltip positioning** uses `event.clientX - rect.left + 14` — relative to the SVG's bounding rect. Works; but in fullscreen overlays the SVG is 100% × 100% of a non-origin container, so `rect.left` can shift. Tested to work in Dashboard's fullscreen overlay.
5. **Zoom state** is not synced across mounts — switching routes resets zoom. Intentional.
6. **Simulation doesn't pause** when off-screen — if the user hides the graph pane via a mobile tab toggle, D3 keeps ticking. Minor CPU cost.

---

## 7. Things to preserve in the rebuild

- Per-course matte fill + mastery-opacity encoding (the whole visual identity).
- Subject-root nodes as larger, colored hubs.
- Drift animation (tasteful "living" feel).
- Animated entry (400ms opacity fade) for new nodes.
- 500ms tier transition for mastery changes.
- Zoom/pan with 0.3–3 scale range.
- Drag to reposition (released nodes rejoin the simulation).
- Tooltip with name / subject dot / mastery % / last studied date.
- Highlight ring (separate effect so it doesn't reseed the sim).
- 4-color comparison outline ring (the social-feature signature visual).
- `React.memo` to prevent needless re-seeding from parent renders.
- Stable `onNodeClick` contract (document the ref pattern for consumers).

## 8. Things to rework

- Remove the production `console.log` on main effect entry.
- Consider adding a `reduceMotion` prop that disables drift + transitions.
- Add a `paused` prop (or visibility observer) to stop the RAF when the graph is off-screen (mobile tab toggles, hidden panels).
- Expose a "reset zoom" API.
