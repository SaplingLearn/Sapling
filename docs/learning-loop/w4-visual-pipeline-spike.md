# W4 spike — Visual / SVG / demo pipeline & teach-prose trust

**Status:** spike (docs only — no production visual pipeline code)  
**Plan rows:** Alvar trilogy W4 / claims **AC**, **AD**, **AE**, **L**, **AR**  
**Branch context:** `feat/learning-loop-reland`  
**Date:** 2026-11-23

---

## Verdict

Sapling already has **structure visuals** (knowledge graph), **verified structured figures** (study-guide charts), **RAG grounding** (quiz + tutor material tools), and a **`visual` surface label** on varied check items that means “diagram described in words” — not a drawable asset. It does **not** have Alvar-style SVG/demo subagents, teach-turn figure slots, or student-facing “grounded / key verified” chrome on Learn.

**Product-safe path to A+:** ship trust chrome + grounded teach cites first; only then an optional fail-closed SVG/figure agent. Do **not** treat unverified generated diagrams as authority, and do **not** open student-editable teaching prompts (settled refusal AN).

**Bottom line after W0:** first build = **Stage 1 + 2** (grounded figure *slots* in teach prose + cite / “Key verified” chrome). Defer Stage 3 (SVG agent) until those are eval-gated and dogfooded.

---

## 1. What Sapling already has

### 1.1 Knowledge graph (structure, not lesson figures)

| Piece | Where | What it gives W4 |
|---|---|---|
| Course graph API + mastery | `services/graph_service.py`, Tree / SessionMap | Persistent structure (claim X); covered-vs-understood is W3.2, not figures |
| Hand-drawn blob SVG nodes | `frontend/src/lib/graph/blobShape.ts`, `nodeStyle.ts` | Sandboxed product SVG for *concepts*, not for teaching diagrams |
| Plan dependency view | W3.1 spike + `prereq_edges` | Structure UX; irrelevant to AC/AD |

Reuse: graph chrome patterns (testid, a11y, no raw script). Do **not** overload SessionMap as the teach-figure surface.

### 1.2 Study guide markup (closest existing “figure pipeline”)

| Piece | Where | Relevance |
|---|---|---|
| Typed blocks (`ChartBlock`, `FormulaBlock`, `ConceptMapBlock`, …) | `backend/models/study_guide.py` | Structured, bounded output — not free SVG |
| Markup + `[S1]` citations | `services/study_guides/markup.py` | Cite-or-drop pattern for prose |
| Verify before save | `services/study_guides/verify.py` | Chart numbers must appear in cited sources or chart is forced `illustrative` (no axis numbers) |
| Deterministic chart SVG | `frontend/.../studyGuide/reader/blocks/ChartSvg.tsx` | Server-shaped data → safe SVG; no model-authored `<script>` |
| Agents | `agents/study_guide.py` + slots `study_guide` in `_providers.py` | Separate product surface; hide-flaged; not LoopLearn |

**Reuse for W4:** citation grammar, fail-closed verify, “illustrative vs sourced” honesty, deterministic render from typed data.

### 1.3 Quiz (grounding + item trust, not demos)

| Piece | Where | Relevance |
|---|---|---|
| Course-material grounding | `services/quiz/grounding.py`, `generation.py` | Attempt-level `chunk_ids` / `rag_grounded`; model does not claim per-item cites |
| Item gates (align + blind solve) | `quiz_item_gates`, `check_items_*` / `quiz_check` slots | **Item** trust (claim M) — already the integrity bar W4.4 should surface, not invent |
| Question markdown | Quiz shell + `MarkdownChat` | KaTeX / mermaid available in chat-like surfaces; loop checks are mostly plain / structured |

### 1.4 Tutor / Learn teach prose (text-only turns today)

| Piece | Where | Gap |
|---|---|---|
| Structured turn | `key_idea` / `body` / `question` (`agents/loop_tutor.py`) | No figure field; ≤5 sentences; latex gated by ceiling |
| Material tools | `search_course_materials`, `read_graph_neighborhood` (`_build_tools(learning_loop=True)`) | Can *read* passages; nothing requires citing chunk ids in the served turn |
| Retrieval seam | `agents/tools/retrieval.py` | Eval-injectable; any grounded-cite mode must stay fixture-friendly |
| Varied `surface_representation=visual` | `learning/surface.py`, `params.SURFACE_REPRESENTATIONS` | Enum + familiarity dial only; prompt says “diagram, graph or table **described in words**” |
| Chat mermaid / plot | `frontend/src/components/chat/MarkdownChat.tsx`, `MermaidBlock.tsx` | `securityLevel: "strict"` but still `dangerouslySetInnerHTML` on mermaid SVG — **not** an acceptable default for LoopLearn figures |

**Scoreboard today:** L / AR ≈ **B**; AC / AD / AE ≈ **D**.

### 1.5 Agent slots (no visual slots yet)

Learning-loop slots in `agents/_providers.py::_DEFAULTS` stop at tutor / grader / check_items / session_close. There is **no** `figure`, `svg`, `visual_verify`, or `grounded_teach` task. W4.5 would add scoped slots + function-mode handlers (`agents/function_handlers_e2e.py`) and Claude eval membership like every other request-path agent — **after** W0 clears the pending Claude set so new slots do not join an already-blocked eval backlog without a plan.

---

## 2. Alvar-style gap vs product-safe options

| Alvar harness (V3) | Sapling product-safe substitute | Why not byte-copy |
|---|---|---|
| Free SVG / interactive demos mid-teach | Typed figure payloads (chart / mermaid-from-schema / attached source figure) rendered by deterministic or sandboxed clients | XSS, wrong-diagram authority, cost |
| Researcher / PDF / SVG / demo **subagent swarm** | At most 1–2 scoped slots (draft figure; verify against claim/key) behind flags | Complexity, spend, integrity; plan W4.5 already narrows AE |
| “Trust the AI” / unvetted visuals | “Grounded in your materials” / “Key verified” / illustrative fallback | Direction audit: positive tutor evidence is **solution-grounded** / vetted |
| Student-editable teaching philosophy | Staff / flag prompt variants only | Settled refusal **AN** / W6 |

**Gap that is real and worth closing:** teach turns can invent prose (and someday diagrams) that contradict course chunks; students cannot see which checks were gate-verified; `visual` isomorphs never show a figure.

**Gap that is spectacle, not pedagogy:** Alvar’s demo subagents as a personal research swarm. Out of scope for A+.

---

## 3. Proposed stages

Ship order matches integrity: **ground + show trust before generate.**

### Stage 1 — Grounded figure *slots* in teach prose (W4.1 narrowed first slice)

**Intent:** Extend the teach turn shape with an optional figure *reference* that is either (a) empty, (b) a typed, server-validated block grounded in retrieved chunk text, or (c) “described in words” only (today’s `visual` behavior).

| Decision | Proposal |
|---|---|
| Payload | Prefer study-guide-like typed JSON (`chart` / `formula` / later `diagram_spec`) over raw SVG strings |
| Source | Must bind to retrieved `chunk_id`(s) or explicit “no figure” |
| Render | LoopLearn dedicated component; reuse ChartSvg patterns; **forbid** free mermaid fences in loop serve path until Stage 3 sandbox exists |
| Flag | e.g. `loop_teach_figures` (default off; variants[0]=`off`) |
| Acceptance sketch | Visual isomorph or teach turn can attach a slot; empty/fail → text-only; sandboxed; no raw script |

**Not in Stage 1:** generative SVG agent, interactive demos, PDF researcher.

### Stage 2 — Verify / cite chrome (W4.3–W4.4; claim L + AR)

**Intent:** Make engineered trust visible without “trust the AI” copy.

| Piece | Proposal |
|---|---|
| Grounded teach mode | Optional: teach `body` must cite retrieved chunk ids; contradiction → rewrite or withhold (fail closed to text / skip figure) |
| UI chips | “Grounded in your materials” when cites present; “Key verified” when posed check passed item gates (reuse quiz/check_items status — do not invent a second verifier). **Shipped:** W4.3 `materials_grounded` (teach/opener); W4.4 `key_verified` on `_pose_payload` when `check_items.canonical_verified` (CheckCard `loop-key-verified`). **Shipped:** honest `title` / `aria-label` tooltips (`frontend/src/lib/loopTrustChrome.ts`) — no “trust the AI”. Cite chips / figure slots still deferred. Servable ≠ verified — chrome keys only on the confirmed-key flag. |
| Flag | e.g. `loop_grounded_teach` (default off); chrome can ship earlier read-only for already-verified items |
| Eval needs | New cases: cite present when materials returned; withhold/rewrite on planted contradiction; no leak regression on H ladder; cost budget logged |
| E2E | Chip testids; flag-off = no chrome / no cite requirement |

Stage 2 can start **without** Stage 3 and already moves L/AR toward A+.

### Stage 3 — Optional SVG / figure agent (W4.1 remainder + W4.2 + W4.5)

**Intent:** Only when Stages 1–2 hold: a scoped agent drafts a typed figure from source passages; a **visual verify** agent checks it against the item key / source claim; fail → text fallback (never serve as authority).

| Piece | Proposal |
|---|---|
| Slots | e.g. `loop_figure` (draft) + `loop_figure_verify` (independent model family / effort, same spirit as `check_items_solve`) |
| Render | Prefer SVG-from-typed-spec or sanitized mermaid in a sandboxed path; never executable script; CSP-compatible |
| Flag | e.g. `loop_svg_figures` nested under / after `loop_teach_figures` |
| Integrity | Unverified figure never appears as “Key verified”; illustrative label if soft-pass; hard fail → omit |
| Eval | Visual claim vs source; wrong-diagram detection; serve-path function handlers |
| Effort | **XL** epic; separate from #866 |

---

## 4. Flags, eval needs, integrity risks

| Flag (proposed names) | Gate | Risk if shipped early |
|---|---|---|
| `loop_grounded_teach` | W0 tutor Claude evals green; new grounded-cite cases | Prompt-hash drift; cost; false “grounded” if chunk ids are decorative |
| Chrome-only (verified item chip) | Can follow W5.E3 item gates | Lying chrome if gates off |
| `loop_teach_figures` | Stage 1 schema + render + E2E | XSS if raw SVG/HTML; mastery contamination if figure replaces graded check |
| `loop_svg_figures` | Stage 3 slots + verify eval | Authoritative-looking wrong diagrams; Bastani-style overtrust |

**Integrity risks (must keep in invariants / amendments when building):**

1. Figures and cites are **never** mastery evidence (same as chat / self-explain).  
2. Fail closed: bad verify → text / illustrative / omit — never “mostly fine.”  
3. No student-authored system prompts or per-student “teaching philosophy” (AN).  
4. Loop serve path must not open a weaker XSS surface than Study Guide / inert markdown profiles.  
5. New agents join `_providers` + function handlers + eval floors; do not enable on students until W0/W5 discipline applies.

---

## 5. Explicit non-goals

| Non-goal | Reason |
|---|---|
| Student-editable teaching / system prompts | Integrity + settled AN |
| Unverified generated diagrams as authority or mastery signal | Wrong-diagram + Bastani overtrust |
| Full Alvar researcher / PDF / demo subagent swarm | Scope; AE narrowed to W4.1–W4.3 needs |
| Raw model SVG / HTML with scripts in LoopLearn | XSS |
| Replacing graded checks with “look at this demo” comprehension | Evidence rules (graded-only belief) |
| Dictation / mic think-while-reading | AO; separate product decision |
| Proposition-chain ontology as graph | Y; W3.5 substitute only |

---

## 6. Effort & dependency on W0

| Slice | Effort | Depends on W0? | Notes |
|---|---|---|---|
| This spike (docs) | S | No | Done |
| Stage 2 chrome for already-verified checks | S | Soft (copy only) | Useful once `quiz_item_gates` / check bank verify exist for the student |
| Stage 2 grounded-cite teach | L | **Yes** — re-record `loop_tutor*` after prompt/schema change | Same W1-style eval discipline |
| Stage 1 typed figure slot + ChartSvg-class render | M–L | **Yes** if turn schema / tutor prompt changes | Can stub UI against fixtures before live agents |
| Stage 3 SVG agent + visual verify | XL | **Yes** + new slot evals | Separate epic; after Stage 1–2 dogfood |

**W0 relationship:** W4 does not unblock flag rollout. W0 unblocks *changing* `loop_tutor` prompts/schemas and adding Claude-gated slots. Building Stage 3 before W0 adds more pending slots on an already-red eval seam. Plan dependency graph already places W4 after W0 on the “harness spectacle” path.

Rough roll-up (unchanged from plan): **W4 overall XL**; critical path to spectacle A+ = W0 → Stage 2 → Stage 1 → Stage 3.

---

## 7. Recommended first build after W0

1. **Stage 2 (W4.3–W4.4):** grounded-cite teach mode (flagged) + student chrome for “Grounded in your materials” / “Key verified” — no SVG agent.  
2. **Then Stage 1:** optional typed figure slot on teach turns, sourced from chunks, ChartSvg-class render, text fallback.  
3. **Only then Stage 3:** `loop_figure` + `loop_figure_verify` slots, sandboxed SVG, fail closed.

**Do not start:** production SVG pipeline, mermaid-as-default in LoopLearn, or student prompt editors.

---

## 8. References

- Plan W4: [`alvar-trilogy-implementation-plan.md`](alvar-trilogy-implementation-plan.md) §4 W4, scoreboard AC/AD/AE/L/AR  
- Non-goals: [`amendments.md`](amendments.md) Alvar adopted / narrowed / refused table  
- Surface dial: `backend/learning/surface.py`  
- Study-guide verify + ChartBlock: `services/study_guides/verify.py`, `models/study_guide.py`  
- Tutor tools / turn shape: `backend/agents/loop_tutor.py`  
- Slots: `backend/agents/_providers.py`  
- Direction audit (grounded / vetted tutors): `docs/research/learning-loop/2026-11-07-direction-audit.md`
