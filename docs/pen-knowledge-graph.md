# Pen knowledge graph: source, live layout and verification

The new Sapling 2D graph uses the authored vector geometry from the Pen master, rather than a force simulation or a screenshot of a sample student's map. The exact reference fixture and the live learner graph have different responsibilities: the fixture preserves every source path and paint; the live graph preserves actual course/concept IDs, relationships, labels and server mastery tiers while adapting the authored shapes to that data.

## Design authority and source integrity

The design master is `JSs7K`, **Component / Exact Figma knowledge graph**, in `Sapling-Complete-Wireframes.pen`, with a complete viewport of **893 × 601**. The master was imported from Figma node `3457:3774` in file `et54abKWl2OTtuyS8Hz7Ig`. The current native geometry and paint derivation is committed at `frontend/public/design/sapling/graph-pen-reference.svg`. The original Figma SVG is retained separately at `frontend/public/design/sapling/graph-reference.svg` for provenance.

The current native SVG's SHA-256 is:

```text
e596208cd4242f3c8a17c21b875237d91b32bb2f5e3ad543a5f1105d12022fd0
```

The original SVG's SHA-256 remains `8a3e55c640872a9316dbdb82c25e206746224eb127cbb6207f691ef3ec065c95`. The native HTML export used for the derivation hashes to `7809dbce8bc9a7d440111093361db91afbcd666bd4ef85a4c2693914e0c2f2ce`.

`graph-provenance.json` records both asset hashes, the viewport and source IDs. `frontend/src/lib/graph/penNativeGraphSource.ts` contains all **74 ordered native paths**, their local-to-canvas transforms, all **21 native linear gradients**, the native shadow effect, and source Pen node IDs. `penGraphSource.ts` preserves the original SVG mapping separately. Native paths with gradient strokes retain the expanded stroke geometry exported by Pen; normal outlines retain their source stroke settings. The 74 paths include two course hubs, twenty topic/leaf marks, organic branches, outlined course labels and the original overlay marks. Native Pen reports 73 immediate children because one child is a frame containing two paths; the recursive path count is 74.

The source artwork has no raster `<image>` and no external font dependency: its two sample course labels are outlined paths. Production course text is rendered from actual data. The supplied asset is for Sapling implementation; no independent redistribution license is inferred.

Verify the committed source from the repository root:

```sh
shasum -a 256 frontend/public/design/sapling/graph-pen-reference.svg
shasum -a 256 frontend/public/design/sapling/graph-reference.svg
cd frontend
npm test -- src/lib/graph/penGraphGeometry.test.ts
```

The pure source tests check both asset hashes, all original ordered path data/paints, every native local path and transform, and the native normalized-gradient formulas. The reference component's DOM test additionally checks all 74 paths, 21 gradients, source IDs, viewport, native transforms and the one source fill path carrying its outer shadow. Changing a screenshot cannot satisfy these vector checks.

## Exact design fixture

`PenGraphReference` renders `PEN_NATIVE_GRAPH_REFERENCE` as SVG paths and paint definitions. It preserves native local paths, viewBox transforms, paint order, the source shadow on path 68 and outlined sample labels. The native shadow is `#00000003` with a six-unit spread; the adjacent outline has no shadow. Gradient/filter IDs are prefixed per component instance so separate maps do not accidentally share paint servers.

`createPenGraphFixture()` provides explicitly named design-only IDs beginning with `pen-fixture:`. `buildPenGraphLayout(data, { referenceFixture: true })` uses the exact 22 source positions and 21 authored branch centerlines, with the corrected native paint model. It refuses ordinary learner IDs or a different edge topology. The original source sample labels are confined to this explicit fixture and the source reference component; live adaptation never matches student labels to CAS sample names.

The complete reference component is the appropriate subject for a 74-path visual comparison. The fixture's logical node/edge layout alone does not include every source label and overlay path.

## Live learner data

`buildPenGraphLayout` is a pure function over existing `GraphNode` and `GraphEdge` objects. It keeps actual IDs, names, course IDs, subject-root flags, server tiers and mastery estimates. It retains disconnected concepts and cross-course relationships. Edges with missing endpoints cannot be painted and are excluded; repeated valid edge records receive distinct renderer keys. No sample course, topic or relationship is added to learner data.

Node positions are deterministic for the same IDs and topology, regardless of input array order, viewport dimensions, palette or mastery changes. Courses are ordered by stable course ID; nodes and traversal ties are ordered by stable node ID. Each course uses one authored branch family, with connected nodes assigned along its source branches. Remaining disconnected nodes use unused family slots. Dense courses receive additional collision-spaced positions. With more than two courses, the layout packs actual painted family bounds into compact deterministic arrangements targeting the 893:601 design aspect, with at least 40 units between family bounds. It preserves every within-family position and avoids carrying unused source-canvas origins or fixed 700-unit row gaps into the overview. Node paint and organic branch control hulls are included in the final bounds. Resizing fits that result uniformly instead of restarting a simulation.

The normal concept and leaf shapes retain their native local fill paths and irregular outline paths, plus individual `fillTransform` and `outlineTransform` values. `shapeTransform` positions the resulting source-space mark in the live map. Course hubs retain their authored native hub paths. Sizes use the source presets—53.5-unit hub radius, 25-unit topic radius and 15-unit leaf radius—rather than an invented mastery-size encoding. Server mastery estimates remain available as data and readable evidence; node fill uses the server's `mastery_tier` and the existing shared legend:

| Meaning | Source fill |
| --- | --- |
| Course hub | `#6C462F` |
| Mastered | `#A3B06D` |
| Learning | `#FCC98A` |
| Struggling | `#EF908F` |
| Unexplored | `#DECDC1` |

`penBranchFor` reuses an authored organic path and applies a similarity transform to meet the actual node boundaries. Its gradient follows the endpoint nodes' actual semantic fills, oriented according to the original source gradient anchor. The native gradient transform first scales normalized object space to source-space bounds, and the branch projection then maps the path and paint to the live endpoints. The renderer must apply `gradientTransform={branch.gradient.transform}`; dropping that transform changes the native paint field. `projectionScale` exposes the similarity transform's scale; dividing the seven-unit branch stroke by this value cancels only the endpoint projection. Outer map fit and zoom can still scale strokes naturally. Dragging can recalculate that same branch from the moved endpoints without mutating graph data.

Arbitrary learner topology necessarily has different positions and labels from the two-course design fixture. Exact source-shape preservation and truthful real data are the live contract; a learner map with different concepts is not evidence of pixel equality to a static reference.

## Visual comparison: two separate checks

Use a fixed Chromium build, 1× device scale, an exact 893 × 601 graph viewport and disabled motion. Wait for `document.fonts.ready` and `data-renderer-ready="true"` before capture. Keep the full viewport; do not crop it back to the original approximately 891 × 599.2 content bounds. Preserve the source's painted overflow allowance.

1. **Native vector against React reference:** compare `graph-pen-reference.svg` to `PenGraphReference` in the same browser, at the same dimensions and background. Normalize only the per-instance ID prefix when comparing SVG attributes. Every path, paint, gradient endpoint/stop and filter primitive must match. Capture both, an overlay, and an unmasked difference image. This isolates errors introduced by source-to-code translation.
2. **Native Pen against browser:** export fresh `JSs7K` at 1× through the Pen integration and compare it to the browser reference at exactly 893 × 601. Use the same composited background for both if taking opaque screenshots. The native export is RGBA with transparent corners, not a black-filled canvas. Its alpha-painted bounds in the October 19 capture are `(0, 0)` through `(892, 597)` inside the full viewport. Inspect all nonzero differences, including opaque branch interiors, before attributing them to antialiasing.

The native paint model matters. Pen evaluates a gradient in normalized object coordinates before applying anisotropic bounds. For rotation `θ`, size height `h` and center `(cx, cy)`, normalized endpoints are `(cx ± sin(θ)h/2, cy ± cos(θ)h/2)`. Retain `gradientTransform="matrix(width 0 0 height 0 0)"`. Flattening only those endpoints into canvas coordinates changes gradient projection on a rectangular branch. This is why merely using the original SVG or the HTML export's flattened gradient endpoints produces a visible paint difference from the current Pen file.

A read-only Sharp/libvips preflight at 893 × 601 over cream gives the following diagnostic comparison to the October 19 native Pen PNG. These are **not browser acceptance results**:

| Derivative | Pixels with channel difference > 8 | Such pixels opaque in both images | Mean channel difference |
| --- | ---: | ---: | ---: |
| Original canonical SVG | 5,711 | 1,993 | 0.2011 |
| Native paths plus corrected normalized paint and native shadow | 4,288 | 622 | 0.1482 |

All 622 remaining opaque pixels above that threshold fall inside the two tiny outlined course-label bounds; no opaque pixels outside those label bounds exceed the threshold. At the previously mismatched branch point `(304, 290)`, the corrected derivative is RGB `(146, 117, 97)` and the native PNG is `(147, 116, 97)`, while the original SVG was `(126, 91, 70)`. Remaining Sharp/native differences include transparent silhouette edges and tiny glyph rasterization. Do not claim they establish browser pixel equality: compare the actual Chromium render to native Pen, inspect the unmasked difference image, and report the resulting metrics separately.

A source hash verifies the asset, not the complete UI. A reference fixture screenshot verifies the source rendering, not live data, interactions, responsive layout or AI learning behavior. Record those claims separately in the PR.

## Functional and responsive verification

The pure geometry tests exercise exact source coordinates, topology gating, actual-ID retention, duplicate names, isolated nodes, dangling edges, repeated edge keys, mastery/input-order stability, 90 nodes across three courses, a compact 19-node/five-course overview, preserved within-family offsets, bounded/nonoverlapping marks, and finite branch projection.

The renderer and application checks must also cover the existing Dashboard and Tutor behavior: course/semester scope, actual counts, ID-based selection, selected concept details, pan/zoom/drag/reset, full map, textual topic list, keyboard activation and focus return, renderer recovery, 2D/3D preference and no-WebGL fallback. Map exploration must remain read-only and must not begin or grade a learning session. Practice must continue through the existing explicit learning controller.

Retained node drag offsets are bounded against the current layout after a course filter repacks it. Stored pan distances are viewport pixels, so the displayed view is also bounded synchronously when the viewport or course scope changes; subsequent gestures start from that visible view. Regression checks cover dragging before filtering, and zooming and panning to a desktop boundary before resizing to a phone or selecting a narrower course scope.

Capture desktop and mobile overviews and selected/full-map states. Exercise 1440, 1024, 768, 390 and 320 CSS-pixel widths and 200% browser zoom. Check long labels, empty data, one course, several courses and a dense map. Phone page scrolling and bottom navigation must remain reachable. The Knowledge sidebar destination and its fullscreen view use the same Sapling 2D appearance as Dashboard and Tutor. Existing default/FA26 renderers remain available for legacy surfaces, and optional 3D retains its own rendering contract.


## Recorded browser comparison — October 19, 2026

Chromium at 1× rendered the complete 893 × 601 native SVG and the React reference over the same paper background. The native source SVG and React reference are **pixel-identical in the same Chromium render: zero changed pixels across 536,693 pixels**. Every path and transform is also checked structurally. The comparison against Pen's own PNG has **4,088 pixels above eight RGB levels (0.762%)**, mean channel difference **0.154656 / 255**, and a maximum of 82. The unmasked difference image shows silhouette/glyph rasterization edges; it is not a claim of pixel-identical rasterization between Pen and Chromium.

- [Original native Pen master](redesign/knowledge-graph/pen-master.png)
- [Browser reference](redesign/knowledge-graph/browser-reference.png)
- [Native/browser overlay](redesign/knowledge-graph/overlay.png)
- [Unmasked difference, channel values amplified ×4](redesign/knowledge-graph/native-diff-x4.png)
- [Machine-readable dimensions, asset hash and comparison metrics](redesign/knowledge-graph/comparison.json)

The design reference route `/design-reference/knowledge-graph` is available only in development or the deterministic test build. Authenticated student screens render actual course/concept data. The representative live screenshots below use isolated seeded data; the AI provider is scripted for deterministic UI verification.

![Desktop learner dashboard](redesign/knowledge-graph/desktop.png)

![Phone learner dashboard](redesign/knowledge-graph/mobile.png)

[Knowledge sidebar page with the same renderer and existing controls](redesign/knowledge-graph/knowledge.png)

The bounded card uses Pen's 48/42-pixel title strips, original graph aspect, 44-pixel map controls, native palette and desktop/phone legend positions. Course progress remains on the count button. Narrow phone cards reserve a separate action row when the existing navigation rail leaves too little horizontal space. ResizeObserver's graph is absolutely positioned inside the aspect-ratio box so its old explicit dimensions cannot hold a resized phone preview open. Card-specific legend/button selectors intentionally outrank the shared primitive CSS.
