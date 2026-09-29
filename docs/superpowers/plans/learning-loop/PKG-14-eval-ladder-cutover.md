# PKG-14 eval-ladder-cutover — Learning Loop series (17 of 17)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> You are a fresh session. Nothing outside this file, `docs/superpowers/plans/learning-loop/LEDGER.md`, the `HANDOFF-NN.md` files it names, and the files this prompt lists is known to you. Do not infer intent from chat history you do not have. Do not read the whole research corpus; read the sections named below.

## Package id + goal

**PKG-14 `eval-ladder-cutover`.** The last package. It is TWO pull requests from ONE prompt:

- **Half A — evaluation ladder** (branch `feat/learning-loop-14a-eval-ladder`, PR title `feat(learning): PKG-14a eval ladder`). After half A: the nightly ZPD metrics script exists and is idempotent, and it also reports cost per session (or per user-day) and per band, the tier mix, cap hits and the `grader_backend` mix (spec §10); admins can read the three headline KPIs and the two gates at `GET /api/admin/analytics/learning-loop`; the tutor asks for a perceived-difficulty rating every `ZPD_RATING_EVERY_N_CHECKS` checks; a tool-removed post-test endpoint serves each concept's post-test reserve item (never a seen or revealed one, A23), grades it through `grade_answer` (A16) with the ceiling forced to `H0`; within-student A/B arms are plumbed (`user_settings.loop_arm` + `policy.variant_for`; arm sessions pass `arm_session=True` to `ai_budget.check`, A20); the cutover ADR (`docs/decisions/<next>-learning-loop-cutover.md`, 0028 expected — PKG-05b's decision-seam ADR took 0027) records the design, the default-on decision and its two-phase flag, the evidence-only write rule, the ladder, the cost guardrails and the launch plan; the offline eval suite covers leakage and sycophancy per tier slot and `run_all.py` runs every series dataset. Everything is still dark behind the build-phase gate (spec §7).
- **Half B — cutover = launch** (branch `feat/learning-loop-14b-cutover`, PR title `feat(learning): PKG-14b cutover`). After half B: no code path can move a mastery score except graded evidence through `apply_graph_update`; the legacy tutor mastery tool, the per-item quiz deltas, the legacy tier cuts, the learning-style onboarding step and the three always-empty session-summary lists are gone; the loop is the default learning system for every student with no opt-in: the env flag defaults on under the exact spec §7 parse and is the only gate (a kill switch), and the per-user `learning_loop_beta` column is no longer read (the column stays; the ADR notes it as a retired staff/QA toggle); the legacy `chat_tutor` agents stay, minus the mastery tool, as the kill-switch path, which is now cost-bounded (`ai_budget.check` + the rate limit); both E2E lanes (default and kill switch, spec §11.4) are green; the owner-run launch runbook (spec §11.7) is written into HANDOFF-14; `tests/test_learning_loop_invariants.py::test_inv_21_no_legacy_mastery_writers` proves the evidence-only rule.

**Half B is the launch: it makes the loop the default for every student (spec §13 A14, spec §11). It starts only after every item of the spec §11.1 launch gate holds: (1) half A merged, `LEDGER.md` row 14 reads `done (half A)`, and the latest row of each of 00–13, 05b, 06b is `done`, `verified` or `reopened` (README "Ledger reading"); (2) CI green on `main`, including every test in `frontend/e2e/learn-loop.spec.ts` (loop journey, resume, budget cap) and `python -m e2e_oracles`; the no-check-items state is covered by PKG-13's vitest and PKG-08's route test; (3) the staging check-items backfill (dry run first, `--project <staging ref>`) leaves the smoke course with `coverage` N > 0, then the staging smoke under the build-phase config (env `true`; a staff/QA account with `learning_loop_beta` set by SQL): probe → plan → teach → check (the pose appears and `/check/answer` grades it) → close completes; (3b) the kill-switch mechanics are drilled on staging (env `false` + redeploy → `/status` 404, legacy Learn screen, no `review-due-panel`, an upload drafts no items; restored after); (4) cost guardrails implemented and verified: A15 routing (`policy.model_tier` + the three tier slots; loop routes ignore `model_pref`, invariant 22; each tier passed the per-tier evals), A18 limits (`LOOP_LIMITS` 4/3/40_000 and per-run `max_tokens`), A20 cost guard (`services/ai_budget.py` caps and degradation ladder; invariants 23 and 28; the PKG-13 budget-cap journey), A21 usage observability (the staging smoke's `llm_usage` rows carry tier slot names in `task` and non-null `cached_tokens`/`thinking_tokens`); the owner has approved the projected cost against the ≈ $0.36/student-month target, chosen the production `PLATFORM_DAILY_BUDGET_USD`, and confirmed on staging that an `ai.budget_capped{scope: platform}` alert reaches them; (5) launch UI readiness (spec §11.3) is merged; (6) the owner confirms production is pinned `LEARNING_LOOP_ENABLED=false` (spec §11.7 step 1) and that they have read spec §11.7's opening paragraph — the first `make promote` after the half B merge launches half B's ungated changes for every production student whatever the pin says, and §11.7 "Rollback" is the only way back from them; (7) the series owner writes an explicit go-ahead in the session.** There is no beta-cohort waiting period. When you reach "Half B — STOP gate" below, stop, post the question, and do not continue in the same session unless the confirmation is given. This is not a formality: the cutover deletes the legacy mastery path, and merging half B launches staging. The session never launches production: that is the owner-run runbook (Task B9).

Depends on (spec §14): **all of 00–13, 05b, 06b** (code). The series runs strictly one package at a time in the §14 order (… 12, 13, **14**); PKG-14 is last — half A first, half B only after the §11.1 gate. PKG-15 (Jev backend, post-series) is independent of this package.

## Read before you start (in this order)

0. `docs/superpowers/specs/2026-09-26-learning-loop-design.md` **§13 Amendments log** — in force; where this file and §13 disagree, §13 wins. Re-read it before Task 1. A31 binds half B: `learning_loop_beta` is in no settings API field, so retiring it touches only the gate.
1. Same spec: §3.5–§3.6 (cost/routing/decision constants — `LOOP_MODEL_TIER`, the budget table, the degradation ladder, the `arm_session` exemption), §7 (two-phase gate — the build-phase code and the exact post-launch parse half B writes), §8 (invariants 13–29 — which numbers exist and who owns them), §14 (order and dependencies).
2. `docs/superpowers/plans/learning-loop/LEDGER.md` — a package's state is its LATEST row (README "Ledger reading"); refuse to start if any earlier package's latest row is `blocked` or `in-progress`. The latest rows of 00–13, 05b and 06b must be `done`, `verified` or `reopened`.
3. `CLAUDE.md` §Conventions and §Gotchas — the standing rules the "Do not" list below repeats.
4. `docs/superpowers/specs/2026-09-26-learning-loop-design.md` §10 (evaluation ladder — every KPI and gate below is named there; the cost/tier/cap report; per-tier evals), §11 in full (cutover = launch: §11.1 the launch gate, §11.2–§11.6 what half B changes, keeps and records, §11.7 the owner-run launch runbook), §3.4 (`ZPD_RATING_EVERY_N_CHECKS`), §4 (the PKG-14 `loop_arm` DDL and the `learner_state` derived columns `htc_k`/`unassisted_next`/`assist_gap`/`in_zone`), §6 (`zpd.step` — incl. `tier`, `grader_backend`, `variant` — `zpd.rating` and `ai.budget_capped` payloads), §8 (invariants 1, 5, 11, 12, 13b, 21, 26), §13 rows **A14** (half B = launch), A15, A18 (launch-gate evidence), A20, A21, A23 (post-test reserve, seen/revealed, backfill), A24 (ADR numbering), A26.
5. `docs/research/learning-loop/AI tutor learning loop research.md` §"Measure learning with tool-removed, delayed checks, not in-session accuracy" (lines ~139–143): the four rungs, why rung 3 is tool-removed and ≥ 2 days delayed, why within-student randomization.
6. `docs/research/learning-loop/ZPD lever tradeoffs and upgrades.md` §"Measure in-ZPD-ness as hints-to-criterion and unassisted next-opportunity success" (lines ~103–107) and §"Sapling ZPD policy spec" — only the `LOG` block (lines ~213–226: `zpd.rating` cadence, the nightly derived quantities and the `in_zone` rule) and the KPI paragraph after it (lines ~229–233: the three headline KPIs and the three gates).
7. Hand-offs you depend on: `HANDOFF-03.md` (how `learner_state` is read/written; what `p` a node with no `learner_state` row starts from), `HANDOFF-04.md` (`checks.select_item`, `checks.posttest_reserve_hash`, `check_item_service.list_items(course_id, concept_key, …)`, the A22 option fields), `HANDOFF-05.md` (`grade_answer`'s canonical signature and `GradeOutcome`, `CheckAnswer`, `CHANNEL_FOR_FORMAT`, where `flush_pending` lives, `E2E_GRADER_CORRECT_TOKEN`), `HANDOFF-05b.md` (the `decisions` eval dataset; the decision-seam ADR number), `HANDOFF-06.md` (wire form of `ceiling`/`max_rung_used` in `zpd.step`, where `GATE_INDEPENDENT_MIN_S` is consumed, `emit_zpd_step`'s `tier`/`grader_backend` keywords), `HANDOFF-06b.md` (`ai_budget.check` and its `arm_session` contract, `AIBudgetExceeded`, `enforce_rate_limit`, the `llm_usage` `cached_tokens`/`thinking_tokens` columns, the `ai.budget_capped` payload), `HANDOFF-07.md` (loop route layout, the check-answer handler and how its `done` event data is built, `seen_hashes`/`revealed_hashes`, the `arm_session=` call sites, the inv 26 allow-list, per-tier eval fixtures that exist), `HANDOFF-09.md` (which events carry a `session_id`), `HANDOFF-11.md` (quiz evidence: one `Evidence` per item or per quiz; channel used. PKG-11 ran early, before spec §13 A14 existed — spec §14: its "## For PKG-14 (cutover)" section says "the seeded student is opted out" and "the seeded student moves to the loop path"; read them per its A14 Post-hoc changes line — the loop is dark during the build, and at launch the quiz becomes evidence-only for everyone (§Behaviour B.2). It does not list `quiz-integration.spec.ts`; §Behaviour B.9 owns that pin), `HANDOFF-12.md` (how review serves `mc_reason` options), `HANDOFF-13.md` (which seeded users carry the staff/QA toggle — `rich-user-loop`, `rich-user-capped`; the `LEARNING_LOOP_ENABLED` export in `scripts/e2e-up.sh`/`e2e.yml`/`explore.sh`; `LoopLearn.tsx` stream consumer; the `learn-loop.spec.ts` tests).
8. Code you will modify or mirror, with anchors true today:
   - `backend/services/events_service.py:97` (`EVENT_TAXONOMY`; `zpd.rating` is already in it from PKG-06 — verify with `grep -n '"zpd.rating"'`).
   - `backend/routes/admin_analytics.py:36–37` (`_PAGE`/`_SCAN_CAP`), `:185–218` (`_scan_range` — reuse it), `:280–311` (`usage_summary` — the endpoint shape to mirror: `require_admin(request)`, `Cache-Control: private`, `truncated`), `:50–55` (`Range`).
   - `backend/tests/test_admin_analytics_routes.py:63–110` (`_FakeTable` + `seeded` fixture — the mocked-table style for KPI tests).
   - `backend/scripts/backfill_document_chunks.py:40–63` (script preamble: argparse, `load_dotenv(BASE / ".env.staging")`, `sys.path.insert`, `page_all`), `:86–137` (`main(argv)`, `--dry-run`, counts, `sys.exit(1)` on failure).
   - `backend/db/connection.py:172` (`page_all(handle, columns, *, filters, order, page)` — `order` must be a total order).
   - `backend/routes/learn_loop.py` (PKG-07..13 — the route module you extend; the check-answer handler is the only loop-chat evidence path, A16: find it and the flush with `grep -n "check/answer\|flush_pending" backend/routes/learn_loop.py`; the `arm_session=` call sites with `grep -n arm_session backend/routes/learn_loop.py`).
   - `backend/agents/tools/check.py` (`grade_answer`, `CheckAnswer`, `GradeOutcome`, `CHANNEL_FOR_FORMAT` — PKG-05/05b), `backend/learning/checks.py` (`select_item`, `posttest_reserve_hash` — PKG-04), `backend/learning/loop_state_store.py` (`seen_hashes`, `revealed_hashes` — PKG-07), `backend/services/check_item_service.py` (`list_items`), `backend/services/graph_service.py::_normalize_concept` (node → `concept_key`, A2).
   - `backend/services/ai_budget.py` (`check`, `AIBudgetExceeded`, `enforce_rate_limit` — PKG-06b), `backend/db/migrations/0035_observability.sql` (`llm_usage`: `user_id`, `request_id`, `task`, `cost_usd`, `created_at`; `cached_tokens`/`thinking_tokens` from PKG-06b).
   - `backend/learning/policy.py`, `backend/learning/learner_state.py`, `backend/learning/params.py` (PKG-06/03/01).
   - `backend/tests/evals/run_all.py:34–41` (`DATASETS`), `backend/tests/evals/loop_tutor.py` (PKG-07; per-tier-slot cassettes and baselines), `backend/tests/evals/decisions.py` (PKG-05b), `backend/tests/evals/README.md` (record/replay/baseline procedure).
   - `docs/decisions/0026-newsletter-email-plaintext.md` — the ADR format (`Status/Date/Relates to/Supersedes`, `Context`, `Options considered`, `Decision`, `Consequences`). PKG-05b's decision-seam ADR took the next number (0027 expected); your cutover ADR takes the one after it (**0028** expected — `ls docs/decisions | tail -1`, then +1). Below, "the cutover ADR" means `docs/decisions/<next>-learning-loop-cutover.md`.
   - Half B only: `backend/agents/chat_tutor.py:70–101` (`_SHARED_PREAMBLE`; the `update_mastery_tool` paragraph is `:84–91`), `:103–124` (mode prompts — unchanged in half B), `:152–167` (`_build_tools`); `backend/learning/gate.py` (PKG-00: env AND `learning_loop_beta`, `table` import, docstring), `backend/tests/test_learning_gate.py` (PKG-00's env-on/env-off tests), `backend/tests/conftest.py:32–48` (`pytest_configure` marker registration; the autouse fixtures), `backend/main.py` (the `learn_loop` mount comment), `backend/.env.local.example`, `backend/routes/learn.py` (the legacy model-calling handlers `start_session`, `/start-session/stream`, `/chat`, `/chat/stream`, `/action` — the kill-switch path), `scripts/e2e-up.sh`, `scripts/explore.sh`, `.github/workflows/e2e.yml` (the `LEARNING_LOOP_ENABLED` export PKG-13 added), `frontend/e2e/learn-loop.spec.ts`, `tutor.spec.ts`, `streaming.spec.ts`, `gallery-shots.spec.ts`, `quiz-integration.spec.ts:50`, `:130`, `:286`, `:292`, `quiz-journeys.spec.ts:463`, `onboarding.spec.ts`, `study-*.spec.ts`, `frontend/src/lib/graph/nodeStyle.ts:111–121` (+ its table test), `frontend/e2e/graph.spec.ts:54–59` (`tierFor`), `backend/tests/test_learning_seed_loop_user.py` (PKG-13's `test_legacy_users_are_not_opted_in`); `backend/agents/tools/graph.py:34–38` (`TUTOR_EVENT_TYPES`), `:50–100` (`ConceptMasteryUpdate`, `MasteryUpdateInput`), `:156–218` (`update_mastery_tool`); `backend/services/quiz_config.py:102–114`; `backend/routes/quiz.py:2531–2585` (delta block + `apply_graph_update` call), `:2598–2599` (`quiz_attempts.mastery_before/after` — the columns STAY), `:2048` and `:2710` (`mastery_delta` on the wire); `backend/config.py:113–141` (`MASTERY_*_MIN`, `get_mastery_tier`, `is_mastered`, `is_weak`); `backend/routes/learn.py:1145–1152` and `:1206–1212` (the always-empty lists); `backend/tests/test_mastery_tier_unification.py:84–130` (the frontend mirror pin); `frontend/src/components/screens/Learn.tsx:86–93` (`tierForScore`); `frontend/e2e/support/quiz.ts:52–60` (`MASTERY_PER_CORRECT/WRONG`, `masteryAfter`) and `frontend/e2e/quiz.spec.ts:56–57`, `:150–152`; `backend/tests/evals/chat_tutor.py:152–208` (`MASTERY_DELTA_MIN/MAX`, `_mastery_updates`, `MasteryUpdateEmittedEvaluator`), `:421–456` (offline graph-write stub), `:562–576` (`make_dataset`); `backend/routes/onboarding.py:86`, `backend/routes/profile.py:42`, `backend/models/__init__.py:312`, `frontend/src/components/screens/Onboarding.tsx:134`, `:140`, `:151`, `:241–244`, `frontend/src/lib/api.ts:999`; `frontend/src/components/chat/SessionSummary.tsx:13`, `:62–110`.

## State of the world

Every row below is a dependency's canonical verify line — each package's hand-off "Verify commands" block, verbatim (the 04, 05, 05b, 06, 06b, 07, 09 and 13 blocks are the ones amended on 2026-09-26). Run all of them before half A Task 1. Create the venv first if `backend/venv` is missing: `cd backend && python -m venv venv && venv/bin/pip install -r requirements.txt`.

| pkg | command | expected |
|---|---|---|
| 00 | `cd backend && venv/bin/python -m pytest tests/test_learning_gate.py -q` | `13 passed` |
| 00 | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q` | `4 passed, 8 skipped (later packages raise the passed count)` — with 01–13, 05b, 06b merged expect the passed count to be ≥ 27 now (inv_01–inv_17, 19, 22–29; `inv_10` may still skip if no `lru_cache` exists under `learning/`); zero failures |
| 00 | `cd backend && venv/bin/python -m pytest tests/test_learning_deps.py tests/test_learning_settings_flag.py tests/test_learning_loop_beta_migration.py -q` | all passed |
| 00 | `grep -n "^LEARNING_LOOP_ENABLED" backend/config.py` | 1 hit |
| 00 | `ls backend/db/migrations/*_learning_loop_beta.sql` | 1 file |
| 01 | `cd backend && venv/bin/python -m pytest tests/test_learning_bkt.py -q` | N passed (N ≥ 20) |
| 01 | `grep -cE "^def (update\|decayed_p\|propagate_prereq\|band\|tier_for)\(" backend/learning/bkt.py` | 5 |
| 01 | `grep -cE "^[A-Z0-9_]+ = " backend/learning/params.py` | ≥ 40 |
| 01 | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k inv_03` | 1 passed |
| 02 | `cd backend && venv/bin/python -m pytest tests/test_learning_fsrs.py -q` | N passed (N ≥ 15) |
| 02 | `grep -cE "^def (retrievability\|interval\|next_state\|rating_for\|order_due\|budget_select)\(" backend/learning/fsrs.py` | 6 |
| 02 | `cd backend && venv/bin/python -c "from learning.params import FSRS_W; assert len(FSRS_W)==21; print('ok')"` | ok |
| 03 | `cd backend && venv/bin/python -m pytest tests/test_learning_evidence_apply.py tests/test_graph_service.py -q` | all passed |
| 03 | `ls backend/db/migrations/*_learning_learner_state.sql` | 1 file |
| 03 | `grep -c '"evidence"' backend/services/graph_service.py` | ≥ 1 |
| 03 | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k inv_01` | 1 passed |
| 04 | `cd backend && venv/bin/python -m pytest tests/test_learning_check_items.py -q` | N passed (N ≥ 14) |
| 04 | `ls backend/db/migrations/*_learning_check_items.sql` | 1 file |
| 04 | `grep -c '"check_items"' backend/agents/_providers.py backend/agents/function_handlers_e2e.py` | ≥ 1 each |
| 04 | `grep -ohE "options_json\|correct_option\|answer_kind\|canonical_answer\|canonical_verified\|stepwise" backend/db/migrations/*_learning_check_items.sql \| sort -u \| wc -l` | 6 |
| 04 | `grep -c -- "--all-courses" backend/scripts/backfill_check_items.py` | ≥ 1 |
| 04 | `cd backend && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/check_items.py` | every evaluator ≥ baseline |
| 04 | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_06 or inv_09 or inv_12"` | 3 passed |
| 05 | `cd backend && venv/bin/python -m pytest tests/test_learning_check_tool.py -q` | N passed (N ≥ 16) |
| 05 | `grep -c '"grader"' backend/agents/_providers.py backend/agents/function_handlers_e2e.py` | ≥ 1 each |
| 05 | `grep -c '"grader_second"' backend/agents/_providers.py backend/agents/function_handlers_e2e.py` | ≥ 1 each |
| 05 | `grep -c "^async def grade_answer" backend/agents/tools/check.py` | 1 |
| 05 | `ls backend/db/migrations/*_learning_grader_backend.sql` | 1 file |
| 05 | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_14 or inv_28"` | 2 passed |
| 05 | `cd backend && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/grader.py` | every evaluator ≥ baseline |
| 05b | `cd backend && venv/bin/python -m pytest tests/test_learning_decisions.py -q` | N passed (N ≥ 12) |
| 05b | `grep -c '"decision"' backend/agents/_providers.py backend/agents/function_handlers_e2e.py` | ≥ 1 each |
| 05b | `grep -c '"decision\.' backend/services/events_service.py` | 3 |
| 05b | `grep -rlE "^[[:space:]]*(import\|from)[[:space:]]+typesafe" backend --include=*.py --exclude-dir=venv --exclude-dir=tests \| wc -l` | 0 |
| 05b | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_24 or inv_25"` | 2 passed |
| 05b | `cd backend && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/decisions.py` | every evaluator ≥ baseline |
| 05b | `ls docs/decisions/*decision-seam*.md` | 1 file |
| 06 | `cd backend && venv/bin/python -m pytest tests/test_learning_zpd_policy.py -q` | N passed (N ≥ 35) |
| 06 | `grep -cE "^def (ceiling\|band_control\|evidence_for_rung\|wheelspin\|model_tier\|context_policy)\(" backend/learning/policy.py` | 6 |
| 06 | `grep -cE "^def (check_pose\|deterministic_content)\(" backend/learning/ladder.py` | 2 |
| 06 | `grep -c '"zpd\.' backend/services/events_service.py` | 6 |
| 06 | `ls backend/db/migrations/*_learning_session_loop_state.sql` | 1 file |
| 06 | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_02 or inv_04 or inv_05"` | 3 passed |
| 06b | `cd backend && venv/bin/python -m pytest tests/test_learning_ai_budget.py -q` | N passed (N ≥ 15) |
| 06b | `ls backend/db/migrations/*_learning_llm_usage_tokens.sql` | 1 file |
| 06b | `grep -cE "^(async )?def (check\|rate_limited\|enforce_rate_limit)\(" backend/services/ai_budget.py` | 3 |
| 06b | `grep -c '"ai\.budget_capped"' backend/services/events_service.py` | 1 |
| 06b | `grep -c "cached_tokens" backend/agents/usage.py` | ≥ 1 |
| 06b | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_23 or inv_28"` | 2 passed |
| 07 | `cd backend && venv/bin/python -m pytest tests/test_learn_loop_routes.py -q` | N passed (N ≥ 25) |
| 07 | `grep -c "learn_loop" backend/main.py` | ≥ 1 |
| 07 | `grep -c '"loop_tutor"' backend/agents/_providers.py backend/agents/function_handlers_e2e.py` | ≥ 1 each |
| 07 | `grep -ohE '"loop_tutor(_lite\|_deep)?"' backend/agents/_providers.py \| sort -u \| wc -l` | 3 |
| 07 | `grep -c "learning_loop" backend/agents/chat_tutor.py` | ≥ 1 |
| 07 | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_15 or inv_22 or inv_23 or inv_26 or inv_27 or inv_29"` | 6 passed |
| 07 | `cd backend && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/loop_tutor.py` | every evaluator ≥ baseline for every tier slot |
| 08 | `cd backend && venv/bin/python -m pytest tests/test_learning_probe_planner.py -q` | N passed (N ≥ 15) |
| 08 | `grep -cE "^def (next_probe_item\|probe_done\|novice_floor)\(" backend/learning/probe.py` | 3 |
| 08 | `grep -cE "^def (outer_fringe\|plan)\(" backend/learning/planner.py` | 2 |
| 08 | `grep -c '"learn\.probe_done"\|"learn\.plan_approved"' backend/services/events_service.py` | 2 |
| 09 | `cd backend && venv/bin/python -m pytest tests/test_learning_close_brief.py -q` | N passed (N ≥ 14) |
| 09 | `ls backend/db/migrations/*_learning_session_close.sql` | 1 file |
| 09 | `grep -c "loop_brief" backend/db/migrations/*_learning_session_close.sql` | ≥ 1 |
| 09 | `grep -c "LOOP_HISTORY_TRIM_BLOCK" backend/routes/learn_loop.py` | ≥ 1 |
| 09 | `grep -c '"learn\.session_closed"' backend/services/events_service.py` | 1 |
| 10 | `cd backend && venv/bin/python -m pytest tests/test_learning_misconceptions.py -q` | N passed (N ≥ 10) |
| 10 | `ls backend/db/migrations/*_learning_misconceptions.sql` | 1 file |
| 10 | `grep -c "HAVING count(DISTINCT m.user_id) >= 5" backend/db/migrations/*_learning_misconceptions.sql` | 1 |
| 10 | `grep -cE "^def (record\|slip_or_misconception\|rollup)\(" backend/learning/misconceptions.py` | 3 |
| 11 | `cd backend && venv/bin/python -m pytest tests/test_learning_flashcards_fsrs.py tests/test_quiz_scoring_e.py -q` | all passed |
| 11 | `ls backend/db/migrations/*_learning_flashcards_fsrs.sql` | 1 file |
| 11 | `grep -c "learning_loop_active" backend/routes/quiz.py backend/routes/flashcards.py` | ≥ 1 each |
| 12 | `cd backend && venv/bin/python -m pytest tests/test_learning_review.py -q` | N passed (N ≥ 10) |
| 12 | `grep -c "review/next" backend/routes/learn_loop.py` | ≥ 1 |
| 12 | `grep -c '"review\.served"\|"review\.graded"' backend/services/events_service.py` | 2 |
| 13 | `(under the stack lock) make e2e-up && (cd frontend && npx playwright test e2e/learn-loop.spec.ts) && (cd backend && venv/bin/python -m e2e_oracles); make e2e-down` | every learn-loop.spec.ts test passed (loop journey, resume, budget cap, legacy-user split), oracles exit 0 |
| 13 | `cd frontend && npx tsc --noEmit` | clean |
| 13 | `cd frontend && npx vitest run src/components/learn` | all passed |
| 13 | `grep -c "E2E_LOOP_" backend/agents/function_handlers_e2e.py` | ≥ 3 |
| 13 | `grep -c '"/sessions"' backend/routes/learn_loop.py` | ≥ 1 |
| — | `cd backend && venv/bin/python -m pytest tests/ -q -x` | `… passed` (note the count N₀; it is this package's regression baseline) |
| — | `cd backend && venv/bin/ruff check .` | `All checks passed!` |
| — | `ls docs/decisions \| tail -1` | the decision-seam ADR (`0027-decision-seam.md` expected, PKG-05b); your cutover ADR takes the next number (0028 expected) |

(The PKG-00 `test_learning_gate.py` row, the PKG-11 gate-grep row and the PKG-13 "legacy-user split" row describe the build phase: half B deliberately rewrites the gate tests, removes the quiz/flashcard gate and replaces the legacy-user split, so after half B those rows no longer hold as written — Task B7 records the replacements in HANDOFF-00, HANDOFF-11 and HANDOFF-13.)

Rule: any red row → STOP. Diagnose, repair on this branch as commit `fix(learning-loop): PKG-MM — <what>` (MM = the package whose line is red), record the deviation in `LEDGER.md` (row `MM | reopened`, "Post-hoc changes" in `HANDOFF-MM.md`), re-run all rows. Never build on a broken base. The PKG-13 row needs the stack lock: wrap the whole up→test→down cycle in ONE `flock /tmp/claude-$(id -u)/sapling-e2e-stack.lock sh -c '…'`.

## Spec

### Behaviour — half A

1. **Metrics script.** `backend/scripts/derive_zpd_metrics.py` recomputes, for every `learner_state` row with `opps > 0` (or one `--user`), the four derived columns from `node_mastery_events` rows with `event_type = 'evidence'` and a non-null `question_hash` (an *opportunity*; propagation rows have no `question_hash` and are excluded). Ordered `created_at desc, id desc`:
   - `htc_k` = mean of `max_rung` over the CORRECT opportunities among the last `HTC_K_WINDOW`; `None` when none of them is correct.
   - `unassisted_next` = share of the last `BAND_WINDOW` opportunities with `correct AND NOT assisted AND max_rung == 0`.
   - `assist_gap` = (correct share among the ASSISTED opportunities in the last `BAND_WINDOW`) − (correct share among the UNASSISTED ones); `None` when either side has zero rows.
   - `in_zone` = `assist_gap ≥ ZPD_IN_ZONE_MIN_GAP AND assisted_rate ≥ ZPD_IN_ZONE_MIN_ASSISTED AND unassisted_next < ZPD_IN_ZONE_MAX_UNASSISTED`; `None` when `assist_gap` is `None`.
   The write goes through a new `learning/learner_state.py::write_metrics(user_id, node_id, *, htc_k, unassisted_next, assist_gap, in_zone)` that UPDATES those four columns (+ `updated_at`) filtered on the primary key and touches nothing else — the one non-evidence write to `learner_state`, recorded as a deviation from spec §5 (†) and in the ADR. The script never calls `table("learner_state")` itself. Re-running produces byte-identical rows (pure function of the events). `--dry-run` prints the would-be rows and writes nothing. Exit codes: `0` normal; `2` when `learner_state` has rows with `opps > 0` but the evidence read returned zero rows for every one of them (a keyspace mismatch — the silent-empty class F5 exists for); `2` also when `--expect-rows` is passed and there are no `learner_state` rows at all. A fresh environment with no rows and no `--expect-rows` exits `0` after printing `0 rows`.
   **Cost and mix report** (spec §10; A15, A20, A21, A22 — read-only, printed as one `REPORT <json>` line on every run, `--dry-run` included; it changes the exit code only when one of its reads fails — §Error semantics). Window: `--from`/`--to` (ISO; default `to` = now, `from` = `to` − `KPI_TREND_WEEKS` weeks, the KPI endpoint's trend window). Reads, each paged with `page_all(…, filters={"created_at": ["gte.<from>", "lt.<to>"]}, order="created_at,id")`: `llm_usage` (`id,user_id,request_id,task,cost_usd,created_at`) and `events` (`id,event_type,user_id,request_id,payload,created_at` with `event_type=in.(zpd.step,ai.budget_capped,learn.session_closed)`). A pure `report(usage, steps, caps, *, sessions_by_request) -> dict` computes:
   - `cost_per_band`: `sum(cost_usd)` (NULL counts as 0) over `llm_usage` rows whose `task` is a series slot other than `check_items` (spec §8 invariant 6 list), keyed by the `band` of a `zpd.step` event with the same `request_id`; rows with no such step go under `"unknown"` — never guessed.
   - Session attribution: `sessions_by_request` maps a request id to the `session_id` any event payload in the window carries (today only `learn.session_closed`; HANDOFF-07/09 say whether a loop event gains one). When EVERY attributed loop row maps, the report carries `cost_per_session` (`{session_id: usd}`); otherwise it carries `cost_per_user_day` (`{"<user_id>/<UTC date>": usd}`) instead, and the hand-off records under Known gaps that per-session cost needs a session key on `zpd.step` or `llm_usage`.
   - `check_items_usd`: the `check_items` rows' total (course assets, not a student's session).
   - `tier_mix`: counts of `zpd.step.tier` values; `grader_backend_mix`: counts of `zpd.step.grader_backend` values (absent keys are not counted, never zeroed).
   - `cap_hits`: counts of `ai.budget_capped` events keyed `"<scope>/<level>"`.
   - `check_item_coverage` (spec §11.7 step 11 — makes coverage erosion visible; read-only, point-in-time, not windowed): `{course_id: [with_items, concepts]}` from PKG-04's `check_item_service.coverage(course_id)` for every distinct `course_id` in `graph_nodes` (paged). A course whose `with_items` falls between runs is the signal that the nightly backfill is not running.
2. **KPI endpoint.** `GET /api/admin/analytics/learning-loop?from=&to=` (admin-only, read-only, `Cache-Control: private`, `truncated` flag) returns:
   - `in_band_share`: over `zpd.step` events in range grouped by `(user_id, concept_id)` in `created_at` order, each step whose phase has a band and that has ≥ `BAND_WINDOW` prior steps of the same kind gets a rolling success rate over those prior steps; `probe` steps use the unassisted first-attempt rate vs `[PROBE_TARGET_LO, PROBE_TARGET_HI]`; `check` steps with `assisted = true` use the assisted first-attempt rate vs `[ACQ_TARGET_LO, ACQ_TARGET_HI]`; `check` steps with `assisted = false` use the unassisted rate vs `[PRACTICE_TARGET_LO, PRACTICE_TARGET_HI]`; every other phase (`teach`, `feedback`, `close`, `plan`, `posttest`) is excluded. `in_band_share = in_band / banded_steps`, `None` when `banded_steps == 0`.
   - `htc_k_trend`: per `concept_id`, the mean `max_rung_used` over correct `zpd.step` rows per ISO week for the last `KPI_TREND_WEEKS` weeks ending at `to`, plus `direction` ∈ {`falling`, `flat`, `rising`, `insufficient`} comparing the first and last week that have data (`insufficient` when fewer than two weeks have data).
   - `unassisted_next_session`: over `node_mastery_events` evidence rows in range grouped by `node_id` and then by `session_id` in `created_at` order, for every session after the first the FIRST row counts as a success when `correct AND NOT assisted AND max_rung == 0`; returns `{sessions, successes, rate}`.
   - `leak_count`: number of `zpd.leak` events in range.
   - `ceiling_compliance`: `{steps, compliant, rate}` over `zpd.step` rows where `max_rung_used ≤ ceiling` (parse the rung wire form per HANDOFF-06 — `"H3"` or `3` — with one `_rung_int` helper; rows missing either key are excluded from `steps`).
   - `gates`: `{zero_leaks: leak_count == GATE_LEAKS_MAX, ceiling_compliance_ok: rate is not None and rate ≥ GATE_CEILING_COMPLIANCE_MIN}`.
   The earnest-revise gate (spec §10) is NOT computed — no event carries that signal; record it under Known gaps.
3. **Rating prompt.** `routes/learn_loop.py` keeps a top-level integer `loop_state["checks_since_rating"]`, incremented in the check-answer handler (`POST /check/answer` and `/check/answer/stream`, PKG-07 — the only loop-chat evidence path, A16) each time it flushes evidence; a plain `/chat/stream` turn or an `[ACTION: …]` turn never touches it (invariant 26), and an `unavailable` grade (no evidence) does not count. When, after that increment, the counter is `≥ ZPD_RATING_EVERY_N_CHECKS`, the `done` event of that `/check/answer/stream` feedback turn carries `data.ask_rating = true` and the JSON `/check/answer` response carries `"ask_rating": true` (absent otherwise — never `false`). `POST /api/learn/loop/rating` body `{session_id, rating}` with `rating ∈ {too_easy, appropriate, too_hard}` (422 otherwise): emits `zpd.rating` with payload `{rating, checks_since_last}` (the counter's value), resets the counter to `0` in `sessions.loop_state`, stores the rating nowhere else, returns `{"ok": true}`. 404 `{"detail": "learning loop not enabled"}` when the gate is false (PKG-07's pattern). Frontend: a three-button prompt in `LoopLearn.tsx` with `data-testid="loop-rating"` (buttons `loop-rating-too_easy` / `loop-rating-appropriate` / `loop-rating-too_hard`), shown when a `done` event carries `ask_rating`, hidden after one click; `api.ts` gains `submitLoopRating(sessionId, rating)`.
4. **Tool-removed post-test.** `POST /api/learn/loop/posttest/start` body `{course_id}` (user from the session cookie, `require_self` on an optional `user_id` exactly as the other loop routes do): selects this user's `learner_state` rows whose `last_evidence_at ≤ now − POSTTEST_MIN_AGE_DAYS` and whose node belongs to `course_id`; resolves each node's `concept_key = _normalize_concept(graph_nodes.concept_name)` (A2) and its items with `check_item_service.list_items(course_id, concept_key)`; excludes `seen ∪ revealed` (`loop_state_store.seen_hashes(user_id)` ∪ `revealed_hashes(user_id)`, PKG-07, A23 — read once per request). The item is the concept's post-test reserve (`checks.posttest_reserve_hash(items)`, A23 — never served by probe, in-session checks or review) when that hash is not excluded; otherwise `checks.select_item(items, format="free", difficulty=CHECK_ITEM_DIFFICULTIES[1], exclude_hashes=seen ∪ revealed)`, and if that returns `None`, the lowest-`question_hash` item not in `seen ∪ revealed` (†: a concept whose reserve was already served still gets one unseen item); nothing left → the node is skipped. Caps at `POSTTEST_MAX_ITEMS` ordered by oldest `last_evidence_at` first, returns `{items: [{node_id, question_hash, format, difficulty, prompt, options}]}` with `prompt` decrypted and `options` = `[{letter, text}]` from the decrypted `options_json` for `mc_reason` items (never `wrong_key`, correctness never marked — A22, as PKG-12 serves them), `null` otherwise. No brief, no RAG, no tutor agent, no session row, no model call. `POST /api/learn/loop/posttest/answer` (with `Depends(ai_budget.enforce_rate_limit)` — it can run the grader, A20) body `{node_id, question_hash, answer, selected_option, reason, idk}` (the last three optional; `idk` default `false`): resolves the node's `course_id`/`concept_key` and loads the item by `(course_id, concept_key, question_hash)` through `check_item_service`, then grades through `agents/tools/check.py::grade_answer(item, CheckAnswer(question_hash, answer_text=answer, selected_option, reason, idk), deps=<SaplingDeps(user_id, learning_loop=True, no session)>, node_id=node_id, max_rung=0)` — the single grading helper the check, probe and review routes use (A16, HANDOFF-05; idk → A1 idk evidence on the item's channel; `mc_reason` and `numeric` pre-checks per A22). `grade_answer` appends the evidence (`assisted=False`, `max_rung=0`, `session_id=None`, with `grader_backend`) to `deps.pending_evidence`; this handler persists it with ONE `flush_pending(deps, course_id)` — it joins the invariant 26 allow-list — emits `zpd.step` with `phase="posttest"`, `ceiling` = the wire form of `H0`, `max_rung_used=0`, `assisted=False`, `n_attempts=1`, `grader_backend` from the outcome, `variant`, and no `tier` key (no tutor turn ran; omitted, never zeroed), and returns `{correct, confidence}`. `outcome.unavailable` (outage, or the `STUDENT_DAILY_GRADES` cap inside `grade()`) → 503 `{"detail": "grader unavailable"}`, no evidence for either outcome (invariant 28), no `zpd.step`, no second prompt (ADR 0024). `"posttest"` is added to every `Literal`/enum that types `zpd.step.phase` (`grep -rn '"feedback", "close"' backend/` and `grep -rn "Phase = Literal" backend/`); the `sessions.close_phase` CHECK is NOT changed — `posttest` is a `zpd.step.phase` value only.
5. **Arms.** Migration `<ts>_learning_loop_arm.sql` (spec §4, verbatim). `loop_arm` is readable in the settings GET (`_SETTINGS_COLS`, `SettingsResponse.loop_arm: str | None = None`) and NOT patchable by the student (not in `ALLOWED`) — assignment is the series owner's, by SQL. `policy.variant_for(user_id: str, node_id: str, arm: str | None) -> Literal["A", "B"]`: `"A"` whenever `arm` is `None` or empty; otherwise `"A"` if the first byte of `sha256(f"{arm}:{user_id}:{node_id}")` is even, else `"B"` — concepts are randomized WITHIN a student, and a different `arm` label reshuffles. `policy.independent_min_s(band, variant) -> int`: variant `"B"` returns `GATE_INDEPENDENT_MIN_S_VARIANT_B` for the develop/profic bands, everything else is unchanged (`GATE_INDEPENDENT_MIN_S` / `GATE_INDEPENDENT_MIN_S_NOVICE`). The one call site that reads the independent-time threshold (HANDOFF-06; `grep -n GATE_INDEPENDENT_MIN_S backend/routes/learn_loop.py backend/learning/gates.py`) goes through it, and `zpd.step` payloads gain `variant` (spec §6, §13 A8). **The arm is plumbing.** With `loop_arm` NULL for everyone, every student is variant `A` and behaviour is unchanged. The first experiment is chosen by the series owner; `GATE_INDEPENDENT_MIN_S` vs `GATE_INDEPENDENT_MIN_S_VARIANT_B` is only the first candidate the ZPD report marks †. Arms may also compare tier policies (for example standard vs deep for develop-band teach, spec §10); wiring such an experiment is the owner's follow-up — this package changes neither `policy.model_tier` nor the §3.5 tier table. **Arm sessions and the budget (A20):** a session is an arm session when the student's `loop_arm` is non-empty (both variants — a within-student design must treat A and B concepts alike); the loop routes pass `arm_session = bool(loop_arm)` to every `ai_budget.check(…, "tutor", …)` and `policy.model_tier(…)` call PKG-07 wrote with `arm_session=` (`grep -n arm_session backend/routes/learn_loop.py`), so arm sessions are never downgraded and pause at the hard level instead. With `loop_arm` NULL it stays `False` — unchanged behaviour. Analysis note (ADR and hand-off): arms are analysed intention-to-treat by assigned variant, plus the tier actually served (`zpd.step.tier`) with a cap-hit covariate (`ai.budget_capped` for that user-day).
6. **ADR** — the cutover ADR, `docs/decisions/<next>-learning-loop-cutover.md` (0028 expected: PKG-05b's decision-seam ADR took 0027; take the next free number and record it in the hand-off), in the 0026 format. Sections: Context (scalar mastery moved by an LLM tool and flat quiz deltas; the research verdict; the owner's 2026-09-26 default-on and cost decisions); Options considered (keep the tool with tighter bounds / evidence-only writes behind a flag then cut over / big-bang); Decision (evidence-only rule — spec §1 and §5; **the loop is the default learning system for every student with no opt-in (spec §13 A14)**: the two-phase flag of spec §7 — dark during the build, env-only kill switch with the exact parse after launch; `learning_loop_beta` is a build-phase staff/QA toggle, set by SQL, retired at half B; the kill-switch semantics of spec §11.6 — what `LEARNING_LOOP_ENABLED=false` restores and what it does NOT (quiz/flashcard deltas, the 0.1/0.45/0.75 tier cuts, any mastery recording on that path); the cost guardrails the launch gate requires — A15 routing, A18 limits, A20 cost guard, A21 usage observability, with the ≈ $0.36/student-month target; the ladder rungs 1–4 with what Sapling implements for each (rung 3 grades through `grade_answer` on the reserve item); the launch plan of spec §11 (§11.1 gate, §11.2 changes, §11.7 owner-run runbook); the `chat_tutor` mode-prompt fold deferred to the follow-up that deletes `LEARNING_LOOP_ENABLED`; the `write_metrics` exception to §5; the `variant` payload key; the `posttest` phase value; the arm analysis note); Consequences (what is deleted in half B, the follow-up that removes `LEARNING_LOOP_ENABLED` entirely and folds the legacy tutor, columns left dead — `user_profiles.learning_style` AND `user_settings.learning_loop_beta` — and the `graph_nodes.mastery_events`-era columns; the applied PKG-00 migration's header ("per-user opt-in for the new tutor loop") describes the build phase and is immutable; the earnest-revise gate not measured). `Relates to:` the spec, ADR 0024, the decision-seam ADR (PKG-05b), ADR 0015, `#620`. Status `accepted`; half B appends `learning_loop_beta retired: <date> (PKG-14b)` and `Cutover executed: <date>, PR #<n>`; the owner's runbook appends `Launched: <date>`.
7. **Evals.** `tests/evals/loop_tutor.py` has at least: two answer-leak fixtures (the item's structured final answer — `check_items.final_answer`, §13 A34 — must not appear at rung < H6 — score with `learning.leak.detect_leak(reference, reply, rung, final_answer=<the case's final_answer>)`; it never parses the reference), two sycophancy fixtures (the student asserts a wrong claim confidently; the reply must not agree — evaluator looks for a contradiction marker set defined in the module and a question), one ceiling-compliance fixture. Add only what HANDOFF-07 lists as missing; ≤ 8 cases total per dataset. The dataset runs per tier slot (`loop_tutor_lite`, `loop_tutor`, `loop_tutor_deep` — PKG-07's layout, spec §10/A15): every new case is recorded and baselined for every slot, and a slot that fails any evaluator is not routable (record it in the hand-off). `run_all.py::DATASETS` contains `check_items`, `grader`, `decisions` (PKG-05b), `loop_tutor`. New cases are recorded once per slot (`SAPLING_EVAL_MODE=record`), baselines updated with `SAPLING_EVAL_UPDATE_BASELINES=1`, cassettes + `baselines.json` committed together.
8. **Flag.** Half A adds nothing that runs when `learning_loop_active` is false (build phase: env AND the staff/QA toggle, spec §7): the rating and post-test routes 404, `checks_since_rating` is only touched inside the check-answer handler, `variant_for` and the `arm_session` plumbing are only reached inside loop code, the script's only write (`write_metrics`) targets `learner_state` rows that are empty for a flag-off deployment and its cost report only prints, and the KPI endpoint is admin-only and read-only. `tests/test_learning_posttest.py::test_posttest_404_when_gate_false` and `tests/test_learn_loop_rating.py::test_rating_404_when_gate_false` prove the route half.

### Behaviour — half B (spec §11.2–§11.6)

1. Remove `update_mastery_tool`, `MasteryUpdateInput`, `ConceptMasteryUpdate`, `TUTOR_EVENT_TYPES` (`agents/tools/graph.py`) and the preamble paragraph `agents/chat_tutor.py:84–91`; `_build_tools(learning_loop=False)` no longer registers `update_mastery_tool` (the legacy set keeps its other six tools). `apply_graph_update` accepts only `new_nodes`, `new_edges`, `evidence` (and PKG-12's `retention`); the `updated_nodes` branch (`services/graph_service.py:764–784` and its event row) is deleted with its tests.
2. Remove `MASTERY_DELTA_PER_CORRECT`, `MASTERY_DELTA_PER_WRONG`, `mastery_after` (`services/quiz_config.py:102–114`) and the delta block in `submit_quiz` (`routes/quiz.py:2531–2585`). Quiz and flashcards run the PKG-11 evidence path for EVERY user — no gate. `quiz_attempts.mastery_before/mastery_after` stay and are filled from the `apply_graph_update` result (`p_before`/`p_after` of the last evidence). The `quiz.completed` payload key `mastery_delta` and the attempt-history field `mastery_delta` (`routes/quiz.py:2048`, `:2710`; `frontend/src/components/screens/Tree.tsx:34`, `:405`, `Tree.quiz.test.tsx`) are renamed `p_delta` (value `p_after − p_before`), so `test_inv_21` can grep the literal.
3. `config.MASTERY_MASTERED_MIN/LEARNING_MIN/STRUGGLING_MIN`, `get_mastery_tier`, `is_mastered`, `is_weak` are deleted; every caller uses `learning/bkt.py::tier_for` (and two new pure predicates there, `is_mastered(p) = tier_for(p) == "mastered"`, `is_weak(p) = tier_for(p) in {"struggling", "unexplored"}`). New cuts are the spec §3.1 tier mirror: `TIER_UNEXPLORED_MAX` / `BAND_NOVICE_MAX` / `BKT_PROFICIENT`. Every frontend copy mirrors them — `Learn.tsx::tierForScore`, the graph's own tier mirror `frontend/src/lib/graph/nodeStyle.ts:111–121` (and the table test next to it) and the E2E copy `frontend/e2e/graph.spec.ts:54–59` (`tierFor`) — so the graph and the Learn screen never disagree; `tests/test_mastery_tier_unification.py` imports from `learning.params` and pins all three copies.
4. `learning_style`: the onboarding step is removed (`Onboarding.tsx` step 5 and `StepLearningStyle`, `canContinue` case 5, the `finish` guard and payload field; `api.ts` `OnboardingProfilePayload.learning_style` removed), `OnboardingBody.learning_style` becomes `Optional[str] = None` and is ignored, `routes/onboarding.py:86` stops writing it, `routes/profile.py:42` stops selecting it, the profile response model drops it (`models/__init__.py:312`). The column stays; the ADR notes it dead. Seeds (`db/seed_staging.py:156`, `db/seed_local_rich.py:167–191`, `db/e2e_checks/academics.py:43`) stop populating it.
5. `end_session` (`routes/learn.py:1145–1152`, `:1206–1212`): `mastery_changes`, `new_connections`, `recommended_next` are removed from both summary dicts; `SessionSummary.tsx` stops rendering them. PKG-09's `tests/test_learning_close_brief.py::test_end_session_flag_off_is_byte_identical` asserts only that `concepts_covered` and `time_spent_minutes` are present (⊆, amended 2026-09-27 for exactly this), so it stays green and unmodified; if HANDOFF-09 shows it still asserts the five-key set, change that one line to the ⊆ form in the B5 commit, add the module to B5's Files, and record a Deviation.
6. Flag collapse (default for everyone, spec §7 "After launch", §13 A14). `backend/config.py` gets exactly:
   ```python
   _raw = os.getenv("LEARNING_LOOP_ENABLED", "").strip().lower()
   # Kill switch (spec §13 A14): any falsy spelling turns the loop off; unset or empty means ON.
   LEARNING_LOOP_ENABLED = _raw not in {"false", "0", "off", "no"}
   ```
   Unset → ON; `""` → ON; `true`/`1`/`yes`/anything else → ON; `false`/`FALSE`/`0`/`off`/`no` (any case, surrounding whitespace ignored) → OFF. `learning/gate.py::learning_loop_active(user_id)` keeps its signature, returns `config.LEARNING_LOOP_ENABLED`, reads no `user_settings`, and no longer imports `table`; its docstring is rewritten to the post-launch meaning (env-only kill switch; no student opt-in). `learning_loop_beta` is retired: the column stays (dead; the cutover ADR says so), and nothing reads it. It is in no settings API field (spec §13 A31; the CodeRabbit PKG-00 reopen 2349294 removed it from `_SETTINGS_COLS`, `ALLOWED`, `UpdateSettingsBody` and `SettingsResponse`); if anything re-added it to one of them, remove it. The gate is still consulted at the `routes/learn.py` delegation lines and the `/api/learn/loop/*` 404 — those are the kill switch (spec §11.6): `LEARNING_LOOP_ENABLED=false` plus a redeploy returns every student to the pre-loop Learn screen, the legacy `chat_tutor` agents (without the mastery tool) and the legacy Study flashcards UI, and 404s `/api/learn/loop/*`. It does NOT restore quiz/flashcard mastery deltas or the 0.1/0.45/0.75 tier cuts (no legacy path exists after half B), and on that path the tutor records no mastery at all; the cutover ADR says so. The kill-switch path is cost-bounded too (A20): every legacy model-calling handler in `routes/learn.py` (`start_session`, `/start-session/stream`, `/chat`, `/chat/stream`, `/action`) gains `dependencies=[Depends(ai_budget.enforce_rate_limit)]` and calls `ai_budget.check(user_id, "tutor", "develop")` (module-qualified) before any agent runs and before a stream opens — the legacy path has no concept band, so it gets the develop/profic allowance (†, the same allowance `check(…, "close")` uses for a session with no novice-band concept); `level == "hard"` → `raise ai_budget.AIBudgetExceeded(decision)` (HTTP 429 `{"detail": "ai budget reached", "reset_at": …}` through PKG-06b's handler; never a mid-stream event on the legacy path); `soft` changes nothing there (the legacy path has no tiers). The quiz and flashcard gates from PKG-11 are removed (both surfaces are evidence-only for everyone). Post-launch wording replaces every build-phase "opt-in" comment in code that shipped: the `gate.py` docstring, the `learn_loop` mount comment in `backend/main.py` → `# Learning loop: 404 when LEARNING_LOOP_ENABLED=false (kill switch).`, `backend/.env.local.example` (`# LEARNING_LOOP_ENABLED — unset = ON (default); false/0/off/no = kill switch (spec §7)`), `scripts/e2e-up.sh` and the `db/seed_local_rich.py` comments (Task B5b). The applied PKG-00 migration header is immutable and stays; the ADR notes it. The follow-up that deletes the env var entirely is a ticket, not this PR.
7. DEFERRED to the follow-up that deletes `LEARNING_LOOP_ENABLED`. Half B keeps `socratic_agent`/`expository_agent`/`teachback_agent` and their mode prompts; removes only the `update_mastery_tool` paragraph (`:84–91`); `_build_tools(learning_loop=False)` drops `update_mastery_tool`; `loop_tutor.py` unchanged; `chat_tutor` cassettes re-recorded against the edited preamble. The legacy agents are what the kill switch serves — on the kill-switch path (`LEARNING_LOOP_ENABLED=false`, i.e. `deps.learning_loop` false) `routes/learn.py` builds its runs exactly as before, minus the mastery tool. The `chat_tutor` `AgentTask`, its `_DEFAULTS` entry and the `E2E_TUTOR_REPLY` handler stay (the kill-switch E2E lane uses them).
8. Evals: `tests/evals/chat_tutor.py` drops `MASTERY_DELTA_MIN/MAX`, `_mastery_updates`, `MasteryUpdateEmittedEvaluator` and the offline graph-write stub's `mastery_delta` handling. There is **no** `EvidenceRecordedEvaluator`: the legacy tutor records no evidence, and no `graded_check_tool` exists (A16). `NoToolMisuseEvaluator.BANNED_SUBSTRINGS` keeps banning `update_mastery_tool`. Cassettes under `tests/evals/cassettes/chat_tutor/` are deleted and re-recorded against the edited preamble (`SAPLING_EVAL_MODE=record venv/bin/python tests/evals/chat_tutor.py`), baselines refreshed, all committed together.
9. E2E: `frontend/e2e/support/quiz.ts` replaces `MASTERY_PER_CORRECT/WRONG` + `masteryAfter` with `bktAfterCorrect(before, n)` — the §3.1 correct-update with the learn step, channel `mc`, mirrored constants `BKT_L0`, `BKT_T`, `CHANNELS["mc"]` (pinned by a new backend test that reads the TS file, same technique as the tier mirror). `quiz.spec.ts` expects `p_after` per §Derived expectations below and one evidence row per item (or per quiz — HANDOFF-11 says which; the `node_mastery_events` count assertion at `:150–152` follows it). `frontend/e2e/quiz-integration.spec.ts:50`, `:130` replace the flat `3 * 0.03` with the same `bktAfterCorrect` expectation (the quiz has no legacy path after half B, so both lanes expect it). The AskPanel assertions (the quiz "Ask about this" sheet → `/api/learn/start-session/stream`, which delegates to the loop opener) are lane-aware: `quiz-journeys.spec.ts:463` and `quiz-integration.spec.ts:286`, `:292` expect `E2E_LOOP_TUTOR_REPLY` in the default lane and `E2E_TUTOR_REPLY` in the kill-switch lane (spec §11.4). No E2E user is opted in by half B — the gate never reads the column, so every seeded student is on the loop in the default lane.
10. E2E after launch (spec §11.4). Half B removes the explicit `LEARNING_LOOP_ENABLED` export from `scripts/e2e-up.sh`, `.github/workflows/e2e.yml` and `scripts/explore.sh`, so the default lane runs the code default. **One lane parse:** `frontend/e2e/support/fixtures.ts` exports `killSwitchLane = ["false", "0", "off", "no"].includes((process.env.LEARNING_LOOP_ENABLED ?? "").trim().toLowerCase())` (the §7 post-launch parse) and every guard uses it — never a raw `!== "false"` compare. `scripts/e2e-up.sh` fails fast (exit 2, a one-line reason) when `backend/.env` contains a `LEARNING_LOOP_ENABLED=` line, because `load_dotenv()` would fill an unset variable from it for the backend while Playwright sees it unset; `frontend/e2e/global-setup.ts` asserts `GET /api/learn/loop/status` for the default fixture user is 404 in the kill-switch lane and `{active: true}` in the default lane. Two lanes: **default** (`make e2e-up` with no `LEARNING_LOOP_ENABLED` at all; oracles exit 0) and **kill switch** (`LEARNING_LOOP_ENABLED=false make e2e-up`; oracles exit 0). **Legacy-only** tests are exactly those that need the legacy Learn screen — `tutor.spec.ts`, `streaming.spec.ts` and the single `/learn` recipe in `gallery-shots.spec.ts` — plus "kill switch restores the legacy Learn screen"; they carry `test.skip(!killSwitchLane, "legacy path: kill-switch lane only")`. **Loop-only** tests (every other `learn-loop.spec.ts` test) carry `test.skip(killSwitchLane, "loop path: default lane only")`. Everything else runs in BOTH lanes — `quiz`, `quiz-integration`, `quiz-journeys`, `onboarding` (without the learning-style step, removed for everyone), `study-room`, `study-recent-guides`, `study-semester`, and the other `gallery-shots` recipes — lane-aware where the lanes differ: the AskPanel reply (B.9), and `study-semester.spec.ts`, which asserts in the default lane that `review-due-panel` and the semester flashcard deck coexist on `/study?mode=cards` and in the kill-switch lane that `review-due-panel` is absent. `learn-loop.spec.ts`: PKG-13's build-phase test "build phase: a user without the staff/QA toggle still gets the legacy Learn screen with the flag on" becomes `test("every student gets the loop by default", …)` (`loop-phase` visible and `tutor-topic-picker` count 0 for the default fixture user), plus `test("kill switch restores the legacy Learn screen", …)` guarded by `test.skip(!killSwitchLane)`. CI: `e2e.yml` runs both lanes (matrix `lane: [default, kill-switch]`; the default lane sets no variable, the kill-switch lane sets `"false"`). PKG-13's `test_inv_13b_seed_opts_in_exactly_the_loop_users` is rewritten in place (name kept, docstring says the name is historical): `grep -rn learning_loop_beta frontend/e2e` → 0 — no journey depends on the toggle; PKG-13's `test_legacy_users_are_not_opted_in` is retired under the deleted-test naming rule (the split it pins no longer exists). The PKG-13 seed and `scripts/e2e-up.sh` comments are rewritten to the post-launch meaning.
11. Hermetic suite after launch (spec §11.5). Every backend test module that exercises code gated by `config.LEARNING_LOOP_ENABLED` (directly or through `learning_loop_active`) without pinning the flag itself runs as an explicit kill-switch test: it declares `pytestmark = pytest.mark.kill_switch`; an autouse fixture in `tests/conftest.py` monkeypatches `config.LEARNING_LOOP_ENABLED = False` for marked tests, and `pytest_configure` registers the marker (`config.addinivalue_line("markers", "kill_switch: legacy path under LEARNING_LOOP_ENABLED=false (spec §11.5)")`). The list: the legacy `/api/learn/*` modules (`tests/test_learn_routes.py`, `test_learn_stream_routes.py`, `test_event_capture_seams.py`, `test_xp_wiring.py`, `test_achievement_dispatch.py`, `test_graph_context_block.py`, plus any other non-loop hit of `grep -ln '/api/learn/' backend/tests`), AND `tests/test_documents_routes.py` — under the default, PKG-04's upload hook schedules `("index_then_check_items", _index_then_check_items, …)` instead of `("index_document", index_document, doc_id)`, so `tasks["index_document"]` (`:858`) raises `KeyError` and `test_sync_upload_is_indexed` (`:468–476`) runs the real `generate_for_document` in the TestClient background task — AND any other module that drives a file in `grep -rln "LEARNING_LOOP_ENABLED\|learning_loop_active" backend/routes backend/services` without patching the flag (run that grep; list each module in the commit body). Per module you may instead keep it unmarked and update its assertions to the default (for `test_documents_routes.py`: expect the `index_then_check_items` post-roll and patch `routes.documents.generate_for_document`) — record which in the hand-off. `tests/test_learning_gate.py`: every env-on test becomes "env on → True for any row state, no `table()` call"; `test_read_error_fails_closed` is removed under the deleted-test naming rule (there is no read); env-off tests keep the no-read assertion; `test_env_flag_defaults_on` is parametrized over `(None, True), ("", True), ("true", True), ("1", True), ("false", False), ("FALSE", False), ("0", False), ("off", False), ("no", False)`. Every reload of `config`/`learning.gate` in a test goes through PKG-00's `reload_gate(monkeypatch, raw)` (never a bare `importlib.reload`: `load_dotenv()` would refill a deleted variable from `backend/.env`, and the recomputed flag would leak into later modules).
12. Launch runbook (spec §11.7). Merging half B launches STAGING (`main` = staging); the first `make promote` after it — the runbook's or any unrelated one — carries half B to production, and the production pin holds back only the gated loop UI/routes: the ungated half B changes (evidence-only quiz/flashcards, the 0.10/0.30/0.95 tier cuts, a legacy tutor that records no mastery, no learning-style step, the budget-checked legacy routes) reach every production student with that promote, and only a revert of the half B merge plus `make promote` undoes them (spec §11.7 Rollback). The session writes spec §11.7 — its opening paragraph, steps 1–12 and the Rollback block — verbatim into HANDOFF-14 under `## Launch runbook` (Task B9) and stops: it never sets a deployed env var, never runs `make promote`, never runs a backfill against staging or production, never reverts. The owner runs every step and makes every abort decision.
13. `Learn()` after launch (spec §11.2). `frontend/src/components/screens/Learn.tsx` (PKG-13's branch point) renders the legacy `LearnInner` ONLY when `GET /api/learn/loop/status` answers HTTP 404 or `{active: false}` (the kill switch). Any other failure — 5xx, timeout, network error — renders `loop-status-error` ("Couldn't reach the tutor. Try again.") with `loop-status-retry`, which re-runs the status GET; it never renders the legacy tree (after launch the backend delegates the legacy `/start-session`/`/chat` calls to the loop, so failing open would give a hybrid: typed answers never graded, loop phase/check events ignored, a smart/fast toggle that does nothing). vitest in `Learn.branch.test.tsx` (or the module PKG-13 named): status 500 → `loop-status-error`, no `LearnInner`, no legacy `start-session` call; retry → `{active: true}` → `LoopLearn`; 404 → `LearnInner` (unchanged). Both testids go in `docs/frontend-testids.md`.

### Schema (exact)

```sql
-- <ts>_learning_loop_arm.sql
-- Learning loop series PKG-14: within-student A/B arm label. NULL = no
-- experiment (every concept is variant A). learning/policy.py::variant_for
-- hashes (arm, user_id, node_id) so concepts are randomised WITHIN a student.
ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS loop_arm text;
```

Half B adds no migration. Columns left dead on purpose (ADR): `user_profiles.learning_style`, `user_settings.learning_loop_beta` (the build-phase staff/QA toggle, retired at half B; its applied PKG-00 migration header describes the build phase and stays as written).

### Named constants

Every number this prompt uses, once. Cite the NAME in code. Rows marked † are not in spec §3: add them to `backend/learning/params.py` in a `# PKG-14 (†)` block and list each in HANDOFF-14 "Constants chosen" and `LEDGER.md` Deviations.

| Name | Value | Spec / source | Used by |
|---|---|---|---|
| `ZPD_RATING_EVERY_N_CHECKS` | 30 | §3.4 | rating prompt |
| `BAND_WINDOW` | 8 | §3.3 | `unassisted_next`, `assist_gap`, KPI rolling window |
| `HTC_K_WINDOW` | 5 † | ZPD report LOG "last k=5 opportunities" | `htc_k` |
| `ZPD_IN_ZONE_MIN_GAP` | 0.25 † | ZPD report LOG "in_zone flag" | `in_zone` |
| `ZPD_IN_ZONE_MIN_ASSISTED` | 0.6 † | same | `in_zone` |
| `ZPD_IN_ZONE_MAX_UNASSISTED` | 0.85 † | same | `in_zone` |
| `PROBE_TARGET_LO` / `PROBE_TARGET_HI` | 0.50 / 0.62 | §3.3 (PKG-06) | KPI band |
| `ACQ_TARGET_LO` / `ACQ_TARGET_HI` | 0.75 / 0.90 | §3.3 (PKG-06) | KPI band |
| `PRACTICE_TARGET_LO` / `PRACTICE_TARGET_HI` | 0.65 / 0.85 | §3.3 (PKG-06) | KPI band |
| `KPI_TREND_WEEKS` | 4 † | this package (spec §13 A6) | `htc_k_trend`; the metrics script's default report window |
| `GATE_LEAKS_MAX` | 0 | §10 gates | KPI gates |
| `GATE_CEILING_COMPLIANCE_MIN` | 0.95 | §10 gates | KPI gates |
| `POSTTEST_MIN_AGE_DAYS` | 2 † | research §"Measure learning…" ("≥ 2 days") | post-test selection |
| `POSTTEST_MAX_ITEMS` | 10 † | engineering cap (spec §13 A6) | post-test selection |
| `CHECK_ITEM_DIFFICULTIES` | 1, 2, 3 | §3.4 (PKG-04) | post-test fallback prefers index 1 (difficulty 2), as the A23 reserve rule does |
| `GATE_INDEPENDENT_MIN_S` | 45 † | §3.3 (PKG-06) | variant A |
| `GATE_INDEPENDENT_MIN_S_NOVICE` | 90 † | §3.3 (PKG-06) | both variants, novice band |
| `GATE_INDEPENDENT_MIN_S_VARIANT_B` | 90 † | first A/B candidate (spec §13 A6) | variant B, develop/profic |
| `TIER_UNEXPLORED_MAX` | 0.10 | §3.1 (PKG-01) | `tier_for`, `tierForScore`, `nodeStyle.ts::tierFor`, `graph.spec.ts::tierFor` (half B) |
| `BAND_NOVICE_MAX` | 0.30 | §3.1 (PKG-01) | same |
| `BKT_PROFICIENT` | 0.95 | §3.1 (PKG-01) | same |
| `BKT_L0` / `BKT_T` | 0.35 / 0.15 | §3.1 (PKG-01) | quiz E2E expectation (half B) |
| `CHANNELS["mc"]` | G 0.25 / S 0.10 | §3.1 (PKG-01) | same |

### Derived expectations (half B, quiz journey)

Three unassisted correct `mc` observations from `BKT_L0`, each `P_post = P(1−S) / [P(1−S) + (1−P)G]` then `P'' = P_post + (1 − P_post)·BKT_T` (weight 1.0, so the learn step applies): `0.710733 → 0.913664 → 0.978259`. **Expected `p_after` = 0.978259** (6 dp; use `toBeCloseTo(…, 5)`). If HANDOFF-03 says a node with no `learner_state` row seeds `p` from `graph_nodes.mastery_score` instead of `BKT_L0`, the seeded 0.25 gives `0.613636 → 0.873468 → 0.967120`; use that and record the deviation. If HANDOFF-11 grades quiz items through the grader as `mc_reasoned`, recompute with that channel's G/S using the snippet in Task B4. `E2E_GRADER_CORRECT_TOKEN` is what the function-mode grader returns for a correct answer (HANDOFF-05) — it decides `correct` on graded formats; for plain `mc` the label match against `E2E_QUIZ_CORRECT_LABELS` decides.

### Invariants asserted by this package (spec §8 numbering plus two new)

- (20, new) `scripts/derive_zpd_metrics.py` has `--dry-run`, contains no `.insert(`, names `on_conflict=` on every `.upsert(`, never calls `table("learner_state")` and calls `write_metrics`.
- (21, new, half B) `grep -rn "mastery_delta\|MASTERY_DELTA_PER\|get_mastery_tier" backend/` has zero hits outside `backend/learning/`, `backend/venv/` and the invariants module itself.
- (1) extended: `learner_state.write_metrics` is referenced only from `scripts/derive_zpd_metrics.py` and `learning/learner_state.py`.
- (5) unchanged and re-run: `posttest` is a payload value, not an event type.
- (26) extended (half A): the post-test answer handler joins the explicit-submission allow-list of `test_inv_26_evidence_only_from_explicit_submission` — it is the only new `flush_pending` caller.
- (11) rewritten in place in half B (name kept; its docstring says the name is historical): parametrized over the spec §7 parse table — unset or `""` → True for every user; any of `false`/`FALSE`/`0`/`off`/`no` (whitespace ignored) → False; `learning/gate.py` imports no `table`, so no read is possible in either case (no opt-in, spec §13 A14).
- (13b) rewritten in place in half B (PKG-13's `test_inv_13b_seed_opts_in_exactly_the_loop_users`, name kept): `frontend/e2e/` never mentions `learning_loop_beta` — no journey depends on the retired toggle.

### Error semantics

Post-test grading: grader `unavailable` (outage or the `STUDENT_DAILY_GRADES` cap) → 503, no evidence for either outcome, `zpd.step` not emitted; over `LEARN_RATE_LIMIT_PER_MIN` → 429 from `enforce_rate_limit` before the handler runs. Kill-switch path (half B): tutor-hard or rate-limited → HTTP 429 `{"detail": "ai budget reached", "reset_at": …}` via `AIBudgetExceeded`, raised before any agent runs or any stream opens. Metrics report: a read error on `llm_usage`/`events` prints `REPORT_FAIL <table> <exc class>` and sets exit code `1` (the derived-column pass still runs). KPI endpoint: any table read error propagates as the existing admin endpoints do (500); a scan hitting `_SCAN_CAP` sets `truncated`. Script: a `table()` exception on one row prints `FAIL <user> <node> <exc class>` and continues; the exit code is `1` if any row failed. Rating route: unknown `rating` → 422 from the body model.

### Events added

None. `zpd.rating` is emitted for the first time (it was registered by PKG-06). `zpd.step` gains the payload key `variant` and the phase value `posttest` (both recorded in spec §13 A8); a post-test step carries `grader_backend` and no `tier`.

## Non-goals

- No rung-4 (delayed proctored) tooling. No instructor dashboard. No uptake estimator.
- No new agent, no new `AgentTask`, no prompt change to `loop_tutor`. The `chat_tutor` mode-prompt fold is NOT in this package (deferred to the follow-up that deletes `LEARNING_LOOP_ENABLED`, spec §11.2); the legacy agents stay for the kill switch.
- No removal of `LEARNING_LOOP_ENABLED` (follow-up ticket), no removal of `user_profiles.learning_style` or `user_settings.learning_loop_beta`, no rewrite of the legacy `/api/learn/chat` request shape.
- No change to `policy.model_tier`, the §3.5 tier table or the budget constants; no tier experiment is wired (arms only carry the plumbing). No Jev code (PKG-15). No admin route for `learning_loop_beta` or `loop_arm`.
- No deploy: the session never sets `LEARNING_LOOP_ENABLED` (or `PLATFORM_DAILY_BUDGET_USD`) in any deployed config, never runs `make promote`, never runs a staging or production backfill, never reverts — the launch runbook is owner-run (Task B9).
- No feature-flag system. No changes to `services/chat_stream.py` except the one optional `done_extra` kwarg if HANDOFF-07 leaves no other way to enrich the `done` event (see Task A5).

---

# Half A — evaluation ladder (`feat/learning-loop-14a-eval-ladder`)

## Tasks

### Task A1: Invariants — `test_inv_20`, extend `test_inv_01`

**Files:**
- Modify: `backend/tests/test_learning_loop_invariants.py`

- [ ] **Step 1: Append the new test and extend inv_01**

```python
def test_inv_20_metrics_script_idempotent():
    path = BACKEND / "scripts" / "derive_zpd_metrics.py"
    assert path.exists(), "PKG-14 ships scripts/derive_zpd_metrics.py"
    text = path.read_text()
    assert "--dry-run" in text, "the script must offer --dry-run"
    assert ".insert(" not in text, "metrics are an UPDATE of derived columns; never insert"
    for m in re.finditer(r"\.upsert\(", text):
        assert "on_conflict=" in text[m.end(): m.end() + 400], "every upsert names on_conflict"
    assert 'table("learner_state")' not in text, "write learner_state only via learning.learner_state.write_metrics"
    assert "write_metrics(" in text
```

In `test_inv_01_single_graph_writer` (PKG-03's body), add at the end:

```python
    callers = sorted(
        str(p.relative_to(BACKEND))
        for p in BACKEND.rglob("*.py")
        if "venv" not in p.parts and "write_metrics(" in p.read_text()
    )
    assert callers == ["learning/learner_state.py", "scripts/derive_zpd_metrics.py", "tests/test_learning_loop_invariants.py"] + sorted(
        c for c in callers if c.startswith("tests/test_learning_zpd_metrics")
    ), f"write_metrics is the metrics script's seam only: {callers}"
```

- [ ] **Step 2: Run** `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_20 or inv_01"`
Expected: `inv_20` FAIL `PKG-14 ships scripts/derive_zpd_metrics.py`; `inv_01` FAIL (no `write_metrics` anywhere yet).

- [ ] **Step 3: Commit**

```
git add backend/tests/test_learning_loop_invariants.py
git commit -m "test(learning-loop): PKG-14a — inv_20 metrics-script idempotence, inv_01 write_metrics seam

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task A2: Arm migration, `loop_arm` read, `variant_for`, `independent_min_s`, `arm_session`

**Files:**
- Create: `backend/db/migrations/<UTC>_learning_loop_arm.sql`
- Modify: `backend/learning/params.py` (the `# PKG-14 (†)` block), `backend/learning/policy.py`, `backend/routes/profile.py` (`_SETTINGS_COLS`), `backend/models/__init__.py` (`SettingsResponse.loop_arm`), `backend/routes/learn_loop.py` (the one independent-time call site; `variant` in the `zpd.step` payload; `arm_session=bool(loop_arm)` at every `ai_budget.check(…, "tutor", …)` / `policy.model_tier(…)` call site)
- Test: `backend/tests/test_learning_arms.py`

- [ ] **Step 1: Write the failing test**

```python
"""PKG-14: within-student arms are plumbing — NULL arm means variant A everywhere."""
import pathlib
import re
from collections import Counter

import pytest

MIG_DIR = pathlib.Path(__file__).resolve().parents[1] / "db" / "migrations"


def test_migration_adds_nullable_loop_arm():
    hits = sorted(MIG_DIR.glob("*_learning_loop_arm.sql"))
    assert len(hits) == 1, hits
    sql = hits[0].read_text()
    assert re.search(r"ADD COLUMN IF NOT EXISTS loop_arm text\s*;", sql)
    assert "NOT NULL" not in sql


def test_null_arm_is_always_a():
    from learning.policy import variant_for
    for node in ("n1", "n2", "n3", "n4"):
        assert variant_for("u", node, None) == "A"
        assert variant_for("u", node, "") == "A"


def test_arm_randomises_within_student_and_is_stable():
    from learning.policy import variant_for
    nodes = [f"node-{i}" for i in range(200)]
    first = [variant_for("student", n, "exp1") for n in nodes]
    again = [variant_for("student", n, "exp1") for n in nodes]
    assert first == again
    counts = Counter(first)
    assert 60 <= counts["A"] <= 140 and 60 <= counts["B"] <= 140, counts
    assert [variant_for("student", n, "exp2") for n in nodes] != first


def test_variant_b_changes_only_the_non_novice_gate():
    from learning import params
    from learning.policy import independent_min_s
    assert independent_min_s("develop", "A") == params.GATE_INDEPENDENT_MIN_S
    assert independent_min_s("profic", "A") == params.GATE_INDEPENDENT_MIN_S
    assert independent_min_s("develop", "B") == params.GATE_INDEPENDENT_MIN_S_VARIANT_B
    assert independent_min_s("novice", "A") == params.GATE_INDEPENDENT_MIN_S_NOVICE
    assert independent_min_s("novice", "B") == params.GATE_INDEPENDENT_MIN_S_NOVICE


def test_loop_arm_is_readable_not_patchable():
    from routes import profile
    assert "loop_arm" in profile._SETTINGS_COLS
    assert "loop_arm" not in profile.ALLOWED


@pytest.mark.parametrize("arm,expected", [(None, False), ("", False), ("exp1", True)])
def test_arm_session_follows_loop_arm(arm, expected, settings_row, budget_calls, tier_calls, run_check_answer):
    """Spec §3.5/§13 A20: arm sessions are exempt from tier downgrades and pause at hard."""
    settings_row["loop_arm"] = arm
    run_check_answer()
    assert budget_calls and all(c["arm_session"] is expected for c in budget_calls)
    assert tier_calls and all(c["arm_session"] is expected for c in tier_calls)
```

`settings_row`/`budget_calls`/`tier_calls`/`run_check_answer` are fixtures you write in this module from the building blocks `tests/test_learn_loop_routes.py` already uses (its mocked `table` serving `user_settings`, its gate-open monkeypatch, its function-mode handlers for `grader` and the tutor slots): `budget_calls` wraps `routes.learn_loop.ai_budget.check` and `tier_calls` wraps the `model_tier` name `learn_loop` calls, each recording the kwargs and delegating to the real function; `run_check_answer` posts one genuine answer to `/api/learn/loop/check/answer` (the feedback turn runs the tutor, so both are called). Keep them local.

- [ ] **Step 2: Run** `cd backend && venv/bin/python -m pytest tests/test_learning_arms.py -v`
Expected: FAIL — `expected exactly one … got []`, then `ImportError: cannot import name 'variant_for'`; `test_arm_session_follows_loop_arm[exp1]` fails on `arm_session is True` (the `None`/`""` cases already pass).

- [ ] **Step 3: Implement.** Migration prefix from `date -u +%Y%m%d%H%M%S`, content from §Schema verbatim. `params.py` gets the † block (names from the table; one comment line citing the ZPD report for the `ZPD_IN_ZONE_*` trio and `HTC_K_WINDOW`). `policy.py`:

```python
def variant_for(user_id: str, node_id: str, arm: str | None) -> Literal["A", "B"]:
    """Within-student randomisation (research §"Measure learning…": Lindsey's
    design). NULL arm → A for every concept, so the plumbing is inert."""
    if not arm:
        return "A"
    digest = hashlib.sha256(f"{arm}:{user_id}:{node_id}".encode()).digest()
    return "A" if digest[0] % 2 == 0 else "B"


def independent_min_s(band: str, variant: str) -> int:
    if band == "novice":
        return GATE_INDEPENDENT_MIN_S_NOVICE
    return GATE_INDEPENDENT_MIN_S_VARIANT_B if variant == "B" else GATE_INDEPENDENT_MIN_S
```

(`hashlib` is stdlib; invariant 2 still holds.) In `routes/learn_loop.py`, read `loop_arm` once per turn alongside the existing `user_settings` read (do not add a second query if one exists — extend its column list), compute `variant = variant_for(user_id, node_id, arm)` where the check's node is known, pass it to `independent_min_s`, and add `"variant": variant` to the `zpd.step` payload. Replace every `arm_session=False` (or omitted `arm_session`) that PKG-07 passes to `ai_budget.check(…, "tutor", …)` and `policy.model_tier(…)` with `arm_session=bool(arm)` — no other budget or tier logic changes. Settings: `loop_arm,` in `_SETTINGS_COLS`; `loop_arm: Optional[str] = None` on `SettingsResponse`; nothing in `ALLOWED`.

- [ ] **Step 4: Run** `cd backend && venv/bin/python -m pytest tests/test_learning_arms.py tests/test_learning_zpd_policy.py tests/test_learn_loop_routes.py tests/test_learning_loop_invariants.py -q && venv/bin/ruff check .`
Expected: all passed except `inv_20`/`inv_01` (Task A3); `All checks passed!`

- [ ] **Step 5: Commit**

```
git add backend/db/migrations/*_learning_loop_arm.sql backend/learning/params.py backend/learning/policy.py backend/routes/profile.py backend/models/__init__.py backend/routes/learn_loop.py backend/tests/test_learning_arms.py
git commit -m "feat(learning-loop): PKG-14a — loop_arm column, variant_for, independent_min_s, arm_session budget exemption (arm plumbing, inert when NULL)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task A3: `write_metrics` + `scripts/derive_zpd_metrics.py` (derived columns + cost/mix report)

**Files:**
- Modify: `backend/learning/learner_state.py` (add `write_metrics`)
- Create: `backend/scripts/derive_zpd_metrics.py`
- Test: `backend/tests/test_learning_zpd_metrics_script.py`

**Interfaces:**
- Produces: `learner_state.write_metrics(user_id, node_id, *, htc_k, unassisted_next, assist_gap, in_zone) -> None`; `derive_zpd_metrics.compute(opps: list[dict]) -> dict` (pure: takes evidence rows newest-first, returns the four values); `derive_zpd_metrics.report(usage, steps, caps, *, sessions_by_request) -> dict` (pure: §Behaviour A.1 cost and mix report); `derive_zpd_metrics.main(argv) -> int`.

- [ ] **Step 1: Write the failing test**

```python
"""PKG-14 nightly ZPD metrics: pure compute + idempotent write through write_metrics."""
from __future__ import annotations

import importlib
import sys

import pytest

from learning import params


def _script():
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "scripts"))
    return importlib.import_module("derive_zpd_metrics")


def _opp(correct, max_rung=0, assisted=False, qh="q"):
    return {"correct": correct, "max_rung": max_rung, "assisted": assisted, "question_hash": qh, "channel": "free_response"}


def test_compute_htc_k_is_mean_rung_over_correct_in_window():
    s = _script()
    opps = [_opp(True, 2), _opp(False, 3), _opp(True, 0), _opp(True, 4), _opp(True, 0), _opp(True, 6)]
    out = s.compute(opps)
    # window = HTC_K_WINDOW newest → rungs of the correct ones: 2, 0, 4, 0 → 1.5
    assert out["htc_k"] == pytest.approx(1.5)


def test_compute_unassisted_next_and_gap():
    s = _script()
    opps = (
        [_opp(True, 0, assisted=False)] * 3
        + [_opp(False, 0, assisted=False)] * 1
        + [_opp(True, 2, assisted=True)] * 3
        + [_opp(False, 3, assisted=True)] * 1
    )
    out = s.compute(opps)
    assert out["unassisted_next"] == pytest.approx(3 / 8)
    assert out["assist_gap"] == pytest.approx(0.75 - 0.75)
    assert out["in_zone"] is False


def test_compute_in_zone_true():
    s = _script()
    opps = [_opp(True, 2, assisted=True)] * 4 + [_opp(False, 0, assisted=False)] * 3 + [_opp(True, 0, assisted=False)]
    out = s.compute(opps)
    assert out["assist_gap"] == pytest.approx(1.0 - 0.25)
    assert out["in_zone"] is True


def test_compute_empty_is_all_none():
    s = _script()
    assert s.compute([]) == {"htc_k": None, "unassisted_next": None, "assist_gap": None, "in_zone": None}


def test_propagation_rows_are_not_opportunities():
    s = _script()
    rows = [{"correct": True, "max_rung": 0, "assisted": False, "question_hash": None}]
    assert s._opportunities(rows) == []


class _T:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def select(self, cols, filters=None, order=None, limit=None):
        self.calls.append(("select", cols, filters, order, limit))
        return self.rows

    def select_with_count(self, cols, filters=None, order=None, limit=None, offset=None):
        self.calls.append(("select_with_count", cols, filters, order, limit, offset))
        return self.rows, len(self.rows)


def test_main_writes_via_write_metrics_and_is_idempotent(monkeypatch):
    s = _script()
    states = [{"user_id": "u", "node_id": "n", "opps": 3}]
    events = [dict(_opp(True, 0), created_at="2026-09-20T00:00:00+00:00", id="e1")] * 3
    monkeypatch.setattr(s, "table", lambda name: _T({"learner_state": states, "node_mastery_events": events}.get(name, [])))
    written = []
    monkeypatch.setattr(s, "write_metrics", lambda uid, nid, **kw: written.append((uid, nid, kw)))
    assert s.main([]) == 0
    assert s.main([]) == 0
    assert written[0] == written[1]
    assert written[0][2]["unassisted_next"] == pytest.approx(1.0)


def test_dry_run_writes_nothing(monkeypatch, capsys):
    s = _script()
    monkeypatch.setattr(s, "table", lambda name: _T({"learner_state": [{"user_id": "u", "node_id": "n", "opps": 1}], "node_mastery_events": [dict(_opp(True), created_at="x", id="e")]}.get(name, [])))
    monkeypatch.setattr(s, "write_metrics", lambda *a, **k: pytest.fail("dry run must not write"))
    assert s.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "(dry run)" in out
    assert "REPORT {" in out  # the cost/mix report is read-only, so a dry run prints it too


def test_zero_evidence_for_expected_rows_exits_2(monkeypatch):
    s = _script()
    monkeypatch.setattr(s, "table", lambda name: _T({"learner_state": [{"user_id": "u", "node_id": "n", "opps": 5}], "node_mastery_events": []}.get(name, [])))
    monkeypatch.setattr(s, "write_metrics", lambda *a, **k: None)
    assert s.main([]) == 2


def test_no_rows_is_ok_unless_expected(monkeypatch):
    s = _script()
    monkeypatch.setattr(s, "table", lambda name: _T([]))
    assert s.main([]) == 0
    assert s.main(["--expect-rows"]) == 2


def _usage(req, task, usd, day="20", user="u"):
    return {"id": f"{req}-{task}", "user_id": user, "request_id": req, "task": task, "cost_usd": usd,
            "created_at": f"2026-09-{day}T10:00:00+00:00"}


USAGE = [_usage("r1", "loop_tutor", "0.010"), _usage("r1", "grader", "0.001"),
         _usage("r2", "loop_tutor_deep", "0.030", day="21"), _usage(None, "check_items", "0.050", user=None),
         _usage("r3", "chat_tutor", "0.500")]  # not a series slot: excluded
STEPS = [{"request_id": "r1", "payload": {"band": "develop", "tier": "standard", "grader_backend": "gemini"}},
         {"request_id": "r9", "payload": {"band": "novice"}}]  # no tier / grader_backend keys: not counted
CAPS = [{"payload": {"scope": "daily_usd", "level": "soft"}}, {"payload": {"scope": "daily_usd", "level": "soft"}}]


def test_report_bands_mixes_and_caps():
    out = _script().report(USAGE, STEPS, CAPS, sessions_by_request={})
    assert out["cost_per_band"] == {"develop": pytest.approx(0.011), "unknown": pytest.approx(0.030)}
    assert out["check_items_usd"] == pytest.approx(0.050)
    assert out["tier_mix"] == {"standard": 1}
    assert out["grader_backend_mix"] == {"gemini": 1}
    assert out["cap_hits"] == {"daily_usd/soft": 2}


def test_report_falls_back_to_user_day_without_a_session_key():
    out = _script().report(USAGE, STEPS, CAPS, sessions_by_request={"r1": "s1"})  # r2 unmapped
    assert "cost_per_session" not in out
    assert out["cost_per_user_day"] == {"u/2026-09-20": pytest.approx(0.011), "u/2026-09-21": pytest.approx(0.030)}


def test_report_uses_sessions_when_every_row_maps():
    out = _script().report(USAGE, STEPS, CAPS, sessions_by_request={"r1": "s1", "r2": "s2"})
    assert out["cost_per_session"] == {"s1": pytest.approx(0.011), "s2": pytest.approx(0.030)}
    assert "cost_per_user_day" not in out


def test_series_slots_are_invariant_6():
    assert set(_script().SERIES_SLOTS) == {"check_items", "grader", "grader_second", "decision",
                                          "loop_tutor", "loop_tutor_lite", "loop_tutor_deep", "session_close"}


def test_write_metrics_updates_only_derived_columns(monkeypatch):
    from learning import learner_state
    t = _T([])
    t.update = lambda data, filters, **kw: t.calls.append(("update", data, filters)) or []
    monkeypatch.setattr(learner_state, "table", lambda name: t)
    learner_state.write_metrics("u", "n", htc_k=1.0, unassisted_next=0.5, assist_gap=0.25, in_zone=True)
    (_, data, filters), = [c for c in t.calls if c[0] == "update"]
    assert set(data) == {"htc_k", "unassisted_next", "assist_gap", "in_zone", "updated_at"}
    assert filters == {"user_id": "eq.u", "node_id": "eq.n"}
    assert params.BAND_WINDOW == 8  # the window the script reads
```

- [ ] **Step 2: Run** `cd backend && venv/bin/python -m pytest tests/test_learning_zpd_metrics_script.py -v`
Expected: `ModuleNotFoundError: No module named 'derive_zpd_metrics'`.

- [ ] **Step 3: Implement.** `write_metrics` in `learner_state.py` (one `table("learner_state").update({...}, filters={"user_id": f"eq.{user_id}", "node_id": f"eq.{node_id}"})`, `updated_at` = now ISO). The script follows `backfill_document_chunks.py` (docstring with run lines, `load_dotenv(BASE / ".env.staging")`, `sys.path.insert`, `# noqa: E402` imports, `print(f"Project: …")`). Structure:

```python
from db.connection import page_all, table  # noqa: E402
from learning.learner_state import write_metrics  # noqa: E402
from learning.params import (  # noqa: E402
    BAND_WINDOW, HTC_K_WINDOW, KPI_TREND_WEEKS, ZPD_IN_ZONE_MAX_UNASSISTED, ZPD_IN_ZONE_MIN_ASSISTED,
    ZPD_IN_ZONE_MIN_GAP,
)

_EVIDENCE_COLS = "id,created_at,correct,assisted,max_rung,question_hash,channel"
_USAGE_COLS = "id,user_id,request_id,task,cost_usd,created_at"
_EVENT_COLS = "id,event_type,user_id,request_id,payload,created_at"
SERIES_SLOTS = (  # spec §8 invariant 6
    "check_items", "grader", "grader_second", "decision",
    "loop_tutor", "loop_tutor_lite", "loop_tutor_deep", "session_close",
)


def _opportunities(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r.get("question_hash")]


def compute(opps: list[dict]) -> dict:  # opps newest-first, already filtered
    ...


def _states(user: str | None) -> list[dict]:
    filters = {"opps": "gt.0"}
    if user:
        filters["user_id"] = f"eq.{user}"
    return list(page_all(table("learner_state"), "user_id,node_id,opps", filters=filters, order="user_id,node_id"))


def _evidence(node_id: str) -> list[dict]:
    return table("node_mastery_events").select(
        _EVIDENCE_COLS,
        filters={"node_id": f"eq.{node_id}", "event_type": "eq.evidence"},
        order="created_at.desc,id.desc",
        limit=BAND_WINDOW * 2,
    )


def report(usage: list[dict], steps: list[dict], caps: list[dict], *, sessions_by_request: dict[str, str]) -> dict:
    ...  # pure; §Behaviour A.1 cost and mix report


def main(argv: list[str] | None = None) -> int:
    ...  # --dry-run, --user, --expect-rows, --from, --to; prints per-row lines then "REPORT {json}"; returns 0/1/2


if __name__ == "__main__":
    sys.exit(main())
```

`limit=BAND_WINDOW * 2` leaves headroom for propagation rows that `_opportunities` drops; take the first `BAND_WINDOW` opportunities after filtering. `main` returns the exit code (the tests call it); `__main__` passes it to `sys.exit`.

Report (§Behaviour A.1): `SERIES_SLOTS` is the spec §8 invariant 6 tuple (the same eight literals as the invariants module's `SERIES_AGENT_TASKS`; `test_series_slots_are_invariant_6` pins it); `report(...)` sums `float(cost_usd or 0)` per key, never invents a band, a session or a zero count. `main` adds `--from`/`--to` (default `to = _now()`, `from = to − timedelta(weeks=KPI_TREND_WEEKS)`), reads `llm_usage` and `events` with `page_all(table(...), cols, filters={"created_at": [f"gte.{from}", f"lt.{to}"], …}, order="created_at,id")`, builds `sessions_by_request` from event rows whose `payload` carries `session_id`, and prints `REPORT ` + `json.dumps(report(...), sort_keys=True)` after the per-row lines, dry run or not. A read error there prints `REPORT_FAIL <table> <exc class>` and makes the exit code `1`; it never skips the derived-column pass. `_now()` is module-level so tests can freeze it. `main` adds `check_item_coverage` to the report dict after `report(...)` returns (a separate paged `graph_nodes` `course_id` read plus `check_item_service.coverage(course)` per course, patched by name in tests — add one test: two courses → `{"c1": [1, 2], "c2": [0, 3]}` in the printed JSON; a coverage read error → `REPORT_FAIL check_items <exc class>`, exit `1`).

- [ ] **Step 4: Run** `cd backend && venv/bin/python -m pytest tests/test_learning_zpd_metrics_script.py tests/test_learning_loop_invariants.py tests/test_learning_evidence_apply.py -q && venv/bin/ruff check .`
Expected: all passed (`inv_20`, `inv_01` now green); `All checks passed!`

- [ ] **Step 5: Commit**

```
git add backend/learning/learner_state.py backend/scripts/derive_zpd_metrics.py backend/tests/test_learning_zpd_metrics_script.py
git commit -m "feat(learning-loop): PKG-14a — nightly derive_zpd_metrics (htc_k, unassisted_next, assist_gap, in_zone) via write_metrics; cost per session/band, tier, cap and grader_backend mix

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task A4: Admin KPI endpoint

**Files:**
- Modify: `backend/routes/admin_analytics.py`
- Test: `backend/tests/test_admin_learning_loop_kpis.py`

**Interfaces:**
- Produces: `GET /api/admin/analytics/learning-loop` → `LearningLoopKpis` (fields in §Behaviour A.2); helpers `_rung_int(value) -> int | None`, `_phase_band(phase, assisted) -> tuple[float, float] | None`, `_in_band_share(steps)`, `_htc_k_trend(steps, to_iso)`, `_next_session_rate(evidence_rows)`, `_ceiling_compliance(steps)`.

- [ ] **Step 1: Write the failing test** (copy `_FakeTable` from `tests/test_admin_analytics_routes.py:63–110` into this module; do not import across test modules)

```python
"""PKG-14: /api/admin/analytics/learning-loop — the three KPIs and two gates of spec §10."""
from __future__ import annotations

import fnmatch

import pytest
from fastapi.testclient import TestClient

from main import app
import routes.admin_analytics as analytics
from learning import params

client = TestClient(app)
URL = "/api/admin/analytics/learning-loop"
RANGE = {"from": "2026-07-01T00:00:00+00:00", "to": "2026-08-01T00:00:00+00:00"}


class _FakeTable:  # verbatim copy of tests/test_admin_analytics_routes.py::_FakeTable
    ...


def _step(i, *, user="u1", concept="c1", phase="check", correct=True, assisted=False, max_rung=0, ceiling="H3", day=10):
    return {
        "event_type": "zpd.step", "category": "usage", "user_id": user, "request_id": f"r{i}",
        "payload": {"concept_id": concept, "phase": phase, "first_attempt_correct": correct, "assisted": assisted,
                    "max_rung_used": max_rung, "ceiling": ceiling},
        "created_at": f"2026-07-{day:02d}T00:{i:02d}:00+00:00",
    }


def _evidence(i, *, node="n1", session, correct=True, assisted=False, max_rung=0):
    return {"id": f"e{i}", "node_id": node, "event_type": "evidence", "session_id": session, "correct": correct,
            "assisted": assisted, "max_rung": max_rung, "question_hash": "q", "created_at": f"2026-07-10T01:{i:02d}:00+00:00"}


@pytest.fixture
def seeded(monkeypatch):
    W = params.BAND_WINDOW
    events = [_step(i, correct=True) for i in range(W)]          # 8 unassisted correct → window full
    events.append(_step(W, correct=True))                        # rolling rate 1.0 > PRACTICE_TARGET_HI → out of band
    events.append(_step(W + 1, correct=False))                    # rolling 1.0 still → out of band
    events.append(_step(30, user="u2", phase="teach"))            # no band → excluded
    events.append(_step(31, user="u2", max_rung=5, ceiling="H3")) # ceiling breach
    events.append({"event_type": "zpd.leak", "category": "error", "user_id": "u2", "request_id": "L",
                   "payload": {"rung_emitted": "H6", "ceiling": "H3"}, "created_at": "2026-07-12T00:00:00+00:00"})
    evidence = [_evidence(0, session="s1"), _evidence(1, session="s1", correct=False),
                _evidence(2, session="s2", correct=True), _evidence(3, session="s3", correct=True, assisted=True, max_rung=2)]
    store = {"events": events, "node_mastery_events": evidence, "learner_state": []}
    monkeypatch.setattr(analytics, "table", lambda name: _FakeTable(store.get(name, [])))
    return store


def test_kpis_shape_and_values(seeded):
    r = client.get(URL, params=RANGE)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["steps_total"] == params.BAND_WINDOW + 4
    assert b["banded_steps"] == 2 and b["in_band_share"] == pytest.approx(0.0)
    assert b["leak_count"] == 1
    assert b["ceiling_compliance"]["steps"] == params.BAND_WINDOW + 4
    assert b["ceiling_compliance"]["compliant"] == params.BAND_WINDOW + 3
    assert b["gates"] == {"zero_leaks": False, "ceiling_compliance_ok": False}
    assert b["unassisted_next_session"] == {"sessions": 2, "successes": 1, "rate": 0.5}
    trend = {t["concept_id"]: t for t in b["htc_k_trend"]}
    assert trend["c1"]["direction"] in {"falling", "flat", "rising", "insufficient"}
    assert b["truncated"] is False


def test_empty_range_is_nones_not_zeros(monkeypatch):
    monkeypatch.setattr(analytics, "table", lambda name: _FakeTable([]))
    b = client.get(URL, params=RANGE).json()
    assert b["in_band_share"] is None and b["ceiling_compliance"]["rate"] is None
    assert b["unassisted_next_session"]["rate"] is None
    assert b["gates"] == {"zero_leaks": True, "ceiling_compliance_ok": False}


@pytest.mark.parametrize("value,expected", [("H3", 3), (3, 3), ("h0", 0), (None, None), ("x", None)])
def test_rung_int(value, expected):
    assert analytics._rung_int(value) == expected


def test_phase_band_mapping():
    assert analytics._phase_band("probe", False) == (params.PROBE_TARGET_LO, params.PROBE_TARGET_HI)
    assert analytics._phase_band("check", True) == (params.ACQ_TARGET_LO, params.ACQ_TARGET_HI)
    assert analytics._phase_band("check", False) == (params.PRACTICE_TARGET_LO, params.PRACTICE_TARGET_HI)
    for p in ("teach", "feedback", "close", "plan", "posttest"):
        assert analytics._phase_band(p, False) is None


def test_requires_admin(monkeypatch):
    from services import auth_guard
    monkeypatch.setattr(analytics, "require_admin", auth_guard._real_require_admin)
    assert client.get(URL, params=RANGE).status_code in (401, 403)
```

- [ ] **Step 2: Run** `cd backend && venv/bin/python -m pytest tests/test_admin_learning_loop_kpis.py -v`
Expected: `404` on the first test; `AttributeError: module 'routes.admin_analytics' has no attribute '_rung_int'`.

- [ ] **Step 3: Implement.** Response models next to the existing ones (`WeekPoint`, `ConceptTrend`, `RateBlock{steps|sessions, compliant|successes, rate}`, `Gates`, `LearningLoopKpis`). The endpoint reads `events` via `_scan_range("events", "event_type,user_id,payload,created_at", …, extra_filters={"event_type": "in.(zpd.step,zpd.leak)"})` and `node_mastery_events` via `_scan_range("node_mastery_events", "id,node_id,session_id,correct,assisted,max_rung,question_hash,created_at", …, extra_filters={"event_type": "eq.evidence"})` (add an `in.(…)` op to your test fake only if `_FakeTable` lacks it — the real filter grammar supports it). Rolling windows: per `(user_id, concept_id)` list in `created_at` order; for step `k` of kind `kind` (`probe`, `check-assisted`, `check-unassisted`), the window is the previous `BAND_WINDOW` steps of the same kind; fewer → not banded. Weeks: `week_start` = Monday of the ISO week (`date.fromisocalendar`), only the last `KPI_TREND_WEEKS` weeks ending at `to`. `truncated` is the OR of both scans. Constants imported from `learning.params` — no literals.

- [ ] **Step 4: Run** `cd backend && venv/bin/python -m pytest tests/test_admin_learning_loop_kpis.py tests/test_admin_analytics_routes.py -q && venv/bin/ruff check .`
Expected: all passed; `All checks passed!`

- [ ] **Step 5: Commit**

```
git add backend/routes/admin_analytics.py backend/tests/test_admin_learning_loop_kpis.py
git commit -m "feat(learning-loop): PKG-14a — admin /learning-loop KPIs (in-band share, htc_k trend, next-session unassisted, leak + ceiling gates)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task A5: `zpd.rating` prompt (backend + frontend)

**Files:**
- Modify: `backend/routes/learn_loop.py`, `backend/models/__init__.py` (`LoopRatingBody`), `frontend/src/components/learn/LoopLearn.tsx`, `frontend/src/lib/api.ts`; only if HANDOFF-07 shows the `done` data is built solely inside `services/chat_stream.py`: add keyword-only `done_extra: dict | None = None` to `stream_agent_turn`, merged into the `done` event's data (record as a Deviation)
- Test: `backend/tests/test_learn_loop_rating.py`

- [ ] **Step 1: Write the failing test** (use the same client/auth/gate fixtures `tests/test_learn_loop_routes.py` uses — copy its top-of-file setup, including the `learning_loop_active` monkeypatch it uses to open the gate)

```python
"""PKG-14: perceived-difficulty prompt every ZPD_RATING_EVERY_N_CHECKS checks (spec §3.4, §6 zpd.rating)."""
from __future__ import annotations

import pytest

from learning import params
from services import events_service


def test_rating_404_when_gate_false(client, gate_off):
    r = client.post("/api/learn/loop/rating", json={"session_id": "s1", "rating": "too_easy"})
    assert r.status_code == 404 and r.json()["detail"] == "learning loop not enabled"


def test_rating_emits_event_and_resets_counter(client, gate_on, session_row, captured_events):
    session_row["loop_state"] = {"checks_since_rating": params.ZPD_RATING_EVERY_N_CHECKS}
    r = client.post("/api/learn/loop/rating", json={"session_id": session_row["id"], "rating": "too_hard"})
    assert r.status_code == 200 and r.json() == {"ok": True}
    (ev,) = [e for e in captured_events if e["event_type"] == "zpd.rating"]
    assert ev["payload"] == {"rating": "too_hard", "checks_since_last": params.ZPD_RATING_EVERY_N_CHECKS}
    assert session_row["loop_state"]["checks_since_rating"] == 0


def test_rating_rejects_unknown_value(client, gate_on, session_row):
    r = client.post("/api/learn/loop/rating", json={"session_id": session_row["id"], "rating": "meh"})
    assert r.status_code == 422


def test_done_carries_ask_rating_at_threshold(client, gate_on, session_row, run_check_answer):
    session_row["loop_state"] = {"checks_since_rating": params.ZPD_RATING_EVERY_N_CHECKS - 1}
    done = run_check_answer(session_row["id"])  # /check/answer/stream → the feedback turn's done data
    assert done["ask_rating"] is True


def test_done_omits_ask_rating_below_threshold(client, gate_on, session_row, run_check_answer):
    session_row["loop_state"] = {"checks_since_rating": 0}
    done = run_check_answer(session_row["id"])
    assert "ask_rating" not in done
    assert session_row["loop_state"]["checks_since_rating"] == 1


def test_plain_chat_turn_never_counts_as_a_check(client, gate_on, session_row, run_chat_turn):
    session_row["loop_state"] = {"phase": "check", "checks_since_rating": 3}
    done = run_chat_turn(session_row["id"], "is it the lexical scope?")  # typed in the check phase: not graded (A16)
    assert "ask_rating" not in done
    assert session_row["loop_state"]["checks_since_rating"] == 3
```

`gate_on`/`gate_off`/`session_row`/`captured_events`/`run_check_answer`/`run_chat_turn` are fixtures you write in this module from the building blocks `tests/test_learn_loop_routes.py` already uses (its mocked `table`, its function-mode handlers for `grader` and the three tutor slots, `events_service.flush_now()` with a captured `table("events").insert`). `run_check_answer` posts one genuine answer to `/api/learn/loop/check/answer/stream` and returns the `done` event's data; `run_chat_turn` posts to `/api/learn/loop/chat/stream`. Keep them local.

- [ ] **Step 2: Run** `cd backend && venv/bin/python -m pytest tests/test_learn_loop_rating.py -v`
Expected: first test `405`/`404` from a missing route (FastAPI returns 404 for an unknown path — the assertion on `detail` fails), the rest fail similarly.

- [ ] **Step 3: Implement** per §Behaviour A.3. `LoopRatingBody(session_id: str, rating: Literal["too_easy", "appropriate", "too_hard"])`. Increment the counter in the check-answer handler right after its `flush_pending` (both the JSON and the SSE variant); persist it with the other `loop_state` writes of that request through the insert-if-missing helper (A11; one write, not a second). `/rating` runs no model, so it takes no `enforce_rate_limit`. Frontend: in `LoopLearn.tsx` keep `askRating` state set from the `done` handler HANDOFF-13 describes; render the three buttons under `data-testid="loop-rating"`; on click call `submitLoopRating(sessionId, rating)` then hide. `api.ts`: `export const submitLoopRating = (sessionId: string, rating: "too_easy" | "appropriate" | "too_hard") => fetchJSON<{ ok: true }>("/api/learn/loop/rating", { method: "POST", body: JSON.stringify({ session_id: sessionId, rating }) });`.

- [ ] **Step 4: Run** `cd backend && venv/bin/python -m pytest tests/test_learn_loop_rating.py tests/test_learn_loop_routes.py tests/test_event_capture_seams.py -q && venv/bin/ruff check . && cd ../frontend && npx tsc --noEmit`
Expected: all passed; `All checks passed!`; tsc clean.

- [ ] **Step 5: Commit**

```
git add backend/routes/learn_loop.py backend/models/__init__.py backend/tests/test_learn_loop_rating.py frontend/src/components/learn/LoopLearn.tsx frontend/src/lib/api.ts
git commit -m "feat(learning-loop): PKG-14a — zpd.rating prompt every ZPD_RATING_EVERY_N_CHECKS checks

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

(Add `backend/services/chat_stream.py` to the `git add` only if the `done_extra` kwarg was needed.)

### Task A6: Tool-removed post-test

**Files:**
- Modify: `backend/routes/learn_loop.py`, `backend/models/__init__.py` (`PosttestStartBody`, `PosttestAnswerBody`), `backend/learning/params.py` (`POSTTEST_*` already added in A2 — verify), every `Literal` that types `zpd.step.phase`, `backend/tests/test_learning_loop_invariants.py` (the post-test answer handler joins `test_inv_26`'s allow-list — the only edit there)
- Test: `backend/tests/test_learning_posttest.py`

- [ ] **Step 1: Write the failing test**

```python
"""PKG-14 rung 3: tool-removed, delayed post-test (spec §10; research §"Measure learning…"; A16, A23)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from learning import params

NOW = datetime(2026, 9, 26, tzinfo=timezone.utc)
OLD = (NOW - timedelta(days=params.POSTTEST_MIN_AGE_DAYS + 1)).isoformat()
FRESH = (NOW - timedelta(hours=1)).isoformat()
MID = params.CHECK_ITEM_DIFFICULTIES[1]


def test_posttest_404_when_gate_false(client, gate_off):
    assert client.post("/api/learn/loop/posttest/start", json={"course_id": "c"}).status_code == 404
    assert client.post("/api/learn/loop/posttest/answer", json={"node_id": "n", "question_hash": "q", "answer": "x"}).status_code == 404


def test_start_serves_only_concepts_taught_long_enough_ago(client, gate_on, tables, freeze_now, seen_revealed):
    freeze_now(NOW)
    seen_revealed(seen=set(), revealed=set())
    tables["learner_state"] = [
        {"user_id": "u", "node_id": "n-old", "last_evidence_at": OLD},
        {"user_id": "u", "node_id": "n-fresh", "last_evidence_at": FRESH},
        {"user_id": "u", "node_id": "n-none", "last_evidence_at": None},
    ]
    tables["graph_nodes"] = [{"id": "n-old", "course_id": "c", "concept_name": "old"},
                             {"id": "n-fresh", "course_id": "c", "concept_name": "fresh"},
                             {"id": "n-none", "course_id": "c", "concept_name": "none"}]
    tables["check_items"] = [item("old", "q-old", fmt="free", difficulty=MID), item("fresh", "q-fresh", fmt="free", difficulty=MID)]
    r = client.post("/api/learn/loop/posttest/start", json={"course_id": "c"})
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert [i["node_id"] for i in items] == ["n-old"]
    assert items[0]["prompt"] == "What is a closure?"  # decrypted
    assert set(items[0]) == {"node_id", "question_hash", "format", "difficulty", "prompt", "options"}
    assert items[0]["options"] is None  # free item


def test_start_serves_the_reserve_and_never_a_seen_or_revealed_item(client, gate_on, tables, freeze_now, seen_revealed):
    freeze_now(NOW)
    tables["learner_state"] = [{"user_id": "u", "node_id": "n1", "last_evidence_at": OLD},
                               {"user_id": "u", "node_id": "n2", "last_evidence_at": OLD},
                               {"user_id": "u", "node_id": "n3", "last_evidence_at": OLD}]
    tables["graph_nodes"] = [{"id": f"n{i}", "course_id": "c", "concept_name": f"k{i}"} for i in (1, 2, 3)]
    tables["check_items"] = [
        item("k1", "a-res", fmt="free", difficulty=MID), item("k1", "b-other", fmt="free", difficulty=MID),  # reserve a-res unseen
        item("k2", "c-res", fmt="free", difficulty=MID), item("k2", "d-other", fmt="free", difficulty=MID),  # reserve revealed → d-other
        item("k3", "e-res", fmt="free", difficulty=MID),                                                    # only item seen → skipped
    ]
    seen_revealed(seen={"e-res"}, revealed={"c-res"})
    items = client.post("/api/learn/loop/posttest/start", json={"course_id": "c"}).json()["items"]
    assert sorted((i["node_id"], i["question_hash"]) for i in items) == [("n1", "a-res"), ("n2", "d-other")]


def test_start_serves_mc_reason_options_without_keys(client, gate_on, tables, freeze_now, seen_revealed):
    freeze_now(NOW)
    seen_revealed(seen=set(), revealed=set())
    tables["learner_state"] = [{"user_id": "u", "node_id": "n1", "last_evidence_at": OLD}]
    tables["graph_nodes"] = [{"id": "n1", "course_id": "c", "concept_name": "k1"}]
    tables["check_items"] = [item("k1", "q1", fmt="mc_reason", difficulty=MID)]
    (served,) = client.post("/api/learn/loop/posttest/start", json={"course_id": "c"}).json()["items"]
    assert served["options"] and all(set(o) == {"letter", "text"} for o in served["options"])  # no wrong_key, no correctness


def test_start_caps_items_oldest_first(client, gate_on, tables, freeze_now, seen_revealed):
    freeze_now(NOW)
    seen_revealed(seen=set(), revealed=set())
    n = params.POSTTEST_MAX_ITEMS + 2
    tables["learner_state"] = [{"user_id": "u", "node_id": f"n{i}", "last_evidence_at": (NOW - timedelta(days=params.POSTTEST_MIN_AGE_DAYS + i)).isoformat()} for i in range(n)]
    tables["graph_nodes"] = [{"id": f"n{i}", "course_id": "c", "concept_name": f"k{i}"} for i in range(n)]
    tables["check_items"] = [item(f"k{i}", f"q{i}") for i in range(n)]
    items = client.post("/api/learn/loop/posttest/start", json={"course_id": "c"}).json()["items"]
    assert len(items) == params.POSTTEST_MAX_ITEMS
    assert items[0]["node_id"] == f"n{n - 1}"  # oldest evidence first


def test_answer_grades_through_grade_answer_and_records_unassisted_evidence(client, gate_on, tables, grader_says, applied, captured_events):
    tables["check_items"] = [item("k1", "q1", fmt="free")]
    tables["graph_nodes"] = [{"id": "n1", "course_id": "c", "concept_name": "k1"}]
    grader_says(correct=True, confidence=0.9)
    r = client.post("/api/learn/loop/posttest/answer", json={"node_id": "n1", "question_hash": "q1", "answer": "a function with its lexical scope"})
    assert r.status_code == 200 and r.json() == {"correct": True, "confidence": 0.9}
    (call,) = applied
    (ev,) = call["graph_update"]["evidence"]
    assert ev["assisted"] is False and ev["max_rung"] == 0 and ev["session_id"] is None
    assert ev["channel"] == "free_response" and ev["question_hash"] == "q1"
    assert ev["grader_backend"] is not None  # set by grade_answer (A22)
    (step,) = [e for e in captured_events if e["event_type"] == "zpd.step"]
    assert step["payload"]["phase"] == "posttest"
    assert step["payload"]["max_rung_used"] == 0 and step["payload"]["assisted"] is False
    assert "tier" not in step["payload"]  # no tutor turn ran: omitted, never zeroed


def test_answer_idk_is_incorrect_idk_evidence(client, gate_on, tables, grader_says, applied):
    tables["check_items"] = [item("k1", "q1", fmt="free")]
    tables["graph_nodes"] = [{"id": "n1", "course_id": "c", "concept_name": "k1"}]
    grader_says(correct=True, confidence=0.9)  # must not be consulted
    r = client.post("/api/learn/loop/posttest/answer", json={"node_id": "n1", "question_hash": "q1", "answer": "", "idk": True})
    assert r.status_code == 200 and r.json()["correct"] is False
    (ev,) = applied[0]["graph_update"]["evidence"]
    assert ev["idk"] is True and ev["correct"] is False and ev["channel"] == "free_response"  # A1


@pytest.mark.parametrize("correct_attempt", [True, False])
def test_answer_grader_unavailable_is_503_and_writes_nothing(client, gate_on, tables, grader_unavailable, applied, captured_events, correct_attempt):
    tables["check_items"] = [item("k1", "q1")]
    tables["graph_nodes"] = [{"id": "n1", "course_id": "c", "concept_name": "k1"}]
    answer = "a function with its lexical scope" if correct_attempt else "a loop"
    r = client.post("/api/learn/loop/posttest/answer", json={"node_id": "n1", "question_hash": "q1", "answer": answer})
    assert r.status_code == 503 and r.json()["detail"] == "grader unavailable"
    assert applied == [] and not [e for e in captured_events if e["event_type"] == "zpd.step"]  # symmetric (inv 28)


def test_posttest_is_a_step_phase_value_not_a_close_phase():
    import glob
    sql = "".join(open(p).read() for p in glob.glob("db/migrations/*_learning_session_close.sql"))
    assert "posttest" not in sql
    from routes import learn_loop
    assert "posttest" in learn_loop.STEP_PHASES
```

`item(concept_key, question_hash, fmt="free", difficulty=MID)` builds a `check_items` row keyed per A2 (`course_id="c"`, `concept_key`) with `services.encryption.encrypt_if_present` on `prompt`/`reference_answer`/`correct_option`/`canonical_answer`/`final_answer` (§13 A34: every fixture item states a non-empty `final_answer` its reference contains — `checks.select_item` and `checks.posttest_reserve_hash` skip an item without one, so a fixture row without it would never be served and these tests would fail as written) and `encrypt_json` on `rubric_json`/`common_wrong_json`/`options_json` (an `mc_reason` row gets four options, one correct, distractors keyed to its wrong keys — the same helper `tests/test_learning_check_items.py` uses; copy it). The fixture `graph_nodes` use lowercase single-word `concept_name`s so `_normalize_concept(concept_name)` equals the key. `seen_revealed(seen=, revealed=)` monkeypatches the `seen_hashes`/`revealed_hashes` names `learn_loop` imports from `learning.loop_state_store`. `grader_says`/`grader_unavailable` monkeypatch the grader call `grade_answer` makes (HANDOFF-05/05b — the `services.decisions` function it calls, or `agents.grader.grade` underneath), so the real `grade_answer` builds the Evidence; `applied` monkeypatches the `apply_graph_update` name `flush_pending` calls (HANDOFF-05) to record calls and return `[{"node_id": "n1", "before": 0.35, "after": 0.71}]`; `freeze_now` monkeypatches the module's `_now()`; `tables` is a dict served by a `_mock_table`-style factory for every `table` the route module and `check_item_service` import; `client`/`gate_on`/`gate_off`/`captured_events` come from the same building blocks as Task A5 (the rate-limit dependency is a no-op under the mocked `llm_usage`). Keep them local.

- [ ] **Step 2: Run** `cd backend && venv/bin/python -m pytest tests/test_learning_posttest.py -v`
Expected: 404s on the second test onward (`assert 404 == 200`), `AttributeError: … has no attribute 'STEP_PHASES'`.

- [ ] **Step 3: Implement** per §Behaviour A.4. Define `STEP_PHASES: tuple[str, ...]` in `routes/learn_loop.py` if PKG-07 typed the phase inline (otherwise extend PKG-07's `Literal` and alias it). The node→course filter: read `graph_nodes` `id,course_id,concept_name` for the candidate node ids in one `in.(…)` select; `concept_key` via `graph_service._normalize_concept` (never re-implemented). Selection uses `checks.posttest_reserve_hash` and `checks.select_item(…, exclude_hashes=…)` (HANDOFF-04), with `seen_hashes`/`revealed_hashes` read once per request. The answer handler builds `CheckAnswer` and `SaplingDeps` exactly as PKG-07's check-answer handler does (HANDOFF-07), calls `grade_answer`, then `flush_pending` once; add its function name to `test_inv_26`'s allow-list in `tests/test_learning_loop_invariants.py`. Attach `Depends(ai_budget.enforce_rate_limit)` to `/posttest/answer` only. `_now()` is a module-level function (`datetime.now(timezone.utc)`) so tests can freeze it. Emit through `learning/zpd_events.emit_zpd_step` (PKG-06) with every §6 key it takes; the ones without a meaning here are `None` (`rungs: []`, `time_to_first_attempt_ms: None`, `tier=None` — which the helper omits, …) — never fabricated.

- [ ] **Step 4: Run** `cd backend && venv/bin/python -m pytest tests/test_learning_posttest.py tests/test_learn_loop_routes.py tests/test_learning_loop_invariants.py -q -k "posttest or loop_routes or inv_05 or inv_26 or inv_28" && venv/bin/ruff check .`
Expected: all passed; `All checks passed!`

- [ ] **Step 5: Commit**

```
git add backend/routes/learn_loop.py backend/models/__init__.py backend/tests/test_learning_posttest.py backend/tests/test_learning_loop_invariants.py backend/learning/params.py
git commit -m "feat(learning-loop): PKG-14a — tool-removed post-test (/posttest/start, /posttest/answer; reserve item, grade_answer, ceiling H0, no RAG, no brief)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task A7: Evals (leakage + sycophancy fixtures per tier slot, `run_all`) and the cutover ADR

**Files:**
- Modify: `backend/tests/evals/loop_tutor.py`, `backend/tests/evals/run_all.py`, `backend/tests/evals/baselines.json`, `backend/tests/evals/cassettes/loop_tutor/*` (recorded, per tier slot)
- Create: `docs/decisions/<next>-learning-loop-cutover.md` (0028 expected — `ls docs/decisions | tail -1` shows PKG-05b's decision-seam ADR; take the next free number)

- [ ] **Step 1: Gap check.** Read HANDOFF-07 "Known gaps" and `grep -n "leak\|sycophan\|insists\|ceiling" backend/tests/evals/loop_tutor.py`. For each of (2 answer-leak, 2 sycophancy, 1 ceiling-compliance) missing, add a `Case` with `metadata={"kind": "leak"|"sycophancy"|"ceiling", ...}` and, if absent, the evaluator: `NoAnswerLeakEvaluator` (uses `learning.leak.detect_leak(reference, emitted, rung, final_answer=...)` with the fixture's reference answer and its structured final answer in metadata, §13 A34), `NoSycophancyEvaluator` (reply must contain a marker from a module-level `CONTRADICTION_MARKERS` tuple AND end with a question), `CeilingComplianceEvaluator` (cassette `tool_calls`/metadata rung ≤ metadata ceiling). Total cases ≤ 8. Every case runs on every tier slot PKG-07's harness iterates (`loop_tutor_lite`, `loop_tutor`, `loop_tutor_deep` — A15); do not add a slot loop of your own.
- [ ] **Step 2:** `run_all.py::DATASETS` = existing + `"check_items", "grader", "decisions", "loop_tutor"` (only the ones missing; `decisions` is PKG-05b's). Run `cd backend && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/run_all.py` → the new cases fail with `No cassette for loop_tutor/<case>`.
- [ ] **Step 3:** Record ONLY the new cases of the `loop_tutor` dataset, for every tier slot (`SAPLING_EVAL_MODE=record venv/bin/python tests/evals/loop_tutor.py`, needs `GEMINI_API_KEY`), eyeball the deltas, then `SAPLING_EVAL_UPDATE_BASELINES=1 venv/bin/python tests/evals/loop_tutor.py`. Re-run replay: every evaluator ≥ baseline for every tier slot. A slot that fails a new evaluator is not routable (A15): stop and record it in the hand-off (Known gaps) rather than loosening the evaluator.
- [ ] **Step 4:** Write the cutover ADR per §Behaviour A.6. Status `accepted`, Date today, `Relates to:` the spec path, ADR 0024 (honest degrade), the decision-seam ADR (PKG-05b), ADR 0015 (the tutor being replaced), `#620` (no flag system). The Decision section states the default-on rule (A14), the two-phase flag and kill-switch semantics (spec §7, §11.6), `learning_loop_beta` as a build-phase staff/QA toggle retired at half B, the cost guardrails (A15/A18/A20/A21), and the deferred `chat_tutor` fold; Consequences lists both dead columns and the PKG-00 migration-header note.
- [ ] **Step 5: Run** `cd backend && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/run_all.py && venv/bin/ruff check .`
Expected: `PASS` for every dataset; `All checks passed!`
- [ ] **Step 6: Commit** (cassettes + baselines together, as `tests/evals/README.md` requires)

```
git add backend/tests/evals/loop_tutor.py backend/tests/evals/run_all.py backend/tests/evals/baselines.json backend/tests/evals/cassettes/loop_tutor docs/decisions/*-learning-loop-cutover.md
git commit -m "evals(learning-loop): PKG-14a — leak + sycophancy + ceiling fixtures per tier slot, run_all covers series datasets; cutover ADR

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task A8: Hand-off + ledger (half A)

- [ ] **Step 1:** Write `docs/superpowers/plans/learning-loop/HANDOFF-14.md` from the template with a first line `Half A only — half B (cutover) pending the series owner's confirmation.` "Verify commands" for half A:

```
cd backend && venv/bin/python -m pytest tests/test_learning_zpd_metrics_script.py tests/test_admin_learning_loop_kpis.py tests/test_learn_loop_rating.py tests/test_learning_posttest.py tests/test_learning_arms.py -q → all passed
cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_20 or inv_01" → 2 passed
ls backend/db/migrations/*_learning_loop_arm.sql                                                  → 1 file
ls docs/decisions/*learning-loop-cutover*.md                                                      → 1 file
cd backend && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/run_all.py                    → PASS for every dataset
```

Constants chosen: every † row of the table. Symbols added include the cutover ADR's actual number. Deviations: `write_metrics` (spec §5 says only `apply_graph_update` writes `learner_state`); the post-test fallback to `select_item` when a concept's reserve is already seen or revealed (†); `done_extra` if used (`variant` and `posttest` are in spec §6/§13 A8 — not deviations). Known gaps: earnest-revise gate not measured; rating prompt not E2E-covered (needs 30 checks); `loop_arm` NULL for everyone until the owner picks an experiment; cost is reported per user-day, not per session, if no session key was reachable (§Behaviour A.1); any tier slot that failed a new evaluator (not routable, A15). Open questions: which experiment first (the `independent_min_s` candidate or a tier policy such as standard vs deep for develop-band teach); arm analysis = intention-to-treat + tier served (`zpd.step.tier`) + cap-hit covariate.
- [ ] **Step 2:** Append ledger row `| 14 | eval-ladder-cutover | done (half A) | feat/learning-loop-14a-eval-ladder | <sha> | 6 modules | — | HANDOFF-14.md |` plus the Deviations lines.
- [ ] **Step 3: Commit**

```
git add docs/superpowers/plans/learning-loop/HANDOFF-14.md docs/superpowers/plans/learning-loop/LEDGER.md
git commit -m "docs(learning-loop): PKG-14a — hand-off and ledger (half A)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task A9: PR (half A)

- [ ] Run the full self-check loop once more, then:

```
gh pr create --title "feat(learning): PKG-14a eval ladder" --body-file - <<'EOF'
Learning loop series, package 17 of 17, half A (evaluation ladder). Spec §10: docs/superpowers/specs/2026-09-26-learning-loop-design.md. Cutover ADR <number> (docs/decisions/<number>-learning-loop-cutover.md).

- scripts/derive_zpd_metrics.py — nightly htc_k / unassisted_next / assist_gap / in_zone via learner_state.write_metrics (idempotent, --dry-run, exit 2 on silent-empty); REPORT line: cost per session (or per user-day) and per band, tier mix, cap hits, grader_backend mix
- GET /api/admin/analytics/learning-loop — in-band share, htc_k trend, next-session unassisted success, leak count, ceiling compliance + gates
- zpd.rating prompt every ZPD_RATING_EVERY_N_CHECKS checks, counted in the check-answer handler (POST /api/learn/loop/rating; LoopLearn three-button prompt)
- tool-removed post-test: POST /api/learn/loop/posttest/{start,answer} (the concept's reserve item, never a seen/revealed one; grades through grade_answer; ceiling H0, no RAG, no brief, assisted=False evidence; joins the inv 26 allow-list)
- user_settings.loop_arm + policy.variant_for (within-student arms; inert while NULL); arm sessions pass arm_session=True to ai_budget.check / policy.model_tier
- evals: leak + sycophancy + ceiling fixtures on every tier slot; run_all covers check_items/grader/decisions/loop_tutor
- cutover ADR: default-on decision (A14), two-phase flag + kill switch, cost guardrails, launch plan
- invariants 20 (+ inv_01 write_metrics seam, inv_26 allow-list)

Still dark behind LEARNING_LOOP_ENABLED (default off during the build). Half B (the launch) is a separate PR that makes the loop the default for every student, no opt-in (spec §13 A14).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
```

---

# Half B — STOP gate

Do not start half B in the same sitting as half A. Preconditions — the spec §11.1 launch gate, all eight (1–7 and 3b), verbatim; ask the series owner to confirm each item git cannot show, and do not infer any of them from git:

1. Half A merged; `LEDGER.md` row 14 reads `done (half A)`; the latest row of each of 00–13, 05b, 06b is `done`, `verified` or `reopened` (README "Ledger reading").
2. CI green on `main`, including every test in `frontend/e2e/learn-loop.spec.ts` (loop journey, resume, budget cap) and `python -m e2e_oracles`; the no-check-items state is covered by PKG-13's vitest and PKG-08's route test.
3. Staging has check items for the smoke course, then the staging smoke passes. Uploads made before staging's flag went `true` (spec §7 table: from PKG-07) drafted no items — the ingest hook runs only on uploads — so the owner first runs the staging backfill: `cd backend && dotenv -f .env.staging run -- env LEARNING_LOOP_ENABLED=true venv/bin/python scripts/backfill_check_items.py --all-courses --project <staging ref> --dry-run` (the printed `Project:` line is the staging ref), then the same without `--dry-run`; the smoke course prints `coverage <course_id> N/M` with N > 0. Smoke under the build-phase config (env `true`; a staff/QA account with `learning_loop_beta` set by SQL): probe → plan → teach → check (the pose appears and `/check/answer` grades it) → close completes.
3b. Kill-switch mechanics drilled on staging: the owner sets staging `LEARNING_LOOP_ENABLED=false` and redeploys → `/api/learn/loop/status` 404, `/learn` shows `tutor-topic-picker`, `/study` hides `review-due-panel`, an upload drafts no `check_items` rows; then restores the value, redeploys, and `/status` is active again. (This proves the switch works as a redeployed env change on the real host; spec §11.7 step 4 repeats the drill on the half B code before anything reaches production.)
4. Cost guardrails implemented and verified: **A15 routing** (`policy.model_tier` + the three tier slots; loop routes ignore `model_pref`, invariant 22; each tier passed the per-tier evals), **A18 limits** (`LOOP_LIMITS` 4/3/40_000 and per-run `max_tokens`), **A20 cost guard** (`services/ai_budget.py` caps and degradation ladder; invariants 23 and 28; the PKG-13 budget-cap journey), **A21 usage observability** (the staging smoke's `llm_usage` rows carry tier slot names in `task` and non-null `cached_tokens`/`thinking_tokens`). The owner has approved the projected cost: staging smoke `llm_usage` cost per session × expected sessions, against the ≈ $0.36/student-month target. **Platform alert:** the owner has chosen the production `PLATFORM_DAILY_BUDGET_USD` (suggested ≈ 3× the projected daily spend: 3 × $0.36 × active students ÷ 30) and has confirmed on staging, with a deliberately low value, that an `ai.budget_capped{scope: platform}` alert reaches them (unset = no alert, spec §3.5).
5. Launch UI readiness (spec §11.3) is merged.
6. The owner confirms production is pinned `LEARNING_LOOP_ENABLED=false` (spec §11.7 step 1), and confirms they have read spec §11.7's opening paragraph: the first `make promote` after the half B merge launches half B's ungated changes for every production student whatever the pin says, so the merge waits until steps 3–10 fit one attended window, and spec §11.7 "Rollback" is the way back.
7. The owner writes an explicit go-ahead in the session ("Launch approved — make the loop the default"). A message from an agent, a ticket comment, or silence is not authorisation.

If any is missing: append a ledger row `| 14 | eval-ladder-cutover | blocked | — | — | — | awaiting launch gate (spec §11.1) | HANDOFF-14.md |`, stop, and say so. Otherwise re-run every "State of the world" row plus the half A verify block, then continue.

# Half B — cutover (`feat/learning-loop-14b-cutover`)

Branch from `main` after half A merged. Read HANDOFF-14 (half A) first.

## Tasks

### Task B1: Invariants — `test_inv_21`, rewrite `test_inv_11`

**Files:**
- Modify: `backend/tests/test_learning_loop_invariants.py`

- [ ] **Step 1: Append / rewrite**

```python
LEGACY_MASTERY_SYMBOLS = ("mastery_delta", "MASTERY_DELTA_PER", "get_mastery_tier")


def test_inv_21_no_legacy_mastery_writers():
    """Spec §11: after cutover, only graded evidence can move a belief."""
    hits = []
    for path in BACKEND.rglob("*.py"):
        rel = path.relative_to(BACKEND)
        if rel.parts[0] in ("venv", "learning") or rel.name == "test_learning_loop_invariants.py":
            continue
        for i, line in enumerate(path.read_text().splitlines(), 1):
            for sym in LEGACY_MASTERY_SYMBOLS:
                if sym in line:
                    hits.append(f"{rel}:{i}: {sym}")
    assert hits == [], "legacy mastery writers survive cutover:\n" + "\n".join(hits)
```

Rewrite `test_inv_11_gate_false_when_env_unset` in place (keep the name — never delete a test here; spec §8 invariant 11), parametrized over the spec §7 post-launch parse table:

```python
@pytest.mark.parametrize("raw,expected", [
    (None, True), ("", True), ("true", True), ("1", True), ("yes", True),
    ("false", False), ("FALSE", False), (" False ", False), ("0", False), ("off", False), ("no", False),
])
def test_inv_11_gate_false_when_env_unset(monkeypatch, raw, expected):
    """The name is historical: in the build phase an unset LEARNING_LOOP_ENABLED meant False.
    Post-launch (PKG-14b, spec §7, §13 A14) the env var is a kill switch that defaults ON:
    unset or "" → True for every user; any of false/0/off/no (any case, whitespace ignored) → False.
    There is no student opt-in, so the gate reads no table in either case."""
    import config

    # PKG-00's helper (this module): hermetic against backend/.env (load_dotenv is a
    # no-op for the reload) and registers every rebound attribute for undo, so the
    # recomputed flag never leaks into later modules. None = unset.
    gate = reload_gate(monkeypatch, raw)
    assert config.LEARNING_LOOP_ENABLED is expected
    assert not hasattr(gate, "table"), "post-launch learning/gate.py imports no table(): nothing to read"
    for uid in ("user_andres", "e2e-student", "nobody"):
        assert gate.learning_loop_active(uid) is expected
```

(If the module does not import `pytest` at the top yet, add it.) Never a bare `importlib.reload(config)` / `importlib.reload(gate)` here: `config.py` calls `load_dotenv()` at import, so the `(None, True)` case would depend on the developer's `backend/.env`, and nothing would restore the flag afterwards — the last case's `False` would leak into every later module and hide default-on breakages. `reload_gate` (PKG-00, `tests/test_learning_loop_invariants.py`) handles both; `monkeypatch` undo restores `config` and `gate` after each case.

- [ ] **Step 2: Run** `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_21 or inv_11"`
Expected: `inv_21` FAIL with a long hit list (`config.py`, `services/quiz_config.py`, `agents/tools/graph.py`, `routes/quiz.py`, `services/graph_service.py`, seeds, tests…); `inv_11` FAIL on every case (the build-phase parse makes unset/`""`/`1`/`yes` False, and `gate.table` still exists). Save the hit list — it is your worklist for B2–B5.

- [ ] **Step 3: Commit**

```
git add backend/tests/test_learning_loop_invariants.py
git commit -m "test(learning-loop): PKG-14b — inv_21 no legacy mastery writers; inv_11 kill-switch semantics (spec §7 parse table)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task B2: Remove the tutor mastery tool; retire the mastery evaluator; re-record chat_tutor cassettes

The `chat_tutor` mode-prompt fold into `loop_tutor` is NOT part of this task (§Behaviour B.7: deferred to the follow-up that deletes `LEARNING_LOOP_ENABLED`). The legacy agents are the kill-switch path and stay.

**Files:**
- Modify: `backend/agents/tools/graph.py`, `backend/agents/chat_tutor.py` (delete the `:84–91` preamble paragraph; `_build_tools(learning_loop=False)` drops `update_mastery_tool`; nothing else), `backend/services/graph_service.py` (delete the `updated_nodes` branch), `backend/agents/deps.py` (drop `mastery_changes` only if no reader remains — `grep -rn mastery_changes backend/`), `backend/tests/evals/chat_tutor.py`, `backend/tests/evals/baselines.json`, `backend/tests/evals/cassettes/chat_tutor/*`, `backend/tests/test_graph_tools_bugs.py` (delete the `update_mastery_tool` classes), `backend/tests/test_prompt_injection.py:399–413` (delete that test; its docstring line 28), `backend/tests/test_graph_service.py` (delete the `updated_nodes` tests at `:612–730`, `:809`, `:871–910`, `:1014`, `:1075` — verify each tests the deleted branch before deleting), `backend/tests/test_shared_course_context.py:440–497` (rewrite to drive `apply_graph_update` with `evidence` instead of `updated_nodes`), any test that counts the legacy tool set (`grep -rn "_build_tools" backend/tests`)
- Test: `backend/tests/test_cutover_tutor.py`

- [ ] **Step 1: Write the failing test**

```python
"""PKG-14b: the mastery tool is gone; the legacy chat_tutor agents stay for the kill switch (spec §11.2, §11.6)."""
import pytest


def test_mastery_tool_symbols_are_gone():
    import agents.tools.graph as g
    for name in ("update_mastery_tool", "MasteryUpdateInput", "ConceptMasteryUpdate", "TUTOR_EVENT_TYPES"):
        assert not hasattr(g, name), name


def test_preamble_no_longer_instructs_mastery_writes():
    import agents.chat_tutor as ct
    assert "update_mastery_tool" not in ct._SHARED_PREAMBLE and "+0.1 to +0.3" not in ct._SHARED_PREAMBLE


def test_legacy_tool_set_drops_only_the_mastery_tool():
    from agents.chat_tutor import _build_tools
    names = {getattr(t, "name", getattr(t, "__name__", "")) for t in _build_tools(learning_loop=False)}  # adapt to _build_tools' return shape
    assert "update_mastery_tool" not in names
    assert len(names) == 6, names  # spec §7: today's seven legacy tools minus the mastery tool


def test_legacy_agents_are_kept_for_the_kill_switch():
    from agents.chat_tutor import expository_agent, socratic_agent, teachback_agent
    from agents.loop_tutor import loop_tutor_agent
    legacy = (socratic_agent, expository_agent, teachback_agent)
    assert len({id(a) for a in legacy}) == 3
    assert all(a is not loop_tutor_agent for a in legacy)


def test_apply_graph_update_rejects_updated_nodes():
    from services.graph_service import apply_graph_update
    with pytest.raises(ValueError, match="updated_nodes"):
        apply_graph_update("u", {"updated_nodes": [{"concept_name": "X"}]}, "c")
```

- [ ] **Step 2: Run** `cd backend && venv/bin/python -m pytest tests/test_cutover_tutor.py -v` → FAIL on the mastery-tool, preamble, tool-set and `updated_nodes` tests; `test_legacy_agents_are_kept_for_the_kill_switch` already passes (it pins what must not change).

- [ ] **Step 3: Implement** per §Behaviour B.1, B.7, B.8. `apply_graph_update` raises `ValueError("updated_nodes is no longer accepted (PKG-14b): pass evidence")` when the key is present — loud, not silent. `loop_tutor.py` and `routes/learn.py` are not touched here. `tests/evals/chat_tutor.py`: drop `MASTERY_DELTA_MIN/MAX`, `_mastery_updates`, `MasteryUpdateEmittedEvaluator` and the stub's `mastery_delta` handling; drop the `expects_mastery_update` tag from `CASES` (no replacement tag — no evidence evaluator exists for the legacy tutor); `NoToolMisuseEvaluator` keeps `update_mastery_tool` in `BANNED_SUBSTRINGS`. Delete `cassettes/chat_tutor/`, re-record against the edited preamble (`SAPLING_EVAL_MODE=record venv/bin/python tests/evals/chat_tutor.py`), update baselines. The `chat_tutor` `AgentTask`, `_DEFAULTS` entry and `E2E_TUTOR_REPLY` handler stay; write "chat_tutor kept for the kill switch until the env-var-removal ticket" in the hand-off.

- [ ] **Step 4: Run** `cd backend && venv/bin/python -m pytest tests/ -q && venv/bin/ruff check . && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/run_all.py`
Expected: zero failures apart from `inv_21` and `inv_11` (B3–B5 finish them); `All checks passed!`; every dataset `PASS` (`loop_tutor`, `grader`, `check_items`, `decisions` baselines unmoved).

- [ ] **Step 5: Commit** (one commit; the message lists every deleted test by name)

```
git add -A backend/agents backend/services/graph_service.py backend/tests
git commit -m "feat(learning-loop): PKG-14b — remove update_mastery_tool and the updated_nodes path; retire the mastery evaluator; chat_tutor cassettes re-recorded (legacy agents kept for the kill switch)

Deleted tests (their code is deleted in this commit): <list>

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task B3: Quiz — evidence only; `p_delta` on the wire; E2E expectation

**Files:**
- Modify: `backend/services/quiz_config.py`, `backend/routes/quiz.py`, `backend/routes/flashcards.py` (drop the PKG-11 gate branch), `backend/services/events_service.py:46` (docstring row: `mastery_delta` → `p_delta`), `backend/tests/test_quiz_scoring_e.py`, `backend/tests/test_quiz_routes.py:38`, `:186–208`, `:675–678`, `backend/tests/test_quiz_lifecycle_d.py:474–478`, `backend/tests/test_event_capture_seams.py:956`, `backend/tests/integration/test_quiz_lifecycle_db.py:42–51`, `backend/tests/test_learning_flashcards_fsrs.py` (gate tests → ungated), `frontend/src/components/screens/Tree.tsx:34`, `:405`, `frontend/src/components/screens/Tree.quiz.test.tsx`, `frontend/src/lib/api.ts` (attempt type), `frontend/e2e/support/quiz.ts`, `frontend/e2e/quiz.spec.ts`, `frontend/e2e/quiz-integration.spec.ts:50`, `:130` (flat `3 * 0.03` → `bktAfterCorrect`; its AskPanel assertions are Task B5b's)
- Test: `backend/tests/test_quiz_evidence_only.py`

- [ ] **Step 1: Write the failing test**

```python
"""PKG-14b: submit_quiz moves mastery only through evidence; the flat delta model is gone."""
import re
from pathlib import Path

import pytest

from learning import params
from learning.bkt import update  # PKG-01 signature per HANDOFF-01


def test_quiz_config_has_no_delta_model():
    import services.quiz_config as qc
    for name in ("MASTERY_DELTA_PER_CORRECT", "MASTERY_DELTA_PER_WRONG", "mastery_after"):
        assert not hasattr(qc, name), name


def test_three_mc_corrects_from_prior():
    p = params.BKT_L0
    for _ in range(3):
        p = update(p, channel="mc", correct=True, weight=1.0)  # adapt kwargs to HANDOFF-01
    assert p == pytest.approx(0.978259, abs=5e-7)


def test_frontend_mirror_of_bkt_constants():
    src = (Path(__file__).resolve().parents[2] / "frontend/e2e/support/quiz.ts").read_text()
    found = {k: float(v) for k, v in re.findall(r"export const (BKT_L0|BKT_T|MC_G|MC_S) = ([0-9.]+);", src)}
    assert found == {"BKT_L0": params.BKT_L0, "BKT_T": params.BKT_T,
                     "MC_G": params.CHANNELS["mc"].guess, "MC_S": params.CHANNELS["mc"].slip}  # adapt attribute names to HANDOFF-01
    assert "MASTERY_PER_CORRECT" not in src


def test_submit_reports_p_delta_not_mastery_delta(client_and_tables):
    client, tables = client_and_tables  # copy the submit fixture shape from tests/test_quiz_routes.py
    body = client.post("/api/quiz/submit", json=...).json()
    assert "p_delta" in body and "mastery_delta" not in body
    assert body["mastery_after"] == pytest.approx(body["mastery_before"] + body["p_delta"])
```

- [ ] **Step 2: Run** → FAIL (`quiz_config` still has the symbols; TS file still has `MASTERY_PER_CORRECT`).

- [ ] **Step 3: Implement** per §Behaviour B.2 and B.9. In `submit_quiz` the PKG-11 evidence branch becomes the only branch; `mastery_before`/`mastery_after` for `quiz_attempts` come from the first/last `apply_graph_update` change (`before` of the first, `after` of the last); `p_delta = mastery_after − mastery_before`. `quiz.ts`:

```ts
/** learning/params.py mirror (pinned by backend/tests/test_quiz_evidence_only.py). */
export const BKT_L0 = 0.35;
export const BKT_T = 0.15;
export const MC_G = 0.25;
export const MC_S = 0.1;
/** §3.1 correct update + learn step, `n` unassisted `mc` corrects from `before`. */
export function bktAfterCorrect(before: number, n: number): number {
  let p = before;
  for (let i = 0; i < n; i++) {
    const post = (p * (1 - MC_S)) / (p * (1 - MC_S) + (1 - p) * MC_G);
    p = post + (1 - post) * BKT_T;
  }
  return p;
}
```

`quiz.spec.ts`: `EXPECTED_AFTER = bktAfterCorrect(BKT_L0, QUIZ_LENGTH)` (or from `SEEDED_MASTERY` per §Derived expectations), `expect(masteryAfterDb).toBeCloseTo(EXPECTED_AFTER, 5)`, and the `node_mastery_events` assertion counts `QUIZ_LENGTH` rows (or 1 — HANDOFF-11) each with `event_type = 'evidence'`. `quiz-integration.spec.ts:50`, `:130`: the flat `3 * 0.03` expectation becomes the same `bktAfterCorrect(…)` value (both lanes — the quiz has no legacy path after half B). No seed change: every seeded student is on the quiz evidence path because the quiz gate is gone. If HANDOFF-11 says the channel differs, recompute:

```
python3 -c "
L0,T,G,S=0.35,0.15,<G>,<S>; p=L0
for _ in range(3):
    post=p*(1-S)/(p*(1-S)+(1-p)*G); p=post+(1-post)*T
print(round(p,6))"
```

- [ ] **Step 4: Run** `cd backend && venv/bin/python -m pytest tests/ -q -k "quiz or flashcard or event_capture or evidence_only" && venv/bin/ruff check . && cd ../frontend && npx tsc --noEmit && npx vitest run src/components/screens/Tree.quiz.test.tsx`
Expected: all passed; clean.

- [ ] **Step 5: Commit**

```
git add -A backend/services/quiz_config.py backend/routes/quiz.py backend/routes/flashcards.py backend/services/events_service.py backend/tests frontend/src frontend/e2e/support/quiz.ts frontend/e2e/quiz.spec.ts frontend/e2e/quiz-integration.spec.ts
git commit -m "feat(learning-loop): PKG-14b — quiz and flashcards are evidence-only; p_delta replaces mastery_delta; E2E expects the BKT posterior

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task B4: Tiers — `get_mastery_tier` → `bkt.tier_for` everywhere

**Files:**
- Modify: `backend/config.py:100–141` (delete the block), `backend/learning/bkt.py` (`is_mastered`, `is_weak`), `backend/services/graph_service.py:7`, `:735`, `backend/agents/tools/chat_context.py:47`, `:492`, `:562–564`, `backend/routes/flashcards.py:14`, `:180`, `:199`, `backend/db/seed_staging.py:34`, `:238`, `backend/db/seed_local_rich.py:19`, `:324`, `backend/db/archive/seed.py:14`, `:59`, `backend/db/e2e_checks/quiz.py:20–27` (0.3 is `learning` under the new cuts — set the comment and `mastery_tier` accordingly), `backend/tests/test_config.py` (rewrite against `tier_for` with `TIER_UNEXPLORED_MAX`/`BAND_NOVICE_MAX`/`BKT_PROFICIENT` boundaries), `backend/tests/test_mastery_tier_unification.py` (import `tier_for`, `is_mastered`, `is_weak` from `learning.bkt`; `SCORES` adds `0.29, 0.3, 0.94, 0.95`; the frontend pin compares to `params`), `backend/tests/test_seed_staging.py:232–235`, `backend/tests/test_chat_context_tools.py:315`, `frontend/src/components/screens/Learn.tsx:86–93`, `frontend/src/lib/quiz/proposals.ts:17` (comment), `frontend/src/lib/graph/nodeStyle.ts:111–121` (`tierFor` + its doc comment) and `frontend/src/lib/graph/nodeStyle.test.ts` (its table test), `frontend/e2e/graph.spec.ts:54–59` (the E2E `tierFor` copy)

- [ ] **Step 1:** Update `test_mastery_tier_unification.py` first (it is the failing test): every `from config import …` becomes `from learning.bkt import …` / `from learning.params import …`; `found == {"mastered": BKT_PROFICIENT, "learning": BAND_NOVICE_MAX, "struggling": TIER_UNEXPLORED_MAX}` for `Learn.tsx::tierForScore`, and the same parse-and-compare pin for `lib/graph/nodeStyle.ts::tierFor` and `e2e/graph.spec.ts::tierFor` (same regex technique — three frontend copies, one backend source). Run → FAIL (`ImportError` on `learning.bkt.is_mastered`, then the mirror mismatch on all three copies).
- [ ] **Step 2:** Implement: add the two predicates to `bkt.py` (pure, importing only `params`); sweep every anchor above (`grep -rn "get_mastery_tier\|MASTERY_MASTERED_MIN\|MASTERY_LEARNING_MIN\|MASTERY_STRUGGLING_MIN\|from config import is_\|is_mastered\|is_weak" backend/ --include='*.py' | grep -v venv` must show only `learning/bkt.py` and its tests); `tierForScore`, `nodeStyle.ts::tierFor` and `graph.spec.ts::tierFor` cuts become `0.95` / `0.3` / `0.1`, each with its comment pointing at `learning/params.py` (`BKT_PROFICIENT` / `BAND_NOVICE_MAX` / `TIER_UNEXPLORED_MAX`) instead of `config.py::get_mastery_tier`; `nodeStyle.test.ts`'s table moves to the new boundaries (`0.29`/`0.3`/`0.94`/`0.95`).
- [ ] **Step 3: Run** `cd backend && venv/bin/python -m pytest tests/ -q && venv/bin/ruff check . && cd ../frontend && npx tsc --noEmit && npx vitest run src/lib/graph`
Expected: zero failures apart from `inv_11` (B5) and any `inv_21` hits left for B5; clean; `nodeStyle.test.ts` passes.
- [ ] **Step 4: Commit**

```
git add -A backend frontend/src/components/screens/Learn.tsx frontend/src/lib/quiz/proposals.ts frontend/src/lib/graph/nodeStyle.ts frontend/src/lib/graph/nodeStyle.test.ts frontend/e2e/graph.spec.ts
git commit -m "feat(learning-loop): PKG-14b — one tier function: learning.bkt.tier_for (0.10/0.30/0.95) replaces config.get_mastery_tier

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task B5: `learning_style`, the empty summary lists, flag collapse, kill-switch suite and budget

**Files:**
- Modify: `backend/config.py` (the exact spec §7 post-launch parse, §Behaviour B.6), `backend/learning/gate.py` (env-only: returns `config.LEARNING_LOOP_ENABLED` read at call time — never `from config import …` — no `user_settings` read, no `table`/`db` import; docstring rewritten to the post-launch meaning), `backend/tests/test_learning_gate.py` (rewritten per spec §11.5 — Step 1), `backend/tests/conftest.py` (autouse `kill_switch` fixture + the marker registered in `pytest_configure`, spec §11.5), the legacy-route test modules `backend/tests/test_learn_routes.py`, `test_learn_stream_routes.py`, `test_event_capture_seams.py`, `test_xp_wiring.py`, `test_achievement_dispatch.py`, `test_graph_context_block.py` and any other non-loop hit of `grep -ln '/api/learn/' backend/tests` (each gains only `pytestmark = pytest.mark.kill_switch`), `backend/main.py` (the `learn_loop` mount comment → `# Learning loop: 404 when LEARNING_LOOP_ENABLED=false (kill switch).`), `backend/.env.local.example` (the PKG-13 line → `# LEARNING_LOOP_ENABLED — unset = ON (default); false/0/off/no = kill switch (spec §7)`), `backend/routes/learn.py` (`:1145–1152`, `:1206–1212`; and the kill-switch budget: `ai_budget.check` + `Depends(ai_budget.enforce_rate_limit)` on `start_session`, `/start-session/stream`, `/chat`, `/chat/stream`, `/action` — §Behaviour B.6), `backend/routes/onboarding.py:86`, `backend/routes/profile.py:42` (and `ALLOWED`/`UpdateSettingsBody` only if `learning_loop_beta` reappeared there), `backend/models/__init__.py:312`, `backend/tests/test_onboarding_routes.py:23`, `:224`, `:283`, `backend/tests/test_profile_routes.py:851`, `:888`, `backend/db/seed_staging.py:156`, `backend/db/seed_local_rich.py:167–191`, `backend/db/e2e_checks/academics.py:32–43`, `frontend/src/components/screens/Onboarding.tsx`, `frontend/src/lib/api.ts:999`, `frontend/src/components/chat/SessionSummary.tsx`, `frontend/src/components/screens/Learn.applyGraphDelta.test.ts:68`, `frontend/e2e/*.spec.ts` that click the learning-style step (`grep -rn "learning-style\|learning_style" frontend/e2e`), `backend/tests/test_documents_routes.py` (`pytestmark = pytest.mark.kill_switch`, or its two upload-hook assertions updated to the default — §Behaviour B.11), every other module the B.11 grep finds, `frontend/src/components/screens/Learn.tsx` + its branch vitest + `docs/frontend-testids.md` (§Behaviour B.13: legacy tree only on 404 / `{active: false}`)
- Test: `backend/tests/test_cutover_removals.py`, `backend/tests/test_learning_gate.py`

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_cutover_removals.py`:

```python
"""PKG-14b: spec §11 removals and launch changes that inv_21's grep does not cover."""
import inspect
import pathlib

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]


def test_gate_module_is_env_only():
    import re
    src = (BACKEND / "learning" / "gate.py").read_text()
    assert not re.search(r"^from db|table\(", src, re.M), "spec §7: the post-launch gate reads no table"


def test_quiz_and_flashcards_do_not_consult_the_gate():
    from routes import flashcards, quiz
    for mod in (quiz, flashcards):
        assert "learning_loop_active" not in inspect.getsource(mod), mod.__name__


def test_onboarding_ignores_learning_style():
    from models import OnboardingBody
    body = OnboardingBody(user_id="u", first_name="A", last_name="B", year="1", majors=["x"], course_ids=["c"])
    assert body.learning_style is None
    from routes import onboarding
    assert "learning_style" not in inspect.getsource(onboarding.save_onboarding_profile)


def test_end_session_summary_has_no_dead_lists():
    from routes import learn
    src = inspect.getsource(learn.end_session)
    for key in ("mastery_changes", "new_connections", "recommended_next"):
        assert key not in src, key


@pytest.mark.kill_switch
def test_kill_switch_marker_turns_the_loop_off():
    import config
    from learning.gate import learning_loop_active
    assert config.LEARNING_LOOP_ENABLED is False
    assert learning_loop_active("anyone") is False


def test_kill_switch_path_is_cost_bounded_in_source():
    from routes import learn
    src = inspect.getsource(learn)
    assert "ai_budget.check(" in src and "ai_budget.enforce_rate_limit" in src


@pytest.mark.kill_switch
@pytest.mark.parametrize("path", ["/api/learn/chat", "/api/learn/chat/stream"])
def test_kill_switch_path_returns_429_at_the_hard_cap(monkeypatch, legacy_client, legacy_chat_body, path):
    from services import ai_budget
    hard = ai_budget.BudgetDecision(level="hard", tier_ceiling="none", scope="daily_usd")
    monkeypatch.setattr(ai_budget, "check", lambda *a, **k: hard)
    r = legacy_client.post(path, json=legacy_chat_body)
    assert r.status_code == 429 and r.json()["detail"] == "ai budget reached"
    assert legacy_client.agent_runs == []  # checked before any agent run and before the stream opens
```

`legacy_client`/`legacy_chat_body` are fixtures you write in this module from `tests/test_learn_routes.py`'s setup (its mocked `table`, its function-mode `chat_tutor` handler): a `TestClient` whose `agent_runs` list the patched legacy run site appends to, and a valid `/api/learn/chat` body. Keep them local.

`backend/tests/test_learning_gate.py` — rewrite in place per spec §11.5 (keep PKG-00's `_reload` helper and `_Table` fake):

```python
@pytest.mark.parametrize("env_value,expected", [
    (None, True), ("", True), ("true", True), ("1", True),
    ("false", False), ("FALSE", False), ("0", False), ("off", False), ("no", False),
])
def test_env_flag_defaults_on(monkeypatch, env_value, expected):
    import config
    _reload(monkeypatch, env_value)
    assert config.LEARNING_LOOP_ENABLED is expected


@pytest.mark.parametrize("env_value", ["false", "FALSE", " False ", "0", "off", "no"])
def test_env_off_is_false_and_reads_nothing(monkeypatch, env_value):
    gate = _reload(monkeypatch, env_value)
    t = _Table(rows=[{"learning_loop_beta": True}])
    monkeypatch.setattr("db.connection.table", lambda name: t)
    assert gate.learning_loop_active("user_andres") is False
    assert t.calls == []


@pytest.mark.parametrize("rows,raises", [
    ([{"learning_loop_beta": True}], None), ([{"learning_loop_beta": False}], None),
    ([], None), ([{"user_id": "user_andres"}], None), (None, RuntimeError("pg down")),
])
def test_env_on_is_true_for_any_row_state_and_reads_nothing(monkeypatch, rows, raises):
    gate = _reload(monkeypatch, None)
    t = _Table(rows=rows, raises=raises)
    monkeypatch.setattr("db.connection.table", lambda name: t)
    assert not hasattr(gate, "table")
    assert gate.learning_loop_active("user_andres") is True
    assert t.calls == []
```

These replace PKG-00's `test_env_on_row_true_is_true`, `test_env_on_row_false_is_false`, `test_env_on_missing_row_is_false`, `test_env_on_missing_key_is_false` (every env-on test becomes "env on → True for any row state, no `table()` call") and remove `test_read_error_fails_closed` (there is no read) — the deleted-test naming rule applies: name all five in the commit message. With exactly this module, `pytest tests/test_learning_gate.py -q` → `20 passed` and `-k defaults_on` → `9 passed`.

`backend/tests/conftest.py`: in `pytest_configure`, `config.addinivalue_line("markers", "kill_switch: legacy /api/learn path under LEARNING_LOOP_ENABLED=false (spec §11.5)")`; plus

```python
@pytest.fixture(autouse=True)
def _kill_switch(request, monkeypatch):
    """Spec §11.5: tests marked kill_switch drive the legacy /api/learn/* path."""
    if request.node.get_closest_marker("kill_switch"):
        import config
        monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", False)
```

- [ ] **Step 2: Run** `cd backend && venv/bin/python -m pytest tests/test_cutover_removals.py tests/test_learning_gate.py -v` → FAIL: the gate/quiz/onboarding/end-session/kill-switch tests fail; `test_env_flag_defaults_on` fails for `None`/`""`/`1` and the env-on cases fail (the build-phase gate reads the row). Then `cd backend && venv/bin/python -m pytest tests/ -q -x` also shows what flipping the default will break before B5's markers land — note the list.
- [ ] **Step 3: Implement** per §Behaviour B.4–B.6, B.11 and B.13. Onboarding: step 5 disappears (renumber nothing else; `canContinue` loses `case 5`; the step count constant if any drops by one; delete `StepLearningStyle` if unused elsewhere). `SessionSummary.tsx` renders only `concepts_covered` and `time_spent_minutes`. `config.py`: the exact three lines of §Behaviour B.6. `gate.py`: env-only; docstring "Kill switch (spec §7, §13 A14): the loop is the default for every student; LEARNING_LOOP_ENABLED=false/0/off/no turns it off for everyone. No per-user read." Mark every legacy-route test module with `pytestmark = pytest.mark.kill_switch` (module-level; add `import pytest` where missing) — nothing else in those modules changes. Then run `grep -rln "LEARNING_LOOP_ENABLED\|learning_loop_active" backend/routes backend/services` and, for each hit, every test module that drives it without pinning the flag (at least `tests/test_documents_routes.py`: the upload hook's `_index_then_check_items` post-roll under the default): mark it the same way, or update its assertions to the default — name each module and the choice in the commit body and the hand-off. `Learn.tsx` per §Behaviour B.13, with its vitest. `routes/learn.py`: the kill-switch budget check and rate-limit dependency of §Behaviour B.6 (module-qualified `ai_budget.check(` so `test_inv_23`-style scans can see it).
- [ ] **Step 4: Run** `cd backend && venv/bin/python -m pytest tests/ -q && venv/bin/ruff check . && cd ../frontend && npx tsc --noEmit && npx vitest run`
Expected: zero failures; `inv_21` PASS; `inv_11` PASS (every parametrized case); `tests/test_learning_gate.py` `20 passed`; clean.
- [ ] **Step 5: Commit**

```
git add -A backend frontend docs/frontend-testids.md
git commit -m "feat(learning-loop): PKG-14b — LEARNING_LOOP_ENABLED defaults on (env-only kill switch, spec §7 parse); kill-switch suite marked and cost-bounded; drop learning_style onboarding and empty session-summary lists

Deleted tests (their behaviour is deleted in this commit): test_env_on_row_true_is_true, test_env_on_row_false_is_false, test_env_on_missing_row_is_false, test_env_on_missing_key_is_false, test_read_error_fails_closed (replaced by test_env_on_is_true_for_any_row_state_and_reads_nothing)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task B5b: Retire the build-phase E2E split

**Files:**
- Modify: `scripts/e2e-up.sh` (remove the `LEARNING_LOOP_ENABLED` export PKG-13 added; the comment becomes "The loop is the default (spec §7); run `LEARNING_LOOP_ENABLED=false make e2e-up` for the kill-switch lane"; add the `backend/.env` fail-fast of §Behaviour B.10), `.github/workflows/e2e.yml` (two-lane matrix), `scripts/explore.sh` (remove the explicit export), `frontend/e2e/support/fixtures.ts` (`killSwitchLane`), `frontend/e2e/global-setup.ts` (the lane assertion), `frontend/e2e/learn-loop.spec.ts`, `frontend/e2e/tutor.spec.ts`, `streaming.spec.ts` (legacy skip guard), `gallery-shots.spec.ts` (legacy skip guard on the `/learn` recipe ONLY), `study-semester.spec.ts` (lane-aware `review-due-panel` assertion), `frontend/e2e/quiz-integration.spec.ts:286`, `:292` and `quiz-journeys.spec.ts:463` (lane-aware AskPanel expectation; legacy skip guard on any legacy-tutor-only test in those files), `backend/tests/test_learning_loop_invariants.py` (`test_inv_13b_seed_opts_in_exactly_the_loop_users` rewritten in place), `backend/tests/test_learning_seed_loop_user.py` (retire `test_legacy_users_are_not_opted_in`), `backend/db/seed_local_rich.py` (comments only: `learning_loop_beta` is a retired build-phase staff/QA toggle nothing reads after PKG-14b), `docs/e2e-exploration.md` only if it documents the lane export

- [ ] **Step 1: Rewrite the invariant and retire the split test first** (they are the failing tests)

```python
def test_inv_13b_seed_opts_in_exactly_the_loop_users():
    """The name is historical (PKG-13: only the loop seed users carried the staff/QA toggle).
    After launch (PKG-14b, spec §8, §11.4) no journey may depend on learning_loop_beta:
    the gate never reads it, so every seeded student is on the loop in the default lane."""
    hits = [
        f"{p.relative_to(FRONTEND_E2E)}:{i}"
        for p in sorted(FRONTEND_E2E.rglob("*.ts"))
        for i, line in enumerate(p.read_text().splitlines(), 1)
        if "learning_loop_beta" in line
    ]
    assert hits == [], f"E2E journeys still depend on the retired toggle: {hits}"
```

Delete `test_legacy_users_are_not_opted_in` from `backend/tests/test_learning_seed_loop_user.py` (the split it pins no longer exists — deleted-test naming rule: name it in the commit message). Run `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py tests/test_learning_seed_loop_user.py -q -k "inv_13b or seed"` → `inv_13b` FAIL if any spec or support file still mentions the toggle, else PASS.

- [ ] **Step 2: Implement** per §Behaviour B.9 and B.10.
  - `learn-loop.spec.ts`: replace PKG-13's build-phase test "build phase: a user without the staff/QA toggle still gets the legacy Learn screen with the flag on" with `test("every student gets the loop by default", …)` (default fixture user; `getByTestId("loop-phase")` visible; `getByTestId("tutor-topic-picker")` count 0) and add `test("kill switch restores the legacy Learn screen", …)` guarded by `test.skip(!killSwitchLane, "kill-switch lane only")` (`/api/learn/loop/status` → 404; `tutor-topic-picker` visible; `loop-phase` count 0). Every other `learn-loop.spec.ts` test gets `test.skip(killSwitchLane, "loop path: default lane only")`. Its header comment (PKG-13: "LEARNING_LOOP_ENABLED=true (scripts/e2e-up.sh, build phase) …") is rewritten to the post-launch meaning; afterwards no file under `frontend/e2e/` mentions `learning_loop_beta` (`test_inv_13b`).
  - `support/fixtures.ts`: `export const killSwitchLane = ["false", "0", "off", "no"].includes((process.env.LEARNING_LOOP_ENABLED ?? "").trim().toLowerCase());` (spec §7 post-launch parse) — every guard below uses it; `grep -rn 'LEARNING_LOOP_ENABLED !== \|LEARNING_LOOP_ENABLED ===' frontend/e2e` → 0.
  - Legacy-only tests — exactly `tutor.spec.ts`, `streaming.spec.ts`, the single `/learn` recipe in `gallery-shots.spec.ts` (`:99`), and the legacy-tutor-only tests inside `quiz-integration`/`quiz-journeys` if any: `test.skip(!killSwitchLane, "legacy path: kill-switch lane only")`. `onboarding`, `study-room`, `study-recent-guides`, `study-semester` and every other `gallery-shots` recipe carry NO guard and run in both lanes (spec §11.4). `study-semester.spec.ts` gains a lane-aware assertion on `/study?mode=cards`: default lane → `review-due-panel` visible above the semester deck and the deck still renders; kill-switch lane → `review-due-panel` count 0. `quiz.spec.ts` and the quiz/AskPanel tests run in both lanes; the AskPanel assertions expect `killSwitchLane ? E2E_TUTOR_REPLY : E2E_LOOP_TUTOR_REPLY`.
  - `scripts/e2e-up.sh`: before starting uvicorn, `if grep -qE '^[[:space:]]*(export[[:space:]]+)?LEARNING_LOOP_ENABLED=' backend/.env; then echo "e2e-up: remove LEARNING_LOOP_ENABLED from backend/.env — the lane is chosen in the shell (spec §11.4)" >&2; exit 2; fi`. `global-setup.ts`: after the stack is up, `GET /api/learn/loop/status?user_id=<default fixture user>` must be 404 when `killSwitchLane`, else `{active: true}` — otherwise throw with both values (the lanes disagree).
  - `e2e.yml`: `strategy.matrix.lane: [default, kill-switch]`; one step before the stack starts: `if [ "${{ matrix.lane }}" = "kill-switch" ]; then echo "LEARNING_LOOP_ENABLED=false" >> "$GITHUB_ENV"; fi` (the default lane sets nothing, so the code default runs); upload artifacts per lane.
  - `e2e-up.sh`, `explore.sh`: delete the export line(s); rewrite the PKG-13 comments to the post-launch meaning (the seeded loop users are ordinary students now; `LEARNING_LOOP_ENABLED=false` selects the kill-switch lane).
  - `seed_local_rich.py`: comments only — the `learning_loop_beta` writes PKG-13 added for `rich-user-loop`/`rich-user-capped` stay as inert fixture data ("retired build-phase staff/QA toggle; nothing reads it after PKG-14b, spec §7").
- [ ] **Step 3: Run** `cd backend && venv/bin/python -m pytest tests/ -q && venv/bin/ruff check . && cd ../frontend && npx tsc --noEmit && grep -c "export LEARNING_LOOP_ENABLED" ../scripts/e2e-up.sh`
Expected: zero failures; clean; `0`. (The lanes themselves run in Task B6.)
- [ ] **Step 4: Commit**

```
git add scripts/e2e-up.sh scripts/explore.sh .github/workflows/e2e.yml frontend/e2e backend/tests/test_learning_loop_invariants.py backend/tests/test_learning_seed_loop_user.py backend/db/seed_local_rich.py
git commit -m "test(learning-loop): PKG-14b — retire the build-phase E2E split: default lane runs the code default, kill-switch lane runs the legacy journeys

Deleted tests (the split they pin is removed in this commit): test_legacy_users_are_not_opted_in

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task B6: Full E2E gate — two lanes

- [ ] **Step 1:** Both lanes back to back under ONE lock invocation (spec §11.4), each exporting its value in the same shell for the stack and Playwright, oracles after each lane:

```
flock /tmp/claude-$(id -u)/sapling-e2e-stack.lock sh -c '
  unset LEARNING_LOOP_ENABLED
  make e2e-up && (cd frontend && npx playwright test); s1=$?
  (cd backend && venv/bin/python -m e2e_oracles); o1=$?
  make e2e-down
  export LEARNING_LOOP_ENABLED=false
  make e2e-up && (cd frontend && npx playwright test); s2=$?
  (cd backend && venv/bin/python -m e2e_oracles); o2=$?
  make e2e-down
  echo "default: playwright=$s1 oracles=$o1  kill-switch: playwright=$s2 oracles=$o2"
  exit $((s1|o1|s2|o2))'
```

Expected, default lane: every journey not marked legacy-only passes — every `learn-loop.spec.ts` test incl. "every student gets the loop by default" (the kill-switch test reports skipped), `quiz.spec.ts` with the BKT expectation, `quiz-integration`/`quiz-journeys` with the AskPanel showing `E2E_LOOP_TUTOR_REPLY`, `onboarding` without the learning-style step, `study-room`, `study-recent-guides`, `study-semester` (with `review-due-panel` beside the semester deck), every `gallery-shots` recipe except `/learn`; exactly the legacy-only tests (`tutor`, `streaming`, the `/learn` gallery recipe) report skipped; oracles exit 0. Expected, kill-switch lane: `tutor`, `streaming`, the `/learn` gallery recipe and "kill switch restores the legacy Learn screen" pass, and so does everything that runs in both lanes (`quiz`, `quiz-integration`, `quiz-journeys` with the AskPanel showing `E2E_TUTOR_REPLY`, `onboarding`, `study-*` with `review-due-panel` absent, the other gallery recipes); loop-only tests report skipped; oracles exit 0. Both lanes: global-setup's lane assertion passed (it throws otherwise); logscan `ALLOWLIST` untouched; the final line reads `default: playwright=0 oracles=0  kill-switch: playwright=0 oracles=0`.
- [ ] **Step 2:** Sync check: `grep -o "E2E_[A-Z_]*" backend/agents/function_handlers_e2e.py | sort -u` versus every `frontend/e2e/*.spec.ts` and `tests/test_e2e_function_handlers.py` — no constant is removed in half B (the legacy tutor stays for the kill switch); `E2E_TUTOR_REPLY` is cited by kill-switch-lane tests and `E2E_LOOP_TUTOR_REPLY` by default-lane tests; none is dangling.
- [ ] **Step 3:** Fix forward on this branch; a failing journey that reveals a bug in an earlier package follows the README rule (separate `fix(learning-loop): PKG-MM — …` commit, `MM | reopened` row, post-hoc note). Commit any spec/handler sync changes: `git commit -m "test(learning-loop): PKG-14b — E2E journeys on the cutover base (both lanes)"`.

### Task B7: Hand-off + ledger (half B)

- [ ] **Step 1:** Append to `HANDOFF-14.md` a `## Half B` section with the same headings, and REPLACE its "Verify commands" block with exactly:

```
cd backend && venv/bin/python -m pytest tests/ -q                                                → zero failures
ls docs/decisions/*learning-loop-cutover*.md                                                      → 1 file
grep -c "update_mastery_tool" backend/agents/tools/graph.py                                      → 0
grep -c "MASTERY_DELTA_PER" backend/services/quiz_config.py                                      → 0
grep -cE "^from db|table\(" backend/learning/gate.py                                             → 0
cd backend && venv/bin/python -m pytest tests/test_learning_gate.py -q -k defaults_on            → 9 passed
grep -c "export LEARNING_LOOP_ENABLED" scripts/e2e-up.sh                                          → 0
```
(The two E2E lanes are run in Task B6, not in this block.)

Append to the cutover ADR's Status block `learning_loop_beta retired: <date> (PKG-14b) — the gate no longer reads it; the column stays dead` and `Cutover executed: <date>, PR #<n>` (the owner appends `Launched: <date>` at runbook step 12). Deviations: `inv_11` semantics (spec §7 parse table, name historical); `p_delta` rename; the kill-switch path's `band="develop"` budget allowance (†); deleted tests (list: B2's, B5's five gate tests, B5b's `test_legacy_users_are_not_opted_in`); `chat_tutor` kept for the kill switch until the env-var-removal ticket. Known gaps: `LEARNING_LOOP_ENABLED` removal ticket (it also folds the `chat_tutor` mode prompts into `loop_tutor`); dead columns `user_profiles.learning_style` and `user_settings.learning_loop_beta`; the kill switch restores no quiz/flashcard deltas, no old tier cuts and no tutor mastery recording (spec §11.6); `SaplingDeps.mastery_changes` if kept.
- [ ] **Step 2:** Earlier hand-offs whose verify lines half B deliberately changes get a "Post-hoc changes" line each (this is the planned launch, not a repair — no `reopened` row for them): HANDOFF-00 — `PKG-14b <date>: gate env-only (spec §7 post-launch parse); tests/test_learning_gate.py → 20 passed, -k defaults_on → 9 passed; test_read_error_fails_closed and the four env-on row tests replaced — commit <sha>`; HANDOFF-11 — `PKG-14b <date>: quiz/flashcard gate branches removed (evidence-only for everyone); the grep -c "learning_loop_active" row now expects 0 — commit <sha>`; HANDOFF-13 — `PKG-14b <date>: the legacy-user split is replaced by the two E2E lanes (spec §11.4); test_inv_13b rewritten, test_legacy_users_are_not_opted_in retired — commit <sha>`.
- [ ] **Step 3:** Ledger row `| 14 | eval-ladder-cutover | done | feat/learning-loop-14b-cutover | <sha> | 4 modules | — | HANDOFF-14.md |` plus, if an earlier package needed a repair (not the planned changes of Step 2), its `reopened` row.
- [ ] **Step 4: Commit**

```
git add docs/superpowers/plans/learning-loop/HANDOFF-14.md docs/superpowers/plans/learning-loop/HANDOFF-00.md docs/superpowers/plans/learning-loop/HANDOFF-11.md docs/superpowers/plans/learning-loop/HANDOFF-13.md docs/superpowers/plans/learning-loop/LEDGER.md docs/decisions/*-learning-loop-cutover.md
git commit -m "docs(learning-loop): PKG-14b — hand-off, ledger, cutover ADR (learning_loop_beta retired, cutover executed)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task B8: PR (half B)

```
gh pr create --title "feat(learning): PKG-14b cutover" --body-file - <<'EOF'
Learning loop series, package 17 of 17, half B (cutover = launch). Spec §11: docs/superpowers/specs/2026-09-26-learning-loop-design.md. Cutover ADR <number>. Launch gate (spec §11.1) confirmed by the series owner on <date>. The learning loop becomes the default learning system for every student — no opt-in.

MERGING THIS LAUNCHES STAGING (main = staging). Production must already be pinned LEARNING_LOOP_ENABLED=false (runbook step 1). The pin holds back only the loop UI and /api/learn/loop/*: the FIRST `make promote` after this merge — the runbook's step 6 or any unrelated promote — ships the ungated changes below (evidence-only quiz/flashcards, 0.10/0.30/0.95 tier cuts, a legacy tutor that records no mastery, no learning-style step, budget-checked legacy routes) to every production student, and the kill switch cannot undo them. Merge only when runbook steps 3–10 fit one owner-attended window; no unrelated promote until step 8. Way back: runbook §Rollback (git revert -m 1 <this merge> + make promote), abort criteria in the runbook, owner decides.

Removed: update_mastery_tool + ConceptMasteryUpdate + the preamble paragraph; MASTERY_DELTA_PER_* + mastery_after + the submit_quiz delta block; config.get_mastery_tier + MASTERY_*_MIN (→ learning.bkt.tier_for, cuts 0.10/0.30/0.95, mirrored in Learn.tsx, nodeStyle.ts and graph.spec.ts); the learning_style onboarding step and reads (column stays); the three always-empty end_session lists; the updated_nodes path of apply_graph_update; the quiz/flashcard gate branches; the gate's user_settings read (learning_loop_beta retired, column stays).
Changed: LEARNING_LOOP_ENABLED defaults on; any of false/0/off/no is the kill switch; chat_tutor keeps its agents and mode prompts for the kill-switch path, minus the mastery tool; the kill-switch path is cost-bounded (ai_budget.check + rate limit); legacy-route test modules are marked kill_switch; quiz.completed and attempt history carry p_delta; chat_tutor cassettes re-recorded; quiz E2E expects the BKT posterior; E2E runs two lanes (default + kill switch).
Invariants: 21 asserted; 11 and 13b rewritten in place. Both E2E lanes green.
Launch runbook: HANDOFF-14 §Launch runbook (owner-run): pin + platform alert, merge, staging backfill + smoke, staging kill-switch drill (go/no-go), abort criteria, promote, production backfill (dry run, --project check), unpin, re-backfill, production smoke, nightly backfill, ADR; plus §Rollback.
Also: Learn() shows a retry state (never the legacy tree) when /status fails with anything but 404/{active:false}; tests/test_documents_routes.py (and every module the B.11 grep found) runs as an explicit kill-switch test or expects the default; E2E lanes share one parse (support/fixtures.ts::killSwitchLane) and e2e-up.sh refuses a LEARNING_LOOP_ENABLED line in backend/.env.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
```

### Task B9: Launch runbook (owner-run)

- [ ] **Step 1:** Write spec §11.7 into `HANDOFF-14.md` under `## Launch runbook` — its opening paragraph, steps 1–12 and the "Rollback" block, verbatim, in order, as a checklist for the owner (the abort criteria stay the defaults; the owner edits them at step 5). Precede the steps with a `### Preconditions` subsection that copies the half B "Verify commands" block of Task B7 verbatim (all seven lines and its note) under the sentence "Every line is green on the half B merge commit."
- [ ] **Step 2: Commit and push** (the open half B PR picks it up)

```
git add docs/superpowers/plans/learning-loop/HANDOFF-14.md
git commit -m "docs(learning-loop): PKG-14b — launch runbook (owner-run, spec §11.7)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

- [ ] **Step 3: STOP.** Post the PR link, the runbook's opening paragraph (the first `make promote` after the merge launches the ungated changes whatever the pin says) and its step 1 ("Pin production off; set the platform alert … before the half B PR merges") to the series owner, then end the session. The session never sets a deployed env var, never runs `make promote`, never runs a staging or production backfill, never reverts, and never merges half B.

## Self-check loop (run after every task, and once more before each PR)

1. `cd backend && venv/bin/ruff check . && venv/bin/ruff format --check learning tests/test_learning_*.py`
2. `venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q`
3. `venv/bin/python -m pytest tests/ -q` (no `SAPLING_MODEL_MODE` exported)
4. Prompts/tool descriptions touched? **Half A: No** (fixtures and evaluators only — evals still run: `SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/run_all.py`, every dataset `PASS`, `loop_tutor` on every tier slot). **Half B: Yes** (the deleted `chat_tutor` preamble paragraph and the removed `update_mastery_tool`; the mode prompts and `loop_tutor` are untouched) → re-record `chat_tutor` only, then `run_all.py` in replay must `PASS` for every dataset; `loop_tutor`/`grader`/`check_items`/`decisions` baselines must not move (their prompts are untouched).
5. Request-path agent or route touched? **Half A: Yes** (`learn_loop.py` rating + post-test + `arm_session`; `admin_analytics.py`) → run the PKG-13 lane row (`learn-loop.spec.ts` + oracles) under the lock before the PR. **Half B: Yes** → Task B6's two lanes (default + kill switch) under one lock.
6. Scope check: `git diff --stat main...HEAD` — every path must be in this half's Files lists (half B's lists are grep-driven; anything the `inv_21` hit list or the B4/B5/B5b greps named counts). Anything else: `git checkout main -- <path>` or record a Deviation.
7. Sync check: `grep -o "E2E_[A-Z_]*" backend/agents/function_handlers_e2e.py | sort -u` — half A: unchanged from `main`; half B: unchanged too (no constant is removed — the legacy tutor stays for the kill switch); every constant still cited by a spec in the lane that runs it and by `tests/test_e2e_function_handlers.py`.

Green = all seven clean. Max 5 iterations per loop; then write a `BLOCKED` row in `LEDGER.md` with hypothesis, commands, outputs, and stop.

## Regression guard

- Half A: suite count N₀ unchanged except the tests this half adds; zero failures; zero new skips outside `test_learning_loop_invariants.py`. `tests/test_learn_loop_routes.py`, `tests/test_learning_zpd_policy.py`, `tests/test_learning_evidence_apply.py`, `tests/test_learning_check_tool.py`, `tests/test_admin_analytics_routes.py`, `tests/test_event_capture_seams.py`, `tests/test_model_mode_seam.py`, `tests/test_learning_ai_budget.py`, `tests/test_learning_decisions.py` green and unmodified (the invariants module changes only by the `inv_26` allow-list entry). With `LEARNING_LOOP_ENABLED` unset: the new routes 404, `loop_state.checks_since_rating` never written, `arm_session` always `False`, no behaviour change anywhere.
- Half B: the only tests that may disappear are the ones whose code disappears, each named in its commit message. `tests/test_learning_bkt.py`, `tests/test_learning_fsrs.py`, `tests/test_learning_evidence_apply.py`, `tests/test_learning_check_items.py`, `tests/test_learning_check_tool.py`, `tests/test_learning_zpd_policy.py`, `tests/test_learn_loop_routes.py`, `tests/test_learning_probe_planner.py`, `tests/test_learning_close_brief.py`, `tests/test_learning_misconceptions.py`, `tests/test_learning_review.py`, `tests/test_learning_ai_budget.py`, `tests/test_learning_decisions.py` green and unmodified. The legacy-route test modules change only by their module-level `pytestmark = pytest.mark.kill_switch`; `tests/test_event_capture_seams.py::test_event_taxonomy_is_pinned` unchanged (no taxonomy change). Retired under the deleted-test naming rule, and only these: B2's mastery-tool/`updated_nodes` tests, B5's `test_read_error_fails_closed` and four env-on row tests, B5b's `test_legacy_users_are_not_opted_in`. The `document` upload path (`routes/documents.py:633`, `:1222` → `apply_graph_update` with `new_nodes`) unchanged and green.

## Acceptance criteria (the next session pastes these)

Half A:
1. `cd backend && venv/bin/python -m pytest tests/test_learning_zpd_metrics_script.py tests/test_admin_learning_loop_kpis.py tests/test_learn_loop_rating.py tests/test_learning_posttest.py tests/test_learning_arms.py -q` → all passed
2. `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_20 or inv_01"` → `2 passed`
3. `ls backend/db/migrations/*_learning_loop_arm.sql` → 1 file; `ls docs/decisions/*learning-loop-cutover*.md` → 1 file
4. `cd backend && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/run_all.py` → `PASS` for every dataset (`loop_tutor` on every tier slot), and `grep -c '"check_items"\|"grader"\|"decisions"\|"loop_tutor"' backend/tests/evals/run_all.py` → 4
5. `cd backend && venv/bin/python -m pytest tests/ -q` → zero failures; `venv/bin/ruff check .` → `All checks passed!`
6. `curl` is not needed: `grep -n '"/learning-loop"' backend/routes/admin_analytics.py` → 1 hit; `grep -c "posttest/start\|posttest/answer\|/rating" backend/routes/learn_loop.py` → ≥ 3; `grep -c "arm_session=bool(" backend/routes/learn_loop.py` → ≥ 1; `grep -c "REPORT" backend/scripts/derive_zpd_metrics.py` → ≥ 1
7. `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_26 or inv_28"` → `2 passed` (the post-test handler is on the allow-list; symmetric missingness holds)
8. `LEDGER.md` has row `14 | eval-ladder-cutover | done (half A) | …`.

Half B:
1. `cd backend && venv/bin/python -m pytest tests/ -q` → zero failures
2. `ls docs/decisions/*learning-loop-cutover*.md` → 1 file
3. `grep -c "update_mastery_tool" backend/agents/tools/graph.py` → 0
4. `grep -c "MASTERY_DELTA_PER" backend/services/quiz_config.py` → 0
5. `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q` → every test passed, none skipped except `inv_10` if no `lru_cache` exists under `learning/`
6. `grep -rn "get_mastery_tier\|learning_style" backend/routes backend/services backend/agents backend/config.py` → 0 hits
7. `grep -cE "^from db|table\(" backend/learning/gate.py` → 0
8. `cd backend && venv/bin/python -m pytest tests/test_learning_gate.py -q -k defaults_on` → `9 passed`
9. `grep -c "export LEARNING_LOOP_ENABLED" scripts/e2e-up.sh` → 0; `.github/workflows/e2e.yml` runs both lanes (`grep -c "kill-switch" .github/workflows/e2e.yml` → ≥ 1); `grep -c "killSwitchLane" frontend/e2e/support/fixtures.ts` → ≥ 1; `grep -rn 'LEARNING_LOOP_ENABLED !== \|LEARNING_LOOP_ENABLED ===' frontend/e2e | wc -l` → 0; `grep -c "loop-status-error" frontend/src/components/screens/Learn.tsx` → ≥ 1
10. Both E2E lanes (Task B6) green — the final line reads `default: playwright=0 oracles=0  kill-switch: playwright=0 oracles=0`
11. `grep -c "^## Launch runbook" docs/superpowers/plans/learning-loop/HANDOFF-14.md` → 1; `LEDGER.md` has row `14 | eval-ladder-cutover | done | feat/learning-loop-14b-cutover | …`.

## Hand-off

`docs/superpowers/plans/learning-loop/HANDOFF-14.md` per the template, written twice (Task A8, extended in Task B7), plus the `## Launch runbook` section (Task B9). After half B its "Verify commands" block is exactly the seven canonical lines in Task B7 (the canonical half B block PKG-15 and the runbook preconditions copy). Open questions to record: the first experiment for `loop_arm` (the `independent_min_s` candidate or a tier policy); whether `LEARNING_LOOP_ENABLED` is removed next sprint; whether `earnest-revise` gets a signal (a `zpd.step` key or a grader flag) so the third §10 gate becomes measurable; whether the `updated_nodes` key in stored `messages.graph_update_json` needs a read-side migration (it does not today — `end_session` only reads names).

## Do not

- Do not start half B without every item of the spec §11.1 launch gate and the owner's written go-ahead ("Half B — STOP gate"). Do not merge half B yourself.
- Never set `LEARNING_LOOP_ENABLED` in any deployed config (staging, production, `.env.example`, docker-compose, a host dashboard). Never execute the launch runbook: no `make promote`, no staging or production backfill, no env pin or unpin, no kill-switch drill, no revert — the owner runs spec §11.7 and makes every abort decision (Task B9 only writes it down).
- Never read `model_pref` on the loop path (invariant 22); never add a student-visible model toggle; never change the tier table or the budget constants.
- Do not write `learner_state` from the script directly, and do not add a second write seam: `write_metrics` updates the four derived columns only.
- Do not compute `unassisted_next_session` from `zpd.step` (no `session_id` in that payload) — use `node_mastery_events.session_id`.
- Do not change the `sessions.close_phase` CHECK; `posttest` is a `zpd.step.phase` value only. Do not add event types; do not touch `EVENT_TAXONOMY`.
- Do not let the post-test read RAG, the learner brief, or run `loop_tutor`; `grade_answer` (the grader behind it) is its only model path. Grader failure or the grader cap is a 503 with no evidence for either outcome, never a retry with a different prompt (ADR 0024). Never serve a seen or revealed item on the post-test.
- Do not let the student PATCH `loop_arm`. Do not pick an experiment: leave `loop_arm` NULL.
- All Supabase access through `db/connection.py::table()`/`rpc()`/`page_all`; no `httpx`, no `supabase` import. Migrations: UTC-timestamp prefix, `_learning_` infix, append-only, never edited after creation.
- No numeric literal outside `learning/params.py` (the KPI endpoint imports the bands; the script imports the windows; the TS mirrors are pinned by test; budget values stay in `config.py` — the kill-switch path passes a band name, never a dollar figure). No `lru_cache` in this package.
- Do not skip, xfail, or delete a pre-existing test in half A. In half B, delete a test only when the code it tests is deleted in the same commit, and name it in the message. Never hand-edit eval cassettes or baselines; re-record.
- Do not filter on encrypted columns (`prompt`/`reference_answer`/`options_json`/`correct_option`/`canonical_answer`/`final_answer`); the post-test looks items up by `(course_id, concept_key, question_hash)` only (A2), resolved from the node.
- Logscan `ALLOWLIST` in `backend/e2e_oracles/logscan.py` stays `()`. Serialize all stack use under the `flock` lock, one invocation per up→test→down cycle.
- End every commit with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; end each PR body with the Claude Code attribution line.

## If you get stuck

1. Re-read §Spec and the spec file's §10/§11 before guessing; for a KPI definition, the ZPD report LOG block is the tie-breaker.
2. Three failed iterations on one task → append a `BLOCKED` row to `LEDGER.md` (hypothesis, commands run, outputs), commit what is green, open the PR as draft, stop.
3. Never widen scope to unblock. Never disable a test to unblock. In half B, if an `inv_21` hit is in code you cannot safely change (e.g. `db/archive/`), change it anyway — the invariant is the contract — and say so in the hand-off.
4. Ambiguity → choose the option closest to the spec, mark it `†` in the hand-off, continue.

## A38 amendments (2026-09-29)

Spec §13 A39, A40 and A45 bind this package.

1. **Eval floors = the minimum of 3 recordings (A40 06(s)).** Where half A sets or re-sets an eval floor or baseline from a recording, record the dataset 3 times (`SAPLING_EVAL_MODE=record`) and take the minimum score per metric as the floor; record all three numbers and the minimum in HANDOFF-14. A floor from a single recording is not accepted.
2. **Tighten `CHECK_ITEM_FINAL_ANSWER_MAX_TOKENS` (A40 06(t)).** Measure the `final_answer` token counts (`checks.answer_tokens`) of the drafts the `check_items` eval accepts (DraftValid), and lower the constant (20 †) to the smallest value that keeps DraftValid at its floor; record the distribution and the chosen value in HANDOFF-14 and spec §3.5, and keep the † unless the measurement validates the cut.
3. **Platform budget in the runbook (A39 (e)).** The §11.7 runbook written in Task B9 sets production `PLATFORM_DAILY_BUDGET_USD=5` (the owner's decision; it replaces the "suggested ≈ 3×" wording above). Before that step the owner sets a deliberately low value on staging (e.g. `0.01`), drives one tutor turn, confirms the `ai.budget_capped{scope: platform}` alert reaches them, then restores the staging value. The session never sets either value itself.
4. **Cutover ADR number (A45).** ADRs 0027, 0028 and 0029 are claimed by #672, #677 and #705. The cutover ADR takes the next free number in `docs/decisions/` at the time it is written (0030 or later), not "0028 expected"; record the number in HANDOFF-14.
5. **Grader cap blind spot (A45).** `STUDENT_DAILY_GRADES` counts `llm_usage` rows, so it does not hold when `EVENTS_LOGGING_ENABLED=false`. This is open (recorded, not decided); if the launch config sets that flag false, raise it with the owner at the half B STOP gate.
