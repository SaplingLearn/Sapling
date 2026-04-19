# Feature · Tree (Full Knowledge Graph)

> Covers: `/tree/page.tsx`. Full-viewport `KnowledgeGraph` with search + filter sidebar + per-node detail panel.

---

## 1. Overview

`/tree` is a focused, immersive view of the user's full knowledge graph. Uses the same `KnowledgeGraph` component as `/dashboard`, `/learn`, and `/social`, but fills the whole viewport (`height: calc(100vh - 48px)`) and overlays a floating control bar + detail sidebar.

Controls:
- **Search** input (client-side `includes` on `concept_name`, case-insensitive).
- **Filter pills**: `all` / `mastered` / `learning` / `struggling` / `unexplored` — apply to `mastery_tier`.
- **"N nodes" counter** in the bar.
- **AI recommendation popup** when `?suggest=` is present (identical pattern to Dashboard/Learn).
- **Per-node detail panel** (right side on desktop, bottom sheet on mobile) shown when a node is clicked.

---

## 2. User flows

### 2.1 Flow: search + filter

- Search input updates `search` state on every keystroke. `filteredNodes` recomputes every render (no debounce).
- Filter pills set `filter`. Default `'all'` shows every node; others filter by `mastery_tier`.
- `filteredEdges` is derived: keep only edges where both endpoints are in `filteredNodeIds`, plus any edge touching a `subject_root` (so course-root connections stay visible). Cross-subject concept edges still hidden as in dashboard/learn.
- Node count shown inline.

### 2.2 Flow: click a node

- `onNodeClick={setSelectedNode}` (`tree/page.tsx:107`) — stores the clicked `GraphNode`.
- Right-side (desktop) / bottom-sheet (mobile) panel renders with:
  - Concept name + `×` close.
  - Subject row: colored dot + subject name in the subject's text color.
  - (Continues past line 278 — to fully document in Phase 4 cross-cutting, but the panel shows mastery %, times studied, last studied date, and likely a "Learn this" link.)
- Clicking the same node again does not toggle — only the `×` closes.
- Clicking a *different* node replaces the panel contents.

### 2.3 Flow: suggest popup

Same pattern as `/learn` — popup with Dismiss + Start Quiz →. Dismiss routes to `/tree` (correctly clears `?suggest=`).

---

## 3. State

- `allNodes`, `allEdges`: from `getGraph(userId)`.
- `filter`: `'all'|'mastered'|'learning'|'struggling'|'unexplored'`.
- `search`: string.
- `selectedNode`: `GraphNode | null`.
- `dimensions`: `{width, height}` — based on `window.innerWidth` + `innerHeight - 48`, tracked via `window.addEventListener('resize')` (no ResizeObserver here — simpler because the graph is full-viewport).
- `courseColorMap`: from `getCourses(userId)`.
- `suggestConcept`: query param.
- `suggestNode`: memo of the matching GraphNode.

---

## 4. API calls

- `getGraph(userId)` → populates `allNodes`, `allEdges`.
- `getCourses(userId)` → populates `courseColorMap`.

No mutations — this is a read-only view.

---

## 5. Components involved

- `KnowledgeGraph` (full-viewport)
- Inline: search input, filter pills, node-detail panel, AI recommendation popup

---

## 6. Interactive patterns

- `window.resize` listener → recompute dimensions (not a ResizeObserver because container size equals viewport-48).
- Client-side search filter (no debounce).
- Floating glass-panel controls at top-center.
- Right-side detail panel (desktop) → bottom sheet on mobile.

---

## 7. Edge cases

1. **Filtering can hide the highlighted `suggestNode`.** If the user sets `filter=mastered` but the AI-recommended concept is `unexplored`, the node is filtered out of view but the suggestion popup still renders. A rebuild should either auto-switch the filter when highlighting or indicate "Filtered out — clear filter to see".
2. **Search and filter do not combine with subject-root visibility consistency** — the current code keeps subject-root edges but not necessarily subject-root *nodes* (`filteredNodeIds` only includes filtered concepts). Subject roots may still render if they're in `allNodes`. Verify in the rebuild.
3. **No URL persistence for filter/search.** Refreshing loses your filter state. Low-priority, but a nice-to-have for shareable views.
4. **Graph re-seeds on resize** — `useEffect` dependency on `width/height` recomputes `dimensions`, which feeds `KnowledgeGraph`. D3 simulation doesn't restart because `KnowledgeGraph` memoizes via `nodeIdsKey`/`edgeIdsKey`, but nodes will visually spring back toward the new center. Expected, keep.

---

## 8. Things to preserve in the rebuild

- Full-viewport immersive graph with non-blocking overlay controls.
- Search + mastery-tier filter combo.
- Per-node detail panel (right on desktop, bottom sheet on mobile).
- `?suggest=` popup parity with Dashboard and Learn.
- "N nodes" live counter.
- Subject-root edge preservation when filtering (so courses never become disconnected islands visually).

## 9. Things to rework

- Expose filter/search in the URL (`?filter=&q=`) for shareable views and refresh persistence.
- Handle "filter hides suggestion" edge case.
