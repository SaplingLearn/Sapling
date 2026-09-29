# HANDOFF-13 — frontend-e2e

Written by the session that executed `PKG-13-frontend-e2e.md`. Read by every later package that depends on 13. Keep every heading, even if the answer is "none".

**Status: in progress — two lanes, then Task 9.** The BACKEND lane (Tasks 1–4 and 8) is committed on `feat/learning-loop-13-frontend-e2e` (worktree `~/Projects/sapling-wt-13`, cut from the PKG-10 tip `4da6166d`). The FRONTEND lane (Tasks 5–7) is built in parallel in `~/Projects/sapling-wt-13fe` and appends its sections below. Task 9 (the journeys + the full E2E cycle), Task 10 (the LEDGER rows) and Task 11 run after both lanes merge. Nothing here has run against the local stack yet (the stack lock was held by another cycle): the seed round-trip of Task 3 Step 5 is Task 9's first step.

## What changed

Backend lane. `GET /api/learn/loop/sessions` lists a student's open loop sessions for one course (require_self + the gate's 404, one `sessions` read, newest first, never rate-limited), so LoopLearn resumes instead of starting a probe. The function-mode seam answers the loop tutor by PHASE on all three tier slots — a hint turn, a feedback turn, everything else the PKG-07 teach turn — reading the phase off THIS run's prompt prefix, never the history. The rich seed carries the two build-phase loop users (`rich-user-loop`, `rich-user-capped`; `user_settings.learning_loop_beta = true`, staff/QA toggle, A14), each with a 3-concept prerequisite chain in CS101, 18 shared encrypted check items drafted from an indexed, shared course-material document (course_chunks + contributor ledger, A23/A34), and — for the capped user — today's spend past the novice allowance (from `config`) plus one due flashcard (A26). The E2E lane (`scripts/e2e-up.sh`, `.github/workflows/e2e.yml`, `scripts/explore.sh`) exports `LEARNING_LOOP_ENABLED=true` (build phase) and `LEARNING_GATE_TIME_SCALE=0.01` (spec §13 A5). A new oracle, `python -m e2e_oracles --check learn_loop`, guards the loop's write invariants table-wide. Two invariants pin the spec↔handler sync (13a) and the staff/QA toggle (13b).

## Symbols added

Backend lane:

- `backend/routes/learn_loop.py::list_open_sessions(request, user_id: str = Query(...), course_id: str = Query(...)) -> dict` — `GET /api/learn/loop/sessions`; `LOOP_OPEN_SESSIONS_LIMIT = 10 †`.
  - Response: `{"sessions": [{"session_id": str, "topic": str, "started_at": str (ISO), "phase": "probe" | "plan" | "teach" | "check" | "feedback"}]}`, newest first (`started_at.desc`), at most 10.
  - Rows: `user_id = me`, `offering_id in (user_offering_ids_for_course(me, course_id))`, `close_json is null`, `ended_at is null`, `mode != review`; a row whose `loop_state` is empty, or whose document is already `phase: close`, is dropped. A lazy session (no row until the first loop write, spec §9) is not listed.
  - `phase` = the stored `close_phase` when set, else the phase `GET /status` reports for the document: PKG-08's `_loop_phase` (probe | plan | teach), refined in teach by PKG-07's `_phase_for` (teach | check | feedback).
  - Errors: 404 `{"detail": "learning loop not enabled", …}` when the gate is false (no read); 403 from `require_self`; 422 without `course_id`; `{"sessions": []}` for a course the student is not enrolled in (no `sessions` read). Never 429.
- `backend/agents/function_handlers_e2e.py`:
  - `E2E_LOOP_PHASE_PATTERNS = {"hint": "the student asked for help with the check item below", "feedback": "the student has just submitted an answer to the check"}` — verbatim fragments of `agents/loop_tutor.py::_PHASE_RULES`.
  - `E2E_LOOP_HINT_TURN` / `E2E_LOOP_HINT_REPLY` (= `render_turn`), `E2E_LOOP_FEEDBACK_TURN` / `E2E_LOOP_FEEDBACK_REPLY` — structured turns valid at H0 with nothing given.
  - `E2E_LOOP_PROBE_PROMPT = "[e2e-loop] Check item: type the e2e grader's correct token to be marked correct."` (every seeded item's plaintext prompt starts with it), `E2E_LOOP_FINAL_ANSWER = "the kilo sentinel phrase"`, `E2E_LOOP_REFERENCE` (closes with `Final answer: the kilo sentinel phrase.`).
  - `_loop_tutor_handler(messages, info)` rewritten: phase from `_last_user_prompt_text(messages)`; registered for `loop_tutor_lite`, `loop_tutor`, `loop_tutor_deep`.
- `backend/db/seed_local_rich.py`: `COURSE_CS_CODE`, `USER_LOOP`, `USER_CAPPED`, `LOOP_USERS`, `ENR_LOOP_CS_S26`, `ENR_CAPPED_CS_S26`, `SEED_LOOP_CONCEPTS`, `SEED_LOOP_FORMATS`, `SEED_LOOP_ITEMS_PER_CONCEPT`, `SEED_CAPPED_SPEND_FACTOR`, `LOOP_NODES` (`(slug, concept_name, notes sentence)`), `LOOP_DOC_ID`, `LOOP_DOC_CATEGORY`, `LOOP_DOC_SHAREABILITY_CONFIDENCE`, `CAPPED_FLASHCARD`, `loop_node_id(user_id, slug)`, `_seed_embedding(text)`, `seed_learning_loop()` (run by `main()` after `seed_sessions()`); `_SUMMARY_ORDER` + `user_settings`, `course_chunks`, `course_chunk_contributors`, `check_items`, `llm_usage`.
- `backend/e2e_oracles/learn_loop.py::learn_loop_findings(evidence_pairs, state_rows, leak_count, step_payloads, node_scores) -> list[Finding]`, `ORACLE_P_TOLERANCE`; `backend/e2e_oracles/gather.py::run_learn_loop(args)`; `CHECKS["learn_loop"]`.
- Tests: `tests/test_learn_loop_sessions.py` (15), `tests/test_learning_seed_loop_user.py` (11), `tests/test_e2e_oracles_learn_loop.py` (17), `tests/test_e2e_function_handlers.py` (+13), `tests/test_learning_loop_invariants.py` (+3: `test_inv_13a_sync_scan_self_test`, `test_inv_13a_spec_constants_match_function_handlers`, `test_inv_13b_seed_opts_in_exactly_the_loop_users`).

Seeded ids the frontend and the journeys use:

| what | value |
|---|---|
| loop user ("Lou Loop") | `rich-user-loop` — enrolled in `rich-off-cs101-s26` only (enrollment `rich-enr-loop-cs101-s26`) |
| capped user ("Casey Cap") | `rich-user-capped` — enrolled in `rich-off-cs101-s26` only (`rich-enr-capped-cs101-s26`) |
| course (abstract `course_id`, what `/sessions` and the review routes take) | `rich-course-cs101` ("Introduction to Computer Science", code `CS101`) |
| graph nodes (per user, `mastery_score` 0.0, no `learner_state`) | `rich-node-loop-{binary,bitwise,twos}`, `rich-node-capped-{binary,bitwise,twos}` — "Binary Numbers" → "Bitwise Operators" → "Two's Complement", `prerequisite` edges, source = prerequisite |
| check items (course assets, shared) | `rich-check-{binary,bitwise,twos}-{free,teachback}-d{1,2,3}` — 18; concept keys `binary numbers`, `bitwise operators`, `two's complement` |
| shared document / chunks | `rich-doc-loop-cs-notes` (uploader `rich-user-loop`, course_material 0.9, `indexed`), 3 `course_chunks` rows (course `CS101`, shared) |
| capped spend | `llm_usage` `rich-usage-capped-1` (task `loop_tutor`, `cost_usd = STUDENT_DAILY_BUDGET_USD × BUDGET_NOVICE_MULTIPLIER × 1.5` = 0.75 at the defaults, stamped `now()`) |
| capped due card | `flashcards` `rich-fc-capped-1` ("What is a bit?" / "A binary digit: 0 or 1.", `due_at` = seed time − 1 day) |

The E2E grader grades an answer correct when it contains `E2E_GRADER_CORRECT_TOKEN` (`"E2E_GRADER_CORRECT"`); any other text is `not_yet`; `E2E_GRADER_WRONG_REASON_TOKEN` in a wrong answer matches the item's first wrong reason (`wrong_token`, PKG-10).

Route contract as verified on disk for the frontend lane (backend facts; the frontend lane owns the client mapping it appends below). Where this differs from the prompt's "expected contract" table, the disk wins:

| route | body / query | response the UI reads | notes |
|---|---|---|---|
| `GET /status` | `user_id`, `session_id` (both required) | `active, session_id, loop_phase (probe\|plan\|teach\|close), phase (teach\|check\|feedback), band, ceiling, active_question_hash, items, rung, attempts` | needs a session id; the cheap probe is `GET /review/active` (A72, PKG-12's `getLoopStatus`) |
| `GET /sessions` | `user_id`, `course_id` | see above | PKG-13 |
| `POST /start-session` (+ `/stream`) | `StartSessionBody{user_id, topic, mode, use_shared_context, course_id, model_pref}` — send no `model_pref` | `session_id, initial_message, graph_state` (+ `budget{level, reset_at, scope, session_capped}` at the hard level: template opener, never a 429, A27) | rate-limited |
| `POST /probe/next` | `ProbeNextBody{session_id, user_id}` (no `course_id`) | `{done:false, check_item_id, question_hash, node_id, format, difficulty, prompt, options}` \| `{done:true, phase:"plan"}` \| `{done:true, phase:"plan", no_check_items:true}` | 429 `"too many requests"` past `PROBE_PLAN_READS_PER_MIN` |
| `POST /probe/answer` | `ProbeAnswerBody{session_id, user_id, question_hash, answer, option, reason, idk}` (`option`, not `selected_option`) | `{graded:true, correct, p_known, probe_done, novice_floor, reference_answer?}` \| `{graded:false, unavailable:true}` \| `{graded:false, refused:true}` \| `{graded:false, recorded:false}` | 409s per HANDOFF-08; 429 rate limit |
| `GET /plan` | `session_id`, `user_id` (no `course_id`) | `{concepts:[{node_id, concept_name, kind: review\|new\|sibling, p_known}], order}` \| `{concepts:[], order, empty:true, phase:"teach"}` | |
| `POST /plan/approve` | `PlanApproveBody{session_id, user_id, concept_ids}` | `{phase:"teach", concept_ids}` | no turn is run; the first teach turn is the client's next `/chat/stream` |
| `POST /chat/stream` | `ChatBody{session_id, user_id, message, mode, use_shared_context, model_pref}` — send no `model_pref` | SSE `phase`, `check{question_hash, format, difficulty}`, `hint_offer{rung}`, `learner_state{node_id, p_known, band}`, `budget{level, reset_at, scope, session_capped}`, `retract{reason: retry\|transform}`, `token`, `graph_update`, `error`, `done{reply, leak_redacted, phase, tier, ceiling, learner_state, hint_offer, budget, check}` | 409 `"finish the probe first"` / `"finish the plan first"` / `"this session is closed"` / `"session close in progress"`; at the hard level: `phase`, `budget`, and NO `done` |
| `POST /check/next` | `LoopCheckNextBody{session_id, user_id}` | `phase, check{question_hash, format, difficulty, prompt, options} \| null, plan_done?` | 429 when a novice concept pauses |
| `POST /check/answer/stream` | `LoopCheckAnswerBody{session_id, user_id, question_hash, answer, option, reason, idk}` | SSE as `/chat/stream`; `done` adds `graded, verdict, unavailable, answer_released, refused` | a released feedback reply starts with "The answer: …" from code (A51 m1) |
| `POST /step/attempt` | `LoopAttemptBody{session_id, user_id, question_hash, attempt_text}` (`attempt_text`, not `text`) | `{genuine, counted, attempts, independent_s}` | rate-limited |
| `POST /hint` | `LoopHintBody{session_id, user_id, question_hash}` | `{rung, intent}` \| `{denied: no_active_item \| dwell \| no_genuine_attempt \| ceiling \| h6_gate}` | NOT `{allowed, reason, reply}`: the hint TEXT is the next `POST /action {action_type: "hint"}` turn (JSON only; phase `hint` in the check phase; H2/H4/H6 are deterministic payloads) |
| `POST /action` | `ActionBody{session_id, user_id, action_type, mode, use_shared_context, model_pref}` — send no `model_pref` | JSON turn (`reply`, `phase`, `check`, …) | rate-limited |
| `POST /close` | `CloseBody{session_id, user_id}` | `{close: {summary, self_eval, if_then, concepts:[{node_id, p_before, p_after}], misconceptions, model_written}, model_written, close_phase}` | A60: idempotent; no student answer is stored — `self_eval` is a reflection prompt only; 409 `"session close in progress"` / `"a check is being graded; close again in a moment"` (retry) |
| 429 body (every rate-limited / budget route) | — | `{detail: "ai budget reached", reset_at: iso \| null, scope, session_capped, request_id}` + `Retry-After` | A39: `session_capped: true` → "for this session" copy |

## Constants chosen

- `SEED_LOOP_CONCEPTS = 3` †, `SEED_LOOP_FORMATS = ("free", "teachback")` †, `SEED_LOOP_ITEMS_PER_CONCEPT = 6` † (= formats × `CHECK_ITEM_DIFFICULTIES`; pinned), `SEED_CAPPED_SPEND_FACTOR = 1.5` †, `LOOP_DOC_SHAREABILITY_CONFIDENCE = 0.9` † (above `chunk_visibility.MIN_SHARE_CONFIDENCE = 0.6`) — `db/seed_local_rich.py`.
- `LOOP_OPEN_SESSIONS_LIMIT = 10` † — `routes/learn_loop.py`.
- `ORACLE_P_TOLERANCE = 1e-9` † — `e2e_oracles/learn_loop.py`.
- Lane: `LEARNING_LOOP_ENABLED=true` (build phase; PKG-14b removes it), `LEARNING_GATE_TIME_SCALE=0.01` (spec §13 A5, the value the spec names).
- Task 9 (not yet chosen): `LOOP_JOURNEY_TIMEOUT_MS` †, `GATE_POLL_MARGIN_MS` †, the `GATE_INDEPENDENT_MIN_S` wait (now × 0.01).

## Deviations from spec

- Prompt Task 3: every seeded item's `reference_answer` = `final_answer` = the grader's correct token → the reference is `E2E_LOOP_REFERENCE` and the final answer `E2E_LOOP_FINAL_ANSWER` (a phrase copied verbatim from it, absent from the prompt, A34), and neither the prompt nor the reference holds the token → the E2E grader grades on the token ANYWHERE in its message, which quotes the item's prompt and reference (`agents/grader.py::build_grader_message`); a token there would grade every answer — a wrong one, an idk — correct, so the journeys could never exercise `not_yet`, the probe's `reference_answer`, or a misconception. Pinned by `test_loop_constants_do_not_state_a_seeded_answer` and the seed test.
- Prompt Task 2: `E2E_LOOP_HINT_REPLY` / `E2E_LOOP_FEEDBACK_REPLY` as bare strings returned in a `TextPart` → structured turns (`E2E_LOOP_HINT_TURN` / `E2E_LOOP_FEEDBACK_TURN`, the `*_REPLY` names their `render_turn`), returned as the turn's JSON → spec §13 A46: the loop tutor's output is `LoopTurnOut` via `PromptedOutput`; a bare string fails validation and burns the output retries.
- Prompt Task 2: phase detection "scans every text part of the message history" → it reads only THIS run's user prompt (`_last_user_prompt_text`) → the history carries earlier turns' prefixes, so a teach turn after a hint turn would be answered with the hint reply; pinned by `test_loop_tutor_handler_reads_this_runs_prompt_not_the_history`. The prompt's pattern test (`pattern in loop_tutor.py source`) is kept and strengthened: each pattern appears in its own phase's REAL prefix (`phase_prefix` + `assemble_turn_message`), in no other phase's, and not in the system prompt.
- Self-check 7 expects exactly four new `E2E_*` names → eight: `E2E_LOOP_{FEEDBACK_REPLY, FEEDBACK_TURN, FINAL_ANSWER, HINT_REPLY, HINT_TURN, PHASE_PATTERNS, PROBE_PROMPT, REFERENCE}`; nothing removed or renamed → the two deviations above.
- CONTINUE §4.4 PKG-13 note ("the rich seed has no `course_chunks` … seed indexed shared chunks") → the seed adds `rich-doc-loop-cs-notes` (course_material, `indexed`, uploader consents via `share_class_context: true` on the same `user_settings` row as the toggle) and one shared `course_chunks` row per concept exactly as `document_indexing` writes them (id = `rag_service.chunk_id(course_code, plaintext)`, `chunk_text` encrypted after hashing, a deterministic unit 768-d embedding so `ragstore` sees no NULL embedding, a `course_chunk_contributors` row); every item cites its chunk and the document (`source_chunk_ids`, `source_document_ids`, `document_id`) → A23: items come only from shared course material, and a teach turn's `chunks_for_ids` now reads a real shared row.
- Invariant 29 (PKG-07) flagged `db/seed_local_rich.py` ("reads course_chunks next to source_chunk_ids") → `CHECK_ITEM_WRITERS` gains `db/seed_local_rich.py` → the seed WRITES both through `db/seed_helpers` and reads no chunk back; `test_the_loop_step_writes_through_the_seed_helpers_and_reads_no_chunk_back` pins that `seed_learning_loop` has no select of its own.
- Prompt Behaviour 13 / Task 4: `phase = close_phase or _phase_for(loop_state)` → `close_phase or (_phase_for(state) if _loop_phase(state) == "teach" else _loop_phase(state))`, and a document at `phase: close` is dropped → `_phase_for` knows only teach/check/feedback; PKG-08's `_loop_phase` (the `/status` `loop_phase`) carries probe/plan/close (HANDOFF-08). Filter `mode` via `session_modes.NOT_REVIEW` (the same `neq.review`). The gate is PKG-07's `_gate` (require_self + `learning_loop_for_request`), not the prompt's `learning_loop_active`. No item read, so a withdrawn active item still reports `check` (the UI renders the restored log either way).
- `tests/test_learn_loop_routes.py` (outside the Files lists): `NO_MODEL_ROUTES += "/sessions"` → `test_rate_limit_dependency_on_model_routes_only` pins the router's EXACT route set; no PKG-07 assertion changed.
- Prompt Task 8 (d) compares `mastery_score` with the raw `learner_state.p_known` on evidence-touched nodes → the gatherer compares with the belief AT THE ROW'S LAST WRITE (`learning.bkt.decayed_p(p_known, (updated_at − last_evidence_at), fsrs_s)`), on every node with a state row → a one-hop propagation stores against the node's kept decay anchor (`graph_service._keep_decay_anchor`) while the mirror holds the belief at the write, so the raw comparison reports a false finding (≈1e-6 after a minute) on the first prerequisite a journey propagates into; propagation targets are written beside the mirror too, so they are compared as well. `bool`/NaN payload values are findings (a bool is an int in Python).
- Spec §13 A5 over the prompt's Named constants ("the journey waits `GATE_INDEPENDENT_MIN_S` honestly") → the lane exports `LEARNING_GATE_TIME_SCALE=0.01` in `e2e-up.sh`, `e2e.yml` and `explore.sh` → A5: "the E2E env sets 0.01"; the prompt's Open question on a lane gate override is answered by the spec. Only the loop reads the value.
- `test_inv_13a_spec_constants_match_function_handlers` skips (named reason) while `frontend/e2e/learn-loop.spec.ts` still carries the PKG-00 stub marker → Task 9 replaces the stub; the skip then cannot fire and the test requires the spec to cite at least one `E2E_*` constant. A `test_inv_13a_sync_scan_self_test` pins the scan itself.
- Hermetic suite: the session override's command (CI's ignore set), not `pytest tests/ -q`.

## Known gaps

- Not yet run against the local stack (lock held): the seed round-trip (Task 3 Step 5: first run `check_items created=18`, `user_settings created=2`, `llm_usage created=1`, `course_chunks created=3`; second run `TOTAL created 0`), the `learn_loop` oracle on real rows, and every lane effect of `LEARNING_LOOP_ENABLED=true` / `LEARNING_GATE_TIME_SCALE=0.01` on the legacy specs — Task 9.
- `GET /sessions` lists one course's sessions; the budget banner clears only on the next successful tutor turn or a reload (no client timer); a reload before the first probe item is shown can start afresh (lazy session rows).
- The A20 rate limit counts the user's `llm_usage` rows per minute (`LEARN_RATE_LIMIT_PER_MIN = 20`); in function mode every loop turn and grade still records a usage row, so a fast journey could 429 — if Task 9 sees it, record the counts (prompt "If you get stuck" 3), never raise a cap or seed usage for the loop user.
- The hint TEXT is not in `/hint`'s response: the client follows an accepted `/hint` with `POST /action {action_type: "hint"}` (JSON only, no stream variant). At H0/H1 the served key idea of a hint (and of a correct-verdict feedback) comes from code (`LOW_RUNG_KEY_IDEAS`), at H2 the hint question (`served_render`), so a journey asserting `E2E_LOOP_HINT_REPLY` verbatim must assert the model-written fields that survive at the rung it reaches.

## Verify commands

```
(under the stack lock) make e2e-up && (cd frontend && npx playwright test e2e/learn-loop.spec.ts) && (cd backend && venv/bin/python -m e2e_oracles); make e2e-down → every learn-loop.spec.ts test passed (loop journey, resume, budget cap, legacy-user split), oracles exit 0
cd frontend && npx tsc --noEmit                                                                   → clean
cd frontend && npx vitest run src/components/learn                                                → all passed
grep -c "E2E_LOOP_" backend/agents/function_handlers_e2e.py                                      → ≥ 3
grep -c '"/sessions"' backend/routes/learn_loop.py                                                → ≥ 1
```

(Backend lane, observed: `grep -c "E2E_LOOP_"` → 19; `grep -c '"/sessions"'` → 1; `pytest tests/test_learn_loop_sessions.py` → 15 passed; `-k "inv_13a or inv_13b"` → 2 passed (13b + the 13a scan self-test), 1 skipped (13a, the stub); full suite 7947 passed, 141 skipped (base 7889 / 140); `ruff check .` clean.)

## Open questions for the series owner

- Whether `Learn()`'s one extra GET for legacy users should be cached in `UserContext` (PKG-14 decides).
- Whether a later follow-up should fold `LoopLearn` into `Learn.tsx` or keep the branch (PKG-14b keeps it: the kill switch needs the legacy tree, spec §11.6).
- Whether `/hint` should return the hint text itself (HANDOFF-07 Open question (e)); until then the client makes two calls.

## Post-hoc changes

(Appended by later packages that modified this package's code. Format: `PKG-MM <date>: <what> — commit <sha>`.)
