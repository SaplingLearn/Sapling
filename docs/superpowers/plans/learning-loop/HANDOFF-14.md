Half A and half B (the cutover) are both BUILT. Half B was built before the §11.1 launch gate is met, on the owner's instruction (2026-09-29): building, not launching. Neither half is merged; they merge into `feat/learning-loop` together after the B6 two-lane E2E gate. See `## Half B` and `## Launch runbook` below.

# HANDOFF-14 — eval-ladder-cutover (half A)

Written by the sessions that executed half A of `PKG-14-eval-ladder-cutover.md`: Tasks A1–A8, three owner rounds, the review fix round of 2026-09-29, and the re-review fix round of 2026-09-30. A9 (the PR) was skipped under the session overrides. Read by half B and by every later session. Keep every heading, even if the answer is "none".

## Status

- **A1–A6 and A8: done.** The review fix round (three reviews of `aaa9085e..2fc29c66`) and the re-review fix round (on `585a6740`: OWNER 1/2, M1, M2, m1–m10) are applied too.
- **A7: blocked on the loop_tutor re-record.**
  - The re-record is three recordings per slot. It waits for the `gemini-2.5-pro` daily request quota (`generate_requests_per_model_per_day`, limit 1000), which ran out in run 1 of the owner-round-2 re-record.
  - Before the quota ran out, `loop_tutor_lite` and `loop_tutor` passed every served gate in run 1, the H1 claim case included.
  - The resume point is `wip/pkg14a-sycophancy-h1-fixture` @ `8f2f96b0`.
- **This branch keeps the PKG-07 loop_tutor dataset, cassettes, baselines and `LOOP_ROUTABLE_TIERS = {"standard", "deep"}`.** No live model call was made in either fix round.
- **Merge plan.** Half A merges into `feat/learning-loop` **together with half B, after half B's Task B6 two-lane E2E gate** (default lane and kill-switch lane, fresh DB). No E2E ran in half A (session override), so the B6 cycle is the E2E gate that CONTINUE §4.0 override 9 requires for this package.
- Branch `feat/learning-loop-14a-eval-ladder` (worktree `~/Projects/sapling-wt-14`), cut from `468ad80c`, fast-forwarded to `aaa9085e` (PKG-10 and PKG-13 merged and verified).

## What changed

- **Nightly ZPD metrics** (`backend/scripts/derive_zpd_metrics.py`). It recomputes `htc_k`, `unassisted_next`, `assist_gap` and `in_zone` from each node's evidence journal: opportunities only, filtered before the window limit, in the A36 apply order. It writes only through `learner_state.write_metrics`.
  - Every run prints one read-only `REPORT <json>` line: cost per band, cost per session (per user-day only for rows with no session key), the check_items total, the tier and `grader_backend` mix, cap hits, and per-course check-item coverage.
  - Usage rows join events on **(user_id, request_id)**, never on the request id alone (X-Request-ID is client-set).
- **Admin KPIs** (`GET /api/admin/analytics/learning-loop`): in-band share, the `htc_k` trend, next-session unassisted success, `caught_leaks` (`zpd.leak`: caught and redacted, never served), `served_reveals` and `unscanned_turns` (`zpd.reveal`) with the zero-leak gate on `served_reveals` (A90), ceiling compliance, and `teach_reveals` (informational).
- **Perceived-difficulty rating.**
  - The check-answer handler counts `loop_state.checks_since_rating` once per flushed grade; at `ZPD_RATING_EVERY_N_CHECKS` the feedback turn carries `ask_rating: true`, and `LoopLearn` shows the `loop-rating` prompt.
  - `POST /rating` is rate-limited. It accepts a rating only on an open session whose counter reached the cadence (else 409), emits `zpd.rating`, and resets the counter.
- **Tool-removed post-test** (`/posttest/start`, `/posttest/answer`).
  - **What it serves.** Each concept whose newest evidence is at least `POSTTEST_MIN_AGE_DAYS` old gets its reserve item (A23), never a seen or revealed one.
  - **It commits when opened** (A87). The pose is recorded in `posttest_poses`. A repeat start returns the same item, never a fresh one. Both routes are rate-limited.
  - **A pose expires** (A89, owner): after `POSTTEST_POSE_TTL_HOURS` it is void — it may be posed again, and a late answer is a 409.
  - **Grading.** The answer grades the open pose only, under a claim taken by one conditional UPDATE, so it is graded once in any number of processes. It grades through `grade_answer` at H0 with no session. If the item was revealed or seen since it was posed, the grade gets no unassisted credit.
  - **Before the flush** the claim is re-validated and the pose closed in one conditional UPDATE (`_answer_pose`): a taken-over claim writes nothing, and a failed flush never reopens the pose. A revealed item, or a node with any evidence after `posed_at`, grades with no unassisted credit (A89).
  - **`zpd.step`** carries `phase: "posttest"`, and its `p_known_after` is a measured value: the flush's result or the stored state. A node with no row emits no step (m8).
- **Within-student arms** (plumbing). `user_settings.loop_arm` plus `learning/arms.py::variant_for`; the genuine-attempt gate reads the concept's variant; `zpd.step` carries `variant`; arm sessions are never downgraded. **First experiment (owner): the variant-B independent-time gate**, started by the owner setting `loop_arm` by SQL.
- **`zpd.step` carries the session id** (A82).
- **Served tutor turns: unchanged text; what they reveal of OPEN, POSED items is recorded at serve time** (A86 "never withheld", A88 scope and store).
  - **Scope.** Only the student's open posed items (`open_posed_items`): the active check item of an open loop session, an open review item, an open post-test pose. Every served model turn is scanned; an item turn skips its own active item. The course-wide scan is gone.
  - **Store.** Stated items go to `learning_reveals` before the turn's state write (the opener too), and `revealed_hashes` reads them. Nothing is held in memory, so no path can lose a reveal. A failed write falls back to `loop_state["revealed"]` in the same compare-and-set write.
  - **Streams.** A stream that ends without `done` records what it relayed, in `_stream_turn`'s `finally`, synchronously.
  - **Fail closed.** A revealed item grades with no unassisted credit. Unreadable open items leave an `unscanned` marker; every item posed at or before it grades as assisted.
  - The event is `zpd.reveal`, not `zpd.leak`.
- **A reasoned wrong claim counts as a genuine attempt for that teach turn's ceiling** (A85): one rung up, capped per band, with no evidence change. A failed, paused or disconnected turn refreshes the time anchor.
- **The A88 precondition, verified 2026-09-30** (owner 1 asked for it first). The loop tutor's teach and item-turn model context never includes an unposed item's prompt or answer:
  - the prompt carries the ACTIVE posed item's prompt on hint and feedback turns only;
  - the rest is the catalog, RAG course passages, the active item's source chunks and the graph block;
  - the tools are `search_course_materials` and `read_graph_neighborhood`;
  - the learner brief names concepts only;
  - the confront line is the wrong-reason text of an item the student already answered;
  - the one code-served exception, an H4 sibling payload, is marked revealed when it is served.
- **ADR 0030** (the cutover ADR) and **tooling for min-of-3 eval floors** (`SAPLING_EVAL_RUNS_LOG` plus `tests/evals/floors.py`).
- **Retired:** A81 (the code-served teach H0/H1 question; reverted `afb857ae`, spec A83) and A84 (withholding; reverted `729b8a55`, superseded by A86).

## Symbols added

Migrations (both new, UTC-prefixed, `_learning_` infix):

- `20260929175715_learning_loop_arm.sql`: `user_settings.loop_arm text`.
- `20260930024005_learning_posttest_poses.sql`: `posttest_poses(user_id, node_id)` PK, with `course_id`, `question_hash`, `posed_at`, `answered_at`, `claim` and `claimed_at`. RLS is on and the table is backend-only.
- `20260930031644_learning_reveals.sql`: `learning_reveals(id)` with `user_id`, `kind` (`reveal` | `unscanned`), `question_hash` (set iff `reveal`), `session_id`, `source`, `at`; index `(user_id, kind, at)`. RLS is on and the table is backend-only.

`backend/learning/`:

- `params.py`, the PKG-14 block: `HTC_K_WINDOW`, `ZPD_IN_ZONE_MIN_GAP`, `ZPD_IN_ZONE_MIN_ASSISTED`, `ZPD_IN_ZONE_MAX_UNASSISTED`, `KPI_TREND_WEEKS`, `GATE_LEAKS_MAX`, `GATE_CEILING_COMPLIANCE_MIN`, `POSTTEST_MIN_AGE_DAYS`, `POSTTEST_MAX_ITEMS`, `POSTTEST_POSE_TTL_HOURS`, `GATE_INDEPENDENT_MIN_S_VARIANT_B`, `TEACH_ATTEMPT_CEILING_RAISE`, `LOOP_FAILED_ANCHORS_MAX`.
- `arms.py` (new, pure, in `PURE_MODULES`): `Variant`, `variant_for(user_id, node_id, arm)`.
- `policy.py` (PKG-06 reopens):
  - `independent_gate(band, variant)`, `independent_min_s(band, variant)`;
  - `CeilingReason.POSTTEST`, `CeilingReason.TEACH_ATTEMPT`;
  - `TEACH_ATTEMPT_CEILING_CAP`;
  - `ceiling_with_reason(..., *, teach_attempt=False)`.
- `gates.py` (PKG-06 reopens): `is_genuine_attempt(..., variant="A")`, `teach_attempt(message, independent_seconds, band, *, time_scale, variant)`, `teach_turn_ceiling(learner, message, independent_seconds, ...)`.
- `zpd_events.py` (PKG-06 reopens): `emit_zpd_step(..., variant=None, session_id=None)`, `emit_zpd_reveal(user_id, request_id, session_id, question_hashes, unscanned, phase)`.
- `learner_state.py`: `write_metrics`, `opportunity_states`, `states_last_evidence_before`, `_LearnerStateRead`.
- `loop_state_store.py` (PKG-06 module): `revealed_hashes` also reads `learning_reveals` (kind `reveal`). The module still never inserts (the PKG-06 pin).
- `reveal_store.py` (new; not a PKG-06 module, so the inertness scan is unchanged): `record_reveals(user_id, hashes, *, session_id, source)`, `record_unscanned(user_id, *, session_id, source, at)`, `unscanned_since(user_id, posed_at) -> bool`, `unscanned_reveals(user_id)` (the loop_state fallback markers).
- `review.py` (PKG-12 reopen): `grade_review(..., max_rung=0)`.

`backend/services/`:

- `check_item_service.items_by_hash(hashes)` (a PKG-04 reader, batched `in.(...)`; `items_for_course` is removed).
- `events_service.EVENT_TAXONOMY` gains `"zpd.reveal"`.

`backend/scripts/derive_zpd_metrics.py`: `compute`, `_opportunities`, `report(usage, steps, caps, *, sessions_by_request)`, `sessions_by_request(events) -> {(user_id, request_id): session_id}`, `main`, `SERIES_SLOTS`, `_now`.

`backend/routes/admin_analytics.py`: `GET /learning-loop` → `LearningLoopKpis`, with `caught_leaks`, `served_reveals` and `unscanned_turns` (`leak_count` is gone); plus `_rung_int`, `_phase_band`, `_in_band_share`, `_htc_k_trend`, `_next_session_rate` and `_ceiling_compliance`.

`backend/routes/learn_loop.py`:

- **Arms:** `_loop_arm`, `_arm_for`.
- **Rating:** `POST /rating` (rate-limited; `_NO_RATING_ASKED`).
- **Post-test:**
  - routes: `POST /posttest/start` (rate-limited) and `POST /posttest/answer` (rate-limited);
  - `STEP_PHASES`, `posttest_item`;
  - pose store: `_read_poses`, `_pose_open` (the TTL), `_record_poses`, `_claim_pose` (returns the row), `_answer_pose`, `_release_pose`;
  - reads: `_CourseNodesRead`, `_course_nodes` (paged);
  - grading and step: `_posttest_floor(user_id, node_id, item, posed_at)`, `_emit_posttest_step`.
- **Teach attempt (A85):** `_LoopTurn._teach_attempt`, and `loop_state.served_at` (written by every served turn); `_LoopTurn.touch_served_at` with the bounded `_FAILED_TURN_ANCHORS`.
- **Served reveals (A88):**
  - scope and scan: `open_posed_items(user_id, *, now)`, `stated_items(text, items, *, rung, given)`, `_ts`;
  - store: `_persist_reveals`, `_mark_revealed` (the loop_state fallback: `revealed`, `reveal_unscanned` markers `{at, source}`);
  - floor: `_reveal_floor(user_id, item, posed_at=None)`, `_review_posed_at`;
  - turn: `_LoopTurn._scan_served`, `_record_served`, `_emit_reveal`, `record_relayed`; `_stream_turn`'s `finally`.
  - Removed: `teach_reveals`, `_scan_teach`, `_resolve_reveal_markers`, `ANY_COURSE`, `_PENDING_REVEALS`, `_stash_pending_reveal`, `_consume_loop_pending` (the handlers call `_consume_pending` again).
- **Rating counter:** `_Submission.ask_rating`.

`backend/models/__init__.py`: `LoopRatingBody`, `PosttestStartBody`, `PosttestAnswerBody`.

`backend/tests/evals/`: `_replay.RUNS_LOG_ENV`, `_log_run`, and `floors.py`.

Frontend:

- `api.ts`: `LoopTurnResult.ask_rating?`, `LoopRating`, `submitLoopRating(sessionId, rating)`.
- `LoopLearn.tsx`: the `RatingPrompt`, with testids `loop-rating` and `loop-rating-{too_easy,appropriate,too_hard}` (in `docs/frontend-testids.md`).

Tests (counts at the end of the re-review fix round):

| module | tests |
|---|---|
| `test_learning_zpd_metrics_script.py` | 34 |
| `test_admin_learning_loop_kpis.py` | 22 |
| `test_learn_loop_rating.py` | 22 |
| `test_learning_posttest.py` | 45 |
| `test_learning_arms.py` | 20 |
| `test_eval_floors.py` | 6 |
| `test_learning_step_session.py` | 3 |
| `test_learning_teach_attempt.py` | 22 |
| `test_learning_teach_reveal.py` | 38 |
| `integration/test_posttest_poses_db.py` | 9 |
| `integration/test_teach_reveal_db.py` | 6 |
| `integration/test_zpd_metrics_db.py` | 1 |

The three integration modules (marker `integration`) ran green against the local stack on 2026-09-30, 19 passed together with `test_migrations_ledger.py` and `test_session_close_db.py`.

- Invariants: `inv_20`; `inv_01`'s `write_metrics` caller block; `inv_26`'s `posttest_answer`; `arms.py` in `PURE_MODULES`.
- Pins updated: `test_learn_loop_routes.py` (the route lists; the `seams` fixture patches `open_posed_items` and the reveal store), `test_event_capture_seams.py` (the taxonomy) and `test_learning_loop_readers.py` (`revealed_hashes` reads `learning_reveals` too).
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
- `LOOP_FAILED_ANCHORS_MAX = 10_000` † — bounds the in-memory failed-turn anchors (A85). It was `LOOP_PENDING_REVEALS_MAX`; the pending reveals are gone (A88).
- `POSTTEST_POSE_TTL_HOURS = 24` † (owner, A89).

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
- **The post-test commits when opened** (A87, owner). A new table plus a database claim replace the in-process lock and the grade-time eligibility check. A79 (d) is marked superseded by A87 (m9).
- **A pose expires after `POSTTEST_POSE_TTL_HOURS = 24` †** (A89, owner). Evidence on the node after `posed_at` floors the grade at `RUNG_NO_CREDIT_MIN`; this replaces A87's "seen since" rule.
- **Items for the post-test** come from `items_for_concepts`. The fallback after the reserve is †: the free item nearest `CHECK_ITEM_DIFFICULTIES[1]`, then the lowest-hash servable item.
- **The route pin** in `tests/test_learn_loop_routes.py` learns `/posttest/answer` as a model route. `/posttest/start` and `/rating` are listed as rate-limited no-model routes.
- **The teach anchor for A85** is `loop_state.served_at`. A failed or paused turn's anchor is kept in memory, because a failed turn writes nothing (ADR 0024; the PKG-07 "persists nothing" pins are unchanged).
- **The A88 scope** (owner 1) replaces A86's course-wide scan: only open, posed items are scanned. The precondition that makes this safe is recorded above.
- **The A88 fail-closed rule** (replacing A86's resolution scan). An `unscanned` marker floors every item posed at or before it (`at ≥ posed_at`) at `RUNG_ASSISTED_MIN`. It never needs resolving, because it can only reach items that were already open when it was written. So m6 (paging the resolution read, ordering the marker after the message save, keeping it on failure, course-less sessions) has nothing left to apply to: there is no resolution, and a marker is per student, not per course.
- **The opener's reveals** are written to `learning_reveals` at serve time (M2). If that write fails, the opener is not served (a 5xx, no pending session), because there is no session row to fall back to.
- **The reveal store is a new module** (`learning/reveal_store.py`), because PKG-06's pin says `loop_state_store` never inserts. It imports nothing from PKG-06, so the inertness scan is unchanged.
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
  - **Until then**, this branch's eval scores the PKG-07 dataset. Served text is unchanged (A86, A88: recording reveals never changes what is served), so eval and production agree on teach text, but A85's raised ceiling on the claim case is not scored yet. The re-review round changed no eval-facing path, so the wip branch needs no change.
  - **Half B's launch gate** (§11.1 item 4) is open until the re-record passes.
- **A85's limitation (owner-accepted).** Any non-empty student message with no non-attempt phrase qualifies once the independent-time gate passes. So a teach message that is not a reasoned claim can raise that one turn's ceiling by one rung. It is bounded: one rung, one turn, capped per band, never in exam mode, and no evidence or state change.
- **The earnest-revise gate** (spec §10, ≤ 5 %) is not measured. Proposed for half B, not built: a per-step `earnest_blocked` counter.
  - It is incremented when `/hint` denies at the ceiling (a reason other than `no_genuine_attempt`) while the step has a genuine attempt.
  - It would be carried as a bool on the feedback `zpd.step`, and the KPI rate would be gated at ≤ 5 %.
- **Per-session cost** covers the requests an event names (`zpd.step`, `learn.session_closed`, `chat.message_sent`). The opener, the probe and review grades, and hint actions stay per user-day until `llm_usage.session_id` lands in half B.
- **In-memory state** (bounded): only the failed-turn anchors (A85). The reveals are in the database now. The backend runs one process (`backend/Dockerfile`), and B9 lists the multi-process precondition. The post-test claim is in the database now.
- **The rating prompt** has no E2E coverage (it needs 30 graded checks).
- **The post-test** has no frontend.
- **Floors.** Only `loop_tutor` was re-recorded live. The other datasets' floors are still single-recording, because half A re-set none of them.
- **No E2E** ran in half A. B6 is the gate.
- **A lost reveal when both stores are down.** If the `learning_reveals` write AND its loop_state fallback both fail, the reveal is logged at ERROR and lost; the grading reads fail at that moment too, so those grades are assisted, but once the database recovers the lost reveal is invisible. This affects a stream that already relayed text, or an item turn whose compare-and-set write then fails.

## Verify commands (half A — superseded by the half B block below)

```
cd backend && venv/bin/python -m pytest tests/test_learning_zpd_metrics_script.py tests/test_admin_learning_loop_kpis.py tests/test_learn_loop_rating.py tests/test_learning_posttest.py tests/test_learning_arms.py tests/test_learning_step_session.py tests/test_learning_teach_attempt.py tests/test_learning_teach_reveal.py tests/test_eval_floors.py -q → 189 passed
cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_20 or inv_01" → 2 passed
cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_26 or inv_28" → 3 passed
ls backend/db/migrations/*_learning_loop_arm.sql backend/db/migrations/*_learning_posttest_poses.sql backend/db/migrations/*_learning_reveals.sql → 3 files
ls docs/decisions/*learning-loop-cutover*.md                                                      → 1 file (0030)
cd backend && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/run_all.py                    → PASS for every dataset (16)
grep -c '"check_items"\|"grader"\|"decisions"\|"loop_tutor"' backend/tests/evals/run_all.py      → 4
grep -n '"/learning-loop"' backend/routes/admin_analytics.py                                     → 1 hit
grep -c '"zpd.reveal"' backend/services/events_service.py                                        → 1
(local stack up) cd backend && RUN_INTEGRATION=1 venv/bin/python -m pytest tests/integration/test_posttest_poses_db.py tests/integration/test_teach_reveal_db.py tests/integration/test_zpd_metrics_db.py -q → 16 passed
```

Observed at the end of the re-review fix round, with the hermetic suite under the override command and neither `SAPLING_MODEL_MODE` nor `SAPLING_FUNCTION_HANDLERS` set:

- Backend: **8346 passed, 156 skipped, 0 failed** (N₀ 8133/140; the 16 new skips are the integration modules, which skip without `RUN_INTEGRATION=1`); invariants 34 passed, 1 skipped; `ruff check .` clean; `run_all` replay 16/16 PASS.
- Integration (local stack, flock'd cycle, 2026-09-30): the three new modules plus `test_migrations_ledger.py` and `test_session_close_db.py`, **19 passed**.
- Frontend (unchanged this round): `npx tsc --noEmit` clean; `npx vitest run` 1260 passed, 2 skipped.

Live spend, metered at `services/llm_pricing` list prices:

| round | spend |
|---|---|
| Half A | $1.00 |
| Owner round 1 (A81 re-record) | $0.955 |
| Owner round 2 (A85 re-record, run 1 until the quota) | $0.314 |
| Review fix round | $0 |
| Re-review fix round | $0 |
| **Total** | **≈ $2.27** |

## Open questions for the series owner

Owner decisions applied (Andres, 2026-09-29):

- **Round 1:** A80 kept at 20; the first `loop_arm` experiment is the variant-B gate; A82 per-session cost.
- **Round 2:** A81 retired (A83); A85, with the 120 s case time and the fast-claim proviso test.
- **Review fix round:** A84 replaced by A86 (mark revealed); A87 (post-test commits when opened); A85 kept, with its limitation recorded; `llm_usage.session_id` in half B.
- **Re-review fix round:** A88 (scan open posed items only; the precondition verified); A89 (`POSTTEST_POSE_TTL_HOURS = 24`, evidence after posed_at is no credit).

Still open:

1. **The A7 re-record** once the quota resets (resume steps above).
2. **A45** (the grader cap is blind without events) stays flagged for the half B STOP gate.

## For half B

- **ADR 0030:** append `learning_loop_beta retired: <date> (PKG-14b)` and `Cutover executed: <date>, PR #<n>`.
- **Merge.** Half A merges together with half B, after B6's two-lane E2E. B6 must replay the three new migrations (`loop_arm`, `posttest_poses`, `learning_reveals`) from an empty DB. Check that `posttest_poses` is reachable through PostgREST for the backend, and that the conditional-UPDATE claim works against real PostgREST: `or=(claim.is.null,claimed_at.lt.…)` with the `answered_at=is.null` filter.
- **`llm_usage.session_id` (owner decision: build it in half B):**
  - a migration adding `llm_usage.session_id text`;
  - `agents/usage.py::record_agent_usage` writing the run's `deps.session_id`;
  - `scripts/derive_zpd_metrics.py` preferring the row's own `session_id` over the event mapping, keeping per user-day only for older rows without it.
- **The launch gate is not met** until the A7 re-record passes (§11.1 item 4).
- **The B9 runbook** (owner steps, listed, never run):
  - Production `PLATFORM_DAILY_BUDGET_USD=5` (A39 (e)). Before that, set a deliberately low staging value (e.g. `0.01`), drive one tutor turn, confirm the `ai.budget_capped{scope: platform}` alert arrives, then restore the staging value.
  - **Precondition before more than one backend process or replica:** `_FAILED_TURN_ANCHORS` (A85) must move to the database. The reveals and the post-test claim are already in the database.
- **Kill-switch marking.** The new test modules patch the gate themselves or never reach it. Confirm with the B5 grep.
- **`loop_arm`** stays out of the settings API (CONTINUE §4.4).
- **Frontend.** The rating prompt lives in the loop tree only.
- **E2E notes for B6:**
  - A88 never changes served text; only `learning_reveals` grows.
  - The seeded items' final answer `E2E_LOOP_FINAL_ANSWER` appears only in `E2E_LOOP_REFERENCE`, so a function-mode turn records no reveal.
  - A85 never raises the seeded novice users (H5 is their cap).

## Post-hoc changes

(Appended by later packages that modified this package's code. Format: `PKG-MM <date>: <what> — commit <sha>`.)

## Half B

Written by the session that built half B of `PKG-14-eval-ladder-cutover.md` (Tasks B1–B5b, B7; B9 as the runbook only), 2026-09-30. Branch `feat/learning-loop-14b-cutover` (worktree `~/Projects/sapling-wt-14b`), cut from half A's tip `585a6740` and pushed after every commit.

### Status

- **B1 done** (`fa2cf011`): `test_inv_21_no_legacy_mastery_writers`; `test_inv_11_gate_false_when_env_unset` rewritten in place over the §7 parse table (both gate entry points, no `table` import, no DB-client call).
- **B2 done, except the re-record** (`ce125b3e`): the mastery tool, the preamble paragraph and `apply_graph_update`'s `updated_nodes` branch are gone (a key is a loud `ValueError` before any I/O); `MasteryUpdateEmittedEvaluator` is retired. **BLOCKED: the `chat_tutor` cassette re-record** — `chat_tutor` runs on `gemini-2.5-pro`, whose daily request quota is exhausted (the key is shared with staging). No live call was made. Resume steps under Known gaps.
- **B3 done** (`59d7695c`): quiz and flashcards are evidence-only for every student (no gate); `p_delta` replaces the legacy key; the quiz E2E expects the BKT posterior.
- **B4 done** (`e780b859`): one tier function, `learning.bkt.tier_for` (0.10 / 0.30 / 0.95), with the three frontend mirrors pinned.
- **B5 done** (`fd003ed4`): the env-only gate with the exact §7 parse; the kill-switch suite marker; the legacy routes' rate limit + budget check; the learning-style step and the empty summary lists removed; `Learn()` never fails open.
- **B5b done** (`dd1a1a9e`): the two E2E lanes (scripts, CI matrix, one lane parse, the global-setup assertion, lane guards).
- **Owner decision: `llm_usage.session_id`, done** (`c2704750`): migration, writer, report preference, plus the required real-SQL integration tests (the A87 claim; the migrations replaying from empty).
- **B6 prepared, NOT run** (`1e3ec043`, session override): the integrator runs both lanes, the kill-switch drill, the integration tests and the smoke in ONE flock'd cycle — commands below. Playwright specs type-check (`npx tsc --noEmit` clean) and parse in both lanes (`npx playwright test --list`: 107 tests / 29 files).
- **B7 done** (this commit): this section, the LEDGER rows, spec §13 A91–A92, the ADR 0030 half-B lines, HANDOFF-00/11/13 Post-hoc lines.
- **B8 skipped** (session override: no PR). **B9 written only** (`## Launch runbook` below), never run.
- **Base deviation** (CONTINUE §4.0 override 9 / session override): the prompt says "branch from main after half A merged"; half B is cut from half A's tip and merges with it into `feat/learning-loop` after B6. Nothing merges to `main`; staging and production were never touched.

### Launch gate (spec §11.1) — status at the end of this session

Git cannot show most of these; nothing here is inferred, and the owner's go-ahead was neither written nor simulated.

| item | status |
|---|---|
| 1. half A merged; LEDGER row 14 `done (half A)`; 00–13/05b/06b latest rows fine | **OPEN.** Half A is not merged; row 14's latest state is `blocked` (the A7 loop_tutor re-record waits on the `gemini-2.5-pro` daily quota). The other packages' latest rows are `verified`/`reopened`. |
| 2. CI green on `main` incl. every `learn-loop.spec.ts` test and the oracles | **OPEN.** Nothing is on `main`; B6 (local) has not run. |
| 3. staging backfill + staging smoke | **OPEN** (owner). |
| 3b. staging kill-switch drill | **OPEN** (owner). The local drill is in the B6 cycle. |
| 4. cost guardrails | **OPEN.** A18 limits, A20 caps/ladder (invariants 23, 28) and A21 token columns are implemented; half B adds the kill-switch path's rate limit + budget check + tutor-call count. Not met: A15 "each tier passed the per-tier evals" (the A7 re-record), the PKG-13 budget-cap journey on this code (B6), the staging smoke's `llm_usage` rows, the owner's cost approval, and the staging proof that the `ai.budget_capped{scope: platform}` alert arrives (production value decided: `PLATFORM_DAILY_BUDGET_USD=5`, A39 (e)). |
| 5. launch UI readiness (§11.3) merged | **Met on `feat/learning-loop`** (PKG-13 verified, `b6c0ed39`); not on `main`. |
| 6. production pinned `LEARNING_LOOP_ENABLED=false`; §11.7 opening paragraph read | **OPEN** (owner). |
| 7. the owner's explicit go-ahead | **OPEN.** Not given in this session. |

Also for the owner at the gate (A45): `STUDENT_DAILY_GRADES` counts `llm_usage` rows, so the grader cap is blind if the launch config sets `EVENTS_LOGGING_ENABLED=false` (half B's tutor-call count covers the tutor, not the grader).

### What changed

- **Evidence-only rule** (spec §11.2). No code path moves a mastery score except graded evidence through `apply_graph_update`: the tutor mastery tool, the `updated_nodes` branch, the flat quiz deltas and their gate branches are gone. `inv_21` greps the retired names across `backend/` (outside `learning/`); the absence checks in tests read the names from `LEGACY_MASTERY_SYMBOLS` instead of spelling them.
- **Quiz** (`routes/quiz.py::submit_quiz`): one `mc` Evidence per question, for every student and under the kill switch. `quiz_attempts.mastery_before/after` are the evidence span; `quiz.completed`, the attempt history and the submit response carry `p_delta`. Flashcards list and rate on FSRS for every student.
- **Tiers**: `learning.bkt.tier_for` + `in_mastered_tier` + `is_weak`; `config.py`'s tier block deleted; `Learn.tsx::tierForScore`, `lib/graph/nodeStyle.ts::tierFor` and `e2e/graph.spec.ts::tierFor` use 0.95 / 0.3 / 0.1.
- **Gate** (`learning/gate.py`): `return bool(config.LEARNING_LOOP_ENABLED)`, no DB import; `config.py` has the exact three lines of §7.
- **Kill-switch path** (`routes/learn.py`): `start_session`, `/start-session/stream`, `/chat`, `/chat/stream`, `/action` carry `Depends(ai_budget.enforce_rate_limit)` and call `_kill_switch_budget(user_id)` after the loop delegation and before any agent run or stream — `ai_budget.check(user, "tutor", KILL_SWITCH_BUDGET_BAND)`; hard → `AIBudgetExceeded` (429); a pass counts one tutor call.
- **Removed**: the learning-style onboarding step (and its reads/writes; `OnboardingBody.learning_style` is Optional and ignored); `end_session`'s three empty lists and their `SessionSummary.tsx` sections.
- **`Learn()`**: `useLoopStatus` → `{status, retry}`; legacy only on 404/`{active: false}`; otherwise `loop-status-error` + `loop-status-retry`.
- **E2E lanes**: `scripts/e2e-up.sh` exports nothing (fail-fast on a `backend/.env` line); `explore.sh` likewise; `e2e.yml` matrix `lane: [default, kill-switch]`; `frontend/e2e/support/lane.ts::killSwitchLane` (re-exported by `fixtures.ts`); `global-setup.ts` asserts the lane against `/status`; guards on `tutor.spec.ts`, `streaming.spec.ts`, the `shot-learn` recipe, every `learn-loop.spec.ts` journey; lane-aware `study-semester.spec.ts`, AskPanel (`quiz-integration`, `quiz-journeys`) and `upload.spec.ts` (kill lane: no check items drafted).
- **Hermetic suite**: the `kill_switch` marker + autouse fixture (`tests/conftest.py`); marked modules listed in `fd003ed4`. The suite passes with `LEARNING_LOOP_ENABLED` unset AND with it `false`.
- **`llm_usage.session_id`** (A92): migration `20260930042516_learning_llm_usage_session_id.sql`; `record_agent_usage(session_id=)`; the degrade-and-retry for a deploy ahead of the migration; the report prefers the row's session.

### Symbols added

- `backend/learning/bkt.py`: `in_mastered_tier(p)`, `is_weak(p)`.
- `backend/routes/learn.py`: `KILL_SWITCH_BUDGET_BAND = "develop"` †, `_kill_switch_budget(user_id)`.
- `backend/agents/usage.py::record_agent_usage(..., session_id=None)`; `backend/services/events_service.py::log_llm_usage(..., session_id=None)`, `_OPTIONAL_COLUMNS`, `_unknown_optional_columns`.
- `backend/db/migrations/20260930042516_learning_llm_usage_session_id.sql`.
- `backend/tests/conftest.py`: marker `kill_switch`, fixture `_kill_switch`.
- Frontend: `components/learn/useLoopStatus.ts` → `LoopStatus`, `{status, retry}`; testids `loop-status-error`, `loop-status-retry` (`docs/frontend-testids.md`); `e2e/support/lane.ts::killSwitchLane`; `e2e/support/quiz.ts`: `BKT_L0`, `BKT_T`, `MC_G`, `MC_S`, `bktAfterCorrect`, `LOOP_TUTOR_REPLY`, `ASK_PANEL_REPLY`, `ASK_PANEL_REPLY_TAIL`, `expectAskReply`.
- Tooling: `docs/superpowers/plans/learning-loop/tools/pkg14b-b6-cycle.sh`.
- Tests (new modules): `test_cutover_tutor.py` 9, `test_quiz_evidence_only.py` 9, `test_cutover_removals.py` 22, `test_learning_llm_usage_session_id.py` 20; integration `test_posttest_claim_db.py` 5 (cut to half-A-complementary tests in the merge), `test_learning_migrations_replay_db.py` 7. `test_learning_gate.py` → 20 (`-k defaults_on` → 9).

### Constants chosen

- `KILL_SWITCH_BUDGET_BAND = "develop"` † (`routes/learn.py`; a band name, never a dollar figure): the kill-switch path has no concept band, so it takes the develop/profic allowance, as `check(…, "close")` does for a session with no novice concept.
- `LOOP_STATUS_TIMEOUT_MS = 2_500` † stays (PKG-13); `LOOP_STATUS_RETRY_MS` is retired (no automatic retries after launch).
- No new `learning/params.py` constant.

### Deviations from spec

- **Built before the §11.1 gate** (owner, 2026-09-29): no `blocked` STOP-gate row was appended; the gate's status is the table above.
- **Base**: half A's tip, not `main` after half A merged (CONTINUE §4.0 override 9).
- **`inv_11` semantics**: rewritten in place over the §7 parse table; the name is historical.
- **`p_delta` rename**: also added to the submit response (the prompt's own test asserts it).
- **Kill-switch budget**: `band="develop"` †; plus `count_tutor_call` on a passing check (A91) — the prompt named only the check.
- **Tier predicate name**: `in_mastered_tier(p)`, because `bkt.is_mastered(p, n_strong_unassisted)` (PKG-01) exists.
- **Half B adds one migration** (A92) against §11.7's "half B adds no migration"; the Rollback revert leaves the additive column.
- **Modules the regression guard lists as unmodified that half B had to touch** (each pins build-phase behaviour §11.2 removes, or the new session kwarg): `test_learning_evidence_apply.py` (the `updated_nodes` legacy trace; `submit_quiz` moved to the sanctioned persisters), `test_learning_fsrs.py` (`UNGATED_FSRS_ROUTES = {"flashcards.py"}`, asserted non-stale), `test_learning_bkt.py` (`test_tier_for_is_not_the_legacy_tier` deleted), `test_learn_loop_routes.py` (a gate-table spy re-pointed at `db.connection.table`; a fake turn gains `session_id`), `test_learning_check_tool.py` and `test_learning_decisions.py` (the recorded-usage pins gain `session_id`).
- **`test_documents_routes.py`** is marked `kill_switch` (the prompt's first option), not updated to the default.
- **E2E**: the lane parse lives in `support/lane.ts` (re-exported by `fixtures.ts`), so `global-setup.ts` never imports a Playwright `test`; the global-setup probe is `/status` with a fresh `session_id` (the route needs one); the AskPanel reply is asserted per paragraph.
- **Deleted tests**: B2's mastery-tool / `updated_nodes` tests, B3's flat-delta and gate-branch tests, B4's `test_tier_for_is_not_the_legacy_tier`, B5's five gate tests (`test_env_on_row_true_is_true`, `test_env_on_row_false_is_false`, `test_env_on_missing_row_is_false`, `test_env_on_missing_key_is_false`, `test_read_error_fails_closed`) and their route-entry, settings-flag and meta twins, B5b's `test_legacy_users_are_not_opted_in` — each named in its commit.
- **`chat_tutor` kept for the kill switch** until the env-var-removal ticket (its `AgentTask`, `_DEFAULTS` entry and `E2E_TUTOR_REPLY` handler stay).

### Known gaps

- **BLOCKED — the `chat_tutor` re-record (B2).** The committed cassettes were recorded against the pre-B2 preamble (they contain `update_mastery_tool` calls, which the evaluators ignore); `baselines.json` dropped only the retired evaluator's key (every other value unchanged). **Resume** after the `gemini-2.5-pro` daily quota resets (midnight Pacific, ≈ 07:00 UTC), with the real key, spending about 16 runs:
  1. `cd backend && git rm -q tests/evals/cassettes/chat_tutor/*.json`
  2. `SAPLING_EVAL_MODE=record venv/bin/python tests/evals/chat_tutor.py`
  3. `SAPLING_EVAL_MODE=replay SAPLING_EVAL_UPDATE_BASELINES=1 venv/bin/python tests/evals/chat_tutor.py` (chat_tutor only)
  4. `SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/run_all.py` → 16/16 PASS; the other datasets' baselines must not move.
  5. Commit cassettes + `baselines.json` together; if an evaluator drops, STOP and report (no bar is lowered).
- **B6 not run** (owner consolidates E2E): the Playwright journeys, the oracles, the integration tests and the drill are unproven on this code until the integrator's cycle.
- **The A7 loop_tutor re-record** (half A) is still blocked; §11.1 item 4 stays open.
- **`LEARNING_LOOP_ENABLED` removal ticket** (it also folds the `chat_tutor` mode prompts into `loop_tutor`).
- **Dead columns**: `user_profiles.learning_style`, `user_settings.learning_loop_beta`.
- **The kill switch restores** no quiz/flashcard deltas, no old tier cuts and no tutor mastery recording (spec §11.6).
- **`SaplingDeps.mastery_changes`** is kept (always empty): `services/chat_stream.py` and the chat wire shape read it.
- **Stored tiers**: `graph_nodes.mastery_tier` rows written before half B keep the old cuts until the node's next write (owner question 2).
- **Landing copy**: `frontend/src/lib/landing/companionContent.ts` (`WIKI_MASTERY_FORMULA`, `WIKI_MASTERY_MOVES`) still describes the retired flat model and the tutor's mastery range (owner question 3; copy is UI/UX's).
- **In-memory state** (half A, after the merge of fix round 3): only `_FAILED_TURN_ANCHORS` (bounded by `LOOP_FAILED_ANCHORS_MAX`); the openers' reveals are in `learning_reveals` (A88). B9 keeps the multi-process precondition.
- **Integration tests**: `test_posttest_claim_db.py` was re-pointed in the merge to half A's `_claim_pose` / `_answer_pose` / `_release_pose` (A89) and cut to what half A's `test_posttest_poses_db.py` does not cover (5 tests: item match, release on error, release never reopens, foreign claim, the 8-submitter claim→close cycle).

### Verify commands

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

Observed at the end of this session (no stack; hermetic override command; neither `SAPLING_MODEL_MODE` nor `SAPLING_FUNCTION_HANDLERS` set):

- Backend: **8377 passed, 156 skipped, 0 failed** with `LEARNING_LOOP_ENABLED` unset, and the same with it `false` (N₀ at half A's tip: 8323 / 140; +16 skips are the new integration tests). Invariants **45 passed, 1 skipped** (`inv_10`). `ruff check .` clean.
- `SAPLING_EVAL_MODE=replay tests/evals/run_all.py`: **16/16 PASS** (chat_tutor on the pre-B2 cassettes — see Known gaps).
- Frontend: `npx tsc --noEmit` clean; `npx vitest run` **1262 passed, 2 skipped**; `npm run lint` exit 0 (warnings only, none new); `npx playwright test --list` 107 tests in both lanes.
- Live spend this session: **$0** (no model call).
- **After merging half A's fix round 3** (`origin/feat/learning-loop-14a-eval-ladder` @ `252723e3`, 2026-09-30): backend **8400 passed, 168 skipped, 0 failed** with `LEARNING_LOOP_ENABLED` unset and the same with it `false` (no `SAPLING_MODEL_MODE` / `SAPLING_FUNCTION_HANDLERS` in either run); invariants **45 passed, 1 skipped**; `ruff check .` clean; `run_all` replay **16/16 PASS**; frontend `tsc` clean, vitest **1262 passed, 2 skipped**, `npm run lint` exit 0, `playwright test --list` 107 tests. Half B's spec rows are renumbered A91 (half B as built) and A92 (`llm_usage.session_id`) — half A took A88–A90 first.

### B6 — the integrator's cycle (not run here)

One flock, one script, from the worktree root (Linux / Podman):

```
cd ~/Projects/sapling-wt-14b
flock /tmp/claude-$(id -u)/sapling-e2e-stack.lock \
  bash docs/superpowers/plans/learning-loop/tools/pkg14b-b6-cycle.sh
```

(`FRONTEND_PORT=3100 E2E_FRONTEND_URL=http://localhost:3100` in front of `bash` if `:3000` is taken.) The script: `supabase stop --no-backup` (fresh volumes, so every migration replays from empty) → default lane with no `LEARNING_LOOP_ENABLED`: `make e2e-up` → `npx playwright test` → `python -m e2e_oracles` → `/status` = 200 → `RUN_INTEGRATION=1 pytest -m integration tests/integration/test_posttest_poses_db.py tests/integration/test_teach_reveal_db.py tests/integration/test_zpd_metrics_db.py tests/integration/test_posttest_claim_db.py tests/integration/test_learning_migrations_replay_db.py tests/integration/test_migrations_ledger.py` → `make e2e-down` → kill-switch lane with `LEARNING_LOOP_ENABLED=false` exported for the stack AND Playwright: `make e2e-up` → Playwright → oracles → `/status` = 404 → `make e2e-down`. It exports `SAPLING_MODEL_MODE=function` and `SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e` for the stack, strips them for pytest, and ends with the gate line:

```
default: playwright=0 oracles=0 integration=0 drill=0  kill-switch: playwright=0 oracles=0 drill=0
```

Equivalent inline (the prompt's B6 form plus the integration tests):

```
flock /tmp/claude-$(id -u)/sapling-e2e-stack.lock bash -c '
  export SAPLING_MODEL_MODE=function SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e
  supabase stop --no-backup >/dev/null 2>&1 || true
  unset LEARNING_LOOP_ENABLED
  make e2e-up && (cd frontend && npx playwright test); s1=$?
  (cd backend && venv/bin/python -m e2e_oracles); o1=$?
  (cd backend && env -u SAPLING_MODEL_MODE -u SAPLING_FUNCTION_HANDLERS RUN_INTEGRATION=1 venv/bin/python -m pytest -m integration -q -p no:cacheprovider tests/integration/test_posttest_poses_db.py tests/integration/test_teach_reveal_db.py tests/integration/test_zpd_metrics_db.py tests/integration/test_posttest_claim_db.py tests/integration/test_learning_migrations_replay_db.py tests/integration/test_migrations_ledger.py); i1=$?
  make e2e-down
  export LEARNING_LOOP_ENABLED=false
  make e2e-up && (cd frontend && npx playwright test); s2=$?
  (cd backend && venv/bin/python -m e2e_oracles); o2=$?
  make e2e-down
  echo "default: playwright=$s1 oracles=$o1 integration=$i1  kill-switch: playwright=$s2 oracles=$o2"
  exit $((s1|o1|i1|s2|o2))'
```

**What to watch** (first run of these journeys on this code):

- **Default lane, legacy-only tests skipped**: exactly `tutor.spec.ts`, `streaming.spec.ts`, the `shot-learn` gallery recipe and "kill switch restores the legacy Learn screen". Kill-switch lane: the four `learn-loop.spec.ts` loop journeys and "every student gets the loop by default" skipped.
- **Quiz** (both lanes): `p_after` 0.978259 (`toBeCloseTo(…, 5)`), three `evidence`/`mc` rows with `evidence_seq` order, `times_studied` 3, the results line's "before" at 35 % (the BKT prior — not the seeded 25 %), the Tree row `+63% mastery`. A mismatch here means HANDOFF-03's prior rule or the per-question evidence changed.
- **AskPanel default lane**: `quiz-integration` / `quiz-journeys` expect the loop opener's `E2E_LOOP_TUTOR_REPLY` paragraphs, and the follow-up counted by its last paragraph ("Which input should stop the recursion?"). If the loop opener serves something else (a probe item, a no-items template) this is the first place it shows.
- **global-setup** throws if the stack and Playwright disagree about the lane (`/status` for `rich-user-active` with a fresh `session_id`: 404 vs `{active: true}`) — check `backend/.env` has no `LEARNING_LOOP_ENABLED` line (e2e-up exits 2 on one).
- **Onboarding** has five steps; `study-semester` default lane expects `review-due-panel` beside the deck; `upload.spec` kill lane expects zero `check_items` for the uploaded doc.
- **Oracles in the kill-switch lane**: the course-context refresh runs the legacy prose regime (`course_summary` handler is registered); `logscan` must stay clean with its `ALLOWLIST` untouched.
- **Integration**: six files — half A's `test_posttest_poses_db.py` (9), `test_teach_reveal_db.py` (6), `test_zpd_metrics_db.py`, half B's `test_posttest_claim_db.py` (5: the claim→close cycle under 8 concurrent submitters closes the pose once) and `test_learning_migrations_replay_db.py` (7: on the fresh-volume stack the four PKG-14 migrations — loop_arm, posttest_poses, learning_reveals, llm_usage_session_id — are in the ledger in filename order, re-apply idempotently, and session_id round-trips), plus the ledger test.
- **Known pre-existing flake**: `e2e/gradebook.spec.ts:35` (fixed on main by #691).
- After the half A re-review fixes merge (`git merge origin/feat/learning-loop-14a-eval-ladder`), re-run this whole cycle.

### Open questions for the series owner

1. **The launch gate** (above): items 1, 2, 3, 3b, 4, 6 and 7 are open; only you can close 3–7, and item 7 is your written go-ahead.
2. **Stored tiers**: re-derive `graph_nodes.mastery_tier` once for rows written under the old cuts (an idempotent data migration from `mastery_score`), or let each node update on its next write? Until then the Tree can label a 0.8 node "mastered" (old cut) while a fresh 0.8 node reads "learning".
3. **Landing copy** (`companionContent.ts` `WIKI_MASTERY_*`) still explains the flat quiz deltas and the tutor's mastery range — a UI/UX copy change.
4. **A45**: will the launch config ever set `EVENTS_LOGGING_ENABLED=false`? The grader cap is blind then.
5. The `chat_tutor` re-record and the half A A7 re-record both wait on the `gemini-2.5-pro` quota — run them in the same window?
6. Carried from the prompt: the first `loop_arm` experiment (the variant-B gate, owner-chosen); whether `LEARNING_LOOP_ENABLED` is removed next sprint; whether earnest-revise gets a signal; whether stored `messages.graph_update_json` `updated_nodes` keys need a read-side migration (they do not today — `end_session` and `quiz_signals` only read names).

### Post-hoc changes

(Appended by later packages. Format: `PKG-MM <date>: <what> — commit <sha>`.)

## Launch runbook

Owner-run (spec §11.7; PKG-14 Task B9). A build session writes it and never runs any step: no deployed env var, no `make promote`, no staging or production backfill, no revert.

### Preconditions

Every line is green on the half B merge commit.

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

Also before step 1 (half A preconditions, kept):

- [ ] **One backend process until the in-memory maps move to the database.** `_FAILED_TURN_ANCHORS` (the A85 failed-turn anchors) lives in process memory (bounded by `LOOP_FAILED_ANCHORS_MAX`). Before production runs more than one backend process or replica, it must move to the database (`grep -n "_FAILED_TURN_ANCHORS" backend/routes/learn_loop.py`). The openers' reveals are already durable (`learning_reveals`, A88) and so is the post-test claim (A87/A89, `posttest_poses`).
- [ ] **Migrations before code** on each environment (A92): `llm_usage.session_id` is additive; code ahead of it degrades (drops the column and retries), but run the migrations first anyway — `dotenv -f .env.staging run -- python -m db.migrate` before the merge (#651: `migrate-staging.yml` races the deploy).

§11.7, verbatim:

Merging half B to `main` launches STAGING (`main` = staging). The first `make promote` after that merge — step 6 below, or ANY unrelated promote — carries half B to production. The production pin (`LEARNING_LOOP_ENABLED=false`) turns off only what the gate controls: the loop UI and the `/api/learn/loop/*` routes. It does NOT hold back half B's ungated changes, which reach every production student with that promote: quiz and flashcards become evidence-only (no per-item mastery deltas), the tier cuts become 0.10/0.30/0.95 on every graph and Learn screen, the legacy tutor — the only tutor while pinned — records no mastery, the learning-style onboarding step disappears, and the legacy tutor routes gain the budget check and rate limit. The kill switch cannot undo those (§11.6); only the Rollback below can. Therefore: merge half B only when steps 3–10 can run in one owner-attended window, and run NO unrelated `make promote` between the half B merge and step 8.
1. **Pin production off; set the platform alert.** Before the half B PR merges, the owner sets `LEARNING_LOOP_ENABLED=false` on the production host and the production `PLATFORM_DAILY_BUDGET_USD` chosen at §11.1 item 4, and confirms both in the session.
2. **Merge half B** (only inside the window above). Staging now runs the loop for everyone (staging env `true` or unset).
3. **Staging backfill, then staging smoke.** Re-run the §11.1 item 3 staging backfill (dry run first; the `Project:` line is the staging ref; idempotent — covers uploads since). Then, on an account with NO `learning_loop_beta` and pre-existing legacy sessions and graph: `/api/learn/loop/status` → `{"active": true}`; `/learn` shows `loop-phase`; probe → plan → teach → check (the pose appears; `/check/answer` grades) → close completes; clicking a pre-launch "Where you left off" card on the Dashboard shows its transcript read-only (`loop-readonly-transcript`) with no `/probe/*` call; `/study` shows the DueQueue panel; the session's `llm_usage` rows carry tier slot names and token columns.
4. **Kill-switch drill on staging — go/no-go before any production step.** Set staging `LEARNING_LOOP_ENABLED=false` and redeploy → `/api/learn/loop/status` 404; `/learn` shows `tutor-topic-picker` and one legacy tutor turn completes; `/study` hides `review-due-panel`; an upload drafts no `check_items` rows. Remove the override, redeploy, `/status` active again. Any failure → STOP: no promote; fix forward on `main` or take the Rollback.
5. **Abort criteria agreed.** The owner writes them into the session before step 6 (defaults below, under Rollback).
6. **`make promote`** (still pinned). Production now runs half B code with the loop off — and half B's ungated changes are live for every production student (intro). The abort-criteria watch starts now. Production gets PKG-04's `check_items` migration only here, so the production backfill must follow this step.
7. **Production check-items backfill.** First confirm, by name only (never print values), that the production env file the promotion runbook uses (`.env.production`) defines `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `ENCRYPTION_KEY`, `GEMINI_API_KEY` and `SAPLING_MODEL_MODE=real` — the script fills anything missing from `.env.staging` and `backend/.env`, which would encrypt with the wrong key or write to the wrong project. Then `cd backend && dotenv -f .env.production run -- env LEARNING_LOOP_ENABLED=true venv/bin/python scripts/backfill_check_items.py --all-courses --project <production ref> --dry-run` and confirm the printed `Project:` line is the production ref (the script refuses to run when `--project` differs from the project `SUPABASE_URL` points at); then the same command without `--dry-run`; the owner reviews the `coverage <course_id> <with_items>/<concepts>` lines (A23).
8. **Unpin:** delete the production variable (or set it to `true`; under the §7 parse an empty value also means ON) and redeploy; `make promote ARGS="--verify-only"`.
9. **Re-run the step-7 backfill** (idempotent; covers uploads made between steps 7 and 8).
10. **Production smoke on a non-staff account:** `/api/learn/loop/status` → `{"active": true}`; one probe item answered; one check posed and graded; one review served; `llm_usage` rows for the tiers used.
11. **Keep coverage complete.** The owner schedules the idempotent `--all-courses` backfill as a recurring production job (nightly, beside `scripts/derive_zpd_metrics.py`; it runs on the flex tier with `user_id=None`, and a covered concept costs nothing). The upload hook drafts at most `CHECK_ITEM_MAX_CONCEPTS_PER_DOC` concepts per upload and nothing else adds items, so without it coverage erodes; PKG-14's metrics REPORT prints per-course coverage so erosion is visible.
12. Append `Launched: <date>` to the cutover ADR.

**Rollback (the owner decides; the session never does).**
- Abort criteria (defaults; the owner may tighten them at step 5), watched for 7 days from step 6: the 5xx rate on `/api/learn/*` or `/api/learn/loop/*` above 2× its pre-launch 7-day baseline for 15 minutes; an `ai.budget_capped{scope: platform}` alert; measured `llm_usage` cost per active student-day above 2× the target (the target is $0.36/student-month ≈ $0.012/day) for a full UTC day; any `zpd.leak` event or an e2e-oracle data-integrity finding on production data.
- Loop only (after step 8): `LEARNING_LOOP_ENABLED=false` + redeploy — the kill switch (§11.6).
- Everything half B changed (after step 6; this is the only way back from the ungated changes): `git revert -m 1 <half B merge sha>` on `main` (staging), verify staging, then `make promote`. The revert restores the build-phase gate (env AND `learning_loop_beta`), so production is off whatever the variable says. Evidence rows, `learner_state` and the backfilled `check_items` stay (append-only; the legacy path ignores them; `graph_nodes.mastery_score` keeps the BKT values written meanwhile, and legacy deltas resume from them). Half B adds no migration, so none is reverted.

Owner amendments in force for these steps (spec §13 A39 (e), A92; PKG-14 "A38 amendments" 3):

- [ ] **Step 1, platform budget:** production `PLATFORM_DAILY_BUDGET_USD=5` (owner decision; replaces the "suggested ≈ 3×" wording). BEFORE setting it, prove the alert on staging: set a deliberately low staging value (e.g. `0.01`), drive one tutor turn, confirm the `ai.budget_capped{scope: platform}` alert reaches you, then restore the staging value.
- [ ] **Rollback:** "Half B adds no migration" no longer holds — `20260930042516_learning_llm_usage_session_id.sql` is half B's. A revert of the half B merge leaves the column (additive and nullable; the build-phase code never names it); nothing to revert.

Owner checklist: - [ ] 1 · - [ ] 2 · - [ ] 3 · - [ ] 4 (go/no-go) · - [ ] 5 · - [ ] 6 · - [ ] 7 · - [ ] 8 · - [ ] 9 · - [ ] 10 · - [ ] 11 · - [ ] 12
