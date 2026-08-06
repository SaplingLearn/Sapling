# 3D knowledge graph — "Focused Minimal" visual upgrade

- **Date**: 2026-08-05
- **Status**: approved (brainstorm w/ visual companion; direction C of 4 mockups)
- **Owner surface**: `frontend/src/components/graph/KnowledgeGraph3D.tsx`

## Problem

The 3D graph mode (shipped as PR #96, toggled via the `2D/3D` button on every
`KnowledgeGraph` mount) is a bare adapter: default library spheres, gray lines,
hover-only tooltip labels, transparent background. It reads as a tech demo, not
a study tool, and nobody has a reason to flip the toggle.

## Direction

**Focused Minimal** ("Obsidian-style clarity"), chosen over Living Organism,
Constellation, and Botanical Growth mockups:

- flat matte spheres, quiet thin links, warm app-native palette;
- **every node label always visible** as a camera-facing text sprite;
- **hover-focus**: hovering a node lights its 1-hop neighborhood and dims
  everything else.

Legibility over spectacle. It should feel like the 2D graph's calmer, deeper
sibling — not a different product.

## Goals

1. Make 3D mode visually coherent with the app shell and genuinely useful
   (readable labels, focus interaction).
2. Zero change to data flow, API payloads, the 2D component, the wrapper/
   toggle, or any mount.
3. Keep every existing contract: testids, sr-only node list, click
   whitelisting, reduced-motion/test-mode determinism, SSR constraints,
   Cloudflare worker bundle size.

## Non-goals

- No default-mode change: **3D stays opt-in** via the existing toggle on all
  three mounts (/tree, dashboard panel, tutor sidebar).
- No landing-page changes (the marketing `KnowledgeGraphDemo` is untouched).
- No node drag, no click fly-to camera animation, no fog/starfield/bloom.
- No label-collision avoidance in v1 (graphs are typically well under a few
  hundred nodes; sprite overlap at extreme zoom-out is accepted).

## Visual & interaction spec

**Background** — stays transparent; each surface's warm panel shows through,
so the scene matches whichever mount hosts it with no per-theme plumbing.

**Nodes** — flat matte spheres (`MeshLambertMaterial`, no gloss/emissive).
Color = course color with the existing per-node seeded shade variation
(`shadeFor`, unchanged). Size = existing scale (concepts 4→10 by
`mastery_score`, subject roots 22). `unexplored`-tier nodes desaturate toward
warm gray so attention lands on studied material.

**Labels** — every node gets an always-visible camera-facing mono text sprite
(`three-spritetext`) positioned below the sphere. Ink color from the app
theme. Subject-root labels render larger/bolder than concept labels. This
replaces "hover tooltip only" as the headline change.

**Hover focus** — `onNodeHover`:

- hovered node: soft focus halo — a slightly larger translucent sphere
  behind the node, colored from the app accent token (`--accent`, currently
  `#2d8f5c`), resolved at mount — label full strength;
- 1-hop neighbors + connecting links: full color;
- everything else: nodes → pale warm gray, links → near-invisible, labels →
  faded;
- mouse-off restores everything.

**Highlight prop** — the existing `highlightId` (tutor "currently discussing")
renders the same accent-token emphasis persistently, replacing today's flat
accent recolor.

**Links** — thin warm-gray lines (today's `rgba(138,131,114,…)` family), width
subtly scaled by `strength` (unchanged formula). No particles/arrows.

**Camera & motion** — library orbit/zoom unchanged; `enableNodeDrag` stays
`false`; `cooldownTicks` stays `120`, and `0` under reduced-motion or
`IS_TEST_MODE`. One new ⌖ recenter button (bottom-right overlay) calling
`zoomToFit`; it carries the same class as the 2D recenter control so the
existing `globals.css` rule keeps hiding it on the tutor sidebar instance.

Two justified deviations from that plain description, both found during
Task 5 verification and fixed under review:

- **Camera auto-fit on engine settle.** The library's default initial
  camera distance never framed a freshly-loaded graph — every node
  rendered as an illegible clump. `onEngineStop` now drives a one-shot
  `zoomToFit`, but naively firing it synchronously (or even one animation
  frame later) measures the scene before that tick's node positions have
  actually landed on their Three.js objects, fitting the camera to a
  stale/near-empty bounding box. The fix polls `getGraphBbox()` on
  successive `requestAnimationFrame` callbacks until two consecutive reads
  agree (frame-capped safety net) before fitting, and is idempotent per
  dataset via a `didFitRef` guard plus an epoch counter that invalidates
  any in-flight poll if `nodes`/`edges` change mid-poll (so a stale poll
  from an abandoned dataset can never clobber the fresh poll's correct
  fit). This is a system-initiated camera fly, not a user gesture, so it —
  and the ⌖ recenter button's `zoomToFit` call, gated the same way — use an
  **instant (`0`ms) duration under reduced-motion/`IS_TEST_MODE`** instead
  of the normal 400ms eased fly; an animated system-initiated fly would
  itself be a motion violation on those paths.
- **`warmupTicks={200}` under reduced-motion/`IS_TEST_MODE`.** With
  `cooldownTicks={0}` alone, the animated tick loop trips its stop
  condition on the very first tick — before ever calling the physics
  step — so the 3D force simulation never actually runs and nodes stay at
  their raw, tightly-clustered pre-simulation positions. `KnowledgeGraph2D`
  already solves the identical problem for its own reduced-motion path via
  `sim.alpha(1).tick(200).alpha(0).stop()` (run the simulation to a real
  settled layout synchronously, then skip the animated loop); `warmupTicks`
  is the 3D library's equivalent knob, applied only on the reduced-motion/
  test-mode paths — the normal animated path (`warmupTicks={0}`) keeps its
  pleasant force-directed settling animation over the full 120 cooldown
  ticks.

**Click** — unchanged: whitelisted original `GraphNode` handed to
`onNodeClick` (node detail aside / tutor deep-link per mount).

## Technical design

**Blast radius** — `KnowledgeGraph3D.tsx` + new sibling `graph3dHelpers.ts`
(pure functions: adjacency map from edges, dim-color math, label sizing).
Nothing else changes.

**New dependency** — `three-spritetext` (same author as
`react-force-graph-3d`, built to pair with it). It is imported only inside
the already-lazy client chunk (`dynamic ssr:false`), so the OpenNext/
Cloudflare worker bundle is unaffected. Verified pre-merge with the CF
Workers build check.

**Node objects** — switch from accessor-styled default spheres to
`nodeThreeObject` returning a `THREE.Group`: matte sphere + `SpriteText`
label. Objects are created once per data change and registered in a
`Map<nodeId, {material, sprite}>`.

**Hover mechanics** — no per-hover geometry rebuilds. `onNodeHover` looks up
the memoized neighbor set and imperatively mutates registered
materials/sprites (opacity + color) for dim/restore. Link dimming goes
through the `linkColor`/`linkOpacity` accessors re-keyed on hover state
(links are cheap line materials).

**Theme resolution** — three.js cannot parse `var(--…)`. Label ink and dim
colors are resolved once at mount via `getComputedStyle` with hex fallbacks.
Node colors already arrive as resolved hex (existing `data.ts` contract,
documented at `lib/data.ts` near `apiToGraphNode`).

**Preserved constraints** (from the current file header + tests):

- SSR/hydration: client-only state (`reducedMotion`, theme colors, hover)
  never flows into SSR-rendered DOM.
- Click handler whitelists by id — library-injected fields (`x/y/z`, `__threeObj`,
  …) never leak to callers.
- sr-only `<ul>` node list and every existing testid unchanged
  (`graph-node-items`, `graph-node-item`, `graph-node-activate`).
- Colors passed to three.js are always hex, never `hsl(…)` (space-separated
  HSL silently renders black).

## Testing

**Component tests** — extend the existing seam in
`KnowledgeGraph3D.test.tsx` (stub `react-force-graph-3d`, capture props,
drive callbacks; additionally stub `three-spritetext` since jsdom has no
canvas 2D context):

- `nodeThreeObject` composes matte sphere + label; roots get the larger/bolder
  label treatment; unexplored tier desaturates.
- hover handler dims non-neighbors and restores on mouse-off (via the
  registry / exported helpers).
- recenter button calls `zoomToFit`.
- reduced-motion + test-mode `cooldownTicks` behavior unchanged.

**Unit tests** — `graph3dHelpers.test.ts` covers adjacency, dim-color math,
label sizing directly (pure, no mocks).

**E2E** — untouched and expected green: the graph render-integrity journey
(`frontend/e2e/graph.spec.ts`) and testmode determinism specs assert via the
sr-only list + testids, which do not change.

**Pre-merge gate** — hermetic backend suite, Chapter 1 Playwright lane +
oracles (full flock'd up→test→down cycle from the primary tree), CF Workers
build check, plus a manual visual pass on the local stack (2D↔3D toggle on
/tree, dashboard, tutor sidebar).

## Rollout

Single PR from `feat/3d-graph-focused-minimal`. No migration, no backend
change, no flag: the toggle is the flag. If 3D regresses, users are on 2D by
default and unaffected.
