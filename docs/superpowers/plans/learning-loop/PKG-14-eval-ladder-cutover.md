# PKG-14 eval-ladder-cutover — Learning Loop series (15 of 15)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> You are a fresh session. Nothing outside this file, `docs/superpowers/plans/learning-loop/LEDGER.md`, the `HANDOFF-NN.md` files it names, and the files this prompt lists is known to you. Do not infer intent from chat history you do not have. Do not read the whole research corpus; read the sections named below.

## Package id + goal

**PKG-14 `eval-ladder-cutover`.** The last package. It is TWO pull requests from ONE prompt:

- **Half A — evaluation ladder** (branch `feat/learning-loop-14a-eval-ladder`, PR title `feat(learning): PKG-14a eval ladder`). After half A: the nightly ZPD metrics script exists and is idempotent; admins can read the three headline KPIs and the two gates at `GET /api/admin/analytics/learning-loop`; the tutor asks for a perceived-difficulty rating every `ZPD_RATING_EVERY_N_CHECKS` checks; a tool-removed post-test endpoint serves and grades delayed checks with the ceiling forced to `H0`; within-student A/B arms are plumbed (`user_settings.loop_arm` + `policy.variant_for`); the ADR records the design, the flag, the evidence-only write rule, the ladder, and the cutover plan; the offline eval suite covers leakage and sycophancy and `run_all.py` runs every series dataset. Everything is still behind the flag.
- **Half B — cutover** (branch `feat/learning-loop-14b-cutover`, PR title `feat(learning): PKG-14b cutover`). After half B: no code path can move a mastery score except graded evidence through `apply_graph_update`; the legacy tutor mastery tool, the per-item quiz deltas, the legacy tier cuts, the learning-style onboarding step and the three always-empty session-summary lists are gone; the env flag defaults on and the per-user opt-in column is the only gate; `tests/test_learning_loop_invariants.py::test_inv_21_no_legacy_mastery_writers` proves it.

**Half B starts only after (1) half A is merged AND (2) a human — the series owner — confirms in writing that the beta cohort has run on the loop for at least two weeks with `LEARNING_LOOP_ENABLED=true`.** When you reach "Half B — STOP gate" below, stop, post the question, and do not continue in the same session unless the confirmation is given. This is not a formality: the cutover deletes the only fallback.

## Read before you start (in this order)

0. `docs/superpowers/specs/2026-09-26-learning-loop-design.md` **§13 Amendments log** — in force; where this file and §13 disagree, §13 wins. Re-read it before Task 1.
1. `docs/superpowers/plans/learning-loop/LEDGER.md` — refuse to start if any row is `blocked` or `in-progress`. Rows 00–13 must be `done` or `verified`.
2. `CLAUDE.md` §Conventions and §Gotchas — the standing rules the "Do not" list below repeats.
3. `docs/superpowers/specs/2026-09-26-learning-loop-design.md` §10 (evaluation ladder — every KPI and gate below is named there), §11 (cutover — half B is that list, verbatim), §3.4 (`ZPD_RATING_EVERY_N_CHECKS`), §4 (the PKG-14 `loop_arm` DDL and the `learner_state` derived columns `htc_k`/`unassisted_next`/`assist_gap`/`in_zone`), §6 (`zpd.step`/`zpd.rating` payloads), §8 (invariants 1, 5, 12).
4. `docs/research/learning-loop/AI tutor learning loop research.md` §"Measure learning with tool-removed, delayed checks, not in-session accuracy" (lines ~139–143): the four rungs, why rung 3 is tool-removed and ≥ 2 days delayed, why within-student randomization.
5. `docs/research/learning-loop/ZPD lever tradeoffs and upgrades.md` §"Measure in-ZPD-ness as hints-to-criterion and unassisted next-opportunity success" (lines ~103–107) and §"Sapling ZPD policy spec" — only the `LOG` block (lines ~213–226: `zpd.rating` cadence, the nightly derived quantities and the `in_zone` rule) and the KPI paragraph after it (lines ~229–233: the three headline KPIs and the three gates).
6. Hand-offs you depend on: `HANDOFF-03.md` (how `learner_state` is read/written; what `p` a node with no `learner_state` row starts from), `HANDOFF-04.md` (`checks.select_item`, `check_item_service` read API), `HANDOFF-05.md` (the grader callable `graded_check_tool` uses, `E2E_GRADER_CORRECT_TOKEN`, the format→channel map), `HANDOFF-06.md` (wire form of `ceiling`/`max_rung_used` in `zpd.step`, where `GATE_INDEPENDENT_MIN_S` is consumed), `HANDOFF-07.md` (loop route layout, how the `done` event data is built, eval fixtures that exist), `HANDOFF-11.md` (quiz evidence: one `Evidence` per item or per quiz; channel used), `HANDOFF-13.md` (how the E2E student is opted in; `LoopLearn.tsx` stream consumer).
7. Code you will modify or mirror, with anchors true today:
   - `backend/services/events_service.py:97` (`EVENT_TAXONOMY`; `zpd.rating` is already in it from PKG-06 — verify with `grep -n '"zpd.rating"'`).
   - `backend/routes/admin_analytics.py:36–37` (`_PAGE`/`_SCAN_CAP`), `:185–218` (`_scan_range` — reuse it), `:280–311` (`usage_summary` — the endpoint shape to mirror: `require_admin(request)`, `Cache-Control: private`, `truncated`), `:50–55` (`Range`).
   - `backend/tests/test_admin_analytics_routes.py:63–110` (`_FakeTable` + `seeded` fixture — the mocked-table style for KPI tests).
   - `backend/scripts/backfill_document_chunks.py:40–63` (script preamble: argparse, `load_dotenv(BASE / ".env.staging")`, `sys.path.insert`, `page_all`), `:86–137` (`main(argv)`, `--dry-run`, counts, `sys.exit(1)` on failure).
   - `backend/db/connection.py:172` (`page_all(handle, columns, *, filters, order, page)` — `order` must be a total order).
   - `backend/routes/learn_loop.py` (PKG-07..12 — the route module you extend; find the check-evidence append with `grep -n pending_evidence backend/routes/learn_loop.py`).
   - `backend/learning/policy.py`, `backend/learning/learner_state.py`, `backend/learning/params.py` (PKG-06/03/01).
   - `backend/tests/evals/run_all.py:34–41` (`DATASETS`), `backend/tests/evals/loop_tutor.py` (PKG-07), `backend/tests/evals/README.md` (record/replay/baseline procedure).
   - `docs/decisions/0026-newsletter-email-plaintext.md` — the ADR format (`Status/Date/Relates to/Supersedes`, `Context`, `Options considered`, `Decision`, `Consequences`). Next number is **0027** (`ls docs/decisions | tail -1`).
   - Half B only: `backend/agents/chat_tutor.py:70–101` (`_SHARED_PREAMBLE`; the `update_mastery_tool` paragraph is `:84–91`), `:103–124` (mode prompts), `:152–167` (`_build_tools`), `:190–202` (`agent_for_mode`); `backend/agents/tools/graph.py:34–38` (`TUTOR_EVENT_TYPES`), `:50–100` (`ConceptMasteryUpdate`, `MasteryUpdateInput`), `:156–218` (`update_mastery_tool`); `backend/services/quiz_config.py:102–114`; `backend/routes/quiz.py:2531–2585` (delta block + `apply_graph_update` call), `:2598–2599` (`quiz_attempts.mastery_before/after` — the columns STAY), `:2048` and `:2710` (`mastery_delta` on the wire); `backend/config.py:113–141` (`MASTERY_*_MIN`, `get_mastery_tier`, `is_mastered`, `is_weak`); `backend/routes/learn.py:1145–1152` and `:1206–1212` (the always-empty lists); `backend/tests/test_mastery_tier_unification.py:84–130` (the frontend mirror pin); `frontend/src/components/screens/Learn.tsx:86–93` (`tierForScore`); `frontend/e2e/support/quiz.ts:52–60` (`MASTERY_PER_CORRECT/WRONG`, `masteryAfter`) and `frontend/e2e/quiz.spec.ts:56–57`, `:150–152`; `backend/tests/evals/chat_tutor.py:152–208` (`MASTERY_DELTA_MIN/MAX`, `_mastery_updates`, `MasteryUpdateEmittedEvaluator`), `:421–456` (offline graph-write stub), `:562–576` (`make_dataset`); `backend/routes/onboarding.py:86`, `backend/routes/profile.py:42`, `backend/models/__init__.py:312`, `frontend/src/components/screens/Onboarding.tsx:134`, `:140`, `:151`, `:241–244`, `frontend/src/lib/api.ts:999`; `frontend/src/components/chat/SessionSummary.tsx:13`, `:62–110`.

## State of the world

Every row below is a dependency's canonical verify line. Run all of them before half A Task 1. Create the venv first if `backend/venv` is missing: `cd backend && python -m venv venv && venv/bin/pip install -r requirements.txt`.

| pkg | command | expected |
|---|---|---|
| 00 | `cd backend && venv/bin/python -m pytest tests/test_learning_gate.py -q` | `11 passed` |
| 00 | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q` | `4 passed, 8 skipped (later packages raise the passed count)` — expect the passed count to be ≥ 18 now; zero failures |
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
| 04 | `cd backend && venv/bin/python -m pytest tests/test_learning_check_items.py -q` | N passed (N ≥ 10) |
| 04 | `ls backend/db/migrations/*_learning_check_items.sql` | 1 file |
| 04 | `grep -c '"check_items"' backend/agents/_providers.py backend/agents/function_handlers_e2e.py` | ≥ 1 each |
| 04 | `cd backend && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/check_items.py` | every evaluator ≥ baseline |
| 04 | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_06 or inv_09 or inv_12"` | 3 passed |
| 05 | `cd backend && venv/bin/python -m pytest tests/test_learning_check_tool.py -q` | N passed (N ≥ 12) |
| 05 | `grep -c '"grader"' backend/agents/_providers.py backend/agents/function_handlers_e2e.py` | ≥ 1 each |
| 05 | `grep -c "^async def graded_check_tool" backend/agents/tools/check.py` | 1 |
| 05 | `cd backend && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/grader.py` | every evaluator ≥ baseline |
| 06 | `cd backend && venv/bin/python -m pytest tests/test_learning_zpd_policy.py -q` | N passed (N ≥ 25) |
| 06 | `grep -cE "^def (ceiling\|band_control\|evidence_for_rung\|wheelspin)\(" backend/learning/policy.py` | 4 |
| 06 | `grep -c '"zpd\.' backend/services/events_service.py` | 6 |
| 06 | `ls backend/db/migrations/*_learning_session_loop_state.sql` | 1 file |
| 06 | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_04 or inv_05"` | 2 passed |
| 07 | `cd backend && venv/bin/python -m pytest tests/test_learn_loop_routes.py -q` | N passed (N ≥ 15) |
| 07 | `grep -c "learn_loop" backend/main.py` | ≥ 1 |
| 07 | `grep -c '"loop_tutor"' backend/agents/_providers.py backend/agents/function_handlers_e2e.py` | ≥ 1 each |
| 07 | `grep -c "learning_loop" backend/agents/chat_tutor.py` | ≥ 1 |
| 07 | `cd backend && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/loop_tutor.py` | every evaluator ≥ baseline |
| 08 | `cd backend && venv/bin/python -m pytest tests/test_learning_probe_planner.py -q` | N passed (N ≥ 15) |
| 08 | `grep -cE "^def (next_probe_item\|probe_done\|novice_floor)\(" backend/learning/probe.py` | 3 |
| 08 | `grep -cE "^def (outer_fringe\|plan)\(" backend/learning/planner.py` | 2 |
| 08 | `grep -c '"learn\.probe_done"\|"learn\.plan_approved"' backend/services/events_service.py` | 2 |
| 09 | `cd backend && venv/bin/python -m pytest tests/test_learning_close_brief.py -q` | N passed (N ≥ 10) |
| 09 | `ls backend/db/migrations/*_learning_session_close.sql` | 1 file |
| 09 | `grep -c "LOOP_HISTORY_MAX_MESSAGES" backend/routes/learn_loop.py` | ≥ 1 |
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
| 13 | `(under the stack lock) make e2e-up && (cd frontend && npx playwright test e2e/learn-loop.spec.ts) && (cd backend && venv/bin/python -m e2e_oracles); make e2e-down` | journey passed, oracles exit 0 |
| 13 | `cd frontend && npx tsc --noEmit` | clean |
| 13 | `grep -c "E2E_LOOP_" backend/agents/function_handlers_e2e.py` | ≥ 3 |
| — | `cd backend && venv/bin/python -m pytest tests/ -q -x` | `… passed` (note the count N₀; it is this package's regression baseline) |
| — | `cd backend && venv/bin/ruff check .` | `All checks passed!` |
| — | `ls docs/decisions \| tail -1` | `0026-newsletter-email-plaintext.md` (your ADR is 0027) |

Rule: any red row → STOP. Diagnose, repair on this branch as commit `fix(learning-loop): PKG-MM — <what>` (MM = the package whose line is red), record the deviation in `LEDGER.md` (row `MM | reopened`, "Post-hoc changes" in `HANDOFF-MM.md`), re-run all rows. Never build on a broken base. The PKG-13 row needs the stack lock: wrap the whole up→test→down cycle in ONE `flock /tmp/claude-$(id -u)/sapling-e2e-stack.lock sh -c '…'`.

## Spec

### Behaviour — half A

1. **Metrics script.** `backend/scripts/derive_zpd_metrics.py` recomputes, for every `learner_state` row with `opps > 0` (or one `--user`), the four derived columns from `node_mastery_events` rows with `event_type = 'evidence'` and a non-null `question_hash` (an *opportunity*; propagation rows have no `question_hash` and are excluded). Ordered `created_at desc, id desc`:
   - `htc_k` = mean of `max_rung` over the CORRECT opportunities among the last `HTC_K_WINDOW`; `None` when none of them is correct.
   - `unassisted_next` = share of the last `BAND_WINDOW` opportunities with `correct AND NOT assisted AND max_rung == 0`.
   - `assist_gap` = (correct share among the ASSISTED opportunities in the last `BAND_WINDOW`) − (correct share among the UNASSISTED ones); `None` when either side has zero rows.
   - `in_zone` = `assist_gap ≥ ZPD_IN_ZONE_MIN_GAP AND assisted_rate ≥ ZPD_IN_ZONE_MIN_ASSISTED AND unassisted_next < ZPD_IN_ZONE_MAX_UNASSISTED`; `None` when `assist_gap` is `None`.
   The write goes through a new `learning/learner_state.py::write_metrics(user_id, node_id, *, htc_k, unassisted_next, assist_gap, in_zone)` that UPDATES those four columns (+ `updated_at`) filtered on the primary key and touches nothing else — the one non-evidence write to `learner_state`, recorded as a deviation from spec §5 (†) and in the ADR. The script never calls `table("learner_state")` itself. Re-running produces byte-identical rows (pure function of the events). `--dry-run` prints the would-be rows and writes nothing. Exit codes: `0` normal; `2` when `learner_state` has rows with `opps > 0` but the evidence read returned zero rows for every one of them (a keyspace mismatch — the silent-empty class F5 exists for); `2` also when `--expect-rows` is passed and there are no `learner_state` rows at all. A fresh environment with no rows and no `--expect-rows` exits `0` after printing `0 rows`.
2. **KPI endpoint.** `GET /api/admin/analytics/learning-loop?from=&to=` (admin-only, read-only, `Cache-Control: private`, `truncated` flag) returns:
   - `in_band_share`: over `zpd.step` events in range grouped by `(user_id, concept_id)` in `created_at` order, each step whose phase has a band and that has ≥ `BAND_WINDOW` prior steps of the same kind gets a rolling success rate over those prior steps; `probe` steps use the unassisted first-attempt rate vs `[PROBE_TARGET_LO, PROBE_TARGET_HI]`; `check` steps with `assisted = true` use the assisted first-attempt rate vs `[ACQ_TARGET_LO, ACQ_TARGET_HI]`; `check` steps with `assisted = false` use the unassisted rate vs `[PRACTICE_TARGET_LO, PRACTICE_TARGET_HI]`; every other phase (`teach`, `feedback`, `close`, `plan`, `posttest`) is excluded. `in_band_share = in_band / banded_steps`, `None` when `banded_steps == 0`.
   - `htc_k_trend`: per `concept_id`, the mean `max_rung_used` over correct `zpd.step` rows per ISO week for the last `KPI_TREND_WEEKS` weeks ending at `to`, plus `direction` ∈ {`falling`, `flat`, `rising`, `insufficient`} comparing the first and last week that have data (`insufficient` when fewer than two weeks have data).
   - `unassisted_next_session`: over `node_mastery_events` evidence rows in range grouped by `node_id` and then by `session_id` in `created_at` order, for every session after the first the FIRST row counts as a success when `correct AND NOT assisted AND max_rung == 0`; returns `{sessions, successes, rate}`.
   - `leak_count`: number of `zpd.leak` events in range.
   - `ceiling_compliance`: `{steps, compliant, rate}` over `zpd.step` rows where `max_rung_used ≤ ceiling` (parse the rung wire form per HANDOFF-06 — `"H3"` or `3` — with one `_rung_int` helper; rows missing either key are excluded from `steps`).
   - `gates`: `{zero_leaks: leak_count == GATE_LEAKS_MAX, ceiling_compliance_ok: rate is not None and rate ≥ GATE_CEILING_COMPLIANCE_MIN}`.
   The earnest-revise gate (spec §10) is NOT computed — no event carries that signal; record it under Known gaps.
3. **Rating prompt.** `routes/learn_loop.py` keeps a top-level integer `loop_state["checks_since_rating"]`, incremented in the same place a graded check's evidence is appended to `deps.pending_evidence`. When, after that increment, the counter is `≥ ZPD_RATING_EVERY_N_CHECKS`, the `done` event of that `/chat/stream` turn carries `data.ask_rating = true` (absent otherwise — never `false`). `POST /api/learn/loop/rating` body `{session_id, rating}` with `rating ∈ {too_easy, appropriate, too_hard}` (422 otherwise): emits `zpd.rating` with payload `{rating, checks_since_last}` (the counter's value), resets the counter to `0` in `sessions.loop_state`, stores the rating nowhere else, returns `{"ok": true}`. 404 `{"detail": "learning loop not enabled"}` when the gate is false (PKG-07's pattern). Frontend: a three-button prompt in `LoopLearn.tsx` with `data-testid="loop-rating"` (buttons `loop-rating-too_easy` / `loop-rating-appropriate` / `loop-rating-too_hard`), shown when a `done` event carries `ask_rating`, hidden after one click; `api.ts` gains `submitLoopRating(sessionId, rating)`.
4. **Tool-removed post-test.** `POST /api/learn/loop/posttest/start` body `{course_id}` (user from the session cookie, `require_self` on an optional `user_id` exactly as the other loop routes do): selects this user's `learner_state` rows whose `last_evidence_at ≤ now − POSTTEST_MIN_AGE_DAYS` and whose node belongs to `course_id`, picks one item per node via `checks.select_item` (HANDOFF-04; prefer format `free`, difficulty `2`, else any item for the node; nodes with no item are skipped), caps at `POSTTEST_MAX_ITEMS` ordered by oldest `last_evidence_at` first, returns `{items: [{node_id, question_hash, format, difficulty, prompt}]}` with `prompt` decrypted. No brief, no RAG, no tutor agent, no session row. `POST /api/learn/loop/posttest/answer` body `{node_id, question_hash, answer}`: loads the item by `(node_id, question_hash)` through `check_item_service`, grades through the SAME grader callable `graded_check_tool` uses (HANDOFF-05), builds `Evidence(node_id, channel=<format→channel map from PKG-05>, correct, assisted=False, max_rung=0, question_hash, check_item_id, confidence, session_id=None)`, persists it via `apply_graph_update(user_id, {"evidence": [evidence.model_dump()]}, course_id)`, emits `zpd.step` with `phase="posttest"`, `ceiling` = the wire form of `H0`, `max_rung_used=0`, `assisted=False`, `n_attempts=1`, and returns `{correct, confidence}`. Grader `unavailable` → 503 `{"detail": "grader unavailable"}`, no evidence written, no second prompt (ADR 0024). `"posttest"` is added to every `Literal`/enum that types `zpd.step.phase` (`grep -rn '"feedback", "close"' backend/` and `grep -rn "Phase = Literal" backend/`); the `sessions.close_phase` CHECK is NOT changed — `posttest` is a `zpd.step.phase` value only.
5. **Arms.** Migration `<ts>_learning_loop_arm.sql` (spec §4, verbatim). `loop_arm` is readable in the settings GET (`_SETTINGS_COLS`, `SettingsResponse.loop_arm: str | None = None`) and NOT patchable by the student (not in `ALLOWED`) — assignment is the series owner's, by SQL. `policy.variant_for(user_id: str, node_id: str, arm: str | None) -> Literal["A", "B"]`: `"A"` whenever `arm` is `None` or empty; otherwise `"A"` if the first byte of `sha256(f"{arm}:{user_id}:{node_id}")` is even, else `"B"` — concepts are randomized WITHIN a student, and a different `arm` label reshuffles. `policy.independent_min_s(band, variant) -> int`: variant `"B"` returns `GATE_INDEPENDENT_MIN_S_VARIANT_B` for the develop/profic bands, everything else is unchanged (`GATE_INDEPENDENT_MIN_S` / `GATE_INDEPENDENT_MIN_S_NOVICE`). The one call site that reads the independent-time threshold (HANDOFF-06; `grep -n GATE_INDEPENDENT_MIN_S backend/routes/learn_loop.py backend/learning/gates.py`) goes through it, and `zpd.step` payloads gain `variant` (†, a payload-key addition to spec §6). **The arm is plumbing.** With `loop_arm` NULL for everyone, every student is variant `A` and behaviour is unchanged. The first experiment is chosen by the series owner; `GATE_INDEPENDENT_MIN_S` vs `GATE_INDEPENDENT_MIN_S_VARIANT_B` is only the first candidate the ZPD report marks †.
6. **ADR** `docs/decisions/0027-learning-loop-cutover.md` in the 0026 format. Sections: Context (scalar mastery moved by an LLM tool and flat quiz deltas; the research verdict); Options considered (keep the tool with tighter bounds / evidence-only writes behind a flag then cut over / big-bang); Decision (evidence-only rule — spec §1 and §5 — the flag, the ladder rungs 1–4 with what Sapling implements for each, the cutover list of §11, the `write_metrics` exception to §5, the `variant` payload key, the `posttest` phase value); Consequences (what is deleted in half B, the follow-up that removes `LEARNING_LOOP_ENABLED` entirely, `user_profiles.learning_style` and `graph_nodes.mastery_events`-era columns left dead, the earnest-revise gate not measured). Status `accepted`; after half B append a line `Cutover executed: <date>, PR #<n>`.
7. **Evals.** `tests/evals/loop_tutor.py` has at least: two answer-leak fixtures (the reference answer's final numeric/symbolic value must not appear at rung < H6 — score with `learning.leak.detect_leak`), two sycophancy fixtures (the student asserts a wrong claim confidently; the reply must not agree — evaluator looks for a contradiction marker set defined in the module and a question), one ceiling-compliance fixture. Add only what HANDOFF-07 lists as missing; ≤ 8 cases total per dataset. `run_all.py::DATASETS` contains `check_items`, `grader`, `loop_tutor`. New cases are recorded once (`SAPLING_EVAL_MODE=record`), baselines updated with `SAPLING_EVAL_UPDATE_BASELINES=1`, cassettes + `baselines.json` committed together.
8. **Flag.** Half A adds nothing that runs when `learning_loop_active` is false: the rating and post-test routes 404, `checks_since_rating` is only touched inside the loop turn, `variant_for` is only called inside loop code, the script and the KPI endpoint read tables that are empty for a flag-off deployment. `tests/test_learning_posttest.py::test_posttest_404_when_gate_false` and `tests/test_learn_loop_rating.py::test_rating_404_when_gate_false` prove the route half.

### Behaviour — half B (spec §11, verbatim list)

1. Remove `update_mastery_tool`, `MasteryUpdateInput`, `ConceptMasteryUpdate`, `TUTOR_EVENT_TYPES` (`agents/tools/graph.py`) and the preamble paragraph `agents/chat_tutor.py:84–91`. `apply_graph_update` accepts only `new_nodes`, `new_edges`, `evidence`; the `updated_nodes` branch (`services/graph_service.py:764–784` and its event row) is deleted with its tests.
2. Remove `MASTERY_DELTA_PER_CORRECT`, `MASTERY_DELTA_PER_WRONG`, `mastery_after` (`services/quiz_config.py:102–114`) and the delta block in `submit_quiz` (`routes/quiz.py:2531–2585`). Quiz and flashcards run the PKG-11 evidence path for EVERY user — no gate. `quiz_attempts.mastery_before/mastery_after` stay and are filled from the `apply_graph_update` result (`p_before`/`p_after` of the last evidence). The `quiz.completed` payload key `mastery_delta` and the attempt-history field `mastery_delta` (`routes/quiz.py:2048`, `:2710`; `frontend/src/components/screens/Tree.tsx:34`, `:405`, `Tree.quiz.test.tsx`) are renamed `p_delta` (value `p_after − p_before`), so `test_inv_21` can grep the literal.
3. `config.MASTERY_MASTERED_MIN/LEARNING_MIN/STRUGGLING_MIN`, `get_mastery_tier`, `is_mastered`, `is_weak` are deleted; every caller uses `learning/bkt.py::tier_for` (and two new pure predicates there, `is_mastered(p) = tier_for(p) == "mastered"`, `is_weak(p) = tier_for(p) in {"struggling", "unexplored"}`). New cuts are the spec §3.1 tier mirror: `TIER_UNEXPLORED_MAX` / `BAND_NOVICE_MAX` / `BKT_PROFICIENT`. `Learn.tsx::tierForScore` mirrors them; `tests/test_mastery_tier_unification.py` imports from `learning.params`.
4. `learning_style`: the onboarding step is removed (`Onboarding.tsx` step 5 and `StepLearningStyle`, `canContinue` case 5, the `finish` guard and payload field; `api.ts` `OnboardingProfilePayload.learning_style` removed), `OnboardingBody.learning_style` becomes `Optional[str] = None` and is ignored, `routes/onboarding.py:86` stops writing it, `routes/profile.py:42` stops selecting it, the profile response model drops it (`models/__init__.py:312`). The column stays; the ADR notes it dead. Seeds (`db/seed_staging.py:156`, `db/seed_local_rich.py:167–191`, `db/e2e_checks/academics.py:43`) stop populating it.
5. `end_session` (`routes/learn.py:1145–1152`, `:1206–1212`): `mastery_changes`, `new_connections`, `recommended_next` are removed from both summary dicts; `SessionSummary.tsx` stops rendering them.
6. Flag collapse: `config.LEARNING_LOOP_ENABLED` defaults to `"true"` (only an explicit `"false"` turns it off — the kill switch stays one deploy away); `learning_loop_active` is unchanged in shape and is consulted only where the per-user opt-in matters (`routes/learn.py` delegation to `learn_loop.py`, the `/api/learn/loop/*` 404). The quiz and flashcard gates from PKG-11 are removed (both surfaces are evidence-only for everyone). The follow-up that deletes the env var entirely is a ticket, not this PR.
7. `chat_tutor.py` mode prompts fold into `loop_tutor.py`: `loop_tutor.MODE_PREFIXES: dict[TutorMode, str]` holds the three mode paragraphs (`chat_tutor.py:103–124` bodies, without the preamble); `chat_tutor.py` becomes a shim exporting `TutorMode`, `agent_for_mode(mode) -> loop_tutor_agent`, `mode_prefix(mode) -> str` and the three legacy names `socratic_agent = expository_agent = teachback_agent = loop_tutor_agent` (kept so `tests/test_chat_tutor_imports.py`, `tests/test_agent_output_schemas.py:79–84` and `tests/test_e2e_function_handlers.py:24` keep importing). `routes/learn.py::_prepare_chat_run` prepends `mode_prefix(mode)` to the assembled message on the non-opted-in path. The `chat_tutor` `AgentTask`, `_DEFAULTS` entry and `E2E_TUTOR_REPLY` handler are removed only if `grep -rn '"chat_tutor"\|E2E_TUTOR_REPLY' backend/ frontend/e2e/` shows no remaining caller after the shim; otherwise they stay and the hand-off says why.
8. Evals: `tests/evals/chat_tutor.py` drops `MASTERY_DELTA_MIN/MAX`, `_mastery_updates`, `MasteryUpdateEmittedEvaluator` and the offline graph-write stub's `mastery_delta` handling; a new `EvidenceRecordedEvaluator` scores cases tagged `expects_check` on at least one `graded_check_tool` call in `tool_calls`. `NoToolMisuseEvaluator.BANNED_SUBSTRINGS` swaps `update_mastery_tool` for `graded_check_tool`. Cassettes under `tests/evals/cassettes/chat_tutor/` are deleted and re-recorded against the shim (`SAPLING_EVAL_MODE=record venv/bin/python tests/evals/chat_tutor.py`), baselines refreshed, all committed together.
9. E2E: `frontend/e2e/support/quiz.ts` replaces `MASTERY_PER_CORRECT/WRONG` + `masteryAfter` with `bktAfterCorrect(before, n)` — the §3.1 correct-update with the learn step, channel `mc`, mirrored constants `BKT_L0`, `BKT_T`, `CHANNELS["mc"]` (pinned by a new backend test that reads the TS file, same technique as the tier mirror). `quiz.spec.ts` expects `p_after` per §Derived expectations below and one evidence row per item (or per quiz — HANDOFF-11 says which; the `node_mastery_events` count assertion at `:150–152` follows it). The seeded E2E quiz user is opted in (`user_settings.learning_loop_beta = true` in `db/seed_local_rich.py`, in the same place HANDOFF-13 seeded the loop journey's user — if that is already the same user, nothing to add).

### Schema (exact)

```sql
-- <ts>_learning_loop_arm.sql
-- Learning loop series PKG-14: within-student A/B arm label. NULL = no
-- experiment (every concept is variant A). learning/policy.py::variant_for
-- hashes (arm, user_id, node_id) so concepts are randomised WITHIN a student.
ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS loop_arm text;
```

Half B adds no migration. Columns left dead on purpose (ADR): `user_profiles.learning_style`.

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
| `KPI_TREND_WEEKS` | 4 † | this package | `htc_k_trend` |
| `GATE_LEAKS_MAX` | 0 | §10 gates | KPI gates |
| `GATE_CEILING_COMPLIANCE_MIN` | 0.95 | §10 gates | KPI gates |
| `POSTTEST_MIN_AGE_DAYS` | 2 † | research §"Measure learning…" ("≥ 2 days") | post-test selection |
| `POSTTEST_MAX_ITEMS` | 8 † | engineering cap | post-test selection |
| `GATE_INDEPENDENT_MIN_S` | 45 † | §3.3 (PKG-06) | variant A |
| `GATE_INDEPENDENT_MIN_S_NOVICE` | 90 † | §3.3 (PKG-06) | both variants, novice band |
| `GATE_INDEPENDENT_MIN_S_VARIANT_B` | 90 † | first A/B candidate (task brief) | variant B, develop/profic |
| `TIER_UNEXPLORED_MAX` | 0.10 | §3.1 (PKG-01) | `tier_for`, `tierForScore` (half B) |
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
- (11) rewritten in half B: with `LEARNING_LOOP_ENABLED=false` the gate is `False` and touches no table; with it unset the gate consults the column.

### Error semantics

Post-test grading: grader `unavailable` → 503, no evidence, `zpd.step` not emitted. KPI endpoint: any table read error propagates as the existing admin endpoints do (500); a scan hitting `_SCAN_CAP` sets `truncated`. Script: a `table()` exception on one row prints `FAIL <user> <node> <exc class>` and continues; the exit code is `1` if any row failed. Rating route: unknown `rating` → 422 from the body model.

### Events added

None. `zpd.rating` is emitted for the first time (it was registered by PKG-06). `zpd.step` gains the payload key `variant` and the phase value `posttest` (†).

## Non-goals

- No rung-4 (delayed proctored) tooling. No instructor dashboard. No uptake estimator.
- No new agent, no new `AgentTask`, no prompt change to `loop_tutor` beyond the mode fold in half B.
- No removal of `LEARNING_LOOP_ENABLED` (follow-up ticket), no removal of `user_profiles.learning_style`, no rewrite of the legacy `/api/learn/chat` request shape.
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

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task A2: Arm migration, `loop_arm` read, `variant_for`, `independent_min_s`

**Files:**
- Create: `backend/db/migrations/<UTC>_learning_loop_arm.sql`
- Modify: `backend/learning/params.py` (the `# PKG-14 (†)` block), `backend/learning/policy.py`, `backend/routes/profile.py` (`_SETTINGS_COLS`), `backend/models/__init__.py` (`SettingsResponse.loop_arm`), `backend/routes/learn_loop.py` (the one independent-time call site; `variant` in the `zpd.step` payload)
- Test: `backend/tests/test_learning_arms.py`

- [ ] **Step 1: Write the failing test**

```python
"""PKG-14: within-student arms are plumbing — NULL arm means variant A everywhere."""
import pathlib
import re
from collections import Counter

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
```

- [ ] **Step 2: Run** `cd backend && venv/bin/python -m pytest tests/test_learning_arms.py -v`
Expected: FAIL — `expected exactly one … got []`, then `ImportError: cannot import name 'variant_for'`.

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

(`hashlib` is stdlib; invariant 2 still holds.) In `routes/learn_loop.py`, read `loop_arm` once per turn alongside the existing `user_settings` read (do not add a second query if one exists — extend its column list), compute `variant = variant_for(user_id, node_id, arm)` where the check's node is known, pass it to `independent_min_s`, and add `"variant": variant` to the `zpd.step` payload. Settings: `loop_arm,` in `_SETTINGS_COLS`; `loop_arm: Optional[str] = None` on `SettingsResponse`; nothing in `ALLOWED`.

- [ ] **Step 4: Run** `cd backend && venv/bin/python -m pytest tests/test_learning_arms.py tests/test_learning_zpd_policy.py tests/test_learn_loop_routes.py tests/test_learning_loop_invariants.py -q && venv/bin/ruff check .`
Expected: all passed except `inv_20`/`inv_01` (Task A3); `All checks passed!`

- [ ] **Step 5: Commit**

```
git add backend/db/migrations/*_learning_loop_arm.sql backend/learning/params.py backend/learning/policy.py backend/routes/profile.py backend/models/__init__.py backend/routes/learn_loop.py backend/tests/test_learning_arms.py
git commit -m "feat(learning-loop): PKG-14a — loop_arm column, variant_for, independent_min_s (arm plumbing, inert when NULL)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task A3: `write_metrics` + `scripts/derive_zpd_metrics.py`

**Files:**
- Modify: `backend/learning/learner_state.py` (add `write_metrics`)
- Create: `backend/scripts/derive_zpd_metrics.py`
- Test: `backend/tests/test_learning_zpd_metrics_script.py`

**Interfaces:**
- Produces: `learner_state.write_metrics(user_id, node_id, *, htc_k, unassisted_next, assist_gap, in_zone) -> None`; `derive_zpd_metrics.compute(opps: list[dict]) -> dict` (pure: takes evidence rows newest-first, returns the four values); `derive_zpd_metrics.main(argv) -> int`.

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
    monkeypatch.setattr(s, "table", lambda name: _T({"learner_state": states, "node_mastery_events": events}[name]))
    written = []
    monkeypatch.setattr(s, "write_metrics", lambda uid, nid, **kw: written.append((uid, nid, kw)))
    assert s.main([]) == 0
    assert s.main([]) == 0
    assert written[0] == written[1]
    assert written[0][2]["unassisted_next"] == pytest.approx(1.0)


def test_dry_run_writes_nothing(monkeypatch, capsys):
    s = _script()
    monkeypatch.setattr(s, "table", lambda name: _T({"learner_state": [{"user_id": "u", "node_id": "n", "opps": 1}], "node_mastery_events": [dict(_opp(True), created_at="x", id="e")]}[name]))
    monkeypatch.setattr(s, "write_metrics", lambda *a, **k: pytest.fail("dry run must not write"))
    assert s.main(["--dry-run"]) == 0
    assert "(dry run)" in capsys.readouterr().out


def test_zero_evidence_for_expected_rows_exits_2(monkeypatch):
    s = _script()
    monkeypatch.setattr(s, "table", lambda name: _T({"learner_state": [{"user_id": "u", "node_id": "n", "opps": 5}], "node_mastery_events": []}[name]))
    monkeypatch.setattr(s, "write_metrics", lambda *a, **k: None)
    assert s.main([]) == 2


def test_no_rows_is_ok_unless_expected(monkeypatch):
    s = _script()
    monkeypatch.setattr(s, "table", lambda name: _T([]))
    assert s.main([]) == 0
    assert s.main(["--expect-rows"]) == 2


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
    BAND_WINDOW, HTC_K_WINDOW, ZPD_IN_ZONE_MAX_UNASSISTED, ZPD_IN_ZONE_MIN_ASSISTED, ZPD_IN_ZONE_MIN_GAP,
)

_EVIDENCE_COLS = "id,created_at,correct,assisted,max_rung,question_hash,channel"


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


def main(argv: list[str] | None = None) -> int:
    ...  # --dry-run, --user, --expect-rows; prints per-row line; returns 0/1/2


if __name__ == "__main__":
    sys.exit(main())
```

`limit=BAND_WINDOW * 2` leaves headroom for propagation rows that `_opportunities` drops; take the first `BAND_WINDOW` opportunities after filtering. `main` returns the exit code (the tests call it); `__main__` passes it to `sys.exit`.

- [ ] **Step 4: Run** `cd backend && venv/bin/python -m pytest tests/test_learning_zpd_metrics_script.py tests/test_learning_loop_invariants.py tests/test_learning_evidence_apply.py -q && venv/bin/ruff check .`
Expected: all passed (`inv_20`, `inv_01` now green); `All checks passed!`

- [ ] **Step 5: Commit**

```
git add backend/learning/learner_state.py backend/scripts/derive_zpd_metrics.py backend/tests/test_learning_zpd_metrics_script.py
git commit -m "feat(learning-loop): PKG-14a — nightly derive_zpd_metrics (htc_k, unassisted_next, assist_gap, in_zone) via write_metrics

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
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

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
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


def test_done_carries_ask_rating_at_threshold(client, gate_on, session_row, run_loop_turn_with_check):
    session_row["loop_state"] = {"checks_since_rating": params.ZPD_RATING_EVERY_N_CHECKS - 1}
    done = run_loop_turn_with_check(session_row["id"])
    assert done["ask_rating"] is True


def test_done_omits_ask_rating_below_threshold(client, gate_on, session_row, run_loop_turn_with_check):
    session_row["loop_state"] = {"checks_since_rating": 0}
    done = run_loop_turn_with_check(session_row["id"])
    assert "ask_rating" not in done
```

`gate_on`/`gate_off`/`session_row`/`captured_events`/`run_loop_turn_with_check` are fixtures you write in this module from the building blocks `tests/test_learn_loop_routes.py` already uses (its mocked `table`, its function-mode handler for `grader` and `loop_tutor`, `events_service.flush_now()` with a captured `table("events").insert`). Keep them local.

- [ ] **Step 2: Run** `cd backend && venv/bin/python -m pytest tests/test_learn_loop_rating.py -v`
Expected: first test `405`/`404` from a missing route (FastAPI returns 404 for an unknown path — the assertion on `detail` fails), the rest fail similarly.

- [ ] **Step 3: Implement** per §Behaviour A.3. `LoopRatingBody(session_id: str, rating: Literal["too_easy", "appropriate", "too_hard"])`. Increment the counter beside the evidence append; persist it with the other `loop_state` writes of that turn (one upsert, not a second). Frontend: in `LoopLearn.tsx` keep `askRating` state set from the `done` handler HANDOFF-13 describes; render the three buttons under `data-testid="loop-rating"`; on click call `submitLoopRating(sessionId, rating)` then hide. `api.ts`: `export const submitLoopRating = (sessionId: string, rating: "too_easy" | "appropriate" | "too_hard") => fetchJSON<{ ok: true }>("/api/learn/loop/rating", { method: "POST", body: JSON.stringify({ session_id: sessionId, rating }) });`.

- [ ] **Step 4: Run** `cd backend && venv/bin/python -m pytest tests/test_learn_loop_rating.py tests/test_learn_loop_routes.py tests/test_event_capture_seams.py -q && venv/bin/ruff check . && cd ../frontend && npx tsc --noEmit`
Expected: all passed; `All checks passed!`; tsc clean.

- [ ] **Step 5: Commit**

```
git add backend/routes/learn_loop.py backend/models/__init__.py backend/tests/test_learn_loop_rating.py frontend/src/components/learn/LoopLearn.tsx frontend/src/lib/api.ts
git commit -m "feat(learning-loop): PKG-14a — zpd.rating prompt every ZPD_RATING_EVERY_N_CHECKS checks

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

(Add `backend/services/chat_stream.py` to the `git add` only if the `done_extra` kwarg was needed.)

### Task A6: Tool-removed post-test

**Files:**
- Modify: `backend/routes/learn_loop.py`, `backend/models/__init__.py` (`PosttestStartBody`, `PosttestAnswerBody`), `backend/learning/params.py` (`POSTTEST_*` already added in A2 — verify), every `Literal` that types `zpd.step.phase`
- Test: `backend/tests/test_learning_posttest.py`

- [ ] **Step 1: Write the failing test**

```python
"""PKG-14 rung 3: tool-removed, delayed post-test (spec §10; research §"Measure learning…")."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from learning import params

NOW = datetime(2026, 9, 26, tzinfo=timezone.utc)
OLD = (NOW - timedelta(days=params.POSTTEST_MIN_AGE_DAYS + 1)).isoformat()
FRESH = (NOW - timedelta(hours=1)).isoformat()


def test_posttest_404_when_gate_false(client, gate_off):
    assert client.post("/api/learn/loop/posttest/start", json={"course_id": "c"}).status_code == 404
    assert client.post("/api/learn/loop/posttest/answer", json={"node_id": "n", "question_hash": "q", "answer": "x"}).status_code == 404


def test_start_serves_only_concepts_taught_long_enough_ago(client, gate_on, tables, freeze_now):
    freeze_now(NOW)
    tables["learner_state"] = [
        {"user_id": "u", "node_id": "n-old", "last_evidence_at": OLD},
        {"user_id": "u", "node_id": "n-fresh", "last_evidence_at": FRESH},
        {"user_id": "u", "node_id": "n-none", "last_evidence_at": None},
    ]
    tables["graph_nodes"] = [{"id": "n-old", "course_id": "c"}, {"id": "n-fresh", "course_id": "c"}, {"id": "n-none", "course_id": "c"}]
    tables["check_items"] = [item("n-old", "q-old", fmt="free", difficulty=2)]
    r = client.post("/api/learn/loop/posttest/start", json={"course_id": "c"})
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert [i["node_id"] for i in items] == ["n-old"]
    assert items[0]["prompt"] == "What is a closure?"  # decrypted
    assert set(items[0]) == {"node_id", "question_hash", "format", "difficulty", "prompt"}


def test_start_caps_items_oldest_first(client, gate_on, tables, freeze_now):
    freeze_now(NOW)
    n = params.POSTTEST_MAX_ITEMS + 2
    tables["learner_state"] = [{"user_id": "u", "node_id": f"n{i}", "last_evidence_at": (NOW - timedelta(days=params.POSTTEST_MIN_AGE_DAYS + i)).isoformat()} for i in range(n)]
    tables["graph_nodes"] = [{"id": f"n{i}", "course_id": "c"} for i in range(n)]
    tables["check_items"] = [item(f"n{i}", f"q{i}") for i in range(n)]
    items = client.post("/api/learn/loop/posttest/start", json={"course_id": "c"}).json()["items"]
    assert len(items) == params.POSTTEST_MAX_ITEMS
    assert items[0]["node_id"] == f"n{n - 1}"  # oldest evidence first


def test_answer_grades_and_records_unassisted_evidence(client, gate_on, tables, grader_says, applied, captured_events):
    tables["check_items"] = [item("n1", "q1", fmt="free")]
    tables["graph_nodes"] = [{"id": "n1", "course_id": "c"}]
    grader_says(correct=True, confidence=0.9)
    r = client.post("/api/learn/loop/posttest/answer", json={"node_id": "n1", "question_hash": "q1", "answer": "a function with its lexical scope"})
    assert r.status_code == 200 and r.json() == {"correct": True, "confidence": 0.9}
    (call,) = applied
    (ev,) = call["graph_update"]["evidence"]
    assert ev["assisted"] is False and ev["max_rung"] == 0 and ev["session_id"] is None
    assert ev["channel"] == "free_response" and ev["question_hash"] == "q1"
    (step,) = [e for e in captured_events if e["event_type"] == "zpd.step"]
    assert step["payload"]["phase"] == "posttest"
    assert step["payload"]["max_rung_used"] == 0 and step["payload"]["assisted"] is False


def test_answer_grader_unavailable_is_503_and_writes_nothing(client, gate_on, tables, grader_unavailable, applied, captured_events):
    tables["check_items"] = [item("n1", "q1")]
    tables["graph_nodes"] = [{"id": "n1", "course_id": "c"}]
    r = client.post("/api/learn/loop/posttest/answer", json={"node_id": "n1", "question_hash": "q1", "answer": "x"})
    assert r.status_code == 503 and r.json()["detail"] == "grader unavailable"
    assert applied == [] and not [e for e in captured_events if e["event_type"] == "zpd.step"]


def test_posttest_is_a_step_phase_value_not_a_close_phase():
    import glob
    sql = "".join(open(p).read() for p in glob.glob("db/migrations/*_learning_session_close.sql"))
    assert "posttest" not in sql
    from routes import learn_loop
    assert "posttest" in learn_loop.STEP_PHASES
```

`item(...)` builds an encrypted `check_items` row with `services.encryption.encrypt_if_present` on `prompt`/`reference_answer`/`rubric_json`/`common_wrong_json` (the same helper `tests/test_learning_check_items.py` uses — copy it). `grader_says`/`grader_unavailable` monkeypatch the grader callable HANDOFF-05 names; `applied` monkeypatches `learn_loop.apply_graph_update` to record calls and return `[{"node_id": "n1", "before": 0.35, "after": 0.71}]`; `freeze_now` monkeypatches the module's `_now()`; `tables` is a dict served by a `_mock_table`-style factory for every `table` the route module and `check_item_service` import.

- [ ] **Step 2: Run** `cd backend && venv/bin/python -m pytest tests/test_learning_posttest.py -v`
Expected: 404s on the second test onward (`assert 404 == 200`), `AttributeError: … has no attribute 'STEP_PHASES'`.

- [ ] **Step 3: Implement** per §Behaviour A.4. Define `STEP_PHASES: tuple[str, ...]` in `routes/learn_loop.py` if PKG-07 typed the phase inline (otherwise extend PKG-07's `Literal` and alias it). The node→course filter: read `graph_nodes` `id,course_id` for the candidate node ids in one `in.(…)` select. `_now()` is a module-level function (`datetime.now(timezone.utc)`) so tests can freeze it. Emit the `zpd.step` payload with every §6 key; the ones without a meaning here are `None` (`rungs: []`, `time_to_first_attempt_ms: None`, …) — never fabricated.

- [ ] **Step 4: Run** `cd backend && venv/bin/python -m pytest tests/test_learning_posttest.py tests/test_learn_loop_routes.py tests/test_learning_loop_invariants.py -q -k "posttest or loop_routes or inv_05" && venv/bin/ruff check .`
Expected: all passed; `All checks passed!`

- [ ] **Step 5: Commit**

```
git add backend/routes/learn_loop.py backend/models/__init__.py backend/tests/test_learning_posttest.py backend/learning/params.py
git commit -m "feat(learning-loop): PKG-14a — tool-removed post-test (/posttest/start, /posttest/answer; ceiling H0, no RAG, no brief)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task A7: Evals (leakage + sycophancy fixtures, `run_all`) and ADR 0027

**Files:**
- Modify: `backend/tests/evals/loop_tutor.py`, `backend/tests/evals/run_all.py`, `backend/tests/evals/baselines.json`, `backend/tests/evals/cassettes/loop_tutor/*` (recorded)
- Create: `docs/decisions/0027-learning-loop-cutover.md`

- [ ] **Step 1: Gap check.** Read HANDOFF-07 "Known gaps" and `grep -n "leak\|sycophan\|insists\|ceiling" backend/tests/evals/loop_tutor.py`. For each of (2 answer-leak, 2 sycophancy, 1 ceiling-compliance) missing, add a `Case` with `metadata={"kind": "leak"|"sycophancy"|"ceiling", ...}` and, if absent, the evaluator: `NoAnswerLeakEvaluator` (uses `learning.leak.detect_leak(reference, emitted, rung)` with the fixture's reference answer in metadata), `NoSycophancyEvaluator` (reply must contain a marker from a module-level `CONTRADICTION_MARKERS` tuple AND end with a question), `CeilingComplianceEvaluator` (cassette `tool_calls`/metadata rung ≤ metadata ceiling). Total cases ≤ 8.
- [ ] **Step 2:** `run_all.py::DATASETS` = existing + `"check_items", "grader", "loop_tutor"` (only the ones missing). Run `cd backend && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/run_all.py` → the new cases fail with `No cassette for loop_tutor/<case>`.
- [ ] **Step 3:** Record ONLY the new dataset (`SAPLING_EVAL_MODE=record venv/bin/python tests/evals/loop_tutor.py`, needs `GEMINI_API_KEY`), eyeball the deltas, then `SAPLING_EVAL_UPDATE_BASELINES=1 venv/bin/python tests/evals/loop_tutor.py`. Re-run replay: every evaluator ≥ baseline.
- [ ] **Step 4:** Write the ADR per §Behaviour A.6. Status `accepted`, Date today, `Relates to:` the spec path, ADR 0024 (honest degrade), ADR 0015 (the tutor being replaced), `#620` (no flag system).
- [ ] **Step 5: Run** `cd backend && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/run_all.py && venv/bin/ruff check .`
Expected: `PASS` for every dataset; `All checks passed!`
- [ ] **Step 6: Commit** (cassettes + baselines together, as `tests/evals/README.md` requires)

```
git add backend/tests/evals/loop_tutor.py backend/tests/evals/run_all.py backend/tests/evals/baselines.json backend/tests/evals/cassettes/loop_tutor docs/decisions/0027-learning-loop-cutover.md
git commit -m "evals(learning-loop): PKG-14a — leak + sycophancy + ceiling fixtures, run_all covers series datasets; ADR 0027

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
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

Constants chosen: every † row of the table. Deviations: `write_metrics` (spec §5 says only `apply_graph_update` writes `learner_state`); `variant` payload key and `posttest` phase value (spec §6); `done_extra` if used. Known gaps: earnest-revise gate not measured; rating prompt not E2E-covered (needs 30 checks); `loop_arm` NULL for everyone until the owner picks an experiment. Open questions: which experiment first; whether `chat_tutor` task/handler survive half B.
- [ ] **Step 2:** Append ledger row `| 14 | eval-ladder-cutover | done (half A) | feat/learning-loop-14a-eval-ladder | <sha> | 6 modules | — | HANDOFF-14.md |` plus the Deviations lines.
- [ ] **Step 3: Commit**

```
git add docs/superpowers/plans/learning-loop/HANDOFF-14.md docs/superpowers/plans/learning-loop/LEDGER.md
git commit -m "docs(learning-loop): PKG-14a — hand-off and ledger (half A)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task A9: PR (half A)

- [ ] Run the full self-check loop once more, then:

```
gh pr create --title "feat(learning): PKG-14a eval ladder" --body-file - <<'EOF'
Learning loop series, package 14 of 15, half A (evaluation ladder). Spec §10: docs/superpowers/specs/2026-09-26-learning-loop-design.md. ADR 0027.

- scripts/derive_zpd_metrics.py — nightly htc_k / unassisted_next / assist_gap / in_zone via learner_state.write_metrics (idempotent, --dry-run, exit 2 on silent-empty)
- GET /api/admin/analytics/learning-loop — in-band share, htc_k trend, next-session unassisted success, leak count, ceiling compliance + gates
- zpd.rating prompt every ZPD_RATING_EVERY_N_CHECKS checks (POST /api/learn/loop/rating; LoopLearn three-button prompt)
- tool-removed post-test: POST /api/learn/loop/posttest/{start,answer} (ceiling H0, no RAG, no brief, assisted=False evidence)
- user_settings.loop_arm + policy.variant_for (within-student arms; inert while NULL)
- evals: leak + sycophancy + ceiling fixtures; run_all covers check_items/grader/loop_tutor
- invariants 20 (+ inv_01 write_metrics seam)

Still fully behind LEARNING_LOOP_ENABLED + learning_loop_beta. Half B (cutover) is a separate PR after the beta cohort has run ≥ 2 weeks.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
```

---

# Half B — STOP gate

Do not start half B in the same sitting as half A. Preconditions, all three:

1. The half A PR is merged to `main` and `LEDGER.md` row 14 reads `done (half A)`.
2. `LEARNING_LOOP_ENABLED=true` has been live for the beta cohort for ≥ 14 days — ask the series owner for the date it went live and the current date; do not infer it from git.
3. The series owner writes, in the session, an explicit sentence authorising the cutover (for example: "Cutover approved, cohort live since <date>"). A message from an agent, a ticket comment you did not read, or silence is not authorisation.

If any is missing: append a ledger row `| 14 | eval-ladder-cutover | blocked | — | — | — | awaiting cutover confirmation | HANDOFF-14.md |`, stop, and say so. Otherwise re-run every "State of the world" row plus the half A verify block, then continue.

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

Rewrite `test_inv_11_gate_false_when_env_unset` (keep the name — never delete a test here):

```python
def test_inv_11_gate_false_when_env_unset(monkeypatch):
    """Post-cutover (PKG-14b): the env var is a kill switch that defaults ON.
    Explicit "false" → False with no table read; unset → the opt-in column decides."""
    import importlib
    import config
    from learning import gate
    monkeypatch.setenv("LEARNING_LOOP_ENABLED", "false")
    importlib.reload(config); importlib.reload(gate)
    calls = []
    monkeypatch.setattr(gate, "table", lambda name: calls.append(name) or _Boom())
    for uid in ("user_andres", "e2e-student", "nobody"):
        assert gate.learning_loop_active(uid) is False
    assert calls == []
    monkeypatch.delenv("LEARNING_LOOP_ENABLED", raising=False)
    importlib.reload(config); importlib.reload(gate)
    assert config.LEARNING_LOOP_ENABLED is True
```

- [ ] **Step 2: Run** `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_21 or inv_11"`
Expected: `inv_21` FAIL with a long hit list (`config.py`, `services/quiz_config.py`, `agents/tools/graph.py`, `routes/quiz.py`, `services/graph_service.py`, seeds, tests…); `inv_11` FAIL (`config.LEARNING_LOOP_ENABLED is False`). Save the hit list — it is your worklist for B2–B5.

- [ ] **Step 3: Commit**

```
git add backend/tests/test_learning_loop_invariants.py
git commit -m "test(learning-loop): PKG-14b — inv_21 no legacy mastery writers; inv_11 kill-switch semantics

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task B2: Remove the tutor mastery tool; fold mode prompts into `loop_tutor`; retire `chat_tutor` cassettes

**Files:**
- Modify: `backend/agents/tools/graph.py`, `backend/agents/chat_tutor.py` (→ shim), `backend/agents/loop_tutor.py` (`MODE_PREFIXES`), `backend/routes/learn.py` (`_prepare_chat_run`), `backend/services/graph_service.py` (delete the `updated_nodes` branch), `backend/agents/deps.py` (drop `mastery_changes` only if no reader remains — `grep -rn mastery_changes backend/`), `backend/tests/evals/chat_tutor.py`, `backend/tests/evals/baselines.json`, `backend/tests/evals/cassettes/chat_tutor/*`, `backend/tests/test_graph_tools_bugs.py` (delete the `update_mastery_tool` classes), `backend/tests/test_prompt_injection.py:399–413` (delete that test; its docstring line 28), `backend/tests/test_graph_service.py` (delete the `updated_nodes` tests at `:612–730`, `:809`, `:871–910`, `:1014`, `:1075` — verify each tests the deleted branch before deleting), `backend/tests/test_shared_course_context.py:440–497` (rewrite to drive `apply_graph_update` with `evidence` instead of `updated_nodes`), `backend/tests/test_chat_tutor_imports.py`, `backend/tests/test_agent_output_schemas.py:79–84`
- Test: `backend/tests/test_chat_tutor_shim.py`

- [ ] **Step 1: Write the failing test**

```python
"""PKG-14b: chat_tutor is a shim over loop_tutor; the mastery tool is gone."""
import pytest


def test_mastery_tool_symbols_are_gone():
    import agents.tools.graph as g
    for name in ("update_mastery_tool", "MasteryUpdateInput", "ConceptMasteryUpdate", "TUTOR_EVENT_TYPES"):
        assert not hasattr(g, name), name


def test_agent_for_mode_returns_loop_tutor():
    from agents.chat_tutor import agent_for_mode, socratic_agent, expository_agent, teachback_agent
    from agents.loop_tutor import loop_tutor_agent
    assert agent_for_mode("socratic") is loop_tutor_agent
    assert agent_for_mode(None) is loop_tutor_agent
    assert socratic_agent is expository_agent is teachback_agent is loop_tutor_agent


@pytest.mark.parametrize("mode,marker", [("socratic", "MODE: Socratic"), ("expository", "MODE: Expository"), ("teachback", "MODE: TeachBack")])
def test_mode_prefix_is_the_folded_paragraph(mode, marker):
    from agents.chat_tutor import mode_prefix
    from agents.loop_tutor import MODE_PREFIXES
    assert mode_prefix(mode) == MODE_PREFIXES[mode]
    assert marker in mode_prefix(mode)
    assert "update_mastery_tool" not in mode_prefix(mode)


def test_preamble_no_longer_instructs_mastery_writes():
    import agents.loop_tutor as lt
    import inspect
    src = inspect.getsource(lt)
    assert "update_mastery_tool" not in src and "+0.1 to +0.3" not in src


def test_apply_graph_update_rejects_updated_nodes():
    from services.graph_service import apply_graph_update
    with pytest.raises(ValueError, match="updated_nodes"):
        apply_graph_update("u", {"updated_nodes": [{"concept_name": "X"}]}, "c")
```

- [ ] **Step 2: Run** `cd backend && venv/bin/python -m pytest tests/test_chat_tutor_shim.py -v` → FAIL on every test.

- [ ] **Step 3: Implement** per §Behaviour B.1, B.7, B.8. `apply_graph_update` raises `ValueError("updated_nodes is no longer accepted (PKG-14b): pass evidence")` when the key is present — loud, not silent. `_prepare_chat_run` prepends `mode_prefix(mode) + "\n\n"` to the assembled message when `deps.learning_loop` is false. Delete `cassettes/chat_tutor/`, adjust `CASES` metadata (`expects_mastery_update` → `expects_check` on the teachback cases only; expository cases lose the tag), re-record, update baselines. Decide the `chat_tutor` task/handler fate by the grep rule in B.7 and write the outcome in the hand-off.

- [ ] **Step 4: Run** `cd backend && venv/bin/python -m pytest tests/ -q && venv/bin/ruff check . && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/run_all.py`
Expected: zero failures (`inv_21` still red — B3/B4 finish it); `All checks passed!`; every dataset `PASS`.

- [ ] **Step 5: Commit** (one commit; the message lists every deleted test by name)

```
git add -A backend/agents backend/routes/learn.py backend/services/graph_service.py backend/tests
git commit -m "feat(learning-loop): PKG-14b — remove update_mastery_tool and the updated_nodes path; chat_tutor is a loop_tutor shim; chat_tutor cassettes re-recorded

Deleted tests (their code is deleted in this commit): <list>

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task B3: Quiz — evidence only; `p_delta` on the wire; E2E expectation

**Files:**
- Modify: `backend/services/quiz_config.py`, `backend/routes/quiz.py`, `backend/routes/flashcards.py` (drop the PKG-11 gate branch), `backend/services/events_service.py:46` (docstring row: `mastery_delta` → `p_delta`), `backend/tests/test_quiz_scoring_e.py`, `backend/tests/test_quiz_routes.py:38`, `:186–208`, `:675–678`, `backend/tests/test_quiz_lifecycle_d.py:474–478`, `backend/tests/test_event_capture_seams.py:956`, `backend/tests/integration/test_quiz_lifecycle_db.py:42–51`, `backend/tests/test_learning_flashcards_fsrs.py` (gate tests → ungated), `frontend/src/components/screens/Tree.tsx:34`, `:405`, `frontend/src/components/screens/Tree.quiz.test.tsx`, `frontend/src/lib/api.ts` (attempt type), `frontend/e2e/support/quiz.ts`, `frontend/e2e/quiz.spec.ts`, `backend/db/seed_local_rich.py` (opt-in for the E2E quiz user)
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

`quiz.spec.ts`: `EXPECTED_AFTER = bktAfterCorrect(BKT_L0, QUIZ_LENGTH)` (or from `SEEDED_MASTERY` per §Derived expectations), `expect(masteryAfterDb).toBeCloseTo(EXPECTED_AFTER, 5)`, and the `node_mastery_events` assertion counts `QUIZ_LENGTH` rows (or 1 — HANDOFF-11) each with `event_type = 'evidence'`. If HANDOFF-11 says the channel differs, recompute:

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
git add -A backend/services/quiz_config.py backend/routes/quiz.py backend/routes/flashcards.py backend/services/events_service.py backend/tests backend/db/seed_local_rich.py frontend/src frontend/e2e/support/quiz.ts frontend/e2e/quiz.spec.ts
git commit -m "feat(learning-loop): PKG-14b — quiz and flashcards are evidence-only; p_delta replaces mastery_delta; E2E expects the BKT posterior

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task B4: Tiers — `get_mastery_tier` → `bkt.tier_for` everywhere

**Files:**
- Modify: `backend/config.py:100–141` (delete the block), `backend/learning/bkt.py` (`is_mastered`, `is_weak`), `backend/services/graph_service.py:7`, `:735`, `backend/agents/tools/chat_context.py:47`, `:492`, `:562–564`, `backend/routes/flashcards.py:14`, `:180`, `:199`, `backend/db/seed_staging.py:34`, `:238`, `backend/db/seed_local_rich.py:19`, `:324`, `backend/db/archive/seed.py:14`, `:59`, `backend/db/e2e_checks/quiz.py:20–27` (0.3 is `learning` under the new cuts — set the comment and `mastery_tier` accordingly), `backend/tests/test_config.py` (rewrite against `tier_for` with `TIER_UNEXPLORED_MAX`/`BAND_NOVICE_MAX`/`BKT_PROFICIENT` boundaries), `backend/tests/test_mastery_tier_unification.py` (import `tier_for`, `is_mastered`, `is_weak` from `learning.bkt`; `SCORES` adds `0.29, 0.3, 0.94, 0.95`; the frontend pin compares to `params`), `backend/tests/test_seed_staging.py:232–235`, `backend/tests/test_chat_context_tools.py:315`, `frontend/src/components/screens/Learn.tsx:86–93`, `frontend/src/lib/quiz/proposals.ts:17` (comment)

- [ ] **Step 1:** Update `test_mastery_tier_unification.py` first (it is the failing test): every `from config import …` becomes `from learning.bkt import …` / `from learning.params import …`; `found == {"mastered": BKT_PROFICIENT, "learning": BAND_NOVICE_MAX, "struggling": TIER_UNEXPLORED_MAX}`. Run → FAIL (`ImportError` on `learning.bkt.is_mastered`, then the mirror mismatch).
- [ ] **Step 2:** Implement: add the two predicates to `bkt.py` (pure, importing only `params`); sweep every anchor above (`grep -rn "get_mastery_tier\|MASTERY_MASTERED_MIN\|MASTERY_LEARNING_MIN\|MASTERY_STRUGGLING_MIN\|from config import is_\|is_mastered\|is_weak" backend/ --include='*.py' | grep -v venv` must show only `learning/bkt.py` and its tests); `tierForScore` cuts become `0.95` / `0.3` / `0.1` with the comment pointing at `learning/params.py`.
- [ ] **Step 3: Run** `cd backend && venv/bin/python -m pytest tests/ -q && venv/bin/ruff check . && cd ../frontend && npx tsc --noEmit`
Expected: zero failures; `inv_21` still lists only `mastery_delta` hits left for B5 (if any); clean.
- [ ] **Step 4: Commit**

```
git add -A backend frontend/src/components/screens/Learn.tsx frontend/src/lib/quiz/proposals.ts
git commit -m "feat(learning-loop): PKG-14b — one tier function: learning.bkt.tier_for (0.10/0.30/0.95) replaces config.get_mastery_tier

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task B5: `learning_style`, the empty summary lists, flag collapse

**Files:**
- Modify: `backend/config.py` (`LEARNING_LOOP_ENABLED` default `"true"`), `backend/tests/test_learning_gate.py` (env-unset cases now expect the column read; explicit `"false"` variants keep the no-read assertion), `backend/routes/onboarding.py:86`, `backend/routes/profile.py:42`, `backend/models/__init__.py:312`, `backend/tests/test_onboarding_routes.py:23`, `:224`, `:283`, `backend/tests/test_profile_routes.py:851`, `:888`, `backend/db/seed_staging.py:156`, `backend/db/seed_local_rich.py:167–191`, `backend/db/e2e_checks/academics.py:32–43`, `backend/routes/learn.py:1145–1152`, `:1206–1212`, `frontend/src/components/screens/Onboarding.tsx`, `frontend/src/lib/api.ts:999`, `frontend/src/components/chat/SessionSummary.tsx`, `frontend/src/components/screens/Learn.applyGraphDelta.test.ts:68`, `frontend/e2e/*.spec.ts` that click the learning-style step (`grep -rn "learning-style\|learning_style" frontend/e2e`)
- Test: `backend/tests/test_cutover_removals.py`

- [ ] **Step 1: Write the failing test**

```python
"""PKG-14b: spec §11 removals that are not covered by inv_21's grep."""
import importlib
import inspect


def test_env_flag_defaults_on(monkeypatch):
    monkeypatch.delenv("LEARNING_LOOP_ENABLED", raising=False)
    import config
    importlib.reload(config)
    assert config.LEARNING_LOOP_ENABLED is True
    monkeypatch.setenv("LEARNING_LOOP_ENABLED", "false")
    importlib.reload(config)
    assert config.LEARNING_LOOP_ENABLED is False


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
```

- [ ] **Step 2: Run** → FAIL on all four.
- [ ] **Step 3: Implement** per §Behaviour B.4–B.6. Onboarding: step 5 disappears (renumber nothing else; `canContinue` loses `case 5`; the step count constant if any drops by one; delete `StepLearningStyle` if unused elsewhere). `SessionSummary.tsx` renders only `concepts_covered` and `time_spent_minutes`.
- [ ] **Step 4: Run** `cd backend && venv/bin/python -m pytest tests/ -q && venv/bin/ruff check . && cd ../frontend && npx tsc --noEmit && npx vitest run`
Expected: zero failures; `inv_21` PASS; `inv_11` PASS; clean.
- [ ] **Step 5: Commit**

```
git add -A backend frontend
git commit -m "feat(learning-loop): PKG-14b — drop learning_style onboarding, empty session-summary lists; LEARNING_LOOP_ENABLED defaults on

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task B6: Full E2E gate

- [ ] **Step 1:** Under ONE lock: `flock /tmp/claude-$(id -u)/sapling-e2e-stack.lock sh -c 'make e2e-up && (cd frontend && npx playwright test) ; s=$?; (cd backend && venv/bin/python -m e2e_oracles); o=$?; make e2e-down; exit $((s|o))'`
Expected: every journey passes (`quiz.spec.ts` with the BKT expectation, `learn-loop.spec.ts`, `tutor.spec.ts`/`streaming.spec.ts` against the shim's reply constant, onboarding without the learning-style step); oracles exit 0; logscan `ALLOWLIST` untouched.
- [ ] **Step 2:** Sync check: `grep -o "E2E_[A-Z_]*" backend/agents/function_handlers_e2e.py | sort -u` versus every `frontend/e2e/*.spec.ts` and `tests/test_e2e_function_handlers.py` — any constant you removed (B2's grep rule) is gone from all three; none is dangling.
- [ ] **Step 3:** Fix forward on this branch; a failing journey that reveals a bug in an earlier package follows the README rule (separate `fix(learning-loop): PKG-MM — …` commit, `MM | reopened` row, post-hoc note). Commit any spec/handler sync changes: `git commit -m "test(learning-loop): PKG-14b — E2E journeys on the cutover base"`.

### Task B7: Hand-off + ledger (half B)

- [ ] **Step 1:** Append to `HANDOFF-14.md` a `## Half B` section with the same headings, and REPLACE its "Verify commands" block with exactly:

```
cd backend && venv/bin/python -m pytest tests/ -q                                                → zero failures
ls docs/decisions/*learning-loop-cutover*.md                                                      → 1 file
grep -c "update_mastery_tool" backend/agents/tools/graph.py                                      → 0
grep -c "MASTERY_DELTA_PER" backend/services/quiz_config.py                                      → 0
```

Append `Cutover executed: <date>, PR #<n>` to ADR 0027's Status block. Deviations: `inv_11` semantics; `p_delta` rename; deleted tests (list); `chat_tutor` task fate. Known gaps: `LEARNING_LOOP_ENABLED` removal ticket; `user_profiles.learning_style` column; `SaplingDeps.mastery_changes` if kept.
- [ ] **Step 2:** Ledger row `| 14 | eval-ladder-cutover | done | feat/learning-loop-14b-cutover | <sha> | 4 modules | — | HANDOFF-14.md |` plus, if any earlier package was touched, its `reopened` row.
- [ ] **Step 3: Commit**

```
git add docs/superpowers/plans/learning-loop/HANDOFF-14.md docs/superpowers/plans/learning-loop/LEDGER.md docs/decisions/0027-learning-loop-cutover.md
git commit -m "docs(learning-loop): PKG-14b — hand-off, ledger, ADR cutover note

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task B8: PR (half B)

```
gh pr create --title "feat(learning): PKG-14b cutover" --body-file - <<'EOF'
Learning loop series, package 14 of 15, half B (cutover). Spec §11: docs/superpowers/specs/2026-09-26-learning-loop-design.md. ADR 0027. Authorised by the series owner on <date> after ≥ 2 weeks of beta.

Removed: update_mastery_tool + ConceptMasteryUpdate + the preamble paragraph; MASTERY_DELTA_PER_* + mastery_after + the submit_quiz delta block; config.get_mastery_tier + MASTERY_*_MIN (→ learning.bkt.tier_for, cuts 0.10/0.30/0.95); the learning_style onboarding step and reads (column stays); the three always-empty end_session lists; the updated_nodes path of apply_graph_update; the quiz/flashcard gate branches.
Changed: LEARNING_LOOP_ENABLED defaults on (explicit "false" is the kill switch); chat_tutor is a shim over loop_tutor with a mode prefix; quiz.completed and attempt history carry p_delta; chat_tutor cassettes re-recorded; quiz E2E expects the BKT posterior; E2E quiz user opted in.
Invariants: 21 asserted. Full E2E gate green.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
```

## Self-check loop (run after every task, and once more before each PR)

1. `cd backend && venv/bin/ruff check . && venv/bin/ruff format --check learning tests/test_learning_*.py`
2. `venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q`
3. `venv/bin/python -m pytest tests/ -q` (no `SAPLING_MODEL_MODE` exported)
4. Prompts/tool descriptions touched? **Half A: No** (fixtures and evaluators only — evals still run: `SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/run_all.py`, every dataset `PASS`). **Half B: Yes** (`loop_tutor.MODE_PREFIXES`, the deleted preamble paragraph, `chat_tutor` retired) → re-record `chat_tutor` only, then `run_all.py` in replay must `PASS` for every dataset; `loop_tutor`/`grader`/`check_items` baselines must not move (their prompts are untouched).
5. Request-path agent or route touched? **Half A: Yes** (`learn_loop.py` rating + post-test; `admin_analytics.py`) → run the PKG-13 lane row (`learn-loop.spec.ts` + oracles) under the lock before the PR. **Half B: Yes** → Task B6's full lane.
6. Scope check: `git diff --stat main...HEAD` — every path must be in this half's Files lists (half B's lists are grep-driven; anything the `inv_21` hit list or the B4/B5 greps named counts). Anything else: `git checkout main -- <path>` or record a Deviation.
7. Sync check: `grep -o "E2E_[A-Z_]*" backend/agents/function_handlers_e2e.py | sort -u` — half A: unchanged from `main`; half B: changed only by the B2 grep rule, mirrored in specs and `tests/test_e2e_function_handlers.py`.

Green = all seven clean. Max 5 iterations per loop; then write a `BLOCKED` row in `LEDGER.md` with hypothesis, commands, outputs, and stop.

## Regression guard

- Half A: suite count N₀ unchanged except the tests this half adds; zero failures; zero new skips outside `test_learning_loop_invariants.py`. `tests/test_learn_loop_routes.py`, `tests/test_learning_zpd_policy.py`, `tests/test_learning_evidence_apply.py`, `tests/test_learning_check_tool.py`, `tests/test_admin_analytics_routes.py`, `tests/test_event_capture_seams.py`, `tests/test_model_mode_seam.py` green and unmodified. With `LEARNING_LOOP_ENABLED` unset: the new routes 404, `loop_state.checks_since_rating` never written, no behaviour change anywhere.
- Half B: the only tests that may disappear are the ones whose code disappears, each named in its commit message. `tests/test_learning_bkt.py`, `tests/test_learning_fsrs.py`, `tests/test_learning_evidence_apply.py`, `tests/test_learning_check_items.py`, `tests/test_learning_check_tool.py`, `tests/test_learning_zpd_policy.py`, `tests/test_learn_loop_routes.py`, `tests/test_learning_probe_planner.py`, `tests/test_learning_close_brief.py`, `tests/test_learning_misconceptions.py`, `tests/test_learning_review.py` green and unmodified. `tests/test_event_capture_seams.py::test_event_taxonomy_is_pinned` unchanged (no taxonomy change). The `document` upload path (`routes/documents.py:633`, `:1222` → `apply_graph_update` with `new_nodes`) unchanged and green.

## Acceptance criteria (the next session pastes these)

Half A:
1. `cd backend && venv/bin/python -m pytest tests/test_learning_zpd_metrics_script.py tests/test_admin_learning_loop_kpis.py tests/test_learn_loop_rating.py tests/test_learning_posttest.py tests/test_learning_arms.py -q` → all passed
2. `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_20 or inv_01"` → `2 passed`
3. `ls backend/db/migrations/*_learning_loop_arm.sql` → 1 file; `ls docs/decisions/*learning-loop-cutover*.md` → 1 file
4. `cd backend && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/run_all.py` → `PASS` for every dataset, and `grep -c '"check_items"\|"grader"\|"loop_tutor"' backend/tests/evals/run_all.py` → 3
5. `cd backend && venv/bin/python -m pytest tests/ -q` → zero failures; `venv/bin/ruff check .` → `All checks passed!`
6. `curl` is not needed: `grep -n '"/learning-loop"' backend/routes/admin_analytics.py` → 1 hit; `grep -c "posttest/start\|posttest/answer\|/rating" backend/routes/learn_loop.py` → ≥ 3
7. `LEDGER.md` has row `14 | eval-ladder-cutover | done (half A) | …`.

Half B:
1. `cd backend && venv/bin/python -m pytest tests/ -q` → zero failures
2. `ls docs/decisions/*learning-loop-cutover*.md` → 1 file
3. `grep -c "update_mastery_tool" backend/agents/tools/graph.py` → 0
4. `grep -c "MASTERY_DELTA_PER" backend/services/quiz_config.py` → 0
5. `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q` → every test passed, none skipped except `inv_10` if no `lru_cache` exists under `learning/`
6. `grep -rn "get_mastery_tier\|learning_style" backend/routes backend/services backend/agents backend/config.py` → 0 hits
7. Full E2E lane (Task B6) green; `LEDGER.md` has row `14 | eval-ladder-cutover | done | feat/learning-loop-14b-cutover | …`.

## Hand-off

`docs/superpowers/plans/learning-loop/HANDOFF-14.md` per the template, written twice (Task A8, extended in Task B7). After half B its "Verify commands" block is exactly the four canonical lines in Task B7. Open questions to record: the first experiment for `loop_arm`; whether `LEARNING_LOOP_ENABLED` is removed next sprint; whether `earnest-revise` gets a signal (a `zpd.step` key or a grader flag) so the third §10 gate becomes measurable; whether the `updated_nodes` key in stored `messages.graph_update_json` needs a read-side migration (it does not today — `end_session` only reads names).

## Do not

- Do not start half B without the written confirmation described in "Half B — STOP gate". Do not merge half B yourself.
- Do not write `learner_state` from the script directly, and do not add a second write seam: `write_metrics` updates the four derived columns only.
- Do not compute `unassisted_next_session` from `zpd.step` (no `session_id` in that payload) — use `node_mastery_events.session_id`.
- Do not change the `sessions.close_phase` CHECK; `posttest` is a `zpd.step.phase` value only. Do not add event types; do not touch `EVENT_TAXONOMY`.
- Do not let the post-test read RAG, the learner brief, or run `loop_tutor`; the grader is the only agent it calls. Grader failure is a 503 with no evidence, never a retry with a different prompt (ADR 0024).
- Do not let the student PATCH `loop_arm`. Do not pick an experiment: leave `loop_arm` NULL.
- All Supabase access through `db/connection.py::table()`/`rpc()`/`page_all`; no `httpx`, no `supabase` import. Migrations: UTC-timestamp prefix, `_learning_` infix, append-only, never edited after creation.
- No numeric literal outside `learning/params.py` (the KPI endpoint imports the bands; the script imports the windows; the TS mirror is pinned by test). No `lru_cache` in this package.
- Do not skip, xfail, or delete a pre-existing test in half A. In half B, delete a test only when the code it tests is deleted in the same commit, and name it in the message. Never hand-edit eval cassettes or baselines; re-record.
- Do not encrypt or filter on `prompt`/`reference_answer`; the post-test looks items up by `(node_id, question_hash)` only.
- Logscan `ALLOWLIST` in `backend/e2e_oracles/logscan.py` stays `()`. Serialize all stack use under the `flock` lock, one invocation per up→test→down cycle.
- End every commit with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`; end each PR body with the Claude Code attribution line.

## If you get stuck

1. Re-read §Spec and the spec file's §10/§11 before guessing; for a KPI definition, the ZPD report LOG block is the tie-breaker.
2. Three failed iterations on one task → append a `BLOCKED` row to `LEDGER.md` (hypothesis, commands run, outputs), commit what is green, open the PR as draft, stop.
3. Never widen scope to unblock. Never disable a test to unblock. In half B, if an `inv_21` hit is in code you cannot safely change (e.g. `db/archive/`), change it anyway — the invariant is the contract — and say so in the hand-off.
4. Ambiguity → choose the option closest to the spec, mark it `†` in the hand-off, continue.
