# HANDOFF-12 — review-surfaces

Written by the session that executed `PKG-12-review-surfaces.md`. Read by every later package that depends on 12. Keep every heading, even if the answer is "none".

**Status: built on `feat/learning-loop-12-review-surfaces` (PKG-07 merged in, 16bde4a7); fix round after three reviews done (Post-hoc changes); awaiting the coordinator** (LEDGER is the coordinator's: no `12` row is written here). No push, no PR, no E2E cycle run (session override: the integrator runs the flock'd cycle and the flag-on manual check of Task 6 Step 5).

## What changed

A student with the learning loop on has a daily review queue. `learning/review.py` merges due flashcards and due concepts (each mapped to one servable check item, never a seen, revealed or post-test-reserve item, A23), orders them by the DASH rule and cuts them at the 12-minute daily budget; at the tutor hard level novice concepts pause while flashcards and the rest keep working (A20). A check review is graded by PKG-05's `grade_answer` (A16, the A22 pre-checks intact) and its one Evidence dict is persisted unchanged by ONE `apply_graph_update(..., retention=)` call at the review's retention target (default / large set / exam window); a flashcard review goes through PKG-11's `flashcard_fsrs_update` at the same target. Successive-relearning counters and HANDOFF-02's `SuccessiveRelearning` machine ride in the review session's `sessions.loop_state` (a `mode='review'` row per user, course and UTC day), written only through `update_loop_state`. Three gated routes serve it — `GET /api/learn/loop/review/next`, `POST /review/answer`, `GET /review/summary` — and grading follows PKG-07's claim discipline (A52): a served item is opened for answering, an answer claims it by compare-and-set before the grader runs, and a double submit (sequential or concurrent) is a 409 that never grades or writes twice. Study → Flashcards shows a "Due today" panel (`DueQueue`) only when the loop is on; otherwise the legacy UI is unchanged.

## Symbols added

- `backend/learning/review.py`:
  - `ReviewItem{kind, id, node_id, course_id, question_hash, due_at, last_review_at, r, stability, format, difficulty, cost_s, sr_stage, sr_target, sr_count, concept_name, topic}`, `ReviewOutcome{correct, hint, next_due_at, rating, sr, unavailable, refused}`.
  - `retention_target(n_scheduled_concepts, exam_within_days) -> float` (wraps `fsrs.retention_target`), `review_retention(user_id, course_id) -> float` (scheduled `learner_state` count on the course + `exam_proximity.days_until_next_exam`).
  - `sr_stage_for_concept(streak_unassisted)`, `sr_stage_for_flashcard(reps, last_rating)` → `(stage, target)`; `sr_key(item)` (`node_id` / `"fc:<card id>"`, the key of `loop_state["sr"]` and `loop_state["open"]`).
  - `review_session_id(user_id, course_id, now)` (uuid5, one per user/course/UTC day), `load_or_create_review_session(user_id, course_id, now) -> (sid, {"sr", "review"})` (insert-if-missing, A11; `review.session_started`, never `session.started` — A73; the read filters by id AND user_id; `PermissionError` for another user's row), `peek_review_session(user_id, course_id, now) -> dict` (read-only: never inserts).
  - `seen_hashes` / `revealed_hashes` (PKG-07's `loop_state_store` readers — ONE definition; read once per queue build, only when a concept is due).
  - `due_queue(...)`, `due_queue_with_stats(user_id, course_id, now, *, loop_state=None, pause_novice: bool | Callable[[], bool] = False) -> (queue, {"due": {"flashcard", "check"}, "in_budget", "unservable", "paused"})` — one DASH-ordered walk over due cards and due concepts; a concept's items are read only while it is inside the budget; `pause_novice` may be a thunk (read once, only when a novice concept is due); `due` counts everything due (concepts past the budget without an item read), `in_budget` the queue. `remaining_budget_s(loop_state)`, `log_served(...)`, `summary(...)` (adds `in_budget`).
  - `InvalidStability(ValueError)`, `_stability(raw)` (None → S0; not finite-positive → raise; the queue skips + WARNs), `open_item_ids(loop_state, now) -> {key: item_id}` (open, ungraded, not under a stale claim), `is_open(loop_state, item, now)`.
  - `item_for_card(row, course_id, now)`, `load_card(user_id, card_id)` (both filters; `_CARD_ROW_COLUMNS` adds `times_reviewed,front,back`), `item_for_check(user_id, check_item, node_id, now)` (one `learner_state` read) — the answer route's server-side re-load.
  - `serve(item, *, check_item=None, card_row=None, loop_state, session_id=None, now=None) -> dict` — no reference / final / canonical answer, rubric, wrong keys or correct option; `mc_reason` → stored `options: [{letter, text}]` (A22). With `now` it opens the item: `loop_state["open"][key] = {"item_id", "served_at"}`; re-serving the item already open for its key writes nothing (A70).
  - Claims (A52): `ReviewClaimRefused(reason)` (`"not_served"` | `"already_graded"`), `claim_item(session_id, key, item_id, claim, now)` (one CAS write; never re-taken), `_release_claim`. `grade_review(..., claim=None)`: unavailable / refused / an error before the write release it; after the write only the record closes it (`graded_at`), so a lost record keeps the item claimed.
  - `async grade_review(user_id, item, *, answer, rating, session_id, loop_state, now, request_id, retention, check_item=None, card_row=None, selected_option=None, reason=None, deps=None, claim=None) -> ReviewOutcome`.
- `backend/routes/learn_loop.py` (appended at the END, its own import block with `# noqa: E402` per line — no ruff baseline entry): `_pause_novice(user_id)` (`ai_budget.check(uid, "tutor", "novice").pause_novice`), `_review_deps(user_id, course_id, session_id, request_id, loop_on)` (`SaplingDeps(..., feature="loop_review", learning_loop=<the gate>)`), `_review_session`, `_serve_review_item`, and the routes:
  - `GET /review/next?user_id=&course_id=` → `{item | null, remaining_budget_s, session_id, retention_target, due_total, in_budget}`; serves the open item first (no write, no event); skips an item that no longer loads (withdrawn / deleted); `review.served` only after a fresh serve.
  - `POST /review/answer` (`ReviewAnswerBody`) → `{correct, hint, next_due_at, rating, remaining_budget_s, sr, unavailable, refused}`. 409 `"review session expired"` (body `session_id` ≠ today's), 404 `"review item not found"` (item, card or the student's node missing), 422 (format needs `selected_option` / `answer`; `ValueError` from grading), 409 `"review item not served"` / `"already graded"` (claim), 409 `"loop state changed, retry"` (`LoopStateConflict`), 403 (another user's row), 429 (rate limit, check answers only).
  - `GET /review/summary?user_id=&course_id=` → `{due: {flashcard, check}, in_budget, unservable, paused, budget_min, remaining_budget_s, retention_target}`; read-only.
  - `GET /review/active?user_id=` → `{active: true}` after `_gate` (404 when off); builds nothing — the frontend's loop probe (A72).
  - Every review route with a `course_id` the student is not enrolled in (`academics.user_offering_ids_for_course` empty) → 404 `"Course not found"`.
- `backend/models/__init__.py::ReviewAnswerBody{user_id, session_id, course_id?, kind: "flashcard"|"check", item_id, answer?, selected_option?, reason?, rating?}` — free text `max_length=GRADER_ANSWER_MAX_CHARS`; check needs `answer` or `selected_option`, flashcard needs `rating ∈ {1,2,3}`; `extra="forbid"` (no `node_id`, no `model_pref`).
- `backend/learning/params.py`: `REVIEW_SECONDS_PER_FLASHCARD`, `REVIEW_DIFFICULTY_BY_BAND`, `REVIEW_FORMAT_BY_BAND`.
- `backend/services/events_service.py`: `review.session_started {session_id, offering_id}`, `review.served {kind, n, budget_min, retention_target}`, `review.graded {kind, correct, rating}` (usage; taxonomy + pin).
- `backend/services/session_modes.py::REVIEW_MODE`, `::NOT_REVIEW` (`{"mode": "neq.review"}`) — added to the filters of `routes/learn.py::list_sessions` / `resume_session`, `services/quiz_signals.py::_tutor_recency`, `routes/profile.py::_get_user_stats`, `services/achievement_service.py` (`session_count`, the session-time stats) (A73).
- `backend/learning/params.py::SR_RELEARN_SESSION_TARGET = 1` (spec §3.2: one correct recall per relearn/done session).
- Migration `backend/db/migrations/20260929111535_learning_fsrs_stability_positive.sql` (A74): `learner_state_fsrs_s_positive`, `flashcards_fsrs_s_positive`.
- Migration `backend/db/migrations/20260929081946_learning_sessions_mode_review.sql` (spec §4, A9): `sessions_mode_check` gains `'review'`.
- `sessions.loop_state` keys (the review session's `LoopState.extra`): `sr[key] = {correct, target, served, stage, relearning}`, `review = {spent_s, served_hashes, retention}`, `open[key] = {item_id, served_at, claim?, claim_at?, graded_at?}` (Unix seconds).
- Reopens: PKG-03 `apply_graph_update(..., retention=None)` (ed164152), PKG-05 `SANCTIONED_GRADING_CALLERS += learning/review.py` (6cd51975), PKG-11 `learning/flashcard_fsrs.py::flashcard_fsrs_update(card_row, rating, *, now, retention)` + `fsrs_rating_for` (13364aa7), PKG-06 `_PKG06_SANCTIONED_IMPORTERS += learning/review.py` (8bd26367; merged as the union with PKG-07's `routes/learn_loop.py`).
- Invariants: `test_inv_19_review_grades_through_grader_only`; inv 26's `EVIDENCE_WRITERS += grade_review`, `EVIDENCE_WRITER_CALLERS += review_answer`; `tests/test_learning_review.py::test_grade_review_called_only_from_review_answer`.
- Frontend: `frontend/src/lib/api.ts` — `ReviewSr`, `ReviewItemPayload`, `ReviewNextResponse` (+ `in_budget`), `ReviewAnswerBody`, `ReviewAnswerResponse`, `ReviewSummaryResponse` (+ `in_budget`), `getReviewNext(userId, courseId?)`, `answerReview(body)`, `getReviewSummary(userId, courseId?)`, `getLoopStatus(userId) -> {active}` (probes `GET /review/active`; all through `fetchJSON`, same-origin). `DueQueue` drops a response for an older request, keeps the typed answer on a 409 "…retry" and re-polls on any other 409. `frontend/src/components/learn/DueQueue.tsx::DueQueue({userId, courseId?})`. `Study.tsx::FlashcardsMode` — `loopActive` state + one `getLoopStatus` effect; `<DueQueue>` as the column's first child.
- Testids (`review` surface, `docs/frontend-testids.md` + the eslint testid block): `review-due-panel`, `review-budget`, `review-empty`, `review-item`, `review-answer-input`, `review-option-{letter}`, `review-reason-input`, `review-submit`, `review-flip`, `review-rate-1|2|3`, `review-hint`, `review-next`, `review-budget-spent`.
- Task 5 Step 0 bindings: (I) inv 26 keys on FUNCTION names (`EVIDENCE_WRITERS` / `EVIDENCE_WRITER_CALLERS`); (R) PKG-07 attaches `dependencies=_RATE_LIMITED`; the review routes carry none and call `ai_budget.enforce_rate_limit_for` inline for `kind == "check"`; (D) `SaplingDeps(user_id, course_id or None, supabase=None, request_id, session_id, feature, learning_loop=<_gate's bool>)`; (N) `_node_for_item(user_id, item)` (course + `_normalize_concept(concept_name) == concept_key`); (B) `ai_budget.check` is sync.
- Tests: `tests/test_learning_review.py` 128 (60 before Tasks 5–6; 104 at the first hand-off; +24 in the fix round), `tests/test_review_sessions_excluded.py` (11), `tests/test_learn_loop_routes.py` (`REVIEW_ROUTES`), frontend `DueQueue.test.tsx` (10), `Study.dueQueue.test.tsx` (3), `api.test.ts` (+3).

## Constants chosen

- `REVIEW_SECONDS_PER_FLASHCARD = 15` † (§3.2 prices only checks)
- `REVIEW_DIFFICULTY_BY_BAND = {"novice": 1, "develop": 2, "profic": 3}` † (§3.1 bands, §3.4 difficulties)
- `REVIEW_FORMAT_BY_BAND = {"novice": "mc_reason", "develop": "mc_reason", "profic": "free"}` † (the other value is the rule-1 fallback)
- Consumed: `REVIEW_DAILY_BUDGET_MIN = 12`, `REVIEW_SECONDS_PER_CHECK = 45`, `REVIEW_ORDER_THRESHOLD = 0.33`, `SR_INITIAL_CRITERION = 3`, `SR_RELEARN_SESSIONS = 3`, `FSRS_RETENTION_*`, `FSRS_EXAM_WINDOW_DAYS`, `FSRS_LARGE_SET_CONCEPTS`, `FSRS_S0_GOOD`, `GRADER_ANSWER_MAX_CHARS`, `LOOP_GRADING_CLAIM_STALE_S = 120` † (PKG-07; here: when a re-serve may replace a claimed open entry).

## Deviations from spec

- Exam window beats large set in the retention target † (also A7).
- The SR stage is derived (`streak_unassisted` / `reps`), not stored † — the flashcard derivation cannot see a lapse mid-relearn (`reps` never decreases; only `last_rating == 1` restarts acquisition).
- Rule 1's other-format fallback (`REVIEW_FORMAT_BY_BAND`'s other value) †.
- Review persists `outcome.evidence` through ONE direct `apply_graph_update(..., retention=)` instead of `flush_pending` (which has no retention parameter; PKG-08's `/probe/answer` pattern) → PKG-03 reopen: `retention` is a KEYWORD of `apply_graph_update`, not `graph_update["retention"]` (a payload key would ride the evidence dict's validation path).
- `fsrs.order_due(items, r_of)` → PKG-02's `order_due` sorts MAPPINGS (`fsrs_s`, `fsrs_last_review_at`), so `_order` wraps each item in the mapping its R came from.
- `fsrs.budget_select(items, budget_s, cost_of)` → PKG-02's prices every item at one cost; the queue mixes 45 s checks and 15 s cards, so `_budget_prefix` is a local greedy prefix summing each item's own cost (stops at the first misfit, so a cheaper later item never jumps the DASH order).
- Successive relearning uses HANDOFF-02's `fsrs.SuccessiveRelearning` per key (persisted as `sr[key]["relearning"]`) next to the per-session counters, seeded from the derived stage.
- `flashcard_fsrs_update` lives in `learning/flashcard_fsrs.py` (PKG-11 reopen; the prompt allowed `services/`), so `learning/review.py` never imports `routes.*`.
- `getLoopStatus` probes a gate-only review route (first `/review/summary`, since the fix round `GET /review/active`) → PKG-07's `GET /status` requires a loop `session_id`. `test_status_reports_active` is `test_review_summary_200_when_active` (+ `test_review_active_is_the_cheap_gate_only_probe`).
- Grading claims (A52 applied to review; not in the prompt): `serve` opens the item in `loop_state["open"]`, `/review/answer` claims it first. Consequences: an item the session never served is a 409 `"review item not served"` (a client cannot grade arbitrary items — e.g. a post-test reserve item — or read their reference through the corrective hint); a double submit is a 409 `"already graded"`.
- `/review/summary` reads the session without creating it (`peek_review_session`); the prompt's `load_or_create` would insert a review row on every Study visit (it is the loop probe).
- `/review/answer` recomputes the retention via `review.review_retention` when the session has none stored (the prompt's `_retention(stats["n_scheduled"])` — `due_queue_with_stats` has no `n_scheduled`); `due_queue_with_stats` stats carry `due` per kind instead.
- A11's lazy insert is MIRRORED, not shared: `load_or_create_review_session` repeats `routes/learn.py`'s insert-if-missing (a `sessions` row, `offering_id` from `resolve_offering`) instead of calling a shared helper, because `learning/review.py` may not import `routes.*` and the legacy insert is entangled with `PENDING_SESSIONS`. Pointer for PKG-09: a session-row helper in `services/` would give the close path, the loop and review one insert.
- Review sessions are excluded from every tutor-session reader and emit `review.session_started` (A73); the prompt had them emit `session.started` "the same way that site does".
- `/review/next` re-serves the open item instead of re-selecting (A70); `due_total` is the true due count plus `in_budget` (A72); `course_id` is validated against enrollments (404); `getLoopStatus` probes the new `GET /review/active`, not `/review/summary` (A72).
- The queue reads a concept's items only while it is inside the budget, and the tutor-budget read is lazy (fix round, cost); `unservable` therefore counts only examined concepts.
- `ReviewAnswerBody` forbids unknown fields (a forged `node_id` or a `model_pref` is a 422) and lives in `models/__init__.py`; the response carries `refused`.
- The plan's `patch("routes.learn_loop.learning_loop_active")` → `learning_loop_for_request` (PKG-07's gate); route tests call the real `_gate`.
- The review routes are appended with mid-file imports carrying `# noqa: E402` (the prompt's separate import block at the end; the ruff baseline is not extended).

## Known gaps

- Name mappings from the prompt's table (HANDOFF names won): `order_due` / `budget_select` shapes (above), `grade_answer` flat `CheckAnswer` (no `idk` sent by review), `get_check_item`, `_node_for_item`, `learning_loop_for_request`, `enforce_rate_limit_for`, `flashcard_fsrs_update` in `learning/`.
- `DueQueue.tsx` is the launch Study surface; PKG-13 adds the budget-pause banner and launch polish. No isomorph re-ask from reviews.
- Within-session relearning is not scheduled: a graded card/concept is no longer due (FSRS moved `due_at`), and a wrong answer only resets the session count — the item comes back in this session only if FSRS makes it due again before the day ends. The within-session acquisition target (3) is therefore rarely reached in one session; the counters still record what happens.
- A lost record after the write keeps the item claimed until a later serve replaces the entry once the claim is older than `LOOP_GRADING_CLAIM_STALE_S`; for a flashcard that re-serve can rate the same card again, and `review.graded` is not emitted for the lost record.
- A review session id is deterministic; the legacy tutor routes that take a session id (`/chat`, `/action`, `/end-session`) do not refuse a `mode='review'` row — it is excluded from every listing and from resume, so a client must forge the id to reach it.
- The fsrs_s CHECK's "existing data" claim is verified by code (both writers go through `fsrs.next_state`, pinned by a domain test), not against a live database — no local stack was run in the fix round.
- Not run here (session override): the E2E cycle and the flag-on manual check (`LEARNING_LOOP_ENABLED=true`, `learning_loop_beta` by SQL, `GET /review/next` 200, a `mode='review'` row) — the migration's live proof is still owed.

## Verify commands

```
cd backend && venv/bin/python -m pytest tests/test_learning_review.py -q                        → N passed (N ≥ 10)
grep -c "review/next" backend/routes/learn_loop.py                                               → ≥ 1
grep -c '"review\.served"\|"review\.graded"' backend/services/events_service.py                  → 2
```

(Observed after the fix round: `128 passed`; `1`; `2` (first hand-off: `104 passed`). Full suite `pytest tests/ -q -p no:cacheprovider --ignore=tests/evals --ignore=tests/test_docling_integration.py --ignore=tests/test_ocr_pipeline.py --ignore=tests/test_extraction_backends.py` → 7440 passed, 136 skipped (7405 at the first hand-off); `SAPLING_EVAL_MODE=replay tests/evals/run_all.py` → all 13 datasets PASS; `cd frontend && npm run typecheck && npm run lint && npm test` → clean, 0 lint errors, 1127 passed / 2 skipped.)

## Open questions for the series owner

- (1) Store `sr_stage` on `learner_state` / `flashcards` (PKG-14)? Took: derived.
- (2) Should review sessions get finer `sessions.mode` values for analytics beyond `'review'`? Took: `'review'`.
- (3) Cache `days_until_next_exam` per request? Took: one read per `/review/next` (and per answer without a stored retention).
- (4) Due-review overlap with PKG-08's `GET /plan`: the plan's "reviews first" section is its own `order_due` + `budget_select` over the same due concepts, graded through `/probe`/`/check` in the loop session, while this queue grades the same concepts in the review session — the two budgets and SR counters are independent, so a concept can be reviewed twice in a day. Took: independent; PKG-08/13 should decide whether the plan's reviews come from `review.due_queue` (one queue) or the Study panel hides concepts the day's plan already covers.
- (5) [RESOLVED — fix round, A70] `/review/next` re-serves the still-open item for a key.

## Post-hoc changes

(Appended by later packages that modified this package's code. Format: `PKG-MM <date>: <what> — commit <sha>`.)
- PKG-12 2026-09-29 (fix round after three reviews): review sessions excluded from every tutor-session reader + `review.session_started` (A73) — c1a6d8cb; PKG-11 docstring (m7) — dfc5d18a; stable open item on refresh (A70), budget-bounded item reads, SQL due filter, lazy tutor-budget read, `/review/active` probe, `due_total` + `in_budget`, course 404, `InvalidStability` + the fsrs_s CHECK migration (A74), `review.served`/`review.graded` only on a real serve/record, `check_achievements("flashcards_reviewed")`, `SR_RELEARN_SESSION_TARGET`, user-scoped session read — 13be97f5; DueQueue race guard, retry-409 vs moved-on 409, `review-budget-spent` — 876cfdb1; spec §4/§5/§6/§9 and §13 A70–A74 (numbered from A70: PKG-08 adds rows in parallel) + HANDOFF-07/11 post-hoc lines — the docs commit after these.
- PKG-12 2026-09-29 (PKG-08 merge, 96bb2ef8): review routes sit after PKG-08's probe/plan block; `_session_scope` refuses review sessions (a phase-less review document would read as probing) — tests `test_loop_session_scope_never_resolves_a_review_session`, `test_probe_next_on_a_review_session_id_writes_nothing`, `test_review_routes_never_consult_the_loop_phase`, `test_a_phase_less_review_document_still_serves` — commit fd5b9ca3
