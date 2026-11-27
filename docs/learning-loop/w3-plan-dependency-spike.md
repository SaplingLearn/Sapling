# W3.1 spike — Plan dependency view

**Status:** spike (not full UI)  
**Plan row:** Alvar trilogy W3.1 / claim **D** (“Plan shown as structure (graph), not only a list”)  
**Branch context:** `feat/learning-loop-reland`  
**Date:** 2026-11-23

---

## Verdict (data)

| Source | Available today? | Notes |
|---|---|---|
| `GET /api/learn/loop/plan` concepts list | Yes | Numbered approve UX; `kind` + goal `reason` |
| `GET /api/learn/loop/plan` **prereq edge pairs** | **Yes (landed in this spike)** | Additive `prereq_edges: [{prerequisite, dependent}]` among proposal ids ∪ goal targets |
| Planner-internal edges | Yes (server-only before spike) | `_plan_prereq_edges` in `services/loop/planning.py`; same orientation as fringe |
| `GET /api/graph/{userId}` edges | Yes | Includes `relationship_type` (`prerequisite`, `builds_on`, …) |
| Learn client graph cache | **Partial** | `LoopLearn.refreshGraph` **drops** `relationship_type` when mapping edges — SessionMap cannot filter prereqs without a one-line keep or the new plan field |
| `/status` approved plan | Concepts + cursor only | No edges; SessionPanel must keep plan-response edges in client state, or re-derive from graph |

**Bottom line:** Enough data to ship W3.1 UI without further schema work. Prefer `plan.prereq_edges` for PlanPanel (planner-aligned, no graph race). SessionPanel can reuse those pairs after approve, or restore `relationship_type` on the Learn graph map and filter to plan ids ∪ goal.

---

## 1. Current UI files (Learn / Loop)

| Role | Path |
|---|---|
| Plan approve surface (numbered list) | `frontend/src/components/learn/PlanPanel.tsx` |
| Session rail (approved plan list + map) | `frontend/src/components/learn/tutor/SessionPanel.tsx` |
| Course knowledge map in rail | `frontend/src/components/learn/tutor/SessionMap.tsx` → `KnowledgeGraph` |
| Orchestration (loads plan + graph, wires rail) | `frontend/src/components/learn/LoopLearn.tsx` |
| Plan kind / goal reason copy | `frontend/src/components/learn/planLabels.ts` |
| Panel plan selection / cursor | `frontend/src/components/learn/tutor/sessionView.ts` |
| Screen shell | `frontend/src/components/screens/Learn.tsx` |
| Types / API | `frontend/src/lib/api.ts` (`LoopPlanConcept`, `getLoopPlan`, `approveLoopPlan`) |
| Unit coverage | `PlanPanel.test.tsx`, `SessionPanel.test.tsx`, `SessionMap.test.tsx`, `LoopLearn.test.tsx` |
| E2E | `frontend/e2e/learn-loop.spec.ts`, `tutor-layout.spec.ts`, `learn-keyboard.spec.ts`, `a11y.spec.ts` |

**What students see today**

- **Plan phase:** `PlanPanel` — ordered `<ol>` of concepts + “Start learning”; goal sessions show `reason` (“Prerequisite for your goal” / “Your selected goal”). No edge list / DAG.
- **Teach phase:** `SessionPanel` — same numbered plan (current step highlighted) + full-course `SessionMap` (mastery colours). Map is course neighbourhood, **not** “today’s plan as a dependency graph.”

---

## 2. Where prereq edges already exist

### Backend planner (authoritative for the loop)

- `services/loop/planning.py::_plan_prereq_edges(user_id, node_ids)` — one `graph_edges` read, `relationship_type = prerequisite`, oriented by `EDGE_PREREQ_SOURCE_IS_PREREQ` (source = prerequisite).
- `_current_plan` uses those edges for `goal_scope`, `outer_fringe`, `prerequisite_ready`, sibling detection, `scope_signature`.
- Upload path writes richer prereq graphs only when `upload_prereq_edges` is on (A118); until then many courses have sparse/empty prereq sets — UI must tolerate **zero edges**.

### Plan HTTP payload (after this spike)

`GET /api/learn/loop/plan` → existing fields plus:

```json
"prereq_edges": [
  { "prerequisite": "<node_id>", "dependent": "<node_id>" }
]
```

Scoped to **today’s proposed concept ids ∪ goal `target_node_ids`**. Empty plan → `"prereq_edges": []`.

Still **not** on `/plan/approve` or `/status` (client should retain the GET /plan pairs through approve).

### Graph API / SessionMap

- `graph_service` already returns `relationship_type` on edges.
- Tree / Study keep the type; Learn’s `refreshGraph` currently strips it (`LoopLearn.tsx` ~472–474).

### Concept-level signals already on the list (not edges)

- `LoopPlanConcept.reason`: `'goal' | 'prerequisite'` (goal sessions) — labels role, not adjacency.
- `target_node_ids` on each concept row — goal set for scope, not an edge list.
- `unresolved_prerequisite_ids` on goal progress — post-attempt status, not plan structure.

---

## 3. Minimal UX proposal

Keep approve UX as the numbered list. Add a **small dependency block under the list** (PlanPanel), mirrored read-only under SessionPanel’s plan section.

1. **List stays primary** — keyboard / a11y / approve flow unchanged (`loop-plan-approve`, concept rows).
2. **Under the list (when `prereq_edges.length > 0`):**  
   - Heading: “How these connect” (or “Dependencies”).  
   - **v1:** compact edge list — `A → B` using concept names (same `names` map as DiagnosisSummary).  
   - **v1.5 (optional):** tiny DAG — plan nodes only, directed prereq arrows; reuse SessionMap/`KnowledgeGraph` with a **filtered** node/edge set (not the full course). Prefer list-first if map chrome feels heavy next to approve.
3. **Zero edges:** omit the block (no empty-state noise); list alone remains valid (common while `upload_prereq_edges` is off).
4. **SessionPanel:** same edge list (or mini-DAG) under Plan; leave full-course Knowledge map + W3.2 dual encoding for later.
5. **Do not** make the DAG the approve control — claim D is “shown as structure,” list remains the action surface (W3.1 acceptance).

---

## 4. E2E testid plan

Existing (keep):

| testid | Use |
|---|---|
| `loop-plan-concept-{nodeId}` | List rows |
| `loop-plan-kind-{nodeId}` / `loop-plan-reason-{nodeId}` | Badges / goal copy |
| `loop-plan-approve` | Approve |
| `loop-rail` | Session panel |
| `tutor-session-map` | Course map (unchanged role) |

Add for W3.1:

| testid | Where | Assert |
|---|---|---|
| `loop-plan-deps` | PlanPanel section (and SessionPanel twin) | Present iff ≥1 edge |
| `loop-plan-dep-{prereqId}-{dependentId}` | One edge row (or SVG title) | Name text / `→` |
| `loop-plan-deps-empty` | **Do not ship** | Prefer absent section when no edges |
| `tutor-panel-plan-deps` | SessionPanel only if markup diverges | Same edge ids as approve-time plan |

Journey sketch (`learn-loop.spec.ts` or small sibling):

1. Seed / rich fixture with a known prereq among planned concepts (goal session already covers Binary → goal).  
2. Reach plan → expect `loop-plan-deps` + specific `loop-plan-dep-…`.  
3. Approve → rail still shows the same deps.  
4. a11y: deps region `aria-labelledby` / listed under plan heading; approve still Tab-reachable (`learn-keyboard.spec.ts`).

---

## 5. Effort estimate (full W3.1)

| Slice | Size | Notes |
|---|---|---|
| Types + keep `prereq_edges` through approve in LoopLearn state | S | `LoopPlan` in `api.ts`; optional `/status` later |
| PlanPanel edge list (+ unit test) | S–M | Main UX |
| SessionPanel mirror | S | Read-only |
| Optional mini-DAG (filtered KnowledgeGraph) | M | Layout/a11y; can follow list |
| Restore `relationship_type` in `refreshGraph` | XS | Only if deriving edges from graph instead of plan field |
| E2E + a11y + testid doc | S | `docs/frontend-testids.md` |
| **Total full W3.1** | **~1.5–3 eng-days** | **M** as planned; list-only under 2 days; mini-DAG toward 3 |

**Dependencies / risks**

- Sparse graphs until `upload_prereq_edges` (E4) — UI must degrade to list-only.  
- Do not invent edges client-side from `reason === 'prerequisite'` (many-to-one goal, not pairwise).  
- W3.2 (covered vs understood on SessionMap) is separate; don’t overload this spike’s mini-DAG with mastery dual encoding.

---

## 6. Code landed in this spike

| Change | File |
|---|---|
| Expose `prereq_edges` on `GET /plan` | `backend/services/loop/plan.py` |
| Tiny coverage | `backend/tests/test_learning_probe_planner.py` (`test_plan_get_exposes_prereq_edges_among_proposed_concepts` + empty assertion on ordered-sections test) |

**Not landed:** PlanPanel / SessionPanel UI, frontend types, E2E.

---

## 7. Recommended next PR (implementation)

1. Extend `LoopPlan` / keep `prereq_edges` in LoopLearn after `getLoopPlan`.  
2. PlanPanel: deps list under `<ol>` when non-empty.  
3. SessionPanel: same.  
4. Unit + one Playwright journey + testid row in `docs/frontend-testids.md`.  
5. Defer mini-DAG / W3.2 encoding.
