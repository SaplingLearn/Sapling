# HANDOFF-13 — frontend-e2e

Written by the sessions that executed `PKG-13-frontend-e2e.md` (backend lane, frontend lane, and the review fix round). Read by every later package that depends on 13. Keep every heading, even if the answer is "none".

**Status: built, review fix round done, fresh-DB E2E cycle pending.** Everything is on `feat/learning-loop-13-frontend-e2e` (worktree `~/Projects/sapling-wt-13`, cut from the PKG-10 tip `4da6166d`). The frontend lane, built in parallel in `~/Projects/sapling-wt-13fe`, was merged in at `45b5fdd2`. Its separate hand-off, `HANDOFF-13-frontend-lane.md`, is folded into this file and deleted. The review fix round (2026-09-29) fixed every finding of the three reviews: 1 critical, 6 major and all minors (commits under "Post-hoc changes"). Task 9 is written: the journeys, `support/params.ts`, `support/oracle.ts` and `support/stack.ts`. The hermetic suite, the eval replay, `tsc`, `vitest` and `eslint` are green. **Not yet run:** the flock'd fresh-DB E2E cycle (Playwright + `e2e_oracles`) and the seed round-trip of Task 3 Step 5. The integrator runs both, then merges (CONTINUE.md override 10).

## What changed

**Backend lane.**
- `GET /api/learn/loop/sessions` lists a student's open loop sessions for one course: require_self and the gate's 404, one `sessions` read, newest first, never rate-limited. LoopLearn resumes from this list instead of starting a probe.
- The function-mode seam answers the loop tutor by PHASE on all three tier slots: a hint turn, a feedback turn, and the PKG-07 teach turn for everything else. It reads the phase off THIS run's prompt prefix, never the history.
- The rich seed carries the two build-phase loop users, `rich-user-loop` and `rich-user-capped` (`user_settings.learning_loop_beta = true`, the staff/QA toggle, A14). Each has:
  - a 3-concept prerequisite chain in CS101;
  - 18 shared encrypted check items drafted from an indexed, shared course-material document (course_chunks + contributor ledger, A23/A34).
- The capped user also has today's spend past the novice allowance (read from `config`, re-stamped `now()` on every seed run) and one due flashcard (A26).
- The E2E lane (`scripts/e2e-up.sh`, `.github/workflows/e2e.yml`, `scripts/explore.sh`) exports `LEARNING_LOOP_ENABLED=true` (build phase) and `LEARNING_GATE_TIME_SCALE=0.01` (spec §13 A5).
- A new oracle, `python -m e2e_oracles --check learn_loop [--expect-loop-activity]`, guards the loop's write invariants and ties them to the session documents, so it cannot pass vacuously.
- Two invariants pin the spec↔handler sync (13a) and the staff/QA toggle (13b).

**Frontend lane.**
- `Learn()` probes the loop status (`getLoopStatus` → `GET /review/active`, which answers `{active}` with 200) through `useLoopStatus` and renders `LoopLearn` for `active: true`. `active: false` keeps the legacy `LearnInner` tree byte-for-byte. The probe never blocks: a timeout or an error renders legacy provisionally, and a late or retried `active: true` switches to the loop.
- `LoopLearn` is the loop-path Learn screen:
  - It lists the student's open loop sessions for the course (`GET /sessions`) and resumes the newest, or the one `?resume=` names. That session may sit in another course or past the list limit.
  - A `?resume=` id that is not an open loop session opens read-only.
  - A failed list shows a retry state, never a probe.
  - A new session and its probe start only when none is open, or on "New session" (which closes the open session it leaves).
- The phase (probe → plan → teach ⇄ check → feedback → close) is server-driven through a pure reducer.
- The attempt box submits only to `/check/answer/stream` (A16). A graded submission closes the item. A submission that does not settle re-reads `GET /status`.
- Streamed turns honour `retract` (A46) and render `done.reply` as the settled text.
- The budget pause banner renders from a 429 body or a hard `budget` event, with the A39 session-capped copy. It lifts at its `reset_at`.
- The close renders the A60 record, with the self-evaluation as a reflection prompt only. A 409 "this session is closed" from any teaching route moves the screen to the stored close.
- `DueQueue` got its launch polish: the budget banner, "All caught up", no stale item, and a summary re-read with every load.
- No model toggle, and no `model_pref` anywhere on the loop path.

**Task 9.** `frontend/e2e/learn-loop.spec.ts` holds four journeys: the loop walk, reload-resume, the budget cap, and the build-phase legacy split. They assert against the DB, and the loop walk runs the `learn_loop` oracle over its own rows.

## Symbols added

Backend:

- `backend/routes/learn_loop.py::list_open_sessions(request, user_id: str = Query(...), course_id: str = Query(...), resume: str | None = Query(None)) -> dict` — `GET /api/learn/loop/sessions`; `LOOP_OPEN_SESSIONS_LIMIT = 10 †`; helpers `_open_loop_filters(user_id)`, `_open_session_entry(row)`, `_resume_entry(user_id, session_id)`; `_OFFERINGS_UNKNOWN`.
  - Response: `{"sessions": [{"session_id": str, "topic": str, "started_at": str (ISO), "phase": "probe" | "plan" | "teach" | "check" | "feedback"}]}`, newest first (`started_at.desc`), at most 10. With `resume=<id>` the response also carries `"resume": {…the same keys…, "course_id": str} | null`. That is the named session when it is the student's open loop session in ANY course, even past the limit: taken from the list when it is there, else ONE read of that row under the same open-loop filters, with its course from `offering_course_id`. `null` means not an open loop session of this student (a legacy or closed one), or its course cannot be told.
  - Rows are filtered on `user_id = me`, `offering_id in course_offering_ids(course_id)` (the COURSE's offerings; `None` → 503, `[]` → no read), `close_json is.null`, `ended_at is.null`, `loop_state neq.{}` (applied BEFORE the limit, so legacy tutor chats cannot push loop sessions off it), and `mode neq.review`. A document already at `phase: close` is dropped. A lazy session (no row until the first loop write, spec §9) is not listed.
  - `phase` is `_loop_phase(state)` (probe | plan | teach), refined in teach by `_phase_for(state)` (teach | check | feedback).
  - Errors: 404 `{"detail": "learning loop not enabled", …}` when the gate is false (no read); 403 from `require_self`; 422 without `course_id`; 503 `"course offerings unavailable, retry"`. Never 429.
- `GET /status` (PKG-07 reopen) adds `"check": _pose_payload(item) | null`. The pose is sent only while the active item takes answers (phase `check`); no new read, no write. The client restores a resumed check READ-ONLY through it and reconciles an unsettled submission with it.
- `GET /review/active` (PKG-12 reopen) → 200 `{"active": bool}` either way, still 403 for another student; `_gate_value(user_id, request)`.
- `backend/agents/function_handlers_e2e.py`:
  - `E2E_LOOP_PHASE_PATTERNS = {"hint": "the student asked for help with the check item below", "feedback": "the student has just submitted an answer to the check"}` — verbatim fragments of `agents/loop_tutor.py::_PHASE_RULES`.
  - `E2E_LOOP_HINT_TURN` / `E2E_LOOP_HINT_REPLY` (= `render_turn`), `E2E_LOOP_HINT_BODY`, `E2E_LOOP_HINT_QUESTION`; `E2E_LOOP_FEEDBACK_TURN` / `E2E_LOOP_FEEDBACK_REPLY`, `E2E_LOOP_FEEDBACK_BODY`, `E2E_LOOP_FEEDBACK_QUESTION` — structured turns valid at H0 with nothing given; the BODY/QUESTION fields are the model-written parts that reach the student verbatim.
  - `E2E_LOOP_PROBE_PROMPT = "[e2e-loop] Check item: type the e2e grader's correct token to be marked correct."` (every seeded item's plaintext prompt starts with it), `E2E_LOOP_FINAL_ANSWER = "the kilo sentinel phrase"`, `E2E_LOOP_REFERENCE` (closes with `Final answer: the kilo sentinel phrase.`).
  - `_loop_tutor_handler(messages, info)` rewritten: phase from `_last_user_prompt_text(messages)`; registered for `loop_tutor_lite`, `loop_tutor`, `loop_tutor_deep`.
- `backend/db/e2e_handler_constants.py::read_constants(*names) -> tuple[str, ...]` — the handler module's `E2E_*` strings, read from its SOURCE by a structural AST evaluator (literals, `+`, f-strings over earlier constants; anything else raises). It exists so the seed and the oracle never import pydantic-ai/genai. Pinned to the imported module by `tests/test_e2e_handler_constants.py`.
- `backend/services/chunk_ids.py`: `EMBED_OUTPUT_DIM = 768`, `chunk_id(...)`. Both were moved verbatim from `rag_service`, which re-exports them, so `rag_service.chunk_id` and `rag_service._OUTPUT_DIM` are unchanged.
- `backend/db/seed_local_rich.py`: `COURSE_CS_CODE`, `USER_LOOP`, `USER_CAPPED`, `LOOP_USERS`, `ENR_LOOP_CS_S26`, `ENR_CAPPED_CS_S26`, `SEED_LOOP_CONCEPTS`, `SEED_LOOP_FORMATS`, `SEED_LOOP_ITEMS_PER_CONCEPT`, `SEED_CAPPED_SPEND_FACTOR`, `LOOP_NODES` (`(slug, concept_name, notes sentence)`), `LOOP_DOC_ID`, `LOOP_DOC_CATEGORY`, `LOOP_DOC_SHAREABILITY_CONFIDENCE`, `CAPPED_FLASHCARD`, `loop_node_id(user_id, slug)`, `_seed_embedding(text)`, `seed_learning_loop()` (run by `main()` after `seed_sessions()`); `_SUMMARY_ORDER` + `user_settings`, `course_chunks`, `course_chunk_contributors`, `check_items`, `llm_usage`.
- `backend/e2e_oracles/learn_loop.py`:
  - `learn_loop_findings(evidence_pairs, state_rows, leak_count, step_payloads, node_scores)` checks (a) to (d).
  - `learn_loop_activity_findings(sessions, evidence_hashes, step_event_hashes, messages, sentinel, loop_users, expect_activity)` checks (e) to (h):
    - (e) a graded check step has an evidence row for its hash;
    - (f) a served feedback turn has a `zpd.step` event;
    - (g) no decrypted assistant message of a loop session states `E2E_LOOP_FINAL_ANSWER` before that session released an answer (a non-correct grade, or a logged H6). Unknown times fail closed, and the text is never echoed;
    - (h) under `--expect-loop-activity`, "no loop users" and "no graded check step" are findings.
  - Also exports `ORACLE_P_TOLERANCE`.
- `backend/e2e_oracles/gather.py`: `run_learn_loop(args)`, `_learn_loop_activity(conn, step_rows, args, learn_loop)`. `CHECKS["learn_loop"]`; CLI flag `--expect-loop-activity`.
- Tests: `tests/test_learn_loop_sessions.py` (24), `tests/test_learning_seed_loop_user.py` (13), `tests/test_e2e_oracles_learn_loop.py` (30), `tests/test_e2e_handler_constants.py` (9), `tests/test_e2e_function_handlers.py` (+13), `tests/test_learning_loop_invariants.py` (+3: `test_inv_13a_sync_scan_self_test`, `test_inv_13a_spec_constants_match_function_handlers`, `test_inv_13b_seed_opts_in_exactly_the_loop_users`); `tests/test_learn_loop_routes.py` (+3 `/status` pose); `tests/test_learning_review.py` (+1, 1 rewritten: `/review/active`).

Frontend:

- `frontend/src/lib/api.ts`:
  - `ChatResult.leak_redacted?`; `StreamChatHandlers` + `onRetract(reason)`, `onPhase(phase)`, `onCheck(item)`, `onHintOffer(rung)`, `onLearnerState(state)`, `onBudget(notice)`; `consumeChatStream` dispatches `retract`, `phase`, `check`, `hint_offer`, `learner_state`, `budget` (legacy callers pass none of them — `api.stream.test.ts` unchanged and green).
  - Types: `LoopPhase`, `LoopBand`, `LoopFormat`, `LoopOption`, `LoopCheckItem`, `LoopProbeItem`, `LoopProbeNext`, `LoopProbeAnswerResult`, `LoopLearnerState`, `LoopPlanConcept`, `LoopPlan`, `LoopOpenSession`, `LoopResumeSession`, `LoopSessionList`, `LoopSessionStatus`, `LoopBudgetNotice`, `LoopStartResult`, `LoopTurnResult`, `LoopCheckNext`, `LoopHintResponse`, `LoopAttemptResult`, `LoopCloseRecord`, `LoopCloseResponse`, `LoopCheckAnswer`, `LoopBudgetPause`; `LOOP_DEEP_LINK_MODES`.
  - Functions: `budgetPauseOf(err)`, `listLoopSessions(userId, courseId)`, `listLoopSessionsFor(userId, courseId, resumeId) -> {sessions, resume}`, `getLoopSessionStatus(sessionId, userId)`, `startLoopSession(userId, courseId, topic, mode?)` (a mode only when it is one `StartSessionBody` knows), `nextLoopProbe`, `answerLoopProbe`, `getLoopPlan`, `approveLoopPlan`, `streamLoopChat`, `streamLoopCheckAnswer`, `postLoopAttempt`, `nextLoopCheck` (it WRITES: activation), `requestLoopHint`, `requestLoopHintTurn`, `closeLoopSession`. PKG-12's `getLoopStatus` is reused (a 404 from an older backend still reads as inactive).
- `frontend/src/components/learn/loopState.ts`: `LoopUiState` (`phase`, `item`, `learnerState`, `focusNodeId`, `budgetPause`), `LoopUiEvent` (`phase`, `check`, `learner_state`, `budget`, `budget_clear`, `reset`), `initialLoopState()`, `reduceLoopEvent`, `uiPhaseOf`. A `check` event for an item with no known pose never makes a promptless item.
- `frontend/src/components/learn/useLoopStatus.ts`: `useLoopStatus(userId, userReady) -> boolean | null`, `LOOP_STATUS_TIMEOUT_MS`, `LOOP_STATUS_RETRY_MS`.
- `frontend/src/components/learn/LoopLearn.tsx`: `LoopLearn()`.
- `frontend/src/components/learn/BudgetPausedBanner.tsx`: `BudgetPausedBanner({testId, resetAt, sessionCapped?, message, children?})`, `formatResetAt(iso)`, `tutorPauseMessage(resetAt, sessionCapped)`.
- `frontend/src/components/learn/resumeParam.ts`: `readResumeParam` (moved from `screens/Learn.tsx`, which re-exports it).
- `frontend/src/components/CustomSelect.tsx`: `testId?` prop (the trigger's `data-testid`; options `<testId>-option-<value>`).
- `frontend/src/components/screens/Learn.tsx`: `Learn()` branches on `useLoopStatus`; `LoopLearn` sits in the same Suspense boundary as `LearnInner`. Nothing below `Learn()` changed.
- `frontend/src/components/learn/DueQueue.tsx`: `getReviewSummary` re-read with every load (a failure keeps the last one), `review-budget-paused`, `review-empty` copy with no "due later" claim, a failed reload clears the item, `review-next` also while paused.
- `frontend/eslint.config.mjs`: `LoopLearn.tsx`, `BudgetPausedBanner.tsx` in the testid `files` array (`DueQueue.tsx` was there from PKG-12).
- `docs/frontend-testids.md`: the `Learning loop | loop` row, the `### loop` inventory, the `### review` owner line + `review-budget-paused`.
- Testids — `loop`: `loop-phase`, `loop-session-picker`, `loop-session-{sessionId}`, `loop-new-session`, `loop-course-select` (+ `-option-{courseId}`), `loop-sessions-error`, `loop-sessions-retry`, `loop-no-course`, `loop-no-course-link`, `loop-start-error`, `loop-start-retry`, `loop-topic-offer`, `loop-topic-start`, `loop-readonly-transcript`, `loop-readonly-new-session`, `loop-budget-paused`, `loop-budget-study-link`, `loop-no-check-items`, `loop-tree-link`, `loop-rail`, `loop-learner-state`, `loop-probe-item`, `loop-probe-input`, `loop-probe-option-{letter}`, `loop-probe-reason`, `loop-probe-submit`, `loop-probe-idk`, `loop-probe-reference`, `loop-probe-retry`, `loop-probe-next`, `loop-plan-concept-{nodeId}`, `loop-plan-retry`, `loop-plan-approve`, `loop-messages`, `loop-teach-start`, `loop-check-me`, `loop-check-prompt`, `loop-attempt-input`, `loop-attempt-option-{letter}`, `loop-attempt-reason`, `loop-attempt-submit`, `loop-attempt-idk`, `loop-hint-button`, `loop-hint-denied`, `loop-hint-reply`, `loop-continue`, `loop-close-button`, `loop-close-summary`, `loop-close-self-eval`, `loop-close-if-then`, `loop-close-done`, `loop-close-study-link`. `review`: `review-budget-paused`. (`loop-hint-offer` was removed; see Deviations.)
- E2E: `frontend/e2e/learn-loop.spec.ts` (4 tests), `frontend/e2e/support/params.ts::learningParams(names)`, `frontend/e2e/support/oracle.ts::runOracle(args) -> {code, count, findings, stderr}`, `frontend/e2e/support/stack.ts::USER_LOOP`, `USER_CAPPED`.
- Tests: `src/lib/api.loop.test.ts` (31), `src/components/learn/loopState.test.ts` (15), `src/components/learn/LoopLearn.test.tsx` (63), `src/components/learn/useLoopStatus.test.tsx` (6), `src/components/learn/LearnBranch.test.tsx` (3), `src/components/learn/DueQueue.test.tsx` (+9).

Seeded ids the frontend and the journeys use:

| what | value |
|---|---|
| loop user ("Lou Loop") | `rich-user-loop` — enrolled in `rich-off-cs101-s26` only (enrollment `rich-enr-loop-cs101-s26`) |
| capped user ("Casey Cap") | `rich-user-capped` — enrolled in `rich-off-cs101-s26` only (`rich-enr-capped-cs101-s26`) |
| course (abstract `course_id`, what `/sessions` and the review routes take) | `rich-course-cs101` ("Introduction to Computer Science", code `CS101`) |
| graph nodes (per user, `mastery_score` 0.0, no `learner_state`) | `rich-node-loop-{binary,bitwise,twos}`, `rich-node-capped-{binary,bitwise,twos}` — "Binary Numbers" → "Bitwise Operators" → "Two's Complement", `prerequisite` edges, source = prerequisite |
| check items (course assets, shared) | `rich-check-{binary,bitwise,twos}-{free,teachback}-d{1,2,3}` — 18; concept keys `binary numbers`, `bitwise operators`, `two's complement` |
| shared document / chunks | `rich-doc-loop-cs-notes` (uploader `rich-user-loop`, course_material 0.9, `indexed`), 3 `course_chunks` rows (course `CS101`, shared) |
| capped spend | `llm_usage` `rich-usage-capped-1` (task `loop_tutor`, `cost_usd = STUDENT_DAILY_BUDGET_USD × BUDGET_NOVICE_MULTIPLIER × 1.5` = 0.75 at the defaults, `created_at` re-stamped now on every seed run — an upsert) |
| capped due card | `flashcards` `rich-fc-capped-1` ("What is a bit?" / "A binary digit: 0 or 1.", `due_at` = seed time − 1 day) |

The E2E grader grades an answer correct when it contains `E2E_GRADER_CORRECT_TOKEN` (`"E2E_GRADER_CORRECT"`); any other text is `not_yet`; `E2E_GRADER_WRONG_REASON_TOKEN` in a wrong answer matches the item's first wrong reason (`wrong_token`, PKG-10).

Route → client mapping (verified on disk; where it differs from the prompt's "expected contract" table, the disk wins):

| route | body / query | response the UI reads | client |
|---|---|---|---|
| `GET /review/active` | `user_id` | 200 `{active: bool}` (PKG-13 reopen of PKG-12; 403 another student) | `getLoopStatus` → `useLoopStatus` |
| `GET /sessions` | `user_id`, `course_id`, `resume?` | `sessions[…]`, `resume {…, course_id} \| null` | `listLoopSessionsFor` |
| `GET /status` | `user_id`, `session_id` | `loop_phase (probe\|plan\|teach\|close)`, `phase (teach\|check\|feedback)`, `check` pose \| null, `band`, `ceiling`, `active_question_hash`, `items`, `rung`, `attempts` | `getLoopSessionStatus` (resume restore; submission reconcile) |
| `POST /start-session` | `{user_id, topic, course_id, mode?}` — no `model_pref` | `session_id, initial_message` (+ `budget{level, reset_at, scope, session_capped}` at the hard level: template opener, never a 429, A27) | `startLoopSession` |
| `POST /probe/next` | `{session_id, user_id}` | `{done:false, check_item_id, question_hash, node_id, format, difficulty, prompt, options}` \| `{done:true, phase:"plan", no_check_items?}` | `nextLoopProbe` |
| `POST /probe/answer` | `{session_id, user_id, question_hash, answer \| (option, reason) \| idk}` | `{graded:true, correct, p_known, probe_done, novice_floor, reference_answer?}` \| `{graded:false, unavailable \| refused \| recorded:false}` | `answerLoopProbe` |
| `GET /plan` | `session_id`, `user_id` | `{concepts:[{node_id, concept_name, kind, p_known}], order}` \| `{concepts:[], empty:true, phase:"teach"}` | `getLoopPlan` |
| `POST /plan/approve` | `{session_id, user_id, concept_ids}` | `{phase:"teach", concept_ids}` — no turn is run | `approveLoopPlan` |
| `POST /chat/stream` | `{session_id, user_id, message}` | SSE `phase, check{question_hash, format, difficulty}, hint_offer, learner_state, budget, retract, token, graph_update, error, done{reply, leak_redacted, phase, check, budget}`; 409 `finish the probe first` / `finish the plan first` / `this session is closed` / `session close in progress` | `streamLoopChat` |
| `POST /check/next` | `{session_id, user_id}` | `phase, check \| null, plan_done?` (it activates — writes) | `nextLoopCheck` ("Check me" only) |
| `POST /check/answer/stream` | `{session_id, user_id, question_hash, answer \| (option, reason), idk}` | as `/chat/stream`; `done` adds `graded, verdict, unavailable, answer_released, refused`; 409 `already graded` | `streamLoopCheckAnswer` |
| `POST /step/attempt` | `{session_id, user_id, question_hash, attempt_text}` | `{genuine, counted, attempts, independent_s}` | `postLoopAttempt` |
| `POST /hint` | `{session_id, user_id, question_hash}` | `{rung, intent}` \| `{denied}` | `requestLoopHint` |
| `POST /action` | `{session_id, user_id, action_type: "hint"}` | JSON turn (`reply, phase, budget`) | `requestLoopHintTurn` |
| `POST /close` | `{session_id, user_id}` | `{close: {summary, self_eval, if_then, concepts, misconceptions, model_written}, model_written, close_phase}` — idempotent; 409 `session close in progress` / `a check is being graded; close again in a moment` | `closeLoopSession` |
| `GET /review/next`, `POST /review/answer`, `GET /review/summary` (PKG-12) | unchanged | + `summary.paused`, `summary.due` | DueQueue |
| `GET /api/learn/sessions/{id}/resume` (legacy) | — | `session.topic`, `messages[{id, role, content}]` | `resumeSession` |
| any 429 | — | `detail == "ai budget reached"`, `reset_at`, `scope`, `session_capped` + `Retry-After` | `budgetPauseOf` |

## Constants chosen

- `SEED_LOOP_CONCEPTS = 3` †, `SEED_LOOP_FORMATS = ("free", "teachback")` †, `SEED_LOOP_ITEMS_PER_CONCEPT = 6` † (= formats × `CHECK_ITEM_DIFFICULTIES`; pinned), `SEED_CAPPED_SPEND_FACTOR = 1.5` †, `LOOP_DOC_SHAREABILITY_CONFIDENCE = 0.9` † (above `chunk_visibility.MIN_SHARE_CONFIDENCE = 0.6`) — `db/seed_local_rich.py`.
- `LOOP_OPEN_SESSIONS_LIMIT = 10` † — `routes/learn_loop.py`.
- `ORACLE_P_TOLERANCE = 1e-9` † — `e2e_oracles/learn_loop.py`; `_RELEASE_RUNG = 6` (H6).
- Lane: `LEARNING_LOOP_ENABLED=true` (build phase; PKG-14b removes it), `LEARNING_GATE_TIME_SCALE=0.01` (spec §13 A5, the value the spec names).
- Journeys: `LOOP_JOURNEY_TIMEOUT_MS = 240_000` †, `GATE_POLL_MARGIN_MS = 15_000` †, `DB_POLL_TIMEOUT_MS = 5_000` (house). The hint poll's bound is the UNSCALED `GATE_INDEPENDENT_MIN_S_NOVICE` (90 s) + margin, so it is honest whatever the lane scale; the gate actually waits 90 × 0.01 = 0.9 s in the lane.
- `LOOP_STATUS_TIMEOUT_MS = 2_500` †, `LOOP_STATUS_RETRY_MS = [2_000, 5_000, 15_000]` † — `useLoopStatus.ts`.
- `RAIL_WIDTH = 300` †, `RAIL_GRAPH_HEIGHT = 240` †, `CONTINUE_MESSAGE = "Let's continue."` †, `MAX_TIMER_MS = 2^31 − 1` (a pause whose reset is further out is never armed early) — `LoopLearn.tsx`.
- Copy (not tunables): `NO_CHECK_ITEMS_COPY`, `PLAN_DONE_COPY` (both verbatim from the prompt), `NO_ITEM_COPY`, `PROBE_UNAVAILABLE_COPY` (verbatim), `PROBE_REFUSED_COPY`, `CLOSED_ELSEWHERE_COPY`, `HINT_DENIED_COPY` (one line per `/hint` denial reason), `CLOSE_RETRY_COPY` (the two A60 409 details), `tutorPauseMessage` (A39 session copy / daily copy / "for now" when `reset_at` is null), DueQueue's `answerPauseMessage` / `pausedConceptsMessage` (the prompt's copy).

## Deviations from spec

Backend lane:
- Prompt Task 3: every seeded item's `reference_answer` = `final_answer` = the grader's correct token → the reference is `E2E_LOOP_REFERENCE` and the final answer `E2E_LOOP_FINAL_ANSWER` (a phrase copied verbatim from it, absent from the prompt, A34), and neither the prompt nor the reference holds the token → the E2E grader grades on the token ANYWHERE in its message, which quotes the item's prompt and reference (`agents/grader.py::build_grader_message`); a token there would grade every answer — a wrong one, an idk — correct, so the journeys could never exercise `not_yet`, the probe's `reference_answer`, or a misconception. Pinned by `test_loop_constants_do_not_state_a_seeded_answer` and the seed test.
- Prompt Task 2: `E2E_LOOP_HINT_REPLY` / `E2E_LOOP_FEEDBACK_REPLY` as bare strings → structured turns (`*_TURN`, the `*_REPLY` names their `render_turn`), returned as the turn's JSON → spec §13 A46: the loop tutor's output is `LoopTurnOut` via `PromptedOutput`; a bare string fails validation. The journeys assert the `*_BODY` / `*_QUESTION` fields (the model-written parts that survive at H0/H1, where the key idea comes from code, `LOW_RUNG_KEY_IDEAS`).
- Prompt Task 2: phase detection "scans every text part of the message history" → it reads only THIS run's user prompt (`_last_user_prompt_text`) → the history carries earlier turns' prefixes; pinned by `test_loop_tutor_handler_reads_this_runs_prompt_not_the_history`. The prompt's pattern test is kept and strengthened: each pattern appears in its own phase's REAL prefix, in no other phase's, and not in the system prompt.
- Self-check 7 expects exactly four new `E2E_*` names → twelve (`E2E_LOOP_{FEEDBACK_BODY, FEEDBACK_QUESTION, FEEDBACK_REPLY, FEEDBACK_TURN, FINAL_ANSWER, HINT_BODY, HINT_QUESTION, HINT_REPLY, HINT_TURN, PHASE_PATTERNS, PROBE_PROMPT, REFERENCE}`); nothing removed or renamed → the deviations above.
- CONTINUE §4.4 PKG-13 note ("seed indexed shared chunks") → the seed adds `rich-doc-loop-cs-notes` (course_material, `indexed`, uploader consents via `share_class_context: true` on the same `user_settings` row as the toggle) and one shared `course_chunks` row per concept exactly as `document_indexing` writes them (id = `chunk_id(course_code, plaintext)`, `chunk_text` encrypted after hashing, a deterministic unit 768-d embedding, a `course_chunk_contributors` row); every item cites its chunk and the document → A23.
- Invariant 29 (PKG-07) flagged `db/seed_local_rich.py` → `CHECK_ITEM_WRITERS` gains it → the seed WRITES both through `db/seed_helpers` and reads no chunk back (pinned).
- Prompt Behaviour 13 / Task 4: `phase = close_phase or _phase_for(loop_state)` → `_phase_for(state) if _loop_phase(state) == "teach" else _loop_phase(state)`, and a document at `phase: close` is dropped → `_phase_for` knows only teach/check/feedback; PKG-08's `_loop_phase` carries probe/plan/close. `close_phase` is not read at all: `store_close` writes it WITH `close_json`, so an open row never has one (fix round). The gate is PKG-07's `_gate`.
- Prompt Behaviour 13: `offering_ids = user_offering_ids_for_course(user_id, course_id)` → `course_offering_ids(course_id)` (fix round, CRITICAL): loop sessions are stamped with `resolve_offering(course, create=True)` — the current term — and the enrollment keyspace diverges at every term rollover (#553/#529), so a reload after a rollover listed nothing and started a new probe. Ownership is the `user_id` filter; unknown offerings are a 503, never `[]`. `loop_state=neq.{}` (the column is `NOT NULL DEFAULT '{}'`, so `not.is.null` would be vacuous) keeps legacy chats out before the limit.
- Prompt Behaviour 13 names one route with one read → `resume=<id>` adds at most one more read (fix round: a deep link to another course's or a past-the-limit session opened read-only).
- `tests/test_learn_loop_routes.py` (outside the Files lists): `NO_MODEL_ROUTES += "/sessions"` and the `/status` pose tests (PKG-07 reopen).
- Prompt Task 8 (d) compares `mastery_score` with the raw `learner_state.p_known` → the gatherer compares with the belief AT THE ROW'S LAST WRITE (`decayed_p(p_known, updated_at − last_evidence_at, fsrs_s)`), on every node with a state row (a one-hop propagation stores against the kept decay anchor). `bool`/NaN payload values are findings.
- Prompt Task 8 / Behaviour 12 (four table-wide checks) → plus (e)–(h) and `--expect-loop-activity` (fix round): the four checks pass on an empty stack, and the fixtures' per-test truncate leaves the post-suite oracle an idle stack. The loop journey runs the oracle over its own rows.
- Spec §13 A5 over the prompt's Named constants → the lane exports `LEARNING_GATE_TIME_SCALE=0.01`; the prompt's Open question on a lane gate override is answered by the spec.
- `GET /review/active` answers 200 `{active: false}` when the gate is off (PKG-12 reopen; spec §13 A78) → spec §7's "every loop route 404s" keeps holding for every other route; the probe's job is to answer the gate, and the 404 logged an `error.4xx` per legacy visit.
- Seed performance (fix round): the loop step no longer imports `agents.function_handlers_e2e` or `services.rag_service` (≈ 2.4 s per Playwright test, since the seed runs before every test) → `db/e2e_handler_constants.py` (AST read) and `services/chunk_ids.py` (moved from `rag_service`, re-exported). Both files are outside the Files lists.
- Hermetic suite: the session override's command (CI's ignore set), not `pytest tests/ -q` (acceptance 7 corrected below).

Frontend lane:
- `nextLoopProbe(sessionId, userId)`, `getLoopPlan(sessionId, userId)` take no `courseId` → the session's course is `_session_scope`'s (HANDOFF-08).
- `answerLoopProbe` sends `option` (not `selected_option`); `postLoopAttempt` sends `attempt_text` (not `text`).
- Hint: `/hint` returns `{denied}` or `{rung, intent}`; the hint TEXT is a follow-up `POST /action {action_type: "hint"}` JSON turn → PKG-07's design (HANDOFF-07 Open question (e)).
- `/step/attempt` is posted when the student asks for a hint, with the current draft, and again only if the server did not count that exact text — not on the first keystroke † → PKG-07's `/step/attempt` judges the TEXT; a one-character first-keystroke post would never be genuine. The journeys type an attempt before the hint poll.
- `/close` takes no answers and returns the A60 record → `loop-close-self-eval` is the reflection prompt (no input), `loop-close-if-then` the stored plan (rendered only when non-empty), no `loop-close-submit`.
- A resumed session in `check` restores its pose with `GET /status` (read-only; fix round) — the frontend lane used `POST /check/next`, which activates (writes) another item when the open one closed or went stale.
- After `/plan/approve` no turn runs → `loop-teach-start` ("Start with <first plan concept>") sends `Teach me about <name>.` †; "Check me" works at once.
- The last probe answer (`probe_done: true`) goes straight to `GET /plan` (another `/probe/next` would 409 `phase is plan`); `loop-probe-next` added for the reference card.
- A turn's `phase` event of `hint` is shown as `check` (`uiPhaseOf`). A teach turn whose `done.check` activated an item moves `data-phase` to `check` (the document is in check, PKG-07 `_phase_for`; fix round).
- The `check` stream event carries only `{question_hash, format, difficulty}` → the reducer keeps the pose it already has for that hash, and never creates a promptless item (fix round). `loop-learner-state` / `loop-tree-link` follow the LAST `learner_state` event's `node_id`, else the deep link's `?suggest=` / `?topic=` concept.
- An activated pose and a hint turn are appended to the log (the server saves both as assistant rows); while the item is current the log HIDES those rows and the card shows them, so nothing renders twice, live or after a reload (fix round).
- `budgetPauseOf` returns `{resetAt, sessionCapped}` (A39). The reducer's `reset` keeps a daily pause across a session switch and drops a session-capped one. A daily / per-minute pause lifts at its `reset_at` (fix round; owner question below).
- `readResumeParam` moved to `components/learn/resumeParam.ts` (re-exported from `screens/Learn.tsx`).
- `LoopLearn` is wrapped in the same `Suspense` boundary as `LearnInner`.
- Course: the first enrolled course, or `?course=` when enrolled; a `CustomSelect` switcher (`loop-course-select`) with more than one †. No enrolled course → `loop-no-course`.
- Deep links (fix round): `?resume=` is read once at mount and the deep link is dropped from the URL (`router.replace`), so it never re-applies on a switch or reload; `?topic=` is the topic of a new session the boot starts, and with a session already open it is OFFERED (`loop-topic-offer`), never started on its own (a reload must never start a probe, §11.3); `?mode=` is passed to `/start-session` only when `StartSessionBody` knows it; `?suggest=` highlights the concept.
- "New session" closes (`POST /close`, A60) the open session it leaves before starting (fix round: sessions accumulated open); a 409 there starts nothing. The boot's automatic start (no open session) and a course switch close nothing.
- `loop-hint-offer` REMOVED (fix round; PKG-07 open question): PKG-07 sends `hint_offer` on the FEEDBACK turn, after the item closed, so the affordance inside the check card could never render, and a hint then has no item (`/hint` → `no_active_item`). `onHintOffer` stays in the client (harmless); where a novice offer should live is recorded below.
- The dead `leakRedacted` reducer state is removed (fix round): the settled bubble is `done.reply` whatever the flag.
- `Learn()` fails closed to legacy on a probe error or timeout (build phase), but PROVISIONALLY: a retried or late `active: true` switches to the loop (fix round), because the backend delegates the legacy routes for that student (`routes/learn.py::_loop_delegate`).
- DueQueue: "All caught up" makes no "N more due later" claim (fix round: that was a mount-time count of what was due TODAY); the summary is re-read with every load.
- DueQueue 429 copy: "AI tutor paused until <time>. Flashcards and review keep working."; `review-next` also renders while paused.
- Lint: `DueQueue.tsx` carried three `react/no-unescaped-entities` errors from PKG-12; fixed in Task 7. No suppressed code was deleted, so `eslint-suppressions.json` is untouched.

Task 9:
- `support/oracle.ts` (outside the Files list) → the loop journey runs the oracle over its own rows (above).
- Four tests as the prompt names; the loop walk hits a denied hint first (`no_genuine_attempt`), then the gated hint; the resume journey adds a NEWER open legacy chat in the same offering to prove the `neq.{}` filter; the legacy test also asserts `/review/active` answered 200 `{active: false}` and no `error.4xx` row.

## Known gaps

- **Not yet run against the local stack**: the seed round-trip (Task 3 Step 5: first run `check_items created=18`, `user_settings created=2`, `llm_usage created=1`, `course_chunks created=3`; second run `TOTAL created 0`), the four journeys, the `learn_loop` oracle on real rows, and every lane effect of the flag on the legacy specs. The integrator's fresh-DB cycle is the gate.
- **PKG-14b — the flag-off leg.** The lane's `LEARNING_LOOP_ENABLED=true` is process-wide: besides the per-student gate (seeded loop users only), EVERY upload indexes and drafts check items inline (`routes/documents.py::_index_then_check_items`, inline in function mode) and `update_course_context` writes the numbers-only A35 summary for everyone. The legacy upload / course-context specs therefore exercise the loop's branches, and the flag-off path production runs today has NO E2E coverage (hermetic tests only) until PKG-14b's kill-switch lane (spec §11.4). The lane comments say so (e2e-up.sh, explore.sh, e2e.yml, seed).
- `GET /sessions` lists one course's sessions (the picker); a `?resume=` deep link reaches any course.
- A reload before the first probe item is shown can start afresh (lazy session rows).
- The A20 rate limit counts the user's `llm_usage` rows per minute (`LEARN_RATE_LIMIT_PER_MIN = 20`); in function mode every loop turn and grade records a usage row, so a fast journey could 429 — if the cycle sees it, record the counts (prompt "If you get stuck" 3), never raise a cap or seed usage for the loop user.
- A pause with NO `reset_at` (e.g. the "for now" copy) never lifts on a timer — only the next successful tutor turn or a reload clears it (owner question below). With chat disabled while paused, that turn can only come from a submission or the close.
- The hint text is a JSON `/action` turn (not streamed); "Continue" persists `Let's continue.` as a student row; the self-evaluation is not answerable (A60); the rail refreshes on mount, after each graded submission and after the close — not on every `graph_update`.
- "New session" closes the session it leaves, which runs the close model when the session has evidence (A60's normal cost; deterministic at the hard level).

## Verify commands

```
(under the stack lock, E2E_FRESH_DB=1) make e2e-up && (cd frontend && npx playwright test e2e/learn-loop.spec.ts) && (cd backend && venv/bin/python -m e2e_oracles); make e2e-down → 4 learn-loop.spec.ts tests passed (loop journey incl. its --expect-loop-activity oracle run, resume, budget cap, legacy-user split), oracles exit 0
cd frontend && npx tsc --noEmit                                                                   → clean
cd frontend && npx vitest run src/components/learn                                                → all passed
grep -c "E2E_LOOP_" backend/agents/function_handlers_e2e.py                                      → ≥ 3
grep -c '"/sessions"' backend/routes/learn_loop.py                                                → ≥ 1
```

Acceptance 7, corrected (the prompt's bare `pytest tests/ -q` collects the OCR/eval suites CI ignores):

```
cd backend && env -u SAPLING_MODEL_MODE -u SAPLING_FUNCTION_HANDLERS venv/bin/python -m pytest tests/ -q -p no:cacheprovider --ignore=tests/evals --ignore=tests/test_docling_integration.py --ignore=tests/test_ocr_pipeline.py --ignore=tests/test_extraction_backends.py → 0 failed; venv/bin/ruff check . → All checks passed!
```

Observed at the end of the fix round (no stack): hermetic suite **7986 passed, 140 skipped, 0 failed**; `ruff check .` clean; `SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/run_all.py` → 16/16 PASS; `-k "inv_13a or inv_13b"` → 3 passed (13a, its scan self-test, 13b); `npx tsc --noEmit` clean; `npx vitest run` → 112 files, 1255 passed, 2 skipped; `npx eslint` on every changed file → clean.

## Open questions for the series owner

- **Budget pause clearing (fix round, conservative choice made):** a daily or per-minute pause now lifts at its `reset_at` (never earlier; a session cap never). Should a pause with no `reset_at` re-check on a timer (e.g. `Retry-After`), or should the client probe `/review/active`-style for the budget? Until decided it clears only on a successful tutor turn or a reload.
- **Novice hint offer (PKG-07 open question):** `hint_offer` rides the feedback turn, after the item closed, so the UI removed `loop-hint-offer`. Should PKG-07 send the offer while the item is current (the next attempt's pose), or should the offer carry over to the next activated item?
- Whether `Learn()`'s one extra GET for legacy users should be cached in `UserContext` (PKG-14 decides).
- Whether a later follow-up should fold `LoopLearn` into `Learn.tsx` or keep the branch (PKG-14b keeps it: the kill switch needs the legacy tree, spec §11.6).
- Whether `/hint` should return the hint text itself, and whether it should stream (HANDOFF-07 Open question (e)); until then the client makes two calls.
- Should `/step/attempt` get an explicit client trigger other than "Hint" (e.g. on blur of a non-empty draft), so time-to-first-attempt is recorded without a hint request?
- Should the plan screen show the band (the response carries `p_known` but no `band`; the UI never computes one from a literal)?
- Should "New session" ask before closing the session it leaves (it closes silently now)?

## Post-hoc changes

(Appended by later packages that modified this package's code. Format: `PKG-MM <date>: <what> — commit <sha>`.)

- PKG-13 2026-09-29 (review fix round; every finding, no accepted gaps): GET /sessions on the course's offerings, `loop_state=neq.{}` before the limit, no `close_phase` read — 52e490c6; 13a sync scan accepts a trailing period — 9555ceb0; `/status` carries the open item's pose (PKG-07 reopen) — 682e161e; `/review/active` 200 `{active}` (PKG-12 reopen) — 532a84c4; `/sessions?resume=` — dbeed6a1; the `learn_loop` oracle cannot pass vacuously — 4c037543; seed capped past midnight, no SDK import — 4b14472f; `useLoopStatus` timeout/retry/late switch — 99872ad0; LoopLearn fix round — 34d2d079; DueQueue summary — b94e8507; Task 9 journeys — de250b2c; lane comments — 977c3e66.
- PKG-14b 2026-09-30: the legacy-user split is replaced by the two E2E lanes (spec §11.4; `e2e/support/lane.ts::killSwitchLane`, re-exported by `support/fixtures.ts`; global-setup asserts the lane); test_inv_13b rewritten, test_legacy_users_are_not_opted_in retired; the build-phase learn-loop journey became "every student gets the loop by default" + "kill switch restores the legacy Learn screen"; `useLoopStatus` → `{status, retry}` with no fail-open (spec §11.2), `LOOP_STATUS_RETRY_MS` retired — commits dd1a1a9e, fd003ed4
- PKG-14 2026-10-01 (final fix round): `AskPanel` takes `quizAsk {attemptId, questionIndex}` (from `QuizQuestion` and `QuizResults`; `MissedItem.questionIndex`) and sends it as the `quiz_ask` origin on both start routes — with the loop on, the follow-up chat 409'd in the probe (the E2E launch blocker); both quiz Ask journeys assert the help row, the `teach` phase (default lane) and the floored evidence (spec §13 A99) — commit a63b34ca. The rich seed's "Variables and Types" moves 0.92 → 0.96 so `graph.spec.ts` has a mastered node under the launch cuts — commit b220b27e
