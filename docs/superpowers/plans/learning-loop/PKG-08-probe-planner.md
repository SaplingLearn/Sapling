# PKG-08 probe-planner — Learning Loop series (11 of 17)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> You are a fresh session. Nothing outside this file, `docs/superpowers/plans/learning-loop/LEDGER.md`, the `HANDOFF-NN.md` files this prompt names, and the files this prompt lists is known to you. Do not infer intent from chat history you do not have. Do not read the whole research corpus; read the sections named below.

## Package id + goal

**PKG-08 `probe-planner`.** After this package: a loop session opens with a *probe* — 4–6 adaptive check items per skill aimed at the probe success band, stopping when belief stabilises, capped per session, with a novice floor — and moves into a *plan* the student approves: the outer fringe of the prerequisite graph (concepts whose prerequisites are all proficient), due reviews first, new material next, interleaved siblings last, coupled concepts capped. `learning/probe.py` and `learning/planner.py` are pure. Four routes under `/api/learn/loop/` drive the two phases. `/probe/next` never serves a concept's post-test reserve item (A23) and answers `no_check_items: true` for a course without check items. `/probe/answer` grades through PKG-05's `grade_answer` (A16, with the A22 pre-checks; no LLM tutor turn), treats an `unavailable` grade as "not asked" (no evidence for either outcome), and persists evidence through `apply_graph_update` exactly once. The probe keeps running at every budget level (A20: grading has its own cap inside the grader). Two events join the taxonomy. `tests/test_learning_probe_planner.py` proves it; `test_inv_16` proves the two modules stay pure; `/probe/answer` joins invariant 26's explicit-submission allow-list.

Branch: `feat/learning-loop-08-probe-planner`. PR title: `feat(learning): PKG-08 probe-planner`.

Depends on (spec §14): PKG-07 (and 04, 05, 06b through it). Runs after PKG-07 and before PKG-09 in the strict one-at-a-time order `00, 01, 02, 03, 04, 05, 05b, 06, 06b, 07, 08, …, 14`.

## Read before you start (in this order)

0. `docs/superpowers/specs/2026-09-26-learning-loop-design.md` **§13 Amendments log** — in force; where this file and §13 disagree, §13 wins. Re-read it before Task 1. Rows that change this package: A1 (idk), A2 (items keyed on `course_id`/`concept_key`), A13 (goal filter), **A16** (grade in the route through `grade_answer`), A19 (PKG-09 reopens `/plan/approve`), **A20** (the probe under the caps), **A22** (pre-checks, `mc_reason` options, symmetric missingness), **A23** (post-test reserve, revealed set, `course_has_items`), **A27** (`/plan/approve` stores `plan.cursor` and the current `concept` that PKG-07's item activation reads).
1. The same spec's §3.5–§3.6 (cost/routing/decision constants), §7 (two-phase gate), §8 (invariants 13–29), §14 (order and dependencies).
2. `docs/superpowers/plans/learning-loop/LEDGER.md` — a package's state is its LATEST row (README "Ledger reading"); refuse to start if any earlier package's latest row is `blocked` or `in-progress`. The latest rows of 00–07, 05b and 06b must be `done`, `verified` or `reopened`.
3. `docs/superpowers/plans/learning-loop/HANDOFF-07.md`, then `HANDOFF-06b.md`, `HANDOFF-05b.md`, `HANDOFF-05.md`, `HANDOFF-04.md`, `HANDOFF-03.md`, `HANDOFF-02.md`, `HANDOFF-01.md` — the "Symbols added" and "Post-hoc changes" sections. You bind to their symbols in Task 2 Step 0; their exact names are recorded there, not here.
4. `CLAUDE.md` §Conventions and §Gotchas — the standing rules the "Do not" list below repeats.
5. `docs/superpowers/specs/2026-09-26-learning-loop-design.md` §3.1 (channel table, propagation paragraph with `EDGE_PREREQ_SOURCE_IS_PREREQ`), §3.3 (success bands table — the `probe` row; slip/misconception/novice rule — the last bullet), §3.4 (`PROBE_*`, `PLAN_*`), §3.5 (degradation ladder — the hard-level "keep working" list names probe selection; the grader-cap row; the validity rule), §4 (the `check_items` DDL — `options_json`, `correct_option`), §5 (`Evidence`: `idk`, `grader_backend`), §6 (`learn.probe_done`, `learn.plan_approved` payloads), §7 (the 404 rule), §8 (invariants 2, 5, 22, 26, 28), §9 (phases; the rate-limit rule for loop routes).
6. Research, only these headings: `docs/research/learning-loop/AI tutor learning loop research.md` §"Probe: 4–6 adaptive items…" (:62–66) and §"Plan: teach at the outer fringe…" (:68–70); `docs/research/learning-loop/ZPD lever tradeoffs and upgrades.md` §"Sapling ZPD policy spec" SUCCESS BANDS block (:186–192). Nothing else.
7. `docs/superpowers/plans/learning-loop/README.md` and `HANDOFF-template.md`.
8. Code you will modify: `backend/routes/learn_loop.py` (whole file as PKG-07 left it — find the gate helper, the loop-state read/write, the evidence flush, the body models it imports), `backend/services/events_service.py:97–168` (`EVENT_TAXONOMY`, last entry `"rag.visibility_resync_failed"`), `backend/tests/test_event_capture_seams.py:84–125` (`test_event_taxonomy_is_pinned`), `backend/tests/test_learning_loop_invariants.py` (`PURE_MODULES` tuple, test list, the explicit-submission allow-list of PKG-07's `test_inv_26_evidence_only_from_explicit_submission`), `backend/learning/params.py` (PKG-01's constants; you add four † names).
9. Code you will read, not modify: `backend/agents/tools/check.py` (`grade_answer`, `CheckAnswer`, `GradeOutcome`, `CHANNEL_FOR_FORMAT` — PKG-05, routed through the decision seam by PKG-05b), `backend/learning/checks.py` (`CheckItem`, `posttest_reserve_hash`), `backend/services/check_item_service.py` (`list_items`, `course_has_items`), `backend/services/ai_budget.py` (`rate_limited`, `enforce_rate_limit` — PKG-06b), PKG-07's `/check/answer` handler in `backend/routes/learn_loop.py` (how it builds `SaplingDeps`, calls `grade_answer`, and attaches the rate limit — the pattern `/probe/answer` copies), `backend/services/graph_service.py::_normalize_concept`, `backend/services/graph_service.py:848–880` (edge upsert — `source_node_id`/`target_node_id`/`relationship_type` columns, no direction semantics), `backend/agents/tools/graph_read.py:237–265` (depth-1 edge read — both columns queried, edges rendered by name, no direction interpreted), `backend/services/graph_context.py:142–150` (renders `source → rel: target`), `backend/db/migrations/0023_graph_integrity.sql:43` (the `relationship_type` CHECK: `related`,`prerequisite`,`builds_on`,`part_of`), `backend/db/seed_local_rich.py:282–295` and `backend/db/seed_staging.py:206–212` (the only prerequisite edges with human-readable endpoints — Task 3 Step 0 uses them), `backend/services/academics.py` (defs at :36, :55, :63, :79, :101, :179, :193, :242, :288, :306, :315, :406 — none maps a syllabus week to concepts; see Non-goals), `backend/routes/learn.py:1474–1480` (`require_self(body.user_id, request)` pattern), `backend/tests/conftest.py:254–312` (`_hermetic_supabase_client`) and `:366–420` (`_bypass_session_auth`), `backend/tests/test_graph_service.py:24–60` (`_mock_table`, `_cached_mock_table`), `backend/main.py:274–299` (router mounts; PKG-07 mounted `learn_loop` here — verify).

## State of the world

Run every row before Task 1. Each is a dependency's canonical verify line (the PKG-00, PKG-03, PKG-05 and PKG-07 blocks, copied verbatim; PKG-04, PKG-05b and PKG-06b are verified by the packages that consume them directly and reach this one through PKG-05 and PKG-07).

| pkg | command | expected |
|---|---|---|
| 00 | `cd backend && venv/bin/python -m pytest tests/test_learning_gate.py -q` | `13 passed` |
| 00 | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q` | `4 passed, 8 skipped (later packages raise the passed count)` — expect the passed count ≥ 10 now |
| 00 | `cd backend && venv/bin/python -m pytest tests/test_learning_deps.py tests/test_learning_settings_flag.py tests/test_learning_loop_beta_migration.py -q` | `all passed` |
| 00 | `grep -n "^LEARNING_LOOP_ENABLED" backend/config.py` | `1 hit` |
| 00 | `ls backend/db/migrations/*_learning_loop_beta.sql` | `1 file` |
| 03 | `cd backend && venv/bin/python -m pytest tests/test_learning_evidence_apply.py tests/test_graph_service.py -q` | `all passed` |
| 03 | `ls backend/db/migrations/*_learning_learner_state.sql` | `1 file` |
| 03 | `grep -c '"evidence"' backend/services/graph_service.py` | `≥ 1` |
| 03 | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k inv_01` | `1 passed` |
| 05 | `cd backend && venv/bin/python -m pytest tests/test_learning_check_tool.py -q` | `N passed (N ≥ 16)` |
| 05 | `grep -c '"grader"' backend/agents/_providers.py backend/agents/function_handlers_e2e.py` | `≥ 1 each` |
| 05 | `grep -c '"grader_second"' backend/agents/_providers.py backend/agents/function_handlers_e2e.py` | `≥ 1 each` |
| 05 | `grep -c "^async def grade_answer" backend/agents/tools/check.py` | `1` |
| 05 | `ls backend/db/migrations/*_learning_grader_backend.sql` | `1 file` |
| 05 | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_14 or inv_28"` | `2 passed` |
| 05 | `cd backend && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/grader.py` | `every evaluator ≥ baseline` |
| 07 | `cd backend && venv/bin/python -m pytest tests/test_learn_loop_routes.py -q` | `N passed (N ≥ 25)` |
| 07 | `grep -c "learn_loop" backend/main.py` | `≥ 1` |
| 07 | `grep -c '"loop_tutor"' backend/agents/_providers.py backend/agents/function_handlers_e2e.py` | `≥ 1 each` |
| 07 | `grep -ohE '"loop_tutor(_lite\|_deep)?"' backend/agents/_providers.py \| sort -u \| wc -l` | `3` |
| 07 | `grep -c "learning_loop" backend/agents/chat_tutor.py` | `≥ 1` |
| 07 | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_15 or inv_22 or inv_23 or inv_26 or inv_27 or inv_29"` | `6 passed` |
| 07 | `cd backend && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/loop_tutor.py` | `every evaluator ≥ baseline for every tier slot` |
| base | `cd backend && venv/bin/python -m pytest tests/ -q -x` | `… passed`, zero failures (note the count N₀) |
| base | `cd backend && venv/bin/ruff check .` | `All checks passed!` |
| base | `head -3 backend/learning/probe.py backend/learning/planner.py` | both are the PKG-00 docstring-only stubs naming PKG-08 |

Rule: any red row → STOP. Diagnose, repair on this branch as commit `fix(learning-loop): repair pre-series base — <what>`, record the deviation in `LEDGER.md`, re-run all rows. Never build on a broken base. When a row is green, append `07 | loop-tutor | verified | … | PKG-08 <date> <command → output>` to the ledger (only the direct dependency, 07, gets a `verified` row from you).

## Spec

### Behaviour

**Probe (`learning/probe.py`, pure):**

1. `expected_success(p_known: float, item_difficulty: int, channel: str) -> float` — shifts `p_known` by `PROBE_DIFFICULTY_SHIFT[item_difficulty]`, clamps to `[0, 1]`, then returns the BKT observation likelihood of a correct answer on that channel: `p·(1 − S) + (1 − p)·G` with `G, S` from `CHANNELS[channel]` (spec §3.1). For `mc` this is the chance correction; for every channel it is the same formula, no special case. Monotone non-decreasing in `p_known`; strictly ordered by difficulty at fixed `p` when the shift moves `p` inside `(0, 1)`.
2. `next_probe_item(states: dict[str, float], items: Sequence[ProbeItem], asked_hashes: Iterable[str], *, channel_for_format: Mapping[str, str]) -> ProbeItem | None` — candidates are items whose `node_id` is in `states`, whose `question_hash` is not in `asked_hashes`, whose format maps to a channel in `channel_for_format`, and whose node has fewer than `PROBE_ITEMS_PER_SKILL_MAX` asked items (counted over `items` — pass the full candidate list, asked ones included). Returns `None` when `len(set(asked_hashes)) ≥ PROBE_SESSION_CAP` or no candidate remains. Otherwise: prefer candidates whose expected success lies in `[PROBE_TARGET_LO, PROBE_TARGET_HI]`; among those (or, if none, among all candidates) pick the one closest to the band midpoint; ties break on `(difficulty, question_hash)` ascending so the choice is deterministic.
3. `probe_done(history: Sequence[ProbeObservation], *, skills: Iterable[str] | None = None) -> bool` — `True` when `len(history) ≥ PROBE_SESSION_CAP`, or `novice_floor(history)`, or every skill (the `node_id`s in `history`, plus every id in `skills` when given) has either `≥ PROBE_ITEMS_PER_SKILL_MAX` observations or `≥ PROBE_ITEMS_PER_SKILL_MIN` observations with `|p_after[-1] − p_after[-2]| < PROBE_STOP_DELTA`. Empty history → `False`.
4. `novice_floor(history) -> bool` — `True` when the count of observations at `PROBE_EASIEST_DIFFICULTY` that are not correct (an `idk` counts as not correct) is `≥ NOVICE_FLOOR_MISSES`, or the count of `idk` observations is `≥ NOVICE_FLOOR_IDK`. Session-wide, not per skill (spec §3.3 last bullet; the research floor rule classifies the *student* as below the bank).
5. `ProbeObservation` is a `TypedDict` with keys `node_id, question_hash, difficulty, channel, correct, idk, p_after` — JSON-shaped because it lives in `sessions.loop_state`. `channel` is always the item's channel; `idk` flags an explicit "I don't know" (A1: there is no `"idk"` channel). `ProbeItem` is a `Protocol` with `id, node_id, format, difficulty, question_hash` so the module never imports `learning.checks` (it may import it for typing only under `TYPE_CHECKING`; do not).
6. The format → channel map is PKG-05's `CHANNEL_FOR_FORMAT` (`agents/tools/check.py`; HANDOFF-05 records its home): `free → free_response`, `teachback → teachback_llm`, `mc_reason → mc_reasoned`. `probe.py` defines no map of its own and cannot import `agents` (invariant 2), so `next_probe_item` takes the map as the required keyword `channel_for_format`; the route passes PKG-05's map and the tests import the same one. (If HANDOFF-05 records that the map moved into `learning/`, the route and tests import it from there; `probe.py` still takes it as an argument.)

**Planner (`learning/planner.py`, pure over an in-memory graph):**

7. `outer_fringe(states: dict[str, float], prereq_edges: Iterable[tuple[str, str]]) -> list[str]` — edges are `(prerequisite, dependent)` ALREADY oriented by the caller (the route orients raw rows with `EDGE_PREREQ_SOURCE_IS_PREREQ`). Edges with an endpoint outside `states`, or self-loops, are ignored. Returns every node with `p < BKT_PROFICIENT` whose prerequisites all have `p ≥ BKT_PROFICIENT` (a node with no prerequisites qualifies), ordered by `p` descending then `node_id` ascending.
8. `plan(fringe, due_reviews, siblings_fn, goal_filter, *, proficient=frozenset(), max_concepts=PLAN_MAX_CONCEPTS, max_coupled=PLAN_MAX_COUPLED) -> Plan` — `Plan(concepts: tuple[PlanConcept, ...], order: tuple[str, ...] = PLAN_ORDER)`, `PlanConcept(node_id: str, kind: Literal["review", "new", "sibling"])`. Sections are built independently and concatenated in `PLAN_ORDER` (`"reviews"`, `"new"`, `"siblings"`): reviews = `due_reviews` in the given order, deduplicated, passing `goal_filter` (uncapped here — PKG-02's `budget_select` caps them before they arrive); new = walk `fringe` in order, skipping ids already in reviews, failing `goal_filter`, or *coupled* — `≥ max_coupled` already-chosen new concepts appear in `siblings_fn(candidate)` — stopping at `max_concepts`; siblings = for each chosen new concept in order, the first id in `siblings_fn(c)` that is in `proficient` and not yet in the plan (at most one per new concept). `goal_filter=None` means no filter. `siblings_fn(node_id) -> Sequence[str]` returns every node sharing at least one prerequisite parent with `node_id`, any state; the route builds it from the same oriented edges.

**Routes (`routes/learn_loop.py`, PKG-07's router; prefix `/api/learn/loop`):**

9. Every route below first calls PKG-07's gate helper (the one that returns 404 `{"detail": "learning loop not enabled"}` when `learning_loop_active(user_id)` is false — spec §7) and `require_self(body.user_id, request)`. With the gate false no `table()` call happens. **Budget (A20):** no PKG-08 route calls `ai_budget.check` — the probe keeps running at the tutor hard cap and keeps serving novice-band concepts (spec §3.5: the probe is the one surface where novice concepts are still checked at the hard level); grading has its own cap, enforced inside `grade()` (PKG-06b), which surfaces here as an `unavailable` grade (Behaviour 11). `/probe/answer` — the only PKG-08 route that can run a model (the grader) — carries PKG-06b's rate limit (`enforce_rate_limit`, spec §9), attached exactly as PKG-07 attaches it to `/check/answer`; `/probe/next`, `GET /plan` and `/plan/approve` run no model and carry none. No body model carries `model_pref` (invariant 22).
10. `POST /probe/next` body `ProbeNextBody(session_id, user_id, course_id)`. Phase must be `probe` (a fresh loop session's phase, per PKG-07; if PKG-07 starts sessions in another phase, this route accepts `probe` and the PKG-07 initial phase, and records that in the hand-off) else 409 `{"detail": "phase is <phase>"}`. **No check items (A23):** before the skill set is fixed (first call), when `check_item_service.course_has_items(course_id)` is False (one `limit=1` read) → finish the probe (Behaviour 12) with no item read and return `{"done": true, "phase": "plan", "no_check_items": true}` — the A26 empty state; teaching still works, no evidence is written. Otherwise, on first call it fixes the probe skill set: `outer_fringe(states, edges)[:PROBE_MAX_SKILLS]`, stored on `loop_state["probe"]["skills"]`. Candidates = the check items for those skills — A2: node → `concept_key = _normalize_concept(graph_nodes.concept_name)` → `check_item_service.list_items(course_id, concept_key)`, decrypted, each bound to the student's `node_id` — minus, per concept, `checks.posttest_reserve_hash(<that concept's items>)` (A23: the probe never serves the post-test reserve) and minus `loop_state["probe"]["unavailable"]` (Behaviour 11). `asked` = the `question_hash`es in `loop_state["probe"]["history"]`. `item = next_probe_item(states, candidates, asked, channel_for_format=CHANNEL_FOR_FORMAT)`; `None` → finish the probe (Behaviour 12) and return `{"done": true, "phase": "plan"}`. Otherwise store `loop_state["probe"]["current"] = {check_item_id, question_hash, node_id, difficulty, channel}` and return `{"done": false, "check_item_id", "question_hash", "node_id", "format", "difficulty", "prompt", "options"}` — `options` is `[{"letter", "text"}]` from the item's decrypted stored options for `mc_reason` items (A22: never rebuilt from the reference, correctness never marked, no `wrong_key`) and `null` for every other format. Never return `reference_answer`, `rubric_json`/`rubric`, `common_wrong_json`/`common_wrong`, `correct_option`, `canonical_answer`, or any option's `wrong_key`.
11. `POST /probe/answer` body `ProbeAnswerBody(session_id, user_id, course_id, question_hash, answer: str = "", selected_option: str | None = None, reason: str = "", idk: bool = False, confidence: float | None = None)` (`selected_option` + `reason` are the `mc_reason` answer, A22; `confidence` is the student's stated confidence, forwarded only if HANDOFF-05's `CheckAnswer` has a field for it — record which). Rate limit first (Behaviour 9): over it → 429 `{"detail": "ai budget reached", "reset_at": …}`, nothing graded. `question_hash` must equal `loop_state["probe"]["current"]["question_hash"]` else 409. The item is found by `current["check_item_id"]` among the skill set's candidates (one read; the key never leaves the process). Build PKG-05's `CheckAnswer(question_hash, answer_text=answer, selected_option, reason, idk)` and grade through **`grade_answer(item, answer, deps=…, node_id=current["node_id"])`** (A16; HANDOFF-05's canonical signature, bound in Task 2 Step 0 (E)) — the single grading path. It runs the A22 pre-checks (`mc_reason`: option compared in code, the reason check run for both outcomes; `numeric`: never a code-issued "correct"), handles `idk` without a grader call (A1: `idk=True, correct=False` on the item's channel), reaches the grader through the decision seam (PKG-05b; the grader's run site checks the grader cap first, PKG-06b), and returns a `GradeOutcome` whose `evidence` is the one Evidence dict (A22 weight, `grader_backend`). Then:
    - **`outcome.unavailable`** (outage, second opinion unavailable, or the `STUDENT_DAILY_GRADES` cap) → **counts as not asked**: no evidence for either outcome (invariant 28), no `ProbeObservation`, no event from this route (PKG-05/05b/06b own the degrade, fallback and cap events); append `question_hash` to `loop_state["probe"]["unavailable"]` (excluded from selection by Behaviour 10, never counted toward the per-skill or session caps), clear `current`, save, and return 200 `{"graded": false, "unavailable": true}`. The next `/probe/next` serves another item. A correct and a wrong attempt take this path identically.
    - **otherwise** persist `outcome.evidence` unchanged with ONE call to the module-level `apply_graph_update(user_id, {"evidence": [outcome.evidence]}, course_id=course_id)`, made in the `/probe/answer` handler body itself (the invariant 26 allow-list names that handler). `deps.pending_evidence` inside the grading seam is discarded, never flushed — this call is the only write. `p_after` = the node's decayed `p_known` re-read after the write. Append the `ProbeObservation` (`correct` from the outcome, `idk` from the evidence, `channel` = the item's channel) to `loop_state["probe"]["history"]`, clear `current`, then if `probe_done(history, skills=skills)`: emit `learn.probe_done` (Events below) and set phase `plan`. Save `loop_state`. Return `{"graded": true, "correct", "p_known", "probe_done", "novice_floor", "reference_answer"}` where `reference_answer` is present only when `correct` is false — a wrong answer or an `idk` (spec §3.3: wrong → corrective feedback with the answer, immediately). The item is then revealed through its `correct=false` evidence row (A23), so review and the post-test never serve it to this student.
    - `wrong_key` / `matched_wrong_key` on the outcome belong to PKG-10's hook inside `grade_answer`; the route ignores them.
12. Finishing the probe with zero items (no check items in the course, empty fringe, or no candidate for the skill set): emit `learn.probe_done` with `items=0`, phase → `plan`. Only the no-check-items case adds `no_check_items: true` to the response. A probe whose remaining candidates were all `unavailable` finishes the same way with `items=len(history)`.
13. `GET /plan?session_id=&user_id=&course_id=` — phase must be `plan` else 409. `states` = decayed `p_known` for every `graph_nodes` row of `(user_id, course_id)` (PKG-03 read; nodes without a `learner_state` row get `BKT_L0`); `edges` = this user's `graph_edges` rows with `relationship_type = 'prerequisite'`, oriented by `EDGE_PREREQ_SOURCE_IS_PREREQ`; `due_reviews` = PKG-02 `order_due` over the states' FSRS fields, then `budget_select` with `REVIEW_DAILY_BUDGET_MIN`/`REVIEW_SECONDS_PER_CHECK` (node ids only); `goal_filter=None` (see Non-goals). Stores the proposal on `loop_state["plan"]["proposed"] = [node ids in order]` and returns `{"concepts": [{node_id, concept_name, kind, p_known}], "order": list(PLAN_ORDER)}`.
14. `POST /plan/approve` body `PlanApproveBody(session_id, user_id, concept_ids: list[str])` — phase must be `plan`; `concept_ids` must be a non-empty subset of `proposed` (order as submitted — the student reorders freely; that is the autonomy the research grants) else 422. Stores `loop_state["plan"]["approved"] = concept_ids` and `loop_state["plan"]["cursor"] = 0`, sets the current concept `loop_state["concept"] = concept_ids[0]` and `loop_state["teach_turns"] = loop_state["concept_checks"] = 0` (spec §9 "Item activation and the current concept", §13 A27 — PKG-07's `_activate_next_item` reads these to pick the check items and the teach-turn band; this route activates nothing and returns no item), emits `learn.plan_approved`, sets phase `teach`, returns `{"phase": "teach", "concept_ids": [...]}`. No learner brief is built here: PKG-09 reopens this handler to build and store it in `sessions.loop_brief` (A19).
15. Loop state is read and written only through PKG-07's accessors (bound in Task 2 Step 0). This package never adds a second writer of `sessions.loop_state`.

### Schema (exact)

None. This package adds no migration; `sessions.loop_state` (PKG-06) carries `probe` (`skills`, `history`, `current`, `unavailable` — ids, hashes, numbers and booleans only, no free text) and `plan` sub-objects and `phase`.

### Named constants

Every number this package uses. Tasks cite the NAME. Spec-owned values already exist in `learning/params.py` (PKG-01); verify with Task 2 Step 0. The four `†` rows are new and go into `params.py` in Task 2 with a `# PKG-08 †` comment.

| Name | Value | Spec | Meaning |
|---|---|---|---|
| `PROBE_TARGET_LO` | 0.50 | §3.3 | probe band lower edge (expected P(correct)) |
| `PROBE_TARGET_HI` | 0.62 | §3.3 | probe band upper edge |
| `PROBE_ITEMS_PER_SKILL_MIN` | 4 | §3.4 | items per skill before the stop rule may fire |
| `PROBE_ITEMS_PER_SKILL_MAX` | 6 | §3.4 | hard cap per skill |
| `PROBE_SESSION_CAP` | 12 | §3.4 | hard cap per session |
| `PROBE_STOP_DELTA` | 0.05 | §3.4 | stop when the last two posteriors move less than this |
| `NOVICE_FLOOR_MISSES` | 3 | §3.3 | misses at the easiest difficulty that end the probe |
| `PLAN_MAX_CONCEPTS` | 5 | §3.4 | new concepts per plan when independent |
| `PLAN_MAX_COUPLED` | 2 | §3.4 | new concepts sharing a parent |
| `PLAN_ORDER` | `("reviews", "new", "siblings")` | §3.4 | section order |
| `BKT_PROFICIENT` | 0.95 | §3.1 | proficient threshold (fringe uses it) |
| `BKT_L0` | 0.35 | §3.1 | prior for a node with no `learner_state` row |
| `CHANNELS[...].G/.S` | §3.1 table | §3.1 | per-channel guess/slip used by `expected_success` |
| `CHECK_ITEM_FORMATS` | `free, teachback, mc_reason` | §3.4 | keys of PKG-05's `CHANNEL_FOR_FORMAT` (passed to `next_probe_item`) |
| `CHECK_ITEM_DIFFICULTIES` | 1, 2, 3 | §3.4 | keys of `PROBE_DIFFICULTY_SHIFT` |
| `EDGE_PREREQ_SOURCE_IS_PREREQ` | `True` | §3.1 | `source_node_id` is the prerequisite; Task 3 Step 0 verifies |
| `REVIEW_DAILY_BUDGET_MIN` | 12 | §3.2 | passed to `budget_select` |
| `REVIEW_SECONDS_PER_CHECK` | 45 | §3.2 | passed to `budget_select` |
| `PROBE_DIFFICULTY_SHIFT` † | `{1: +0.15, 2: 0.0, 3: −0.15}` | — | difficulty shifts `p` before the likelihood; no calibrated item parameters exist (research §Probe, last sentence) |
| `NOVICE_FLOOR_IDK` † | 2 | — | "repeated `idk`" (§3.3) given a number; the spec names none |
| `PROBE_EASIEST_DIFFICULTY` | `min(CHECK_ITEM_DIFFICULTIES)` | derived | the "difficulty 1" of §3.3, spelled without a literal |
| `PROBE_MAX_SKILLS` | `PROBE_SESSION_CAP // PROBE_ITEMS_PER_SKILL_MIN` | derived | skills a probe can reach MIN on inside the session cap |
| `LEARN_RATE_LIMIT_PER_MIN` | 20 † | §3.5 (`config.py`, PKG-06b) | consumed only through `enforce_rate_limit` on `/probe/answer`; never read directly here |
| `STUDENT_DAILY_GRADES` | 300 † | §3.5 (`config.py`, PKG-06b) | the grader cap inside `grade()`; reaching it makes a probe answer `unavailable` (not asked); never read directly here |

`†` values go to the hand-off "Constants chosen" with the marker and to `LEDGER.md` Deviations (the two `config.py` rows are PKG-06b's, not this package's).

### Invariants asserted by this package (spec §8 numbering)

- (2, extended) `learning/probe.py` and `learning/planner.py` import nothing from `agents`, `pydantic_ai`, `google`, `db` — `PURE_MODULES` gains both names AND a dedicated `test_inv_16_probe_planner_pure` asserts it by name so a later edit to the tuple cannot silently drop them.
- (5) the two new event names are in `EVENT_TAXONOMY` — PKG-06's `test_inv_05` greps every `learn.*` literal under `backend/`; it goes red the moment Task 4's route code emits a name the taxonomy lacks.
- (1) still holds: the only `apply_graph_update` call this package adds is in `routes/learn_loop.py`; no `table("graph_nodes"|"graph_edges"|"node_mastery_events"|"learner_state").upsert/update/insert` appears in any file this package touches.
- (26, extended) the `/probe/answer` handler joins the explicit-submission allow-list of PKG-07's `test_inv_26_evidence_only_from_explicit_submission` (Task 5); it is the only PKG-08 function that calls `apply_graph_update`, and it calls it only after an explicit answer.
- (28) mirrored at the route: an `unavailable` grade writes no evidence for either outcome — the route never sees the outcome of an ungraded attempt (`test_probe_answer_unavailable_counts_as_not_asked`). The behavioural invariant itself stays PKG-05/06b's.
- (22) still holds: no PKG-08 body model or route reads `model_pref`. (23) is untouched: PKG-08 runs no agent directly; the grader run inside `grade()` checks the grader cap (PKG-06b).

### Error semantics

Grader `unavailable` (outage, second opinion unavailable, or the `STUDENT_DAILY_GRADES` cap) → 200 `{"graded": false, "unavailable": true}`; the item counts as not asked (its hash joins `loop_state["probe"]["unavailable"]`, excluded from selection, not counted toward caps), no evidence for either outcome, no second prompt stack, no event from this route (ADR 0024; PKG-05/05b/06b own the degrade, fallback and cap events). Rate limit exceeded on `/probe/answer` → 429 `{"detail": "ai budget reached", "reset_at": …}` from PKG-06b's dependency, nothing graded. The tutor budget level (soft or hard) changes nothing on any PKG-08 route. Gate false → 404 before any read. Phase mismatch → 409. Bad `question_hash` → 409. Approve with ids outside the proposal → 422. `expected_success` with an unknown channel raises `KeyError` — the route filters formats first, so this is a programming error, not a user path. `outer_fringe`/`plan` never raise on malformed edges; they drop them.

### Events added

| type | category | payload |
|---|---|---|
| `learn.probe_done` | usage | `items` (int), `misses` (int, not-correct observations incl. idk), `novice_floor` (bool), `skills` (list of node ids) |
| `learn.plan_approved` | usage | `concept_ids` (list), `n_reviews_first` (int: length of the leading run of `review` entries in the approved order) |

Both via `events_service.log_event(type, category="usage", user_id=..., request_id=..., payload=...)`. Ids and counts only; no prompt text. A no-check-items finish emits `items=0, misses=0, novice_floor=false, skills=[]` (the payload keys stay exactly the spec §6 four).

## Non-goals

- No LLM tutor turn in either phase; `/probe/answer` calls `grade_answer` only (A22 pre-checks + the grader through the decision seam). Teach/check/feedback turns are PKG-07's.
- No `ai_budget.check` call in any PKG-08 route (A20: the probe runs at the tutor hard cap; the grader cap lives inside `grade()`, PKG-06b). No learner brief (PKG-09 reopens `/plan/approve`, A19). No post-test serving (this package only excludes the reserve; PKG-14a serves it).
- No syllabus-week goal filter. `services/academics.py` exposes term/offering/enrollment resolution only (defs listed in Read §9); nothing maps a week or an assignment to concept ids. `plan()` takes `goal_filter` so PKG-13/14 can wire one; the route passes `None`. `services/exam_proximity.py::days_until_next_exam` (:146) is the nearest existing signal and belongs to PKG-12's retention-target choice, not here. Recorded as an open question.
- No frontend (PKG-13). No migration. No new `AgentTask`, no function-mode handler, no eval dataset (the grader's already exist).
- No misconception code here. PKG-10's slip/misconception hook lives inside `grade_answer` (A16), so it covers probe answers once PKG-10 lands; the route ignores `wrong_key`/`matched_wrong_key`.
- No change to `agents/`, `services/chat_stream.py`, `services/graph_service.py`, `services/ai_budget.py`, `services/check_item_service.py`, `learning/{bkt,fsrs,evidence,learner_state,checks,policy,gates,ladder,leak}.py`.

## Tasks

### Task 1: Invariants — pure probe/planner

**Files:**
- Modify: `backend/tests/test_learning_loop_invariants.py`

**Interfaces:**
- Consumes: `PURE_MODULES`, `_imports_of`, `FORBIDDEN_IMPORT_ROOTS` from the module.
- Produces: `test_inv_16_probe_planner_pure`; `PURE_MODULES` includes `"probe.py"`, `"planner.py"`.

- [ ] **Step 1: Extend the tuple and add the test**

Change the tuple to include the two names (keep every existing entry):
```python
PURE_MODULES = ("bkt.py", "fsrs.py", "policy.py", "gates.py", "ladder.py", "leak.py", "probe.py", "planner.py")
```
Append after the last `test_inv_` function (spec §8 reserves 16 for this one; 13–15 and 22–29 already exist or belong to other packages — never reuse a number):
```python
def test_inv_16_probe_planner_pure():
    """PKG-08: the probe and planner are policy, not I/O. Named explicitly so a
    later edit to PURE_MODULES cannot drop them without this test noticing."""
    for name in ("probe.py", "planner.py"):
        assert name in PURE_MODULES, f"{name} fell out of PURE_MODULES"
        path = LEARNING / name
        assert path.exists(), f"{name} missing"
        bad = [r for r in _imports_of(path) if r in FORBIDDEN_IMPORT_ROOTS]
        assert not bad, f"{name} imports {bad}"
        text = path.read_text()
        assert "table(" not in text and "rpc(" not in text, f"{name} touches the database"
        assert "learning.checks" not in text, f"{name} must stay decoupled from checks.py (Protocol instead)"
```

- [ ] **Step 2: Run**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q`
Expected: every previously-passing test still passes; `test_inv_16` PASSES already (the stubs import nothing). It exists to stay green through Tasks 2–3.

- [ ] **Step 3: Commit**

```
git add backend/tests/test_learning_loop_invariants.py
git commit -m "test(learning-loop): PKG-08 — inv_16 probe/planner stay pure

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 2: `learning/probe.py` + † constants

**Files:**
- Modify: `backend/learning/params.py` (four names; separate first commit — see Step 1)
- Modify: `backend/learning/probe.py` (replace the stub)
- Create: `backend/tests/test_learning_probe_planner.py` (probe half; Task 3 appends the planner half, Tasks 4–6 the route half)

**Interfaces:**
- Consumes: `learning.params` names in the table above.
- Produces: `expected_success`, `next_probe_item`, `probe_done`, `novice_floor`, `ProbeItem`, `ProbeObservation`, `CHANNEL_FOR_FORMAT`.

- [ ] **Step 0: Bind the dependency surface (write the answers into your hand-off as you go)**

Run and record each result; every later step refers to these by the letter:
```
cd backend
grep -nE "^(PROBE_|PLAN_|NOVICE_FLOOR|EDGE_PREREQ|BKT_PROFICIENT|BKT_L0|CHANNELS|CHECK_ITEM_|REVIEW_DAILY|REVIEW_SECONDS)" learning/params.py     # (A) all spec-owned names present? note the CHANNELS shape (mapping of dicts or of dataclasses)
grep -nE "^def (read_state|write_state)" learning/learner_state.py                # (B) PKG-03 read signature: (user_id, node_ids?) → what shape? decayed?
grep -nE "^def (order_due|budget_select)" learning/fsrs.py                        # (C) PKG-02 signatures
grep -nE "^(def|async def|class) " services/check_item_service.py                 # (D) PKG-04: list_items(course_id, concept_key, ...) (decrypts) and course_has_items(course_id)
grep -nE "^(def|class) |posttest_reserve_hash|options|correct_option" learning/checks.py   # (D) PKG-04: the CheckItem field names (id, format, difficulty, question_hash, prompt, reference_answer, options[{letter,text,wrong_key}], correct_option — no node_id, A2) and posttest_reserve_hash(items)
grep -n "def _normalize_concept" services/graph_service.py                       # (D) A2: node concept_name → concept_key
grep -nE "^(def|async def|class) |^CHANNEL_FOR_FORMAT" agents/tools/check.py      # (E) PKG-05: grade_answer(item, answer, *, deps, node_id, max_rung=0, same_session_recheck=False) -> GradeOutcome (the caller passes the student's node_id — A2: CheckItem has none); CheckAnswer; GradeOutcome fields (correct, confidence, unavailable, evidence, wrong_key, grader_backend); CHANNEL_FOR_FORMAT
grep -nE "^(def|async def) |^router|learning_loop_active|loop_state|grade_answer|SaplingDeps\(|enforce_rate_limit|apply_graph_update" routes/learn_loop.py | head -60   # (F) PKG-07: gate helper, loop-state load/save, initial phase, how /check/answer builds SaplingDeps, calls grade_answer, writes evidence and attaches the rate limit, body-model import site
grep -n "class .*Body" models/__init__.py | tail -8                               # (G) where PKG-07 put its loop bodies
grep -nE "^(async )?def (check|rate_limited|enforce_rate_limit)\(" services/ai_budget.py   # (H) PKG-06b: the rate-limit names the fixtures patch
grep -n "def test_inv_26" -A 25 tests/test_learning_loop_invariants.py            # (I) PKG-07: the explicit-submission allow-list's name and shape (function names? route paths?)
```
If (A) shows a spec-owned name missing, that is a PKG-01 defect: stop, add it with its §3 value in the same `fix(learning-loop): PKG-01` commit as Step 1, and record it as a Deviation. If (B)–(I) show a symbol missing, STOP — the dependency is not done; write a `BLOCKED` ledger row.

- [ ] **Step 1: Add the † constants to `params.py`** (an earlier package's file → its own commit, ledger row `01 | reopened`, "Post-hoc changes" line in `HANDOFF-01.md`)

Append, next to the other `PROBE_*` names:
```python
# PKG-08 † — engineering choices with no validated cut-point (first A/B candidates).
# Difficulty shifts p_known before the §3.1 observation likelihood; LLM-generated
# items carry no calibrated parameters (research §Probe, last sentence).
PROBE_DIFFICULTY_SHIFT: dict[int, float] = {1: 0.15, 2: 0.0, 3: -0.15}
# "repeated idk" (§3.3) given a number.
NOVICE_FLOOR_IDK = 2
# Derived, so no literal repeats the spec's "difficulty 1" or the skill count.
PROBE_EASIEST_DIFFICULTY = min(CHECK_ITEM_DIFFICULTIES)
PROBE_MAX_SKILLS = PROBE_SESSION_CAP // PROBE_ITEMS_PER_SKILL_MIN
```
Add an import-time assertion beside PKG-01's channel checks: `assert set(PROBE_DIFFICULTY_SHIFT) == set(CHECK_ITEM_DIFFICULTIES)`.

```
git add backend/learning/params.py
git commit -m "fix(learning-loop): PKG-01 — probe † constants for PKG-08

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 2: Write the failing tests (probe half)**

```python
"""PKG-08: probe phase + planner (spec §3.3 probe row, §3.4, §6, §9).
Pure halves use synthetic learner states; route half patches the seams
routes/learn_loop.py exposes for this package."""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from agents.tools.check import CHANNEL_FOR_FORMAT  # PKG-05's map; probe.py takes it as an argument (invariant 2)
from learning import params as P


# ── fixtures ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _Item:
    id: str
    node_id: str
    format: str
    difficulty: int
    question_hash: str


def _items(node_id: str, n: int, *, difficulty: int = 2, fmt: str = "free") -> list[_Item]:
    return [_Item(f"{node_id}-i{k}", node_id, fmt, difficulty, f"h-{node_id}-{k}") for k in range(n)]


def _obs(node_id, p_after, *, correct=True, idk=False, difficulty=2, k=0):
    return {
        "node_id": node_id, "question_hash": f"h-{node_id}-{k}", "difficulty": difficulty,
        "channel": "free_response", "correct": correct, "idk": idk, "p_after": p_after,
    }


# ── expected_success ────────────────────────────────────────────────────────


def test_expected_success_monotone_in_p():
    from learning.probe import expected_success
    grid = [i / 20 for i in range(21)]
    vals = [expected_success(p, 2, "free_response") for p in grid]
    assert all(a <= b for a, b in zip(vals, vals[1:]))
    assert 0.0 <= min(vals) and max(vals) <= 1.0


def test_easier_items_have_higher_expected_success():
    from learning.probe import expected_success
    p = 0.5
    e1, e2, e3 = (expected_success(p, d, "free_response") for d in (1, 2, 3))
    assert e1 > e2 > e3


def test_mc_is_chance_corrected_by_channel_guess():
    from learning.probe import expected_success
    # A student who knows nothing still "succeeds" at the channel's guess rate.
    assert expected_success(0.0, 2, "mc") > expected_success(0.0, 2, "free_response")


# ── next_probe_item ─────────────────────────────────────────────────────────


def test_choice_is_in_band_and_closest_to_midpoint():
    from learning.probe import expected_success, next_probe_item
    states = {"A": 0.5}
    items = _items("A", 1, difficulty=1) + _items("A", 1, difficulty=2) + _items("A", 1, difficulty=3)
    chosen = next_probe_item(states, items, asked_hashes=[], channel_for_format=CHANNEL_FOR_FORMAT)
    assert chosen is not None
    es = expected_success(states["A"], chosen.difficulty, CHANNEL_FOR_FORMAT[chosen.format])
    mid = (P.PROBE_TARGET_LO + P.PROBE_TARGET_HI) / 2
    in_band = [
        it for it in items
        if P.PROBE_TARGET_LO <= expected_success(states["A"], it.difficulty, CHANNEL_FOR_FORMAT[it.format]) <= P.PROBE_TARGET_HI
    ]
    if in_band:
        assert P.PROBE_TARGET_LO <= es <= P.PROBE_TARGET_HI
    best = min(items, key=lambda it: abs(expected_success(states["A"], it.difficulty, CHANNEL_FOR_FORMAT[it.format]) - mid))
    assert chosen.question_hash == best.question_hash


def test_falls_back_to_nearest_when_nothing_is_in_band():
    from learning.probe import next_probe_item
    states = {"A": 0.0}  # every item is below the band
    items = _items("A", 1, difficulty=3) + _items("A", 1, difficulty=1)
    chosen = next_probe_item(states, items, asked_hashes=[], channel_for_format=CHANNEL_FOR_FORMAT)
    assert chosen is not None and chosen.difficulty == P.PROBE_EASIEST_DIFFICULTY


def test_asked_hashes_are_skipped():
    from learning.probe import next_probe_item
    items = _items("A", 2)
    chosen = next_probe_item(
        {"A": 0.5}, items, asked_hashes=[items[0].question_hash], channel_for_format=CHANNEL_FOR_FORMAT
    )
    assert chosen is not None and chosen.question_hash == items[1].question_hash


def test_per_skill_cap():
    from learning.probe import next_probe_item
    items = _items("A", P.PROBE_ITEMS_PER_SKILL_MAX + 2) + _items("B", 1)
    asked = [it.question_hash for it in items if it.node_id == "A"][: P.PROBE_ITEMS_PER_SKILL_MAX]
    chosen = next_probe_item(
        {"A": 0.5, "B": 0.5}, items, asked_hashes=asked, channel_for_format=CHANNEL_FOR_FORMAT
    )
    assert chosen is not None and chosen.node_id == "B"


def test_session_cap_returns_none():
    from learning.probe import next_probe_item
    items = _items("A", P.PROBE_SESSION_CAP + 3)
    asked = [it.question_hash for it in items][: P.PROBE_SESSION_CAP]
    chosen = next_probe_item({"A": 0.5}, items, asked_hashes=asked, channel_for_format=CHANNEL_FOR_FORMAT)
    assert chosen is None


def test_unknown_node_and_unknown_format_are_ignored():
    from learning.probe import next_probe_item
    items = _items("Z", 1) + [_Item("x", "A", "essay", 2, "h-x")]
    chosen = next_probe_item({"A": 0.5}, items, asked_hashes=[], channel_for_format=CHANNEL_FOR_FORMAT)
    assert chosen is None


# ── probe_done / novice_floor ───────────────────────────────────────────────


def test_probe_done_empty_is_false():
    from learning.probe import probe_done
    assert probe_done([]) is False


def test_stop_rule_needs_min_items_and_stable_posterior():
    from learning.probe import probe_done
    stable = [0.5, 0.55, 0.6, 0.6 + P.PROBE_STOP_DELTA / 2]
    hist = [_obs("A", p, k=i) for i, p in enumerate(stable)]
    assert len(hist) == P.PROBE_ITEMS_PER_SKILL_MIN
    assert probe_done(hist) is True
    moving = stable[:-1] + [stable[-2] + 2 * P.PROBE_STOP_DELTA]
    assert probe_done([_obs("A", p, k=i) for i, p in enumerate(moving)]) is False
    assert probe_done(hist[:-1]) is False  # below MIN


def test_probe_done_at_per_skill_max_even_if_moving():
    from learning.probe import probe_done
    hist = [_obs("A", 0.1 * i, k=i) for i in range(P.PROBE_ITEMS_PER_SKILL_MAX)]
    assert probe_done(hist) is True


def test_probe_done_requires_every_named_skill():
    from learning.probe import probe_done
    hist = [_obs("A", 0.6, k=i) for i in range(P.PROBE_ITEMS_PER_SKILL_MAX)]
    assert probe_done(hist, skills=["A", "B"]) is False
    assert probe_done(hist, skills=["A"]) is True


def test_probe_done_at_session_cap():
    from learning.probe import probe_done
    hist = [_obs(f"N{i}", 0.5, k=i) for i in range(P.PROBE_SESSION_CAP)]
    assert probe_done(hist) is True


def test_novice_floor_misses_at_easiest_difficulty():
    from learning.probe import novice_floor, probe_done
    hist = [
        _obs("A", 0.2, correct=False, difficulty=P.PROBE_EASIEST_DIFFICULTY, k=i)
        for i in range(P.NOVICE_FLOOR_MISSES)
    ]
    assert novice_floor(hist) is True and probe_done(hist) is True
    harder = [dict(h, difficulty=P.PROBE_EASIEST_DIFFICULTY + 1) for h in hist]
    assert novice_floor(harder) is False


def test_novice_floor_repeated_idk():
    from learning.probe import novice_floor
    hist = [_obs("A", 0.3, correct=False, idk=True, difficulty=3, k=i) for i in range(P.NOVICE_FLOOR_IDK)]
    assert novice_floor(hist) is True
    assert novice_floor(hist[:-1]) is False
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_probe_planner.py -q`
Expected: every test FAILS with `ImportError: cannot import name 'expected_success' from 'learning.probe'` (the stub has no symbols).

- [ ] **Step 4: Implement `learning/probe.py`**

```python
"""Probe phase (spec §3.3 probe band, §3.4 limits). Pure: no agents/db imports.

Picks the next check item whose expected success under the current belief
sits in the probe band, stops when belief stabilises, and detects the
novice floor. Items arrive through a Protocol so this module never depends
on learning.checks; the format -> channel map arrives as an argument
(PKG-05 owns it in agents/, which this module may not import); observations
are JSON dicts because they live in sessions.loop_state.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterable, Mapping, Protocol, Sequence, TypedDict

from learning.params import (
    CHANNELS,
    NOVICE_FLOOR_IDK,
    NOVICE_FLOOR_MISSES,
    PROBE_DIFFICULTY_SHIFT,
    PROBE_EASIEST_DIFFICULTY,
    PROBE_ITEMS_PER_SKILL_MAX,
    PROBE_ITEMS_PER_SKILL_MIN,
    PROBE_SESSION_CAP,
    PROBE_STOP_DELTA,
    PROBE_TARGET_HI,
    PROBE_TARGET_LO,
)


class ProbeItem(Protocol):
    id: str
    node_id: str
    format: str
    difficulty: int
    question_hash: str


class ProbeObservation(TypedDict):
    node_id: str
    question_hash: str
    difficulty: int
    channel: str  # always the item's channel (A1: no "idk" channel)
    correct: bool
    idk: bool  # explicit "I don't know" (A1)
    p_after: float


def _guess_slip(channel: str) -> tuple[float, float]:
    ch = CHANNELS[channel]
    if isinstance(ch, dict):
        return float(ch["G"]), float(ch["S"])
    return float(ch.G), float(ch.S)


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def expected_success(p_known: float, item_difficulty: int, channel: str) -> float:
    """P(correct) for one item: difficulty-shifted belief through the channel's
    BKT observation likelihood (spec §3.1) — the same formula chance-corrects mc."""
    g, s = _guess_slip(channel)
    p = _clamp01(p_known + PROBE_DIFFICULTY_SHIFT[item_difficulty])
    return p * (1.0 - s) + (1.0 - p) * g


def next_probe_item(
    states: dict[str, float],
    items: Sequence[ProbeItem],
    asked_hashes: Iterable[str],
    *,
    channel_for_format: Mapping[str, str],
) -> ProbeItem | None:
    """The unasked item closest to the probe-band midpoint, in-band preferred.
    Respects PROBE_ITEMS_PER_SKILL_MAX per node and PROBE_SESSION_CAP. Pass the
    full candidate list (asked items included) so per-node counts are right;
    the caller has already removed items that must never be served (post-test
    reserve, unavailable). channel_for_format is PKG-05's CHANNEL_FOR_FORMAT."""
    asked = set(asked_hashes)
    if len(asked) >= PROBE_SESSION_CAP:
        return None
    per_node: Counter[str] = Counter(it.node_id for it in items if it.question_hash in asked)
    mid = (PROBE_TARGET_LO + PROBE_TARGET_HI) / 2.0
    in_band: list[tuple[tuple, ProbeItem]] = []
    near: list[tuple[tuple, ProbeItem]] = []
    for it in items:
        if it.question_hash in asked or it.node_id not in states:
            continue
        if per_node[it.node_id] >= PROBE_ITEMS_PER_SKILL_MAX:
            continue
        channel = channel_for_format.get(it.format)
        if channel is None or it.difficulty not in PROBE_DIFFICULTY_SHIFT:
            continue
        es = expected_success(states[it.node_id], it.difficulty, channel)
        key = (abs(es - mid), it.difficulty, it.question_hash)
        (in_band if PROBE_TARGET_LO <= es <= PROBE_TARGET_HI else near).append((key, it))
    pool = in_band or near
    if not pool:
        return None
    return min(pool, key=lambda pair: pair[0])[1]


def novice_floor(history: Sequence[ProbeObservation]) -> bool:
    """Spec §3.3 last bullet: misses at the easiest difficulty, or repeated idk."""
    misses_easiest = sum(
        1 for h in history
        if h["difficulty"] == PROBE_EASIEST_DIFFICULTY and not h["correct"]
    )
    idks = sum(1 for h in history if h.get("idk", False))
    return misses_easiest >= NOVICE_FLOOR_MISSES or idks >= NOVICE_FLOOR_IDK


def probe_done(
    history: Sequence[ProbeObservation],
    *,
    skills: Iterable[str] | None = None,
) -> bool:
    """Session cap, novice floor, or every skill stabilised (≥ MIN items and the
    last two posteriors within PROBE_STOP_DELTA) or capped (≥ MAX items)."""
    if not history:
        return False
    if len(history) >= PROBE_SESSION_CAP or novice_floor(history):
        return True
    by_node: dict[str, list[float]] = defaultdict(list)
    for h in history:
        by_node[h["node_id"]].append(float(h["p_after"]))
    required = set(by_node) | (set(skills) if skills is not None else set())
    for node_id in required:
        ps = by_node.get(node_id, [])
        if len(ps) >= PROBE_ITEMS_PER_SKILL_MAX:
            continue
        if len(ps) >= PROBE_ITEMS_PER_SKILL_MIN and abs(ps[-1] - ps[-2]) < PROBE_STOP_DELTA:
            continue
        return False
    return True
```
Adapt `_guess_slip` to the `CHANNELS` shape (A) — keep only the branch that matches; a two-branch helper is acceptable only if PKG-01 left the shape ambiguous.

- [ ] **Step 5: Run tests, lint, invariants**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_probe_planner.py tests/test_learning_loop_invariants.py -q && venv/bin/ruff check . && venv/bin/ruff format --check learning tests/test_learning_probe_planner.py`
Expected: probe tests all pass (16); invariants unchanged + `inv_16` passes; `All checks passed!`.

- [ ] **Step 6: Commit**

```
git add backend/learning/probe.py backend/tests/test_learning_probe_planner.py
git commit -m "feat(learning-loop): PKG-08 — probe: expected_success, next_probe_item, probe_done, novice_floor

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 3: `learning/planner.py` + edge-direction check

**Files:**
- Modify: `backend/learning/planner.py` (replace the stub)
- Modify: `backend/tests/test_learning_probe_planner.py` (append planner half)
- Modify (only if Step 0 says so): `backend/learning/params.py` — flip `EDGE_PREREQ_SOURCE_IS_PREREQ`, as a separate `fix(learning-loop): PKG-01` commit + Deviation.

**Interfaces:**
- Consumes: `BKT_PROFICIENT`, `PLAN_MAX_CONCEPTS`, `PLAN_MAX_COUPLED`, `PLAN_ORDER`.
- Produces: `outer_fringe`, `plan`, `Plan`, `PlanConcept`.

- [ ] **Step 0: Verify the edge-direction convention against real data (one-off, not committed)**

The spec fixes `EDGE_PREREQ_SOURCE_IS_PREREQ = True` and tells this package to verify. Two sources of truth exist today; check both.

(a) Seeds — the only edges with human-readable endpoints:
```
grep -n '"prerequisite"' backend/db/seed_local_rich.py backend/db/seed_staging.py
```
Expected today: `seed_local_rich.py` tuples `(edge_id, source, target, type, strength)` with `rich-node-cs-variables → rich-node-cs-controlflow` and `rich-node-math-matrices → rich-node-math-eigenvalues`; `seed_staging.py` `(source, target, type, strength)` with `seed-node-cs-variables → seed-node-cs-functions`. Variables are a prerequisite of control flow; matrices of eigenvalues. Source = prerequisite → the constant stays `True`.

(b) Live rows, only if `backend/.env.staging` exists (never prod). Run and eyeball ≤ 20 rows; read each line as "`<source>` is a prerequisite of `<target>`" and count how many read sensibly:
```
cd backend && dotenv -f .env.staging run -- venv/bin/python - <<'EOF'
from db.connection import table
edges = table("graph_edges").select("user_id,source_node_id,target_node_id", filters={"relationship_type": "eq.prerequisite"}, limit=20) or []
ids = {e["source_node_id"] for e in edges} | {e["target_node_id"] for e in edges}
names = {}
if ids:
    for n in table("graph_nodes").select("id,concept_name", filters={"id": f"in.({','.join(ids)})"}) or []:
        names[n["id"]] = n["concept_name"]
for e in edges:
    print(f'{names.get(e["source_node_id"], "?"):40s} → {names.get(e["target_node_id"], "?")}')
print(len(edges), "rows")
EOF
```
Decision rule: (a) agrees with `True` → keep. (b) contradicts (a) on a clear majority → flip the constant in `params.py` in its own `fix(learning-loop): PKG-01 — flip EDGE_PREREQ_SOURCE_IS_PREREQ` commit, add a Deviation, and note the row count. Zero live rows or no staging env → keep `True` on the strength of (a) and record "verified against seeds only" in the hand-off. Either way, write the † line in the hand-off "Constants chosen".

Note for the hand-off: `agents/tools/graph_read.py:237–265` and `services/graph_context.py:142–150` query both endpoint columns and render edges by name without interpreting direction, and `frontend/src/lib/landing/companionContent.ts:187` says the tree draws all four types the same way — nothing in the product contradicts the seed convention, and nothing enforces it either. The tutor's `apply_graph_update_tool` emits `new_edges` with `source`/`target` names (`services/graph_service.py:848–880`); the prompt at `agents/chat_tutor.py:94` names the types but not the direction. That is an open question for the series owner (below).

- [ ] **Step 1: Write the failing tests (planner half — append to the file)**

```python
# ── planner ─────────────────────────────────────────────────────────────────

_PROF = P.BKT_PROFICIENT
_BELOW = P.BKT_PROFICIENT - 0.2


def test_fringe_chain_a_b_c():
    from learning.planner import outer_fringe
    edges = [("A", "B"), ("B", "C")]
    assert outer_fringe({"A": _BELOW, "B": _BELOW, "C": _BELOW}, edges) == ["A"]
    assert outer_fringe({"A": _PROF, "B": _BELOW, "C": _BELOW}, edges) == ["B"]
    assert outer_fringe({"A": _PROF, "B": _PROF, "C": _BELOW}, edges) == ["C"]
    assert outer_fringe({"A": _PROF, "B": _PROF, "C": _PROF}, edges) == []


def test_fringe_orders_by_p_desc_then_id():
    from learning.planner import outer_fringe
    states = {"R1": _BELOW, "R2": _BELOW + 0.1, "R3": _BELOW}
    assert outer_fringe(states, []) == ["R2", "R1", "R3"]


def test_fringe_ignores_foreign_endpoints_and_self_loops():
    from learning.planner import outer_fringe
    states = {"A": _BELOW}
    assert outer_fringe(states, [("ghost", "A"), ("A", "A")]) == ["A"]


def _sib_map(edges):
    parents = {}
    for a, b in edges:
        parents.setdefault(b, set()).add(a)
    def siblings(n):
        return sorted(m for m, ps in parents.items() if m != n and ps & parents.get(n, set()))
    return siblings


def test_plan_sections_follow_plan_order():
    from learning.planner import plan
    edges = [("P", "N1"), ("P", "N2"), ("Q", "N3"), ("P", "K")]
    out = plan(["N1", "N3"], ["R1"], _sib_map(edges), None, proficient=frozenset({"K", "R1"}))
    assert [c.kind for c in out.concepts] == ["review", "new", "new", "sibling"]
    assert [c.node_id for c in out.concepts] == ["R1", "N1", "N3", "K"]
    assert out.order == P.PLAN_ORDER


def test_plan_coupled_cap():
    from learning.planner import plan
    n = P.PLAN_MAX_COUPLED + 2
    fringe = [f"N{i}" for i in range(n)]
    edges = [("P", f) for f in fringe]
    out = plan(fringe, [], _sib_map(edges), None)
    new = [c.node_id for c in out.concepts if c.kind == "new"]
    assert len(new) == P.PLAN_MAX_COUPLED


def test_plan_max_concepts_when_independent():
    from learning.planner import plan
    fringe = [f"N{i}" for i in range(P.PLAN_MAX_CONCEPTS + 3)]
    out = plan(fringe, [], lambda _n: [], None)
    assert len([c for c in out.concepts if c.kind == "new"]) == P.PLAN_MAX_CONCEPTS


def test_plan_goal_filter_and_dedupe():
    from learning.planner import plan
    out = plan(["N1", "N2", "R1"], ["R1", "R1"], lambda _n: [], lambda n: n != "N2")
    assert [c.node_id for c in out.concepts] == ["R1", "N1"]


def test_plan_siblings_only_when_proficient_and_unique():
    from learning.planner import plan
    edges = [("P", "N1"), ("P", "N2"), ("P", "K")]
    out = plan(["N1", "N2"], [], _sib_map(edges), None, proficient=frozenset({"K"}))
    sibs = [c.node_id for c in out.concepts if c.kind == "sibling"]
    assert sibs == ["K"]  # one K, not one per new concept; N2 is not proficient so never a sibling entry
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_probe_planner.py -q -k "fringe or plan"`
Expected: 8 FAIL — `ImportError: cannot import name 'outer_fringe' from 'learning.planner'`.

- [ ] **Step 3: Implement `learning/planner.py`**

```python
"""Planner (spec §3.4 PLAN_*; research §Plan). Pure over an in-memory graph.

outer_fringe: KST's "ready to learn" set — not proficient, every prerequisite
proficient. plan: PLAN_ORDER sections (reviews → new → interleaved siblings)
with the coupled cap. Edges arrive ALREADY oriented as (prerequisite,
dependent); the route applies EDGE_PREREQ_SOURCE_IS_PREREQ.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Iterable, Literal, Sequence

from learning.params import BKT_PROFICIENT, PLAN_MAX_CONCEPTS, PLAN_MAX_COUPLED, PLAN_ORDER

PlanKind = Literal["review", "new", "sibling"]


@dataclass(frozen=True)
class PlanConcept:
    node_id: str
    kind: PlanKind


@dataclass(frozen=True)
class Plan:
    concepts: tuple[PlanConcept, ...]
    order: tuple[str, ...] = tuple(PLAN_ORDER)


def outer_fringe(states: dict[str, float], prereq_edges: Iterable[tuple[str, str]]) -> list[str]:
    prereqs: dict[str, set[str]] = defaultdict(set)
    for prereq, dependent in prereq_edges:
        if prereq == dependent or prereq not in states or dependent not in states:
            continue
        prereqs[dependent].add(prereq)
    fringe = [
        n for n, p in states.items()
        if p < BKT_PROFICIENT and all(states[q] >= BKT_PROFICIENT for q in prereqs[n])
    ]
    return sorted(fringe, key=lambda n: (-states[n], n))


def plan(
    fringe: Sequence[str],
    due_reviews: Sequence[str],
    siblings_fn: Callable[[str], Sequence[str]],
    goal_filter: Callable[[str], bool] | None,
    *,
    proficient: frozenset[str] = frozenset(),
    max_concepts: int = PLAN_MAX_CONCEPTS,
    max_coupled: int = PLAN_MAX_COUPLED,
) -> Plan:
    keep = goal_filter or (lambda _n: True)

    reviews: list[str] = []
    for n in due_reviews:
        if n not in reviews and keep(n):
            reviews.append(n)

    new: list[str] = []
    for n in fringe:
        if len(new) >= max_concepts:
            break
        if n in reviews or n in new or not keep(n):
            continue
        sibs = set(siblings_fn(n))
        if sum(1 for c in new if c in sibs) >= max_coupled:
            continue
        new.append(n)

    taken = set(reviews) | set(new)
    siblings: list[str] = []
    for n in new:
        for s in siblings_fn(n):
            if s in proficient and s not in taken:
                siblings.append(s)
                taken.add(s)
                break

    sections = {
        "reviews": [PlanConcept(n, "review") for n in reviews],
        "new": [PlanConcept(n, "new") for n in new],
        "siblings": [PlanConcept(n, "sibling") for n in siblings],
    }
    concepts = [c for name in PLAN_ORDER for c in sections[name]]
    return Plan(tuple(concepts), tuple(PLAN_ORDER))
```

- [ ] **Step 4: Run tests, lint, invariants**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_probe_planner.py tests/test_learning_loop_invariants.py -q && venv/bin/ruff check . && venv/bin/ruff format --check learning tests/test_learning_probe_planner.py`
Expected: 24 passed in the package file; invariants green; `All checks passed!`.

- [ ] **Step 5: Commit**

```
git add backend/learning/planner.py backend/tests/test_learning_probe_planner.py
git commit -m "feat(learning-loop): PKG-08 — planner: outer_fringe and PLAN_ORDER plan with coupled cap

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 4: Events `learn.probe_done`, `learn.plan_approved`

**Files:**
- Modify: `backend/services/events_service.py` (`EVENT_TAXONOMY`, :97–168)
- Modify: `backend/tests/test_event_capture_seams.py` (`test_event_taxonomy_is_pinned`, :84–125)

**Interfaces:**
- Produces: the two names in the frozenset and in the pin.

- [ ] **Step 1: Extend the pin test first** — add, after PKG-06's `zpd.*` block in the pinned set:
```python
        # PKG-08: probe finished (items/misses/novice_floor/skills) and the
        # student approved a plan (concept_ids/n_reviews_first). Emit coverage
        # lives in test_learning_probe_planner.py.
        "learn.probe_done",
        "learn.plan_approved",
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_event_capture_seams.py -q -k pinned`
Expected: 1 FAILED — the frozenset comparison shows the two names missing on the left.

- [ ] **Step 3: Add to `EVENT_TAXONOMY`** with the same two-line comment, placed after the `zpd.*` entries PKG-06 added.

- [ ] **Step 4: Run**

Run: `cd backend && venv/bin/python -m pytest tests/test_event_capture_seams.py tests/test_learning_loop_invariants.py -q -k "pinned or inv_05"`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```
git add backend/services/events_service.py backend/tests/test_event_capture_seams.py
git commit -m "feat(learning-loop): PKG-08 — learn.probe_done and learn.plan_approved in the taxonomy

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 5: Routes `POST /probe/next`, `POST /probe/answer`

**Files:**
- Modify: `backend/routes/learn_loop.py`
- Modify: `backend/models/__init__.py` (two body models beside PKG-07's loop bodies, (G))
- Modify: `backend/tests/test_learning_probe_planner.py` (append route half, part 1)
- Modify: `backend/tests/test_learning_loop_invariants.py` (the `/probe/answer` handler joins the invariant 26 allow-list, (I))

**Interfaces:**
- Consumes: (B) `learner_state` read, (D) `check_item_service.list_items`/`course_has_items`, `checks.posttest_reserve_hash`, `_normalize_concept`, (E) `grade_answer`/`CheckAnswer`/`CHANNEL_FOR_FORMAT`, (F) gate helper + loop-state accessors + PKG-07's `SaplingDeps` construction, (H) `enforce_rate_limit`, `services.graph_service.apply_graph_update`, `services.events_service.log_event`, `learning.probe`, `learning.planner.outer_fringe`.
- Produces: the two routes (the answer handler is named `probe_answer`); the private seams below, which the tests patch by name: `_read_states(user_id, course_id) -> dict[str, float]`, `_prereq_edges(user_id, node_ids) -> list[tuple[str, str]]`, `_course_has_items(course_id) -> bool`, `_probe_items(course_id, node_ids) -> list` (node-bound items, UNfiltered — the handlers drop the reserve and unavailable hashes), `async _grade(item, answer, *, user_id, session_id) -> GradeOutcome`, `_load_loop_state(session_id) -> dict`, `_save_loop_state(session_id, state) -> None`, `_node_names(node_ids) -> dict[str, str]`.

If PKG-07 already has functions equivalent to `_load_loop_state`/`_save_loop_state`, alias them (`_load_loop_state = <pkg07 name>`) rather than writing a second reader/writer. Evidence is written by ONE direct call to the module-level `apply_graph_update(user_id, {"evidence": [outcome.evidence]}, course_id=course_id)` inside `probe_answer` itself — never through a new private helper (the invariant 26 AST allow-list names handlers) and never through `flush_pending` as well. `apply_graph_update` must be a module-level name in `routes/learn_loop.py` (import it if PKG-07 did not) — the tests patch `routes.learn_loop.apply_graph_update`. If (I) shows the allow-list admits PKG-07's flush helper and that helper calls `apply_graph_update` with exactly this shape through the same module-level name, calling it instead is acceptable; record which in the hand-off.

More binding rules the tests rely on: (i) emit events as `events_service.log_event(...)` through `from services import events_service` (the `routes/learn.py:19` pattern) even if PKG-07 imported the bare name — the tests patch `services.events_service.log_event`; (ii) the fixtures patch `routes.learn_loop.learning_loop_active` and `routes.learn_loop.table` — if PKG-07 binds the gate or the table factory under another module-level name, change the two fixtures to patch that name; do not restructure PKG-07's code; (iii) A2: PKG-04's `CheckItem` has no `node_id` — `_probe_items` binds each item to the student's node (`item.model_copy(update={"node_id": nid})` if the model admits the field, else a small frozen wrapper that adds `node_id` and delegates every other attribute), so every candidate exposes `id, node_id, format, difficulty, question_hash, prompt, reference_answer, options, correct_option`; if (D)'s attribute names differ, rename them in `_items`/`_ci`/`_probe_env` too and record the mapping in the hand-off; (iv) the fakes build `GradeOutcome`-shaped `SimpleNamespace`s with `unavailable, correct, confidence, wrong_key, grader_backend, evidence` and read `CheckAnswer` as `answer_text, selected_option, reason, idk` — if (E) names differ, rename them in `_answer_env` and record it; `_grade` calls `grade_answer(<the underlying CheckItem>, answer, deps=deps, node_id=item.node_id)` — HANDOFF-05's canonical signature, where the caller supplies the student's `node_id` (A2); (v) the `loop_on` fixture patches `services.ai_budget.rate_limited` — if (H) shows `enforce_rate_limit` reads another name, patch that one. The rate-limit check runs after the gate (spec §7: gate false → 404 before any read); if PKG-07 attaches `enforce_rate_limit` as a route dependency that FastAPI resolves before the handler body, attach it the same way and record in the hand-off that the gate-false path performs that one read.

- [ ] **Step 1: Write the failing tests (append)**

```python
# ── routes ──────────────────────────────────────────────────────────────────

from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)
LOOP = "/api/learn/loop"
UID = "user_andres"
NEXT = {"session_id": "s1", "user_id": UID, "course_id": "c1"}


def _state_store(initial: dict):
    store = {"state": dict(initial)}
    def load(_session_id):
        return dict(store["state"])
    def save(_session_id, state):
        store["state"] = dict(state)
    return store, load, save


def _never(*_a, **_k):
    raise AssertionError("must not be called on this path")


@pytest.fixture
def loop_on(monkeypatch):
    import routes.learn_loop as rl
    from services import ai_budget
    monkeypatch.setattr(rl, "learning_loop_active", lambda _uid: True)
    monkeypatch.setattr(ai_budget, "rate_limited", lambda _uid: False)  # binding rule (v)
    return rl


@pytest.fixture
def loop_off(monkeypatch):
    import routes.learn_loop as rl
    monkeypatch.setattr(rl, "learning_loop_active", lambda _uid: False)
    calls = []
    monkeypatch.setattr(rl, "table", lambda name: calls.append(name) or _Boom())
    return calls


class _Boom:
    def __getattr__(self, _name):
        raise AssertionError("gate false must not reach the database")


GATED_ROUTES = [
    ("post", "/probe/next", {"session_id": "s1", "user_id": UID, "course_id": "c1"}),
    ("post", "/probe/answer", {"session_id": "s1", "user_id": UID, "course_id": "c1", "question_hash": "h", "answer": "x"}),
    # Task 6 appends the two /plan rows here.
]


@pytest.mark.parametrize("method,path,body", GATED_ROUTES)
def test_gate_false_is_404_and_reads_nothing(loop_off, method, path, body):
    r = getattr(client, method)(f"{LOOP}{path}", json=body) if body else client.get(f"{LOOP}{path}")
    assert r.status_code == 404
    assert r.json() == {"detail": "learning loop not enabled"}
    assert loop_off == []


def _ci(it, **extra):
    """A decrypted PKG-04 item bound to the student's node (binding rule iii)."""
    fields = {**it.__dict__, "prompt": f"Q {it.id}", "reference_answer": "SECRET",
              "options": None, "correct_option": None, **extra}
    return type("CI", (), fields)()


def _probe_env(monkeypatch, rl, *, phase="probe", history=None, skills=None, current=None, items=None):
    store, load, save = _state_store({
        "phase": phase,
        "probe": {"skills": skills or [], "history": history or [], "current": current, "unavailable": []},
        "plan": {},
    })
    monkeypatch.setattr(rl, "_load_loop_state", load)
    monkeypatch.setattr(rl, "_save_loop_state", save)
    monkeypatch.setattr(rl, "_read_states", lambda _u, _c: {"A": 0.5, "B": _BELOW, "K": _PROF})
    monkeypatch.setattr(rl, "_prereq_edges", lambda _u, _ids: [("K", "B")])
    monkeypatch.setattr(rl, "_course_has_items", lambda _c: True)
    if items is None:
        items = _items("A", P.PROBE_ITEMS_PER_SKILL_MAX, difficulty=2) + _items("B", 2, difficulty=1)
    full = [it if hasattr(it, "prompt") else _ci(it) for it in items]
    monkeypatch.setattr(rl, "_probe_items", lambda _c, _ids: full)
    monkeypatch.setattr(rl, "_node_names", lambda ids: {i: i.lower() for i in ids})
    return store, full


def _reserves(full):
    """PKG-04's A23 rule, per concept (one concept per node here)."""
    from learning.checks import posttest_reserve_hash
    nodes = {it.node_id for it in full}
    return {posttest_reserve_hash([it for it in full if it.node_id == n]) for n in nodes} - {None}


def test_probe_next_serves_an_item_without_the_key(loop_on, monkeypatch):
    store, full = _probe_env(monkeypatch, loop_on)
    r = client.post(f"{LOOP}/probe/next", json=NEXT)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["done"] is False
    assert set(body) >= {"check_item_id", "question_hash", "node_id", "format", "difficulty", "prompt", "options"}
    assert body["options"] is None  # a free item
    assert "SECRET" not in r.text and "reference_answer" not in body and "rubric_json" not in body
    assert body["question_hash"] not in _reserves(full)  # A23
    st = store["state"]
    assert st["probe"]["current"]["question_hash"] == body["question_hash"]
    assert st["probe"]["skills"] and len(st["probe"]["skills"]) <= P.PROBE_MAX_SKILLS
    assert "K" not in st["probe"]["skills"]  # proficient nodes are never probed


def test_probe_next_serves_mc_reason_options_without_the_key(loop_on, monkeypatch):
    """A22: the stored options go out as letter + text only — no wrong_key, no correct option."""
    opts = [SimpleNamespace(letter=x, text=f"opt {x}", wrong_key="" if x == "B" else f"wk-{x}") for x in "ABCD"]
    items = [
        _ci(_Item("A-f", "A", "free", 2, "h-A-0")),  # A's post-test reserve (A23) — never served
        _ci(_Item("A-m", "A", "mc_reason", 2, "h-A-m"), options=opts, correct_option="B"),
    ]
    _probe_env(monkeypatch, loop_on, items=items)
    r = client.post(f"{LOOP}/probe/next", json=NEXT)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["format"] == "mc_reason" and body["question_hash"] == "h-A-m"
    assert body["options"] == [{"letter": x, "text": f"opt {x}"} for x in "ABCD"]
    assert "wk-" not in r.text and "correct_option" not in body and "SECRET" not in r.text


def test_probe_next_never_serves_the_posttest_reserve(loop_on, monkeypatch):
    """A23: each concept's post-test reserve is never probed; every other item stays reachable."""
    store, full = _probe_env(monkeypatch, loop_on)
    reserves = _reserves(full)
    served = []
    with patch("services.events_service.log_event"):
        for _ in range(len(full) + 1):
            body = client.post(f"{LOOP}/probe/next", json=NEXT).json()
            if body["done"]:
                break
            served.append(body["question_hash"])
            probe_state = store["state"]["probe"]
            probe_state["history"].append({**probe_state["current"], "correct": True, "idk": False, "p_after": 0.5})
            probe_state["current"] = None
    assert served and not reserves & set(served)
    assert len(served) == len(full) - len(reserves)


def test_probe_next_wrong_phase_is_409(loop_on, monkeypatch):
    _probe_env(monkeypatch, loop_on, phase="teach")
    r = client.post(f"{LOOP}/probe/next", json=NEXT)
    assert r.status_code == 409


def test_probe_next_with_no_items_finishes_probe(loop_on, monkeypatch):
    store, _ = _probe_env(monkeypatch, loop_on)
    monkeypatch.setattr(loop_on, "_probe_items", lambda _c, _ids: [])
    with patch("services.events_service.log_event") as log:
        r = client.post(f"{LOOP}/probe/next", json=NEXT)
    assert r.status_code == 200 and r.json() == {"done": True, "phase": "plan"}
    assert store["state"]["phase"] == "plan"
    names = [c.args[0] for c in log.call_args_list]
    assert names == ["learn.probe_done"]
    assert log.call_args.kwargs["payload"]["items"] == 0


def test_probe_next_course_without_check_items(loop_on, monkeypatch):
    """A23/A26 empty state (the route test spec §11.1 item 2 names): the course has no
    check items → the probe finishes at once with no_check_items; no item read, no evidence."""
    store, _ = _probe_env(monkeypatch, loop_on)
    monkeypatch.setattr(loop_on, "_course_has_items", lambda _c: False)
    monkeypatch.setattr(loop_on, "_probe_items", _never)
    with patch("services.events_service.log_event") as log, patch("routes.learn_loop.apply_graph_update") as agu:
        r = client.post(f"{LOOP}/probe/next", json=NEXT)
    assert r.status_code == 200 and r.json() == {"done": True, "phase": "plan", "no_check_items": True}
    assert store["state"]["phase"] == "plan" and agu.call_count == 0
    assert [c.args[0] for c in log.call_args_list] == ["learn.probe_done"]
    assert log.call_args.kwargs["payload"]["items"] == 0


def _answer_env(monkeypatch, rl, *, history=None, correct=True, unavailable=False):
    # h-A-0 is concept A's post-test reserve (PKG-04 rule), so the served item is A-i3.
    current = {"check_item_id": "A-i3", "question_hash": "h-A-3", "node_id": "A", "difficulty": 2,
               "channel": "free_response"}
    store, _ = _probe_env(monkeypatch, rl, history=history, skills=["A"], current=current)
    calls = []

    async def fake_grade(item, answer, *, user_id, session_id):
        """Stands in for grade_answer (binding rule iv); PKG-05's tests cover the grader itself."""
        calls.append(SimpleNamespace(item_id=item.id, answer=answer, user_id=user_id, session_id=session_id))
        if unavailable:
            return SimpleNamespace(unavailable=True, correct=None, confidence=None, wrong_key=None,
                                   grader_backend=None, evidence=None)
        ok = False if answer.idk else correct
        ev = {"node_id": item.node_id, "channel": CHANNEL_FOR_FORMAT[item.format], "idk": bool(answer.idk),
              "correct": ok, "assisted": False, "max_rung": 0, "weight": 1.0, "session_id": session_id,
              "check_item_id": item.id, "question_hash": item.question_hash,
              "confidence": None if answer.idk else 0.9, "grader_backend": None if answer.idk else "gemini"}
        return SimpleNamespace(unavailable=False, correct=ok, confidence=ev["confidence"], wrong_key=None,
                               grader_backend=ev["grader_backend"], evidence=ev)

    monkeypatch.setattr(rl, "_grade", fake_grade)
    monkeypatch.setattr(rl, "_read_states", lambda _u, _c: {"A": 0.61, "B": _BELOW, "K": _PROF})
    return store, calls


def _answer(**extra):
    return {"session_id": "s1", "user_id": UID, "course_id": "c1", "question_hash": "h-A-3", **extra}


def test_probe_answer_persists_grade_answer_evidence_exactly_once(loop_on, monkeypatch):
    store, calls = _answer_env(monkeypatch, loop_on)
    with patch("routes.learn_loop.apply_graph_update", return_value=[]) as agu:
        r = client.post(f"{LOOP}/probe/answer", json=_answer(answer="because"))
    assert r.status_code == 200, r.text
    assert [c.item_id for c in calls] == ["A-i3"]
    assert calls[0].answer.answer_text == "because" and calls[0].answer.idk is False
    assert calls[0].user_id == UID and calls[0].session_id == "s1"
    assert agu.call_count == 1
    (uid, update), kw = agu.call_args
    assert uid == UID and kw.get("course_id") == "c1"
    ev = update["evidence"]
    assert len(ev) == 1 and ev[0]["node_id"] == "A" and ev[0]["channel"] == "free_response"
    assert ev[0]["correct"] is True and ev[0]["question_hash"] == "h-A-3" and ev[0]["grader_backend"] == "gemini"
    body = r.json()
    assert body["graded"] is True and body["correct"] is True and body["probe_done"] is False
    assert "reference_answer" not in body
    st = store["state"]
    assert st["probe"]["current"] is None
    assert st["probe"]["history"][-1]["p_after"] == pytest.approx(0.61)
    assert st["probe"]["history"][-1]["channel"] == "free_response"


def test_probe_answer_wrong_returns_reference(loop_on, monkeypatch):
    _answer_env(monkeypatch, loop_on, correct=False)
    with patch("routes.learn_loop.apply_graph_update", return_value=[]):
        r = client.post(f"{LOOP}/probe/answer", json=_answer(answer="nope"))
    assert r.status_code == 200 and r.json()["graded"] is True and r.json()["correct"] is False
    assert r.json()["reference_answer"] == "SECRET"  # spec §3.3; the item is now revealed (A23)


def test_probe_answer_forwards_option_and_reason(loop_on, monkeypatch):
    _, calls = _answer_env(monkeypatch, loop_on)
    with patch("routes.learn_loop.apply_graph_update", return_value=[]):
        r = client.post(f"{LOOP}/probe/answer", json=_answer(selected_option="B", reason="slope is constant"))
    assert r.status_code == 200, r.text
    a = calls[0].answer
    assert a.selected_option == "B" and a.reason == "slope is constant" and a.idk is False


def test_probe_answer_idk_goes_through_grade_answer_on_the_items_channel(loop_on, monkeypatch):
    store, calls = _answer_env(monkeypatch, loop_on)
    with patch("routes.learn_loop.apply_graph_update", return_value=[]) as agu:
        r = client.post(f"{LOOP}/probe/answer", json=_answer(idk=True))
    assert r.status_code == 200
    assert calls[0].answer.idk is True  # grade_answer builds the A1 evidence with no grader call (PKG-05)
    ev = agu.call_args.args[1]["evidence"][0]
    assert ev["channel"] == "free_response" and ev["idk"] is True and ev["correct"] is False  # A1: no "idk" channel
    assert r.json()["reference_answer"] == "SECRET"
    obs = store["state"]["probe"]["history"][-1]
    assert obs["idk"] is True and obs["correct"] is False


def test_probe_answer_hash_mismatch_is_409(loop_on, monkeypatch):
    _, calls = _answer_env(monkeypatch, loop_on)
    with patch("routes.learn_loop.apply_graph_update") as agu:
        r = client.post(f"{LOOP}/probe/answer", json=_answer(question_hash="stale", answer="x"))
    assert r.status_code == 409 and agu.call_count == 0 and calls == []


def test_probe_answer_unavailable_counts_as_not_asked(loop_on, monkeypatch):
    """A20/A22: an outage or the grader cap → no evidence for either outcome, the item is
    dropped without counting toward any cap, and the next item is served (no 503, no retry)."""
    store, _ = _answer_env(monkeypatch, loop_on, unavailable=True)
    history_before = list(store["state"]["probe"]["history"])
    with patch("routes.learn_loop.apply_graph_update") as agu, patch("services.events_service.log_event") as log:
        r = client.post(f"{LOOP}/probe/answer", json=_answer(answer="x"))
        assert r.status_code == 200 and r.json() == {"graded": False, "unavailable": True}
        assert agu.call_count == 0 and log.call_count == 0
        st = store["state"]
        assert st["probe"]["history"] == history_before and st["probe"]["current"] is None
        assert st["probe"]["unavailable"] == ["h-A-3"] and st["phase"] == "probe"
        nxt = client.post(f"{LOOP}/probe/next", json=NEXT)
    assert nxt.status_code == 200 and nxt.json()["done"] is False
    assert nxt.json()["question_hash"] != "h-A-3"


def test_probe_answer_emits_probe_done_and_moves_to_plan(loop_on, monkeypatch):
    stable = [0.55, 0.58, 0.6]
    history = [_obs("A", p, k=i) for i, p in enumerate(stable)]  # one short of MIN
    store, _ = _answer_env(monkeypatch, loop_on, history=history)
    with patch("routes.learn_loop.apply_graph_update", return_value=[]), \
         patch("services.events_service.log_event") as log:
        r = client.post(f"{LOOP}/probe/answer", json=_answer(answer="y"))
    assert r.status_code == 200 and r.json()["probe_done"] is True
    assert store["state"]["phase"] == "plan"
    assert log.call_count == 1
    name, kw = log.call_args.args[0], log.call_args.kwargs
    assert name == "learn.probe_done" and kw["category"] == "usage" and kw["user_id"] == UID
    assert set(kw["payload"]) == {"items", "misses", "novice_floor", "skills"}
    assert kw["payload"]["items"] == P.PROBE_ITEMS_PER_SKILL_MIN and kw["payload"]["skills"] == ["A"]


def test_probe_answer_rate_limited_is_429_and_grades_nothing(loop_on, monkeypatch):
    """Spec §9 / A20: /probe/answer can run the grader, so it carries PKG-06b's rate limit."""
    from services import ai_budget
    _, calls = _answer_env(monkeypatch, loop_on)
    monkeypatch.setattr(ai_budget, "rate_limited", lambda _uid: True)
    with patch("routes.learn_loop.apply_graph_update") as agu:
        r = client.post(f"{LOOP}/probe/answer", json=_answer(answer="x"))
    assert r.status_code == 429 and "ai budget reached" in r.text
    assert calls == [] and agu.call_count == 0


def test_probe_keeps_running_at_the_tutor_hard_cap(loop_on, monkeypatch):
    """A20: no PKG-08 route asks for the tutor budget; at the hard level the probe still grades
    and still serves a novice-band concept (spec §3.5: the probe is exempt from the novice pause)."""
    from services import ai_budget
    _answer_env(monkeypatch, loop_on)
    kinds = []
    hard = SimpleNamespace(level="hard", tier_ceiling="none", scope="daily_usd", reset_at=None, pause_novice=True)
    monkeypatch.setattr(ai_budget, "check", lambda _uid, kind, *a, **k: kinds.append(kind) or hard)
    with patch("routes.learn_loop.apply_graph_update", return_value=[]), patch("services.events_service.log_event"):
        a = client.post(f"{LOOP}/probe/answer", json=_answer(answer="y"))
        monkeypatch.setattr(loop_on, "_read_states", lambda _u, _c: {"A": 0.2, "B": _BELOW, "K": _PROF})
        n = client.post(f"{LOOP}/probe/next", json=NEXT)
    assert a.status_code == 200 and a.json()["graded"] is True, a.text
    assert n.status_code == 200 and n.json()["done"] is False and n.json()["node_id"] == "A", n.text
    assert "tutor" not in kinds
```
(The last posterior `0.61` from `_answer_env` is within `PROBE_STOP_DELTA` of `0.6`, so the fourth item satisfies the stop rule. If the `PROBE_STOP_DELTA` value ever changes, adjust the synthetic posteriors, not the rule. Every answer test grades `A-i3` because `h-A-0` is concept A's post-test reserve under PKG-04's rule and is never served. `0.2` is below `BAND_NOVICE_MAX`, so the last test's `/probe/next` serves a novice-band concept at the hard level.)

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_probe_planner.py -q -k "gate or probe_next or probe_answer or tutor_hard_cap"`
Expected: `AttributeError: <module 'routes.learn_loop'> has no attribute '_load_loop_state'` (or 404s on unknown paths for the gate test).

- [ ] **Step 3: Implement**

Body models in `models/__init__.py`, beside (G) — no `model_pref` field (invariant 22):
```python
class ProbeNextBody(BaseModel):
    session_id: str
    user_id: str = "user_andres"
    course_id: str


class ProbeAnswerBody(BaseModel):
    session_id: str
    user_id: str = "user_andres"
    course_id: str
    question_hash: str
    answer: str = ""
    selected_option: Optional[str] = None  # mc_reason (A22)
    reason: str = ""  # mc_reason (A22)
    idk: bool = False
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)  # stated; see Behaviour 11
```

In `routes/learn_loop.py` — imports (only those not already present): `from learning import checks, planner, probe`, `from learning.params import BKT_L0, BKT_PROFICIENT, EDGE_PREREQ_SOURCE_IS_PREREQ, PLAN_ORDER, PROBE_MAX_SKILLS, REVIEW_DAILY_BUDGET_MIN, REVIEW_SECONDS_PER_CHECK`, `from agents.tools.check import CHANNEL_FOR_FORMAT, CheckAnswer, grade_answer` (names per (E)), `from services.graph_service import apply_graph_update` (if absent), `from services import ai_budget, check_item_service, events_service` (if absent), plus (B)/(C) imports.

Seams (private, module-level; tests patch them):
```python
def _read_states(user_id: str, course_id: str) -> dict[str, float]:
    """Decayed p_known for every graph_nodes row of (user, course); BKT_L0 when
    no learner_state row exists. Uses PKG-03's reader (B)."""
    ...

def _prereq_edges(user_id: str, node_ids: list[str]) -> list[tuple[str, str]]:
    rows = table("graph_edges").select(
        "source_node_id,target_node_id",
        filters={"user_id": f"eq.{user_id}", "relationship_type": "eq.prerequisite"},
    ) or []
    keep = set(node_ids)
    out = []
    for e in rows:
        s, t = e.get("source_node_id"), e.get("target_node_id")
        if s in keep and t in keep:
            out.append((s, t) if EDGE_PREREQ_SOURCE_IS_PREREQ else (t, s))
    return out

def _course_has_items(course_id: str) -> bool:
    return check_item_service.course_has_items(course_id)   # (D); one limit=1 read (A23)

def _probe_items(course_id: str, node_ids: list[str]) -> list:
    """(D) A2: one graph_nodes read for the nodes' concept_name → _normalize_concept →
    check_item_service.list_items(course_id, concept_key) per concept (decrypted), each item
    bound to the student's node_id (binding rule iii). Unfiltered: the handlers drop the
    post-test reserve and the unavailable hashes."""

async def _grade(item, answer, *, user_id: str, session_id: str):
    """(E) grade_answer(<the underlying CheckItem>, answer, deps=..., node_id=item.node_id) with
    SaplingDeps built exactly as PKG-07's /check/answer builds them (learning_loop=True —
    grade_answer is inert when it is False).
    Returns the GradeOutcome. deps.pending_evidence is discarded, never flushed: the handler
    writes outcome.evidence itself (one write)."""

def _node_names(node_ids: list[str]) -> dict[str, str]:
    ...   # one graph_nodes read, id → concept_name
```
`_load_loop_state`/`_save_loop_state`: alias PKG-07's. Also a tiny `_loop_state_or_409(session_id, *phases) -> dict` and `_reserve_hashes(items) -> set[str]` (group by `node_id`; `checks.posttest_reserve_hash(group)` per group; drop `None`).

`/probe/next` per Behaviour 10; `/probe/answer` (handler `probe_answer`) per Behaviour 11 — write `_finish_probe(state, user_id, request_id)` used by both: sets `state["phase"] = "plan"` and emits `learn.probe_done` with `items=len(history)`, `misses=sum(not h["correct"])`, `novice_floor=probe.novice_floor(history)`, `skills=state["probe"]["skills"]`. `request_id` as `routes/learn.py:1413–1417` derives it. `/probe/next` selects with `probe.next_probe_item(states, [it for it in items if it.question_hash not in _reserve_hashes(items) | set(unavailable)], asked, channel_for_format=CHANNEL_FOR_FORMAT)` and builds `options` as `[{"letter": o.letter, "text": o.text} for o in item.options]` for `mc_reason` (else `None`). `/probe/answer`: rate limit per binding rule (v); finds the item to grade by `current["check_item_id"]` inside `_probe_items(course_id, state["probe"]["skills"])` (one read; the key never leaves the process); builds `CheckAnswer(question_hash=body.question_hash, answer_text=body.answer, selected_option=body.selected_option, reason=body.reason, idk=body.idk)`; `outcome = await _grade(item, answer, user_id=..., session_id=...)`; unavailable → Behaviour 11's first branch; else ONE `apply_graph_update(user_id, {"evidence": [outcome.evidence]}, course_id=course_id)` in the handler body, then `p_after = _read_states(user_id, course_id).get(node_id, BKT_L0)`. `outcome.evidence` is persisted as returned (it already carries the A22 weight and `grader_backend`; PKG-03's `apply_graph_update` re-validates it) — never rebuilt here. No `ai_budget.check` call anywhere in these handlers (Behaviour 9).

Invariant 26 (binding (I)): add `probe_answer` — the handler's function name, or its route path if (I) shows the allow-list keys on paths — to the explicit-submission allow-list of `test_inv_26_evidence_only_from_explicit_submission`. Change nothing else in that test.

- [ ] **Step 4: Run tests, lint, invariants, PKG-07's suite**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_probe_planner.py tests/test_learn_loop_routes.py tests/test_learning_loop_invariants.py -q && venv/bin/ruff check .`
Expected: all passed (`inv_26` included); `All checks passed!`.

- [ ] **Step 5: Commit**

```
git add backend/routes/learn_loop.py backend/models/__init__.py backend/tests/test_learning_probe_planner.py backend/tests/test_learning_loop_invariants.py
git commit -m "feat(learning-loop): PKG-08 — /probe/next and /probe/answer (grade_answer only, unavailable = not asked, evidence via apply_graph_update once)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 6: Routes `GET /plan`, `POST /plan/approve`

**Files:**
- Modify: `backend/routes/learn_loop.py`, `backend/models/__init__.py` (`PlanApproveBody`)
- Modify: `backend/tests/test_learning_probe_planner.py` (append route half, part 2)

**Interfaces:**
- Consumes: (C) `order_due`/`budget_select`, `_read_states`, `_prereq_edges`, `_node_names`, `learning.planner`.
- Produces: the two routes; seam `_due_reviews(user_id, course_id, states) -> list[str]` (node ids, budgeted).

- [ ] **Step 1: Write the failing tests (append; also add the two `/plan` rows to `GATED_ROUTES`)**

```python
GATED_ROUTES.extend([
    ("get", "/plan?session_id=s1&user_id=user_andres&course_id=c1", None),
    ("post", "/plan/approve", {"session_id": "s1", "user_id": UID, "concept_ids": ["n"]}),
])


def _plan_env(monkeypatch, rl, *, phase="plan", proposed=None):
    store, load, save = _state_store({"phase": phase, "probe": {"skills": ["B"], "history": [], "current": None},
                                      "plan": ({"proposed": proposed,
                                                "proposed_kinds": {n: ("review" if n.startswith("R") else "new") for n in proposed}}
                                               if proposed else {})})
    monkeypatch.setattr(rl, "_load_loop_state", load)
    monkeypatch.setattr(rl, "_save_loop_state", save)
    states = {"P": _PROF, "N1": _BELOW, "N2": _BELOW, "K": _PROF, "R1": _BELOW, "X": _BELOW}
    monkeypatch.setattr(rl, "_read_states", lambda _u, _c: states)
    monkeypatch.setattr(rl, "_prereq_edges", lambda _u, _ids: [("P", "N1"), ("P", "N2"), ("P", "K"), ("N1", "X")])
    monkeypatch.setattr(rl, "_due_reviews", lambda _u, _c, _s: ["R1"])
    monkeypatch.setattr(rl, "_node_names", lambda ids: {i: f"name-{i}" for i in ids})
    return store


def test_plan_get_returns_ordered_sections_and_stores_proposal(loop_on, monkeypatch):
    store = _plan_env(monkeypatch, loop_on)
    r = client.get(f"{LOOP}/plan", params={"session_id": "s1", "user_id": UID, "course_id": "c1"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["order"] == list(P.PLAN_ORDER)
    ids = [c["node_id"] for c in body["concepts"]]
    kinds = [c["kind"] for c in body["concepts"]]
    assert ids[0] == "R1" and kinds[0] == "review"
    assert set(ids[1:3]) == {"N1", "N2"} and kinds[1:3] == ["new", "new"]
    assert ids[3:] == ["K"] and kinds[3:] == ["sibling"]          # proficient sibling, once
    assert "X" not in ids                                          # blocked behind N1
    assert all(c["concept_name"] == f"name-{c['node_id']}" for c in body["concepts"])
    assert store["state"]["plan"]["proposed"] == ids


def test_plan_get_wrong_phase_is_409(loop_on, monkeypatch):
    _plan_env(monkeypatch, loop_on, phase="probe")
    r = client.get(f"{LOOP}/plan", params={"session_id": "s1", "user_id": UID, "course_id": "c1"})
    assert r.status_code == 409


def test_plan_approve_stores_order_emits_event_moves_to_teach(loop_on, monkeypatch):
    store = _plan_env(monkeypatch, loop_on, proposed=["R1", "N1", "N2", "K"])
    with patch("services.events_service.log_event") as log:
        r = client.post(f"{LOOP}/plan/approve", json={"session_id": "s1", "user_id": UID, "concept_ids": ["R1", "N2"]})
    assert r.status_code == 200 and r.json() == {"phase": "teach", "concept_ids": ["R1", "N2"]}
    assert store["state"]["phase"] == "teach" and store["state"]["plan"]["approved"] == ["R1", "N2"]
    assert store["state"]["plan"]["cursor"] == 0 and store["state"]["concept"] == "R1"  # A27: PKG-07 activates from here
    assert store["state"]["teach_turns"] == 0 and store["state"]["concept_checks"] == 0 and "active" not in store["state"]
    assert log.call_count == 1
    assert log.call_args.args[0] == "learn.plan_approved"
    assert log.call_args.kwargs["payload"] == {"concept_ids": ["R1", "N2"], "n_reviews_first": 1}


def test_plan_approve_rejects_ids_outside_proposal_and_empty(loop_on, monkeypatch):
    _plan_env(monkeypatch, loop_on, proposed=["R1", "N1"])
    with patch("services.events_service.log_event") as log:
        r1 = client.post(f"{LOOP}/plan/approve", json={"session_id": "s1", "user_id": UID, "concept_ids": ["ZZ"]})
        r2 = client.post(f"{LOOP}/plan/approve", json={"session_id": "s1", "user_id": UID, "concept_ids": []})
    assert r1.status_code == 422 and r2.status_code == 422 and log.call_count == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_probe_planner.py -q -k "plan_get or plan_approve"`
Expected: 4 FAIL — 404 `Not Found` (routes absent) or `AttributeError: … '_due_reviews'`.

- [ ] **Step 3: Implement**

`PlanApproveBody(session_id: str, user_id: str = "user_andres", concept_ids: list[str])`.

`_due_reviews(user_id, course_id, states)`: read the FSRS fields PKG-03 stores on `learner_state` (through (B), or one `table("learner_state").select("node_id,fsrs_d,fsrs_s,fsrs_last_review_at,fsrs_due_at", filters={"user_id": ..., "node_id": f"in.({...})"})` if the reader does not expose them), call (C) `order_due(...)` then `budget_select(..., REVIEW_DAILY_BUDGET_MIN, REVIEW_SECONDS_PER_CHECK)` with the signatures HANDOFF-02 records, and return node ids in that order. No FSRS state → `[]`.

`GET /plan` per Behaviour 13: `states = _read_states(...)`; `edges = _prereq_edges(user_id, list(states))`; `fringe = planner.outer_fringe(states, edges)`; build `parents: dict[node, set[prereq]]` from `edges`, `siblings_fn = lambda n: sorted(m for m in states if m != n and parents.get(m, set()) & parents.get(n, set()))`; `proficient = frozenset(n for n, p in states.items() if p >= BKT_PROFICIENT)`; `out = planner.plan(fringe, _due_reviews(...), siblings_fn, None, proficient=proficient)`; names via `_node_names`; store `proposed`; respond. `n_reviews_first` on approve = length of the leading run of ids whose kind in the stored proposal was `review` — store `proposed_kinds: {node_id: kind}` beside `proposed` on `GET /plan` so approve can compute it without recomputing the plan (the test env seeds both keys).

`POST /plan/approve` per Behaviour 14.

- [ ] **Step 4: Run tests, lint, invariants, full suite**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_probe_planner.py tests/test_learn_loop_routes.py tests/test_learning_loop_invariants.py -q && venv/bin/python -m pytest tests/ -q && venv/bin/ruff check .`
Expected: package file ≥ 47 passed (16 probe + 8 planner + 17 Task 5 cases + 6 Task 6 cases; the gate test now has four rows); full suite `N₀ + (new tests) passed`, zero failures; `All checks passed!`.

- [ ] **Step 5: Commit**

```
git add backend/routes/learn_loop.py backend/models/__init__.py backend/tests/test_learning_probe_planner.py
git commit -m "feat(learning-loop): PKG-08 — GET /plan (outer fringe, PLAN_ORDER) and POST /plan/approve

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 7: Hand-off + ledger

- [ ] **Step 1:** Write `docs/superpowers/plans/learning-loop/HANDOFF-08.md` from `HANDOFF-template.md`. "Verify commands" must be exactly these four lines (they become PKG-13's State-of-the-world rows):

```
cd backend && venv/bin/python -m pytest tests/test_learning_probe_planner.py -q                 → N passed (N ≥ 15)
grep -cE "^def (next_probe_item|probe_done|novice_floor)\(" backend/learning/probe.py            → 3
grep -cE "^def (outer_fringe|plan)\(" backend/learning/planner.py                                → 2
grep -c '"learn\.probe_done"\|"learn\.plan_approved"' backend/services/events_service.py         → 2
```

Fixed headings and what goes under each: **What changed** — probe + plan phases exist behind the gate; four routes; two events; `/probe/answer` grades through `grade_answer` and treats `unavailable` as not asked; `/probe/next` excludes the post-test reserve and reports `no_check_items`. **Symbols added** — every seam and route above (name `_probe_items` as PKG-08's node → `concept_key` → items resolver, the inverse of the `node_id` resolver HANDOFF-05 asks for), `learning.probe.*`, `learning.planner.*`, `ProbeNextBody`/`ProbeAnswerBody`/`PlanApproveBody`, the two event types, the `/probe/next` response shape (incl. `options`, `no_check_items`) and the `/probe/answer` response shapes (`graded: true` and `{"graded": false, "unavailable": true}`) — PKG-13 builds against these. **Constants chosen** — the four † rows with `†`, `EDGE_PREREQ_SOURCE_IS_PREREQ = True †verified against: <seeds only | seeds + N staging rows>`, and the import path of PKG-05's `CHANNEL_FOR_FORMAT` the route passes in. **Deviations from spec** — the params.py touch (`PKG-01 reopened`), the `proficient=`, `skills=` and `channel_for_format=` keyword extensions, the "coupled with ≥ max_coupled already-chosen" reading of the coupled rule, novice floor session-wide, the `graded` key on the `/probe/answer` response, how `/probe/answer` attaches the rate limit (and whether the gate-false path performs that read — binding rule (v)), whether stated `confidence` reaches `CheckAnswer`. **Known gaps** — `goal_filter=None` (no syllabus-week helper exists), `wrong_key` ignored by the route (PKG-10's hook lives inside `grade_answer`), no frontend (PKG-13), probe skills fixed on first `/probe/next` and never re-derived within a session, at the grader cap every probe answer comes back `unavailable` and the probe ends only when the candidates run out (each skill's items minus its reserve, all answered ungraded). **Open questions** — (1) edge direction: nothing enforces the seed convention on tutor-emitted `new_edges` (`agents/chat_tutor.py:94` names types, not direction) — should PKG-14's cutover add a prompt line or a write-side check? (2) should the goal filter come from `exam_proximity` (assignments within `FSRS_EXAM_WINDOW_DAYS`) once PKG-12 lands? (3) the initial phase PKG-07 writes vs. `probe` (Behaviour 10) — record what you found. (4) should `/probe/next` finish the probe early after consecutive `unavailable` grades (the grader-cap gap above) instead of serving items nobody can grade?

- [ ] **Step 2:** Ledger rows: `| 08 | probe-planner | done | feat/learning-loop-08-probe-planner | <sha> | test_learning_probe_planner.py (≥ 47) + inv_16 + inv_26 allow-list | — | HANDOFF-08.md |`, the `07 | loop-tutor | verified | …` row from State of the world, and `01 | bkt-core | reopened | … | PKG-08 † constants` if Task 2 Step 1 ran. Deviations: the † lines in the LEDGER format.

- [ ] **Step 3: Commit**

```
git add docs/superpowers/plans/learning-loop/HANDOFF-08.md docs/superpowers/plans/learning-loop/HANDOFF-01.md docs/superpowers/plans/learning-loop/LEDGER.md
git commit -m "docs(learning-loop): PKG-08 — hand-off and ledger

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 8: PR

- [ ] **Step 1:** Run the self-check loop once more (all seven steps), then:

```
gh pr create --title "feat(learning): PKG-08 probe-planner" --body-file - <<'EOF'
Learning loop series, package 11 of 17. Spec: docs/superpowers/specs/2026-09-26-learning-loop-design.md §3.3–3.5, §6, §9, §13 A16/A20/A22/A23.

- learning/probe.py (pure): expected_success, next_probe_item (probe band, per-skill + session caps), probe_done (stop rule), novice_floor
- learning/planner.py (pure): outer_fringe over oriented prerequisite edges, plan() in PLAN_ORDER with the coupled cap
- routes/learn_loop.py: POST /probe/next (never serves the post-test reserve; no_check_items for a course without items; mc_reason options without keys), POST /probe/answer (grade_answer only — no tutor turn; unavailable counts as not asked, no evidence either outcome; evidence through apply_graph_update exactly once; rate-limited), GET /plan, POST /plan/approve
- the probe runs at every budget level: no ai_budget.check in these routes (the grader cap lives inside grade())
- events learn.probe_done, learn.plan_approved (+ pin)
- inv_16: probe.py/planner.py stay pure; /probe/answer joins the inv_26 explicit-submission allow-list
- † constants: PROBE_DIFFICULTY_SHIFT, NOVICE_FLOOR_IDK (+ two derived names); EDGE_PREREQ_SOURCE_IS_PREREQ verified — see HANDOFF-08

Flag-off behaviour is byte-identical: every new route returns 404 before any read when the gate is false.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
```

## Self-check loop (run after every task, and once more before the PR)

1. `cd backend && venv/bin/ruff check . && venv/bin/ruff format --check learning tests/test_learning_*.py`
2. `venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q`
3. `venv/bin/python -m pytest tests/ -q` (no `SAPLING_MODEL_MODE` exported)
4. Prompts/tool descriptions touched? **No** in this package → skip evals. `/probe/answer` *calls* PKG-05's `grade_answer`; it does not edit `agents/grader.py`, `agents/tools/check.py`, or any prompt. If you find yourself editing anything under `backend/agents/`, stop: scope creep. (Sanity: `cd backend && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/grader.py` still ≥ baseline — replay only, no recording.)
5. Request-path agent or route touched? **Yes** (four routes on the mounted loop router) → run the E2E cycle once before the PR, under the stack lock, to prove the existing lane is unaffected (no Playwright journey exercises these routes until PKG-13; `frontend/e2e/learn-loop.spec.ts` is still a stub):
   `flock /tmp/claude-$(id -u)/sapling-e2e-stack.lock sh -c 'make e2e-up && (cd frontend && npx playwright test) && (cd backend && venv/bin/python -m e2e_oracles); rc=$?; make e2e-down; exit $rc'` → journeys pass, oracles exit 0, logscan clean.
6. Scope check: `git diff --stat main...HEAD` — every path must be in this prompt's Files lists. Anything else: `git checkout main -- <path>` or record a Deviation.
7. Sync check: `grep -o "E2E_[A-Z_]*" backend/agents/function_handlers_e2e.py | sort -u` unchanged from `main`.

Green = all seven clean. Max 5 iterations per loop; then write a `BLOCKED` row in `LEDGER.md` with hypothesis, commands, outputs, and stop.

## Regression guard

- Pre-series suite count N₀ (from State of the world) must be unchanged except for the tests this package adds. Zero failures, zero new skips outside `test_learning_loop_invariants.py`.
- Dependency suites unchanged and green: `tests/test_learn_loop_routes.py` (PKG-07), `tests/test_learning_ai_budget.py` (PKG-06b), `tests/test_learning_decisions.py` (PKG-05b), `tests/test_learning_check_tool.py` (PKG-05), `tests/test_learning_check_items.py` (PKG-04), `tests/test_learning_evidence_apply.py` + `tests/test_graph_service.py` (PKG-03), `tests/test_learning_fsrs.py` (PKG-02), `tests/test_learning_bkt.py` (PKG-01), `tests/test_learning_gate.py` (PKG-00).
- Pre-series suites this package touches: `tests/test_event_capture_seams.py` (taxonomy pin — extended, not changed), `tests/test_learn_routes.py` + `tests/test_learn_stream_routes.py` (legacy learn routes — untouched, must stay green), `tests/test_model_mode_seam.py`.
- With `LEARNING_LOOP_ENABLED` unset: the four new routes return 404 before any read (`test_gate_false_is_404_and_reads_nothing`); no legacy route changes. With it set and the staff/QA toggle on (build phase; spec §13 A14): only the four new routes change behaviour.

## Acceptance criteria (the next session pastes these)

1. `cd backend && venv/bin/python -m pytest tests/test_learning_probe_planner.py -q` → `N passed (N ≥ 15)` (expect ≥ 47)
2. `grep -cE "^def (next_probe_item|probe_done|novice_floor)\(" backend/learning/probe.py` → `3`
3. `grep -cE "^def (outer_fringe|plan)\(" backend/learning/planner.py` → `2`
4. `grep -c '"learn\.probe_done"\|"learn\.plan_approved"' backend/services/events_service.py` → `2`
5. `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_05 or inv_16 or inv_26"` → `3 passed`
6. `cd backend && venv/bin/python -m pytest tests/ -q` → zero failures; `venv/bin/ruff check .` → `All checks passed!`
7. `grep -cE "probe/next|probe/answer|\"/plan\"|plan/approve" backend/routes/learn_loop.py` → `≥ 4`
8. `git diff --stat main...HEAD` lists only: `backend/learning/probe.py`, `backend/learning/planner.py`, `backend/learning/params.py`, `backend/routes/learn_loop.py`, `backend/models/__init__.py`, `backend/services/events_service.py`, `backend/tests/test_learning_probe_planner.py`, `backend/tests/test_learning_loop_invariants.py`, `backend/tests/test_event_capture_seams.py`, `docs/superpowers/plans/learning-loop/{HANDOFF-08.md,HANDOFF-01.md,LEDGER.md}`.
9. `LEDGER.md` has rows `08 | probe-planner | done | …` and `07 | loop-tutor | verified | …`.
10. `grep -c "no_check_items" backend/routes/learn_loop.py` → `≥ 1`; `grep -c "posttest_reserve_hash" backend/routes/learn_loop.py` → `≥ 1`.

## Hand-off

`docs/superpowers/plans/learning-loop/HANDOFF-08.md` per the template; the Verify commands block is fixed above (Task 7). Record every binding from Task 2 Step 0 ((B)–(I)) under "Symbols added" as `<their name> — used by PKG-08 as <seam>` so PKG-13 can build the frontend against stable names. Open questions: the four in Task 7 Step 1.

## Do not

- Do not run an LLM tutor turn in either phase; do not edit anything under `backend/agents/` (`grade_answer` is called, not changed). No new `AgentTask`, no function-mode handler, no eval dataset.
- Do not call `ai_budget.check` from any PKG-08 route (A20: the probe runs at the tutor hard cap; the grader cap is enforced inside `grade()`). Do not answer an `unavailable` grade with 503 or re-serve that item; do not record an observation or evidence for it.
- Do not write `graph_nodes`, `graph_edges`, `node_mastery_events`, or `learner_state` from the route — evidence goes through `apply_graph_update` exactly once per answer (spec §5, invariant 1). Do not add a second writer of `sessions.loop_state`; use PKG-07's accessors.
- Do not touch `services/chat_stream.py`, `services/graph_service.py`, `agents/chat_tutor.py`, `learning/{bkt,fsrs,evidence,learner_state,checks,policy,gates,ladder,leak}.py`. `learning/params.py` only for the four † names (and the direction flip if Step 0 demands it), each in its own `fix(learning-loop): PKG-01` commit.
- `learning/probe.py` and `learning/planner.py` import nothing from `agents`, `pydantic_ai`, `google`, `db`, and not `learning.checks` either (Protocol instead).
- Never return `reference_answer`, `rubric_json`, `common_wrong_json`, `correct_option`, `canonical_answer`, or an option's `wrong_key` from `/probe/next`; never serve a concept's post-test reserve; `/probe/answer` returns `reference_answer` only when `correct` is false (wrong or idk). Never filter or join on encrypted columns.
- No numeric literals in loop code: every number is a name in the table above; test data may use synthetic `p` values but thresholds come from `learning.params`.
- All Supabase access through `db/connection.py::table()`; no `httpx`, no `supabase` import. No migration in this package. No `lru_cache`.
- Do not skip, xfail, or delete any pre-existing test. Do not hand-edit eval cassettes or baselines.
- Logscan `ALLOWLIST` in `backend/e2e_oracles/logscan.py` stays `()`.
- End every commit with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; end the PR body with the Claude Code attribution line.

## If you get stuck

1. Re-read §Spec and the spec file's §3.3/§3.4/§3.5/§6/§9/§13 before guessing; then the relevant HANDOFF's "Symbols added" and "Post-hoc changes".
2. A binding in Task 2 Step 0 is missing → the dependency is not done: `BLOCKED` row in `LEDGER.md` naming the symbol and the HANDOFF that should have listed it; stop.
3. Three failed iterations on one task → append a `BLOCKED` row to `LEDGER.md` (hypothesis, commands run, outputs), commit what is green, open the PR as draft, stop.
4. Never widen scope to unblock. Never disable a test to unblock.
5. Ambiguity → choose the option closest to the spec, mark it `†` in the hand-off, continue.
