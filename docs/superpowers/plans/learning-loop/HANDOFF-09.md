# HANDOFF-09 — close-brief

Written by the session that executed `PKG-09-close-brief.md`. Read by every later package that depends on 09. Keep every heading, even if the answer is "none".

**Status: built on `feat/learning-loop-09-close-brief` (cut from `feat/learning-loop` at 9dac6bd2); awaiting the coordinator** (LEDGER is the coordinator's: no row is written here). No push, no PR, no E2E run (session instructions).

## What changed

A loop session now ends with a real close. `POST /api/learn/loop/close` (and the legacy `end_session`'s loop delegate, for a materialised session with loop state) stores ONE close per session, encrypted on `sessions.close_json`, with the phase it stopped in on `sessions.close_phase`, and moves `loop_state["phase"]` to `close`; after that every teaching and answer route answers 409 `"this session is closed"`, and a second close returns the stored one (no model call, no event). The close is model-written by `agents/session_close.py` (flash-lite, one prompt, tool-less, `CLOSE_LIMITS`, an output validator that retries a malformed shape) only when the session has evidence rows and `ai_budget.check(user_id, "close", band)` is not hard (A25; invariant 23); otherwise — and whenever the agent is unavailable or its served text would state the answer of an item the session posed but never released — the deterministic `fallback_close` is stored with `model_written=false`. The close agent reads the session record only inside a nonce envelope (A51). A close is taken under a compare-and-set claim in `loop_state`; grading claims (check and probe) and close claims exclude each other, so no evidence lands outside a stored close. Every loop session carries a bounded learner brief (≤ 1800 chars; goal, weakest in-play concepts, last closes, open misconception keys; tags neutralised; one untrusted envelope) built once — at `/plan/approve` (PKG-08 reopen) or on the first loop turn without one — and stored encrypted on `sessions.loop_brief`; the loop history is the loop system prompt, the brief as a synthetic first message, then a block-trimmed 10–19-message window (A19). `learn.session_closed` is in the taxonomy. With `LEARNING_LOOP_ENABLED` unset nothing changes: `routes/learn.py` is byte-identical, `/close` and `/plan/approve` 404, and nothing reads or writes `close_json`/`loop_brief`.

Found and fixed on the way (PKG-07 reopen): pydantic-ai adds an agent's system prompt only to a run with NO `message_history`, so every loop turn after the opener ran without `_LOOP_SYSTEM_PROMPT` (loop rules, M2, the envelope, the injection guard). `_with_system_prompt` now leads the history with it.

## Symbols added

- `sessions.close_json text` (encrypted JSON `CloseRecord`), `sessions.close_phase text CHECK (… CLOSE_PHASES)`, `sessions.loop_brief text` (encrypted brief) — `backend/db/migrations/20260929112944_learning_session_close.sql`.
- `backend/learning/session_close.py`: `Turn`, `ConceptDelta{node_id,p_before,p_after}`, `CloseDraft{turns,concepts,misconception_keys,concept_names}`, `CloseRecord{summary,self_eval,if_then,concepts,misconceptions,model_written}`; `build_close(session_messages, evidence_rows, misconception_keys, learner_deltas, *, concept_names=None) -> CloseDraft` (pure; last LOOP_HISTORY_MAX_MESSAGES user/assistant turns cut to CLOSE_TRANSCRIPT_TURN_MAX_CHARS; first p_before / last p_after per node); `concept_label(draft, node_id)`; `fallback_close(draft)` (`"<name>: p a → b"` joined `"; "` or `NO_EVIDENCE_SUMMARY`, `FALLBACK_SELF_EVAL`, `if_then=""`, `model_written=False`); `normalise_close(output, draft)` (caps, keys ∩ draft keys); `ensure_session_row(session_id, user_id, row_defaults) -> bool` (A11 insert-if-missing, never upsert); `store_close(session_id, user_id, record, phase, *, row_defaults)` (ValueError on a phase outside CLOSE_PHASES, LookupError when the row is missing and cannot be created).
- `backend/learning/learner_brief.py`: `BRIEF_HEADER`, `build_brief(user_id, course_id, node_ids_in_play) -> str` (never raises; ≤ LEARNER_BRIEF_MAX_CHARS for any input), `store_brief(session_id, user_id, course_id, node_ids, *, row_defaults=None) -> str` (writes even an empty brief; DB errors propagate), `_open_misconception_keys(user_id, node_ids_in_play, closes)` (PKG-10 hook; reads the closes only).
- `backend/agents/session_close.py`: `SessionClose{summary,self_eval_prompt,if_then_plan,open_misconception_keys}`, `session_close_agent` (+ output validator `_validate_close`), `render_draft(draft, *, nonce)`, `direction(delta)`, `close_band(draft)`, `async run_session_close(draft, *, user_id, request_id) -> SessionClose | None` (calls `ai_budget.check(user_id, "close", close_band(draft))` first; bills a failed run via `UnfinishedRun`; never a tutor call, A39), `complete_sentences`, `close_shape_problems`, `is_one_question`, `is_if_then`, `shape_close(output, draft)`.
- `backend/agents/_providers.py`: `AgentTask "session_close"`, `_DEFAULTS["session_close"] = "gemini-2.5-flash-lite"`.
- `backend/agents/__init__.py::CLOSE_LIMITS = UsageLimits(2, 0, 20_000)`.
- `backend/agents/function_handlers_e2e.py`: `E2E_CLOSE_SUMMARY`, `E2E_CLOSE_SELF_EVAL`, `E2E_CLOSE_IF_THEN`, `E2E_CLOSE_MISCONCEPTIONS = []`, handler `"session_close"` (`_structured_output`).
- `backend/services/prompt_safety.py::neutralise_control_tags` (moved from `agents/loop_tutor.py`, re-imported there).
- `backend/learning/params.py`: `CLOSE_PHASES`, `CLOSE_SUMMARY_MAX_CHARS`, `CLOSE_SELF_EVAL_MAX_CHARS`, `CLOSE_IF_THEN_MAX_CHARS`, `CLOSE_TRANSCRIPT_TURN_MAX_CHARS`, `LOOP_HISTORY_TRIM_BLOCK`.
- `backend/models/__init__.py::CloseBody{session_id, user_id=""}`.
- `backend/routes/learn_loop.py`: `POST /close` (`close`; gate 404 first; A20 rate limit inline and only before a model run); `async close_session(session_id, user_id, *, request_id=None, rate_limit=False) -> {"close", "model_written", "close_phase"}`; `end_session(body, request) -> None` (the legacy delegate: closes through `run_agent_sync`); `served_close(output, draft, unreleased_items)`; `close_states_answer(text, item)`; `_close_phase`, `_unreleased_items`, `_close_misconception_keys` (PKG-10 hook, `[]`), `_stored_close`, `_claim_close`, `_finish_close`, `_session_record`, `_concept_names`, `_live`, `_grading_in_flight`, `_refuse_while_closing`, `_require_open`; history: `_BriefRequest(ModelRequest)`, `_brief_message`, `_history_window(n)`, `_brief_node_ids(loop_state, user_id, course_id)`, `_load_loop_history(session_id, *, user_id=None, course_id=None, loop_state=None)`, `_with_system_prompt(messages)`; constants `_SESSION_CLOSED`, `_CLOSE_IN_PROGRESS`, `_CLOSE_STORE_FAILED`, `_GRADING_IN_FLIGHT`; `_TEACHING_CLOSED["close"]`.
- `sessions.loop_state` keys: top-level `phase = "close"` (after a stored close), `close_claim` (uuid hex) / `close_claim_at` (Unix seconds) while a close is written.
- Event `learn.session_closed` (usage): `session_id, concepts, misconceptions, has_if_then, model_written`.
- Eval dataset `backend/tests/evals/session_close.py` (6 cases; cassettes `tests/evals/cassettes/session_close/`; `baselines.json["session_close"]`; in `run_all.DATASETS`).
- Tests: `tests/test_learning_close_brief.py` (102); `tests/test_e2e_function_handlers.py` +1; `tests/test_learning_probe_planner.py` +4; `tests/test_learn_loop_routes.py` +2 (and one rewritten in place); `tests/test_learn_loop_hardening.py` +1; `tests/test_event_capture_seams.py` pin +1; `tests/test_agent_output_schemas.py` roster +1; `tests/test_learning_loop_invariants.py` floors in inv_06/12/23.

## Constants chosen

- `LOOP_HISTORY_MAX_MESSAGES = 20` (§3.4; PKG-01, unchanged)
- `LOOP_HISTORY_TRIM_BLOCK = 10` † (§3.5 / §13 A19)
- `LEARNER_BRIEF_MAX_CHARS = 1800` (§3.4; PKG-01)
- `LEARNER_BRIEF_LAST_CLOSES = 3` (§3.4; PKG-01)
- `LEARNER_BRIEF_TOP_STATES = 5` (§3.4; PKG-01)
- `LEARNER_BRIEF_MAX_MISCONCEPTIONS = 5` (§3.4; PKG-01)
- `CLOSE_PHASES = ("probe","plan","teach","check","feedback","close")` (§4 CHECK / §9)
- `CLOSE_SUMMARY_MAX_CHARS = 500` †
- `CLOSE_SELF_EVAL_MAX_CHARS = 200` †
- `CLOSE_IF_THEN_MAX_CHARS = 200` †
- `CLOSE_TRANSCRIPT_TURN_MAX_CHARS = 400` †
- `CLOSE_LIMITS` = request 2 / tool calls 0 / tokens 20_000 † (`agents/__init__.py`)
- Strings (not tunables): `FALLBACK_SELF_EVAL`, `NO_EVIDENCE_SUMMARY`, `BRIEF_HEADER`, the close claim stale window reuses `LOOP_GRADING_CLAIM_STALE_S` (120 †, PKG-07).

Eval (served path, recorded 2026-09-29, gemini-2.5-flash-lite, output validator on): every gate 1.000 — ServedIfThenForm, ServedOneQuestion, ServedKeysSubset, ServedSummaryBounded, ServedNoInjection, ServedNoUnreleasedAnswer, ServedModelWritten, ServedSummaryComplete, ServedSecondPerson, ServedDirectionFaithful; diagnostics RawIfThenForm, RawOneQuestion, RawKeysSubset, RawSummaryWithinCap, RawSummaryComplete all 1.000. Two earlier recordings in the same session (same cases) exposed what the validator, the second-person rule and the `(up|down|unchanged)` labels now fix: summaries stopped mid-sentence ("… The student"), plans about "the student" instead of to them, and a summary calling a drop (0.40 → 0.21) "progress".

## Deviations from spec

- Task 1 committed red → the invariant floors (session_close REQUIRED in AgentTask, `agents/session_close.py` defines its agent, `session_close_agent` a budgeted run site) were committed right after Task 4 turned them green → owner rule: the suite is green after every commit. `SERIES_AGENT_TASKS`, `SERIES_AGENT_MODULES`, `BUDGETED_AGENT_MODULES` and inv_09's `close_json`/`loop_brief` were already present on the base (PKG-00/04/06b), so the "extend the list" steps became floors.
- Close input in `wrap_untrusted(source="session transcript and evidence")` → the whole record (transcript, concept changes, keys) inside ONE nonce envelope (`agents.loop_tutor.student_envelope`, tags neutralised) → spec §13 A51 (student text reaches a model only inside a nonce envelope); the eval uses a FIXED nonce.
- The draft carries concept names (`CloseDraft.concept_names`, one `graph_nodes` read on the student's own nodes) and the fallback summary says `"<name>: p …"` (node id when unknown) → a student-facing summary of UUIDs is not a summary; the stored record keeps node ids.
- `render_draft` labels each move `(up|down|unchanged)` → recorded flash-lite called a drop "progress" (structured data instead of asking the model to compare numbers).
- The agent has an output validator (`close_shape_problems`: complete summary, "If …, then …", one question, addressed as "you"), within `retries=2`/`CLOSE_LIMITS` → the prompt had none; served-path shape is also enforced in code (`shape_close`).
- Served close = `shape_close` + a strict served-mode leak check against every item the session posed but never released → fallback close on a hit (never masked, A51 N1). Lives in `routes/learn_loop.py::served_close` because `agents/` may import only one sanctioned PKG-06 name (`test_zpd_layer_is_inert_nothing_imports_it`).
- `store_close` raises `LookupError` when the row is missing and cannot be created → the prompt left it silent; a close is never dropped (route → 502).
- `/close` rate limit: inline `ai_budget.enforce_rate_limit_for` after the gate, only when this close would run the model → prompt said the PKG-07 dependency form; spec §9 sanctions inline "where only some bodies run a model" and PKG-08 (A55(e)) set the gate-404-before-429 precedent; a zero-evidence close always works (§3.5 ladder). `/close` joins PKG-07's `NO_MODEL_ROUTES` list in `test_rate_limit_dependency_on_model_routes_only`.
- Close phase: `loop_state` empty → `close`; else PKG-08's `_loop_phase` (probe/plan/teach; A55(a)), and in `teach` PKG-07's `_phase_for` (teach/check/feedback) → the prompt's "HANDOFF-06 phase key, missing → close" predates A55.
- Idempotent close, a close claim, `phase = "close"`, 409 on every teaching/answer route after it, and grading/closing mutual exclusion → not in the prompt; without them a double click (or /close then end-session) ran the model twice and emitted two events, and a turn or a graded answer after the close landed outside it. Built as structured state (claims in `loop_state`, CAS), not heuristics. The PKG-07/08 parts are reopen commits.
- `end_session` delegation: the prompt's block in `routes/learn.py` + `async def end_session` → PKG-07 already delegates (`_loop_delegate("end_session")`), so `routes/learn.py` is untouched and `learn_loop.end_session` (sync, as the legacy handler is) runs the async close through the sanctioned `agents._run.run_agent_sync` → the legacy handler stays a sync `def` (worker thread), byte-identical with the flag off; the prompt itself says "extend its branch".
- `event learn.session_closed` carries `request_id` (as PKG-08's events do) and the added `model_written` key (A8).
- `run_session_close` sets `SaplingDeps.learning_loop=True` (reached only behind the route-entry gate, A38 00).
- Brief: offerings from `services.academics.course_offering_ids` (tri-state; unknown → section skipped with a WARNING), not `user_offering_ids_for_course` → sessions are stamped by `resolve_offering`, and the enrollment-derived set diverges at a term rollover (the #553/#529 keyspace shape; the academics docstring says exactly this). Closes ordered `started_at.desc`, not `ended_at.desc` → a /close does not set `ended_at` and PostgREST's DESC puts NULLs first. The `graph_nodes` names read filters `user_id` too; an in-play node with no `learner_state` row is shown at the BKT prior; `goal: next exam in 1 day` (singular); the body's control tags are neutralised (the neutraliser moved to `services.prompt_safety` — PKG-07 reopen); the brief's patch names in tests are `course_offering_ids` and `read_states` (HANDOFF-03's real `read_states(user_id, ids) -> {id: LearnerState}`).
- `_session_course_id` not added → `/plan/approve` already reads `_session_scope`, which returns the abstract course (PKG-07's equivalent).
- Loop history: the brief is a `_BriefRequest` (a `ModelRequest` subclass: a type marker a student row can never forge), passed by `_guard_history` as built (never student-enveloped) and dropped for a turn when it restates the withheld item (A51 C1(b)).
- PKG-07 reopens (separate commits): neutraliser move (e2150dda), system prompt on history turns (8a9d1d04), route tests for A19 + `/close` (92de1e59), closed-session 409s (de52a38b), grading claim refused while closing (f4e43232). PKG-08 reopens: brief at `/plan/approve` (a9a87359), probe claim refused while closing (9f2efe0c). HANDOFF-07/08 Post-hoc lines written; LEDGER rows left to the coordinator.
- Migration has no RLS/REVOKE block → it only adds columns to the legacy `sessions` table, whose RLS/grants are unchanged (as `20260929050800_learning_loop_state_rev.sql`); both text columns hold ciphertext only.

## Known gaps

- A19's cacheable prefix is only [system prompt + brief]: PKG-07's `_guard_history` re-envelopes every history user row with a fresh per-call nonce (A51), so the window differs every call. Proposed row A63 below; the saving is unmeasured until A21's token columns are read.
- The stored brief can go stale within a session (A19; the current band rides in the phase prefix).
- `_open_misconception_keys` and `_close_misconception_keys` read nothing but the closes / return `[]` until PKG-10 repoints them.
- A pending (never-materialised) session closed via `/close` gets a `sessions` row from the A11 helper but no opener message and no `session.started` event (the legacy `_consume_pending` does both); if the store fails after the pending entry is popped, the session is gone (502).
- `ciphertext` oracle: `sessions.close_json` / `sessions.loop_brief` are not in `e2e_oracles` manifest yet; no journey closes a loop session until PKG-13 (add them then).
- The loop_tutor eval cases carry no history, so the system-prompt fix (and the brief) is not measured by any eval; a multi-turn loop case is PKG-14 territory.
- E2E not run (session instructions); `routes/learn.py` is byte-identical, so the flag-off lane is unaffected by construction.

## Verify commands

```
cd backend && venv/bin/python -m pytest tests/test_learning_close_brief.py -q                   → N passed (N ≥ 14)
ls backend/db/migrations/*_learning_session_close.sql                                            → 1 file
grep -c "loop_brief" backend/db/migrations/*_learning_session_close.sql                          → ≥ 1
grep -c "LOOP_HISTORY_TRIM_BLOCK" backend/routes/learn_loop.py                                   → ≥ 1
grep -c '"learn\.session_closed"' backend/services/events_service.py                             → 1
```

(Observed at hand-off: `102 passed`; 1 file; 2; 4; 1. Also: `tests/test_learning_loop_invariants.py -q` → `27 passed, 1 skipped`; `-k "inv_05 or inv_06 or inv_09 or inv_12 or inv_23"` → 6 passed (inv_23 + its self-test); full suite with the CI ignore set → `7501 passed, 136 skipped` (N₀ = 7389); `SAPLING_EVAL_MODE=replay tests/evals/run_all.py` → 14 datasets PASS.)

## Open questions for the series owner

1. Legacy `chat_tutor` has the same system-prompt shape (`system_prompt=` + a DB `message_history`), so the legacy tutor's prompt has also been missing from turn two on. Outside the series; fixed only for the loop. Took: report it (flag-off behaviour untouched).
2. Should PKG-13 render `self_eval` as a prompt the student answers, and where would the answer go (nothing stores it; `close_json` must not hold student text)? Took: returned and stored as the question only.
3. The close summary is shown to the student and read by the next session's brief; it speaks about "the student" in the third person while the question and the plan speak to "you". Took: validator enforces second person only for the question and the plan.
4. A per-session history nonce (A63 below) to make the A19 prefix cacheable past the brief: a PKG-07 change against A51's "fresh nonce per call". Took: nothing built.

## Proposed §13 rows (for the coordinator)

- **A60 The session close as built (PKG-09).** One close per session: `close_session` claims it by compare-and-set (`loop_state.close_claim`/`close_claim_at`, stale after `LOOP_GRADING_CLAIM_STALE_S`), stores `close_json` + `close_phase`, then sets `loop_state.phase = "close"`; a stored close is returned as is (no model, no event). Grading claims (`_claim_grading`, `/probe/answer`) are refused while the session is closed or a live close claim holds it, and a close is refused (409) while any grading claim is live. After the close, `/chat`, `/chat/stream`, `/action`, `/hint`, `/check/next`, `/check/answer(/stream)` and `/step/attempt` answer 409 `"this session is closed"`. The phase is `close` for a session with no loop state, else A55(a)'s phase refined by PKG-07's `_phase_for`. `/close`'s A20 check is inline after the gate and only before a model run. The close agent's input is ONE nonce envelope (A51); an output validator retries an incomplete summary, a plan not "If …, then …", a self-evaluation that is not one question, or a plan/question about "the student"; the served close (`routes.learn_loop.served_close`) cuts the summary to complete sentences, drops a malformed plan, replaces a malformed question, and stores the deterministic close when any served text states the answer of an item the session posed but never released (strict, served mode). Moves are labelled `(up|down|unchanged)` in the record; the draft carries concept names.
- **A61 The loop system prompt rides the history.** pydantic-ai adds an agent's system prompt only to a run with no `message_history`; every loop turn after the opener has one, so `_LoopTurn.plan` leads the history with `ModelRequest(SystemPromptPart(_LOOP_SYSTEM_PROMPT))` (`_with_system_prompt`). Any agent run with a DB history needs the same (the legacy chat tutor included — outside the series).
- **A62 The learner brief as built.** Offerings from `course_offering_ids` (the `resolve_offering` keyspace), closes ordered `started_at.desc`, names read on the student's own `graph_nodes`, an in-play node with no state shown at the BKT prior, control tags neutralised (`services.prompt_safety.neutralise_control_tags`), the hard bound re-cut after delimiter neutralisation. In the loop history it is a `_BriefRequest` (type marker), never re-enveloped as the student's words, dropped for a turn when it restates the withheld item (A51 C1(b)). At `/plan/approve` the course is `_session_scope`'s.
- **A63 (proposal, not built) A per-session history nonce.** Envelope history user rows with a nonce stored once per session in `loop_state` (never shown to the student), keeping a fresh per-call nonce for the current turn's message only, so A19's stable prefix extends through the history window instead of ending at the brief.

## Post-hoc changes

(Appended by later packages that modified this package's code. Format: `PKG-MM <date>: <what> — commit <sha>`.)
