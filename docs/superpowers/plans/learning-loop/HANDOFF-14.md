Half A only — half B (cutover) pending the series owner's confirmation.

# HANDOFF-14 — eval-ladder-cutover (half A)

Written by the sessions that executed half A of `PKG-14-eval-ladder-cutover.md`: Tasks A1–A8, three owner rounds, and the review fix round of 2026-09-29. A9 (the PR) was skipped under the session overrides. Read by half B and by every later session. Keep every heading, even if the answer is "none".

## Status

- **A1–A6 and A8: done.** The review fix round (three reviews of `aaa9085e..2fc29c66`) is applied too.
- **A7: blocked on the loop_tutor re-record.**
  - The re-record is three recordings per slot. It waits for the `gemini-2.5-pro` daily request quota (`generate_requests_per_model_per_day`, limit 1000), which ran out in run 1 of the owner-round-2 re-record.
  - Before the quota ran out, `loop_tutor_lite` and `loop_tutor` passed every served gate in run 1, the H1 claim case included.
  - The resume point is `wip/pkg14a-sycophancy-h1-fixture` @ `8f2f96b0`.
- **This branch keeps the PKG-07 loop_tutor dataset, cassettes, baselines and `LOOP_ROUTABLE_TIERS = {"standard", "deep"}`.** No live model call was made in the review fix round.
- **Merge plan.** Half A merges into `feat/learning-loop` **together with half B, after half B's Task B6 two-lane E2E gate** (default lane and kill-switch lane, fresh DB). No E2E ran in half A (session override), so the B6 cycle is the E2E gate that CONTINUE §4.0 override 9 requires for this package.
- Branch `feat/learning-loop-14a-eval-ladder` (worktree `~/Projects/sapling-wt-14`), cut from `468ad80c`, fast-forwarded to `aaa9085e` (PKG-10 and PKG-13 merged and verified).

## What changed

- **Nightly ZPD metrics** (`backend/scripts/derive_zpd_metrics.py`). It recomputes `htc_k`, `unassisted_next`, `assist_gap` and `in_zone` from each node's evidence journal: opportunities only, filtered before the window limit, in the A36 apply order. It writes only through `learner_state.write_metrics`.
  - Every run prints one read-only `REPORT <json>` line: cost per band, cost per session (per user-day only for rows with no session key), the check_items total, the tier and `grader_backend` mix, cap hits, and per-course check-item coverage.
  - Usage rows join events on **(user_id, request_id)**, never on the request id alone (X-Request-ID is client-set).
- **Admin KPIs** (`GET /api/admin/analytics/learning-loop`): in-band share, the `htc_k` trend, next-session unassisted success, `leak_count` plus the zero-leak gate (served leaks on item turns only), ceiling compliance, and `teach_reveals` (informational).
- **Perceived-difficulty rating.**
  - The check-answer handler counts `loop_state.checks_since_rating` once per flushed grade; at `ZPD_RATING_EVERY_N_CHECKS` the feedback turn carries `ask_rating: true`, and `LoopLearn` shows the `loop-rating` prompt.
  - `POST /rating` is rate-limited. It accepts a rating only on an open session whose counter reached the cadence (else 409), emits `zpd.rating`, and resets the counter.
- **Tool-removed post-test** (`/posttest/start`, `/posttest/answer`).
  - **What it serves.** Each concept whose newest evidence is at least `POSTTEST_MIN_AGE_DAYS` old gets its reserve item (A23), never a seen or revealed one.
  - **It commits when opened** (A87). The pose is recorded in `posttest_poses`. A repeat start returns the same item, never a fresh one. Both routes are rate-limited.
  - **Grading.** The answer grades the open pose only, under a claim taken by one conditional UPDATE, so it is graded once in any number of processes. It grades through `grade_answer` at H0 with no session. If the item was revealed or seen since it was posed, the grade gets no unassisted credit.
  - **`zpd.step`** carries `phase: "posttest"`, and its `p_known_after` is always a real value.
- **Within-student arms** (plumbing). `user_settings.loop_arm` plus `learning/arms.py::variant_for`; the genuine-attempt gate reads the concept's variant; `zpd.step` carries `variant`; arm sessions are never downgraded. **First experiment (owner): the variant-B independent-time gate**, started by the owner setting `loop_arm` by SQL.
- **`zpd.step` carries the session id** (A82).
- **Served teach turns: unchanged text, stated items marked revealed** (A86, replacing A84's withholding).
  - Every item of the student's course that a served teach turn states joins `loop_state["revealed"]`. So it is never selected as a check or a post-test item, and a posed one grades with no unassisted credit.
  - The event is `zpd.teach_reveal`, not `zpd.leak`.
  - Fail closed: when the items cannot be read, a marker makes every grade in that course assisted until the marker is resolved.
- **A reasoned wrong claim counts as a genuine attempt for that teach turn's ceiling** (A85): one rung up, capped per band, with no evidence change. A failed or paused turn refreshes the time anchor.
- **ADR 0030** (the cutover ADR) and **tooling for min-of-3 eval floors** (`SAPLING_EVAL_RUNS_LOG` plus `tests/evals/floors.py`).
- **Retired:** A81 (the code-served teach H0/H1 question; reverted `afb857ae`, spec A83) and A84 (withholding; reverted `729b8a55`, superseded by A86).

## Symbols added

Migrations (both new, UTC-prefixed, `_learning_` infix):

- `20260929175715_learning_loop_arm.sql`: `user_settings.loop_arm text`.
- `20260930024005_learning_posttest_poses.sql`: `posttest_poses(user_id, node_id)` PK, with `course_id`, `question_hash`, `posed_at`, `answered_at`, `claim` and `claimed_at`. RLS is on and the table is backend-only.

`backend/learning/`:

- `params.py`, the PKG-14 block: `HTC_K_WINDOW`, `ZPD_IN_ZONE_MIN_GAP`, `ZPD_IN_ZONE_MIN_ASSISTED`, `ZPD_IN_ZONE_MAX_UNASSISTED`, `KPI_TREND_WEEKS`, `GATE_LEAKS_MAX`, `GATE_CEILING_COMPLIANCE_MIN`, `POSTTEST_MIN_AGE_DAYS`, `POSTTEST_MAX_ITEMS`, `GATE_INDEPENDENT_MIN_S_VARIANT_B`, `TEACH_ATTEMPT_CEILING_RAISE`, `LOOP_PENDING_REVEALS_MAX`.
- `arms.py` (new, pure, in `PURE_MODULES`): `Variant`, `variant_for(user_id, node_id, arm)`.
- `policy.py` (PKG-06 reopens):
  - `independent_gate(band, variant)`, `independent_min_s(band, variant)`;
  - `CeilingReason.POSTTEST`, `CeilingReason.TEACH_ATTEMPT`;
  - `TEACH_ATTEMPT_CEILING_CAP`;
  - `ceiling_with_reason(..., *, teach_attempt=False)`.
- `gates.py` (PKG-06 reopens): `is_genuine_attempt(..., variant="A")`, `teach_attempt(message, independent_seconds, band, *, time_scale, variant)`, `teach_turn_ceiling(learner, message, independent_seconds, ...)`.
- `zpd_events.py` (PKG-06 reopens): `emit_zpd_step(..., variant=None, session_id=None)`, `emit_zpd_teach_reveal(user_id, request_id, question_hashes, unscanned)`.
- `learner_state.py`: `write_metrics`, `opportunity_states`, `states_last_evidence_before`, `_LearnerStateRead`.
- `loop_state_store.py` (PKG-06 module): `unscanned_reveals(user_id) -> list[(session_id, marker)]`.
- `review.py` (PKG-12 reopen): `grade_review(..., max_rung=0)`.

`backend/services/`:

- `check_item_service.items_for_course(course_id)` (a PKG-04 reader, paged).
- `events_service.EVENT_TAXONOMY` gains `"zpd.teach_reveal"`.

`backend/scripts/derive_zpd_metrics.py`: `compute`, `_opportunities`, `report(usage, steps, caps, *, sessions_by_request)`, `sessions_by_request(events) -> {(user_id, request_id): session_id}`, `main`, `SERIES_SLOTS`, `_now`.

`backend/routes/admin_analytics.py`: `GET /learning-loop` → `LearningLoopKpis`, which adds `teach_reveals`; plus `_rung_int`, `_phase_band`, `_in_band_share`, `_htc_k_trend`, `_next_session_rate` and `_ceiling_compliance`.

`backend/routes/learn_loop.py`:

- **Arms:** `_loop_arm`, `_arm_for`.
- **Rating:** `POST /rating` (rate-limited; `_NO_RATING_ASKED`).
- **Post-test:**
  - routes: `POST /posttest/start` (rate-limited) and `POST /posttest/answer` (rate-limited);
  - `STEP_PHASES`, `posttest_item`;
  - pose store: `_read_poses`, `_record_poses`, `_claim_pose`, `_settle_pose`;
  - reads: `_CourseNodesRead`, `_course_nodes` (paged);
  - grading and step: `_posttest_floor`, `_emit_posttest_step`.
- **Teach attempt (A85):** `_LoopTurn._teach_attempt`, and `loop_state.served_at` (written by every served turn); `_LoopTurn.touch_served_at` with the bounded `_FAILED_TURN_ANCHORS`.
- **Teach reveal (A86):**
  - scanning: `teach_reveals`, `_scan_teach`;
  - marking: `_mark_revealed`, `_resolve_reveal_markers`, `_reveal_floor`, `ANY_COURSE`;
  - opener reveals: `_PENDING_REVEALS` (bounded), `_stash_pending_reveal`, `_consume_loop_pending`;
  - `loop_state["reveal_unscanned"]` markers `{id, course_id, at, rung}`;
  - `_LoopTurn._teach_scanned`, `_scan_served_teach`, `_emit_teach_reveal`.
- **Rating counter:** `_Submission.ask_rating`.

`backend/models/__init__.py`: `LoopRatingBody`, `PosttestStartBody`, `PosttestAnswerBody`.

`backend/tests/evals/`: `_replay.RUNS_LOG_ENV`, `_log_run`, and `floors.py`.

Frontend:

- `api.ts`: `LoopTurnResult.ask_rating?`, `LoopRating`, `submitLoopRating(sessionId, rating)`.
- `LoopLearn.tsx`: the `RatingPrompt`, with testids `loop-rating` and `loop-rating-{too_easy,appropriate,too_hard}` (in `docs/frontend-testids.md`).

Tests (counts at the end of the review fix round):

| module | tests |
|---|---|
| `test_learning_zpd_metrics_script.py` | 34 |
| `test_admin_learning_loop_kpis.py` | 21 |
| `test_learn_loop_rating.py` | 22 |
| `test_learning_posttest.py` | 37 |
| `test_learning_arms.py` | 20 |
| `test_eval_floors.py` | 6 |
| `test_learning_step_session.py` | 3 |
| `test_learning_teach_attempt.py` | 22 |
| `test_learning_teach_reveal.py` | 24 |

- Invariants: `inv_20`; `inv_01`'s `write_metrics` caller block; `inv_26`'s `posttest_answer`; `arms.py` in `PURE_MODULES`.
- Pins updated: `test_learn_loop_routes.py` (the route lists) and `test_event_capture_seams.py` (the taxonomy).
- Frontend: `LoopLearn.test.tsx` +4, `api.loop.test.ts` +1.
- The A81 and A84 tests went with their reverts.

Side branch, not for merge: `wip/pkg14a-sycophancy-h1-fixture` @ `8f2f96b0`. It holds the eval fixture, the eval's A85/A86 parity, the tests that go with them, and run 1's (pre-A86) cassettes.

## Constants chosen

Every PKG-14 † constant (also in LEDGER Deviations):

- `HTC_K_WINDOW = 5` †, `ZPD_IN_ZONE_MIN_GAP = 0.25` †, `ZPD_IN_ZONE_MIN_ASSISTED = 0.6` †, `ZPD_IN_ZONE_MAX_UNASSISTED = 0.85` † — the ZPD report LOG block. "Assisted" means the correct share among the assisted opportunities in the window.
- `KPI_TREND_WEEKS = 4` †.
- `POSTTEST_MIN_AGE_DAYS = 2` †, `POSTTEST_MAX_ITEMS = 10` †.
- `GATE_INDEPENDENT_MIN_S_VARIANT_B = 90` † — the first `loop_arm` experiment (owner).
- `TEACH_ATTEMPT_CEILING_RAISE = 1` † (A85). The cap per band is `policy.TEACH_ATTEMPT_CEILING_CAP` = profic H3, develop H6, novice H5 (Rung members).
- `LOOP_PENDING_REVEALS_MAX = 10_000` † — bounds both the openers' pending reveals (A86) and the in-memory failed-turn anchors (A85).

Not †: `GATE_LEAKS_MAX = 0` and `GATE_CEILING_COMPLIANCE_MIN = 0.95` (spec §10).

`CHECK_ITEM_FINAL_ANSWER_MAX_TOKENS` stays 20 † (owner decision; A80):

- Stored draft `final_answer` lengths run 1–16 tokens.
- Recorded 3× per cap:

  | cap | DraftValid | McOptionsValid |
  |---|---|---|
  | 16 | 0.963 / 0.852 / 0.815 | 1.000 / 1.000 / 0.944 |
  | 20 | 0.778 / 0.870 / 0.981 | 1.000 ×3 |

## Deviations from spec

- **`write_metrics` is a second learner_state writer.** Spec §5 says only `apply_graph_update` writes `learner_state` → `write_metrics` UPDATEs the four derived columns (†, A79 (a)).
- **`inv_20` and its reads.** `inv_20` uses `(?<!sys\.path)\.insert\(`, and the script reads states through `learner_state.opportunity_states` → the prompt's own preamble and snippet contradicted `inv_20`. The journal is read in the A36 order.
- **`variant_for` module.** `policy.variant_for` → `learning/arms.variant_for` → invariant 4.
- **`loop_arm` and the settings API.** It is in no settings API field → CONTINUE §4.4 (A31's reason).
- **Variant threshold reader.** The threshold's one reader is `gates.is_genuine_attempt` → `variant=` is a PKG-06 reopen.
- **The post-test commits when opened** (A87, owner). A new table plus a database claim replace the in-process lock and the grade-time eligibility check.
- **Items for the post-test** come from `items_for_concepts`. The fallback after the reserve is †: the free item nearest `CHECK_ITEM_DIFFICULTIES[1]`, then the lowest-hash servable item.
- **The route pin** in `tests/test_learn_loop_routes.py` learns `/posttest/answer` as a model route. `/posttest/start` and `/rating` are listed as rate-limited no-model routes.
- **The teach anchor for A85** is `loop_state.served_at`. A failed or paused turn's anchor is kept in memory, because a failed turn writes nothing (ADR 0024; the PKG-07 "persists nothing" pins are unchanged).
- **A86's fail-closed rule** (owner: "pick the simplest correct rule"):
  - an unscanned marker makes every grade in its course at least `RUNG_ASSISTED_MIN`;
  - it lasts until `_resolve_reveal_markers` rescans the session's later tutor messages against the course's items;
  - resolution runs before every grading floor;
  - a failed marker read means every course is unresolved.
- **The opener has no session row**, so its reveals ride a bounded in-memory map and are written when the session materialises (`_consume_loop_pending`). They carry the same durability as the lazy session itself.
- **A7 recording scope.** "Record ONLY the new cases, once per slot" → the whole dataset, three times per slot (A40 06(s)).
- **Fixture swap.** The second sycophancy fixture replaces `teach_develop_derivatives` (same phase, band and ceiling as the first), keeping the cap of 8.

## Known gaps

- **BLOCKED — the A7 re-record** (`gemini-2.5-pro` daily quota).
  - **Resume:**
    1. After the quota resets, check out onto this branch the wip branch's `backend/tests/evals/loop_tutor.py` and `backend/tests/test_learning_eval_ladder.py`.
    2. `git rm` the `teach_develop_derivatives` cassettes (3 slots plus 3 rung-judge files).
    3. Record 3× per slot with `SAPLING_EVAL_RUNS_LOG`.
    4. Run `tests/evals/floors.py --runs 3 --datasets loop_tutor_lite,loop_tutor,loop_tutor_deep --routing loop_tutor_routing`.
    5. Set `LOOP_ROUTABLE_TIERS` to exactly the tiers whose three runs all pass.
    6. STOP if standard or deep fail.
  - **Cost:** about $0.95.
  - **Until then**, this branch's eval scores the PKG-07 dataset. Teach turns are served unchanged (A86), so eval and production agree on teach text, but A85's raised ceiling on the claim case is not scored yet.
  - **Half B's launch gate** (§11.1 item 4) is open until the re-record passes.
- **A85's limitation (owner-accepted).** Any non-empty student message with no non-attempt phrase qualifies once the independent-time gate passes. So a teach message that is not a reasoned claim can raise that one turn's ceiling by one rung. It is bounded: one rung, one turn, capped per band, never in exam mode, and no evidence or state change.
- **The earnest-revise gate** (spec §10, ≤ 5 %) is not measured. Proposed for half B, not built: a per-step `earnest_blocked` counter.
  - It is incremented when `/hint` denies at the ceiling (a reason other than `no_genuine_attempt`) while the step has a genuine attempt.
  - It would be carried as a bool on the feedback `zpd.step`, and the KPI rate would be gated at ≤ 5 %.
- **Per-session cost** covers the requests an event names (`zpd.step`, `learn.session_closed`, `chat.message_sent`). The opener, the probe and review grades, and hint actions stay per user-day until `llm_usage.session_id` lands in half B.
- **In-memory state** (bounded): the openers' pending reveals and the failed-turn anchors. The backend runs one process (`backend/Dockerfile`), and B9 lists the multi-process precondition. The post-test claim is in the database now.
- **The rating prompt** has no E2E coverage (it needs 30 graded checks).
- **The post-test** has no frontend.
- **Floors.** Only `loop_tutor` was re-recorded live. The other datasets' floors are still single-recording, because half A re-set none of them.
- **No E2E** ran in half A. B6 is the gate.

## Verify commands

```
cd backend && venv/bin/python -m pytest tests/test_learning_zpd_metrics_script.py tests/test_admin_learning_loop_kpis.py tests/test_learn_loop_rating.py tests/test_learning_posttest.py tests/test_learning_arms.py tests/test_learning_step_session.py tests/test_learning_teach_attempt.py tests/test_learning_teach_reveal.py tests/test_eval_floors.py -q → 189 passed
cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_20 or inv_01" → 2 passed
cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_26 or inv_28" → 3 passed
ls backend/db/migrations/*_learning_loop_arm.sql backend/db/migrations/*_learning_posttest_poses.sql → 2 files
ls docs/decisions/*learning-loop-cutover*.md                                                      → 1 file (0030)
cd backend && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/run_all.py                    → PASS for every dataset (16)
grep -c '"check_items"\|"grader"\|"decisions"\|"loop_tutor"' backend/tests/evals/run_all.py      → 4
grep -n '"/learning-loop"' backend/routes/admin_analytics.py                                     → 1 hit
grep -c '"zpd.teach_reveal"' backend/services/events_service.py                                   → 1
```

Observed at the end of the review fix round (no stack), with the hermetic suite under the override command and neither `SAPLING_MODEL_MODE` nor `SAPLING_FUNCTION_HANDLERS` set:

- Backend: **8323 passed, 140 skipped, 0 failed** (N₀ 8133/140); invariants 34 passed, 1 skipped; `ruff check .` clean; `run_all` replay 16/16 PASS.
- Frontend: `npx tsc --noEmit` clean; `npx vitest run` 1260 passed, 2 skipped.

Live spend, metered at `services/llm_pricing` list prices:

| round | spend |
|---|---|
| Half A | $1.00 |
| Owner round 1 (A81 re-record) | $0.955 |
| Owner round 2 (A85 re-record, run 1 until the quota) | $0.314 |
| Review fix round | $0 |
| **Total** | **≈ $2.27** |

## Open questions for the series owner

Owner decisions applied (Andres, 2026-09-29):

- **Round 1:** A80 kept at 20; the first `loop_arm` experiment is the variant-B gate; A82 per-session cost.
- **Round 2:** A81 retired (A83); A85, with the 120 s case time and the fast-claim proviso test.
- **Review fix round:** A84 replaced by A86 (mark revealed); A87 (post-test commits when opened); A85 kept, with its limitation recorded; `llm_usage.session_id` in half B.

Still open:

1. **The A7 re-record** once the quota resets (resume steps above).
2. **A45** (the grader cap is blind without events) stays flagged for the half B STOP gate.

## For half B

- **ADR 0030:** append `learning_loop_beta retired: <date> (PKG-14b)` and `Cutover executed: <date>, PR #<n>`.
- **Merge.** Half A merges together with half B, after B6's two-lane E2E. B6 must replay both new migrations (`loop_arm`, `posttest_poses`) from an empty DB. Check that `posttest_poses` is reachable through PostgREST for the backend, and that the conditional-UPDATE claim works against real PostgREST: `or=(claim.is.null,claimed_at.lt.…)` with the `answered_at=is.null` filter.
- **`llm_usage.session_id` (owner decision: build it in half B):**
  - a migration adding `llm_usage.session_id text`;
  - `agents/usage.py::record_agent_usage` writing the run's `deps.session_id`;
  - `scripts/derive_zpd_metrics.py` preferring the row's own `session_id` over the event mapping, keeping per user-day only for older rows without it.
- **The launch gate is not met** until the A7 re-record passes (§11.1 item 4).
- **The B9 runbook** (owner steps, listed, never run):
  - Production `PLATFORM_DAILY_BUDGET_USD=5` (A39 (e)). Before that, set a deliberately low staging value (e.g. `0.01`), drive one tutor turn, confirm the `ai.budget_capped{scope: platform}` alert arrives, then restore the staging value.
  - **Precondition before more than one backend process or replica:** the in-memory maps (`_PENDING_REVEALS`, `_FAILED_TURN_ANCHORS`) must move to the database. The post-test claim is already in the database.
- **Kill-switch marking.** The new test modules patch the gate themselves or never reach it. Confirm with the B5 grep.
- **`loop_arm`** stays out of the settings API (CONTINUE §4.4).
- **Frontend.** The rating prompt lives in the loop tree only.
- **E2E notes for B6:**
  - A86 never changes served text; only `loop_state["revealed"]` grows.
  - The seeded items' final answer `E2E_LOOP_FINAL_ANSWER` appears only in `E2E_LOOP_REFERENCE`, so a function-mode teach turn marks nothing.
  - A85 never raises the seeded novice users (H5 is their cap).

## Post-hoc changes

(Appended by later packages that modified this package's code. Format: `PKG-MM <date>: <what> — commit <sha>`.)
