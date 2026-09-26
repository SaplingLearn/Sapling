# PKG-13 frontend-e2e — Learning Loop series (14 of 15)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> You are a fresh session. Nothing outside this file, `docs/superpowers/plans/learning-loop/LEDGER.md`, the `HANDOFF-NN.md` files it names, and the files this prompt lists is known to you. Do not infer intent from chat history you do not have. Do not read the whole research corpus; read the sections named below.

## Package id + goal

**PKG-13 `frontend-e2e`.** After this package: an opted-in student sees the loop UI in the Learn screen (probe → plan → teach/check → feedback → close) driven by `/api/learn/loop/*`; the SSE consumer understands the four loop events and the leak-redaction flag; the function-mode seam has phase-aware `E2E_LOOP_*` constants; the rich seed carries an opted-in student with a prerequisite chain and encrypted check items; `LEARNING_LOOP_ENABLED=true` is part of the E2E lane; `frontend/e2e/learn-loop.spec.ts` walks the whole loop and asserts the database; the `learn_loop` oracle guards the loop's write invariants; and every legacy user, spec, and oracle is unchanged. Depends on PKG-08, PKG-09, PKG-12 (and transitively 05, 06, 07).

Branch: `feat/learning-loop-13-frontend-e2e`. PR title: `feat(learning): PKG-13 frontend-e2e`.

## Read before you start (in this order)

0. `docs/superpowers/specs/2026-09-26-learning-loop-design.md` **§13 Amendments log** — in force; where this file and §13 disagree, §13 wins. Re-read it before Task 1.
1. `docs/superpowers/plans/learning-loop/LEDGER.md` — refuse to start if any row is `blocked` or `in-progress`. Rows 00–12 must be `done` or `verified`.
2. `docs/superpowers/plans/learning-loop/HANDOFF-07.md`, `HANDOFF-08.md`, `HANDOFF-09.md`, `HANDOFF-12.md` (also `HANDOFF-05.md`, `HANDOFF-06.md` §Symbols added). Copy every route path, body model, response key, event name, gate denial reason, and `E2E_*` constant name they list into the scratch table you keep for Task 4 Step 0. **They override the "expected contract" tables in this prompt wherever they differ.**
3. `CLAUDE.md` §Conventions and §Gotchas — especially the E2E-stack-singleton `flock` rule and the function-mode seam paragraph.
4. `docs/superpowers/specs/2026-09-26-learning-loop-design.md` §3.3 (gates: what a genuine attempt is, `OFFER_BANDS`), §3.4 (`PROBE_*`, `PLAN_*`), §6 (event payload keys), §7 (404 when the gate is false), §8 (invariants 1, 5, 6), §9 (session phases + the four stream events).
5. `docs/superpowers/plans/learning-loop/README.md` and `HANDOFF-template.md`.
6. Research, only these sections: `docs/research/learning-loop/AI tutor learning loop research.md` §"Run each session as probe, plan, step, check, feedback, close" (lines ~58–97: the six phases the UI renders, incl. "Close: a written summary, a self-evaluation, an if-then plan"); `docs/research/learning-loop/ZPD lever tradeoffs and upgrades.md` §"Sapling ZPD policy spec" (lines ~143–234: the GATES block — what the UI must NOT let a student skip — and the LOG block the oracle reads).
7. Code you will modify:
   - `frontend/src/components/screens/Learn.tsx` — `Learn()` wrapper `:327–333` (the branch point), `LearnInner` `:335` (`useUser` at `:338`), `tierForScore` `:88–93` (do not touch; the loop UI reads `band` off the server), the streamed opener `beginSession` `:545–625` (`startSessionStream` call `:599`), the chat turn's `streamChat` call `:777–786` (the `onToken`/`onGraphUpdate`/`signal` handler shape LoopLearn mirrors), entry-screen render `:1231`, active-session render `:1302`.
   - `frontend/src/lib/api.ts` — `fetchJSON` `:108`, `ChatResult` `:295`, `StreamEvent` `:303`, `StreamChatHandlers` `:355`, `consumeChatStream` `:363–397`, `streamChat` `:399`, `startSessionStream` `:422`.
   - `frontend/src/app/(shell)/learn/page.tsx` — mounts `<Learn />`; unchanged unless the branch must live here (it must not).
   - `backend/agents/function_handlers_e2e.py` — `_last_user_prompt_text` `:81`, the `loop_tutor` handler PKG-07 added (grep `"loop_tutor"`), `E2E_LOOP_TUTOR_REPLY` (PKG-07), `E2E_CHECK_ITEM_*` (PKG-04), `E2E_GRADER_*` (PKG-05), `E2E_CLOSE_*` (PKG-09). `grep -n "^E2E_" backend/agents/function_handlers_e2e.py` and record every name.
   - `backend/tests/test_e2e_function_handlers.py` — `_clean_function_registry` fixture `:44–52`, `_deps()` `:55`, the per-handler test shape `:66–80`.
   - `backend/db/seed_local_rich.py` — header `:1–33` (`_guard_local`, encryption imports), ids `:35–78`, `_USERS` `:162–187`, `seed_users` `:194`, `_ENROLLMENTS` `:230`, `_GRAPH_NODES`/`_GRAPH_EDGES`/`seed_graph` `:259–348`, `_SUMMARY_ORDER` `:842`, `main` `:852`. `backend/db/seed_helpers.py` (`upsert`, `insert_if_absent`, `exists_by`).
   - `backend/e2e_oracles/__main__.py` (`CHECKS` `:41`), `gather.py` (`_db_conn` `:79`, `run_orphans` `:286` — the shape to mirror), `judges.py` (pure judges), `findings.py`, `__init__.py` (stdlib-only contract). Tests: `backend/tests/test_e2e_oracles_cli.py`, `test_e2e_oracles_judges.py`.
   - `scripts/e2e-up.sh` — the `export QUIZ_GENERATE_RATE_LIMIT` block (#537) just before uvicorn starts; `.github/workflows/e2e.yml` `:103–115` (the "Boot the stack" env block); `scripts/explore.sh:398–410` (the seam exports).
   - `frontend/eslint.config.mjs` `:53–92` (the testid `files` array); `docs/frontend-testids.md` §Naming, §"Where the testids live", §"Adding a surface" (`:602`).
8. Code you will mirror: `frontend/e2e/tutor.spec.ts` (journey style, DB poll `:82–102`, decrypt readback `:107–120`), `frontend/e2e/study-room.spec.ts:120–130` (`browser.newContext({ storageState: await mintStorageState(...) })`), `frontend/e2e/events.spec.ts:96–112` (events-table assertion), `frontend/e2e/support/{fixtures,db,session,stack,decrypt}.ts`, `frontend/src/lib/api.stream.test.ts:1–40` (`sseBody`/`ev` helpers), `frontend/e2e/global-setup.ts`.
9. `docs/e2e-exploration.md` §7–§8 (triage/promotion: the seam-artifact tell) and §10 (lock protocol).

## State of the world

Verify the base before Task 1. Every row must be green.

| check | command | expected |
|---|---|---|
| ledger | `grep -E "^\| (0[5-9]\|1[0-2]) " docs/superpowers/plans/learning-loop/LEDGER.md` | every row `done` or `verified`, none `blocked`/`in-progress` |
| hermetic suite green | `cd backend && venv/bin/python -m pytest tests/ -q -x` | `… passed`, zero failures (note the count N₁₂) |
| lint green | `cd backend && venv/bin/ruff check .` | `All checks passed!` |
| frontend typecheck | `cd frontend && npx tsc --noEmit` | clean |
| frontend unit tests | `cd frontend && npm test` | all passed (note the count) |
| stubs still inert | `cat frontend/src/components/learn/LoopLearn.tsx frontend/e2e/learn-loop.spec.ts` | comment + `export {};` only |
| PKG-00 | `cd backend && venv/bin/python -m pytest tests/test_learning_gate.py -q` | `11 passed` |
| PKG-00 | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q` | `12 passed` or `11 passed, 1 skipped` (inv_10 may still be a placeholder) |
| PKG-00 | `cd backend && venv/bin/python -m pytest tests/test_learning_deps.py tests/test_learning_settings_flag.py tests/test_learning_loop_beta_migration.py -q` | all passed |
| PKG-00 | `grep -n "^LEARNING_LOOP_ENABLED" backend/config.py` | 1 hit |
| PKG-00 | `ls backend/db/migrations/*_learning_loop_beta.sql` | 1 file |
| PKG-05 | `cd backend && venv/bin/python -m pytest tests/test_learning_check_tool.py -q` | N passed (N ≥ 12) |
| PKG-05 | `grep -c '"grader"' backend/agents/_providers.py backend/agents/function_handlers_e2e.py` | ≥ 1 each |
| PKG-05 | `grep -c "^async def graded_check_tool" backend/agents/tools/check.py` | 1 |
| PKG-05 | `cd backend && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/grader.py` | every evaluator ≥ baseline |
| PKG-07 | `cd backend && venv/bin/python -m pytest tests/test_learn_loop_routes.py -q` | N passed (N ≥ 15) |
| PKG-07 | `grep -c "learn_loop" backend/main.py` | ≥ 1 |
| PKG-07 | `grep -c '"loop_tutor"' backend/agents/_providers.py backend/agents/function_handlers_e2e.py` | ≥ 1 each |
| PKG-07 | `grep -c "learning_loop" backend/agents/chat_tutor.py` | ≥ 1 |
| PKG-07 | `cd backend && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/loop_tutor.py` | every evaluator ≥ baseline |
| PKG-08 | `cd backend && venv/bin/python -m pytest tests/test_learning_probe_planner.py -q` | N passed (N ≥ 15) |
| PKG-08 | `grep -cE "^def (next_probe_item\|probe_done\|novice_floor)\(" backend/learning/probe.py` | 3 |
| PKG-08 | `grep -cE "^def (outer_fringe\|plan)\(" backend/learning/planner.py` | 2 |
| PKG-08 | `grep -c '"learn\.probe_done"\|"learn\.plan_approved"' backend/services/events_service.py` | 2 |
| PKG-09 | `cd backend && venv/bin/python -m pytest tests/test_learning_close_brief.py -q` | N passed (N ≥ 10) |
| PKG-09 | `ls backend/db/migrations/*_learning_session_close.sql` | 1 file |
| PKG-09 | `grep -c "LOOP_HISTORY_MAX_MESSAGES" backend/routes/learn_loop.py` | ≥ 1 |
| PKG-09 | `grep -c '"learn\.session_closed"' backend/services/events_service.py` | 1 |
| PKG-12 | `cd backend && venv/bin/python -m pytest tests/test_learning_review.py -q` | N passed (N ≥ 10) |
| PKG-12 | `grep -c "review/next" backend/routes/learn_loop.py` | ≥ 1 |
| PKG-12 | `grep -c '"review\.served"\|"review\.graded"' backend/services/events_service.py` | 2 |
| E2E lane green on `main` (under the lock, once) | `flock /tmp/claude-$(id -u)/sapling-e2e-stack.lock -c 'export SAPLING_MODEL_MODE=function SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e GEMINI_API_KEY=e2e-dummy-key-no-billing; make e2e-up && (cd frontend && npx playwright test) && (cd backend && venv/bin/python -m e2e_oracles); rc=$?; make e2e-down; exit $rc'` | every spec passed; `0 finding(s)`; exit 0 (note the spec count S₀) |

The `grep -cE` rows above use `\|` inside the character alternation only because Markdown tables eat bare pipes; type them with a bare `|`.

Rule: any red row → STOP. Diagnose, repair on this branch as commit `fix(learning-loop): repair pre-series base — <what>`, record the deviation in `LEDGER.md`, re-run all rows. Never build on a broken base. If the E2E row is red on `main` before you have changed anything, that is a pre-existing lane failure: record it as `BLOCKED` in the ledger and stop — this package cannot be verified on a red lane.

## Spec

### Behaviour

1. **Branch point.** `Learn()` (`Learn.tsx:327`) calls `GET /api/learn/loop/status` once `userReady && userId`. `{active: true}` → render `<LoopLearn />`. `{active: false}`, HTTP 404 (spec §7: flag off), or any error → render the existing `<Suspense><LearnInner /></Suspense>` exactly as today. While the status is unresolved, render the existing Suspense fallback text (`Loading…`). Nothing else in `LearnInner` changes; a legacy user's Learn screen differs from today by exactly one GET.
2. **Phases** (spec §9). `LoopLearn` is a single component with a `phase` state machine `probe → plan → teach ⇄ check → feedback → close`. The root carries `data-testid="loop-phase"` and `data-phase="<phase>"`. Phase changes come from the server: the response of each loop endpoint carries `phase`, and the stream emits a `phase` event; the client never advances a phase on its own.
3. **Probe.** On mount, `POST /api/learn/loop/probe/start` for the student's current course (pick the first enrolled course id from the existing `getEnrolledCourses` client, or whatever HANDOFF-08 says the route needs). Render the current item (`loop-probe-item`, with `data-question-hash`): the prompt, a free-text answer (`loop-probe-input` + `loop-probe-submit`) for `free`/`teachback`, option buttons (`loop-probe-option-{key}`) plus a one-sentence reason field (`loop-probe-reason`) for `mc_reason`, and an "I don't know" control (`loop-probe-idk`) that submits `idk: true` with no answer text. Each answer posts `POST /api/learn/loop/probe/answer` and renders the next item or the `plan` phase.
4. **Plan.** `GET /api/learn/loop/plan` → the ordered concept list (`loop-plan-concept-{nodeId}`, showing concept name, band, and a "review" badge when `is_review`), plus `loop-plan-approve`. Approving posts `POST /api/learn/loop/plan/approve` and enters `teach`.
5. **Teach / check.** The chat log (`loop-messages`) streams over `POST /api/learn/loop/chat/stream` using the same `onToken` + streaming-bubble pattern as `Learn.tsx:777–786` (reuse `ChatPanel` with `header` and no `onAction`; the legacy `[ACTION: hint]` path is not the loop's hint). A `check` stream event sets the current item (`loop-check-prompt`, `data-question-hash`). The attempt box (`loop-attempt-input`, `loop-attempt-submit`): on the FIRST keystroke for a given `question_hash` it posts `POST /api/learn/loop/step/attempt` once (a ref keyed on `question_hash` prevents re-posting); submit sends the answer as a chat turn (the server runs `graded_check_tool`). The Hint button (`loop-hint-button`) posts `POST /api/learn/loop/hint`; `allowed: false` renders `loop-hint-denied` with `data-reason="<reason>"` and a plain-English line per reason; `allowed: true` renders the hint text in `loop-hint-reply` and appends it to the log. A `hint_offer` stream event (novice band only, spec §3.3 `OFFER_BANDS`) renders an "Want a hint?" affordance that clicks through to the same Hint call. A `learner_state` event updates `loop-learner-state` (`data-node-id`, `data-p-known`, `data-band`).
6. **Feedback.** The `phase: feedback` event flips the phase; the settled reply is `done.data.reply`. When `done.data.leak_redacted === true`, the rendered bubble is REPLACED by `done.data.reply` (the redacted text), never the streamed tokens — confirm the key names against HANDOFF-07 and adapt. A "Continue" control (`loop-continue`) sends the next turn.
7. **Close.** `loop-close-button` (available in teach/check/feedback) posts `POST /api/learn/loop/close` and renders `loop-close-summary` (the summary text), the self-evaluation question with `loop-close-self-eval`, the if-then prompt with `loop-close-if-then`, and `loop-close-submit`; submitting posts the two answers (second call, or the same route with the fields — per HANDOFF-09) and renders `loop-close-done`.
8. **Inert when the gate is false.** With `LEARNING_LOOP_ENABLED` unset, `/api/learn/loop/status` 404s → `Learn()` renders the legacy tree; `LoopLearn` is never mounted; no loop client function is called except the status GET. Proven by the vitest test in Task 4 (404 → `false`) and by the legacy specs staying green on a stack whose flag is ON but whose users are not opted in.
9. **Seam.** In function mode the `loop_tutor` handler answers by PHASE: the hint prompt → `E2E_LOOP_HINT_REPLY`; the feedback prompt → `E2E_LOOP_FEEDBACK_REPLY`; anything else → `E2E_LOOP_TUTOR_REPLY` (PKG-07's constant, unchanged). Phase detection scans every text part of the message history for the substrings in `E2E_LOOP_PHASE_PATTERNS`, whose values are copied from the phase prompts in `agents/loop_tutor.py` (never invented). Still no tool calls from the handler.
10. **Seed.** `rich-user-loop` ("Lou Loop") — approved, onboarded, enrolled in `OFF_CS_S26`, `user_settings.learning_loop_beta = true`, `SEED_LOOP_CONCEPTS` graph nodes in `COURSE_CS` chained by `prerequisite` edges oriented per `learning.params.EDGE_PREREQ_SOURCE_IS_PREREQ`, mastery `0.0`/`unexplored`, no `learner_state` rows, and `SEED_LOOP_ITEMS_PER_CONCEPT` `check_items` per node (one per value of `CHECK_ITEM_DIFFICULTIES`, format `free`, encrypted columns, `question_hash` over the plaintext prompt, reference answer = the PKG-05 grader's correct token). `rich-user-active`, `rich-user-second`, `rich-user-new` stay legacy (no `learning_loop_beta`).
11. **Lane env.** `scripts/e2e-up.sh` exports `LEARNING_LOOP_ENABLED="${LEARNING_LOOP_ENABLED:-true}"` before starting uvicorn (same shape and placement as the #537 `QUIZ_GENERATE_RATE_LIMIT` export); `.github/workflows/e2e.yml` and `scripts/explore.sh` set the same value beside the other seam vars.
12. **Oracle.** `python -m e2e_oracles --check learn_loop` asserts, table-wide: (a) every `node_mastery_events` row with `event_type = 'evidence'` has a `learner_state` row for `(graph_nodes.user_id, node_id)`; (b) zero `events` rows with `event_type = 'zpd.leak'`; (c) every `zpd.step` payload has numeric `p_known_before` and `p_known_after` in `[0, 1]`; (d) for every evidence-touched node, `graph_nodes.mastery_score` equals `learner_state.p_known` within `ORACLE_P_TOLERANCE`. A missing `learner_state` table is an `oracle-error` finding.

### Expected route contract (from the PKG-07/08/09/12 prompts — VERIFY against `routes/learn_loop.py` and the hand-offs; the hand-offs win)

| method + path | body | response keys the UI needs | owner |
|---|---|---|---|
| `GET /api/learn/loop/status?user_id=` | — | `active` | PKG-07 |
| `POST /api/learn/loop/probe/start` | `user_id, course_id` | `session_id, phase, item{question_hash, format, difficulty, prompt, options?, node_id}` | PKG-08 |
| `POST /api/learn/loop/probe/answer` | `session_id, user_id, question_hash, answer?, reason?, idk` | `phase, item|null, learner_state[]` | PKG-08 |
| `GET /api/learn/loop/plan?session_id=&user_id=` | — | `phase, concepts[{node_id, concept_name, p_known, band, is_review}]` | PKG-08 |
| `POST /api/learn/loop/plan/approve` | `session_id, user_id` | `phase` | PKG-08 |
| `POST /api/learn/loop/chat/stream` | `session_id, user_id, message` | SSE: `token, phase, check, hint_offer, learner_state, graph_update, error, done{reply, leak_redacted?}` | PKG-07 |
| `POST /api/learn/loop/step/attempt` | `session_id, user_id, question_hash, text` | `recorded` | PKG-06/07 |
| `POST /api/learn/loop/hint` | `session_id, user_id, question_hash, text?` | `allowed, reason?, rung?, reply?` | PKG-07 |
| `POST /api/learn/loop/close` | `session_id, user_id, self_eval?, if_then?` | `phase, summary, self_eval_question, if_then_prompt` | PKG-09 |
| `GET /api/learn/loop/review/next?user_id=` | — | `kind, n, items[]` | PKG-12 |

Every loop route returns 404 `{"detail": "learning loop not enabled"}` when the gate is false (spec §7).

### Schema (exact)

None. This package writes no migration. It reads `learner_state` (PKG-03), `check_items` (PKG-04), `sessions.loop_state` (PKG-06), `sessions.close_json`/`close_phase` (PKG-09), `events` (0035).

### Named constants

Learning constants are cited by name and read from `backend/learning/params.py` — in TypeScript through `frontend/e2e/support/params.ts::learningParams()` (a python shell-out, Task 7), never as a literal. Harness constants are named `const`s at the top of the file that owns them; they are not learning parameters and do NOT go into `params.py`. `†` = engineering choice without a validated cut-point; list every † in the hand-off.

| Name | Value | Owner file | Meaning / source |
|---|---|---|---|
| `BKT_L0` | 0.35 | `learning/params.py` (spec §3.1) | journey asserts `learner_state.p_known > BKT_L0` |
| `PROBE_ITEMS_PER_SKILL_MIN` | 4 | `learning/params.py` (spec §3.4) | journey asserts it answered at least this many probe items |
| `PROBE_SESSION_CAP` | 12 | `learning/params.py` (spec §3.4) | upper bound of the journey's probe loop |
| `GATE_INDEPENDENT_MIN_S` | 45 † | `learning/params.py` (spec §3.3) | the journey's hint poll waits this long for the independent-time gate |
| `GATE_RUNG_DWELL_MIN_S` | 8 † | `learning/params.py` (spec §3.3) | informational; one hint only in the journey |
| `CHECK_ITEM_DIFFICULTIES` | (1, 2, 3) | `learning/params.py` (spec §3.4) | seed writes one item per value |
| `CHECK_ITEM_MIN_RUBRIC` / `CHECK_ITEM_MIN_WRONG` | 2 / 1 | `learning/params.py` (spec §3.4) | seed rubric/wrong lists meet them |
| `EDGE_PREREQ_SOURCE_IS_PREREQ` | True (or flipped by PKG-08) | `learning/params.py` (spec §3.1) | seed orients the prerequisite edges by it |
| `SEED_LOOP_CONCEPTS` | 3 † | `db/seed_local_rich.py` | nodes in the loop user's chain |
| `SEED_LOOP_ITEMS_PER_CONCEPT` | `len(CHECK_ITEM_DIFFICULTIES)` = 3 † | `db/seed_local_rich.py` | items per node (brief minimum 2) |
| `LOOP_JOURNEY_TIMEOUT_MS` | 240_000 † | `frontend/e2e/learn-loop.spec.ts` | `test.setTimeout`; covers the independent-time gate plus paced streaming |
| `GATE_POLL_MARGIN_MS` | 15_000 † | `frontend/e2e/learn-loop.spec.ts` | added to `GATE_INDEPENDENT_MIN_S` for the hint poll |
| `DB_POLL_TIMEOUT_MS` | 5_000 | `frontend/e2e/learn-loop.spec.ts` | house value (`tutor.spec.ts:101`) |
| `ORACLE_P_TOLERANCE` | 1e-9 † | `backend/e2e_oracles/learn_loop.py` | `mastery_score == p_known` tolerance |
| `E2E_FUNCTION_STREAM_DELAY_MS` | 150 | `function_handlers_e2e.py:48` (existing) | not changed; explains the journey's stream pacing |

### Invariants asserted by this package (spec §8 numbering)

This package owns none of the twelve. Task 1 adds two package-specific invariants to the module:

- (13-a) every `E2E_*` name a spec file cites in a `Must match backend/agents/function_handlers_e2e.py::NAME` comment exists in that module, and the TypeScript literal beside it equals the Python value — source scan over `frontend/e2e/*.spec.ts` + import of the module under the registry-clearing fixture.
- (13-b) `db/seed_local_rich.py` sets `learning_loop_beta` to `True` for exactly one user id (`rich-user-loop`) — source scan; the legacy `rich-user-active`/`second`/`new` never appear on a line with `learning_loop_beta`.

### Error semantics

The status GET fails closed to the legacy tree. Loop client calls that fail surface through the existing toast path (`useToast`) and leave the phase unchanged; a failed stream uses the same `ChatStreamError` handling as `Learn.tsx` minus the JSON-fallback rung (the loop has no JSON twin — confirm in HANDOFF-07; if a twin exists, mirror the ladder). No agent is called from this package's backend code (the handler is scripted output).

### Events added

None. The oracle READS `zpd.step`, `zpd.leak`, `learn.session_closed` (spec §6). `EVENT_TAXONOMY` is untouched.

## Non-goals

- No new route, no route change, no `chat_stream.py` change, no `agent_events.py` change. A contract gap between this prompt's expected table and the real routes is fixed by adapting THIS package's client (and recording the deviation), not by editing PKG-07..12 code — unless a route is actually broken, in which case: separate first commit `fix(learning-loop): PKG-MM — <what>`, `MM | reopened` ledger row, "Post-hoc changes" in `HANDOFF-MM.md`.
- No redesign of `ChatPanel`; no change to the legacy entry screen, session picker, knowledge-map rail, or `tierForScore`.
- No mobile layout work beyond what `ChatPanel` already provides; no review-surface UI beyond the "review" badge on plan rows (PKG-12's Study-screen surfaces are theirs).
- No `explore` (Chapter 2) run; Chapter 1 only.
- No cutover (PKG-14).

## Tasks

### Task 1: Package invariants (spec sync + seed opt-in)

**Files:**
- Modify: `backend/tests/test_learning_loop_invariants.py` (append two tests)

**Interfaces:**
- Consumes: `frontend/e2e/*.spec.ts` (source), `agents.function_handlers_e2e` (import), `db/seed_local_rich.py` (source).

- [ ] **Step 1: Append the tests** (they fail now: the spec file is a stub and the seed has no loop user)

```python
# ── PKG-13 ────────────────────────────────────────────────────────────────

FRONTEND_E2E = BACKEND.parent / "frontend" / "e2e"
SEED = BACKEND / "db" / "seed_local_rich.py"

# `/** Must match backend/agents/function_handlers_e2e.py::E2E_X */` followed by
# `const NAME = "..." + "...";` — the house shape (tutor.spec.ts:34–37).
_SYNC_RX = re.compile(
    r"Must match backend/agents/function_handlers_e2e\.py::(E2E_[A-Z0-9_]+)\s*\*/\s*"
    r"const\s+\w+\s*=\s*((?:\"(?:[^\"\\]|\\.)*\"\s*\+?\s*)+);",
)


def _ts_string(expr: str) -> str:
    import json
    return "".join(json.loads(piece) for piece in re.findall(r"\"(?:[^\"\\]|\\.)*\"", expr))


def test_inv_13a_spec_constants_match_function_handlers(monkeypatch):
    import sys
    from agents._providers import clear_function_handlers
    sys.modules.pop("agents.function_handlers_e2e", None)
    import importlib
    handlers = importlib.import_module("agents.function_handlers_e2e")
    try:
        pairs = []
        for spec in sorted(FRONTEND_E2E.glob("*.spec.ts")):
            for name, expr in _SYNC_RX.findall(spec.read_text()):
                pairs.append((spec.name, name, _ts_string(expr)))
        assert any(spec == "learn-loop.spec.ts" for spec, _, _ in pairs), "learn-loop.spec.ts cites no E2E_ constant"
        for spec, name, ts_value in pairs:
            assert hasattr(handlers, name), f"{spec} cites {name}, not in function_handlers_e2e"
            assert getattr(handlers, name) == ts_value, f"{spec}: {name} drifted from the backend constant"
    finally:
        clear_function_handlers()
        sys.modules.pop("agents.function_handlers_e2e", None)


def test_inv_13b_seed_opts_in_exactly_the_loop_user():
    text = SEED.read_text()
    assert "USER_LOOP = \"rich-user-loop\"" in text, "seed has no loop user"
    opt_in_lines = [ln for ln in text.splitlines() if "learning_loop_beta" in ln]
    assert opt_in_lines, "seed never sets learning_loop_beta"
    assert all("True" in ln for ln in opt_in_lines), opt_in_lines
    for legacy in ("USER_ACTIVE", "USER_SECOND", "USER_NEW", "rich-user-active", "rich-user-second", "rich-user-new"):
        assert not any(legacy in ln for ln in opt_in_lines), f"{legacy} must stay legacy"
```

- [ ] **Step 2: Run to see the current state**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_13"`
Expected: 2 failed — `learn-loop.spec.ts cites no E2E_ constant`; `seed has no loop user`.

- [ ] **Step 3: Commit**

```
git add backend/tests/test_learning_loop_invariants.py
git commit -m "test(learning-loop): PKG-13 — spec/handler sync and seed opt-in invariants

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 2: Phase-aware `loop_tutor` handler + `E2E_LOOP_*` constants

**Files:**
- Modify: `backend/agents/function_handlers_e2e.py`
- Test: `backend/tests/test_e2e_function_handlers.py` (append)

**Interfaces:**
- Consumes: the phase prompts in `agents/loop_tutor.py` (read them; the pattern VALUES come from there).
- Produces: `E2E_LOOP_PROBE_PROMPT: str`, `E2E_LOOP_HINT_REPLY: str`, `E2E_LOOP_FEEDBACK_REPLY: str`, `E2E_LOOP_PHASE_PATTERNS: dict[str, str]` (`{"hint": ..., "feedback": ...}`), `_loop_tutor_handler` rewritten to dispatch on phase.

- [ ] **Step 1: Write the failing tests** (append; reuse the module's `_clean_function_registry` fixture and `_deps()`)

```python
# ── Learning loop, PKG-13 ─────────────────────────────────────────────────
#
# The loop_tutor handler answers by PHASE so frontend/e2e/learn-loop.spec.ts
# can tell a hint turn from a feedback turn from a teach turn. Detection is a
# substring scan over every text part (system + user) for the phase prompts
# loop_tutor.py actually emits — E2E_LOOP_PHASE_PATTERNS copies those
# substrings, so a prompt rewrite that drops them fails these tests, not the
# browser lane.


def _loop_messages(*texts: str):
    from pydantic_ai.messages import ModelRequest, SystemPromptPart, UserPromptPart
    parts = [SystemPromptPart(content=t) for t in texts[:-1]] + [UserPromptPart(content=texts[-1])]
    return [ModelRequest(parts=parts)]


def test_loop_tutor_handler_default_is_the_pkg07_reply():
    from agents.function_handlers_e2e import E2E_LOOP_TUTOR_REPLY, _loop_tutor_handler
    out = _loop_tutor_handler(_loop_messages("explain binary numbers"), None)
    assert out.parts[0].content == E2E_LOOP_TUTOR_REPLY


def test_loop_tutor_handler_hint_phase():
    from agents.function_handlers_e2e import E2E_LOOP_HINT_REPLY, E2E_LOOP_PHASE_PATTERNS, _loop_tutor_handler
    out = _loop_tutor_handler(_loop_messages(E2E_LOOP_PHASE_PATTERNS["hint"], "hint please"), None)
    assert out.parts[0].content == E2E_LOOP_HINT_REPLY


def test_loop_tutor_handler_feedback_phase():
    from agents.function_handlers_e2e import E2E_LOOP_FEEDBACK_REPLY, E2E_LOOP_PHASE_PATTERNS, _loop_tutor_handler
    out = _loop_tutor_handler(_loop_messages(E2E_LOOP_PHASE_PATTERNS["feedback"], "my answer"), None)
    assert out.parts[0].content == E2E_LOOP_FEEDBACK_REPLY


def test_loop_phase_patterns_are_real_loop_tutor_prompt_text():
    """Patterns must be substrings of loop_tutor.py's own prompt source, so
    they can never be invented strings that no real prompt carries."""
    import pathlib
    from agents.function_handlers_e2e import E2E_LOOP_PHASE_PATTERNS
    src = (pathlib.Path(__file__).resolve().parents[1] / "agents" / "loop_tutor.py").read_text()
    assert set(E2E_LOOP_PHASE_PATTERNS) == {"hint", "feedback"}
    for phase, pattern in E2E_LOOP_PHASE_PATTERNS.items():
        assert len(pattern) >= 12, (phase, pattern)
        assert pattern in src, f"{phase!r} pattern {pattern!r} is not in agents/loop_tutor.py"


def test_loop_constants_do_not_leak_the_grader_token():
    """A hint or feedback reply carrying the correct token would let the
    journey pass a check it never answered — and would be a real leak."""
    from agents.function_handlers_e2e import (
        E2E_LOOP_FEEDBACK_REPLY, E2E_LOOP_HINT_REPLY, E2E_LOOP_PROBE_PROMPT, E2E_LOOP_TUTOR_REPLY,
    )
    import agents.function_handlers_e2e as m
    token = next(getattr(m, n) for n in dir(m) if n.startswith("E2E_GRADER_") and "TOKEN" in n)
    for text in (E2E_LOOP_HINT_REPLY, E2E_LOOP_FEEDBACK_REPLY, E2E_LOOP_TUTOR_REPLY, E2E_LOOP_PROBE_PROMPT):
        assert token not in text
    assert E2E_LOOP_PROBE_PROMPT.startswith("[e2e-loop]")


def test_loop_tutor_handler_makes_no_tool_calls(monkeypatch):
    """Same constraint as test_e2e_tutor_handler_makes_no_tool_calls_and_no_graph_writes."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    monkeypatch.setenv("SAPLING_FUNCTION_HANDLERS", "agents.function_handlers_e2e")
    from agents.loop_tutor import loop_tutor_agent  # name per HANDOFF-07; adapt
    with loop_tutor_agent.override(model=model_for("loop_tutor")):
        result = loop_tutor_agent.run_sync("teach me", deps=_deps())
    from agents.function_handlers_e2e import E2E_LOOP_TUTOR_REPLY
    assert result.output == E2E_LOOP_TUTOR_REPLY
    assert all(p.part_kind != "tool-call" for msg in result.all_messages() for p in msg.parts)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && venv/bin/python -m pytest tests/test_e2e_function_handlers.py -q -k loop`
Expected: FAIL — `ImportError: cannot import name 'E2E_LOOP_HINT_REPLY'`.

- [ ] **Step 3: Implement.** Read `agents/loop_tutor.py` and pick, for the hint prompt and the feedback prompt, one distinctive sentence fragment (≥ 12 chars) that appears verbatim in the prompt source. Then, in `function_handlers_e2e.py`, replace PKG-07's `_loop_tutor_handler` block with:

```python
# ── Learning loop (PKG-13) ──────────────────────────────────────────────────
#
# One handler, three fixed replies keyed on the PHASE prompt loop_tutor.py
# composes (agents/loop_tutor.py). Phase detection is a substring scan over
# every text part of the history — system and user — because the route may
# carry the phase in either. Values in E2E_LOOP_PHASE_PATTERNS are copied
# from the prompt source; tests/test_e2e_function_handlers.py pins that.
# Asserted verbatim by frontend/e2e/learn-loop.spec.ts. Keep in sync.

E2E_LOOP_PHASE_PATTERNS: dict[str, str] = {
    "hint": "<verbatim fragment of the hint-rung prompt>",
    "feedback": "<verbatim fragment of the feedback prompt>",
}
# Prefix of every seeded loop check item's PLAINTEXT prompt
# (db/seed_local_rich.py imports it); the spec asserts the probe card shows it.
E2E_LOOP_PROBE_PROMPT = "[e2e-loop] Probe item: state the e2e grader token to be marked correct."
E2E_LOOP_HINT_REPLY = (
    "[e2e-function-model] Deterministic loop HINT (H1): what is the first "
    "thing you need before you can answer this?"
)
E2E_LOOP_FEEDBACK_REPLY = (
    "[e2e-function-model] Deterministic loop FEEDBACK: your answer matched "
    "the rubric; next we check a nearby idea."
)


def _all_text(messages) -> str:
    out: list[str] = []
    for message in messages:
        for part in getattr(message, "parts", None) or []:
            content = getattr(part, "content", "")
            if isinstance(content, str):
                out.append(content)
    return "\n".join(out)


def _loop_tutor_handler(messages, info) -> ModelResponse:
    text = _all_text(messages)
    if E2E_LOOP_PHASE_PATTERNS["hint"] in text:
        return ModelResponse(parts=[TextPart(content=E2E_LOOP_HINT_REPLY)])
    if E2E_LOOP_PHASE_PATTERNS["feedback"] in text:
        return ModelResponse(parts=[TextPart(content=E2E_LOOP_FEEDBACK_REPLY)])
    return ModelResponse(parts=[TextPart(content=E2E_LOOP_TUTOR_REPLY)])


register_function_handler("loop_tutor", _loop_tutor_handler)
```

Keep `E2E_LOOP_TUTOR_REPLY` where PKG-07 defined it; do not rename any existing constant. If the hint and feedback prompts share the pattern, choose a fragment unique to each; if `loop_tutor.py` injects the phase only through the user message, the scan still finds it.

- [ ] **Step 4: Run tests, lint**

Run: `cd backend && venv/bin/python -m pytest tests/test_e2e_function_handlers.py tests/test_learning_loop_invariants.py -q -k "loop or inv_06 or inv_12" && venv/bin/ruff check .`
Expected: loop handler tests pass; inv_06/inv_12 still pass; `All checks passed!`

- [ ] **Step 5: Commit**

```
git add backend/agents/function_handlers_e2e.py backend/tests/test_e2e_function_handlers.py
git commit -m "feat(learning-loop): PKG-13 — phase-aware loop_tutor function handler and E2E_LOOP_* constants

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 3: Seed the opted-in student + lane env

**Files:**
- Modify: `backend/db/seed_local_rich.py`, `scripts/e2e-up.sh`, `.github/workflows/e2e.yml`, `scripts/explore.sh`, `backend/.env.local.example` (one commented line)
- Test: `backend/tests/test_learning_seed_loop_user.py`

**Interfaces:**
- Consumes: `learning.params` (`CHECK_ITEM_DIFFICULTIES`, `CHECK_ITEM_MIN_RUBRIC`, `CHECK_ITEM_MIN_WRONG`, `EDGE_PREREQ_SOURCE_IS_PREREQ`), `learning.checks.question_hash` (PKG-04; verify the name and its argument — plaintext prompt), `services.encryption`, the PKG-05 grader token constant, `E2E_LOOP_PROBE_PROMPT`.
- Produces: `seed_local_rich.USER_LOOP`, `ENR_LOOP_CS_S26`, `LOOP_NODES`, `LOOP_EDGES`, `SEED_LOOP_CONCEPTS`, `SEED_LOOP_ITEMS_PER_CONCEPT`, `seed_learning_loop()`; `LEARNING_LOOP_ENABLED=true` in the lane.

- [ ] **Step 1: Write the failing test**

```python
"""PKG-13: the rich seed carries one opted-in loop student with a prerequisite
chain and encrypted check items. Hermetic — `db.seed_helpers.table` and the
seed's own `table` are replaced by a recorder; nothing reaches PostgREST."""
from __future__ import annotations

import json

import pytest

from db import seed_helpers
from db import seed_local_rich as seed
from learning.params import CHECK_ITEM_DIFFICULTIES, CHECK_ITEM_MIN_RUBRIC, CHECK_ITEM_MIN_WRONG
from services.encryption import decrypt_if_present


class _Recorder:
    def __init__(self):
        self.rows: dict[str, list[dict]] = {}

    def __call__(self, name):
        rec = self
        class _T:
            def select(self, cols, filters=None, limit=None):
                return []
            def upsert(self, row, on_conflict=None):
                rec.rows.setdefault(name, []).append(row)
            def insert(self, row):
                rec.rows.setdefault(name, []).append(row)
        return _T()


@pytest.fixture
def recorder(monkeypatch):
    r = _Recorder()
    monkeypatch.setattr(seed_helpers, "table", r)
    monkeypatch.setattr(seed, "table", r)
    seed_helpers.reset_counts()
    seed.seed_learning_loop()
    return r


def test_loop_user_is_opted_in_and_enrolled(recorder):
    settings = [r for r in recorder.rows["user_settings"] if r["user_id"] == seed.USER_LOOP]
    assert settings and settings[0]["learning_loop_beta"] is True
    users = [r for r in recorder.rows["users"] if r["id"] == seed.USER_LOOP]
    assert users and users[0]["is_approved"] and users[0]["onboarding_completed"]
    assert any(r["user_id"] == seed.USER_LOOP for r in recorder.rows["enrollments"])


def test_legacy_users_are_not_opted_in(recorder):
    for row in recorder.rows.get("user_settings", []):
        assert row["user_id"] == seed.USER_LOOP


def test_prerequisite_chain(recorder):
    nodes = [r for r in recorder.rows["graph_nodes"] if r["user_id"] == seed.USER_LOOP]
    assert len(nodes) == seed.SEED_LOOP_CONCEPTS
    assert all(r["mastery_score"] == 0.0 and r["mastery_tier"] == "unexplored" for r in nodes)
    edges = [r for r in recorder.rows["graph_edges"] if r["user_id"] == seed.USER_LOOP]
    assert len(edges) == seed.SEED_LOOP_CONCEPTS - 1
    assert all(r["relationship_type"] == "prerequisite" for r in edges)
    ids = {r["id"] for r in nodes}
    assert all(r["source_node_id"] in ids and r["target_node_id"] in ids for r in edges)


def test_check_items_encrypted_and_hashed(recorder):
    items = recorder.rows["check_items"]
    assert len(items) == seed.SEED_LOOP_CONCEPTS * seed.SEED_LOOP_ITEMS_PER_CONCEPT
    assert sorted({r["difficulty"] for r in items}) == sorted(CHECK_ITEM_DIFFICULTIES)
    for r in items:
        plain = decrypt_if_present(r["prompt"])
        assert plain != r["prompt"], "prompt stored in plaintext"
        assert plain.startswith("[e2e-loop]")
        assert decrypt_if_present(r["reference_answer"]) != r["reference_answer"]
        assert len(json.loads(decrypt_if_present(r["rubric_json"]))) >= CHECK_ITEM_MIN_RUBRIC
        assert len(json.loads(decrypt_if_present(r["common_wrong_json"]))) >= CHECK_ITEM_MIN_WRONG
        assert r["format"] == "free" and r["graded"] is False
        assert len(r["question_hash"]) == 64
    assert len({(r["node_id"], r["question_hash"]) for r in items}) == len(items)


def test_no_learner_state_seeded(recorder):
    assert "learner_state" not in recorder.rows
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_seed_loop_user.py -q`
Expected: ERROR — `AttributeError: module 'db.seed_local_rich' has no attribute 'seed_learning_loop'`.

- [ ] **Step 3: Implement the seed.** Add after the `USER_*` ids (`:63–67`):

```python
# Learning loop (PKG-13): the one opted-in student. Legacy rich-* users stay
# on the pre-series path — the E2E lane runs with LEARNING_LOOP_ENABLED=true
# and relies on that split to keep tutor/quiz specs untouched.
USER_LOOP = "rich-user-loop"
ENR_LOOP_CS_S26 = "rich-enr-loop-cs101-s26"
SEED_LOOP_CONCEPTS = 3
# (node_id, concept_name) — a prerequisite chain in order; edges are oriented
# by learning.params.EDGE_PREREQ_SOURCE_IS_PREREQ at write time.
LOOP_NODES = [
    ("rich-node-loop-binary", "Binary Numbers"),
    ("rich-node-loop-bitwise", "Bitwise Operators"),
    ("rich-node-loop-twos", "Two's Complement"),
]
```

Add the user tuple to `_USERS` (`onboarding_completed=True, is_approved=True, streak_count=3`, profile `{"name": "Lou Loop", "first_name": "Lou", "last_name": "Loop", "username": "rich-loop", "year": "Sophomore", "majors": ["Computer Science"], "minors": [], "learning_style": "visual"}`) and the enrollment tuple `(ENR_LOOP_CS_S26, USER_LOOP, OFF_CS_S26, "#4f86f7", "Intro CS (loop)", "raw", None, None)` to `_ENROLLMENTS`. Then add the step (after `seed_sessions`):

```python
def seed_learning_loop() -> None:
    """PKG-13: opted-in loop student — settings flag, prerequisite chain,
    encrypted check items. Imports are function-local: `learning.*` and the
    function-handler constant are only needed here, and importing
    agents.function_handlers_e2e registers handlers as a harmless side
    effect in this CLI process."""
    import json

    from agents.function_handlers_e2e import E2E_LOOP_PROBE_PROMPT
    from learning.checks import question_hash
    from learning.params import CHECK_ITEM_DIFFICULTIES, EDGE_PREREQ_SOURCE_IS_PREREQ

    h.upsert("user_settings", {"user_id": USER_LOOP, "learning_loop_beta": True}, on_conflict="user_id")

    for node_id, concept in LOOP_NODES:
        h.upsert(
            "graph_nodes",
            {
                "id": node_id, "user_id": USER_LOOP, "course_id": COURSE_CS,
                "concept_name": concept, "subject": concept.split()[0],
                "mastery_score": 0.0, "mastery_tier": get_mastery_tier(0.0),
            },
            on_conflict="user_id,course_id,concept_name",
        )
    for (prereq_id, _), (dep_id, _) in zip(LOOP_NODES, LOOP_NODES[1:]):
        src, tgt = (prereq_id, dep_id) if EDGE_PREREQ_SOURCE_IS_PREREQ else (dep_id, prereq_id)
        h.upsert(
            "graph_edges",
            {
                "id": f"rich-edge-loop-{prereq_id.rsplit('-', 1)[1]}-{dep_id.rsplit('-', 1)[1]}",
                "user_id": USER_LOOP, "source_node_id": src, "target_node_id": tgt,
                "relationship_type": "prerequisite", "strength": 0.9,
            },
            on_conflict="user_id,source_node_id,target_node_id,relationship_type",
        )

    for node_id, concept in LOOP_NODES:
        for difficulty in CHECK_ITEM_DIFFICULTIES:
            prompt = f"{E2E_LOOP_PROBE_PROMPT} [{concept}, difficulty {difficulty}]"
            h.upsert(
                "check_items",
                {
                    "id": f"rich-check-{node_id.rsplit('-', 1)[1]}-d{difficulty}",
                    "node_id": node_id, "course_id": COURSE_CS, "document_id": None,
                    "format": "free", "difficulty": difficulty,
                    "prompt": encrypt_if_present(prompt),                       # 🔒
                    "reference_answer": encrypt_if_present(GRADER_CORRECT_TOKEN),  # 🔒
                    "rubric_json": encrypt_json([                                # 🔒
                        {"id": "r1", "text": "States the e2e grader token."},
                        {"id": "r2", "text": f"Names {concept}."},
                    ]),
                    "common_wrong_json": encrypt_json([                          # 🔒
                        {"key": "wrong_token", "text": "Gives a different token."},
                    ]),
                    "source_chunk_ids": [], "question_hash": question_hash(prompt), "graded": False,
                },
                on_conflict="node_id,question_hash",
            )
```

`GRADER_CORRECT_TOKEN` is the PKG-05 constant (HANDOFF-05 names it; import it beside `E2E_LOOP_PROBE_PROMPT`). If `learning.checks.question_hash` takes anything other than the plaintext prompt, follow its signature. If PKG-04's `services/check_item_service.py` exposes a create helper that encrypts and hashes, you may call it instead of the direct upsert — but the test above must still pass unchanged (it reads the recorded rows), so prefer the direct upsert. `SEED_LOOP_ITEMS_PER_CONCEPT = len(CHECK_ITEM_DIFFICULTIES)` is defined at module top via a lazy import inside a tiny helper, or hardcoded as `3` with a comment citing `CHECK_ITEM_DIFFICULTIES` and a test assertion (`test_check_items_encrypted_and_hashed` already pins the difficulties set). Call `seed_learning_loop()` from `main()` after `seed_sessions()`; add `"user_settings"` and `"check_items"` to `_SUMMARY_ORDER`; note `user_settings` is truncated and re-seeded per test by the Playwright fixture (it is not in either denylist), which is what keeps the opt-in stable across specs.

- [ ] **Step 4: Lane env.** In `scripts/e2e-up.sh`, immediately after the `export QUIZ_GENERATE_RATE_LIMIT=…` line, add:

```bash
# Learning loop series (PKG-13): the lane boots with the loop flag ON. Only
# the seeded rich-user-loop is opted in (user_settings.learning_loop_beta), so
# every legacy spec keeps the pre-series path; frontend/e2e/learn-loop.spec.ts
# is the one journey on the loop path. Exported, so it beats backend/.env.
export LEARNING_LOOP_ENABLED="${LEARNING_LOOP_ENABLED:-true}"
echo "  ℹ LEARNING_LOOP_ENABLED=$LEARNING_LOOP_ENABLED for this stack (PKG-13; only rich-user-loop is opted in)"
```

In `.github/workflows/e2e.yml` add `LEARNING_LOOP_ENABLED: "true"` to the "Boot the stack" `env:` block with a one-line comment; in `scripts/explore.sh` add `export LEARNING_LOOP_ENABLED=true` beside the seam exports (`:398–410`); in `backend/.env.local.example` add a commented `# LEARNING_LOOP_ENABLED=true   # learning loop beta (PKG-00); the E2E lane exports it` line.

- [ ] **Step 5: Run tests, lint, and a real seed round-trip against the local database** (the seed runs under the lane later; here prove it is idempotent in isolation, under the lock):

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_seed_loop_user.py tests/test_learning_loop_invariants.py -q -k "seed or inv_13b" && venv/bin/ruff check . && bash -n ../scripts/e2e-up.sh`
Expected: all passed; `All checks passed!`; no bash syntax error.

Run: `flock /tmp/claude-$(id -u)/sapling-e2e-stack.lock -c 'cd backend && supabase start >/dev/null 2>&1; SUPABASE_DB_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres venv/bin/python -m db.migrate && venv/bin/python -m db.seed_local_rich && venv/bin/python -m db.seed_local_rich | tail -n 4'`
Expected: first run prints `check_items created=9`, `user_settings created=1`; second run prints `TOTAL created 0` and `(all rows already present — re-run was a no-op)`.

- [ ] **Step 6: Commit**

```
git add backend/db/seed_local_rich.py backend/tests/test_learning_seed_loop_user.py scripts/e2e-up.sh scripts/explore.sh .github/workflows/e2e.yml backend/.env.local.example
git commit -m "feat(learning-loop): PKG-13 — seed opted-in loop student and enable the flag in the E2E lane

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 4: API client + stream events + pure phase reducer

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Create: `frontend/src/components/learn/loopState.ts`, `frontend/src/components/learn/useLoopStatus.ts`
- Test: `frontend/src/lib/api.loop.test.ts`, `frontend/src/components/learn/loopState.test.ts`

**Interfaces:**
- Consumes: `fetchJSON`, `consumeChatStream`, `ApiError` (`api.ts`).
- Produces (all exported from `api.ts`): types `LoopPhase`, `LoopCheckItem`, `LoopLearnerState`, `LoopPlanConcept`, `LoopHintResponse`, `LoopCloseResponse`; functions `getLoopStatus(userId)`, `startLoopProbe(userId, courseId)`, `answerLoopProbe(sessionId, userId, questionHash, {answer?, reason?, idk})`, `getLoopPlan(sessionId, userId)`, `approveLoopPlan(sessionId, userId)`, `streamLoopChat(sessionId, userId, message, handlers)`, `postLoopAttempt(sessionId, userId, questionHash, text)`, `requestLoopHint(sessionId, userId, questionHash, text?)`, `closeLoopSession(sessionId, userId, answers?)`, `getLoopReviewNext(userId)`; `StreamChatHandlers` gains `onPhase`, `onCheck`, `onHintOffer`, `onLearnerState`; `ChatResult` gains `leak_redacted?: boolean`. From `loopState.ts`: `LoopUiState`, `LoopUiEvent`, `initialLoopState()`, `reduceLoopEvent(state, ev)`. From `useLoopStatus.ts`: `useLoopStatus(userId, userReady): boolean | null`.

- [ ] **Step 0: Verify the contract.** Run `grep -n "^@router\.\(get\|post\)" backend/routes/learn_loop.py` and `grep -n "class .*Body\|class .*Response" backend/routes/learn_loop.py backend/models/__init__.py | grep -i loop`. Fill a path → body → response table in your scratch notes from THOSE plus HANDOFF-07/08/09/12. Every client function below targets that table, not this prompt's "expected" one. Record each difference for the hand-off's Deviations.

- [ ] **Step 1: Write the failing tests**

`frontend/src/components/learn/loopState.test.ts`:
```ts
import { describe, expect, it } from 'vitest';

import { initialLoopState, reduceLoopEvent } from './loopState';

const item = { question_hash: 'qh1', format: 'free' as const, difficulty: 1 as const, prompt: 'p', node_id: 'n1' };

describe('reduceLoopEvent', () => {
  it('starts in probe with no item', () => {
    expect(initialLoopState()).toMatchObject({ phase: 'probe', item: null, hintOffer: null, leakRedacted: false });
  });
  it('phase events move the phase and nothing else', () => {
    const s = reduceLoopEvent({ ...initialLoopState(), item }, { type: 'phase', phase: 'teach' });
    expect(s.phase).toBe('teach');
    expect(s.item).toEqual(item);
  });
  it('check sets the current item and clears a stale hint offer', () => {
    const s = reduceLoopEvent({ ...initialLoopState(), hintOffer: 1 }, { type: 'check', item });
    expect(s.item).toEqual(item);
    expect(s.hintOffer).toBeNull();
  });
  it('hint_offer records the rung', () => {
    expect(reduceLoopEvent(initialLoopState(), { type: 'hint_offer', rung: 1 }).hintOffer).toBe(1);
  });
  it('learner_state is keyed by node_id and overwrites', () => {
    let s = reduceLoopEvent(initialLoopState(), { type: 'learner_state', state: { node_id: 'n1', p_known: 0.4, band: 'develop' } });
    s = reduceLoopEvent(s, { type: 'learner_state', state: { node_id: 'n1', p_known: 0.6, band: 'develop' } });
    expect(s.learnerState.n1.p_known).toBe(0.6);
  });
  it('done with leak_redacted flips the flag; without it clears', () => {
    const on = reduceLoopEvent(initialLoopState(), { type: 'done', leakRedacted: true });
    expect(on.leakRedacted).toBe(true);
    expect(reduceLoopEvent(on, { type: 'done', leakRedacted: false }).leakRedacted).toBe(false);
  });
  it('never advances the phase on its own', () => {
    const s = reduceLoopEvent(initialLoopState(), { type: 'done', leakRedacted: false });
    expect(s.phase).toBe('probe');
  });
});
```

`frontend/src/lib/api.loop.test.ts` (copy `sseBody`/`ev` from `api.stream.test.ts:3–14`):
```ts
import { afterEach, describe, expect, it, vi } from 'vitest';

import { getLoopStatus, streamLoopChat } from './api';

function sseBody(blocks: string[]): ReadableStream { /* as api.stream.test.ts */ }
const ev = (name: string, data: unknown) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`;
afterEach(() => vi.restoreAllMocks());

describe('getLoopStatus', () => {
  it('404 (flag off) resolves inactive instead of throwing', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ detail: 'learning loop not enabled' }), { status: 404 }),
    );
    await expect(getLoopStatus('u')).resolves.toEqual({ active: false });
  });
  it('active passes through', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ active: true }), { status: 200 }));
    await expect(getLoopStatus('u')).resolves.toEqual({ active: true });
  });
  it('a 5xx still throws (fail closed is the caller\'s job)', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('boom', { status: 503 }));
    await expect(getLoopStatus('u')).rejects.toBeTruthy();
  });
});

describe('streamLoopChat', () => {
  it('dispatches phase/check/hint_offer/learner_state and returns leak_redacted', async () => {
    const check = { question_hash: 'qh', format: 'free', difficulty: 2, prompt: 'p', node_id: 'n' };
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(sseBody([
      ev('phase', { type: 'phase', step: 'loop', message: '', data: { phase: 'check' } }),
      ev('token', { type: 'token', step: 'reply', message: '', data: { delta: 'Hi' } }),
      ev('check', { type: 'check', step: 'loop', message: '', data: check }),
      ev('hint_offer', { type: 'hint_offer', step: 'loop', message: '', data: { rung: 1 } }),
      ev('learner_state', { type: 'learner_state', step: 'loop', message: '', data: { node_id: 'n', p_known: 0.5, band: 'develop' } }),
      ev('done', { type: 'done', step: 'reply', message: '', data: { reply: 'Hi [redacted]', graph_update: {}, mastery_changes: [], leak_redacted: true } }),
    ])));
    const seen: string[] = [];
    const res = await streamLoopChat('s', 'u', 'm', {
      onToken: (d) => seen.push(`token:${d}`),
      onPhase: (p) => seen.push(`phase:${p}`),
      onCheck: (i) => seen.push(`check:${i.question_hash}`),
      onHintOffer: (r) => seen.push(`offer:${r}`),
      onLearnerState: (s) => seen.push(`state:${s.node_id}:${s.p_known}`),
    });
    expect(seen).toEqual(['phase:check', 'token:Hi', 'check:qh', 'offer:1', 'state:n:0.5']);
    expect(res.reply).toBe('Hi [redacted]');
    expect(res.leak_redacted).toBe(true);
    const [url, init] = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(String(url)).toContain('/api/learn/loop/chat/stream');
    expect(JSON.parse(String((init as RequestInit).body))).toMatchObject({ session_id: 's', user_id: 'u', message: 'm' });
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/lib/api.loop.test.ts src/components/learn/loopState.test.ts`
Expected: FAIL — `getLoopStatus is not exported` / `Cannot find module './loopState'`.

- [ ] **Step 3: Implement.** In `api.ts`, after `startSessionStream`:

```ts
// ── Learning loop (PKG-13) ──────────────────────────────────────────────────
// Clients for /api/learn/loop/* (backend/routes/learn_loop.py). Every route
// 404s when the gate is false (spec §7); only getLoopStatus swallows that.
export type LoopPhase = 'probe' | 'plan' | 'teach' | 'check' | 'feedback' | 'close';
export type LoopBand = 'novice' | 'develop' | 'profic';
export interface LoopCheckItem {
  question_hash: string; format: 'free' | 'teachback' | 'mc_reason'; difficulty: 1 | 2 | 3;
  prompt: string; node_id: string; concept_name?: string; options?: { key: string; text: string }[];
}
export interface LoopLearnerState { node_id: string; p_known: number; band: LoopBand }
export interface LoopPlanConcept { node_id: string; concept_name: string; p_known: number; band: LoopBand; is_review: boolean }
export interface LoopHintResponse { allowed: boolean; reason?: string; rung?: number; reply?: string }
export interface LoopCloseResponse { phase: LoopPhase; summary: string; self_eval_question: string; if_then_prompt: string }

export const getLoopStatus = async (userId: string): Promise<{ active: boolean }> => {
  try {
    return await fetchJSON<{ active: boolean }>(`/api/learn/loop/status?user_id=${encodeURIComponent(userId)}`);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return { active: false }; // flag off → legacy
    throw err;
  }
};
// … startLoopProbe / answerLoopProbe / getLoopPlan / approveLoopPlan /
// postLoopAttempt / requestLoopHint / closeLoopSession / getLoopReviewNext:
// thin fetchJSON wrappers over the paths in your Step-0 table.
export const streamLoopChat = (sessionId: string, userId: string, message: string, handlers: StreamChatHandlers = {}) =>
  consumeChatStream('/api/learn/loop/chat/stream', { session_id: sessionId, user_id: userId, message }, handlers);
```

Extend `StreamChatHandlers` (`:355`) with `onPhase?: (phase: LoopPhase) => void; onCheck?: (item: LoopCheckItem) => void; onHintOffer?: (rung: number) => void; onLearnerState?: (s: LoopLearnerState) => void;`, `ChatResult` (`:295`) with `leak_redacted?: boolean;`, and `consumeChatStream` (`:383–392`) with four `else if` branches before `done` (`ev.type === 'phase'` → `onPhase?.(String(ev.data?.phase) as LoopPhase)`, etc.). Check `ApiError` exposes `status` (it is constructed with `res.status` at `:116`; confirm the field name).

`loopState.ts`: the reducer exactly as the test describes (`phase`, `item`, `hintOffer`, `learnerState: Record<string, LoopLearnerState>`, `leakRedacted`); pure, no React import.

`useLoopStatus.ts`:
```ts
import { useEffect, useState } from 'react';
import { getLoopStatus } from '@/lib/api';

/** null = unresolved; false = legacy tree; true = loop tree. Fails closed. */
export function useLoopStatus(userId: string, userReady: boolean): boolean | null {
  const [active, setActive] = useState<boolean | null>(null);
  useEffect(() => {
    if (!userReady) return;
    if (!userId) { setActive(false); return; }
    let cancelled = false;
    getLoopStatus(userId)
      .then((r) => { if (!cancelled) setActive(Boolean(r.active)); })
      .catch(() => { if (!cancelled) setActive(false); });
    return () => { cancelled = true; };
  }, [userId, userReady]);
  return active;
}
```

- [ ] **Step 4: Run tests, typecheck, lint**

Run: `cd frontend && npx vitest run src/lib/api.loop.test.ts src/lib/api.stream.test.ts src/components/learn/loopState.test.ts && npx tsc --noEmit && npm run lint`
Expected: all passed; clean; lint clean.

- [ ] **Step 5: Commit**

```
git add frontend/src/lib/api.ts frontend/src/lib/api.loop.test.ts frontend/src/components/learn/loopState.ts frontend/src/components/learn/loopState.test.ts frontend/src/components/learn/useLoopStatus.ts
git commit -m "feat(learning-loop): PKG-13 — loop API clients, stream events, phase reducer

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 5: `LoopLearn` + the `Learn` branch + testids

**Files:**
- Modify: `frontend/src/components/learn/LoopLearn.tsx` (replace the stub), `frontend/src/components/screens/Learn.tsx` (`Learn()` only), `frontend/eslint.config.mjs` (`files` array), `docs/frontend-testids.md` (table row + inventory section `### \`loop\``)
- Test: `npx tsc --noEmit`, `npm run lint` (the testid rule is the test: every `<button>/<input>/<textarea>` in `LoopLearn.tsx` must carry a testid), plus the Playwright journey in Task 7.

**Interfaces:**
- Consumes: Task 4's clients and reducer, `ChatPanel` (`components/chat/ChatPanel.tsx:33–53` props: `messages`, `onSend`, `header`, `streamingText`, `onStop`), `useUser`, `useToast`, `getEnrolledCourses` (or the course source HANDOFF-08 names), `DisclaimerModal`, `FullHeightScreen`, `TopBar` (same imports `Learn.tsx` uses).
- Produces: `export function LoopLearn()`; the testids below.

- [ ] **Step 1: Testids.** Add to `docs/frontend-testids.md`: table row `| Learning loop | \`loop\` | \`frontend/src/components/learn/LoopLearn.tsx\` (the loop-path Learn screen an opted-in student gets; PKG-13) |` and an inventory section:

```
### `loop`

| testid | element |
| --- | --- |
| `loop-phase` | root container; `data-phase` = probe / plan / teach / check / feedback / close |
| `loop-probe-item` | the current probe card; `data-question-hash` |
| `loop-probe-input` | free/teachback answer textarea |
| `loop-probe-option-{key}` | one `mc_reason` option button, suffixed with the option key |
| `loop-probe-reason` | the one-sentence reason input (`mc_reason`) |
| `loop-probe-submit` | submit the probe answer |
| `loop-probe-idk` | "I don't know" (submits idk, no answer) |
| `loop-plan-concept-{nodeId}` | one planned concept row (name, band, review badge) |
| `loop-plan-approve` | approve the plan |
| `loop-messages` | the teach/check/feedback chat log (`ChatPanel`, `role="log"` — reuse `tutor-messages`? NO: LoopLearn wraps ChatPanel in a `loop-messages` container; ChatPanel's own ids stay) |
| `loop-check-prompt` | the current check item; `data-question-hash` |
| `loop-attempt-input` | attempt textarea; first keystroke posts /step/attempt |
| `loop-attempt-submit` | submit the attempt as a chat turn |
| `loop-hint-button` | request a hint |
| `loop-hint-denied` | denial line; `data-reason` |
| `loop-hint-reply` | the hint text when allowed |
| `loop-hint-offer` | the "Want a hint?" affordance (hint_offer event) |
| `loop-learner-state` | current concept belief; `data-node-id`, `data-p-known`, `data-band` |
| `loop-continue` | send the next turn after feedback |
| `loop-close-button` | end the session (calls /close) |
| `loop-close-summary` | the close summary text |
| `loop-close-self-eval` | self-evaluation answer input |
| `loop-close-if-then` | if-then plan input |
| `loop-close-submit` | submit the close answers |
| `loop-close-done` | rendered after the close answers persist |
```

Add `"src/components/learn/LoopLearn.tsx",` to the `files` array in `eslint.config.mjs` (after `"src/components/screens/Learn.tsx",`).

- [ ] **Step 2: Implement `LoopLearn.tsx`.** Structure (write the full component; the shape below is the contract, not a code dump):

```tsx
"use client";
// Learning loop (PKG-13): the Learn screen an opted-in student gets.
// Phase is SERVER-DRIVEN — reduceLoopEvent never advances it on its own.
// Spec: docs/superpowers/specs/2026-09-26-learning-loop-design.md §9.
export function LoopLearn() {
  const { userId } = useUser();
  const toast = useToast();
  const [state, dispatch] = useReducer(reduceLoopEvent, undefined, initialLoopState);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [streamingText, setStreamingText] = useState<string | null>(null);
  const [plan, setPlan] = useState<LoopPlanConcept[]>([]);
  const [hint, setHint] = useState<LoopHintResponse | null>(null);
  const [close, setClose] = useState<LoopCloseResponse | null>(null);
  const attemptPosted = useRef<Set<string>>(new Set());   // question_hash → /step/attempt sent
  const streamAbort = useRef<AbortController | null>(null);
  // mount: startLoopProbe(userId, courseId) → setSessionId, dispatch check/phase
  // probe submit / idk → answerLoopProbe → dispatch({type:'check', item}) or phase
  // plan phase → getLoopPlan → setPlan; approve → approveLoopPlan → phase
  // teach/check/feedback: send(text) → streamLoopChat with onToken/onPhase/onCheck/
  //   onHintOffer/onLearnerState/signal; on done: settle the bubble with
  //   res.leak_redacted ? res.reply : (accumulated || res.reply); dispatch done
  // attempt input onChange: if (!attemptPosted.current.has(qh)) { post; add }
  // hint click → requestLoopHint(sessionId, userId, qh, draft) → setHint
  // close click → closeLoopSession → setClose; submit → closeLoopSession(..., {self_eval, if_then}) → done
  return (
    <FullHeightScreen>
      <DisclaimerModal />
      <div data-testid="loop-phase" data-phase={state.phase}> …phase panels… </div>
    </FullHeightScreen>
  );
}
```

Rules: no numeric literal for timing (no client-side timers at all — the gate is server-side); the settled reply after a `leak_redacted` done is `res.reply` and the streamed bubble text is discarded; a `ChatStreamError` surfaces via `toast.error` and leaves the phase unchanged; `signal` aborts on unmount (same `streamAbort` pattern as `Learn.tsx:590–593`). The `loop-learner-state` element renders the concept the current item belongs to (`state.learnerState[state.item?.node_id]`) and is present (empty attributes) even before any event, so the spec can wait on its attributes.

- [ ] **Step 3: The branch in `Learn.tsx`.** Replace `Learn()` (`:327–333`) with:

```tsx
export function Learn() {
  const { userId, userReady } = useUser();
  // Learning loop (PKG-13): one GET decides the tree. null → the same
  // fallback the legacy Suspense shows; false / 404 / error → legacy, unchanged.
  const loop = useLoopStatus(userId, userReady);
  if (loop === null) return <div style={{ padding: 40, color: "var(--text-dim)" }}>Loading…</div>;
  if (loop) return <LoopLearn />;
  return (
    <Suspense fallback={<div style={{ padding: 40, color: "var(--text-dim)" }}>Loading…</div>}>
      <LearnInner />
    </Suspense>
  );
}
```

Import `LoopLearn` and `useLoopStatus`. `useUser` is already imported (`:22`). Nothing below `:335` changes.

- [ ] **Step 4: Typecheck, lint, unit tests**

Run: `cd frontend && npx tsc --noEmit && npm run lint && npm test`
Expected: clean; lint clean (if lint lists untagged elements in `LoopLearn.tsx`, tag them — never baseline them); all unit tests pass.

- [ ] **Step 5: Commit**

```
git add frontend/src/components/learn/LoopLearn.tsx frontend/src/components/screens/Learn.tsx frontend/eslint.config.mjs docs/frontend-testids.md
git commit -m "feat(learning-loop): PKG-13 — LoopLearn phase UI and the Learn branch on loop status

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 6: `learn_loop` oracle

**Files:**
- Create: `backend/e2e_oracles/learn_loop.py` (pure judge, stdlib only — `e2e_oracles/__init__.py` contract)
- Modify: `backend/e2e_oracles/gather.py` (add `run_learn_loop`), `backend/e2e_oracles/__main__.py` (`CHECKS` entry + docstring), `backend/e2e_oracles/findings.py` (oracle name comment)
- Test: `backend/tests/test_e2e_oracles_learn_loop.py`

**Interfaces:**
- Produces: `learn_loop.learn_loop_findings(evidence_pairs, state_rows, leak_count, step_payloads, node_scores) -> list[Finding]`; `gather.run_learn_loop(args) -> tuple[list[Finding], int]`; check name `learn_loop`.

- [ ] **Step 1: Write the failing tests**

```python
"""Pure tests for the PKG-13 `learn_loop` oracle judge (spec §8 inv 1, §6)."""
from e2e_oracles.learn_loop import ORACLE_P_TOLERANCE, learn_loop_findings


def _clean():
    return dict(
        evidence_pairs=[("u", "n1")],
        state_rows=[{"user_id": "u", "node_id": "n1", "p_known": 0.61}],
        leak_count=0,
        step_payloads=[{"p_known_before": 0.35, "p_known_after": 0.61}],
        node_scores=[{"id": "n1", "mastery_score": 0.61}],
    )


def test_clean_run_has_no_findings():
    assert learn_loop_findings(**_clean()) == []


def test_evidence_without_learner_state_is_a_single_writer_finding():
    kw = _clean(); kw["state_rows"] = []
    f = learn_loop_findings(**kw)
    assert len(f) == 1 and f[0].oracle == "learn_loop" and "learner_state" in f[0].summary


def test_any_leak_event_is_a_finding():
    kw = _clean(); kw["leak_count"] = 2
    assert any("zpd.leak" in x.summary for x in learn_loop_findings(**kw))


def test_step_payload_bounds_and_missing_keys():
    kw = _clean(); kw["step_payloads"] = [{"p_known_before": 1.2, "p_known_after": 0.5}, {"p_known_after": 0.5}]
    f = learn_loop_findings(**kw)
    assert len(f) == 2 and all("zpd.step" in x.summary for x in f)


def test_mastery_score_must_mirror_p_known():
    kw = _clean(); kw["node_scores"] = [{"id": "n1", "mastery_score": 0.61 + 10 * ORACLE_P_TOLERANCE}]
    f = learn_loop_findings(**kw)
    assert len(f) == 1 and "mastery_score" in f[0].summary


def test_untouched_nodes_are_not_compared():
    kw = _clean(); kw["node_scores"].append({"id": "n2", "mastery_score": 0.0})
    assert learn_loop_findings(**kw) == []


def test_cli_registers_learn_loop():
    from e2e_oracles import __main__ as cli
    assert "learn_loop" in cli.CHECKS
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && venv/bin/python -m pytest tests/test_e2e_oracles_learn_loop.py -q`
Expected: ERROR — `ModuleNotFoundError: No module named 'e2e_oracles.learn_loop'`.

- [ ] **Step 3: Implement.** `e2e_oracles/learn_loop.py`:

```python
"""`learn_loop` oracle (PKG-13): the learning loop's write invariants, judged
over already-gathered rows. Pure — stdlib only, no IO (e2e_oracles contract).

(a) single writer: every evidence event's (user, node) has a learner_state row
    (spec §8 inv 1 — only apply_graph_update writes both, so one without the
    other means a second writer exists);
(b) no zpd.leak events (spec §6 — a leak is an error-category event);
(c) every zpd.step payload carries p_known_before/after in [0, 1];
(d) graph_nodes.mastery_score mirrors learner_state.p_known on evidence-touched
    nodes (spec §5), within ORACLE_P_TOLERANCE.
"""
from __future__ import annotations

from e2e_oracles.findings import Finding

ORACLE_P_TOLERANCE = 1e-9  # † mirror equality; floats written from one value


def learn_loop_findings(
    evidence_pairs: list[tuple[str, str]],
    state_rows: list[dict],
    leak_count: int,
    step_payloads: list[dict],
    node_scores: list[dict],
) -> list[Finding]:
    findings: list[Finding] = []
    state = {(r["user_id"], r["node_id"]): r["p_known"] for r in state_rows}

    missing = sorted({(u, n) for u, n in evidence_pairs if (u, n) not in state})
    if missing:
        findings.append(Finding(
            oracle="learn_loop",
            summary=f"{len(missing)} evidence-touched (user, node) pair(s) have no learner_state row",
            evidence={"sample": missing[:20]},
        ))

    if leak_count:
        findings.append(Finding(oracle="learn_loop", summary=f"{leak_count} zpd.leak event(s) recorded", evidence={"count": leak_count}))

    for i, p in enumerate(step_payloads):
        for key in ("p_known_before", "p_known_after"):
            v = p.get(key)
            if not isinstance(v, (int, float)) or not (0.0 <= float(v) <= 1.0):
                findings.append(Finding(oracle="learn_loop", summary=f"zpd.step payload #{i} {key} out of [0,1] or missing", evidence={"value": v}))

    touched = {n for _, n in evidence_pairs}
    p_by_node = {n: p for (_, n), p in state.items()}
    for row in node_scores:
        nid = row["id"]
        if nid not in touched or nid not in p_by_node:
            continue
        if abs(float(row["mastery_score"]) - float(p_by_node[nid])) > ORACLE_P_TOLERANCE:
            findings.append(Finding(
                oracle="learn_loop",
                summary=f"graph_nodes.mastery_score != learner_state.p_known for {nid}",
                evidence={"mastery_score": row["mastery_score"], "p_known": p_by_node[nid]},
            ))
    return findings
```

`gather.run_learn_loop(args)`: `conn = _db_conn()`; if `information_schema.tables` lacks `learner_state` → return `[Finding(oracle="oracle-error", summary="learner_state table missing — PKG-03 migration not applied?")], 0`; else run the five queries (`SELECT DISTINCT g.user_id, e.node_id FROM node_mastery_events e JOIN graph_nodes g ON g.id = e.node_id WHERE e.event_type = 'evidence'`; `SELECT user_id, node_id, p_known FROM learner_state`; `SELECT count(*) AS n FROM events WHERE event_type = 'zpd.leak'`; `SELECT payload FROM events WHERE event_type = 'zpd.step'`; `SELECT id, mastery_score FROM graph_nodes WHERE id = ANY(%s)` with the touched ids) and return `learn_loop.learn_loop_findings(...)`, `0`. Table-wide on purpose: `args.user` is ignored (the loop user is not the CLI default). Register `"learn_loop": lambda args: gather.run_learn_loop(args)` in `CHECKS`; update the `__main__` docstring's check list and the `Finding.oracle` comment.

- [ ] **Step 4: Run tests, lint**

Run: `cd backend && venv/bin/python -m pytest tests/test_e2e_oracles_learn_loop.py tests/test_e2e_oracles_cli.py tests/test_e2e_oracles_judges.py -q && venv/bin/ruff check .`
Expected: all passed; `All checks passed!`

- [ ] **Step 5: Commit**

```
git add backend/e2e_oracles backend/tests/test_e2e_oracles_learn_loop.py
git commit -m "feat(learning-loop): PKG-13 — learn_loop oracle (single writer, no leaks, step bounds, mirror)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 7: The journey + the full E2E cycle

**Files:**
- Create: `frontend/e2e/support/params.ts`
- Modify: `frontend/e2e/learn-loop.spec.ts` (replace the stub), `frontend/e2e/support/stack.ts` (add `USER_LOOP`)
- Test: the spec itself, run under the stack lock.

**Interfaces:**
- Consumes: `mintStorageState` (`support/session.ts`), `queryRaw` (`support/db.ts`), `decryptText` (`support/decrypt.ts`), the `E2E_*` constants (mirrored literals with the `Must match` comment — the Task-1 invariant checks them).
- Produces: `support/params.ts::learningParams(names) → Record<string, number|boolean>` (python shell-out, same venv/env resolution as `decrypt.ts`), `support/stack.ts::USER_LOOP = "rich-user-loop"`.

- [ ] **Step 1: `params.ts`** — copy `decrypt.ts`'s spawn shape with this program: `import json, sys; from learning import params; names = json.load(sys.stdin); sys.stdout.write(json.dumps({n: getattr(params, n) for n in names}))`. Export `learningParams(names: string[]): Promise<Record<string, number | boolean>>`.

- [ ] **Step 2: Write the journey**

```ts
/**
 * Journey (learning loop, PKG-13): an opted-in student walks the whole loop —
 * probe → plan → teach/check (hint gate) → feedback → close — and every
 * belief change lands in the database through apply_graph_update.
 *
 * Determinism: function mode (SAPLING_MODEL_MODE=function,
 * SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e) plus
 * LEARNING_LOOP_ENABLED=true (scripts/e2e-up.sh). The seeded rich-user-loop
 * is the only opted-in user (db/seed_local_rich.py::seed_learning_loop).
 * The grader is scripted: an answer carrying GRADER_CORRECT_TOKEN grades
 * correct. Learning constants are read from backend/learning/params.py via
 * support/params.ts — never as literals here.
 */
import { expect, test } from "./support/fixtures";
import { queryRaw } from "./support/db";
import { decryptText } from "./support/decrypt";
import { learningParams } from "./support/params";
import { mintStorageState } from "./support/session";
import { USER_LOOP } from "./support/stack";

/** Must match backend/agents/function_handlers_e2e.py::E2E_LOOP_PROBE_PROMPT */
const LOOP_PROBE_PROMPT = "[e2e-loop] Probe item: state the e2e grader token to be marked correct.";
/** Must match backend/agents/function_handlers_e2e.py::E2E_LOOP_TUTOR_REPLY */
const LOOP_TUTOR_REPLY = "<copy PKG-07's value verbatim>";
/** Must match backend/agents/function_handlers_e2e.py::E2E_LOOP_HINT_REPLY */
const LOOP_HINT_REPLY = "[e2e-function-model] Deterministic loop HINT (H1): what is the first " +
  "thing you need before you can answer this?";
/** Must match backend/agents/function_handlers_e2e.py::E2E_LOOP_FEEDBACK_REPLY */
const LOOP_FEEDBACK_REPLY = "[e2e-function-model] Deterministic loop FEEDBACK: your answer matched " +
  "the rubric; next we check a nearby idea.";
/** Must match backend/agents/function_handlers_e2e.py::E2E_GRADER_CORRECT_TOKEN */
const GRADER_CORRECT_TOKEN = "<copy PKG-05's value verbatim>";
/** Must match backend/agents/function_handlers_e2e.py::E2E_CLOSE_SUMMARY */
const CLOSE_SUMMARY = "<copy PKG-09's value verbatim; adapt the constant name to HANDOFF-09>";

// Harness constants (†, not learning parameters — see PKG-13 §Named constants).
const LOOP_JOURNEY_TIMEOUT_MS = 240_000;
const GATE_POLL_MARGIN_MS = 15_000;
const DB_POLL_TIMEOUT_MS = 5_000;

test("opted-in student completes probe → plan → check with a gated hint → close, and the loop writes land", async ({ browser }) => {
  test.setTimeout(LOOP_JOURNEY_TIMEOUT_MS);
  const P = await learningParams(["BKT_L0", "PROBE_ITEMS_PER_SKILL_MIN", "PROBE_SESSION_CAP", "GATE_INDEPENDENT_MIN_S"]);
  const context = await browser.newContext({ storageState: await mintStorageState(USER_LOOP, "Lou Loop") });
  const page = await context.newPage();
  await page.addInitScript(() => { localStorage.setItem("sapling_disclaimer_ack", "true"); });

  // ── Probe ─────────────────────────────────────────────────────────────────
  await page.goto("/learn");
  const phase = page.getByTestId("loop-phase");
  await expect(phase).toHaveAttribute("data-phase", "probe");
  const probeItem = page.getByTestId("loop-probe-item");
  await expect(probeItem).toContainText(LOOP_PROBE_PROMPT);

  let answered = 0;
  while ((await phase.getAttribute("data-phase")) === "probe" && answered < Number(P.PROBE_SESSION_CAP)) {
    const qh = await probeItem.getAttribute("data-question-hash");
    await page.getByTestId("loop-probe-input").fill(GRADER_CORRECT_TOKEN);
    await page.getByTestId("loop-probe-submit").click();
    answered += 1;
    // The server serves a different item or flips the phase; wait for either.
    await expect
      .poll(async () =>
        (await phase.getAttribute("data-phase")) !== "probe" ||
        (await probeItem.getAttribute("data-question-hash").catch(() => null)) !== qh,
      )
      .toBe(true);
  }
  expect(answered).toBeGreaterThanOrEqual(Number(P.PROBE_ITEMS_PER_SKILL_MIN));

  // ── Plan ──────────────────────────────────────────────────────────────────
  await expect(phase).toHaveAttribute("data-phase", "plan");
  await expect(page.locator("[data-testid^='loop-plan-concept-']").first()).toBeVisible();
  await page.getByTestId("loop-plan-approve").click();

  // ── Teach / check ─────────────────────────────────────────────────────────
  await expect(phase).toHaveAttribute("data-phase", /teach|check/);
  const log = page.getByTestId("loop-messages");
  await expect(log).toContainText(LOOP_TUTOR_REPLY);
  const check = page.getByTestId("loop-check-prompt");
  await expect(check).toBeVisible();
  const checkHash = await check.getAttribute("data-question-hash");
  expect(checkHash).toBeTruthy();

  // Hint before any attempt → denied with a reason from learning/gates.py.
  await page.getByTestId("loop-hint-button").click();
  const denied = page.getByTestId("loop-hint-denied");
  await expect(denied).toBeVisible();
  expect(await denied.getAttribute("data-reason")).toBeTruthy();

  // First keystroke posts /step/attempt → sessions.loop_state records it.
  await page.getByTestId("loop-attempt-input").fill("working: ");
  const sessionRows = async () =>
    (await queryRaw(`SELECT id, loop_state FROM sessions WHERE user_id = $1`, [USER_LOOP])) as
      { id: string; loop_state: Record<string, { attempted_at?: unknown[] }> }[];
  await expect
    .poll(async () => {
      const rows = await sessionRows();
      return rows.some((r) => (r.loop_state?.[checkHash!]?.attempted_at?.length ?? 0) >= 1);
    }, { timeout: DB_POLL_TIMEOUT_MS })
    .toBe(true);

  // The independent-time gate (GATE_INDEPENDENT_MIN_S †) is server-side: poll
  // the Hint button until the rung unlocks. No client timer exists to skip it.
  await expect
    .poll(async () => {
      await page.getByTestId("loop-hint-button").click();
      return (await page.getByTestId("loop-hint-reply").textContent().catch(() => "")) ?? "";
    }, { timeout: Number(P.GATE_INDEPENDENT_MIN_S) * 1000 + GATE_POLL_MARGIN_MS, intervals: [2_000] })
    .toContain(LOOP_HINT_REPLY);

  // Correct attempt → graded_check_tool → feedback phase.
  await page.getByTestId("loop-attempt-input").fill(`working: ${GRADER_CORRECT_TOKEN}`);
  await page.getByTestId("loop-attempt-submit").click();
  await expect(phase).toHaveAttribute("data-phase", "feedback");
  await expect(log).toContainText(LOOP_FEEDBACK_REPLY);
  const learner = page.getByTestId("loop-learner-state");
  await expect.poll(async () => Number(await learner.getAttribute("data-p-known"))).toBeGreaterThan(Number(P.BKT_L0));

  // ── Close ─────────────────────────────────────────────────────────────────
  await page.getByTestId("loop-close-button").click();
  await expect(phase).toHaveAttribute("data-phase", "close");
  await expect(page.getByTestId("loop-close-summary")).toContainText(CLOSE_SUMMARY);
  await page.getByTestId("loop-close-self-eval").fill("I can convert small binary numbers now.");
  await page.getByTestId("loop-close-if-then").fill("If I see a bitwise problem, then I will write the bits out first.");
  await page.getByTestId("loop-close-submit").click();
  await expect(page.getByTestId("loop-close-done")).toBeVisible();

  // ── Database: the loop's writes, through apply_graph_update ──────────────
  const states = (await queryRaw(
    `SELECT node_id, p_known FROM learner_state WHERE user_id = $1`, [USER_LOOP],
  )) as { node_id: string; p_known: number }[];
  expect(states.length).toBeGreaterThan(0);
  expect(Math.max(...states.map((s) => Number(s.p_known)))).toBeGreaterThan(Number(P.BKT_L0));

  const evidence = (await queryRaw(
    `SELECT count(*)::int AS n FROM node_mastery_events e JOIN graph_nodes g ON g.id = e.node_id
      WHERE g.user_id = $1 AND e.event_type = 'evidence'`, [USER_LOOP],
  )) as { n: number }[];
  expect(evidence[0].n).toBeGreaterThan(0);

  const closed = (await queryRaw(
    `SELECT close_json, close_phase FROM sessions WHERE user_id = $1 AND close_json IS NOT NULL`, [USER_LOOP],
  )) as { close_json: string; close_phase: string }[];
  expect(closed).toHaveLength(1);
  expect(closed[0].close_json).not.toContain("summary");          // ciphertext at rest
  expect(await decryptText(closed[0].close_json)).toContain("summary"); // decrypts to the JSON

  const events = (await queryRaw(
    `SELECT DISTINCT event_type FROM events WHERE user_id = $1 AND event_type = ANY($2)`,
    [USER_LOOP, ["zpd.step", "learn.session_closed", "zpd.leak"]],
  )) as { event_type: string }[];
  const types = events.map((e) => e.event_type).sort();
  expect(types).toEqual(["learn.session_closed", "zpd.step"]);   // and NO zpd.leak

  await context.close();
});

test("legacy user still gets the pre-series Learn screen with the flag on", async ({ page }) => {
  await page.addInitScript(() => { localStorage.setItem("sapling_disclaimer_ack", "true"); });
  await page.goto("/learn");
  await expect(page.getByTestId("tutor-topic-picker")).toBeVisible();
  await expect(page.getByTestId("loop-phase")).toHaveCount(0);
});
```

Adapt: the close flow (one call or two), the attempt/hint body fields, the `loop_state` key shape (`attempted_at` per spec §4 PKG-06 comment), and the name of PKG-09's close constant — all from the hand-offs. If the gate needs a SUBMITTED wrong answer rather than `/step/attempt` to count as genuine (HANDOFF-06 `genuine_attempt`), insert a wrong submit (`"working: not the token"`) before the hint poll and expect the corrective-feedback phase in between; record it as a deviation from this prompt's flow.

- [ ] **Step 3: Run the full cycle under the lock** (this is the package's self-check step 5; the exact block):

```
flock /tmp/claude-$(id -u)/sapling-e2e-stack.lock -c '
  export SAPLING_MODEL_MODE=function
  export SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e
  export GEMINI_API_KEY=e2e-dummy-key-no-billing
  make e2e-up || { make e2e-down; exit 2; }
  (cd frontend && npx playwright test e2e/learn-loop.spec.ts); rc1=$?
  (cd frontend && npx playwright test); rc2=$?
  (cd backend && venv/bin/python -m e2e_oracles); rc3=$?
  make e2e-down
  echo "loop=$rc1 all=$rc2 oracles=$rc3"
  [ "$rc1$rc2$rc3" = "000" ]
'
```

Expected: `loop=0 all=0 oracles=0`; the oracle prints `0 finding(s), 0 suppressed (allowlisted).`; the full suite count is S₀ + 2. A red `learn-loop.spec.ts`: read `.e2e/backend.log` first (a `UnregisteredHandlerError` means a request-path task has no handler — that is a PKG-04/05/07 gap, fix as a reopened package; a byte-match to an `E2E_*` constant in a "wrong" reply is the seam working). A red legacy spec is a regression in `Learn()` — the branch, not the loop. Never edit `logscan.ALLOWLIST`.

- [ ] **Step 4: Commit**

```
git add frontend/e2e/learn-loop.spec.ts frontend/e2e/support/params.ts frontend/e2e/support/stack.ts
git commit -m "test(learning-loop): PKG-13 — learn-loop browser journey with DB and oracle assertions

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 8: Hand-off + ledger

- [ ] **Step 1:** Write `docs/superpowers/plans/learning-loop/HANDOFF-13.md` from `HANDOFF-template.md`. "Verify commands" must be exactly these three lines:

```
(under the stack lock) make e2e-up && (cd frontend && npx playwright test e2e/learn-loop.spec.ts) && (cd backend && venv/bin/python -m e2e_oracles); make e2e-down → journey passed, oracles exit 0
cd frontend && npx tsc --noEmit                                                                   → clean
grep -c "E2E_LOOP_" backend/agents/function_handlers_e2e.py                                      → ≥ 3
```

Under "Constants chosen" list every † from the Named-constants table (`SEED_LOOP_CONCEPTS`, `SEED_LOOP_ITEMS_PER_CONCEPT`, `LOOP_JOURNEY_TIMEOUT_MS`, `GATE_POLL_MARGIN_MS`, `ORACLE_P_TOLERANCE`, and the `GATE_INDEPENDENT_MIN_S` wait the journey pays). Under "Symbols added" list the route → client mapping you verified in Task 4 Step 0 (the table is the series' only frontend-facing record of the loop API). Under "Open questions": whether the lane should get a gate override to cut the `GATE_INDEPENDENT_MIN_S` wait (PKG-06 owner decides; this package waits honestly); whether `Learn()`'s one extra GET for legacy users should be cached in `UserContext` (PKG-14 decides).

- [ ] **Step 2:** Ledger. Append `| 13 | frontend-e2e | done | feat/learning-loop-13-frontend-e2e | <sha> | 6 modules + 1 spec | — | HANDOFF-13.md |`, plus `verified` rows for 08, 09, 12 (`verified-by: 13, <date>, <command → output>` from the State-of-the-world rows). Add Deviations for every contract difference from Task 4 Step 0 and every † the spec did not name.

- [ ] **Step 3: Commit**

```
git add docs/superpowers/plans/learning-loop/HANDOFF-13.md docs/superpowers/plans/learning-loop/LEDGER.md
git commit -m "docs(learning-loop): PKG-13 — hand-off and ledger

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 9: PR

- [ ] **Step 1:** Run the self-check loop one last time (below), then:

```
gh pr create --title "feat(learning): PKG-13 frontend-e2e" --body-file - <<'EOF'
Learning loop series, package 13 of 15. Spec: docs/superpowers/specs/2026-09-26-learning-loop-design.md §9.

- LoopLearn: server-driven probe → plan → teach/check → feedback → close UI; Learn() branches on GET /api/learn/loop/status (404/false → legacy tree, unchanged)
- api.ts: /api/learn/loop/* clients; consumeChatStream handles phase/check/hint_offer/learner_state + done.leak_redacted
- function-mode seam: phase-aware loop_tutor handler, E2E_LOOP_* constants pinned to the spec by tests/test_learning_loop_invariants.py::test_inv_13a
- seed: rich-user-loop (learning_loop_beta=true), 3-concept prerequisite chain, 9 encrypted check_items; LEARNING_LOOP_ENABLED=true in e2e-up.sh / e2e.yml / explore.sh
- frontend/e2e/learn-loop.spec.ts: full journey + DB asserts (learner_state, evidence events, close_json ciphertext, zpd.step / learn.session_closed, no zpd.leak)
- e2e_oracles learn_loop: single writer, no leaks, zpd.step bounds, mastery_score mirrors p_known

Flag-off behaviour: /status 404s → legacy Learn; no loop client call is made. Legacy specs green on the flag-on stack (only rich-user-loop is opted in).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
```

## Self-check loop (run after every task, and once more before the PR)

1. `cd backend && venv/bin/ruff check . && venv/bin/ruff format --check learning tests/test_learning_*.py`
2. `venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q`
3. `venv/bin/python -m pytest tests/ -q` (no `SAPLING_MODEL_MODE` exported)
4. Prompts/tool descriptions touched? **No** in this package → skip evals. (`function_handlers_e2e.py` is scripted output, not a prompt. If you find yourself editing `agents/loop_tutor.py`, `agents/grader.py`, or any `tests/evals/*`, stop: that is a reopened package, not this one.)
5. Request-path agent or route touched? **Yes — the frontend consumes them and the seam handler changed** → the E2E cycle is REQUIRED: the Task 7 Step 3 block, verbatim, under ONE `flock` around up → test → down. Run it after Task 7 and again before the PR. Also `cd frontend && npx tsc --noEmit && npm run lint && npm test` after Tasks 4, 5, 7.
6. Scope check: `git diff --stat main...HEAD` — every path must be in this prompt's Files lists. Anything else: `git checkout main -- <path>` or record a Deviation.
7. Sync check: `diff <(git show main:backend/agents/function_handlers_e2e.py | grep -o "E2E_[A-Z_]*" | sort -u) <(grep -o "E2E_[A-Z_]*" backend/agents/function_handlers_e2e.py | sort -u)` — the only lines are `> E2E_LOOP_FEEDBACK_REPLY`, `> E2E_LOOP_HINT_REPLY`, `> E2E_LOOP_PHASE_PATTERNS`, `> E2E_LOOP_PROBE_PROMPT`; nothing removed.

Green = all seven clean. Max 5 iterations per loop; then write a `BLOCKED` row in `LEDGER.md` with hypothesis, commands, outputs, and stop.

## Regression guard

- Backend suite count N₁₂ (from State of the world) unchanged except for the tests this package adds (`test_learning_loop_invariants.py` +2, `test_e2e_function_handlers.py` +6, `test_learning_seed_loop_user.py`, `test_e2e_oracles_learn_loop.py`). Zero failures, zero new skips.
- Dependency modules stay green and untouched: `tests/test_learning_check_tool.py` (05), `tests/test_learning_zpd_policy.py` (06), `tests/test_learn_loop_routes.py` (07), `tests/test_learning_probe_planner.py` (08), `tests/test_learning_close_brief.py` (09), `tests/test_learning_review.py` (12).
- Pre-series suites touched by this package: `tests/test_e2e_function_handlers.py` (every pre-existing test unchanged), `tests/test_e2e_oracles_cli.py`, `tests/test_e2e_oracles_judges.py`, `tests/test_e2e_oracles_logscan.py`, `tests/test_model_mode_seam.py`, `tests/test_event_capture_seams.py`.
- Frontend: `npm test` count unchanged except `+2` files; `api.stream.test.ts` unchanged and green (the four new stream branches must not alter token/graph_update/error/done handling).
- Browser lane: every pre-existing spec passes on the flag-ON stack (`tutor.spec.ts`, `streaming.spec.ts`, `quiz*.spec.ts`, `dashboard.spec.ts` all render Learn or its deep links for legacy users). Full-suite count = S₀ + 2.
- Oracles: `graph`, `counts`, `ciphertext`, `logscan`, `orphans`, `ragstore` produce the same `0 finding(s)` as on `main`; `learn_loop` adds none.
- With `LEARNING_LOOP_ENABLED` unset locally (`python main.py` without the export): `GET /api/learn/loop/status` → 404 and `/learn` renders the legacy picker.

## Acceptance criteria (the next session pastes these)

1. `(under the stack lock) make e2e-up && (cd frontend && npx playwright test e2e/learn-loop.spec.ts) && (cd backend && venv/bin/python -m e2e_oracles); make e2e-down` → journey passed (2 tests), `0 finding(s)`, exit 0
2. `cd frontend && npx tsc --noEmit` → clean
3. `grep -c "E2E_LOOP_" backend/agents/function_handlers_e2e.py` → ≥ 3
4. `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k inv_13` → `2 passed`
5. `cd backend && venv/bin/python -m pytest tests/ -q` → zero failures; `venv/bin/ruff check .` → `All checks passed!`
6. `cd frontend && npm test && npm run lint` → all passed; lint clean
7. `grep -n "LEARNING_LOOP_ENABLED" scripts/e2e-up.sh .github/workflows/e2e.yml scripts/explore.sh` → ≥ 1 hit each
8. `grep -c '"learn_loop"' backend/e2e_oracles/__main__.py` → 1
9. `git diff --stat main...HEAD` lists only: `frontend/src/components/learn/*`, `frontend/src/components/screens/Learn.tsx`, `frontend/src/lib/api.ts`, `frontend/src/lib/api.loop.test.ts`, `frontend/e2e/learn-loop.spec.ts`, `frontend/e2e/support/{params,stack}.ts`, `frontend/eslint.config.mjs`, `docs/frontend-testids.md`, `backend/agents/function_handlers_e2e.py`, `backend/db/seed_local_rich.py`, `backend/e2e_oracles/*`, `backend/tests/test_learning_loop_invariants.py`, `backend/tests/test_e2e_function_handlers.py`, `backend/tests/test_learning_seed_loop_user.py`, `backend/tests/test_e2e_oracles_learn_loop.py`, `scripts/e2e-up.sh`, `scripts/explore.sh`, `.github/workflows/e2e.yml`, `backend/.env.local.example`, `docs/superpowers/plans/learning-loop/{HANDOFF-13.md,LEDGER.md}` (plus any reopened-package files, each with its own first commit).
10. `LEDGER.md` has row `13 | frontend-e2e | done | …` and `verified` rows for 08, 09, 12.

## Hand-off

`docs/superpowers/plans/learning-loop/HANDOFF-13.md` per the template; the Verify commands block is fixed above (Task 8). Headings: What changed · Symbols added · Constants chosen · Deviations from spec · Known gaps · Verify commands · Open questions for the series owner · Post-hoc changes. Open questions to record: the `GATE_INDEPENDENT_MIN_S` wait in the lane (override or not — PKG-06's call); caching the status GET for legacy users (PKG-14); whether PKG-14's cutover should fold `LoopLearn` into `Learn.tsx` or keep the branch.

## Do not

- Do not edit any route, body model, `services/chat_stream.py`, `services/agent_events.py`, `services/events_service.py`, `services/graph_service.py`, `agents/loop_tutor.py`, `agents/grader.py`, or any `tests/evals/*` — a contract gap is a client adaptation plus a Deviation, or a reopened package with its own first commit.
- Do not advance a phase client-side, add a client-side gate timer, or let the UI skip an attempt; the ZPD gates are server-side (spec §3.3).
- Do not render the streamed tokens when `done.data.leak_redacted` is true; render `done.data.reply`.
- Do not opt in any legacy seeded user; do not seed `learner_state`; do not put plaintext into `check_items.prompt/reference_answer/rubric_json/common_wrong_json` (spec §4); never filter or `UNIQUE` on those columns.
- Do not put a learning constant as a literal in TS, the seed, or the oracle: `learningParams()` in the spec, `from learning.params import …` in Python. Harness constants (`LOOP_JOURNEY_TIMEOUT_MS`, `GATE_POLL_MARGIN_MS`, `DB_POLL_TIMEOUT_MS`, `ORACLE_P_TOLERANCE`, `SEED_LOOP_*`) are named `const`s in their owning file and † in the hand-off.
- Do not run the stack outside ONE `flock /tmp/claude-$(id -u)/sapling-e2e-stack.lock` wrapping up → test → down; never separate flock calls for up and down; always tear down, even after failures.
- Do not edit `backend/e2e_oracles/logscan.py::ALLOWLIST` (stays `()`); do not `test.fixme` the journey to make the lane green; do not add `waitForTimeout` sleeps — poll.
- Do not anchor selectors on copy or CSS classes; every new interactive element in `LoopLearn.tsx` carries a `data-testid` from the inventory (never baseline them).
- Do not rename any existing `E2E_*` constant or testid; do not change `tierForScore`, `LearnInner`, `ChatPanel` props.
- All Supabase access in the seed through `db/connection.py::table()` via `seed_helpers`; the oracle's psycopg connection is `gather._db_conn()` only.
- Do not skip, xfail, or delete any pre-existing test. Do not hand-edit eval cassettes or baselines.
- End every commit with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`; end the PR body with the Claude Code attribution line.

## If you get stuck

1. Re-read §Spec, the hand-offs 07/08/09/12 §Symbols added, and `routes/learn_loop.py` before guessing a route or field name.
2. Journey red: `.e2e/backend.log` first (tracebacks, `UnregisteredHandlerError`, 404 `learning loop not enabled` = the flag export did not reach uvicorn), then `frontend/e2e/results/last-run.json` and the retained trace; compare any "wrong" reply byte-for-byte against `E2E_*` constants before calling it a bug (`docs/e2e-exploration.md` §7).
3. Three failed iterations on one task → append a `BLOCKED` row to `LEDGER.md` (hypothesis, commands run, outputs), commit what is green, open the PR as draft, stop.
4. Never widen scope to unblock. Never disable a test to unblock.
5. Ambiguity → choose the option closest to the spec, mark it `†` in the hand-off, continue.
