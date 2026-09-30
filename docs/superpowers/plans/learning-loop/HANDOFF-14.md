Half A only — half B (cutover) pending the series owner's confirmation.

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

## Verify commands

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
