# HANDOFF-11 — quiz-flashcards

Written by the session that executed `PKG-11-quiz-flashcards.md`. Read by every later package that depends on 11. Keep every heading, even if the answer is "none".

## What changed

`POST /api/quiz/submit`, `POST /api/flashcards/rate` and `GET /api/flashcards/user/{user_id}` each evaluate `learning.gate.learning_loop_active` once, at route entry, into a local `loop_on`. With the loop on, `submit_quiz` hands `apply_graph_update` one `Evidence` dict per graded question under the single key `"evidence"`: channel `"mc"`, the stored or recomputed `question_hash`, and no session or check item. On that path it never calls `quiz_config.mastery_after` and computes no `quiz_*` event type. The attempt's `mastery_before`/`mastery_after` are then the first `before` and the last `after` the graph returned. With the loop on, `rate_card` maps the 1/2/3 UI rating to FSRS Again/Hard/Good through `FLASHCARD_RATING_TO_FSRS`; any other rating is a 422 before any write. It advances FSRS-6 state through `learning.fsrs.next_state`/`interval` at `FSRS_RETENTION_DEFAULT` and writes `fsrs_d`, `fsrs_s`, `due_at`, `reps` and `lapses` in the same single `update` as the three legacy columns. The response gains `due_at` and `fsrs_rating`. With the loop on, `get_flashcards` also selects the five FSRS columns and returns cards in three groups: due cards first, in `learning.fsrs.order_due`'s `|R − REVIEW_ORDER_THRESHOLD|` order; then never-rated cards, in the query's `created_at.desc` order; then not-yet-due cards by `due_at`. It honours `?due_only=true` and adds `due_count`. With the gate false, all three handlers issue the same queries, payloads and response shapes as before, byte for byte, and a `gate_off` snapshot test pins each one. Migration `20260927035346_learning_flashcards_fsrs.sql` adds the five columns and `flashcards_due_idx`. PKG-03's `test_inv_01_single_graph_writer` now names both routes explicitly. PKG-03's evidence-caller scan now sanctions exactly the gated `submit_quiz` call, and its fsrs-importer pin now admits `routes/flashcards.py`. The E2E seeded student stays on the legacy path, so the `+0.09` pin in `frontend/e2e/quiz.spec.ts` is untouched.

## Symbols added

- `backend/routes/quiz.py::_quiz_evidence(concept_node_id, questions, results) -> list[dict]` — one dict per `(stored question, result)` pair, in stored order, with exactly the keys `node_id`, `channel="mc"`, `correct`, `question_hash=wire_question_hash(question)` (may be None), `check_item_id=None` and `session_id=None`. Every other `Evidence` field takes the model default. The student's `confidence` is never copied.
- `backend/routes/quiz.py::_mastery_span(applied, default_before) -> tuple[float, float]` — the first recognisable change's `before` (default `default_before`) and the last recognisable change's `after`. "Recognisable" means a dict whose `after` is not None. An empty or unrecognisable return is `(default_before, default_before)`. Used only on the loop path.
- `backend/routes/quiz.py::submit_quiz` — gains `loop_on = learning_loop_active(user_id)` right after the attempt load. On the loop path it calls `apply_graph_update(user_id, {"evidence": _quiz_evidence(...)}, course_id=node.get("course_id"))`. The legacy delta block sits unchanged under `else:`.
- `backend/routes/flashcards.py::_fsrs_advance(row, fsrs_rating, now) -> dict` — ADAPTER over `next_state(d, s, rating, days_since, *, same_day)` and `interval(FSRS_RETENTION_DEFAULT, S')`. It returns `{fsrs_d, fsrs_s, due_at (ISO), reps + 1, lapses (+1 on Rating.AGAIN)}`.
  - `days_since` is measured from `last_reviewed_at`, clamped at 0, and is 0 when that is null.
  - `same_day` is `now − last_reviewed_at < 1 day` (PKG-03's `_fsrs_after` rule) †.
  - Errors propagate.
- `backend/routes/flashcards.py::_order_due_rows(rows, now) -> list[dict]` — ADAPTER that returns `order_due(rows, now, last_review_key="last_reviewed_at")`, or `[]` for no rows.
- `backend/routes/flashcards.py::_loop_order(rows, now) -> (ordered, due)` — due rows (`due_at <= now`) in `_order_due_rows` order, then rows with a null `fsrs_s` in query order, then the rest by `due_at` ascending. A null `due_at` is never due.
- `backend/routes/flashcards.py::_LEGACY_LIST_COLS`, `::_FSRS_LIST_COLS` (`",fsrs_d,fsrs_s,due_at,reps,lapses"`) and `::_ONE_DAY`.
- `GET /api/flashcards/user/{user_id}?due_only=true|false` — the loop path returns only the due bucket when true; the legacy path ignores the parameter. The loop-path response key `due_count` is `len(due)`.
- `POST /api/flashcards/rate` — loop-path response keys `due_at` (ISO, the same string that was written) and `fsrs_rating` (int). A loop-path rating outside `{1, 2, 3}` is a 422 with detail `"rating must be one of 1, 2, 3"`.
- Columns `flashcards.fsrs_d double precision`, `fsrs_s double precision`, `due_at timestamptz`, `reps int NOT NULL DEFAULT 0` and `lapses int NOT NULL DEFAULT 0`, plus index `flashcards_due_idx (user_id, due_at)`. Migration: `backend/db/migrations/20260927035346_learning_flashcards_fsrs.sql`, the spec §4 DDL verbatim.
- `backend/learning/params.py::FLASHCARD_RATING_TO_FSRS: dict[int, int] = {1: 1, 2: 2, 3: 3}` † (§13 A6).
- `backend/tests/test_learning_loop_invariants.py::ROUTE_GRAPH_CALLERS`, `::_GRAPH_WRITE` — the widened `test_inv_01_single_graph_writer` (PKG-03 reopen `2eed297`).
- `backend/tests/test_learning_evidence_apply.py::SANCTIONED_EVIDENCE_CALLERS = {("routes/quiz.py", "submit_quiz")}`, `::LOOP_GATE_LOCAL = "loop_on"`, `::_gated_evidence_calls(source) -> [(line, def name)]`, and `::test_gated_evidence_call_detector` (10 cases). All four come from PKG-03 reopen `4c51f62`, and PKG-05 deletes them together with `test_no_production_caller_passes_evidence_yet`.
- Tests:
  - `backend/tests/test_learning_flashcards_fsrs.py` has 32 tests: `TestMigration` 8, `TestRateCard` 16 and `TestListFlashcards` 8.
  - `backend/tests/test_quiz_scoring_e.py::TestLearningLoopEvidencePath` has 8.

## Constants chosen

- `FLASHCARD_RATING_TO_FSRS = {1: 1, 2: 2, 3: 3}` † — UI forgot → Again, hard → Hard, easy → Good. The values are `learning.fsrs.Rating.AGAIN/HARD/GOOD`, pinned by `test_map_values_are_pkg02_rating_grades`. `params.py` holds plain ints because it cannot import `learning.fsrs`, which imports it. Spec §3.2 has no flashcard-UI row, and Easy(4) is never emitted in v1. §13 A6 records the value.
- `FSRS_RETENTION_DEFAULT` (spec §3.2, 0.90, PKG-02) is used unconditionally for flashcard `due_at`.
- `REVIEW_ORDER_THRESHOLD` (spec §3.2, 0.33) is cited only; `order_due` applies it.
- No numeric literal from the prompt's Named-constants table appears in route code (acceptance 8: the added route lines contain none of `0.03|0.02|0.09|0.9|0.33`).

## Deviations from spec

- Branch cut from `main` → `feat/learning-loop-11-quiz-flashcards` cut from `feat/learning-loop-03-evidence-state` HEAD `a1a416b`. PKG-04..10 do not exist yet, and PKG-11 ran in parallel with PKG-03's last fix round and a plan-amendment pass → session override (the PKG-00 stacked-branch ledger line).
- Commit trailer `Claude Fable 5.1` → `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` → session override.
- Task 7 `git push` / `gh pr create` → not run → session override; the last step is the hand-off + ledger commit.
- State-of-the-world rows:
  - `tests/test_learning_gate.py → 11 passed` → observed `13 passed`, PKG-00's recorded arithmetic slip.
  - Invariants `4 passed, 8 skipped` → observed `7 passed, 6 skipped` (inv_01/03/13 are real).
  - `ls backend/db/migrations | tail -1` prints `README.md`. The latest migration is `20260927024349_learning_learner_state.sql`, and this package's `20260927035346_…` sorts after it.
  - None of these is a red row.
- Full suite `pytest tests/ -q` (SoW `-q -x`) → run with `-p no:cacheprovider --ignore=tests/evals --ignore=tests/test_docling_integration.py --ignore=tests/test_ocr_pipeline.py --ignore=tests/test_extraction_backends.py`, because the OCR stack is not installed (session override; CI's ignore set).
  - N₀ at `a1a416b` is `3262 passed, 141 skipped` (clean re-run in a detached clone; see Known gaps for the first, contaminated run).
  - After PKG-11 it is `3312 passed, 141 skipped`: +32 flashcards_fsrs, +8 scoring_e, +10 PKG-03 detector cases. Zero failures, no new skips.
- Task 1 Step 5/6 (HANDOFF-03 Post-hoc line and ledger `03 | reopened` row in the reopen commit, with its own SHA) → the reopen commit `2eed297` carries the test change only, and the Post-hoc line and ledger row land in the hand-off commit with the real SHA → a commit cannot name its own SHA; PKG-02 and PKG-03 recorded their reopens the same way.
- A second PKG-03 reopen that the prompt does not list (`4c51f62`, `backend/tests/test_learning_evidence_apply.py`, which is outside the Files lists) → two tests needed it:
  - `test_no_production_caller_passes_evidence_yet` fails on any `{"evidence": …}` payload by design. PKG-03 wrote it for PKG-05 to delete, but PKG-11 lands first in this run. It now excuses exactly the calls `_gated_evidence_calls` finds: a pure-evidence dict literal in the body (not the else) of an `if loop_on:` inside `routes/quiz.py::submit_quiz`. A 10-case detector covers it. It was mutation-checked: `if loop_on or True:` fails the scan.
  - `test_fsrs_importers_are_sanctioned` pinned the `learning.fsrs` importer set to `{services/graph_service.py}`. It now admits `routes/flashcards.py`, which HANDOFF-03 Known gaps asked PKG-11 to do.
  - Neither test was renamed, skipped or deleted. Acceptance 9's path list gains this file.
- §Interfaces consumed (assumed) → adapted to HANDOFF-02/03, in the named adapters and their test stubs only:
  - `next_state(d, s, rating, days_since, *, same_day=False, mc_unassisted=False)` → `_fsrs_advance` passes `same_day=(now − last_reviewed_at < 1 day)`, PKG-03's `_fsrs_after` rule and py-fsrs's `(review − last).days < 1`. Without it, a second rating of a card the same day ran `S_recall`/`S_lapse` at R ≈ 1 instead of spec §3.2's `S_same_day` †. `mc_unassisted` is left at False, because a flashcard is not an MC check. The prompt's positional assertions are unchanged, and `ns.call_args.kwargs == {"same_day": …}` is added.
  - `order_due(items, now, *, stability_key="fsrs_s", last_review_key="fsrs_last_review_at")` → `_order_due_rows` passes `last_review_key="last_reviewed_at"` (HANDOFF-02 consumer line). The prompt's list-test stub lambda gains `**kw`, and the ordering test asserts the kwarg.
  - `learning.fsrs.Rating` exists → the lapse test is `fsrs_rating == Rating.AGAIN` instead of `min(FLASHCARD_RATING_TO_FSRS.values())`. The params map keeps literals, as explained under Constants chosen.
  - `apply_graph_update`'s evidence path returns `{"concept", "before", "after"}` per applied evidence (HANDOFF-03), which is the prompt's assumed shape, so no adaptation was needed.
- Test counts: acceptance 1 expected `55 (26 + 29)` → observed `62 (32 + 30)`. The additions:
  - `TestRateCard` gains same-day branch, "an FSRS failure is not swallowed into a legacy write", achievement dispatch on the loop path, gate evaluated once per rating, and map values == `fsrs.Rating`.
  - `TestListFlashcards` gains "real `order_due` through the adapter ranks by distance from the threshold".
  - `TestLearningLoopEvidencePath` gains "the route's dicts validate as PKG-03 `Evidence` (unassisted, rung 0, weight 1.0, no confidence)".
  - The ledger's "tests added" is therefore 50, not 33.
- Task 2 test module → imports arrive with the task that first uses them (`datetime`/`MagicMock`/`patch` in Task 4), because ruff F401 fails a module that imports them unused in Task 2. `test_prefix_is_a_utc_timestamp` asserts that the glob is non-empty before indexing, so the red run reads "no migration" rather than `IndexError`.
- Task 5 Step 2 expected every `test_gate_on_*` list test to fail before the implementation → `test_gate_on_response_rows_carry_the_fsrs_columns` already passed, because the mocked rows carry every key whatever the select string is. `test_gate_on_selects_fsrs_columns_with_the_same_query` is the real pin. Kept as written.
- Acceptance 9 / self-check 6 `git diff --stat main...HEAD` → measured as `git diff --stat a1a416b..HEAD` → stacked run. The paths are the prompt's list, plus `backend/tests/test_learning_evidence_apply.py` (the second reopen above).
- Acceptance 11 / self-check 5 (the E2E cycle under the lock) → not run; needs local Supabase stack (supabase start) → there is no supabase CLI, podman or docker on the executing machine. `grep -rn "learning_loop_beta\|LEARNING_LOOP_ENABLED" backend/db/seed_local_rich.py scripts/e2e-up.sh .github/workflows/e2e.yml` has no hits, so the stack cannot enable the loop. `git diff a1a416b..HEAD -- backend/services/quiz_config.py frontend/e2e backend/db/seed_local_rich.py backend/agents backend/services/graph_service.py` is empty. The legacy payload is pinned by `test_gate_off_is_the_legacy_delta_path` and the unchanged `TestSubmitQuizMasteryWrite`.

## Known gaps

- (a) Flashcards ignore `FSRS_RETENTION_EXAM` and `FSRS_RETENTION_LARGE_SET`: `due_at` always uses `FSRS_RETENTION_DEFAULT`. PKG-12 owns retention selection.
- (b) A never-rated card is not "due" under `due_only`; its `due_at` is null. PKG-12 decides whether never-reviewed cards count (HANDOFF-02: they have R = 1.0 and sort last in `order_due`).
- (c) A boolean `due_only` is ignored when the gate is false, so the legacy path's queries and response stay byte-identical. It is a typed parameter (`due_only: bool = False`, plan Behaviour 1), so FastAPI validates it before the handler runs on both paths: `?due_only=<not a bool>` is now a 422 (`bool_parsing`, `loc ["query","due_only"]`) where the pre-series route ignored the unknown parameter and answered 200. No client sends it today. Pinned by `test_a_non_boolean_due_only_is_a_422_on_both_paths`.
- (d) Flashcards have no successive-relearning state machine (`SR_*`, PKG-12).
- (e) Same-session quiz re-checks are not weighted. `same_session_recheck` stays at its default, and PKG-03's in-call detection needs a `session_id`, which the quiz does not have.
- (f) `Study.tsx` does not yet show `due_count` or rely on the due-first order (PKG-13); it renders the API's order, which is now due-first for beta users.
- Needs local Supabase stack (supabase start): apply `20260927035346_learning_flashcards_fsrs.sql` with `python -m db.migrate` (and replay from empty on PG15), then run the E2E cycle under the lock: `quiz.spec.ts`, `quiz-journeys`, `quiz-errors`, `quiz-integration`, `study-semester` and `study-recent-guides`, plus `python -m e2e_oracles`. Here it is proven only by hermetic tests.
- Deploy order: apply the migration BEFORE any beta user has the loop on. Before the migration, the loop-path list select fails with `column … does not exist`, and `get_flashcards`'s existing degrade (a message containing "does not exist" becomes `{"flashcards": []}`) would silently show that user an EMPTY deck. `rate_card` would 500 instead. The legacy path never names the new columns.
- `days_since` for FSRS is measured from `last_reviewed_at`, which the legacy path also writes. If a user leaves the beta, rates cards on the legacy path and rejoins, elapsed time is measured from the last legacy rating, and those legacy ratings never advanced FSRS state.
- Corrupt stored FSRS state (`fsrs_s` ≤ 0 or NaN, `fsrs_d` outside [1, 10]) raises in `order_due`/`next_state`, as PKG-02/03 intend. That surfaces as a 500 on rate and on list, and it is never swallowed.
- On the loop path a quiz writes one evidence per question on the same node, so `apply_graph_update` bumps `graph_nodes.times_studied` and journals one `node_mastery_events` row per question (a 5-question quiz gives +5 and 5 rows; the legacy path gives +1 and 1 row). That is PKG-03 behaviour, reported here because this package is its first caller.
- `submit_quiz` evaluates the gate before the atomic `completed_at` claim (the prompt's placement), so with the flag on, a 409 replay costs one `user_settings` read.
- No E2E journey covers the loop path (PKG-13).
- The first full-suite run at the base was contaminated. It ran while this package's Task 3 edit landed, and `test_no_production_caller_passes_evidence_yet` read the edited `routes/quiz.py` with the pre-reopen test module, giving `3261 passed, 1 failed, 141 skipped`. The clean re-run at `a1a416b` in a detached clone is the N₀ above. It is not a flake.
- Evals: not run. No agent prompt or tool description changed (self-check 4).
- Flakes observed: none.

## Verify commands

```
cd backend && venv/bin/python -m pytest tests/test_learning_flashcards_fsrs.py tests/test_quiz_scoring_e.py -q → all passed
ls backend/db/migrations/*_learning_flashcards_fsrs.sql                                          → 1 file
grep -c "learning_loop_active" backend/routes/quiz.py backend/routes/flashcards.py               → ≥ 1 each
```

(Observed at hand-off: `62 passed`, `backend/db/migrations/20260927035346_learning_flashcards_fsrs.sql`, `backend/routes/quiz.py:2` / `backend/routes/flashcards.py:3`.)

## For PKG-14 (cutover)

`frontend/e2e/quiz.spec.ts:56–57` (`EXPECTED_DELTA = masteryAfter(0, QUIZ_LENGTH, QUIZ_LENGTH)`, the `+0.09` pin), `frontend/e2e/support/quiz.ts:58` (`masteryAfter`) and `backend/tests/test_quiz_scoring_e.py::TestMasteryModelSeam` are LEGACY-PATH pins. They hold today because the seeded student is opted out. At cutover (spec §11) the seeded student moves to the loop path, `mastery_after` is deleted, and the pin becomes the BKT posterior the function-mode constants produce for 3/3 `mc` correct from `SEEDED_MASTERY` — recompute it from `learning.bkt` with the `mc` channel, do not hard-code. Update the spec, the support helper and the backend test in the same commit as the deletion (docs/quiz-mastery-model.md §Constraint).

Also at cutover:
- `submit_quiz`'s `else:` branch, `_mastery_span`'s legacy twin (the `for change in applied` reduction), the `quiz_*` event-type bucketing and the `mastery_after` import go.
- `rate_card`'s and `get_flashcards`'s `loop_on` branches become unconditional.
- `test_gate_off_*` in `test_learning_flashcards_fsrs.py` and `TestLearningLoopEvidencePath::test_gate_off_is_the_legacy_delta_path` are deleted in the same commit.
- Note that on the loop path the first evidence starts from `BKT_L0` (0.35), not the node's legacy `mastery_score` (HANDOFF-03 Known gaps), so the recomputed pin starts from the prior, not from `SEEDED_MASTERY`, unless the seed writes a `learner_state` row.

## Open questions for the series owner

- (1) Should the loop-path `mastery_before`/`mastery_after` shown on the results screen be BKT `p_known` (what PKG-03 returns) or a legacy-scaled display number? Option taken: report what the graph returned. For a node's first evidence, `mastery_before` is the decayed prior (`BKT_L0` = 0.35), not the node's previous `mastery_score`, so a beta user can see "before" fall below the Tree's last number.
- (2) Should PKG-12's review surface reuse `_loop_order` or own its ordering? Option taken: `_loop_order` stays private to `routes/flashcards.py`, and PKG-12 composes `learning.fsrs.order_due` → `budget_select` itself.
- (3) Should `due_only` return 400 when the gate is false instead of being ignored? Option taken: ignored, which keeps the legacy path byte-identical and leaves the frontend nothing to guard.
- (4) Same-day flashcard re-ratings take FSRS's `S_same_day` branch (elapsed < 24 h, PKG-03's rule) †. The alternative is the prompt's 4-argument call, which uses `S_recall`/`S_lapse` at R ≈ 1.

## Post-hoc changes

(Appended by later packages that modified this package's code. Format: `PKG-MM <date>: <what> — commit <sha>`.)
