# W7.D3 — Quiz launcher + Map design

**Status:** resolved for W7.3 / W7.10 (2026-11-23)  
**Branch:** `feat/learning-loop-reland`  
**Inputs:** `w7-design-decisions.md` (W7.D1 #1 accent, #5 empty course), `w7-d2-hub-guide-settings.md` (home *is* the launcher; no second ranking), `quiz-shell-port-map.md` §2–§4, plan § W7.3 / W7.10, production `home/QuizHome.tsx` + `LiveNeighbourhood` + `HomeStates`  
**Design frames (reference only):** kit / HANDOFF step 10 — List + Map; work visual polish on **copies**. Production never invents a MATH 151 concept inventory.

Closes step-10 product questions so W7.3 can wire Start/Adjust to the plan and W7.10 can swap in a Tree-grade Map without a parallel ranking brain or a fake course list. Pixel Map chrome and graph-prop wiring stay in **W7.10**; this doc is the **integrity + layout contract**.

---

## Decisions table

| # | Question | Decision | Rationale (tokens + loop) | W7.3 / W7.10? |
|---|---|---|---|---|
| 1 | Is there a separate `/quiz/launcher`? | **No.** Quiz home **is** the launcher (`QuizHome` / `useQuizHome`). Hub header Quiz already opens course home with no `start=1` (W7.D2 #1). Do not add a route or a second plan client. | Port-map + D2 integrity: one ranking path. A new route would fork deep links (`buildQuizHref`) and resume. | **W7.3 — keep home; copy may say “launcher”** |
| 2 | Layout: concept list + Map | **Two browse modes over the same home grid.** **List (default):** today’s two columns — lead `ProposalCard` (copy + Start / Adjust) with `LiveNeighbourhood` under it; right = `TopicsColumn` (course pills + search + plan-aware rows). **Map:** keep the **same lead** (proposal + Start / Adjust); replace the right column with a course-scoped full graph using `KnowledgeGraph2D` + `ConceptNode` (Tree’s renderer / marks — same as W7.10 acceptance). One List \| Map control on the topics/Map pane; do not nest a second proposal. | HANDOFF “list + Map” without duplicating the Start surface. Neighbourhood stays List-mode orientation (already Tree-backed). Full Map is browse, not a third ranking. Mobile: stack lead above list/Map (existing `quiz-home__grid` behaviour); Map pane gets a bounded height (exact CSS → W7.10). | **W7.3 — List stays; W7.10 — Map pane + toggle** |
| 3 | What does Map render? | **The student’s real course graph** for the active course filter (or all enrolled courses when filter is All — same node set `TopicsColumn` would list). Mastery fill / tiers from existing graph data; optional practiced outline when W3.2 encoding is ready on this surface. **Not** a demo MATH 151 subgraph, **not** a plant-stage kit, **not** a second `ConceptNode` skin. | Same integrity as Tree / SessionMap. Fake nodes break belief and the empty-library hard rule. | **W7.10 — reuse Tree components** |
| 4 | Empty / new-course / no-data | **Honest `HomeStates` only.** No courses → `noCoursesState`. Enrolled but empty tree → `emptyTreeState` (Library / Learn CTAs). Load error → `errorCard` + Retry. All concepts “good” with no proposal → `masteredState` while the list (or Map) still shows every concept. **Never** seed a production MATH 151 list. Design fixtures may show only Derivatives / Chain Rule (or rich-seed / catalog concepts that already exist). | W7.D1 #5 + port-map hard rule. Empty library ≠ fake concepts. Blocks empty-course *polish*, not shell chrome. | **W7.3 — keep HomeStates; W7.10 — Map empty = same states, no ghost nodes** |
| 5 | Start | **Primary CTA on the lead card** starts the **current card** (plan suggestion, deep-link arrival, or a list/Map pick) via existing `startCard` / queue helpers. `?start=1` deep links unchanged (Hub Focus, Guide, Due Reviews). Forest for the Start button (W7.D1 #1); course colour only on identity chips / concept tint. | One start seam (`useHomeCard` / `useQuizSession`). Mid-session XP stays off the home chrome. | **W7.3 — pass planned concept ids when `home.planned`** |
| 6 | Adjust | **Same `AdjustDialog` + `lib/quiz/prefs.ts`** (Length / Difficulty / Answers / Format). Opens from the lead; Start-from-Adjust remembers prefs then starts the **current** card. Settings Quiz subsection (W7.D2 #7) shares that store — no third prefs path. | Avoid home vs Settings drift. | **W7.3 — already; keep** |
| 7 | How Map selection feeds Start | **Select → pick, not auto-start.** Clicking a quizzable Map node calls the same `proposal.choose(id)` as a topic row: lead updates (title, plan line, neighbourhood when back on List), Start/Adjust target that concept. Course hubs / non-quizzable nodes ignore. **Explicit Start** (or an existing `?start=1` link) begins generation — Map click alone does not. Optional later: node “Quiz” affordance that is still `choose` + `startCard` (not a new API). | Matches today’s neighbourhood click behaviour (`LiveNeighbourhood` → `onPick`). Auto-start on every node click would fight Adjust and accidental taps. | **W7.10 — wire `onNodeClick` → `choose`; Start stays on lead** |
| 8 | Ranking / plan | **Only `getQuizPlan` / `useQuizHome`** (flag `learning_loop` + `quiz_concept_plan`). List order and “suggestion” stay `rankFromPlan` / tier fallback. Map may **highlight** plan-ranked / due nodes but must **not** invent a Map-local sort or a parallel recommend call. | W7.D2 integrity contract; W8.6 learner-next must stay one family. | **W7.3 — plan wire; W7.10 — highlight only** |
| 9 | Accent | **Forest chrome / course identity split** (W7.D1 #1). Start / Adjust primary / focus rings = `--brand-forest` / `--accent`. `--quiz-accent` = course label, concept pill, Map course identity — not the Start fill. | Multi-course hops must not rebrand CTAs. | **Both — follow D1** |
| 10 | Definitive / Mixed / Conceptual | **Stay omitted** on launcher (W7.D1 #4). | Pedagogy stays in planner / generation. | **Omit** |

---

## Integrity contract (do not break)

```text
GET /api/quiz/plan + useQuizHome   → suggestion + list order + Map highlights
proposal.choose / useHomeCard      → list row click AND Map node select
startCard / AdjustDialog + prefs   → only Start / Adjust entry points
KnowledgeGraph2D + ConceptNode     → Map + LiveNeighbourhood (Tree parity)
HomeStates                         → every empty / error / mastered frame
```

- No `/quiz/launcher`, no second `getQuizPlan` wrapper that re-sorts, no MATH 151 fixture in production bundles.  
- Flag-off: pre-loop tier ranking on the same home; Map still real graph nodes when W7.10 ships.  
- Resume stays `ResumeStrip` on this home (W7.D2 #3) — Map mode does not add a second resume.

---

## Production anchors (today → W7.3 / W7.10)

| Concern | Today | Target |
|---|---|---|
| Launcher surface | `QuizHome` two-column List | Same; + List \| Map on the side pane (W7.10) |
| Plan bootstrap | `useQuizHome` + `getQuizPlan` | Unchanged; Start/Adjust pass planned ids (W7.3) |
| Neighbourhood | `LiveNeighbourhood` under proposal | Keep in List mode |
| Full Map | Absent | Course-filtered `KnowledgeGraph2D` in the side pane (W7.10) |
| Pick | Topic row / neighbourhood click → `choose` | Map node → same `choose` |
| Start / Adjust | ProposalCard + `AdjustDialog` | Unchanged ownership; forest CTA |
| Empty | `HomeStates` | Unchanged; Map never fills ghosts |
| MATH 151 list | Deferred / forbidden in prod | **Resolved:** never invent; seed/catalog or honest empty |

Optional one-line `// W7.D3:` TODOs may point at this file from `QuizHome.tsx` — **no** UI rewrite in the design-doc PR.

---

## Deferred to W7.10 (impl detail)

Leave code-level choices out of this brief; implementers decide against Tree parity:

- Exact List \| Map control component, URL `?view=map` persistence, and a11y labelling.  
- Map pane height, fit-all vs Tree default zoom, 2D-only (no 3D toggle — same as `LiveNeighbourhood`).  
- Wiring `practicedIds` / covered-vs-understood legend once KG props are ready.  
- Multi-course “All” Map layout (single union graph vs per-course sections).  
- Whether Map highlight of plan top-N uses existing plan meters only (no new scores).

W7.3 may ship plan-aware Start/Adjust on **List** without waiting for the Map pane.

---

## Out of scope / pointers

- **W7.D2** — Hub / Guide / Settings entry + prefs (`w7-d2-hub-guide-settings.md`).  
- **W7.D4** — 17.3 clickable prototype (E2E preferred).  
- **W7.1 / W7.1b** — Session forest chrome (already decided).  
- **W7.8** — Practice vs Exam Twin session modes (launcher may later expose a mode control; not required to close D3).  
- **W8.6** — Shared learner-next helper; launcher must consume it, not fork it.

Supersedes W7.D1 #5’s “defer to W7.D3” for **product behaviour** (honest empty; no fake MATH 151). Visual DC Map frames remain optional polish before/during W7.10.
