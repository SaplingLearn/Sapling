# W3.5 spike — Learner-constructed mini-map

**Status:** W3.5a spike + presentational wrap-up stub  
**Plan row:** Alvar trilogy W3.5 / claim **Y** substitute (design_choices **Q6**)  
**Branch context:** `feat/learning-loop-reland`  
**Date:** 2026-11-23  
**Siblings:** `w3-plan-dependency-spike.md` (W3.1), `w3-covered-vs-understood-spike.md` (W3.2) — those paint the **course** graph; this is a **student-built** generative activity. Do not conflate.

---

## Verdict

| Question | Answer |
|---|---|
| What exists today for “graphs”? | Course concept + prereq graph (Tree, SessionMap, plan `prereq_edges`). Mastery fill + practiced outline (W3.2). **No** learner-drawn edges. |
| Alvar proposition / reasoning-chain ontology? | **Refused as mastery** (W6 / claim Y **N/A**). Weak ROI; extraction errors would become stored “knowledge” (Q3 reliability). |
| Product-safe substitute (Q6)? | Occasional **learner-constructed** “connect these ideas” map — generative activity (Schroeder et al. creating-maps g ≈ 0.72), not LLM auto-extract. |
| Does W3.5a write mastery / `graph_edges`? | **Never.** Stub = client React state only. No `apply_graph_update`, no PostgREST graph writes, no evidence channel. |
| Stub vs full | **Stub (a):** spike doc + wrap-up section with 2–3 chips → local edges + testids. **Full (b):** optional graded *structure* check later — still never promotes free-text / drawn links into mastery edges. |

**Bottom line:** Reuse concept ids as chips; let the student draw temporary links for reflection. Persist nothing from this activity into the knowledge graph or BKT. Graded structure (phase b) may one day score topology against a key without writing those edges into `graph_edges`.

**Code landed this spike:** `frontend/src/components/learn/LearnerMiniMapStub.tsx` (+ unit test); optional section on Learn wrap-up (`ClosePanel`) when 2–3 measured concepts exist. See §6.

---

## 1. What already exists (do not fork)

| Surface | Path | Role vs W3.5 |
|---|---|---|
| SessionMap | `frontend/src/components/learn/tutor/SessionMap.tsx` → `KnowledgeGraph` | Course neighbourhood + mastery / practiced paint. **Read-only** for the student. |
| Plan deps (W3.1) | `PlanPanel` / `SessionPanel` + GET `/plan` `prereq_edges` | Authoritative **system** prereqs among today’s plan concepts. Not learner-drawn. |
| Tree | `/tree` + KnowledgeGraph2D | Full-course graph; same integrity as SessionMap. |
| Launcher Map (W7.10) | Quiz home Map pane | Same course graph; select ≠ start. |
| Wrap-up | `ClosePanel.tsx` | Reflection (self-eval unsaved), handoffs (hide_* safe). Natural home for an optional generative beat after close. |

**Invariant:** Course edges / mastery only move through `apply_graph_update` + graded evidence. Learner mini-map edges are **not** that path.

---

## 2. Product-safe substitute for Alvar proposition ontology

| Alvar / harness idea | Sapling stance | Why |
|---|---|---|
| Persistent proposition + reasoning-chain graph extracted from chat | **Do not build as knowledge** (claim Y N/A; W6) | No RCT for auto-extract; inherits free-text→belief failure mode (Q3 / refused text→mastery) |
| Concept + prerequisite graph | **Keep** (claim X) | Standard ITS sequencing; already shipped |
| Learner constructs a small map | **Build as activity** (Q6 moderate; W3.5) | Evidence is for *constructing*, not for the system inventing propositions |

Phrase for product/docs: “Connect these ideas” — generative core cousin (W1.3), not a second knowledge store.

---

## 3. Integrity rules (hard)

1. **No mastery from free-text links.** Drawn edges, edge labels, or any prose about the map never update `p_known` / FSRS / misconceptions.
2. **No `graph_edges` / `apply_graph_update` from this feature** in stub or phase-b structure check. A later graded structure item may emit ordinary **check evidence** on concept ids if product defines a keyed topology score — still without inserting student-drawn edges into the course graph.
3. **No auto-extract** of propositions or reasoning chains from tutor chat into stored ontology.
4. **No flag required for stub** — presentational + local state; safe without `learning_loop` population enables. Do **not** invent a new feature flag just to show chips.
5. **Hide-flag:** stub lives on Learn wrap-up only; do not add Study/Quiz/Tree nav destinations. Existing wrap-up handoffs stay hide_* gated (`ClosePanel` / `learningHandoffs`).

---

## 4. Recommended UI surface

| Option | Fit | Notes |
|---|---|---|
| **Learn wrap-up (`ClosePanel`) — preferred for stub** | High | Session already closed; mirrors self-eval “nothing is saved”; 2–3 concepts from `close.concepts` are a natural chip set. |
| SessionPanel rail | Lower for v1 | Competes with SessionMap (system graph); easy to confuse “my sketch” with “the course map.” |
| Tree | No | Tree is the durable course graph; overlaying drafts risks belief errors. |
| Quiz Sort/Label kit | Different job | Interactive kits grade into short_answer; mini-map is reflection first. Phase b structure check could later reuse kit patterns **without** graph writes. |

**Stub UX (landed):** up to three concept chips → click A then B to add an undirected edge → list edges locally → clear / remove. Caption: just for you, nothing is saved.

---

## 5. Acceptance: stub (W3.5a) vs full (W3.5b+)

### Stub (a) — this spike

| Criterion | Done when |
|---|---|
| Spike doc | This file |
| Presentational UI + testids | `LearnerMiniMapStub`; wrap-up mounts when 2–3 concepts |
| Client-only state | Unmount / navigation discards edges |
| No graph / mastery writes | No service calls from the stub |
| Unit test | Connect + remove + no network |

### Full (b+) — later, not this PR

| Criterion | Constraint |
|---|---|
| Occasional prompt cadence | Product: after multi-concept sessions / combine-ideas dial — not every wrap-up forever |
| Optional graded **structure** check | Score topology vs a staff/model key if desired; evidence = graded check only; **never** upsert learner edges into `graph_edges` |
| Persistence of sketches (if ever) | Separate low-trust store or ephemeral only; never mastery input |
| E2E | Journey asserts local connect + absence of graph mutation |

---

## 6. Code landed (W3.5a)

| File | Change |
|---|---|
| `frontend/src/components/learn/LearnerMiniMapStub.tsx` | Chips + local edges |
| `frontend/src/components/learn/LearnerMiniMapStub.test.tsx` | Vitest |
| `frontend/src/components/learn/ClosePanel.tsx` | Section when `concepts.length ≥ 2` (stub caps chips at 3) |
| `docs/frontend-testids.md` | `loop-close-minimap*` |

**Out of scope here:** SessionMap/Tree changes, flags, backend routes, `apply_graph_update`, proposition schema.

---

## 7. Pointers

- design_choices **Q6** — `docs/research/learning-loop/notes/direction/design_choices.md`
- amendments Alvar table — narrowed “Persistent knowledge graphs” → this spike
- plan W3.5 + Day 9 #6 — `alvar-trilogy-implementation-plan.md`
- W6 refusals — free-text→mastery, proposition ontology as knowledge
