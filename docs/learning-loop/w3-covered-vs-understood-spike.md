# W3.2 spike — Covered vs understood on SessionMap

**Status:** spike (not full UI)  
**Plan row:** Alvar trilogy W3.2 / claim **AQ** (“Graph shows covered vs understood”)  
**Branch context:** `feat/learning-loop-reland`  
**Date:** 2026-11-23  
**Sibling:** `docs/learning-loop/w3-plan-dependency-spike.md` (W3.1 — PlanPanel owned elsewhere; do not edit)

---

## Verdict (data)

| Source | Grain | Available today? | Role for dual encoding |
|---|---|---|---|
| Graph `GET /api/graph/{userId}` → `mastery_score` / `mastery_tier` | concept | Yes | **Understood** (persisted BKT; what SessionMap paints today via `colorMode="mastery"`) |
| Live `LoopLearnerState` (`p_known`, `band`) in `loopState.learnerState` | concept | Yes (session) | **Understood (live)** once `measured !== false`; Skill meters already prefer this over the map score |
| Keys of `learnerState` (measured only) | concept | Yes | Best **practiced-this-session** proxy — evidence updated skill this turn/session |
| Approved plan + `cursor` (`ApprovedPlan`) | concept | Yes | **Plan progress:** indices `< cursor` = advanced past; `cursor` = current; ahead = not yet. Not the same as “understood” |
| Plan concept ids (whole list) | concept | Yes | “On today’s plan” — scheduled coverage, not practiced |
| Item `seen` / `revealed` hashes | **question** | Server-only in `loop_state` | Wrong grain for SessionMap; do **not** promote to concept “covered” without a new aggregation |
| `concepts_covered` (legacy close / non-loop) | concept names | Legacy | Not wired into loop SessionMap |
| `practicedNodeIds` already computed in LoopLearn | — | **No** | Derivable in one line from `learnerState`; not a named set today |
| KnowledgeGraph / SessionMap multi-outline by id | paint | **No** | Only single `highlightId` pulse + social `comparison` rings (name-matched partner mastery) |

**Bottom line:** Enough data to design dual encoding **without schema work**. Understood = mastery fill (graph tier today; optionally overlay live `p_known`/`band` for plan nodes). Covered/practiced = a **separate channel** (outline / stroke / hatch), sourced preferably from **measured `learnerState` keys** (practiced), with plan-cursor as a weaker “reached in today’s order” fallback. Item-level seen/revealed is not a SessionMap input. Full paint needs KnowledgeGraph2D (or ConceptMark) support — **not** a one-file SessionMap-only change.

**Code landed this spike:** none (no obvious one-file safe paint; see §6).

---

## 1. Current UI (what students see)

| Role | Path |
|---|---|
| Session rail map | `frontend/src/components/learn/tutor/SessionMap.tsx` → `KnowledgeGraph` → `KnowledgeGraph2D` |
| Map key (tiers only) | `SessionPanel.tsx` — `data-testid="tutor-map-key"` + `MASTERY_PALETTE` / `TIER_LABEL` |
| Paint arithmetic | `frontend/src/lib/graph/nodeStyle.ts` (`masteryFillFor`, `tierFor`, `TIER_OPACITY`, …) |
| Live skill vs map | `LoopLearn.tsx` `panelSkills()` — live `learnerState[id].p_known` else graph score |
| Focus ring | `highlightId={mapNodeId}` — current plan cursor / focus only; **not** “covered” |
| Orchestration | `LoopLearn.tsx` builds `railGraph` (course filter); does **not** merge live p_known into node fills |

**Today’s encoding is single-channel:** fill hue = mastery tier. Highlight pulse = “here now.” There is no visual for “we visited / practiced this but skill is still low” (illusion-of-mastery anti-pattern AQ targets).

---

## 2. Definitions (propose for W3.2)

Keep two axes orthogonal; never collapse them into one colour.

| Axis | Meaning for the student | Recommended source (v1) |
|---|---|---|
| **Covered / practiced** | “You engaged this concept with a graded signal this session” | Node id ∈ `Object.keys(state.learnerState)` after measured `learner_state` events (`measured !== false` never lands in the map — see `loopState.ts` K52) |
| **Understood** | “How well the model believes you know it” | Graph `mastery_tier` / `mastery_score` for fill; for plan-row meters, keep preferring live `p_known` / map `band` → tier |

**Do not use as “covered” (v1):**

- Whole plan list (scheduled ≠ practiced).
- Plan cursor alone (advanced-past can mean “moved on after struggle,” still useful as a **secondary** “reached” cue if practiced set is empty early in teach).
- Question-hash seen/revealed (item economy, not concept coverage).

**Band vs tier:** loop `band` is `novice` / `develop` / `profic` (`BAND_NOVICE_MAX` 0.30 / `BAND_DEVELOP_MAX` 0.80). Graph tiers are `unexplored` / `struggling` / `learning` / `mastered` (`tierFor` / `bkt.tier_for`). Fill should stay on the **four mastery tiers** (existing palette + key). Band can caption the learner chip / Skill meters; optional later stroke weight by band — not required for AQ v1.

---

## 3. UX dual-encoding proposal

### v1 (SessionMap + legend)

1. **Fill = understood** — keep `colorMode="mastery"` / `MASTERY_PALETTE` (unchanged semantics).
2. **Outline = covered/practiced** — for each practiced node id, draw a **solid** hand-drawn outline ring (reuse blob path like highlight / ConceptNode growth “before” ring), distinct from:
   - `highlightId` pulse (current step only),
   - `comparison` dashed partner rings (social; wrong semantics — do not reuse for practiced).
3. **Unpracticed nodes:** fill only (today’s look).
4. **Practiced + low mastery:** filled “struggling/unexplored” **with** outline — the AQ tell (“covered but not yet understood”).
5. **Legend (`tutor-map-key`):** keep four tier swatches; add one line/swatch: “Practiced (outline)” — extend SessionPanel legend when the encoding ships (W3.2 implementation; this spike does not edit PlanPanel / prefers SessionMap + key).

### v1.5 (optional)

- Plan-cursor “reached” as a **lighter** dashed outline for `plan[0..cursor]` minus practiced — only if user testing shows practiced-only is too sparse mid-session.
- Live remint of fill from `learnerState.p_known` for practiced nodes so the map doesn’t wait on `refreshGraph` after grade (Skill meters already do this; map currently lags until graph refresh).

### Non-goals

- Do not change Tree / full KnowledgeGraph default mode.
- Do not overload W3.1 plan-deps mini-DAG with this encoding.
- Do not invent concept-level seen from item hashes in the client.

---

## 4. E2E testid plan

Existing (keep):

| testid | Use |
|---|---|
| `tutor-session-map` | SessionMap root |
| `tutor-map-key` | Mastery tier key |
| `graph-node-highlight` | Current-concept pulse (KG2D) |
| `loop-rail` | Session panel |

Add for W3.2:

| testid | Where | Assert |
|---|---|---|
| `tutor-map-practiced-{nodeId}` | Outline mark on a practiced concept (KG2D / SessionMap) | Present after measured learner_state for that id |
| `tutor-map-key-practiced` | Legend row for outline = practiced | Present when dual encoding on |
| `tutor-map-understood-{tier}` | Optional; only if tier swatches need stable ids | Prefer keep existing key `<li>` text unless E2E needs ids |

Journey sketch (`learn-loop.spec.ts` or sibling):

1. Start loop → teach → grade a check that emits measured `learner_state` for concept A.  
2. Expect `tutor-map-practiced-{A}` and tier fill still readable (not “mastered” solely from visit).  
3. Advance cursor without measuring B → B has highlight when current, **no** practiced outline until measured.  
4. a11y: key names both channels; map `aria-label` / title text can mention practiced vs mastery if tooltips gain copy.

---

## 5. Effort estimate (full W3.2)

| Slice | Size | Notes |
|---|---|---|
| Derive `practicedNodeIds` in LoopLearn; pass into SessionMap | XS | `new Set(Object.keys(state.learnerState))` |
| KnowledgeGraph (+2D) prop: outline set by node id | S–M | New prop; do not hijack `comparison` |
| SessionMap forward prop + SessionPanel legend row | S | Legend is SessionPanel (allowed for ship; spike avoided editing it) |
| Optional live fill from `p_known` for practiced ids | S | Avoids graph-refresh lag |
| Unit tests (SessionMap + KG highlight twin) | S | |
| E2E + `docs/frontend-testids.md` | S | |
| **Total full W3.2** | **~1.5–2.5 eng-days** | **M** as planned |

**Dependencies / risks**

- Practiced set is **session-UI memory** today — resume must rehydrate measured learner_state (turns/`/status` paths) or outlines vanish on reload; confirm restore coverage before E2E.  
- Sparse early teach: few outlines until first grades — legend still explains empty outline channel.  
- W7.10 launcher map should reuse the same prop once KG supports it.

---

## 6. Code landed in this spike

| Change | File |
|---|---|
| — | **None** |

**Why not a one-file prop?**

- LoopLearn does **not** already hold a `practicedNodeIds` set — only raw `learnerState`.  
- SessionMap → KnowledgeGraph has **no** multi-id outline API; accepting an unused optional prop is dead surface.  
- Misusing `comparison` rings would paint the wrong metaphor (partner mastery, name match, dashed).  
- Safe paint needs KG2D (+ likely SessionPanel legend) — outside “SessionMap / nodeStyle only” one-file scope.

**Recommended first implementation PR:** KG2D `practicedIds?: ReadonlySet<string>` (or `string[]`) + SessionMap forward + LoopLearn one-liner + legend row + unit test; then E2E.

---

## 7. Recommended next PR (implementation)

1. Add id-based practiced outline to `KnowledgeGraph2D` (solid ring; testids).  
2. `SessionMap({ …, practicedNodeIds? })` forwards to KG.  
3. `LoopLearn`: `practicedNodeIds={new Set(Object.keys(state.learnerState))}` (or memo).  
4. Extend `tutor-map-key` with practiced outline swatch.  
5. Unit + Playwright + testid doc.  
6. Defer cursor-as-covered and live fill remint to a follow-up if needed.
