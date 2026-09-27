# PKG-12 review-surfaces — Learning Loop series (15 of 17)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> You are a fresh session. Nothing outside this file, `docs/superpowers/plans/learning-loop/LEDGER.md`, the `HANDOFF-NN.md` files it names, and the files this prompt lists is known to you. Do not infer intent from chat history you do not have. Do not read the whole research corpus; read the sections named below.

## Package id + goal

**PKG-12 `review-surfaces`.** After this package: a student on the loop path has a daily review queue with a time budget. Due flashcards (facts) and due concepts (each mapped to a check item) are merged, ordered by the DASH rule, and cut at the daily budget. A concept's check item is never one the student has already seen or had revealed, nor the concept's post-test reserve (spec §13 A23); when that leaves nothing, review falls back to excluding only revealed items and the reserve, and a concept with nothing left is counted `unservable`. Both kinds are graded through the same path every other check uses — check items through PKG-05's `grade_answer` (A16; an `mc_reason` item is served with its stored options and answered with an option plus a reason, A22), whose one Evidence goes to `apply_graph_update` exactly once, so a review is evidence and moves `learner_state`; flashcards through the PKG-11 FSRS rating path. A grader outage or the daily grade cap writes nothing for either outcome (invariant 28). Review keeps working at the tutor hard budget level; only novice-band concepts pause there (A20). Successive relearning is enforced per item (criterion in the acquisition session, then one recall in each of the next sessions). Three gated routes under `/api/learn/loop/review/*` serve it (`/review/answer`, the only one that can run a model, carries the A20 rate limit); the Study screen shows a "Due today" queue (`DueQueue.tsx`, the launch Study surface, spec §11.3) when the loop is active and is byte-identical otherwise. `tests/test_learning_review.py` proves it.

Branch: `feat/learning-loop-12-review-surfaces`. PR title: `feat(learning): PKG-12 review-surfaces`.

Depends on (spec §14): **05, 06b, 07, 11** (code) — `grade_answer` (PKG-05, routed through PKG-05b's decision seam), `ai_budget.check` / `enforce_rate_limit` (PKG-06b), the router, gate, deps builder and seen/revealed readers (PKG-07), the flashcard FSRS helper (PKG-11). Runs after PKG-11 and before PKG-13 in the strict one-at-a-time order `00, 01, 02, 03, 04, 05, 05b, 06, 06b, 07, 08, 09, 10, 11, 12, 13, 14`.

## Read before you start (in this order)

0. `docs/superpowers/specs/2026-09-26-learning-loop-design.md` **§13 Amendments log** — in force; where this file and §13 disagree, §13 wins. Re-read it before Task 1. The rows that bind this package: **A16** (grade in the route through `grade_answer`; review is one of its four callers), **A22** (serve the stored `options_json`, never rebuilt, correctness never marked; symmetric missingness), **A23** (seen/revealed/post-test-reserve exclusion, the revealed-only fallback, `unservable`), A20 (review under the caps: it keeps working at the tutor hard level, novice-band concepts pause, the grader cap makes a grade `unavailable`, the rate limit sits on `/review/answer`), A14 and A31 (the loop is the default for every student at launch; during the build `learning_loop_beta` is a staff/QA toggle set by SQL and in no settings API field, never set by a student PATCH — Task 6's manual check), plus A2 (items keyed on `course_id`/`concept_key`), A7 (exam beats large set; never-reviewed R = 1.0), A28 (§3.2 is now the FSRS-6 form PKG-02 shipped: same-day floor, lapse cap, unclamped reversion target, `FSRS_STABILITY_MIN`), A9 (the `sessions.mode` migration), A13 (`days_until_next_exam` drives `retention_target`).
1. The same spec's §3.5–§3.6 (cost/routing/decision constants — the degradation ladder's hard-level "keeps working" list names the review queue and self-rated flashcards; the grader-cap row; the validity rule), §7 (two-phase gate), §8 (invariants 13–29 — this package asserts 19 and extends 26), §14 (order and dependencies).
2. `docs/superpowers/plans/learning-loop/LEDGER.md` — a package's state is its LATEST row (README "Ledger reading"); refuse to start if any earlier package's latest row is `blocked` or `in-progress`. The latest rows of 00–11, 05b and 06b must be `done`, `verified` or `reopened` (spec §14: 05, 06b, 07 and 11 are this package's dependencies, and packages run strictly one at a time).
3. `docs/superpowers/plans/learning-loop/HANDOFF-02.md`, `HANDOFF-03.md`, `HANDOFF-04.md`, `HANDOFF-05.md`, `HANDOFF-05b.md`, `HANDOFF-06b.md`, `HANDOFF-07.md`, `HANDOFF-11.md` — §Symbols added, §Post-hoc changes and §Open questions. From HANDOFF-06b take `ai_budget.check`'s exact signature, whether it is `async`, `BudgetDecision.pause_novice`, and `enforce_rate_limit`; from HANDOFF-07 the deps builder `/check/answer` uses, how it resolves a check item's `node_id`, how it attaches `enforce_rate_limit`, `loop_state_store.seen_hashes`/`revealed_hashes`, and the shape of `test_inv_26`'s allow-list. This prompt names the symbols it consumes under §Spec/"Names from earlier hand-offs"; where a hand-off's name differs, the hand-off wins (see the rule there).
4. `CLAUDE.md` §Conventions and §Gotchas — the standing rules the "Do not" list below repeats.
5. `docs/superpowers/specs/2026-09-26-learning-loop-design.md` §3.2 (FSRS: budget, ordering, retention targets, successive-relearning constants, rating map), §3.3 "Evidence mapping by rung" (the wrong-answer feedback rule), §4 (the `check_items` DDL — `options_json`, `correct_option`; the PKG-12 `sessions.mode` DDL), §5 (Evidence model, `apply_graph_update` contract incl. `graph_update["retention"]`), §6 (`review.served`, `review.graded`), §7 (gate, 404 body), §8 (invariants 1, 5, 7, 8, 19, 22, 26, 28), §9 (the route table and the rate-limit rule).
6. `docs/research/learning-loop/AI tutor learning loop research.md` §"Schedule review with FSRS-6 at 90% retention and successive relearning" (lines ~98–122; the retention-target rule, the |R − threshold| ordering, successive relearning) and §"Check: free response and teach-back for credit, multiple choice for speed" (lines ~78–81). Nothing else from the corpus.
7. `docs/superpowers/plans/learning-loop/README.md` — series conventions. `HANDOFF-template.md` — what you write at the end.
8. Code you will modify: `backend/learning/review.py` (stub), `backend/learning/params.py` (append three names), `backend/routes/learn_loop.py` (PKG-07's router; read the whole file: its gate pattern, body models, error helpers, the `/check/answer` handler), `backend/services/events_service.py:97–170` (`EVENT_TAXONOMY`), `backend/tests/test_event_capture_seams.py:84–125` (the pin), `backend/tests/test_learning_loop_invariants.py` (incl. PKG-07's `test_inv_26_evidence_only_from_explicit_submission` allow-list), `frontend/src/lib/api.ts:807–843` (flashcard calls; add the review calls after `deleteFlashcard`), `frontend/src/components/screens/Study.tsx:107–196` (`Study` shell, mode switch) and `:595–877` (`FlashcardsMode`), `docs/frontend-testids.md` §"Current inventory".
9. Code you will consume, read only: `backend/learning/fsrs.py` (PKG-02: `retrievability`, `interval`, `next_state`, `rating_for`, `order_due`, `budget_select`), `backend/learning/bkt.py` (`decayed_p`, `band`), `backend/learning/learner_state.py` (PKG-03: the `learner_state` read), `backend/learning/checks.py` + `backend/services/check_item_service.py` (PKG-04: `CheckItem` with decrypted `options`/`correct_option`, `list_items`, `select_item`, `posttest_reserve_hash`), `backend/agents/tools/check.py` (PKG-05, routed through the decision seam by PKG-05b: `grade_answer`, `CheckAnswer`, `GradeOutcome`, `CHANNEL_FOR_FORMAT`), `backend/learning/loop_state_store.py` (PKG-07: `seen_hashes`, `revealed_hashes`), `backend/services/ai_budget.py` (PKG-06b: `check`, `enforce_rate_limit`), `backend/services/graph_service.py::_normalize_concept` (A2 concept key), `backend/routes/flashcards.py:295–383` (`get_flashcards` select at :312–315, `rate_card` :345–383, the PKG-11 FSRS branch inside it), `backend/services/graph_service.py::apply_graph_update` (:683 on `main` before the series; PKG-03 moved it — grep), `backend/services/exam_proximity.py:146–190` (`days_until_next_exam(user_id, course_id) -> int | None`; `0` = today, `None` = none/unknown; never raises), `backend/services/academics.py:242` (`user_offering_ids_for_course`), `backend/routes/learn.py:415–437` (the lazy `sessions` insert shape), `backend/db/migrations/0025_study_integrity.sql:70–81` (`sessions.mode` CHECK).
10. Code you will mirror: `backend/tests/test_graph_service.py:25–75` (`_mock_table`, `_cached_mock_table`), `backend/tests/test_achievement_dispatch.py:186–210` (TestClient + `patch("routes.<mod>.table")` route-test shape), `backend/tests/test_flashcards_routes.py:255–283` (encrypted-column assertion shape).

## State of the world

Verify the base before Task 1. Every row must be green. The PKG-00, 02, 03, 04, 05, 06b, 07 and 11 rows are those packages' hand-off Verify blocks, verbatim (PKG-05b is verified by the packages that consume it directly and reaches this one through PKG-05's `grade_answer`).

| check | command | expected |
|---|---|---|
| hermetic suite green | `cd backend && venv/bin/python -m pytest tests/ -q -x` | `… passed` (note the count N₀) |
| lint green | `cd backend && venv/bin/ruff check .` | `All checks passed!` |
| PKG-00 | `cd backend && venv/bin/python -m pytest tests/test_learning_gate.py -q` | `13 passed` |
| PKG-00 | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q` | `4 passed, 8 skipped (later packages raise the passed count)` — expect the passed count to be higher now; zero failures |
| PKG-00 | `cd backend && venv/bin/python -m pytest tests/test_learning_deps.py tests/test_learning_settings_flag.py tests/test_learning_loop_beta_migration.py -q` | all passed |
| PKG-00 | `grep -n "^LEARNING_LOOP_ENABLED" backend/config.py` | 1 hit |
| PKG-00 | `ls backend/db/migrations/*_learning_loop_beta.sql` | 1 file |
| PKG-02 | `cd backend && venv/bin/python -m pytest tests/test_learning_fsrs.py -q` | `N passed` (N ≥ 15) |
| PKG-02 | `grep -cE "^def (retrievability\|interval\|next_state\|rating_for\|order_due\|budget_select)\(" backend/learning/fsrs.py` | `6` |
| PKG-02 | `cd backend && venv/bin/python -c "from learning.params import FSRS_W; assert len(FSRS_W)==21; print('ok')"` | `ok` |
| PKG-03 | `cd backend && venv/bin/python -m pytest tests/test_learning_evidence_apply.py tests/test_graph_service.py -q` | all passed |
| PKG-03 | `ls backend/db/migrations/*_learning_learner_state.sql` | 1 file |
| PKG-03 | `grep -c '"evidence"' backend/services/graph_service.py` | ≥ 1 |
| PKG-03 | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k inv_01` | `1 passed` |
| PKG-04 | `cd backend && venv/bin/python -m pytest tests/test_learning_check_items.py -q` | `N passed` (N ≥ 14) |
| PKG-04 | `ls backend/db/migrations/*_learning_check_items.sql` | 1 file |
| PKG-04 | `grep -c '"check_items"' backend/agents/_providers.py backend/agents/function_handlers_e2e.py` | ≥ 1 each |
| PKG-04 | `grep -ohE "options_json\|correct_option\|answer_kind\|canonical_answer\|canonical_verified\|stepwise" backend/db/migrations/*_learning_check_items.sql \| sort -u \| wc -l` | `6` |
| PKG-04 | `grep -c -- "--all-courses" backend/scripts/backfill_check_items.py` | ≥ 1 |
| PKG-04 | `cd backend && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/check_items.py` | every evaluator ≥ baseline |
| PKG-04 | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_06 or inv_09 or inv_12"` | `3 passed` |
| PKG-05 | `cd backend && venv/bin/python -m pytest tests/test_learning_check_tool.py -q` | `N passed` (N ≥ 16) |
| PKG-05 | `grep -c '"grader"' backend/agents/_providers.py backend/agents/function_handlers_e2e.py` | ≥ 1 each |
| PKG-05 | `grep -c '"grader_second"' backend/agents/_providers.py backend/agents/function_handlers_e2e.py` | ≥ 1 each |
| PKG-05 | `grep -c "^async def grade_answer" backend/agents/tools/check.py` | `1` |
| PKG-05 | `ls backend/db/migrations/*_learning_grader_backend.sql` | 1 file |
| PKG-05 | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_14 or inv_28"` | `2 passed` |
| PKG-05 | `cd backend && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/grader.py` | every evaluator ≥ baseline |
| PKG-06b | `cd backend && venv/bin/python -m pytest tests/test_learning_ai_budget.py -q` | `N passed` (N ≥ 15) |
| PKG-06b | `ls backend/db/migrations/*_learning_llm_usage_tokens.sql` | 1 file |
| PKG-06b | `grep -cE "^(async )?def (check\|rate_limited\|enforce_rate_limit)\(" backend/services/ai_budget.py` | `3` |
| PKG-06b | `grep -c '"ai\.budget_capped"' backend/services/events_service.py` | `1` |
| PKG-06b | `grep -c "cached_tokens" backend/agents/usage.py` | ≥ 1 |
| PKG-06b | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_23 or inv_28"` | `2 passed` |
| PKG-07 | `cd backend && venv/bin/python -m pytest tests/test_learn_loop_routes.py -q` | `N passed` (N ≥ 25) |
| PKG-07 | `grep -c "learn_loop" backend/main.py` | ≥ 1 |
| PKG-07 | `grep -c '"loop_tutor"' backend/agents/_providers.py backend/agents/function_handlers_e2e.py` | ≥ 1 each |
| PKG-07 | `grep -ohE '"loop_tutor(_lite\|_deep)?"' backend/agents/_providers.py \| sort -u \| wc -l` | `3` |
| PKG-07 | `grep -c "learning_loop" backend/agents/chat_tutor.py` | ≥ 1 |
| PKG-07 | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_15 or inv_22 or inv_23 or inv_26 or inv_27 or inv_29"` | `6 passed` |
| PKG-07 | `cd backend && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/loop_tutor.py` | every evaluator ≥ baseline for every tier slot |
| PKG-11 | `cd backend && venv/bin/python -m pytest tests/test_learning_flashcards_fsrs.py tests/test_quiz_scoring_e.py -q` | all passed |
| PKG-11 | `ls backend/db/migrations/*_learning_flashcards_fsrs.sql` | 1 file |
| PKG-11 | `grep -c "learning_loop_active" backend/routes/quiz.py backend/routes/flashcards.py` | ≥ 1 each |
| review stub inert | `grep -rn "learning.review\|from learning import review" backend --include='*.py' \| grep -v "^backend/learning/review.py"` | empty |
| frontend types | `cd frontend && npx tsc --noEmit` | clean |
| latest migration prefix | `ls backend/db/migrations \| tail -1` | a `2026…` timestamped file; your migration's prefix must sort after it |

Rule: any red row → STOP. Diagnose, repair on this branch as commit `fix(learning-loop): repair pre-series base — <what>` (or `fix(learning-loop): PKG-MM — <what>` when the fault is in an earlier package; MM gets a `reopened` ledger row), record the deviation in `LEDGER.md`, re-run all rows. Never build on a broken base.

## Spec

### Names from earlier hand-offs

This prompt was written before PKG-02/03/04/05/05b/06b/07/11 executed. It refers to their symbols by the names below. **The hand-off wins**: if `HANDOFF-NN.md` §Symbols added lists a different name or signature for the same contract, use the hand-off's, rename in both `review.py` and the tests, and list the mapping under "Known gaps" in `HANDOFF-12.md` (a rename is not a Deviation). If a hand-off lacks the contract entirely, the fallback in the last column applies.

| this prompt says | contract | owner | fallback if absent |
|---|---|---|---|
| `fsrs.retrievability(elapsed_days, stability) -> float` | spec §3.2 `R(t,S)` | PKG-02 | none — STOP |
| `fsrs.interval(retention, stability) -> float` (days) | spec §3.2 `I(r,S)` | PKG-02 | none — STOP |
| `fsrs.next_state(d, s, r, rating, *, same_day=False) -> (d, s)` | spec §3.2 | PKG-02 | adapt call |
| `fsrs.rating_for(channel, correct, max_rung) -> int` | spec §3.2 rating map | PKG-02 | none — STOP |
| `fsrs.order_due(items, r_of) -> list` | order by `abs(r_of(x) − REVIEW_ORDER_THRESHOLD)` ascending | PKG-02 | adapt call |
| `fsrs.budget_select(items, budget_s, cost_of) -> list` | greedy prefix whose summed `cost_of` ≤ `budget_s` | PKG-02 | adapt call |
| `bkt.decayed_p(p_stored, elapsed_days, stability) -> float`, `bkt.band(p) -> "novice"\|"develop"\|"profic"` | spec §3.1 | PKG-01 | none — STOP |
| `apply_graph_update(user_id, graph_update, course_id=None)` accepting `graph_update["evidence"]` (a list of Evidence dicts — review passes `outcome.evidence` unchanged and never builds an `Evidence` itself) | spec §5 | PKG-03 (PKG-05 added `grader_backend`) | none — STOP |
| `apply_graph_update` honouring a per-call retention target for `fsrs.interval` (this prompt: `graph_update["retention"]: float`, default `FSRS_RETENTION_DEFAULT`) | needed so an exam-week review is scheduled at `FSRS_RETENTION_EXAM` | PKG-03 | add it as a post-hoc PKG-03 fix (Task 3 Step 3b) |
| `check_item_service.list_items(course_id, concept_key, *, format=None, difficulty=None) -> list[CheckItem]` (decrypted; `options: list[Option] \| None` with `Option{letter, text, wrong_key}` and `correct_option` decrypted from `options_json`/`correct_option`) | spec §2, A2, A22 | PKG-04 | adapt call |
| `services.graph_service._normalize_concept(concept_name) -> str` (a node's `concept_key`) | A2 | pre-series | none — STOP |
| `checks.select_item(items, *, format, difficulty, exclude_hashes=()) -> CheckItem \| None` (exact difficulty first, else nearest; format never substituted) | spec §2 | PKG-04 | adapt call |
| `checks.posttest_reserve_hash(items) -> str \| None` | A23 | PKG-04 | none — STOP (one definition of the reserve) |
| `agents.tools.check.grade_answer(item: CheckItem, answer: CheckAnswer, *, deps: SaplingDeps, node_id: str, max_rung: int = 0, same_session_recheck: bool = False) -> GradeOutcome`; `CheckAnswer(question_hash, answer_text, selected_option, reason, idk)` (flat); `GradeOutcome{correct: bool \| None, confidence, feedback_hint: str, matched_wrong_key, wrong_key, unavailable: bool, grader_backend, evidence: dict \| None}` — `evidence` is the one Evidence dict it appended to `deps.pending_evidence` (A22 weight, `grader_backend`); `unavailable=True` on outage, second opinion unavailable, or the `STUDENT_DAILY_GRADES` cap, with nothing appended for either outcome | spec A16, A22; HANDOFF-05 (routed through `services/decisions.py` by PKG-05b, grader cap by PKG-06b) | PKG-05 | none — STOP; this package must not call `agents/grader.py` or `services/decisions.py` directly (inv 19). If HANDOFF-05's signature has no `node_id` keyword, drop it from the call and the Task 3 stub (a rename, not a deviation) |
| `agents.tools.check.CHANNEL_FOR_FORMAT` (`free → free_response`, `mc_reason → mc_reasoned`, …) | spec §3.1 | PKG-05 | none — STOP (no second format → channel map) |
| `learning.loop_state_store.seen_hashes(user_id)`, `revealed_hashes(user_id)` → iterables of `question_hash` | A23 | PKG-07 | none — STOP (one definition of seen/revealed) |
| PKG-07's `/check/answer` deps construction (`SaplingDeps(user_id=…, course_id=…, supabase=None, request_id=…, session_id=…, feature=…, learning_loop=True)`), `_node_for_item(user_id, item)` (check item → the student's `node_id`, A2), `services.check_item_service.get_check_item(item_id)` (decrypted item by id) | A16, A2 | PKG-07 (PKG-04 for `get_check_item`) | build `SaplingDeps` and resolve the node in `routes/learn_loop.py` the way HANDOFF-07 describes; record it |
| `services.ai_budget.check(user_id, kind, band=None, *, session_tutor_requests=0, session_deep_requests=0, arm_session=False) -> BudgetDecision` (`.level`, `.pause_novice`); FastAPI dependency `enforce_rate_limit` and its inline form `enforce_rate_limit_for(user_id)` (429 `{"detail": "ai budget reached", "reset_at": …}`) | spec §3.5, §9, A20 | PKG-06b | none — STOP (if HANDOFF-06b has no inline form, add it as a `fix(learning-loop): PKG-06b — …` reopen: the dependency body moved into `enforce_rate_limit_for`) |
| `routes/learn_loop.py`: router, `_gate(user_id, request)` (or equivalent) raising 404 `{"detail": "learning loop not enabled"}` | spec §7 | PKG-07 | write `_gate` locally in the same style |
| `GET /api/learn/loop/status` → `{"active": true}` (gated) | frontend needs it | PKG-07 | add it in Task 5 |
| flashcard FSRS helper: `flashcard_fsrs_update(card_row, rating, *, now, retention=FSRS_RETENTION_DEFAULT) -> dict` (legacy 1/2/3 → FSRS rating map, returns the columns `rate_card` writes: `fsrs_d, fsrs_s, due_at, reps, lapses, times_reviewed, last_rating, last_reviewed_at`) | the loop branch of `rate_card` | PKG-11 | if the helper lives inside `routes/flashcards.py` or lacks `retention`, move/extend it in a post-hoc PKG-11 fix commit (Task 4 Step 3b); `learning/review.py` never imports `routes.*` |

### Behaviour

1. **Queue.** `learning.review.due_queue(user_id, course_id, now, *, loop_state=None, pause_novice=False) -> list[ReviewItem]`:
   - Flashcards: one `table("flashcards").select("id,topic,offering_id,fsrs_d,fsrs_s,due_at,reps,lapses,last_rating", filters={"user_id": f"eq.{user_id}"})`; a card is due when `due_at` is `None` (never scheduled: it enters the pool with `stability = FSRS_S0_GOOD`, elapsed 0) or `due_at <= now`. With a `course_id`, keep cards whose `offering_id` is in `user_offering_ids_for_course(user_id, course_id)` **or** `None` (the `get_flashcards` :333–336 rule: term-less cards are never stranded). `course_id=None` → every due card.
   - Concepts: one `table("learner_state").select("node_id,p_known,streak_unassisted,fsrs_d,fsrs_s,fsrs_last_review_at,fsrs_due_at", filters={"user_id": f"eq.{user_id}", "fsrs_due_at": f"lte.{now.isoformat()}"})`; a `NULL fsrs_due_at` concept is not due (it has never been scheduled; loop sessions schedule it). Then one `table("graph_nodes").select("id,course_id,concept_name", filters={"user_id": …, "id": f"in.({ids})"})`; with a `course_id`, keep nodes on that abstract course.
   - Each concept maps to one check item (A2, A23): `band = bkt.band(bkt.decayed_p(p_known, elapsed_days, fsrs_s or FSRS_S0_GOOD))`.
     - **Tutor hard level (A20):** when `pause_novice` is true (the route passes `ai_budget.check(user_id, "tutor", "novice").pause_novice`) and `band == "novice"`, the concept is skipped before any item read and counted `paused` (INFO log; no event). Develop/profic concepts and every flashcard are served as usual — the review queue keeps working at the hard level (spec §3.5).
     - Otherwise `pool = list_items(<node's course_id>, _normalize_concept(concept_name))` — ONE read per concept, every format and difficulty, decrypted — and `reserve = checks.posttest_reserve_hash(pool)`.
     - Exclusion sets (A23): `strict = served_today ∪ seen ∪ revealed ∪ {reserve}` and `fallback = revealed ∪ {reserve}`, where `seen = seen_hashes(user_id)` and `revealed = revealed_hashes(user_id)` are read once per queue build (only when at least one concept is due) and `served_today = loop_state["review"]["served_hashes"]` (rule 3). A `None` reserve adds nothing.
     - Selection: for `exclude` in (`strict`, `fallback`), for `fmt` in (`REVIEW_FORMAT_BY_BAND[band]`, then the other value of `REVIEW_FORMAT_BY_BAND`): `item = checks.select_item(pool, format=fmt, difficulty=REVIEW_DIFFICULTY_BY_BAND[band], exclude_hashes=exclude)` (`select_item` falls back to the nearest difficulty itself); the first hit wins. The `fallback` pass runs only when the `strict` pass found nothing in any format. Still nothing → the concept is skipped and counted `unservable` (INFO log; no event). Review never serves the post-test reserve or a revealed item, and never generates an item on the request path.
   - `r = fsrs.retrievability(elapsed_days, stability)` with `elapsed_days` measured from `fsrs_last_review_at` (concepts) / `last_reviewed_at` (flashcards; `None` → 0).
   - Items whose successive-relearning target is already met in this review session (`loop_state["sr"][key]["correct"] >= target`) are dropped.
   - Merge both kinds, `fsrs.order_due(items, r_of=lambda i: i.r)`, then `fsrs.budget_select(ordered, remaining_budget_s, cost_of=lambda i: i.cost_s)` where `remaining_budget_s = REVIEW_DAILY_BUDGET_MIN * 60 − loop_state["review"]["spent_s"]` and `cost_s` is `REVIEW_SECONDS_PER_CHECK` for checks, `REVIEW_SECONDS_PER_FLASHCARD` for flashcards.
2. **Retention target.** `retention_target(n_scheduled_concepts, exam_within_days) -> float`: `exam_within_days is not None and exam_within_days <= FSRS_EXAM_WINDOW_DAYS` → `FSRS_RETENTION_EXAM`; else `n_scheduled_concepts > FSRS_LARGE_SET_CONCEPTS` → `FSRS_RETENTION_LARGE_SET`; else `FSRS_RETENTION_DEFAULT`. Exam beats large-set †. `n_scheduled_concepts` = count of the user's `learner_state` rows for the course with a non-null `fsrs_due_at`; `exam_within_days = services.exam_proximity.days_until_next_exam(user_id, course_id)` (resolvable today: the gradebook's `assignments` rows, strict exam match; `None` when there is no course or no upcoming exam).
3. **Successive relearning (spec §3.2 `SR_INITIAL_CRITERION`, `SR_RELEARN_SESSIONS`).** No new column. Two layers:
   - Within a review session, counters live in `sessions.loop_state["sr"][key] = {"correct": int, "target": int, "served": int}` with `key = node_id` for concepts and `key = "fc:" + card_id` for flashcards; `loop_state["review"] = {"spent_s": int, "retention": float, "served_hashes": [question_hash, …]}` (`served_hashes` = the check items served in this review session; hashes only, no free text). A correct answer increments `correct`; a wrong answer resets `correct` to 0 (the item stays due and re-enters the queue next poll); `served` increments on every `serve`; `spent_s += cost_s` on every graded answer.
   - Across sessions the stage is **derived**: concepts from `learner_state.streak_unassisted` (`sr_stage_for_concept`): `streak < SR_INITIAL_CRITERION` → `acquire`, target `SR_INITIAL_CRITERION`; `SR_INITIAL_CRITERION <= streak < SR_INITIAL_CRITERION + SR_RELEARN_SESSIONS` → `relearn`, target 1; else `done`, target 1. This is exact because a relearn/done session serves the item at most once after its target is met (rule 1) and PKG-03 resets `streak_unassisted` on any incorrect evidence, so `streak − SR_INITIAL_CRITERION` counts completed relearn sessions. Flashcards (`sr_stage_for_flashcard(reps, last_rating)`): `reps < SR_INITIAL_CRITERION or last_rating == 1` → `acquire`; `SR_INITIAL_CRITERION <= reps < SR_INITIAL_CRITERION + SR_RELEARN_SESSIONS` → `relearn`; else `done`; targets as for concepts. † A stored `sr_stage`/`sr_streak` on `learner_state` and `flashcards` would be cleaner (the flashcard derivation cannot see a lapse that happened mid-relearn because `reps` never decreases); record it as an Open question — PKG-14 may add the column.
4. **Review session row.** `review_session_id(user_id, course_id, now) = str(uuid.uuid5(uuid.NAMESPACE_URL, f"sapling:review:{user_id}:{course_id or '-'}:{now.date().isoformat()}"))` — one per user, course, UTC day. `_load_or_create_review_session` reads `table("sessions").select("id,loop_state", filters={"id": f"eq.{sid}"})`; missing → insert `{"id": sid, "user_id": user_id, "offering_id": resolve_offering(course_id) or omitted, "mode": "review", "topic": "Daily review", "name": "Daily review"}` mirroring `routes/learn.py:424–434`, and emit `session.started` the same way that site does (`content=` the topic, never payload). `loop_state` writes go through `table("sessions").update({"loop_state": …}, filters={"id": f"eq.{sid}"})`. `mode='review'` requires the migration below.
5. **Serve.** `serve(item) -> dict` returns the client payload: `{kind, id, node_id, concept_name, format, difficulty, cost_s, sr: {stage, correct, target}, prompt}` for checks — plus, for `mc_reason` only, `options: [{"letter", "text"}]` taken in stored order from the item's decrypted `options_json` (`check_item.options`; A22: never rebuilt from the reference, no `wrong_key`, correctness never marked) — and `{kind, id, topic, cost_s, sr, front, back}` for flashcards (`back` is needed for self-rating; both decrypted via `decrypt_if_present`). A check payload **never** carries `reference_answer`, `rubric_json`/`rubric`, `common_wrong_json`/`common_wrong`, `correct_option`, `canonical_answer`, or any option's `wrong_key`. It increments `loop_state["sr"][key]["served"]` and, for a check, appends the item's `question_hash` to `loop_state["review"]["served_hashes"]` (once).
6. **Grade.** `async grade_review(user_id, item, *, answer, rating, session_id, loop_state, now, request_id, retention, check_item=None, card_row=None, selected_option=None, reason=None, deps=None) -> ReviewOutcome`:
   - `kind == "check"`: build PKG-05's `CheckAnswer(question_hash=check_item.question_hash, answer_text=answer or "", selected_option=selected_option, reason=reason)` and call `outcome = await grade_answer(check_item, check_answer, deps=deps, node_id=item.node_id)` (A16; `deps` is the route-built `SaplingDeps` with `learning_loop=True` and `session_id` = the review session; `max_rung=0`, `same_session_recheck=False` — a review is unassisted). `grade_answer` runs the A22 pre-checks (an `mc_reason` option is compared in code against the decrypted `correct_option` and the reason check runs for BOTH outcomes; a numeric answer never gets a code-issued "correct") and reaches the grader through PKG-05b's decision seam, whose run site checks PKG-06b's grader cap first.
     - `outcome.refused` (spec §13 A33; a refused outcome is also `unavailable`) → the `unavailable` path below — nothing recorded, the item stays due, so a refusal is never a skip — but the response also carries `refused: true` so the client asks for the answer in the student's own words instead of reporting an outage.
     - `outcome.unavailable` (outage, second opinion unavailable, or the `STUDENT_DAILY_GRADES` cap) → `ReviewOutcome(unavailable=True)`: no evidence for either outcome (invariant 28), no SR change, no `spent_s` change, no `loop_state` write, no `review.graded`; the item stays due. A correct and a wrong attempt take this path identically.
     - Otherwise persist `outcome.evidence` **unchanged** (it carries the A22 weight and `grader_backend`; review never builds an `Evidence` or recomputes a weight) with ONE call `apply_graph_update(user_id, {"evidence": [outcome.evidence], "retention": retention}, course_id=item.course_id)`. `deps.pending_evidence` is discarded, never flushed — `flush_pending` cannot carry the retention target, and this call is the only write. `hint` = `outcome.feedback_hint`, and when wrong, `outcome.feedback_hint + "\n\nAnswer: " + check_item.reference_answer` (spec §3.3: corrective feedback WITH the answer, immediately; the item is now revealed through its `correct=false` evidence row, A23). `rating = fsrs.rating_for(outcome.evidence["channel"], outcome.correct, 0)` (for the response and the event only; `apply_graph_update` computes the FSRS update itself). `next_due_at` is read back from `learner_state` after the apply (one select) — never computed here. `outcome.wrong_key` / `matched_wrong_key` belong to PKG-10's hook inside `grade_answer`; review ignores them.
   - `kind == "flashcard"`: `cols = flashcard_fsrs_update(card_row, rating, now=now, retention=retention)`; `table("flashcards").update(cols, filters={"id": f"eq.{card_id}", "user_id": f"eq.{user_id}"})`; `correct = rating >= 2` (legacy 1 = forgot); `next_due_at = cols["due_at"]`; FSRS rating = the map PKG-11 owns.
   - Both: update `loop_state["sr"][key]` per rule 3 and `loop_state["review"]["spent_s"]`, persist `loop_state`, emit `review.graded`.
7. **Routes** (`routes/learn_loop.py`, mounted by PKG-07 under `/api/learn/loop`), all `require_self` + gate → 404 `{"detail": "learning loop not enabled"}`. No body model or query carries `model_pref` (invariant 22). No route gates on the tutor budget level — review keeps working at the hard level (spec §3.5); the only budget reads are `pause_novice` and the rate limit:
   - `GET /review/next?user_id=&course_id=` → `{"item": serve(first) | null, "remaining_budget_s": int, "session_id": str, "retention_target": float, "due_total": int}`; builds the queue with `pause_novice = _pause_novice(user_id)` (= `ai_budget.check(user_id, "tutor", "novice").pause_novice`); emits `review.served` once per kind present in the built queue. Runs no model → no rate limit.
   - `POST /review/answer` body `ReviewAnswerBody {user_id: str, session_id: str, course_id: str | None, kind: Literal["flashcard","check"], item_id: str, answer: str | None = None, selected_option: str | None = None, reason: str | None = None, rating: int | None = None}` — `check` with neither `answer` nor `selected_option`, or `flashcard` without `rating in (1, 2, 3)` → 422; after the item loads, an `mc_reason` item without `selected_option` or a `free` item without `answer` → 422. Rate limit for `kind == "check"` ONLY — the one body that can run a model (the grader): the handler's first statement after validation is `if body.kind == "check": ai_budget.enforce_rate_limit_for(body.user_id)` (PKG-06b's inline form; spec §9) → over `LEARN_RATE_LIMIT_PER_MIN` → 429 `{"detail": "ai budget reached", "reset_at": …}`, nothing graded. A `flashcard` rating runs no model and is NEVER rate-limited (spec §3.5: self-rated flashcards keep working at every level); the route carries no `enforce_rate_limit` dependency. Returns `{"correct": bool | null, "hint": str | null, "next_due_at": iso | null, "rating": int | null, "remaining_budget_s": int, "sr": {...}, "unavailable": bool}`.
   - `GET /review/summary?user_id=&course_id=` → `{"due": {"flashcard": n, "check": n}, "unservable": n, "paused": n, "budget_min": REVIEW_DAILY_BUDGET_MIN, "remaining_budget_s": int, "retention_target": float}` (`paused` = novice-band concepts held back at the tutor hard level; rule 1). Runs no model → no rate limit.
   - The route layer re-loads the item by id on `/review/answer` (`check_item_service` for checks — decrypted — or the `flashcards` row); the client never round-trips reference text. A check item's `node_id` is the student's `graph_nodes.id` for `(item.course_id, item.concept_key)` (A2), resolved server-side the way PKG-07's `/check/answer` resolves it — never taken from the client; none → 404 `"review item not found"`. The `SaplingDeps` for `grade_answer` come from PKG-07's deps builder with the review session's id.
8. **Frontend.** `api.ts` gains `getLoopStatus`, `getReviewNext`, `answerReview`, `getReviewSummary`. `Study.tsx` `FlashcardsMode` calls `getLoopStatus(userId)` once; a 404 or any error → `loopActive=false` and the existing UI renders byte-identically. `loopActive=true` → a `<DueQueue>` panel (new file `frontend/src/components/learn/DueQueue.tsx`) renders above the card filter bar, driven by `/review/next` → answer → next. It shows the remaining budget, the prompt (or front/back flip for flashcards), a free-text answer box or the served `mc_reason` options (letter + text, one radio each) + one-sentence reason box (submitted as `selected_option` + `reason`), the corrective `hint`, and "All caught up" when `item` is null. DueQueue is the launch Study surface (spec §11.3); PKG-13 adds the budget banner and launch polish.
9. **Flag inert.** With `LEARNING_LOOP_ENABLED` unset (build phase, spec §7): the three routes 404 before any read; `learning/review.py` is imported only by `routes/learn_loop.py`; `Study.tsx` renders the legacy `FlashcardsMode` (status 404 → `loopActive=false`). `tests/test_learning_review.py::test_routes_404_when_gate_false` proves the routes; the frontend path is covered by the unchanged `frontend/e2e/study-*.spec.ts` journeys in the E2E cycle.

### Schema (exact)

Spec §4's PKG-12 block (Amendment A9), required by Behaviour rule 4 (`sessions.mode` is CHECK-constrained by `0025_study_integrity.sql:74`). The basename is the spec's: `<ts>_learning_sessions_mode_review.sql`.

```sql
-- <ts>_learning_sessions_mode_review.sql  (spec §4, Amendment A9)
-- Learning loop series PKG-12: daily review sessions are `sessions` rows so
-- successive-relearning counters can live in sessions.loop_state (PKG-06)
-- without a new column. 0025 constrained mode to socratic/expository/
-- teachback; widen it. The inline CHECK's default name is sessions_mode_check.
ALTER TABLE sessions DROP CONSTRAINT IF EXISTS sessions_mode_check;
ALTER TABLE sessions ADD CONSTRAINT sessions_mode_check
    CHECK (mode IN ('socratic','expository','teachback','review'));
```

The E2E lane replays migrations, and the `review.spec`-less Chapter 1 run still exercises the insert through Task 6's manual check; if the live constraint carries a different name the DROP is a no-op and the insert of `mode='review'` fails there — that is the signal to write a follow-up migration that drops it by its real name (query `pg_constraint` on the local stack), never to edit this one.

### Named constants

Existing (spec §3.2, already in `learning/params.py` from PKG-01/02 — cite, do not redefine): `FSRS_RETENTION_DEFAULT` 0.90, `FSRS_RETENTION_LARGE_SET` 0.85, `FSRS_LARGE_SET_CONCEPTS` 150, `FSRS_RETENTION_EXAM` 0.95, `FSRS_EXAM_WINDOW_DAYS` 14, `FSRS_S0_GOOD` = `FSRS_W[2]`, `REVIEW_ORDER_THRESHOLD` 0.33, `REVIEW_DAILY_BUDGET_MIN` 12, `REVIEW_SECONDS_PER_CHECK` 45, `SR_INITIAL_CRITERION` 3, `SR_RELEARN_SESSIONS` 3; spec §3.4 `CHECK_ITEM_DIFFICULTIES` 1–3 (the Task 2 consistency test). The evidence weight is not a review constant: it arrives on `outcome.evidence` from `grade_answer` (PKG-03's `evidence_weight`, A22) and is never recomputed here, so `WEIGHT_LOW_CONFIDENCE` / `GRADER_LOW_CONFIDENCE` are not read by this package. The format → channel map is PKG-05's `CHANNEL_FOR_FORMAT`; this package defines no second one.

Budget constants (spec §3.5, `config.py`, PKG-06b — consumed only through PKG-06b's functions, never read directly here): `STUDENT_DAILY_GRADES` 300 † (the grader cap inside `grade()`; reaching it makes a review grade `unavailable`), `LEARN_RATE_LIMIT_PER_MIN` 20 † (through `enforce_rate_limit` on `/review/answer`), and the hard-level triggers behind `BudgetDecision.pause_novice`.

New in this package (append to `learning/params.py` under a `# PKG-12 review surfaces` comment; every † goes in the hand-off's Constants chosen and the ledger's Deviations):

| Name | Value | Meaning / source |
|---|---|---|
| `REVIEW_SECONDS_PER_FLASHCARD` | 15 † | budget cost of one self-rated card; the spec prices only checks (`REVIEW_SECONDS_PER_CHECK`) and a flip-and-rate is a fraction of a graded free response — no validated cut-point |
| `REVIEW_DIFFICULTY_BY_BAND` | `{"novice": 1, "develop": 2, "profic": 3}` † | which `check_items.difficulty` a review draws for a concept, by spec §3.1 band; the spec gives `CHECK_ITEM_DIFFICULTIES` 1–3 but no band mapping |
| `REVIEW_FORMAT_BY_BAND` | `{"novice": "mc_reason", "develop": "mc_reason", "profic": "free"}` † | both are strong channels (spec §3.1 `mc_reasoned`, `free_response`); free response reserved for proficient students per the research §"Check" (free response for credit, MC for speed); the other value is the fallback format in rule 1 |

### Invariants asserted by this package (spec §8 numbering + series extension)

- (19, new) `learning/review.py` grades only through `grade_answer` (PKG-05, A16): source scan shows `from agents.tools.check import` and `grade_answer` present, and neither `Agent(`, nor `agents.grader`, nor `services.decisions` anywhere in the file (one grader, one prompt stack, and the A22 pre-checks are never bypassed).
- (1, re-asserted by PKG-03's existing test) `review.py` never calls `.insert(`/`.update(`/`.upsert(` on `graph_nodes`, `graph_edges`, `node_mastery_events`, `learner_state` — its only graph write is `apply_graph_update`. Run `-k inv_01` after Task 3; it must stay green.
- (26, extended) the `/review/answer` handler joins the explicit-submission allow-list of PKG-07's `test_inv_26_evidence_only_from_explicit_submission` (Task 5). Its one write happens inside `review.grade_review`, so Task 5 also adds `test_grade_review_called_only_from_review_answer` (AST: every call of `review.grade_review` in `routes/learn_loop.py` sits inside the `/review/answer` handler).
- (28, mirrored) an `unavailable` grade — outage or the `STUDENT_DAILY_GRADES` cap — writes no evidence for either outcome and changes no review state (`test_grader_unavailable_writes_nothing`, parametrized over a right and a wrong option). The behavioural invariant itself stays PKG-05/06b's.
- (22) still holds: no PKG-12 body model or route reads `model_pref`. (23) is untouched: PKG-12 runs no agent directly; the grader's run site checks the grader cap (PKG-06b).
- (5) `review.served` and `review.graded` literals are in `EVENT_TAXONOMY` (PKG-06's `inv_05` scans for `"review."` literals; it must stay green after Task 2).
- (7) `review.py` mentions `table(` and has `from db.connection import table`.
- (8) the new migration matches `^\d{14}_learning_[a-z_]+\.sql$` and is never edited.

### Error semantics

- Grader unavailable (ADR 0024 outage, second opinion unavailable, or the `STUDENT_DAILY_GRADES` cap — `GradeOutcome.unavailable=True`): the answer route returns 200 with `unavailable: true`, `correct: null`; nothing is written for either outcome (invariant 28); the item stays due. Never a second prompt stack, never a retry loop here.
- Rate limit (`ai_budget.enforce_rate_limit_for` inside `/review/answer`, for `kind="check"` only): 429 `{"detail": "ai budget reached", "reset_at": …}` before anything is graded or written. A flashcard rating is never rate-limited; a rate-limit-only hard level never sets `pause_novice` (PKG-06b), so review items are not dropped by a burst.
- Tutor hard level: `/review/next`, `/review/summary` and flashcard answers keep working; novice-band concepts are skipped and counted `paused`; never a 429 from the tutor budget on a review route.
- `apply_graph_update` raising → 500 from the route (a review that could not be recorded is not silently a success); the `loop_state` update is skipped so the item re-enters the queue.
- Empty check-item pool for a due concept, or nothing left after the A23 exclusions and fallback → skip + `unservable` count; never a 500, never an LLM call to generate one on the request path.
- Any exception in `days_until_next_exam` is already swallowed there (`None`).
- Gate false → 404 before any table read (assert with a `table` spy, as PKG-00 does).

### Events added

Both to `EVENT_TAXONOMY` and the pin test, category `usage`, payload keys exactly per spec §6:

- `review.served` — `{kind: "flashcard"|"check", n: int, budget_min: int, retention_target: float}`; one per kind present in a built queue.
- `review.graded` — `{kind, correct: bool, rating: int}`; one per graded answer; not emitted on `unavailable`.

## Non-goals

- No new agent, no `AgentTask`, no prompt change, no function-mode handler, no eval dataset (the grader is PKG-05's; reviews reuse it unchanged).
- No interleaving policy, no sibling mixing, no isomorph re-ask scheduling (PKG-07/08 own in-session re-asks; the review pool simply serves what is due).
- No change to `routes/flashcards.py::rate_card` or `get_flashcards` beyond what a PKG-11 post-hoc fix strictly needs (Task 4 Step 3b), no change to `apply_graph_update` beyond the retention kwarg (Task 3 Step 3b).
- No full loop UI, no `LoopLearn.tsx`, no E2E journey, no budget-pause banner or launch polish on `DueQueue` (PKG-13, spec §11.3). No `sr_stage` column (PKG-14 decides).
- No `ai_budget.check` gate on the review routes: review and self-rated flashcards keep working at the tutor hard level (spec §3.5); only novice-band concept checks pause, flashcards never do. No change to `grade_answer`, `grade()` or the decision seam.
- No per-user retention optimisation, no CMRR simulation.

## Tasks

### Task 1: Invariant 19 — reviews grade through `grade_answer` only

**Files:**
- Modify: `backend/tests/test_learning_loop_invariants.py`

**Interfaces:**
- Consumes: filesystem under `backend/learning/`.
- Produces: `test_inv_19_review_grades_through_grader_only`.

- [ ] **Step 1: Append the test** (after the highest-numbered `test_inv_NN` currently in the module; do not renumber anything)

```python
def test_inv_19_review_grades_through_grader_only():
    """PKG-12: a review is graded by grade_answer, the single grading route
    helper (spec §13 A16) shared with the check route, the probe and the
    post-test. review.py must import it from agents/tools/check.py and never
    build an Agent, reach agents/grader.py, or call the decision seam itself
    (one grader, one prompt stack, the A22 pre-checks never bypassed)."""
    path = LEARNING / "review.py"
    text = path.read_text()
    assert "from agents.tools.check import" in text, "review.py must import the PKG-05 grading helper"
    assert "grade_answer" in text, "review.py must grade through grade_answer"
    assert "Agent(" not in text, "review.py constructs an Agent"
    assert "agents.grader" not in text, "review.py bypasses grade_answer and reaches the grader agent"
    assert "services.decisions" not in text, "review.py bypasses grade_answer and reaches the decision seam"
    assert not re.search(r"table\(\"(graph_nodes|graph_edges|node_mastery_events|learner_state)\"\)\.(insert|update|upsert)\(", text), \
        "review.py writes a graph table directly (inv 1)"
```

- [ ] **Step 2: Run to see it fail**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k inv_19`
Expected: FAIL — `AssertionError: review.py must import the PKG-05 grading helper` (the stub has no imports).

- [ ] **Step 3: Commit** (red is expected; Task 3 turns it green)

```
git add backend/tests/test_learning_loop_invariants.py
git commit -m "test(learning-loop): PKG-12 — inv 19 review grades through grade_answer only

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 2: Events, constants, migration

**Files:**
- Modify: `backend/services/events_service.py` (`EVENT_TAXONOMY`), `backend/tests/test_event_capture_seams.py` (the pin), `backend/learning/params.py`
- Create: `backend/db/migrations/<UTC>_learning_sessions_mode_review.sql`
- Test: `backend/tests/test_learning_review.py` (first block)

**Interfaces:**
- Produces: `review.served`, `review.graded` in the taxonomy; `params.REVIEW_SECONDS_PER_FLASHCARD`, `params.REVIEW_DIFFICULTY_BY_BAND`, `params.REVIEW_FORMAT_BY_BAND`; the migration.

- [ ] **Step 1: Write the failing tests** — create `backend/tests/test_learning_review.py` with this header and first block (later tasks append to the same file):

```python
"""PKG-12 review surfaces: queue merge/order/budget, one grader path,
FSRS on flashcards, retention targets, successive relearning, events, gate.
Hermetic: every table() is a mock, the grader helper is patched."""
from __future__ import annotations

import asyncio
import pathlib
import re
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from learning import params

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
USER = "user_andres"
COURSE = "course-1"
MIG_DIR = pathlib.Path(__file__).resolve().parents[1] / "db" / "migrations"


def _tables(data: dict):
    """One MagicMock per table name so a test can assert on a specific table's
    update/insert calls (mirrors tests/test_graph_service.py::_cached_mock_table)."""
    handles: dict = {}

    def factory(name):
        if name not in handles:
            m = MagicMock(name=name)
            m.select.return_value = list(data.get(name, []))
            m.insert.return_value = []
            m.update.return_value = []
            m.upsert.return_value = []
            handles[name] = m
        return handles[name]

    return factory, handles


# ── Task 2: taxonomy, constants, migration ────────────────────────────────────


def test_review_events_are_in_the_taxonomy():
    from services import events_service

    assert {"review.served", "review.graded"} <= events_service.EVENT_TAXONOMY


def test_review_constants_exist_and_are_consistent():
    assert params.REVIEW_SECONDS_PER_FLASHCARD < params.REVIEW_SECONDS_PER_CHECK
    assert set(params.REVIEW_DIFFICULTY_BY_BAND) == {"novice", "develop", "profic"}
    assert set(params.REVIEW_DIFFICULTY_BY_BAND.values()) <= set(params.CHECK_ITEM_DIFFICULTIES)
    assert set(params.REVIEW_FORMAT_BY_BAND) == {"novice", "develop", "profic"}
    assert set(params.REVIEW_FORMAT_BY_BAND.values()) == {"free", "mc_reason"}  # rule 1 falls back to the other one


def test_review_session_mode_migration():
    hits = sorted(MIG_DIR.glob("*_learning_sessions_mode_review.sql"))
    assert len(hits) == 1, hits
    sql = hits[0].read_text()
    assert re.fullmatch(r"\d{14}_learning_sessions_mode_review\.sql", hits[0].name)
    assert "DROP CONSTRAINT IF EXISTS sessions_mode_check" in sql
    assert re.search(r"CHECK \(mode IN \('socratic','expository','teachback','review'\)\)", sql)
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_review.py -v`
Expected: 3 FAIL — `AssertionError` on the taxonomy subset; `AttributeError: module 'learning.params' has no attribute 'REVIEW_SECONDS_PER_FLASHCARD'`; `assert len(hits) == 1` with `[]`.

- [ ] **Step 3: Implement**

`services/events_service.py`: add to `EVENT_TAXONOMY` after PKG-09's `learn.session_closed` entry (or after the last `zpd.*`/`learn.*` entry present):
```python
    # Learning loop PKG-12: the daily review queue. `served` once per kind in
    # a built queue (n = how many), `graded` per answer. Reviews are evidence,
    # so `graded` is the countable twin of the node_mastery_events row.
    "review.served",
    "review.graded",
```
`tests/test_event_capture_seams.py::test_event_taxonomy_is_pinned`: add the same two strings with a `# PKG-12` comment.

`learning/params.py`, appended:
```python
# ── PKG-12 review surfaces (spec §3.2; † = engineering choice, see HANDOFF-12) ──
REVIEW_SECONDS_PER_FLASHCARD = 15  # † budget cost of one self-rated card
REVIEW_DIFFICULTY_BY_BAND = {"novice": 1, "develop": 2, "profic": 3}  # †
REVIEW_FORMAT_BY_BAND = {"novice": "mc_reason", "develop": "mc_reason", "profic": "free"}  # †
```

Migration: prefix from `date -u +%Y%m%d%H%M%S`; content is §Spec/Schema verbatim including the comment.

- [ ] **Step 4: Run tests, lint**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_review.py tests/test_event_capture_seams.py::test_event_taxonomy_is_pinned tests/test_learning_loop_invariants.py -q -k "(review and not inv_19) or pinned or inv_05 or inv_08" && venv/bin/ruff check .`
Expected: all passed (inv_19 still fails — it is excluded by `-k`); `All checks passed!`

- [ ] **Step 5: Commit**

```
git add backend/services/events_service.py backend/tests/test_event_capture_seams.py backend/learning/params.py backend/db/migrations/*_learning_sessions_mode_review.sql backend/tests/test_learning_review.py
git commit -m "feat(learning-loop): PKG-12 — review events, review constants, review session mode

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 3: `learning/review.py` — queue, retention target, SR stage, serve, check grading

**Files:**
- Modify: `backend/learning/review.py` (replace the stub)
- Possibly modify (Step 3b only): `backend/services/graph_service.py` (retention kwarg), `docs/superpowers/plans/learning-loop/HANDOFF-03.md` (Post-hoc changes)
- Test: `backend/tests/test_learning_review.py` (second block)

**Interfaces:**
- Consumes: the §"Names from earlier hand-offs" table.
- Produces: `ReviewItem`, `ReviewOutcome`, `retention_target`, `sr_stage_for_concept`, `sr_stage_for_flashcard`, `review_session_id`, `load_or_create_review_session`, `due_queue`, `serve`, `grade_review`, `summary`. Every external call is a module-level name (`table`, `list_items`, `select_item`, `posttest_reserve_hash`, `seen_hashes`, `revealed_hashes`, `_normalize_concept`, `grade_answer`, `CheckAnswer`, `apply_graph_update`, `days_until_next_exam`, `user_offering_ids_for_course`, `resolve_offering`, `flashcard_fsrs_update`, `log_event`, `decayed_p`, `band`) so tests patch `learning.review.<name>`.

- [ ] **Step 1: Append the failing tests**

```python
# ── Task 3: retention target, SR stage, queue, check grading ─────────────────


def _item(kind, r, **kw):
    from learning.review import ReviewItem

    base = dict(
        kind=kind, id=kw.pop("id", f"{kind}-{r}"), node_id=kw.pop("node_id", None),
        course_id=COURSE, question_hash=kw.pop("question_hash", None), due_at=NOW,
        r=r, stability=params.FSRS_S0_GOOD, format=kw.pop("format", None),
        difficulty=kw.pop("difficulty", None),
        cost_s=params.REVIEW_SECONDS_PER_CHECK if kind == "check" else params.REVIEW_SECONDS_PER_FLASHCARD,
        sr_stage="acquire", sr_target=params.SR_INITIAL_CRITERION,
    )
    base.update(kw)
    return ReviewItem(**base)


@pytest.mark.parametrize("n,exam,expected", [
    (0, None, "FSRS_RETENTION_DEFAULT"),
    (params.FSRS_LARGE_SET_CONCEPTS, None, "FSRS_RETENTION_DEFAULT"),
    (params.FSRS_LARGE_SET_CONCEPTS + 1, None, "FSRS_RETENTION_LARGE_SET"),
    (0, params.FSRS_EXAM_WINDOW_DAYS, "FSRS_RETENTION_EXAM"),
    (0, params.FSRS_EXAM_WINDOW_DAYS + 1, "FSRS_RETENTION_DEFAULT"),
    (0, 0, "FSRS_RETENTION_EXAM"),
    (params.FSRS_LARGE_SET_CONCEPTS + 1, 1, "FSRS_RETENTION_EXAM"),  # exam beats large set †
])
def test_retention_target(n, exam, expected):
    from learning.review import retention_target

    assert retention_target(n, exam) == getattr(params, expected)


@pytest.mark.parametrize("streak,stage,target", [
    (0, "acquire", params.SR_INITIAL_CRITERION),
    (params.SR_INITIAL_CRITERION - 1, "acquire", params.SR_INITIAL_CRITERION),
    (params.SR_INITIAL_CRITERION, "relearn", 1),
    (params.SR_INITIAL_CRITERION + params.SR_RELEARN_SESSIONS - 1, "relearn", 1),
    (params.SR_INITIAL_CRITERION + params.SR_RELEARN_SESSIONS, "done", 1),
])
def test_sr_stage_for_concept(streak, stage, target):
    from learning.review import sr_stage_for_concept

    assert sr_stage_for_concept(streak) == (stage, target)


@pytest.mark.parametrize("reps,last_rating,stage", [
    (0, None, "acquire"),
    (params.SR_INITIAL_CRITERION, 3, "relearn"),
    (params.SR_INITIAL_CRITERION, 1, "acquire"),  # a lapse restarts acquisition
    (params.SR_INITIAL_CRITERION + params.SR_RELEARN_SESSIONS, 2, "done"),
])
def test_sr_stage_for_flashcard(reps, last_rating, stage):
    from learning.review import sr_stage_for_flashcard

    assert sr_stage_for_flashcard(reps, last_rating)[0] == stage


def test_review_session_id_is_one_per_user_course_day():
    from learning.review import review_session_id

    a = review_session_id(USER, COURSE, NOW)
    assert a == review_session_id(USER, COURSE, NOW + timedelta(hours=11))
    assert a != review_session_id(USER, COURSE, NOW + timedelta(days=1))
    assert a != review_session_id(USER, None, NOW)
    assert a != review_session_id("someone-else", COURSE, NOW)


@pytest.fixture(autouse=True)
def _no_review_history(monkeypatch):
    """A23 readers (PKG-07) and the post-test reserve (PKG-04) default to
    "nothing excluded"; the exclusion tests override them."""
    from learning import review

    monkeypatch.setattr(review, "seen_hashes", lambda user_id: set(), raising=False)
    monkeypatch.setattr(review, "revealed_hashes", lambda user_id: set(), raising=False)
    monkeypatch.setattr(review, "posttest_reserve_hash", lambda items: None, raising=False)


def _option(letter, text, wrong_key):
    opt = MagicMock()
    opt.letter, opt.text, opt.wrong_key = letter, text, wrong_key
    return opt


def _check_item(node_id, qh, fmt="free", difficulty=2):
    """A decrypted CheckItem stand-in (A2: keyed on course_id/concept_key; the
    student's node is resolved by the caller, never stored on the item)."""
    item = MagicMock()
    item.id = f"ci-{qh}"
    item.course_id = COURSE
    item.concept_key = f"key-{node_id}"
    item.format = fmt
    item.difficulty = difficulty
    item.question_hash = qh
    item.created_at = None
    item.prompt = f"Explain {node_id}"
    item.reference_answer = f"REF-{node_id}"
    item.rubric = [{"id": "r1", "text": "x"}, {"id": "r2", "text": "y"}]
    item.common_wrong = [{"key": "w1", "text": "z"}]
    item.options, item.correct_option = None, None
    if fmt == "mc_reason":  # A22: stored options, one correct, distractors keyed
        item.options = [_option("A", f"OPT-A-{node_id}", None), _option("B", f"OPT-B-{node_id}", "w1")]
        item.correct_option = "A"
    return item


def _due_row(node_id, p_known, past):
    return {"node_id": node_id, "p_known": p_known, "streak_unassisted": 0, "fsrs_d": 5.0,
            "fsrs_s": 1.0, "fsrs_last_review_at": past, "fsrs_due_at": past}


def test_due_queue_merges_orders_and_drops_not_due(monkeypatch):
    from learning import review
    from services.graph_service import _normalize_concept

    past, future = (NOW - timedelta(days=3)).isoformat(), (NOW + timedelta(days=3)).isoformat()
    factory, handles = _tables({
        "flashcards": [
            {"id": "f-due", "topic": "T", "offering_id": None, "fsrs_d": 5.0, "fsrs_s": 1.0,
             "due_at": past, "reps": 0, "lapses": 0, "last_rating": None, "last_reviewed_at": past},
            {"id": "f-null", "topic": "T", "offering_id": None, "fsrs_d": None, "fsrs_s": None,
             "due_at": None, "reps": 0, "lapses": 0, "last_rating": None, "last_reviewed_at": None},
            {"id": "f-future", "topic": "T", "offering_id": None, "fsrs_d": 5.0, "fsrs_s": 9.0,
             "due_at": future, "reps": 1, "lapses": 0, "last_rating": 3, "last_reviewed_at": past},
        ],
        "learner_state": [
            {"node_id": "n-due", "p_known": 0.9, "streak_unassisted": 0, "fsrs_d": 5.0,
             "fsrs_s": 0.5, "fsrs_last_review_at": past, "fsrs_due_at": past},
        ],
        "graph_nodes": [{"id": "n-due", "course_id": COURSE, "concept_name": "Gradient descent"}],
    })
    monkeypatch.setattr(review, "table", factory)
    monkeypatch.setattr(review, "user_offering_ids_for_course", lambda u, c: ["off-1"])
    monkeypatch.setattr(review, "decayed_p", lambda p, elapsed, s: p)
    profic = (params.REVIEW_FORMAT_BY_BAND["profic"], params.REVIEW_DIFFICULTY_BY_BAND["profic"])
    novice = (params.REVIEW_FORMAT_BY_BAND["novice"], params.REVIEW_DIFFICULTY_BY_BAND["novice"])
    reads = []
    monkeypatch.setattr(review, "list_items", lambda course_id, concept_key, **kw: reads.append((course_id, concept_key, kw)) or [
        _check_item("n-due", "qh-0", *novice), _check_item("n-due", "qh-1", *profic),
    ])

    q = review.due_queue(USER, COURSE, NOW)

    ids = [i.id for i in q]
    assert "f-future" not in ids
    assert set(ids) == {"f-due", "f-null", "ci-qh-1"}
    # order: ascending |r − REVIEW_ORDER_THRESHOLD|
    dist = [abs(i.r - params.REVIEW_ORDER_THRESHOLD) for i in q]
    assert dist == sorted(dist)
    # never-scheduled card has r == 1.0 (elapsed 0, S0) → last
    assert ids[-1] == "f-null"
    # A2: ONE item read per concept, keyed on the node's course + concept_key, every format and difficulty
    assert [(c, k) for c, k, _ in reads] == [(COURSE, _normalize_concept("Gradient descent"))]
    assert not reads[0][2].get("format") and not reads[0][2].get("difficulty")
    # the concept drew a profic-band item (p_known 0.9 ≥ BAND_DEVELOP_MAX)
    check = next(i for i in q if i.kind == "check")
    assert (check.format, check.difficulty) == profic
    assert check.node_id == "n-due" and check.question_hash == "qh-1"
    assert check.cost_s == params.REVIEW_SECONDS_PER_CHECK
    # learner_state was read with the due filter, not scanned
    args, kwargs = handles["learner_state"].select.call_args
    assert kwargs["filters"]["fsrs_due_at"] == f"lte.{NOW.isoformat()}"


def test_due_queue_respects_budget_and_session_progress(monkeypatch):
    from learning import review

    past = (NOW - timedelta(days=2)).isoformat()
    n_cards = (params.REVIEW_DAILY_BUDGET_MIN * 60) // params.REVIEW_SECONDS_PER_FLASHCARD + 5
    cards = [
        {"id": f"f{i}", "topic": "T", "offering_id": None, "fsrs_d": 5.0, "fsrs_s": 1.0,
         "due_at": past, "reps": 0, "lapses": 0, "last_rating": None, "last_reviewed_at": past}
        for i in range(n_cards)
    ]
    factory, _ = _tables({"flashcards": cards, "learner_state": [], "graph_nodes": []})
    monkeypatch.setattr(review, "table", factory)

    full = review.due_queue(USER, None, NOW)
    assert sum(i.cost_s for i in full) <= params.REVIEW_DAILY_BUDGET_MIN * 60
    assert len(full) == (params.REVIEW_DAILY_BUDGET_MIN * 60) // params.REVIEW_SECONDS_PER_FLASHCARD

    spent = params.REVIEW_DAILY_BUDGET_MIN * 60 - params.REVIEW_SECONDS_PER_FLASHCARD
    loop_state = {"review": {"spent_s": spent}, "sr": {"fc:f0": {"correct": params.SR_INITIAL_CRITERION,
                                                                 "target": params.SR_INITIAL_CRITERION, "served": 3}}}
    nearly_done = review.due_queue(USER, None, NOW, loop_state=loop_state)
    assert len(nearly_done) == 1
    assert nearly_done[0].id != "f0"  # target met this session → dropped


def test_due_queue_skips_concepts_with_no_items(monkeypatch, caplog):
    from learning import review

    past = (NOW - timedelta(days=1)).isoformat()
    factory, _ = _tables({
        "flashcards": [],
        "learner_state": [_due_row("n-bare", 0.5, past)],
        "graph_nodes": [{"id": "n-bare", "course_id": COURSE, "concept_name": "Bare"}],
    })
    monkeypatch.setattr(review, "table", factory)
    calls = []
    monkeypatch.setattr(review, "list_items", lambda course_id, concept_key, **kw: calls.append(concept_key) or [])
    with caplog.at_level("INFO"):
        q, stats = review.due_queue_with_stats(USER, COURSE, NOW)
    assert q == [] and stats["unservable"] == 1 and stats["paused"] == 0
    # ONE read per concept (format fallback and the A23 fallback run in memory) — no 500, no generation
    assert len(calls) == 1
    assert any("unservable" in r.getMessage() for r in caplog.records)


def test_due_queue_excludes_seen_revealed_and_reserve_then_falls_back(monkeypatch):
    """A23: strict = served_today ∪ seen ∪ revealed ∪ {reserve}; fallback = revealed ∪ {reserve};
    nothing left → unservable. The reserve and a revealed item are never served."""
    from learning import review

    past = (NOW - timedelta(days=1)).isoformat()
    factory, _ = _tables({
        "flashcards": [],
        "learner_state": [_due_row("n-a", 0.9, past)],
        "graph_nodes": [{"id": "n-a", "course_id": COURSE, "concept_name": "A"}],
    })
    monkeypatch.setattr(review, "table", factory)
    monkeypatch.setattr(review, "decayed_p", lambda p, elapsed, s: p)
    fmt, diff = params.REVIEW_FORMAT_BY_BAND["profic"], params.REVIEW_DIFFICULTY_BY_BAND["profic"]
    pool = [_check_item("n-a", h, fmt, diff) for h in ("qh-reserve", "qh-seen", "qh-revealed", "qh-served", "qh-fresh")]
    monkeypatch.setattr(review, "list_items", lambda course_id, concept_key, **kw: list(pool))
    monkeypatch.setattr(review, "posttest_reserve_hash", lambda items: "qh-reserve")
    monkeypatch.setattr(review, "seen_hashes", lambda user_id: {"qh-seen"})
    monkeypatch.setattr(review, "revealed_hashes", lambda user_id: {"qh-revealed"})
    loop_state = {"sr": {}, "review": {"spent_s": 0, "served_hashes": ["qh-served"]}}

    def picked():
        q, stats = review.due_queue_with_stats(USER, COURSE, NOW, loop_state=loop_state)
        return [i.question_hash for i in q if i.kind == "check"], stats

    assert picked()[0] == ["qh-fresh"]
    # strict pass empty → the fallback may re-serve a seen or served item, never a revealed one or the reserve
    pool[:] = [i for i in pool if i.question_hash != "qh-fresh"]
    assert picked()[0] in (["qh-seen"], ["qh-served"])
    # only the revealed item and the reserve left → unservable
    pool[:] = [i for i in pool if i.question_hash in {"qh-reserve", "qh-revealed"}]
    checks, stats = picked()
    assert checks == [] and stats["unservable"] == 1


def test_due_queue_pauses_novice_concepts_at_the_tutor_hard_level(monkeypatch):
    """A20: at the hard level novice-band concepts pause (counted, no item read);
    develop/profic concepts and every flashcard keep being served."""
    from learning import review

    past = (NOW - timedelta(days=1)).isoformat()
    factory, _ = _tables({
        "flashcards": [{"id": "f1", "topic": "T", "offering_id": None, "fsrs_d": 5.0, "fsrs_s": 1.0,
                        "due_at": past, "reps": 0, "lapses": 0, "last_rating": None, "last_reviewed_at": past}],
        "learner_state": [_due_row("n-nov", 0.05, past), _due_row("n-pro", 0.9, past)],
        "graph_nodes": [{"id": "n-nov", "course_id": COURSE, "concept_name": "Nov"},
                        {"id": "n-pro", "course_id": COURSE, "concept_name": "Pro"}],
    })
    monkeypatch.setattr(review, "table", factory)
    monkeypatch.setattr(review, "user_offering_ids_for_course", lambda u, c: [])
    monkeypatch.setattr(review, "decayed_p", lambda p, elapsed, s: p)
    reads = []

    def items(course_id, concept_key, **kw):
        reads.append(concept_key)
        return [_check_item(concept_key, f"qh-{concept_key}-{params.REVIEW_FORMAT_BY_BAND[b]}",
                            params.REVIEW_FORMAT_BY_BAND[b], params.REVIEW_DIFFICULTY_BY_BAND[b])
                for b in ("novice", "profic")]

    monkeypatch.setattr(review, "list_items", items)

    normal, s_normal = review.due_queue_with_stats(USER, COURSE, NOW)
    assert {i.node_id for i in normal if i.kind == "check"} == {"n-nov", "n-pro"} and s_normal["paused"] == 0
    reads.clear()
    hard, s_hard = review.due_queue_with_stats(USER, COURSE, NOW, pause_novice=True)
    assert {i.node_id for i in hard if i.kind == "check"} == {"n-pro"}
    assert s_hard["paused"] == 1 and s_hard["unservable"] == 0
    assert [i.id for i in hard if i.kind == "flashcard"] == ["f1"]  # flashcards never pause
    assert len(reads) == 1  # the paused concept's items were never read


def test_serve_never_leaks_reference_or_rubric(monkeypatch):
    from learning import review

    item = _item("check", 0.4, id="ci-qh-1", node_id="n-due", question_hash="qh-1", format="free", difficulty=3)
    loop_state = {"sr": {}, "review": {"spent_s": 0}}
    payload = review.serve(item, check_item=_check_item("n-due", "qh-1"), loop_state=loop_state)
    flat = str(payload)
    assert "REF-n-due" not in flat and "rubric" not in flat and "common_wrong" not in flat
    assert payload["prompt"] == "Explain n-due"
    assert payload.get("options") is None  # only mc_reason items carry options
    assert payload["sr"] == {"stage": "acquire", "correct": 0, "target": params.SR_INITIAL_CRITERION}
    assert loop_state["sr"]["n-due"]["served"] == 1
    assert loop_state["review"]["served_hashes"] == ["qh-1"]  # served_today for the A23 exclusion


def test_serve_mc_reason_sends_the_stored_options_only(monkeypatch):
    """A22: the stored options_json, letter + text in stored order — never rebuilt
    from the reference, never a wrong_key, never which option is correct."""
    from learning import review

    item = _item("check", 0.4, id="ci-qh-2", node_id="n-due", question_hash="qh-2", format="mc_reason", difficulty=1)
    payload = review.serve(item, check_item=_check_item("n-due", "qh-2", "mc_reason", 1),
                           loop_state={"sr": {}, "review": {"spent_s": 0}})
    assert payload["options"] == [{"letter": "A", "text": "OPT-A-n-due"}, {"letter": "B", "text": "OPT-B-n-due"}]
    flat = str(payload)
    assert "REF-n-due" not in flat and "wrong_key" not in flat and "w1" not in flat and "correct_option" not in flat


def _deps():
    """Stand-in for the SaplingDeps the route builds with PKG-07's deps builder."""
    deps = MagicMock()
    deps.user_id, deps.session_id, deps.learning_loop, deps.pending_evidence = USER, "sess-1", True, []
    return deps


def _grade(correct=True, confidence=0.9, unavailable=False, feedback="Nice.", weight=1.0, backend="gemini"):
    """Stand-in for PKG-05's grade_answer: like the real helper it appends its one
    Evidence dict to deps.pending_evidence and returns it as outcome.evidence;
    unavailable → nothing appended, for either outcome."""
    from agents.tools.check import CHANNEL_FOR_FORMAT

    calls = []

    async def _run(item, answer, *, deps, node_id, max_rung=0, same_session_recheck=False):
        out = MagicMock()
        out.unavailable, out.feedback_hint, out.wrong_key, out.matched_wrong_key = unavailable, feedback, None, None
        out.correct = None if unavailable else correct
        out.confidence = None if unavailable else confidence
        out.grader_backend = None if unavailable else backend
        out.evidence = None
        if not unavailable:
            out.evidence = {
                "node_id": node_id, "channel": CHANNEL_FOR_FORMAT[item.format], "idk": False, "correct": correct,
                "assisted": False, "max_rung": max_rung, "weight": weight, "session_id": deps.session_id,
                "check_item_id": item.id, "question_hash": item.question_hash, "confidence": confidence,
                "same_session_recheck": same_session_recheck, "grader_backend": backend,
            }
            deps.pending_evidence.append(out.evidence)
        calls.append({"item": item, "answer": answer, "deps": deps, "node_id": node_id, "max_rung": max_rung,
                      "same_session_recheck": same_session_recheck, "outcome": out})
        return out

    return _run, calls


def test_check_review_writes_evidence_once_through_apply_graph_update(monkeypatch):
    from learning import review

    grade, calls = _grade(correct=True)
    monkeypatch.setattr(review, "grade_answer", grade)
    applied = []
    monkeypatch.setattr(review, "apply_graph_update", lambda uid, gu, course_id=None: applied.append((uid, gu, course_id)) or [])
    factory, handles = _tables({
        "learner_state": [{"node_id": "n-due", "fsrs_due_at": (NOW + timedelta(days=4)).isoformat()}],
    })
    monkeypatch.setattr(review, "table", factory)
    events = []
    monkeypatch.setattr(review, "log_event", lambda et, **kw: events.append((et, kw)))

    item = _item("check", 0.4, id="ci-qh-1", node_id="n-due", question_hash="qh-1", format="free", difficulty=3)
    loop_state = {"sr": {"n-due": {"correct": 0, "target": params.SR_INITIAL_CRITERION, "served": 1}},
                  "review": {"spent_s": 0, "retention": params.FSRS_RETENTION_DEFAULT}}
    deps = _deps()
    out = asyncio.run(review.grade_review(
        USER, item, answer="because the gradient points uphill", rating=None,
        session_id="sess-1", loop_state=loop_state, now=NOW, request_id="req-1",
        retention=params.FSRS_RETENTION_EXAM, check_item=_check_item("n-due", "qh-1"), deps=deps,
    ))

    # graded once, through grade_answer, unassisted (A16)
    (call,) = calls
    assert call["deps"] is deps and call["node_id"] == "n-due"
    assert call["max_rung"] == 0 and call["same_session_recheck"] is False
    assert call["answer"].question_hash == "qh-1" and call["answer"].answer_text == "because the gradient points uphill"
    # one write: the helper's Evidence dict, unchanged (A22 weight, grader_backend), plus the retention target
    assert len(applied) == 1
    uid, gu, course_id = applied[0]
    assert uid == USER and course_id == COURSE
    assert gu["retention"] == params.FSRS_RETENTION_EXAM
    assert gu["evidence"] == [call["outcome"].evidence]
    assert out.correct is True and out.unavailable is False
    assert out.next_due_at == (NOW + timedelta(days=4)).isoformat()
    assert "REF-n-due" not in (out.hint or "")
    # SR + budget advanced and persisted
    assert loop_state["sr"]["n-due"]["correct"] == 1
    assert loop_state["review"]["spent_s"] == params.REVIEW_SECONDS_PER_CHECK
    handles["sessions"].update.assert_called_once()
    assert handles["sessions"].update.call_args.kwargs["filters"] == {"id": "eq.sess-1"}
    assert events == [("review.graded", {"category": "usage", "user_id": USER, "request_id": "req-1",
                                         "payload": {"kind": "check", "correct": True, "rating": out.rating}})]


def test_check_review_wrong_answer_gets_the_answer_and_resets_sr(monkeypatch):
    from learning import review

    grade, _ = _grade(correct=False, feedback="Not quite.")
    monkeypatch.setattr(review, "grade_answer", grade)
    monkeypatch.setattr(review, "apply_graph_update", lambda *a, **k: [])
    factory, _ = _tables({"learner_state": [{"node_id": "n-due", "fsrs_due_at": NOW.isoformat()}]})
    monkeypatch.setattr(review, "table", factory)
    monkeypatch.setattr(review, "log_event", lambda *a, **k: None)
    item = _item("check", 0.4, id="ci-qh-1", node_id="n-due", question_hash="qh-1", format="free", difficulty=3)
    loop_state = {"sr": {"n-due": {"correct": 2, "target": 3, "served": 3}}, "review": {"spent_s": 0}}
    out = asyncio.run(review.grade_review(
        USER, item, answer="downhill", rating=None, session_id="s", loop_state=loop_state,
        now=NOW, request_id="r", retention=params.FSRS_RETENTION_DEFAULT, check_item=_check_item("n-due", "qh-1"),
        deps=_deps(),
    ))
    assert out.correct is False
    assert "REF-n-due" in out.hint  # spec §3.3: corrective feedback WITH the answer
    assert loop_state["sr"]["n-due"]["correct"] == 0


def test_check_review_mc_reason_forwards_the_choice_and_keeps_the_helpers_weight(monkeypatch):
    """A22: option + reason reach grade_answer as submitted; the Evidence (weight from the
    reason check's confidence, grader_backend) is persisted exactly as grade_answer built it."""
    from learning import review

    grade, calls = _grade(correct=True, confidence=0.3, weight=params.WEIGHT_LOW_CONFIDENCE, backend="gemini_second")
    monkeypatch.setattr(review, "grade_answer", grade)
    applied = []
    monkeypatch.setattr(review, "apply_graph_update", lambda uid, gu, course_id=None: applied.append(gu) or [])
    factory, _ = _tables({"learner_state": [{"node_id": "n-due", "fsrs_due_at": NOW.isoformat()}]})
    monkeypatch.setattr(review, "table", factory)
    monkeypatch.setattr(review, "log_event", lambda *a, **k: None)
    item = _item("check", 0.4, id="ci-qh-1", node_id="n-due", question_hash="qh-1", format="mc_reason", difficulty=1)
    asyncio.run(review.grade_review(
        USER, item, answer=None, selected_option="A", reason="because it stops", rating=None, session_id="s",
        loop_state={"sr": {}, "review": {"spent_s": 0}}, now=NOW, request_id="r",
        retention=params.FSRS_RETENTION_DEFAULT, check_item=_check_item("n-due", "qh-1", "mc_reason", 1), deps=_deps(),
    ))
    (call,) = calls
    assert call["answer"].selected_option == "A" and call["answer"].reason == "because it stops"
    (ev,) = applied[0]["evidence"]
    assert ev["weight"] == params.WEIGHT_LOW_CONFIDENCE and ev["grader_backend"] == "gemini_second"
    assert ev["channel"] == "mc_reasoned"


@pytest.mark.parametrize("selected_option", ["A", "B"])  # the right option and a wrong one (invariant 28)
def test_grader_unavailable_writes_nothing(monkeypatch, selected_option):
    """Outage or the STUDENT_DAILY_GRADES cap: nothing for either outcome, item stays due."""
    from learning import review

    grade, calls = _grade(unavailable=True)
    monkeypatch.setattr(review, "grade_answer", grade)
    applied = []
    monkeypatch.setattr(review, "apply_graph_update", lambda *a, **k: applied.append(1))
    factory, handles = _tables({})
    monkeypatch.setattr(review, "table", factory)
    events = []
    monkeypatch.setattr(review, "log_event", lambda et, **kw: events.append(et))
    item = _item("check", 0.4, id="ci-qh-1", node_id="n-due", question_hash="qh-1", format="mc_reason", difficulty=1)
    loop_state = {"sr": {}, "review": {"spent_s": 0}}
    out = asyncio.run(review.grade_review(
        USER, item, answer=None, selected_option=selected_option, reason="because", rating=None, session_id="s",
        loop_state=loop_state, now=NOW, request_id="r", retention=params.FSRS_RETENTION_DEFAULT,
        check_item=_check_item("n-due", "qh-1", "mc_reason", 1), deps=_deps(),
    ))
    assert len(calls) == 1  # the grade was attempted, whichever option was chosen
    assert out.unavailable is True and out.correct is None
    assert applied == [] and events == [] and loop_state["review"]["spent_s"] == 0
    assert "sessions" not in handles or not handles["sessions"].update.called
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_review.py -v -k "retention or sr_stage or session_id or due_queue or serve or check_review or unavailable"`
Expected: every test FAILS or ERRORS with `ImportError: cannot import name 'retention_target' from 'learning.review'` (or `AttributeError: module 'learning.review' has no attribute 'table'` / `'due_queue_with_stats'`).

- [ ] **Step 3: Implement `backend/learning/review.py`**

Module docstring names the package and the spec sections (§3.2, §5, §6; §13 A16, A20, A22, A23). Imports, all module-level so they are patchable:

```python
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel

from agents.tools.check import CheckAnswer, grade_answer   # PKG-05 — the ONLY grading path (A16, inv 19)
from db.connection import table
from learning import fsrs
from learning.bkt import band, decayed_p
from learning.checks import posttest_reserve_hash, select_item
from learning.loop_state_store import revealed_hashes, seen_hashes   # PKG-07 (A23)
from learning.params import (
    FSRS_EXAM_WINDOW_DAYS, FSRS_LARGE_SET_CONCEPTS, FSRS_RETENTION_DEFAULT, FSRS_RETENTION_EXAM,
    FSRS_RETENTION_LARGE_SET, FSRS_S0_GOOD, REVIEW_DAILY_BUDGET_MIN, REVIEW_DIFFICULTY_BY_BAND,
    REVIEW_FORMAT_BY_BAND, REVIEW_SECONDS_PER_CHECK, REVIEW_SECONDS_PER_FLASHCARD,
    SR_INITIAL_CRITERION, SR_RELEARN_SESSIONS,
)
from services.academics import resolve_offering, user_offering_ids_for_course
from services.check_item_service import list_items
from services.encryption import decrypt_if_present
from services.events_service import log_event
from services.exam_proximity import days_until_next_exam
from services.graph_service import _normalize_concept, apply_graph_update
from <PKG-11 module> import flashcard_fsrs_update      # per HANDOFF-11; never routes.*
```

No `learning.evidence` import: review never builds an `Evidence` — it persists the dict `grade_answer` returns. No `services.ai_budget` import: the route passes `pause_novice` in.

Models:
```python
class ReviewItem(BaseModel):
    kind: Literal["flashcard", "check"]
    id: str
    node_id: str | None = None
    course_id: str | None = None
    question_hash: str | None = None
    due_at: datetime | None = None
    r: float
    stability: float
    format: Literal["free", "mc_reason"] | None = None
    difficulty: int | None = None
    cost_s: int
    sr_stage: Literal["acquire", "relearn", "done"]
    sr_target: int


class ReviewOutcome(BaseModel):
    correct: bool | None = None
    hint: str | None = None
    next_due_at: str | None = None
    rating: int | None = None
    sr: dict = {}
    unavailable: bool = False
```

Functions, each per §Behaviour: `retention_target` (rule 2), `sr_stage_for_concept` / `sr_stage_for_flashcard` (rule 3), `review_session_id` (rule 4), `load_or_create_review_session(user_id, course_id, now) -> tuple[str, dict]` (rule 4; returns `(sid, loop_state)` with `loop_state` defaulting to `{"sr": {}, "review": {"spent_s": 0, "served_hashes": []}}`; every reader tolerates a missing key), `_persist_loop_state(session_id, loop_state)`, `_elapsed_days(last_iso, now) -> float` (`None` → 0.0), `_sr_key(item)`, `due_queue(user_id, course_id, now, *, loop_state=None, pause_novice=False)` (rule 1; expose `due_queue_with_stats(user_id, course_id, now, *, loop_state=None, pause_novice=False) -> tuple[list[ReviewItem], dict]` with stats `{"unservable": int, "paused": int, "n_scheduled": int}` and have `due_queue` return the list; `summary()` uses the stats), `serve(item, *, check_item=None, card_row=None, loop_state)` (rule 5), `grade_review(...)` (rule 6), `summary(user_id, course_id, now, *, loop_state, pause_novice=False) -> dict` (route 7c's body). Keep the flashcard branch of `grade_review` for Task 4, but write the function skeleton now with `raise NotImplementedError("PKG-12 Task 4")` in that branch.

`next_due_at` after a check: `rows = table("learner_state").select("node_id,fsrs_due_at", filters={"user_id": f"eq.{user_id}", "node_id": f"eq.{node_id}"})` → `rows[0]["fsrs_due_at"]` or `None`.

Contract details the tests pin: `serve` initialises `loop_state["sr"][key]` to `{"correct": 0, "target": item.sr_target, "served": 0}` when absent, then increments `served`, and for a check appends `item.question_hash` to `loop_state["review"]["served_hashes"]` (created when absent, never duplicated); for an `mc_reason` check it returns `options = [{"letter": o.letter, "text": o.text} for o in check_item.options]` and nothing else from the options; `grade_review` does the same SR initialisation, after an `unavailable` outcome has already returned, before touching `correct`. `log_event` is always called with exactly the four keyword arguments `category="usage", user_id=..., request_id=..., payload={...}` and nothing else. `grade_review(user_id, item, *, answer, rating, session_id, loop_state, now, request_id, retention, check_item=None, card_row=None, selected_option=None, reason=None, deps=None)` takes `check_item=` (a decrypted `CheckItem`, for checks) or `card_row=` (the `flashcards` row, for flashcards) so it never re-reads what the route already loaded, and `deps=` (the route-built `SaplingDeps`, required for checks). For a check it calls `grade_answer(check_item, CheckAnswer(question_hash=check_item.question_hash, answer_text=answer or "", selected_option=selected_option, reason=reason), deps=deps, node_id=item.node_id)` exactly once and, unless `unavailable`, `apply_graph_update(user_id, {"evidence": [outcome.evidence], "retention": retention}, course_id=item.course_id)` exactly once — never `flush_pending`, never a second write of `deps.pending_evidence`.

The `hint` for a wrong check answer is `f"{outcome.feedback_hint}\n\nAnswer: {check_item.reference_answer}"`; for a correct answer, `outcome.feedback_hint` alone. `rating = fsrs.rating_for(outcome.evidence["channel"], outcome.correct, 0)`.

- [ ] **Step 3b (only if HANDOFF-03 shows `apply_graph_update` ignores a retention target):** add `retention = float(graph_update.get("retention", FSRS_RETENTION_DEFAULT))` at the top of the evidence branch in `services/graph_service.py::apply_graph_update` and pass it to the `fsrs.interval(...)` call that sets `fsrs_due_at`; add one test to `tests/test_learning_evidence_apply.py` asserting an exam-window retention yields a shorter interval than the default for the same state. Commit **first and separately**:

```
git add backend/services/graph_service.py backend/tests/test_learning_evidence_apply.py
git commit -m "fix(learning-loop): PKG-03 — apply_graph_update honours graph_update[\"retention\"]

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
Then append `| 03 | evidence-state | reopened | feat/learning-loop-12-review-surfaces | <sha> | 1 test | PKG-12 | HANDOFF-03.md |` to the ledger and a `## Post-hoc changes` line to `HANDOFF-03.md`.

- [ ] **Step 4: Run tests, lint**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_review.py tests/test_learning_loop_invariants.py tests/test_learning_evidence_apply.py tests/test_graph_service.py -q && venv/bin/ruff check . && venv/bin/ruff format --check learning/review.py`
Expected: every Task 2/3 test passes; `inv_19`, `inv_01`, `inv_05`, `inv_07` pass; `All checks passed!`; format clean.

- [ ] **Step 5: Commit**

```
git add backend/learning/review.py backend/tests/test_learning_review.py
git commit -m "feat(learning-loop): PKG-12 — review queue, retention target, SR stage, check grading

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 4: Flashcard reviews through the PKG-11 FSRS path

**Files:**
- Modify: `backend/learning/review.py` (flashcard branch of `grade_review`)
- Possibly modify (Step 3b only): the PKG-11 helper's module, `docs/superpowers/plans/learning-loop/HANDOFF-11.md`
- Test: `backend/tests/test_learning_review.py` (third block)

**Interfaces:**
- Consumes: `flashcard_fsrs_update(card_row, rating, *, now, retention)`.
- Produces: the flashcard branch; `review.graded {kind: "flashcard"}`.

- [ ] **Step 1: Append the failing tests**

```python
# ── Task 4: flashcard reviews ─────────────────────────────────────────────────


def _card_row(**kw):
    row = {"id": "f1", "user_id": USER, "topic": "T", "offering_id": None, "fsrs_d": None, "fsrs_s": None,
           "due_at": None, "reps": 0, "lapses": 0, "times_reviewed": 0, "last_rating": None,
           "last_reviewed_at": None, "front": "enc-front", "back": "enc-back"}
    row.update(kw)
    return row


@pytest.mark.parametrize("rating,correct", [(1, False), (2, True), (3, True)])
def test_flashcard_review_updates_fsrs_and_legacy_columns(monkeypatch, rating, correct):
    from learning import review

    factory, handles = _tables({"flashcards": [_card_row()]})
    monkeypatch.setattr(review, "table", factory)
    events = []
    monkeypatch.setattr(review, "log_event", lambda et, **kw: events.append((et, kw["payload"])))
    item = _item("flashcard", 1.0, id="f1", node_id=None)
    loop_state = {"sr": {}, "review": {"spent_s": 0}}
    out = asyncio.run(review.grade_review(
        USER, item, answer=None, rating=rating, session_id="s", loop_state=loop_state,
        now=NOW, request_id="r", retention=params.FSRS_RETENTION_DEFAULT, card_row=_card_row(),
    ))
    handles["flashcards"].update.assert_called_once()
    cols, kwargs = handles["flashcards"].update.call_args.args[0], handles["flashcards"].update.call_args.kwargs
    assert kwargs["filters"] == {"id": "eq.f1", "user_id": f"eq.{USER}"}
    assert {"fsrs_d", "fsrs_s", "due_at", "reps", "lapses", "times_reviewed", "last_rating", "last_reviewed_at"} <= set(cols)
    assert cols["reps"] == 1 and cols["times_reviewed"] == 1 and cols["last_rating"] == rating
    assert cols["fsrs_s"] > 0 and cols["due_at"] > NOW.isoformat()
    assert out.correct is correct and out.next_due_at == cols["due_at"]
    assert loop_state["review"]["spent_s"] == params.REVIEW_SECONDS_PER_FLASHCARD
    assert loop_state["sr"]["fc:f1"]["correct"] == (1 if correct else 0)
    assert events == [("review.graded", {"kind": "flashcard", "correct": correct, "rating": out.rating})]
    assert out.rating in (1, 2, 3)  # Easy(4) is never emitted in v1 (spec §3.2)


def test_flashcard_review_uses_the_requested_retention(monkeypatch):
    from learning import review

    seen = []
    real = review.flashcard_fsrs_update

    def spy(card_row, rating, *, now, retention):
        seen.append(retention)
        return real(card_row, rating, now=now, retention=retention)

    monkeypatch.setattr(review, "flashcard_fsrs_update", spy)
    factory, _ = _tables({"flashcards": [_card_row()]})
    monkeypatch.setattr(review, "table", factory)
    monkeypatch.setattr(review, "log_event", lambda *a, **k: None)
    asyncio.run(review.grade_review(
        USER, _item("flashcard", 1.0, id="f1"), answer=None, rating=3, session_id="s",
        loop_state={"sr": {}, "review": {"spent_s": 0}}, now=NOW, request_id="r",
        retention=params.FSRS_RETENTION_EXAM, card_row=_card_row(),
    ))
    assert seen == [params.FSRS_RETENTION_EXAM]


def test_flashcard_review_rejects_bad_rating(monkeypatch):
    from learning import review

    with pytest.raises(ValueError):
        asyncio.run(review.grade_review(
            USER, _item("flashcard", 1.0, id="f1"), answer=None, rating=4, session_id="s",
            loop_state={"sr": {}, "review": {"spent_s": 0}}, now=NOW, request_id="r",
            retention=params.FSRS_RETENTION_DEFAULT, card_row=_card_row(),
        ))
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_review.py -v -k flashcard_review`
Expected: FAIL — `NotImplementedError: PKG-12 Task 4`.

- [ ] **Step 3: Implement** the flashcard branch per §Behaviour rule 6: validate `rating in (1, 2, 3)` (else `ValueError`), call `flashcard_fsrs_update`, write the `flashcards` row, set `correct = rating >= 2`, `out.rating` = the FSRS rating the helper chose (read it from the returned cols if present, else `fsrs.rating_for("mc", correct, 0)` is NOT the right map — use PKG-11's; if the helper does not expose it, extend it in Step 3b), advance SR + budget, persist, emit.

- [ ] **Step 3b (only if the PKG-11 helper is inside `routes/flashcards.py`, is not pure, or lacks `retention=`):** move/extend it into `backend/services/flashcard_fsrs.py` (or the module HANDOFF-11 already uses), keep `rate_card` calling it, keep `tests/test_learning_flashcards_fsrs.py` green. Commit **separately and before** the review change:

```
git add backend/services/flashcard_fsrs.py backend/routes/flashcards.py backend/tests/test_learning_flashcards_fsrs.py
git commit -m "fix(learning-loop): PKG-11 — pure flashcard_fsrs_update with a retention target

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
Ledger row `| 11 | quiz-flashcards | reopened | … | PKG-12 | HANDOFF-11.md |` and a Post-hoc line in `HANDOFF-11.md`.

- [ ] **Step 4: Run tests, lint**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_review.py tests/test_learning_flashcards_fsrs.py tests/test_flashcards_routes.py tests/test_achievement_dispatch.py -q && venv/bin/ruff check .`
Expected: all passed; `All checks passed!`

- [ ] **Step 5: Commit**

```
git add backend/learning/review.py backend/tests/test_learning_review.py
git commit -m "feat(learning-loop): PKG-12 — flashcard reviews through the FSRS rating path

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 5: Routes `/review/next`, `/review/answer`, `/review/summary`

**Files:**
- Modify: `backend/routes/learn_loop.py`, `backend/tests/test_learning_loop_invariants.py` (the invariant 26 allow-list only)
- Test: `backend/tests/test_learning_review.py` (fourth block)

**Interfaces:**
- Consumes: PKG-07's router + gate helper, deps builder, check-item → `node_id` resolution and `enforce_rate_limit` attachment pattern; PKG-06b's `ai_budget.check` / `enforce_rate_limit`; `learning.review.*`.
- Produces: the three routes (§Behaviour rule 7), `_review_deps`, `_review_node_id`, `_pause_novice`, and, if absent, `GET /status`.

- [ ] **Step 0: Bind to PKG-07's shapes** (record each answer in the hand-off's Symbols section):

```
grep -n "def test_inv_26" -A 30 backend/tests/test_learning_loop_invariants.py    # (I) the allow-list: function names or route paths?
grep -n "enforce_rate_limit" backend/routes/learn_loop.py                           # (R) how /check/answer attaches it (dependencies=[…] or a parameter)
grep -n "SaplingDeps(" backend/routes/learn_loop.py                                  # (D) how /check/answer builds its deps
grep -n "def _node_for_item" -A 12 backend/routes/learn_loop.py                     # (N) how the student's node_id is resolved
grep -nE "^(async )?def check\(" backend/services/ai_budget.py                       # (B) is ai_budget.check async?
```

- [ ] **Step 1: Append the failing tests**

```python
# ── Task 5: routes ────────────────────────────────────────────────────────────


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient
    from main import app
    from services.ai_budget import enforce_rate_limit

    # PKG-06b's reads are pinned here: the rate limit never trips and the tutor is
    # below the hard level. test_rate_limit_applies_to_check_answers_only and the
    # summary test cover the two seams themselves.
    app.dependency_overrides[enforce_rate_limit] = lambda: None
    monkeypatch.setattr("services.ai_budget.enforce_rate_limit_for", lambda user_id: None)
    monkeypatch.setattr("routes.learn_loop._pause_novice", lambda user_id: False, raising=False)
    yield TestClient(app)
    app.dependency_overrides.pop(enforce_rate_limit, None)


def _no_table(name):
    raise AssertionError(f"table({name!r}) must not be called on the gated-off path")


@pytest.mark.parametrize("method,path,body", [
    ("get", f"/api/learn/loop/review/next?user_id={USER}&course_id={COURSE}", None),
    ("post", "/api/learn/loop/review/answer", {"user_id": USER, "session_id": "s", "kind": "flashcard", "item_id": "f1", "rating": 3}),
    ("get", f"/api/learn/loop/review/summary?user_id={USER}", None),
])
def test_routes_404_when_gate_false(client, method, path, body):
    with patch("routes.learn_loop.require_self", return_value=None), \
         patch("routes.learn_loop.learning_loop_active", return_value=False), \
         patch("learning.review.table", side_effect=_no_table):
        r = getattr(client, method)(path, json=body) if body else getattr(client, method)(path)
    assert r.status_code == 404
    assert r.json() == {"detail": "learning loop not enabled"}


def test_status_reports_active(client):
    with patch("routes.learn_loop.require_self", return_value=None), \
         patch("routes.learn_loop.learning_loop_active", return_value=True):
        r = client.get(f"/api/learn/loop/status?user_id={USER}")
    assert r.status_code == 200 and r.json()["active"] is True


def test_review_next_serves_first_item_with_budget_and_events(client, monkeypatch):
    from learning import review

    item = _item("check", 0.4, id="ci-qh-1", node_id="n-due", question_hash="qh-1", format="free", difficulty=3)
    card = _item("flashcard", 0.9, id="f1")
    monkeypatch.setattr(review, "load_or_create_review_session", lambda u, c, now: ("sess-1", {"sr": {}, "review": {"spent_s": 60}}))
    monkeypatch.setattr(review, "due_queue_with_stats", lambda u, c, now, **kw: ([item, card], {"unservable": 0, "paused": 0, "n_scheduled": 3}))
    monkeypatch.setattr(review, "days_until_next_exam", lambda u, c: None)
    monkeypatch.setattr(review, "_persist_loop_state", lambda sid, ls: None)
    monkeypatch.setattr("routes.learn_loop._load_check_item", lambda item_id: _check_item("n-due", "qh-1"))
    events = []
    monkeypatch.setattr(review, "log_event", lambda et, **kw: events.append((et, kw["payload"])))
    with patch("routes.learn_loop.require_self", return_value=None), \
         patch("routes.learn_loop.learning_loop_active", return_value=True):
        r = client.get(f"/api/learn/loop/review/next?user_id={USER}&course_id={COURSE}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["session_id"] == "sess-1" and body["due_total"] == 2
    assert body["remaining_budget_s"] == params.REVIEW_DAILY_BUDGET_MIN * 60 - 60
    assert body["retention_target"] == params.FSRS_RETENTION_DEFAULT
    assert body["item"]["kind"] == "check" and body["item"]["prompt"] == "Explain n-due"
    assert "REF-n-due" not in r.text
    assert sorted(events) == sorted([
        ("review.served", {"kind": "check", "n": 1, "budget_min": params.REVIEW_DAILY_BUDGET_MIN, "retention_target": params.FSRS_RETENTION_DEFAULT}),
        ("review.served", {"kind": "flashcard", "n": 1, "budget_min": params.REVIEW_DAILY_BUDGET_MIN, "retention_target": params.FSRS_RETENTION_DEFAULT}),
    ])


def test_review_next_empty_queue_is_null_item(client, monkeypatch):
    from learning import review

    monkeypatch.setattr(review, "load_or_create_review_session", lambda u, c, now: ("sess-1", {"sr": {}, "review": {"spent_s": 0}}))
    monkeypatch.setattr(review, "due_queue_with_stats", lambda u, c, now, **kw: ([], {"unservable": 0, "paused": 0, "n_scheduled": 0}))
    monkeypatch.setattr(review, "days_until_next_exam", lambda u, c: None)
    events = []
    monkeypatch.setattr(review, "log_event", lambda et, **kw: events.append(et))
    with patch("routes.learn_loop.require_self", return_value=None), \
         patch("routes.learn_loop.learning_loop_active", return_value=True):
        r = client.get(f"/api/learn/loop/review/next?user_id={USER}")
    assert r.status_code == 200 and r.json()["item"] is None and r.json()["due_total"] == 0
    assert events == []  # nothing served, nothing emitted


@pytest.mark.parametrize("body", [
    {"user_id": USER, "session_id": "s", "kind": "check", "item_id": "ci-1"},               # neither answer nor selected_option
    {"user_id": USER, "session_id": "s", "kind": "flashcard", "item_id": "f1"},             # no rating
    {"user_id": USER, "session_id": "s", "kind": "flashcard", "item_id": "f1", "rating": 4},
    {"user_id": USER, "session_id": "s", "kind": "essay", "item_id": "x", "answer": "y"},
])
def test_review_answer_validates_body(client, body):
    with patch("routes.learn_loop.require_self", return_value=None), \
         patch("routes.learn_loop.learning_loop_active", return_value=True):
        r = client.post("/api/learn/loop/review/answer", json=body)
    assert r.status_code == 422


def test_review_answer_grades_and_returns_next_due(client, monkeypatch):
    from learning import review
    from learning.review import ReviewOutcome

    monkeypatch.setattr(review, "load_or_create_review_session", lambda u, c, now: ("sess-1", {"sr": {}, "review": {"spent_s": 45, "retention": params.FSRS_RETENTION_DEFAULT}}))
    monkeypatch.setattr("routes.learn_loop._load_check_item", lambda item_id: _check_item("n-due", "qh-1"))
    monkeypatch.setattr("routes.learn_loop._review_node_id", lambda user_id, item: "n-due")  # server-side (A2)
    monkeypatch.setattr("routes.learn_loop._review_deps", lambda *a, **k: "DEPS")
    seen = {}

    async def fake_grade(user_id, item, **kw):
        seen.update(kw)
        seen["item"] = item
        return ReviewOutcome(correct=True, hint="Nice.", next_due_at="2026-10-01T00:00:00+00:00", rating=3, sr={"stage": "acquire", "correct": 1, "target": 3})

    monkeypatch.setattr(review, "grade_review", fake_grade)
    with patch("routes.learn_loop.require_self", return_value=None), \
         patch("routes.learn_loop.learning_loop_active", return_value=True):
        r = client.post("/api/learn/loop/review/answer", json={
            "user_id": USER, "session_id": "sess-1", "course_id": COURSE, "kind": "check",
            "item_id": "ci-qh-1", "answer": "because",
        })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["correct"] is True and body["hint"] == "Nice." and body["rating"] == 3
    assert body["next_due_at"] == "2026-10-01T00:00:00+00:00" and body["unavailable"] is False
    assert body["remaining_budget_s"] == params.REVIEW_DAILY_BUDGET_MIN * 60 - 45
    assert seen["item"].kind == "check" and seen["item"].id == "ci-qh-1" and seen["item"].node_id == "n-due"
    assert seen["answer"] == "because" and seen["deps"] == "DEPS"
    assert seen["retention"] == params.FSRS_RETENTION_DEFAULT


def test_review_answer_forwards_the_mc_reason_choice(client, monkeypatch):
    """A22: an mc_reason review answer is an option letter plus a reason; both reach
    grade_review, and an mc_reason answer without an option is a 422."""
    from learning import review
    from learning.review import ReviewOutcome

    monkeypatch.setattr(review, "load_or_create_review_session", lambda u, c, now: ("sess-1", {"sr": {}, "review": {"spent_s": 0, "retention": params.FSRS_RETENTION_DEFAULT}}))
    monkeypatch.setattr("routes.learn_loop._load_check_item", lambda item_id: _check_item("n-due", "qh-2", "mc_reason", 1))
    monkeypatch.setattr("routes.learn_loop._review_node_id", lambda user_id, item: "n-due")
    monkeypatch.setattr("routes.learn_loop._review_deps", lambda *a, **k: "DEPS")
    seen = {}

    async def fake_grade(user_id, item, **kw):
        seen.update(kw)
        return ReviewOutcome(correct=False, hint="Not quite.", rating=1, sr={"stage": "acquire", "correct": 0, "target": 3})

    monkeypatch.setattr(review, "grade_review", fake_grade)
    base = {"user_id": USER, "session_id": "sess-1", "course_id": COURSE, "kind": "check", "item_id": "ci-qh-2"}
    with patch("routes.learn_loop.require_self", return_value=None), \
         patch("routes.learn_loop.learning_loop_active", return_value=True):
        ok = client.post("/api/learn/loop/review/answer", json={**base, "selected_option": "B", "reason": "because it loops"})
        no_option = client.post("/api/learn/loop/review/answer", json={**base, "answer": "B because it loops"})
    assert ok.status_code == 200, ok.text
    assert seen["selected_option"] == "B" and seen["reason"] == "because it loops"
    assert no_option.status_code == 422


def test_rate_limit_applies_to_check_answers_only():
    """A20 / spec §9, §3.5: the rate limit guards the one review body that can run a model —
    a check answer (the grader). No review route carries the dependency; a self-rated
    flashcard is never rate-limited (flashcards keep working at every level)."""
    import ast
    import pathlib

    from main import app
    from services.ai_budget import enforce_rate_limit

    deps_by_path = {
        r.path: {d.call for d in r.dependant.dependencies}
        for r in app.routes if getattr(r, "path", "").startswith("/api/learn/loop/review/")
    }
    assert all(enforce_rate_limit not in deps for deps in deps_by_path.values())
    src = (pathlib.Path(__file__).resolve().parents[1] / "routes" / "learn_loop.py").read_text()
    handler = next(n for n in ast.walk(ast.parse(src))
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "review_answer")
    body = ast.unparse(handler)
    assert "enforce_rate_limit_for" in body and 'kind == "check"' in body


def test_grade_review_called_only_from_review_answer():
    """Invariant 26 (extended): a review's one evidence write happens inside
    review.grade_review, so every call of it in routes/learn_loop.py must sit in the
    /review/answer handler — an explicit submission, never a chat turn."""
    import ast

    src = pathlib.Path(__file__).resolve().parents[1] / "routes" / "learn_loop.py"
    callers = set()
    for fn in ast.walk(ast.parse(src.read_text())):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for node in ast.walk(fn):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "grade_review":
                    callers.add(fn.name)
    assert callers == {"review_answer"}, callers


def test_review_summary_counts_by_kind(client, monkeypatch):
    from learning import review

    monkeypatch.setattr(review, "load_or_create_review_session", lambda u, c, now: ("sess-1", {"sr": {}, "review": {"spent_s": 0}}))
    seen_kw = {}

    def fake_queue(u, c, now, **kw):
        seen_kw.update(kw)
        return (
            [_item("check", 0.4, id="c1", node_id="n1"), _item("flashcard", 0.5, id="f1"), _item("flashcard", 0.6, id="f2")],
            {"unservable": 2, "paused": 1, "n_scheduled": params.FSRS_LARGE_SET_CONCEPTS + 1},
        )

    monkeypatch.setattr(review, "due_queue_with_stats", fake_queue)
    monkeypatch.setattr(review, "days_until_next_exam", lambda u, c: None)
    monkeypatch.setattr("routes.learn_loop._pause_novice", lambda user_id: True)  # tutor at the hard level (A20)
    with patch("routes.learn_loop.require_self", return_value=None), \
         patch("routes.learn_loop.learning_loop_active", return_value=True):
        r = client.get(f"/api/learn/loop/review/summary?user_id={USER}&course_id={COURSE}")
    assert r.status_code == 200
    assert seen_kw["pause_novice"] is True
    assert r.json() == {
        "due": {"flashcard": 2, "check": 1}, "unservable": 2, "paused": 1,
        "budget_min": params.REVIEW_DAILY_BUDGET_MIN,
        "remaining_budget_s": params.REVIEW_DAILY_BUDGET_MIN * 60,
        "retention_target": params.FSRS_RETENTION_LARGE_SET,
    }
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_review.py -v -k "routes_404 or status or review_next or review_answer or review_summary or rate_limit or grade_review_called"`
Expected: 404s from FastAPI's own "Not Found" (`{"detail": "Not Found"}` ≠ the gate body) → FAIL; `test_rate_limit_applies_to_check_answers_only` → `StopIteration` (no `review_answer` handler yet); `test_grade_review_called_only_from_review_answer` → `AssertionError: set()`; `test_status_reports_active` FAILS only if PKG-07 did not add `/status`.

- [ ] **Step 3: Implement** in `routes/learn_loop.py`, in PKG-07's style (handler functions named `review_next`, `review_answer`, `review_summary`):
   - `from learning import review` (module import — tests patch attributes on it) and `from learning.params import REVIEW_DAILY_BUDGET_MIN`.
   - `ReviewAnswerBody(BaseModel)` with a `model_validator` enforcing rule 7b (check needs `answer` or `selected_option`; flashcard needs `rating` in 1..3) — raise `ValueError` so FastAPI answers 422. `kind: Literal["flashcard", "check"]`; `selected_option: str | None = None`, `reason: str | None = None`; no `model_pref` field (invariant 22). After the item loads: `mc_reason` without `selected_option`, or `free` without `answer` → `HTTPException(422)`.
   - `_load_check_item(item_id)` → `check_item_service.get_check_item(item_id)` (decrypted) or `None` → 404 `"review item not found"`; `_load_card(user_id, item_id)` → `table("flashcards").select(...)` with both `id` and `user_id` filters, 404 when empty.
   - `_review_node_id(user_id, item) -> str | None` — the student's `graph_nodes.id` for `(item.course_id, item.concept_key)`: a thin wrapper over PKG-07's `_node_for_item(user_id, item)` (Step 0 (N)); `None` → 404 `"review item not found"`. Never read a `node_id` from the body.
   - `_review_deps(user_id, course_id, session_id, request_id) -> SaplingDeps` — built the way PKG-07's `/check/answer` builds its fresh deps (Step 0 (D)): `SaplingDeps(user_id=…, course_id=course_id or None, supabase=None, request_id=…, session_id=<the review session id>, feature="loop_review", learning_loop=True)`; a thin wrapper so tests patch one name.
   - `_pause_novice(user_id) -> bool` = `ai_budget.check(user_id, "tutor", "novice").pause_novice` (A20; the read is cached per request by PKG-06b). If Step 0 (B) shows `check` is `async`, make `_pause_novice` async, `await` it, and change the two test patches of it (the `client` fixture, the summary test) to `async def` stubs.
   - `_retention(user_id, course_id, stats) = review.retention_target(stats["n_scheduled"], review.days_until_next_exam(user_id, course_id))`, stored into `loop_state["review"]["retention"]`.
   - `GET /status` (only if absent): `require_self`, gate, `{"active": True}`.
   - `GET /review/next`: `require_self` → gate → `sid, loop_state = review.load_or_create_review_session(...)` → `queue, stats = review.due_queue_with_stats(..., loop_state=loop_state, pause_novice=_pause_novice(user_id))` → for each kind present, `review.log_event("review.served", category="usage", user_id=..., request_id=current_request_id(), payload={...})` → `item = queue[0]` → `review.serve(item, check_item=..., card_row=..., loop_state=loop_state)` → `review._persist_loop_state(sid, loop_state)` → response. `now = datetime.now(timezone.utc)`. No rate limit (runs no model).
   - `POST /review/answer` (the handler function is named `review_answer`): no rate-limit dependency; after body validation, `if body.kind == "check": ai_budget.enforce_rate_limit_for(body.user_id)` (A20, inline — a flashcard rating runs no model and is never limited). `sid, loop_state = review.load_or_create_review_session(user_id, course_id, now)`; `body.session_id != sid` → 409 `"review session expired"` (a new UTC day began; the client re-polls `/review/next`). `retention = loop_state["review"].get("retention")` or recompute via `_retention`. Build the `ReviewItem` from the loaded row (kind, id, `node_id = _review_node_id(...)` for checks, course_id, question_hash, format, difficulty, cost_s, sr from `loop_state["sr"]`/derivation) and `await review.grade_review(..., answer=body.answer, selected_option=body.selected_option, reason=body.reason, deps=_review_deps(...))` for checks (flashcards: `card_row=`, no deps); 500 if `apply_graph_update` raised (let it propagate; the middleware turns it into `error.5xx`). This is the ONLY place `review.grade_review` is called.
   - `GET /review/summary`: counts per kind from the built queue + stats (`unservable`, `paused`), built with `pause_novice=_pause_novice(user_id)`. No rate limit.
   - Every handler passes `request_id=current_request_id()` from `services.request_context`.
   - Invariant 26 (binding Step 0 (I)): add `review_answer` — the handler's function name, or its route path if (I) shows the allow-list keys on paths — to the explicit-submission allow-list of `test_inv_26_evidence_only_from_explicit_submission` (PKG-07 names it `EVIDENCE_WRITERS`). Change nothing else in that test; the indirect write through `review.grade_review` is covered by `test_grade_review_called_only_from_review_answer`.

- [ ] **Step 4: Run tests, lint**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_review.py tests/test_learn_loop_routes.py tests/test_learn_routes.py tests/test_learning_ai_budget.py -q && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_22 or inv_26" && venv/bin/ruff check .`
Expected: all passed (`inv_22`, `inv_26` included); `All checks passed!`

- [ ] **Step 5: Commit**

```
git add backend/routes/learn_loop.py backend/tests/test_learning_review.py backend/tests/test_learning_loop_invariants.py
git commit -m "feat(learning-loop): PKG-12 — /review/next, /review/answer, /review/summary

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 6: Frontend — API client + "Due today" on Study

**Files:**
- Modify: `frontend/src/lib/api.ts` (after `deleteFlashcard`, :839–843), `frontend/src/components/screens/Study.tsx` (`FlashcardsMode` only), `docs/frontend-testids.md` (§Current inventory: new `### review` block)
- Create: `frontend/src/components/learn/DueQueue.tsx`

**Interfaces:**
- Produces: `getLoopStatus(userId)`, `getReviewNext(userId, courseId?)`, `answerReview(body)`, `getReviewSummary(userId, courseId?)`, `<DueQueue userId courseId? />`; testids `review-due-panel`, `review-budget`, `review-item`, `review-answer-input`, `review-submit`, `review-rate-1|2|3`, `review-flip`, `review-hint`, `review-empty`.

- [ ] **Step 1: `api.ts`** — add, in the existing style (`fetchJSON`, `JSON.stringify` body):

```ts
// Learning loop (PKG-12): daily review queue. 404 from any of these means the
// loop is off for this user (spec §7) — callers treat it as "inactive".
export interface ReviewItemPayload {
  kind: 'flashcard' | 'check';
  id: string;
  node_id?: string | null;
  concept_name?: string;
  format?: 'free' | 'mc_reason' | null;
  difficulty?: number | null;
  cost_s: number;
  sr: { stage: 'acquire' | 'relearn' | 'done'; correct: number; target: number };
  prompt?: string;
  options?: { letter: string; text: string }[] | null; // mc_reason only: stored options, correctness never marked (A22)
  topic?: string;
  front?: string;
  back?: string;
}
export interface ReviewNextResponse {
  item: ReviewItemPayload | null;
  remaining_budget_s: number;
  session_id: string;
  retention_target: number;
  due_total: number;
}
export interface ReviewAnswerResponse {
  correct: boolean | null;
  hint: string | null;
  next_due_at: string | null;
  rating: number | null;
  remaining_budget_s: number;
  sr: ReviewItemPayload['sr'];
  unavailable: boolean;
}
export const getLoopStatus = (userId: string) =>
  fetchJSON<{ active: boolean }>(`/api/learn/loop/status?user_id=${encodeURIComponent(userId)}`);
export const getReviewNext = (userId: string, courseId?: string) => {
  const params = new URLSearchParams({ user_id: userId });
  if (courseId) params.set('course_id', courseId);
  return fetchJSON<ReviewNextResponse>(`/api/learn/loop/review/next?${params}`);
};
export const answerReview = (body: {
  user_id: string; session_id: string; course_id?: string; kind: 'flashcard' | 'check';
  item_id: string; answer?: string; selected_option?: string; reason?: string; rating?: number;
}) => fetchJSON<ReviewAnswerResponse>('/api/learn/loop/review/answer', { method: 'POST', body: JSON.stringify(body) });
export const getReviewSummary = (userId: string, courseId?: string) => {
  const params = new URLSearchParams({ user_id: userId });
  if (courseId) params.set('course_id', courseId);
  return fetchJSON<{ due: { flashcard: number; check: number }; unservable: number; paused: number; budget_min: number; remaining_budget_s: number; retention_target: number }>(
    `/api/learn/loop/review/summary?${params}`,
  );
};
```

- [ ] **Step 2: `DueQueue.tsx`** — one component, no new dependencies, existing `btn`/`chip` classes and CSS variables only. State: `next: ReviewNextResponse | null`, `answer`, `choice`, `flipped`, `result: ReviewAnswerResponse | null`, `busy`. On mount and after each "Next", call `getReviewNext`. Render: `data-testid="review-due-panel"`; budget chip `review-budget` showing `Math.round(remaining_budget_s / 60)` min left; when `item` is null → `review-empty` "All caught up for today"; check item → prompt in `review-item`, `mc_reason` → one radio per served option (`{letter}. {text}`, stored order; the UI never infers which is correct) + one-sentence reason textarea, submitted as `selected_option` + `reason`, `free` → textarea `review-answer-input` submitted as `answer`, submit `review-submit`; flashcard → front, `review-flip` button reveals back, then `review-rate-1/2/3` (same labels as `ratingOptions` in `Study.tsx:101–105`); after answering show `review-hint` (correct/incorrect + hint, or "Grader unavailable — try again later" when `unavailable`) and a "Next" button. Errors → `console.error` + a muted line; never a thrown render.

- [ ] **Step 3: `Study.tsx`** — in `FlashcardsMode`: add `const [loopActive, setLoopActive] = React.useState(false);` and one effect `getLoopStatus(userId).then(r => setLoopActive(!!r.active)).catch(() => setLoopActive(false))` gated on `userId`; render `{loopActive && <DueQueue userId={userId} courseId={courseId !== "all" ? courseId : undefined} />}` as the first child of the column `div` at `:735`, above the filter bar. Import `DueQueue` from `"../learn/DueQueue"` and `getLoopStatus` from `@/lib/api`. Nothing else in the file changes.

- [ ] **Step 4: testids doc** — append a `### review` block to `docs/frontend-testids.md` §Current inventory listing the testids above with one-line meanings and "owner: `frontend/src/components/learn/DueQueue.tsx` (PKG-12; the launch Study surface, spec §11.3 — PKG-13 adds the budget banner and launch polish)".

- [ ] **Step 5: Type-check + E2E cycle** (request-path routes and a shared screen changed → the cycle applies)

Run: `cd frontend && npx tsc --noEmit && npx eslint src/components/learn/DueQueue.tsx src/components/screens/Study.tsx src/lib/api.ts`
Expected: clean.

Run (ONE flock; never split up/down):
```
flock /tmp/claude-$(id -u)/sapling-e2e-stack.lock sh -c '
  make e2e-up &&
  (cd frontend && npx playwright test e2e/study-semester.spec.ts e2e/study-recent-guides.spec.ts e2e/tutor.spec.ts e2e/quiz.spec.ts) &&
  (cd backend && venv/bin/python -m e2e_oracles);
  status=$?; make e2e-down; exit $status'
```
Expected: journeys pass (flag unset in the lane → Study renders the legacy cards UI; `getLoopStatus` 404s and is swallowed), oracles exit 0 (`logscan` sees no new WARN/ERROR: a 404 from `/status` is `error.4xx`, which the lane already tolerates for unauthenticated probes — if `logscan` flags it, the frontend must not call `/status` when `userId` is empty; fix that, never the `ALLOWLIST`).

Then, still under the same lock invocation pattern, one manual flag-on check: `LEARNING_LOOP_ENABLED=true make e2e-up`; set the seeded student's staff/QA toggle by SQL — `psql "<local stack DB URL>" -c "UPDATE user_settings SET learning_loop_beta = true WHERE user_id = '<seed user>'"` (spec §13 A14, A31: `learning_loop_beta` is in no settings API field, so a settings PATCH never writes it; `docs/local-supabase.md` names the local stack's DB URL — never print a value from an `.env` file); then, with the test-login cookie (`docs/e2e-exploration.md` §3 shows the cookie recipe), `GET /api/learn/loop/review/next?user_id=<seed user>` → 200 with a `session_id` and an `item` or `null`; check `psql` that a `sessions` row with `mode='review'` exists (this is the migration's live proof); `make e2e-down`. Record the outcome in the hand-off.

- [ ] **Step 6: Commit**

```
git add frontend/src/lib/api.ts frontend/src/components/learn/DueQueue.tsx frontend/src/components/screens/Study.tsx docs/frontend-testids.md
git commit -m "feat(learning-loop): PKG-12 — Due today queue on Study behind the loop flag

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 7: Hand-off + ledger

- [ ] **Step 1:** Write `docs/superpowers/plans/learning-loop/HANDOFF-12.md` from `HANDOFF-template.md`. "Verify commands" must be exactly these three lines:

```
cd backend && venv/bin/python -m pytest tests/test_learning_review.py -q                        → N passed (N ≥ 10)
grep -c "review/next" backend/routes/learn_loop.py                                               → ≥ 1
grep -c '"review\.served"\|"review\.graded"' backend/services/events_service.py                  → 2
```

Constants chosen: the three PKG-12 names with their † marks. Deviations: exam-beats-large-set precedence † (also A7); the derived SR stage † (with the flashcard mid-relearn lapse blind spot); the other-review-format fallback in rule 1 †; review persists `outcome.evidence` through one direct `apply_graph_update` (carrying `retention`) instead of `flush_pending`, which has no retention parameter (the same pattern as PKG-08's `/probe/answer`); any Step 3b/4 Step 3b post-hoc fixes. (The `sessions.mode` migration is spec §4 / A9, not a deviation.) Symbols added: the route shapes (incl. `ReviewAnswerBody.selected_option`/`reason`, the `options: [{letter, text}]` payload, `/review/summary`'s `paused`), the testids, and the Task 5 Step 0 bindings (I), (R), (D), (N), (B) — PKG-13 reads them. Known gaps: the hand-off name mapping table (§"Names from earlier hand-offs"), `DueQueue.tsx` is the launch Study surface; PKG-13 polishes it (budget banner, launch polish), no isomorph re-ask from reviews. Open questions: should `learner_state.sr_stage`/`flashcards.sr_stage` be stored (PKG-14); should review sessions get their own `sessions.mode` for analytics beyond `'review'`; whether `days_until_next_exam` should be cached per request.

- [ ] **Step 2:** Append the ledger row: `| 12 | review-surfaces | done | feat/learning-loop-12-review-surfaces | <sha> | 1 module | — | HANDOFF-12.md |`, plus `| NN | … | verified | … | PKG-12, <date>, <the State-of-the-world command> → <output> | … |` rows for 02, 03, 04, 05, 06b, 07, 11 (one row each, the first command of each block), plus the Deviations lines.

- [ ] **Step 3: Commit + PR**

```
git add docs/superpowers/plans/learning-loop/HANDOFF-12.md docs/superpowers/plans/learning-loop/LEDGER.md
git commit -m "docs(learning-loop): PKG-12 — hand-off and ledger

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
gh pr create --title "feat(learning): PKG-12 review-surfaces" --body-file - <<'EOF'
Learning loop series, package 15 of 17. Spec: docs/superpowers/specs/2026-09-26-learning-loop-design.md §3.2, §3.5, §5, §6, §7; §13 A16, A20, A22, A23.

- learning/review.py: due queue (flashcards + concept check items), DASH ordering, daily budget, retention target (default / large set / exam window via services/exam_proximity), successive relearning derived from streak/reps with per-session counters in sessions.loop_state
- check items keyed per A2; seen, revealed and the post-test reserve excluded, revealed-only fallback, else unservable (A23)
- check reviews graded through grade_answer (A16; stored mc_reason options served, option + reason answered, A22) → its one Evidence persisted unchanged with the retention target via apply_graph_update (inv 19; /review/answer joins the inv 26 allow-list); flashcard reviews through the PKG-11 FSRS path
- grader outage or daily grade cap → unavailable, nothing written for either outcome (inv 28); tutor hard level → novice concepts pause, review and flashcards keep working (A20)
- GET/POST /api/learn/loop/review/{next,answer,summary}, gated (404 when the loop is off); /review/answer carries the rate limit
- review.served / review.graded in the taxonomy + pin
- Study.tsx shows a "Due today" panel (DueQueue, the launch Study surface) only when /status says active; legacy cards UI byte-identical otherwise
- migration: sessions.mode CHECK widened to include 'review' (spec §4, A9)

Flag-off behaviour is unchanged: routes 404 before any read; review.py is imported only by routes/learn_loop.py.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
```

## Self-check loop (run after every task, and once more before the PR)

1. `cd backend && venv/bin/ruff check . && venv/bin/ruff format --check learning tests/test_learning_*.py`
2. `venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q`
3. `venv/bin/python -m pytest tests/ -q` (no `SAPLING_MODEL_MODE` exported)
4. Prompts/tool descriptions touched? **No** in this package → skip evals. (If you find yourself editing anything under `backend/agents/` or `services/ai_budget.py`/`services/decisions.py`, stop: scope creep — `grade_answer` is PKG-05's (seam PKG-05b, cap PKG-06b) and reviews call it unchanged. The only sanctioned edits outside `learning/`, `routes/learn_loop.py`, `services/events_service.py`, `params.py`, the invariant 26 allow-list in `tests/test_learning_loop_invariants.py` and the frontend files are the two conditional post-hoc fixes in Task 3 Step 3b / Task 4 Step 3b.)
5. Request-path agent or route touched? **Yes** (three routes, one shared screen) → the E2E cycle in Task 6 Step 5 applies; re-run it once more before the PR if any backend file changed after it last ran. Specs: `study-semester`, `study-recent-guides`, `tutor`, `quiz` (unchanged files; they prove flag-off is byte-identical). `learn-loop.spec.ts` stays a stub (PKG-13).
6. Scope check: `git diff --stat main...HEAD` — every path must be in this prompt's Files lists. Anything else: `git checkout main -- <path>` or record a Deviation.
7. Sync check: `grep -o "E2E_[A-Z_]*" backend/agents/function_handlers_e2e.py | sort -u` unchanged from `main`.

Green = all seven clean. Max 5 iterations per loop; then write a `BLOCKED` row in `LEDGER.md` with hypothesis, commands, outputs, and stop.

## Regression guard

- Pre-series suite count N₀ (from State of the world) must be unchanged except for the tests this package adds (and the one test each of Task 3 Step 3b / Task 4 Step 3b may add). Zero failures, zero new skips.
- Dependency suites stay green and unmodified except by the two sanctioned post-hoc steps: `tests/test_learning_fsrs.py` (PKG-02), `tests/test_learning_evidence_apply.py` + `tests/test_graph_service.py` (PKG-03), `tests/test_learning_check_items.py` (PKG-04), `tests/test_learning_check_tool.py` (PKG-05), `tests/test_learning_decisions.py` (PKG-05b), `tests/test_learning_ai_budget.py` (PKG-06b), `tests/test_learn_loop_routes.py` (PKG-07), `tests/test_learning_flashcards_fsrs.py` + `tests/test_quiz_scoring_e.py` (PKG-11).
- Pre-series suites this package touches: `tests/test_event_capture_seams.py` (pin edited, all else green), `tests/test_flashcards_routes.py`, `tests/test_achievement_dispatch.py`, `tests/test_learn_routes.py`, `tests/test_model_mode_seam.py` — green.
- With `LEARNING_LOOP_ENABLED` unset (build phase, spec §7): `/api/learn/loop/review/*` and `/status` 404 with the spec §7 body; `routes/flashcards.py`, `routes/quiz.py`, `routes/learn.py` behaviour unchanged; `Study.tsx` renders the legacy `FlashcardsMode` (the `study-*` journeys pass unchanged).
- `tests/evals/*` cassettes and `baselines.json` untouched (`git diff --stat main...HEAD -- backend/tests/evals` is empty).

## Acceptance criteria (the next session pastes these)

1. `cd backend && venv/bin/python -m pytest tests/test_learning_review.py -q` → `N passed` (N ≥ 10)
2. `grep -c "review/next" backend/routes/learn_loop.py` → ≥ 1
3. `grep -c '"review\.served"\|"review\.graded"' backend/services/events_service.py` → `2`
4. `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_19 or inv_01 or inv_05 or inv_07 or inv_08 or inv_22 or inv_26"` → `7 passed`
5. `cd backend && venv/bin/python -m pytest tests/ -q` → zero failures; `venv/bin/ruff check .` → `All checks passed!`
6. `ls backend/db/migrations/*_learning_sessions_mode_review.sql` → 1 file
7. `grep -cE "^(async )?def (due_queue|due_queue_with_stats|serve|grade_review|retention_target|sr_stage_for_concept|sr_stage_for_flashcard|review_session_id|load_or_create_review_session|summary)\(" backend/learning/review.py` → `10`
8. `grep -c "Agent(" backend/learning/review.py` → `0`; `grep -c "from agents.tools.check import" backend/learning/review.py` → `1`; `grep -cE "flush_pending\(|Evidence\(" backend/learning/review.py` → `0` (the evidence is `grade_answer`'s, persisted once, unchanged)
9. `cd backend && venv/bin/python -m pytest tests/test_learning_review.py -q -k "excludes or pauses_novice or mc_reason or unavailable or rate_limit or grade_review_called"` → all passed (A23 exclusion + fallback, A20 novice pause, A22 stored options, invariant 28, the rate limit, the invariant 26 extension)
10. `cd frontend && npx tsc --noEmit` → clean; `grep -c "getLoopStatus\|DueQueue" frontend/src/components/screens/Study.tsx` → ≥ 2
11. `git diff --stat main...HEAD` lists only: `backend/learning/review.py`, `backend/learning/params.py`, `backend/routes/learn_loop.py`, `backend/services/events_service.py`, `backend/db/migrations/*_learning_sessions_mode_review.sql`, `backend/tests/test_learning_review.py`, `backend/tests/test_learning_loop_invariants.py`, `backend/tests/test_event_capture_seams.py`, `frontend/src/lib/api.ts`, `frontend/src/components/learn/DueQueue.tsx`, `frontend/src/components/screens/Study.tsx`, `docs/frontend-testids.md`, `docs/superpowers/plans/learning-loop/{HANDOFF-12.md,LEDGER.md}` — plus, only if the conditional steps ran: `backend/services/graph_service.py` + `backend/tests/test_learning_evidence_apply.py` + `HANDOFF-03.md`, or `backend/services/flashcard_fsrs.py` + `backend/routes/flashcards.py` + `backend/tests/test_learning_flashcards_fsrs.py` + `HANDOFF-11.md`.
12. `LEDGER.md` has row `12 | review-surfaces | done | …` and `verified` rows for 02, 03, 04, 05, 06b, 07, 11.

## Hand-off

`docs/superpowers/plans/learning-loop/HANDOFF-12.md` per the template; the Verify commands block is fixed above (Task 7). Headings, all kept: What changed · Symbols added · Constants chosen · Deviations from spec · Known gaps · Verify commands · Open questions for the series owner · Post-hoc changes. PKG-13 reads §Symbols added for the route shapes (incl. `selected_option`/`reason`, `options: [{letter, text}]`, `paused`) and testids, and polishes `DueQueue` as the launch Study surface; PKG-14 reads §Open questions for the `sr_stage` column decision.

## Do not

- Do not construct an `Agent(`, import `agents/grader.py`, or call `services/decisions.py` from `learning/review.py`; grade only through `grade_answer` in `agents/tools/check.py` (A16, inv 19). Do not build an `Evidence`, recompute a weight, or call `flush_pending` in review: persist `outcome.evidence` unchanged with ONE `apply_graph_update` that carries `retention`. Do not add an `AgentTask`, a prompt, a function-mode handler, or an eval dataset.
- Do not write evidence, SR progress or budget for an `unavailable` grade — not for a correct attempt, not for a wrong one (invariant 28). Do not gate a review route on the tutor budget level; the only budget reads are `pause_novice` and the rate limit on `/review/answer` (A20).
- Do not write `graph_nodes`, `graph_edges`, `node_mastery_events`, or `learner_state` anywhere but `apply_graph_update` (inv 1). Do not compute a concept's next due date in `review.py`; read it back.
- Do not add an `sr_stage` column or any column to `learner_state`/`flashcards`; the only migration is the `sessions.mode` widening in §Spec/Schema. Migrations: UTC-timestamp prefix, `_learning_` infix, append-only, never edited after creation.
- Do not import `routes.*` from `learning/`. Do not put the review routes anywhere but `routes/learn_loop.py`. Do not call the gate inside `services/chat_stream.py`.
- Do not send `reference_answer`, `rubric_json`, `common_wrong_json`, `correct_option`, `canonical_answer`, an option's `wrong_key`, or a marked-correct option to the client; serve `mc_reason` options only as the stored `{letter, text}` pairs, never rebuilt from the reference (A22). Do not serve a concept's post-test reserve or a revealed item (A23). Do not take a `node_id` from the client. Do not filter or `eq.` on an encrypted column; `question_hash` is the lookup key.
- All Supabase access through `db/connection.py::table()`; no `httpx`, no `supabase` import. Every `table("...")` read in `review.py` names its user (`user_id` filter).
- No numeric literals in loop code; every number is a `learning/params.py` name (the three new ones are in §Named constants). No second format → channel map: use PKG-05's `CHANNEL_FOR_FORMAT`. No `lru_cache` in this package.
- Do not skip, xfail, or delete any pre-existing test. Do not hand-edit eval cassettes or baselines. Do not touch `frontend/e2e/learn-loop.spec.ts` or `LoopLearn.tsx` (PKG-13).
- Do not run E2E stack commands outside one `flock` invocation; never split up/down into separate flocks. Logscan `ALLOWLIST` in `backend/e2e_oracles/logscan.py` stays `()`.
- End every commit with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; end the PR body with the Claude Code attribution line.

## If you get stuck

1. Re-read §Spec and the spec file's §3.2/§5/§6/§7 before guessing; then the relevant `HANDOFF-NN.md` §Symbols added — most "stuck" here is a name mismatch covered by §"Names from earlier hand-offs".
2. Three failed iterations on one task → append a `BLOCKED` row to `LEDGER.md` (hypothesis, commands run, outputs), commit what is green, open the PR as draft, stop.
3. Never widen scope to unblock. Never disable a test to unblock. Never bypass `grade_answer` to unblock a review test — patch `learning.review.grade_answer` in the test instead.
4. Ambiguity → choose the option closest to the spec, mark it `†` in the hand-off, continue.
