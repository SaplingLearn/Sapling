# PKG-13 frontend-e2e — Learning Loop series (16 of 17)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> You are a fresh session. Nothing outside this file, `docs/superpowers/plans/learning-loop/LEDGER.md`, the `HANDOFF-NN.md` files it names, and the files this prompt lists is known to you. Do not infer intent from chat history you do not have. Do not read the whole research corpus; read the sections named below.

## Package id + goal

**PKG-13 `frontend-e2e`.** This package builds the launch UI (spec §11.3; the launch gate §11.1 item 5 requires it). After this package: a student on the loop path (build phase: staff/QA toggle; after launch: every student) sees the loop UI in the Learn screen (probe → plan → teach/check → feedback → close) driven by `/api/learn/loop/*`; `LoopLearn` lists the student's open loop sessions and resumes the newest instead of starting a new probe — a reload of `/learn` never starts a probe — through ONE new read-only route, `GET /api/learn/loop/sessions`; it keeps the knowledge map (rail or `/tree` link), shows no model toggle and sends no `model_pref` (spec §13 A15/A26); the attempt box submits explicit answers to `/check/answer/stream`, never as a chat turn (A16); a budget-pause banner renders from the 429 body or the `budget` stream event (A20/A26), and a "no check items for this course yet" state renders from `no_check_items` (A23); the Study screen's `DueQueue` (PKG-12) gets its launch polish; the SSE consumer understands the five loop events (`phase`, `check`, `hint_offer`, `learner_state`, `budget`) and the leak-redaction flag; the function-mode seam has phase-aware `E2E_LOOP_*` constants served on all three tutor slots; the rich seed carries the two loop users (staff/QA toggle, build phase; spec §13 A14) — `rich-user-loop` with a prerequisite chain and shared encrypted check items, and `rich-user-capped` whose spend today is past the novice budget allowance; `LEARNING_LOOP_ENABLED=true` is part of the E2E lane for the build phase (PKG-14b removes the export); `frontend/e2e/learn-loop.spec.ts` walks the loop, the resume, the budget cap and the build-phase legacy-user split and asserts the database; the `learn_loop` oracle guards the loop's write invariants; and every legacy user, spec, and oracle is unchanged.

Branch: `feat/learning-loop-13-frontend-e2e`. PR title: `feat(learning): PKG-13 frontend-e2e`.

Depends on (spec §14): **08, 09, 12** (and **06b** for the budget-cap journey; transitively 04, 05, 05b, 06, 07, 11).

## Read before you start (in this order)

0. `docs/superpowers/specs/2026-09-26-learning-loop-design.md` **§13 Amendments log** — in force; where this file and §13 disagree, §13 wins. Re-read it before Task 1. The rows that bind this package: **A27** (render the `check` object a teach turn or `POST /check/next` returns; a "Check me" control; a capped student still gets a template opener and the probe), **A26** (frontend: no model toggle, explicit submissions, budget banner, empty state, resume, knowledge map, DueQueue polish, the budget-cap journey), **A16** (the attempt box grades only through `/check/answer(/stream)`), **A23** (`no_check_items`, check items as shared course assets), **A15** (tier routing in code; loop routes ignore `model_pref`; three tutor slots the seam must serve), **A20** (429 body, `budget` stream event, the hard level's "practice and review keep working"), **A14** (wording: `learning_loop_beta` is a build-phase staff/QA toggle, never a student opt-in), **A31** (the toggle is in no settings API field, so the UI can never see it; `/status` is the only input), A2 (check items keyed on `(course_id, concept_key)`), A17 (the check pose is a template turn). And spec **§11.3** (launch UI readiness — this package builds it).
1. The same spec's §3.5–§3.6 (cost/routing/decision constants — the §3.5 budget table and degradation ladder the banner and the cap journey follow), §7 (two-phase gate), §8 (invariants 13–29 — this package owns 13a and 13b; 22 and 26 are the server halves of its no-`model_pref` and explicit-submission rules), §14 (order and dependencies).
2. `docs/superpowers/plans/learning-loop/LEDGER.md` — a package's state is its LATEST row (README "Ledger reading"); refuse to start if any earlier package's latest row is `blocked` or `in-progress`. The latest rows of 00–12, 05b and 06b must be `done`, `verified` or `reopened` (spec §14: packages run strictly one at a time).
3. `docs/superpowers/plans/learning-loop/HANDOFF-07.md`, `HANDOFF-08.md`, `HANDOFF-09.md`, `HANDOFF-12.md` (also `HANDOFF-04.md` — the `check_items` columns and keying the seed writes; `HANDOFF-05.md` — the grader's correct-token constant; `HANDOFF-06.md` and `HANDOFF-06b.md` §Symbols added — the 429 body, `enforce_rate_limit`, the `budget` event levels; `HANDOFF-11.md` — the `flashcards` FSRS columns the capped seed writes). Copy every route path, body model, response key, event name, gate denial reason, and `E2E_*` constant name they list into the scratch table you keep for Task 5 Step 0. **They override the "expected contract" tables in this prompt wherever they differ.**
4. `CLAUDE.md` §Conventions and §Gotchas — especially the E2E-stack-singleton `flock` rule and the function-mode seam paragraph.
5. `docs/superpowers/specs/2026-09-26-learning-loop-design.md` §3.3 (gates: what a genuine attempt is, `OFFER_BANDS`), §3.4 (`PROBE_*`, `PLAN_*`), §3.5 (budget constants and the degradation ladder: what keeps working at the hard level), §6 (event payload keys), §7 (404 when the gate is false), §8 (invariants 1, 5, 6), §9 (session phases, the five stream events, the loop route table incl. `GET /sessions`), §11.3 (launch UI readiness).
6. `docs/superpowers/plans/learning-loop/README.md` and `HANDOFF-template.md`.
7. Research, only these sections: `docs/research/learning-loop/AI tutor learning loop research.md` §"Run each session as probe, plan, step, check, feedback, close" (lines ~58–97: the six phases the UI renders, incl. "Close: a written summary, a self-evaluation, an if-then plan"); `docs/research/learning-loop/ZPD lever tradeoffs and upgrades.md` §"Sapling ZPD policy spec" (lines ~143–234: the GATES block — what the UI must NOT let a student skip — and the LOG block the oracle reads).
8. Code you will modify:
   - `frontend/src/components/screens/Learn.tsx` — `Learn()` wrapper `:327–333` (the branch point), `LearnInner` `:335` (`useUser` at `:338`), `tierForScore` `:88–93` (do not touch; the loop UI reads `band` off the server), the streamed opener `beginSession` `:545–625` (`startSessionStream` call `:599`), the chat turn's `streamChat` call `:777–786` (the `onToken`/`onGraphUpdate`/`signal` handler shape LoopLearn mirrors), entry-screen render `:1231`, active-session render `:1302`, `readResumeParam` (the `?resume=` deep link, pinned by `Learn.resume.test.ts`), `SidebarKnowledgeGraph` `:1753–1790` (the knowledge-map rail LoopLearn mirrors with `KnowledgeGraph`; read, do not export or edit), and the `ModelToggle`/`useModelPref` import `:13` (LoopLearn imports neither).
   - `frontend/src/lib/api.ts` — `ApiError` `:47` (`status`, `body`), `fetchJSON` `:108`, `ChatResult` `:295`, `StreamEvent` `:303`, `ChatStreamError` `:321`, `StreamChatHandlers` `:355`, `consumeChatStream` `:363–397`, `streamChat` `:399`, `startSessionStream` `:422`, `resumeSession` `:511` (the existing session-messages route, `GET /api/learn/sessions/{id}/resume` — not gated, reads `messages`), and PKG-12's `getLoopStatus` / `getReviewNext` / `answerReview` / `getReviewSummary` (HANDOFF-12 §Symbols; `getLoopStatus` exists already — extend it, never add a second one). `frontend/src/lib/sse.ts:36–46` (a non-2xx stream response throws an `Error` whose `message` is the raw body and whose `.status` is set).
   - `frontend/src/components/learn/DueQueue.tsx` (PKG-12) and its `### review` block in `docs/frontend-testids.md` — launch polish only (Task 7).
   - `backend/routes/learn_loop.py` — PKG-07's router: its gate check (`learning_loop_active` → 404), `require_self` pattern, `_phase_for(state)` (the phase `GET /status` reports), the per-route `enforce_rate_limit` attachment (which `GET /sessions` must NOT carry). You add ONE read-only route (Task 4) and change nothing else. `backend/services/academics.py::user_offering_ids_for_course`. `backend/tests/test_learn_loop_routes.py` (PKG-07's route-test client/gate fixtures to reuse).
   - `frontend/src/app/(shell)/learn/page.tsx` — mounts `<Learn />`; unchanged unless the branch must live here (it must not).
   - `backend/agents/function_handlers_e2e.py` — `_last_user_prompt_text` `:81`, the `loop_tutor` handler PKG-07 added and registered for the three tutor slots `loop_tutor`, `loop_tutor_lite`, `loop_tutor_deep` (grep `"loop_tutor`), `E2E_LOOP_TUTOR_REPLY` (PKG-07), `E2E_CHECK_ITEM_*` (PKG-04), `E2E_GRADER_*` (PKG-05), `E2E_CLOSE_*` (PKG-09). `grep -n "^E2E_" backend/agents/function_handlers_e2e.py` and record every name.
   - `backend/tests/test_e2e_function_handlers.py` — `_clean_function_registry` fixture `:44–52`, `_deps()` `:55`, the per-handler test shape `:66–80`.
   - `backend/db/seed_local_rich.py` — header `:1–33` (`_guard_local`, encryption imports), ids `:35–78`, `_USERS` `:162–187`, `seed_users` `:194`, `_ENROLLMENTS` `:230`, `_GRAPH_NODES`/`_GRAPH_EDGES`/`seed_graph` `:259–348`, `_FLASHCARDS`/`seed_flashcards` `:555–586` (the encrypted-card insert the capped user's card copies), `_SUMMARY_ORDER` `:842`, `main` `:852`. `backend/db/seed_helpers.py` (`upsert`, `insert_if_absent`, `exists_by`). `backend/db/migrations/0035_observability.sql:41–57` (`llm_usage` columns; `created_at` defaults to `now()`). `frontend/e2e/support/db.ts` (`TRUNCATE_DENYLIST`, `resetDb`: every mutable table — `user_settings`, `llm_usage`, `flashcards` included — is truncated and re-seeded before EVERY test).
   - `backend/e2e_oracles/__main__.py` (`CHECKS` `:41`), `gather.py` (`_db_conn` `:79`, `run_orphans` `:286` — the shape to mirror), `judges.py` (pure judges), `findings.py`, `__init__.py` (stdlib-only contract). Tests: `backend/tests/test_e2e_oracles_cli.py`, `test_e2e_oracles_judges.py`.
   - `scripts/e2e-up.sh` — the `export QUIZ_GENERATE_RATE_LIMIT` block (#537) just before uvicorn starts; `.github/workflows/e2e.yml` `:103–115` (the "Boot the stack" env block); `scripts/explore.sh:398–410` (the seam exports).
   - `frontend/eslint.config.mjs` `:53–92` (the testid `files` array); `docs/frontend-testids.md` §Naming, §"Where the testids live", §"Adding a surface" (`:602`).
9. Code you will mirror: `frontend/e2e/tutor.spec.ts` (journey style, DB poll `:82–102`, decrypt readback `:107–120`), `frontend/e2e/study-room.spec.ts:120–130` (`browser.newContext({ storageState: await mintStorageState(...) })`), `frontend/e2e/events.spec.ts:96–112` (events-table assertion), `frontend/e2e/support/{fixtures,db,session,stack,decrypt}.ts`, `frontend/src/lib/api.stream.test.ts:1–40` (`sseBody`/`ev` helpers), `frontend/src/components/quiz/QuizScreen.test.tsx:1–40` (the jsdom + Testing Library screen-test shape: `vi.mock("next/navigation")`, `vi.mock("@/context/UserContext")`), `frontend/e2e/global-setup.ts`.
10. `docs/e2e-exploration.md` §7–§8 (triage/promotion: the seam-artifact tell) and §10 (lock protocol).

## State of the world

Verify the base before Task 1. Every row must be green. The PKG-00, PKG-05, PKG-06b, PKG-07, PKG-08, PKG-09 and PKG-12 rows are those packages' hand-off Verify blocks, verbatim (the amendment manifest's canonical blocks).

| check | command | expected |
|---|---|---|
| ledger | `grep -E "^\| (0[0-9]\|05b\|06b\|1[0-2]) " docs/superpowers/plans/learning-loop/LEDGER.md` | 00–12, 05b, 06b: the LATEST row of each listed package is `done`, `verified` or `reopened` (README "Ledger reading"; earlier rows are history); no package's latest row is `planned`, `blocked` or `in-progress` |
| hermetic suite green | `cd backend && venv/bin/python -m pytest tests/ -q -x` | `… passed`, zero failures (note the count N₁₂) |
| lint green | `cd backend && venv/bin/ruff check .` | `All checks passed!` |
| frontend typecheck | `cd frontend && npx tsc --noEmit` | clean |
| frontend unit tests | `cd frontend && npm test` | all passed (note the count) |
| stubs still inert | `cat frontend/src/components/learn/LoopLearn.tsx frontend/e2e/learn-loop.spec.ts` | comment + `export {};` only |
| PKG-12's frontend present | `ls frontend/src/components/learn/DueQueue.tsx && grep -c "export const getLoopStatus" frontend/src/lib/api.ts` | 1 file; `1` (Task 5 extends it, never adds a second) |
| PKG-00 | `cd backend && venv/bin/python -m pytest tests/test_learning_gate.py -q` | `13 passed` |
| PKG-00 | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q` | `4 passed, 8 skipped (later packages raise the passed count)` — expect the passed count to be higher now; zero failures |
| PKG-00 | `cd backend && venv/bin/python -m pytest tests/test_learning_deps.py tests/test_learning_settings_flag.py tests/test_learning_loop_beta_migration.py -q` | all passed |
| PKG-00 | `grep -n "^LEARNING_LOOP_ENABLED" backend/config.py` | 1 hit |
| PKG-00 | `ls backend/db/migrations/*_learning_loop_beta.sql` | 1 file |
| PKG-05 | `cd backend && venv/bin/python -m pytest tests/test_learning_check_tool.py -q` | N passed (N ≥ 16) |
| PKG-05 | `grep -c '"grader"' backend/agents/_providers.py backend/agents/function_handlers_e2e.py` | ≥ 1 each |
| PKG-05 | `grep -c '"grader_second"' backend/agents/_providers.py backend/agents/function_handlers_e2e.py` | ≥ 1 each |
| PKG-05 | `grep -c "^async def grade_answer" backend/agents/tools/check.py` | 1 |
| PKG-05 | `ls backend/db/migrations/*_learning_grader_backend.sql` | 1 file |
| PKG-05 | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_14 or inv_28"` | 2 passed |
| PKG-05 | `cd backend && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/grader.py` | every evaluator ≥ baseline |
| PKG-06b | `cd backend && venv/bin/python -m pytest tests/test_learning_ai_budget.py -q` | N passed (N ≥ 15) |
| PKG-06b | `ls backend/db/migrations/*_learning_llm_usage_tokens.sql` | 1 file |
| PKG-06b | `grep -cE "^(async )?def (check\|rate_limited\|enforce_rate_limit)\(" backend/services/ai_budget.py` | 3 |
| PKG-06b | `grep -c '"ai\.budget_capped"' backend/services/events_service.py` | 1 |
| PKG-06b | `grep -c "cached_tokens" backend/agents/usage.py` | ≥ 1 |
| PKG-06b | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_23 or inv_28"` | 2 passed |
| PKG-07 | `cd backend && venv/bin/python -m pytest tests/test_learn_loop_routes.py -q` | N passed (N ≥ 25) |
| PKG-07 | `grep -c "learn_loop" backend/main.py` | ≥ 1 |
| PKG-07 | `grep -c '"loop_tutor"' backend/agents/_providers.py backend/agents/function_handlers_e2e.py` | ≥ 1 each |
| PKG-07 | `grep -ohE '"loop_tutor(_lite\|_deep)?"' backend/agents/_providers.py \| sort -u \| wc -l` | 3 |
| PKG-07 | `grep -c "learning_loop" backend/agents/chat_tutor.py` | ≥ 1 |
| PKG-07 | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_15 or inv_22 or inv_23 or inv_26 or inv_27 or inv_29"` | 6 passed |
| PKG-07 | `cd backend && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/loop_tutor.py` | every evaluator ≥ baseline for every tier slot |
| PKG-08 | `cd backend && venv/bin/python -m pytest tests/test_learning_probe_planner.py -q` | N passed (N ≥ 15) |
| PKG-08 | `grep -cE "^def (next_probe_item\|probe_done\|novice_floor)\(" backend/learning/probe.py` | 3 |
| PKG-08 | `grep -cE "^def (outer_fringe\|plan)\(" backend/learning/planner.py` | 2 |
| PKG-08 | `grep -c '"learn\.probe_done"\|"learn\.plan_approved"' backend/services/events_service.py` | 2 |
| PKG-09 | `cd backend && venv/bin/python -m pytest tests/test_learning_close_brief.py -q` | N passed (N ≥ 14) |
| PKG-09 | `ls backend/db/migrations/*_learning_session_close.sql` | 1 file |
| PKG-09 | `grep -c "loop_brief" backend/db/migrations/*_learning_session_close.sql` | ≥ 1 |
| PKG-09 | `grep -c "LOOP_HISTORY_TRIM_BLOCK" backend/routes/learn_loop.py` | ≥ 1 |
| PKG-09 | `grep -c '"learn\.session_closed"' backend/services/events_service.py` | 1 |
| PKG-12 | `cd backend && venv/bin/python -m pytest tests/test_learning_review.py -q` | N passed (N ≥ 10) |
| PKG-12 | `grep -c "review/next" backend/routes/learn_loop.py` | ≥ 1 |
| PKG-12 | `grep -c '"review\.served"\|"review\.graded"' backend/services/events_service.py` | 2 |
| E2E lane green on `main` (under the lock, once) | `flock /tmp/claude-$(id -u)/sapling-e2e-stack.lock -c 'export SAPLING_MODEL_MODE=function SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e GEMINI_API_KEY=e2e-dummy-key-no-billing; make e2e-up && (cd frontend && npx playwright test) && (cd backend && venv/bin/python -m e2e_oracles); rc=$?; make e2e-down; exit $rc'` | every spec passed; `0 finding(s)`; exit 0 (note the spec count S₀) |

The `grep -E`/`-cE`/`-ohE` rows above use `\|` inside the alternation (and before `sort`/`wc`) only because Markdown tables eat bare pipes; type them with a bare `|`.

Rule: any red row → STOP. Diagnose, repair on this branch as commit `fix(learning-loop): repair pre-series base — <what>`, record the deviation in `LEDGER.md`, re-run all rows. Never build on a broken base. If the E2E row is red on `main` before you have changed anything, that is a pre-existing lane failure: record it as `BLOCKED` in the ledger and stop — this package cannot be verified on a red lane.

## Spec

### Behaviour

1. **Branch point.** `Learn()` (`Learn.tsx:327`) calls `GET /api/learn/loop/status` once `userReady && userId`. `{active: true}` → render `<LoopLearn />`. `{active: false}`, HTTP 404 (spec §7: flag off), or any error → render the existing `<Suspense><LearnInner /></Suspense>` exactly as today (build phase: failing closed to the legacy tree is correct while the loop is dark; PKG-14 half B narrows it to 404 / `{active: false}` only and renders a retry state on any other error — spec §11.2). While the status is unresolved, render the existing Suspense fallback text (`Loading…`). The status response is the ONLY input: `Learn()` never reads `learning_loop_beta` or any other setting (the server gate decides; after launch it ignores the column, spec §7), so the same code serves the build phase and the launch. Nothing else in `LearnInner` changes; a legacy user's Learn screen differs from today by exactly one GET.
2. **Phases** (spec §9). `LoopLearn` is a single component with a `phase` state machine `probe → plan → teach ⇄ check → feedback → close`. The root carries `data-testid="loop-phase"`, `data-phase="<phase>"` and `data-session-id="<session id or empty>"`. Phase changes come from the server: the response of each loop endpoint carries `phase` (or `done` + `phase`), the stream emits a `phase` event, and a resumed session's phase comes from `GET /sessions`; the client never advances a phase on its own.
3. **Open sessions, resume, and the probe** (spec §11.3, A26; finding F22). On mount, once `userId` and the course are known (the first enrolled course's `course_id` from the existing `getCourses(userId)` client — `{courses: EnrolledCourse[]}`, `api.ts:199`, the same call `Learn.tsx:483` makes — or whatever HANDOFF-08 says the routes need), LoopLearn calls `GET /api/learn/loop/sessions?user_id=&course_id=` (NEW, Behaviour 13) — the student's open loop sessions for that course, newest first.
   - **A `?resume=<id>` that is NOT an open loop session** (spec §11.3: after launch the Dashboard "Where you left off" cards and the Tree resume links still list LEGACY sessions — `Dashboard.tsx:283` `getSessions`, `:596` and `Tree.tsx:418` push `/learn?resume=<id>` — and `/sessions` lists loop sessions only) → open THAT session read-only: `resumeSession(id)` (`GET /api/learn/sessions/{id}/resume`, the existing legacy route), render its transcript in `loop-readonly-transcript` with a "Start a new session" button (`loop-readonly-new-session`, which runs the "New session" path below). It never falls through to `/start-session` or any `/probe/*` call on its own (a probe costs a model call and discards the student's context). A `resumeSession` error → the same retry state as a failed `/sessions` (`loop-sessions-retry`), never a probe.
   - **One or more open** → resume the newest (or the one `readResumeParam(searchParams)` names, when it is in the list — the Dashboard and Tree deep links keep working for loop sessions): set `sessionId`; the phase is the listed `phase` (the server derives it from `loop_state`/`close_phase`); the messages come from the existing session-messages route `resumeSession(sessionId)` (`GET /api/learn/sessions/{id}/resume`), mapped to `ChatMsg`. Then continue the phase: `probe` → `POST /probe/next` with THAT `session_id` (continues the same probe; never a new session); `plan` → `GET /plan`; `teach`/`check`/`feedback` → render the restored log and wait for the student (no turn is sent on resume). A picker (`loop-session-picker`) lists every open session (`loop-session-{sessionId}`: topic + start date; the current one marked `aria-current="true"`); clicking another row resumes it the same way.
   - **None open, or the student clicks "New session"** (`loop-new-session`, always rendered) → `POST /api/learn/loop/start-session` (PKG-07; `{user_id, topic, course_id}`, topic = the course name) → `session_id`; then `POST /probe/next` `{session_id, user_id, course_id}` (PKG-08).
   - **A reload of `/learn` mid-session never starts a probe**: while an open session exists and "New session" was not clicked, LoopLearn calls neither `/start-session` nor, for a session past the probe, any `/probe/*` route (vitest in Task 6; journey in Task 9). A session row exists only after its first loop write (spec §9 lazy rows) — the first `/probe/next` writes it — so a reload before the first probe item is shown may start afresh; that is expected.
   - **Probe items** (`/probe/next` response, HANDOFF-08): render `loop-probe-item` (`data-question-hash`) with the prompt, a free-text answer (`loop-probe-input` + `loop-probe-submit`) for `free`/`teachback`, the served options (`[{letter, text}]`, A22 — never marked correct) as `loop-probe-option-{letter}` plus a one-sentence reason field (`loop-probe-reason`) for `mc_reason`, and an "I don't know" control (`loop-probe-idk`) that submits `idk: true` with no answer text. Each answer posts `POST /probe/answer`; a response with `reference_answer` (a wrong answer or idk — spec §3.3 corrective feedback) renders it in `loop-probe-reference` before the next item; `{graded: false, unavailable: true}` renders a muted "Couldn't grade that one — here's another." line and counts as not asked. Then `POST /probe/next` → the next item, or `{done: true, phase: "plan"}` → the `plan` phase.
4. **Plan.** `GET /api/learn/loop/plan?session_id=&user_id=&course_id=` → the ordered concept list (`loop-plan-concept-{nodeId}`, showing the concept name, the band when the response carries one — never computed client-side from a literal — and a "review" badge when the concept is a due review: `kind === "review"` per HANDOFF-08), plus `loop-plan-approve`. Approving posts `POST /api/learn/loop/plan/approve` `{session_id, user_id, concept_ids}` (the proposed ids, in order) and enters `teach`; the first teach turn is whatever HANDOFF-07/08 name (a server-run opener or a client `/chat/stream` call — record which in the scratch table).
5. **Teach / check** (A16, A17). The chat log (`loop-messages`) streams over `POST /api/learn/loop/chat/stream` using the same `onToken` + streaming-bubble pattern as `Learn.tsx:777–786` (reuse `ChatPanel` with `header` and no `onAction`; the legacy `[ACTION: hint]` path is not the loop's hint). A message typed into the chat is NEVER graded, whatever the phase (invariant 26 is the server half). The current check item comes from a `check` object (spec §9 "Item activation and the current concept", §13 A27): the `check` stream event plus `done.data.check` of the teach turn that activated it (PKG-07 activates after `LOOP_TEACH_TURNS_BEFORE_CHECK` teach turns), or the response of "Check me" — `loop-check-me`, rendered in `teach` whenever no item is current, posts `POST /api/learn/loop/check/next` (`{phase, check, plan_done?}`; `check: null` + `plan_done: true` → a muted "That's every concept in today's plan — close the session when you're ready." line). The `check` object is `{question_hash, format, difficulty, prompt, options}`: `loop-check-prompt` (`data-question-hash`, `data-format`) shows `check.prompt` — the template pose (A17), also saved as an assistant row so a resumed transcript shows it — and, for `mc_reason`, `check.options` (`[{letter, text}]`, never marked correct). A 429 from `/check/next` (a novice concept paused at the hard level) is the budget banner, never a toast. The client never activates an item itself. The attempt box: `loop-attempt-input` (free/teachback) or `loop-attempt-option-{letter}` + `loop-attempt-reason` (`mc_reason`), `loop-attempt-submit`, and `loop-attempt-idk`. On the FIRST keystroke (or option click) for a given `question_hash` it posts `POST /api/learn/loop/step/attempt` once (a ref keyed on `question_hash` prevents re-posting). Submit posts the explicit answer to `POST /api/learn/loop/check/answer/stream` — `{session_id, user_id, question_hash, answer, idk: false}` for free/teachback, `{session_id, user_id, question_hash, option, reason, idk: false}` for `mc_reason`; `loop-attempt-idk` posts `{session_id, user_id, question_hash, idk: true}` with no answer text (field names per PKG-07's `LoopCheckAnswerBody` — `option`, not the probe's `selected_option`; HANDOFF-07 confirms) — never as a chat message. That stream carries the ONE feedback turn (the verdict rides in the phase prefix, A16) through the same handlers as a chat turn. The Hint button (`loop-hint-button`) posts `POST /api/learn/loop/hint`; `allowed: false` renders `loop-hint-denied` with `data-reason="<reason>"` and a plain-English line per reason; `allowed: true` renders the hint text in `loop-hint-reply` and appends it to the log (plus the follow-up turn HANDOFF-07 requires, if any). A `hint_offer` stream event (novice band only, spec §3.3 `OFFER_BANDS`) renders a "Want a hint?" affordance (`loop-hint-offer`) that clicks through to the same Hint call. A `learner_state` event updates `loop-learner-state` (`data-node-id`, `data-p-known`, `data-band`).
6. **Feedback.** The `phase: feedback` event flips the phase; the settled reply is `done.data.reply`. When `done.data.leak_redacted === true`, the rendered bubble is REPLACED by `done.data.reply` (the redacted text), never the streamed tokens — confirm the key names against HANDOFF-07 and adapt. A "Continue" control (`loop-continue`) sends the next turn.
7. **Close.** `loop-close-button` (available in teach/check/feedback) posts `POST /api/learn/loop/close` and renders `loop-close-summary` (the summary text), the self-evaluation question with `loop-close-self-eval`, the if-then prompt with `loop-close-if-then`, and `loop-close-submit`; submitting posts the two answers (second call, or the same route with the fields — per HANDOFF-09) and renders `loop-close-done`.
8. **Inert when the gate is false.** With `LEARNING_LOOP_ENABLED` unset, `/api/learn/loop/status` 404s → `Learn()` renders the legacy tree; `LoopLearn` is never mounted; no loop client function is called except the status GET (and PKG-12's Study-screen status GET). Proven by the vitest test in Task 5 (404 → `false`) and by the legacy specs staying green on a stack whose flag is ON but whose legacy users carry no staff/QA toggle.
9. **Seam.** In function mode the `loop_tutor` handler answers by PHASE: the hint prompt → `E2E_LOOP_HINT_REPLY`; the feedback prompt → `E2E_LOOP_FEEDBACK_REPLY`; anything else → `E2E_LOOP_TUTOR_REPLY` (PKG-07's constant, unchanged). It is registered for all three tutor slots — `loop_tutor`, `loop_tutor_lite`, `loop_tutor_deep` (A15: code picks the slot per run; feedback after a correct answer runs on `loop_tutor_lite`), so the reply never depends on the tier. Phase detection scans every text part of the message history for the substrings in `E2E_LOOP_PHASE_PATTERNS`, whose values are copied from the phase prompts in `agents/loop_tutor.py` (never invented). Still no tool calls from the handler.
10. **Seed** — the loop users (staff/QA toggle, build phase; spec §13 A14). `LOOP_USERS = (USER_LOOP, USER_CAPPED)`, both approved, onboarded, enrolled in `OFF_CS_S26`, `user_settings.learning_loop_beta = true`, each with its own `SEED_LOOP_CONCEPTS` graph nodes in `COURSE_CS` (same concept names) chained by `prerequisite` edges oriented per `learning.params.EDGE_PREREQ_SOURCE_IS_PREREQ`, mastery `0.0`/`unexplored`, no `learner_state` rows.
    - **Check items are course assets** (A2): keyed on `(course_id, concept_key)` with `concept_key = services.graph_service._normalize_concept(concept_name)`, no `node_id` column, written ONCE and shared by both loop users: `SEED_LOOP_ITEMS_PER_CONCEPT` per concept — one per (format in `SEED_LOOP_FORMATS`, difficulty in `CHECK_ITEM_DIFFICULTIES`) — with encrypted columns, `question_hash` over the plaintext prompt, reference answer = the PKG-05 grader's correct token. Six per concept, because the probe never serves a concept's post-test reserve (A23) and must still reach `PROBE_ITEMS_PER_SKILL_MIN`. The in-session check the loop journey answers comes from PKG-07's `_activate_next_item` AFTER the probe, which excludes every seen, revealed and reserve hash (spec §9, A27): a plan concept the probe exhausted is skipped and the cursor advances. If the journey finds no `loop-check-prompt` after "Check me", raise `SEED_LOOP_ITEMS_PER_CONCEPT` (or seed one more concept) — never weaken the exclusion.
    - `rich-user-loop` ("Lou Loop") walks the loop journey and the resume journey.
    - `rich-user-capped` ("Casey Cap", A26) walks the budget-cap journey: ONE `llm_usage` row stamped `now()` (the column default; the Playwright fixture re-seeds before every test) with a tutor-slot `task` and `cost_usd = STUDENT_DAILY_BUDGET_USD × BUDGET_NOVICE_MULTIPLIER × SEED_CAPPED_SPEND_FACTOR`, the first two read from `config` at seed time, never a literal — past the novice allowance, so the hard level applies in every band, while one row stays far below `LEARN_RATE_LIMIT_PER_MIN`, so the journey hits the $ cap and not the rate limit; plus one due flashcard (`CAPPED_FLASHCARD`, encrypted `front`/`back`, `due_at` a day ago). A lane-wide low `STUDENT_DAILY_BUDGET_USD` is NOT used: it would cap every loop journey (A26).
    - `rich-user-active`, `rich-user-second`, `rich-user-new` stay legacy (no `learning_loop_beta`).
11. **Lane env.** `scripts/e2e-up.sh` exports `LEARNING_LOOP_ENABLED="${LEARNING_LOOP_ENABLED:-true}"` before starting uvicorn (same shape and placement as the #537 `QUIZ_GENERATE_RATE_LIMIT` export); `.github/workflows/e2e.yml` and `scripts/explore.sh` set the same value beside the other seam vars. This is the build-phase lane: PKG-14b removes all three explicit exports so the default lane runs the code default (spec §11.4).
12. **Oracle.** `python -m e2e_oracles --check learn_loop` asserts, table-wide: (a) every `node_mastery_events` row with `event_type = 'evidence'` has a `learner_state` row for `(graph_nodes.user_id, node_id)`; (b) zero `events` rows with `event_type = 'zpd.leak'`; (c) every `zpd.step` payload has numeric `p_known_before` and `p_known_after` in `[0, 1]`; (d) for every evidence-touched node, `graph_nodes.mastery_score` equals `learner_state.p_known` within `ORACLE_P_TOLERANCE`. A missing `learner_state` table is an `oracle-error` finding.
13. **`GET /api/learn/loop/sessions`** (NEW, the one route this package adds; spec §9 route table, §11.3). `list_open_sessions(user_id: str, course_id: str, request)` in `routes/learn_loop.py`: `require_self` → PKG-07's gate (404 `{"detail": "learning loop not enabled"}` when false, no read) → `offering_ids = user_offering_ids_for_course(user_id, course_id)` (none → `{"sessions": []}`, no `sessions` read) → ONE read `table("sessions").select("id,topic,started_at,loop_state,close_phase", filters={"user_id": eq, "offering_id": in.(…), "close_json": "is.null", "ended_at": "is.null", "mode": "neq.review"}, order="started_at.desc", limit=LOOP_OPEN_SESSIONS_LIMIT)` → drop rows whose `loop_state` is empty → `{"sessions": [{"session_id", "topic", "started_at", "phase"}]}` with `phase = close_phase or _phase_for(loop_state)` (PKG-07's helper behind `GET /status`, which reports `teach`/`check`/`feedback` and — once PKG-08 stores the probe/plan phase in `loop_state` — `probe`/`plan`; HANDOFF-07/08 name the helper and the key; if `_phase_for` does not know `probe`/`plan`, derive them from `loop_state["probe"]`/`["plan"]` exactly as HANDOFF-08 records and note it as a Deviation). `mode = 'review'` rows are PKG-12's daily review sessions, not resumable loop sessions. Read-only: no write, no model, no event, and **no rate limit** (A20: a failure here must not push a student off the loop UI). Never filters on `close_json` by value (only `is.null`; invariant 9), never reads `model_pref` (invariant 22).
14. **No model toggle** (A15/A26). `LoopLearn` imports neither `ModelToggle` nor `useModelPref`; no loop client function takes or sends `model_pref` (loop routes ignore it anyway — invariant 22 is the server half).
15. **Budget pause banner** (A20/A26, spec §3.5 hard level). A loop call that answers HTTP 429 with `{"detail": "ai budget reached", "reset_at": <iso>}` (from a JSON route: `ApiError.status === 429` + `ApiError.body`; from a stream route: the `sse.ts` `Error` with `.status === 429` and the JSON body as its `message`), or a `budget` stream event with `level: "hard"`, renders `loop-budget-paused` (`role="status"`, `data-reset-at="<iso or empty>"`) with the copy "Tutor chat paused until <reset_at in local time>. Practice and review keep working." and a link to `/study?mode=cards` (`loop-budget-study-link`). It is not a toast and leaves the phase unchanged. While paused, the chat input is disabled; the attempt box, the probe, hint denials and close stay usable (grading, the check-pose template and the deterministic close keep working at the hard level). A `budget` event with `level: "soft"` renders nothing (the downgrade is invisible). At the hard level PKG-07's stream sends `phase`, then `budget`, and ends WITHOUT `done` (so `consumeChatStream` throws "Chat stream ended without a done event."): a stream that delivered a hard `budget` event is the pause, not an error — no toast, no retry. No client timer clears the banner; the next successful tutor turn or a reload does.
16. **No check items** (A23/A26). A `/probe/next` response with `no_check_items: true` renders `loop-no-check-items` ("No check items for this course yet. You can still learn with the tutor; nothing is graded until the course has items.") above the plan; the flow continues to the `plan` phase as the response says.
17. **Knowledge map** (spec §11.3). `loop-tree-link` — a link to `/tree?node=<current item's node_id>` (or `/tree` when no item is current) — is always rendered. On wide screens LoopLearn also renders the knowledge-map rail (`loop-rail`) by reusing `KnowledgeGraph` exactly as `Learn.tsx::SidebarKnowledgeGraph` (`:1753–1790`) feeds it (`getGraph`); on narrow screens the link is the rail's stand-in. No change to `Learn.tsx`'s own rail.
18. **DueQueue launch polish** (spec §11.3; PKG-12 owns the component, this package its launch polish). `DueQueue.tsx` is the launch Study surface. It gains: (a) `review-budget-paused` — the same banner component as Behaviour 15 (`BudgetPausedBanner`), shown when a review call answers 429 `ai budget reached` (the rate limit) or when `/review/summary` reports novice-band concepts paused at the tutor hard level (`paused` > 0 — PKG-12's count per spec §3.5; HANDOFF-12 confirms the key — absent key → only the 429 case, recorded as a Deviation), with the copy "<n> concept(s) paused until your daily AI budget resets. Flashcards and other reviews keep working."; (b) a real "All caught up" state (`review-empty`: "All caught up — nothing is due right now.", plus the due counts from `/review/summary` when present) that never renders a stale item; (c) a `data-testid` on every interactive element, `DueQueue.tsx` added to the eslint testid `files` array, and the `### review` block in `docs/frontend-testids.md` updated (owner line "PKG-12; launch polish PKG-13"). The review flow itself (serve → answer → next) is unchanged.

### Expected route contract (from the PKG-07/08/09/12 prompts — VERIFY against `routes/learn_loop.py` and the hand-offs; the hand-offs win)

| method + path | body | response keys the UI needs | owner |
|---|---|---|---|
| `GET /api/learn/loop/status?user_id=` | — | `active` (plus `session_id, phase, band` when `session_id=` is passed) | PKG-07 |
| `GET /api/learn/loop/sessions?user_id=&course_id=` | — | `sessions[{session_id, topic, started_at, phase}]`, newest first | **PKG-13 (this package)** |
| `POST /api/learn/loop/start-session` | `user_id, topic, course_id` | `session_id` (plus `initial_message?, graph_state?`, and `budget{level, reset_at}` when the student is at the hard level — the opener is then a template and never a 429, A27; the session's first phase is `probe` after PKG-08) | PKG-07/08 |
| `POST /api/learn/loop/probe/next` | `session_id, user_id, course_id` | `done, phase?, no_check_items?` or `done: false, check_item_id, question_hash, node_id, format, difficulty, prompt, options[{letter, text}]\|null` | PKG-08 |
| `POST /api/learn/loop/probe/answer` | `session_id, user_id, course_id, question_hash, answer, selected_option?, reason?, idk` | `graded, correct, p_known, probe_done, novice_floor, reference_answer?` or `graded: false, unavailable: true` | PKG-08 |
| `GET /api/learn/loop/plan?session_id=&user_id=&course_id=` | — | `concepts[{node_id, concept_name, kind, p_known}], order` | PKG-08 |
| `POST /api/learn/loop/plan/approve` | `session_id, user_id, concept_ids` | `phase, concept_ids` | PKG-08 (PKG-09 stores the brief here) |
| `POST /api/learn/loop/chat/stream` | `session_id, user_id, message` — no `model_pref` | SSE: `token, phase, check, hint_offer, learner_state, budget, graph_update, error, done{reply, leak_redacted, phase, …}` | PKG-07 |
| `POST /api/learn/loop/check/answer/stream` (JSON twin `/check/answer`) | `session_id, user_id, question_hash, answer \| (option, reason), idk` (`LoopCheckAnswerBody`) | SSE as `/chat/stream`: ONE feedback turn; `done{reply, leak_redacted, phase, …}` plus the verdict keys HANDOFF-07 names | PKG-07 (A16) |
| `POST /api/learn/loop/check/next` | `session_id, user_id` | `phase, check{question_hash, format, difficulty, prompt, options}\|null, plan_done?` (429 when a novice concept pauses) | PKG-07 (A27) |
| `POST /api/learn/loop/step/attempt` | `session_id, user_id, question_hash, text` | `recorded` | PKG-07 |
| `POST /api/learn/loop/hint` | `session_id, user_id, question_hash, text?` | `allowed, reason?, rung?, reply?` | PKG-07 |
| `POST /api/learn/loop/close` | `session_id, user_id, self_eval?, if_then?` | `phase, summary, self_eval_question, if_then_prompt` | PKG-09 |
| `GET /api/learn/loop/review/next?user_id=&course_id=` | — | `item\|null, remaining_budget_s, session_id, retention_target, due_total` | PKG-12 (DueQueue) |
| `POST /api/learn/loop/review/answer` | `user_id, session_id, course_id, kind, item_id, answer?, selected_option?, reason?, rating?` | `correct, hint, next_due_at, rating, remaining_budget_s, sr, unavailable` | PKG-12 |
| `GET /api/learn/loop/review/summary?user_id=&course_id=` | — | `due{flashcard, check}, unservable, paused, budget_min, remaining_budget_s, retention_target` | PKG-12 |
| `GET /api/learn/sessions/{id}/resume` (legacy, not gated) | — | `session, messages[{id, role, content, created_at}]` | pre-series |

Every loop route returns 404 `{"detail": "learning loop not enabled"}` when the gate is false (spec §7). Every model-calling loop route may answer HTTP 429 `{"detail": "ai budget reached", "reset_at": <iso>}` (the A20 rate limit or the tutor hard level); `GET /status` and `GET /sessions` never do.

### Schema (exact)

None. This package writes no migration. It reads `learner_state` (PKG-03), `check_items` (PKG-04), `sessions.loop_state` (PKG-06), `sessions.close_json`/`close_phase` (PKG-09), `events` (0035), `llm_usage` (0035; PKG-06b columns), `flashcards` FSRS columns (PKG-11). The seed writes `user_settings`, `check_items`, `llm_usage` and `flashcards` rows through `db/seed_helpers.py`.

### Named constants

Learning constants are cited by name and read from `backend/learning/params.py` — in TypeScript through `frontend/e2e/support/params.ts::learningParams()` (a python shell-out, Task 9), never as a literal; the budget constants are read from `backend/config.py` (spec §3.5 puts them there). Harness constants are named `const`s at the top of the file that owns them; they are not learning parameters and do NOT go into `params.py` or `config.py`. `†` = engineering choice without a validated cut-point; list every † in the hand-off.

| Name | Value | Owner file | Meaning / source |
|---|---|---|---|
| `BKT_L0` | 0.35 | `learning/params.py` (spec §3.1) | journey asserts `learner_state.p_known > BKT_L0` |
| `PROBE_ITEMS_PER_SKILL_MIN` | 4 | `learning/params.py` (spec §3.4) | journey asserts it answered at least this many probe items; the seed's per-concept item count exceeds it |
| `PROBE_SESSION_CAP` | 12 | `learning/params.py` (spec §3.4) | upper bound of the journey's probe loop |
| `GATE_INDEPENDENT_MIN_S` | 45 † | `learning/params.py` (spec §3.3) | the journey's hint poll waits this long for the independent-time gate |
| `GATE_RUNG_DWELL_MIN_S` | 8 † | `learning/params.py` (spec §3.3) | informational; one hint only in the journey |
| `CHECK_ITEM_DIFFICULTIES` | (1, 2, 3) | `learning/params.py` (spec §3.4) | seed writes one item per value per format |
| `CHECK_ITEM_MIN_RUBRIC` / `CHECK_ITEM_MIN_WRONG` | 2 / 1 | `learning/params.py` (spec §3.4) | seed rubric/wrong lists meet them |
| `EDGE_PREREQ_SOURCE_IS_PREREQ` | True (or flipped by PKG-08) | `learning/params.py` (spec §3.1) | seed orients the prerequisite edges by it |
| `STUDENT_DAILY_BUDGET_USD` | 0.20 † | `config.py` (spec §3.5, PKG-06b) | × `BUDGET_NOVICE_MULTIPLIER` = the novice daily allowance the capped seed exceeds |
| `BUDGET_NOVICE_MULTIPLIER` | 2.5 † | `config.py` (spec §3.5, PKG-06b) | as above |
| `LEARN_RATE_LIMIT_PER_MIN` | 20 † | `config.py` (spec §3.5, PKG-06b) | the capped seed writes fewer `llm_usage` rows than this, so the cap journey hits the $ cap, not the rate limit |
| `SEED_LOOP_CONCEPTS` | 3 † | `db/seed_local_rich.py` | nodes in each loop user's chain |
| `SEED_LOOP_FORMATS` | (`"free"`, `"teachback"`) † | `db/seed_local_rich.py` | free-text formats only, so a journey answers every item by typing |
| `SEED_LOOP_ITEMS_PER_CONCEPT` | `len(SEED_LOOP_FORMATS) × len(CHECK_ITEM_DIFFICULTIES)` = 6 † | `db/seed_local_rich.py` | ≥ `PROBE_ITEMS_PER_SKILL_MIN` + 1: the probe never serves the post-test reserve (A23) |
| `SEED_CAPPED_SPEND_FACTOR` | 1.5 † | `db/seed_local_rich.py` | today's seeded spend = the novice allowance × this |
| `LOOP_OPEN_SESSIONS_LIMIT` | 10 † | `routes/learn_loop.py` | open sessions listed by `GET /sessions` (mirrors the legacy `getSessions(limit=10)`) |
| `LOOP_JOURNEY_TIMEOUT_MS` | 240_000 † | `frontend/e2e/learn-loop.spec.ts` | `test.setTimeout`; covers the independent-time gate plus paced streaming |
| `GATE_POLL_MARGIN_MS` | 15_000 † | `frontend/e2e/learn-loop.spec.ts` | added to `GATE_INDEPENDENT_MIN_S` for the hint poll |
| `DB_POLL_TIMEOUT_MS` | 5_000 | `frontend/e2e/learn-loop.spec.ts` | house value (`tutor.spec.ts:101`) |
| `ORACLE_P_TOLERANCE` | 1e-9 † | `backend/e2e_oracles/learn_loop.py` | `mastery_score == p_known` tolerance |
| `E2E_FUNCTION_STREAM_DELAY_MS` | 150 | `function_handlers_e2e.py:48` (existing) | not changed; explains the journey's stream pacing |

### Invariants asserted by this package (spec §8 numbering)

This package owns none of 1–12 and none of 22–29 (22 and 26 are the server halves of Behaviours 14 and 5; PKG-07 owns them). Task 1 adds two package-specific invariants to the module (spec §8 series table, names fixed):

- `test_inv_13a_spec_constants_match_function_handlers` — every `E2E_*` name a spec file cites in a `Must match backend/agents/function_handlers_e2e.py::NAME` comment exists in that module, and the TypeScript literal beside it equals the Python value — source scan over `frontend/e2e/*.spec.ts` + import of the module under the registry-clearing fixture.
- `test_inv_13b_seed_opts_in_exactly_the_loop_users` — `db/seed_local_rich.py` sets `learning_loop_beta` only through `LOOP_USERS = (USER_LOOP, USER_CAPPED)` (allowed set `{rich-user-loop, rich-user-capped}`), always to `True` — source scan; the legacy `rich-user-active`/`second`/`new` never appear on a line that writes `learning_loop_beta`. Build phase only: PKG-14b rewrites it in place (name kept) to "no journey depends on `learning_loop_beta`" and retires `test_legacy_users_are_not_opted_in` (spec §11.2).

Filter them with `-k "inv_13a or inv_13b"` — a bare `-k inv_13` also selects PKG-02's `test_inv_13_fsrs_weights_pinned`.

### Error semantics

The status GET fails closed to the legacy tree (build phase; PKG-14b B.13 changes this to a retry state for every error except 404 / `{active: false}`). Loop client calls that fail surface through the existing toast path (`useToast`) and leave the phase unchanged, with three exceptions: (1) a 429 `ai budget reached` (or a `budget` event with `level: "hard"`) renders the pause banner (Behaviour 15), never a toast; (2) a failed `GET /sessions` renders `loop-sessions-error` with a Retry button (`loop-sessions-retry`) — it never falls through to a new session or probe (a reload must never start a probe, spec §11.3); (3) `{graded: false, unavailable: true}` from `/probe/answer` is not an error (Behaviour 3). A failed stream uses the same `ChatStreamError` handling as `Learn.tsx` minus the JSON-fallback rung (the loop streams have JSON twins — `/chat`, `/check/answer` — but the loop client does not use them; if HANDOFF-07 asks for the ladder, mirror it). `GET /sessions` answers 404 when the gate is false and never 429. No agent is called from this package's backend code (the handler is scripted output; the new route reads one table).

### Events added

None. The oracle READS `zpd.step`, `zpd.leak`, `learn.session_closed` (spec §6); the journey reads `zpd.step.tier` (A15) and `review.graded`. `EVENT_TAXONOMY` is untouched.

## Non-goals

- One new read-only route (`GET /api/learn/loop/sessions`, Behaviour 13) and nothing else on the server: no other route change, no body-model change, no `chat_stream.py` change, no `agent_events.py` change. A contract gap between this prompt's expected table and the real routes is fixed by adapting THIS package's client (and recording the deviation), not by editing PKG-07..12 code — unless a route is actually broken, in which case: separate first commit `fix(learning-loop): PKG-MM — <what>`, `MM | reopened` ledger row, "Post-hoc changes" in `HANDOFF-MM.md`.
- No redesign of `ChatPanel`; no change to the LEGACY entry screen, session picker, knowledge-map rail, or `tierForScore` (LoopLearn gets its own picker and map, Behaviours 3 and 17).
- No mobile layout work beyond what `ChatPanel` already provides; no new review surface — `DueQueue.tsx` (PKG-12) gets only its launch polish (Behaviour 18).
- No model toggle, no tier indicator, no student-visible cost figure (spec §12: no student-visible model toggle on the loop).
- No `explore` (Chapter 2) run; Chapter 1 only.
- No cutover (PKG-14): the lane keeps the explicit `true` export and the build-phase legacy-user test; PKG-14b rewrites both.

## Tasks

### Task 1: Package invariants (spec sync + seed staff/QA toggle)

**Files:**
- Modify: `backend/tests/test_learning_loop_invariants.py` (append two tests)

**Interfaces:**
- Consumes: `frontend/e2e/*.spec.ts` (source), `agents.function_handlers_e2e` (import), `db/seed_local_rich.py` (source).

- [ ] **Step 1: Append the tests** (they fail now: the spec file is a stub and the seed has no loop users)

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


def test_inv_13b_seed_opts_in_exactly_the_loop_users():
    """Build phase (spec §13 A14): user_settings.learning_loop_beta is a staff/QA
    toggle, and the seed sets it only for the loop users {rich-user-loop,
    rich-user-capped}. PKG-14b rewrites this test in place (name kept) to "no
    journey depends on learning_loop_beta" (spec §8, §11.2)."""
    text = SEED.read_text()
    assert 'USER_LOOP = "rich-user-loop"' in text, "seed has no loop user"
    assert 'USER_CAPPED = "rich-user-capped"' in text, "seed has no capped user"
    assert re.search(r"^LOOP_USERS = \(USER_LOOP, USER_CAPPED\)$", text, re.M), "the toggle's allowed set changed"
    # Lines that WRITE the column carry the quoted dict key; comments do not.
    toggle_lines = [ln for ln in text.splitlines() if '"learning_loop_beta"' in ln]
    assert toggle_lines, "seed never sets learning_loop_beta"
    assert all("True" in ln for ln in toggle_lines), toggle_lines
    for legacy in ("USER_ACTIVE", "USER_SECOND", "USER_NEW", "rich-user-active", "rich-user-second", "rich-user-new"):
        assert not any(legacy in ln for ln in toggle_lines), f"{legacy} must stay legacy"
```

- [ ] **Step 2: Run to see the current state**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_13a or inv_13b"` (a bare `-k inv_13` also selects PKG-02's `test_inv_13_fsrs_weights_pinned`)
Expected: 2 failed — `learn-loop.spec.ts cites no E2E_ constant`; `seed has no loop user`.

- [ ] **Step 3: Commit**

```
git add backend/tests/test_learning_loop_invariants.py
git commit -m "test(learning-loop): PKG-13 — spec/handler sync and seed staff/QA-toggle invariants

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 2: Phase-aware `loop_tutor` handler + `E2E_LOOP_*` constants

**Files:**
- Modify: `backend/agents/function_handlers_e2e.py`
- Test: `backend/tests/test_e2e_function_handlers.py` (append)

**Interfaces:**
- Consumes: the phase prompts in `agents/loop_tutor.py` (read them; the pattern VALUES come from there).
- Produces: `E2E_LOOP_PROBE_PROMPT: str`, `E2E_LOOP_HINT_REPLY: str`, `E2E_LOOP_FEEDBACK_REPLY: str`, `E2E_LOOP_PHASE_PATTERNS: dict[str, str]` (`{"hint": ..., "feedback": ...}`), `_loop_tutor_handler` rewritten to dispatch on phase and registered for the three tutor slots `loop_tutor`, `loop_tutor_lite`, `loop_tutor_deep` (spec §13 A15; invariant 6).

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


@pytest.mark.parametrize("slot", ["loop_tutor", "loop_tutor_lite", "loop_tutor_deep"])
def test_loop_tutor_handler_serves_every_tier_slot(monkeypatch, slot):
    """Spec §13 A15: code picks the tier slot per run (feedback after a correct
    answer runs on loop_tutor_lite), so the scripted reply must not depend on it."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    monkeypatch.setenv("SAPLING_FUNCTION_HANDLERS", "agents.function_handlers_e2e")
    from agents.loop_tutor import loop_tutor_agent  # name per HANDOFF-07; adapt
    from agents.function_handlers_e2e import E2E_LOOP_TUTOR_REPLY
    with loop_tutor_agent.override(model=model_for(slot)):
        result = loop_tutor_agent.run_sync("teach me", deps=_deps())
    assert result.output == E2E_LOOP_TUTOR_REPLY
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


# One handler for the three tier slots (spec §13 A15): the tier is chosen in
# code per run, so the scripted reply never depends on it.
for _slot in ("loop_tutor", "loop_tutor_lite", "loop_tutor_deep"):
    register_function_handler(_slot, _loop_tutor_handler)
```

Keep `E2E_LOOP_TUTOR_REPLY` where PKG-07 defined it; do not rename any existing constant. PKG-07 registered its handler for the same three slots — this block replaces those registrations one for one; a slot left on PKG-07's handler would answer the hint/feedback prompts with the teach reply. If the hint and feedback prompts share the pattern, choose a fragment unique to each; if `loop_tutor.py` injects the phase only through the user message, the scan still finds it.

- [ ] **Step 4: Run tests, lint**

Run: `cd backend && venv/bin/python -m pytest tests/test_e2e_function_handlers.py tests/test_learning_loop_invariants.py -q -k "loop or inv_06 or inv_12" && venv/bin/ruff check .`
Expected: loop handler tests pass (incl. the three tier-slot cases); inv_06/inv_12 still pass; `All checks passed!`

- [ ] **Step 5: Commit**

```
git add backend/agents/function_handlers_e2e.py backend/tests/test_e2e_function_handlers.py
git commit -m "feat(learning-loop): PKG-13 — phase-aware loop_tutor function handler and E2E_LOOP_* constants

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 3: Seed the loop users + lane env

**Files:**
- Modify: `backend/db/seed_local_rich.py`, `scripts/e2e-up.sh`, `.github/workflows/e2e.yml`, `scripts/explore.sh`, `backend/.env.local.example` (one commented line)
- Test: `backend/tests/test_learning_seed_loop_user.py`

**Interfaces:**
- Consumes: `learning.params` (`CHECK_ITEM_DIFFICULTIES`, `CHECK_ITEM_MIN_RUBRIC`, `CHECK_ITEM_MIN_WRONG`, `EDGE_PREREQ_SOURCE_IS_PREREQ`, `PROBE_ITEMS_PER_SKILL_MIN`), `config` (`STUDENT_DAILY_BUDGET_USD`, `BUDGET_NOVICE_MULTIPLIER`, `LEARN_RATE_LIMIT_PER_MIN` — PKG-06b), `learning.checks.question_hash` (PKG-04; verify the name and its argument — plaintext prompt), `services.graph_service._normalize_concept` (the A2 concept key), `services.encryption`, the PKG-05 grader token constant, `E2E_LOOP_PROBE_PROMPT`.
- Produces: `seed_local_rich.USER_LOOP`, `USER_CAPPED`, `LOOP_USERS`, `ENR_LOOP_CS_S26`, `ENR_CAPPED_CS_S26`, `LOOP_NODES`, `loop_node_id()`, `SEED_LOOP_CONCEPTS`, `SEED_LOOP_FORMATS`, `SEED_LOOP_ITEMS_PER_CONCEPT`, `SEED_CAPPED_SPEND_FACTOR`, `CAPPED_FLASHCARD`, `seed_learning_loop()`; `LEARNING_LOOP_ENABLED=true` in the lane (build phase).

- [ ] **Step 1: Write the failing test**

```python
"""PKG-13: the rich seed carries the two loop users (staff/QA toggle, build phase;
spec §13 A14) — prerequisite chains, shared encrypted check items (A2), and the
capped user's spend and due flashcard (A26). Hermetic — `db.seed_helpers.table`
and the seed's own `table` are replaced by a recorder; nothing reaches PostgREST."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

import config
from db import seed_helpers
from db import seed_local_rich as seed
from learning.params import (
    CHECK_ITEM_DIFFICULTIES, CHECK_ITEM_MIN_RUBRIC, CHECK_ITEM_MIN_WRONG, PROBE_ITEMS_PER_SKILL_MIN,
)
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
    monkeypatch.setattr(seed, "_admin_role_id", lambda: None)  # the recorder has no roles table
    seed_helpers.reset_counts()
    seed.seed_users()          # the loop users' `users` rows come from _USERS
    seed.seed_enrollments()    # … and their enrollments from _ENROLLMENTS
    seed.seed_learning_loop()
    return r


def test_loop_users_carry_the_staff_toggle_and_are_enrolled(recorder):
    assert seed.LOOP_USERS == (seed.USER_LOOP, seed.USER_CAPPED)
    for uid in seed.LOOP_USERS:
        settings = [r for r in recorder.rows["user_settings"] if r["user_id"] == uid]
        assert settings and settings[0]["learning_loop_beta"] is True
        users = [r for r in recorder.rows["users"] if r["id"] == uid]
        assert users and users[0]["is_approved"] and users[0]["onboarding_completed"]
        assert any(r["user_id"] == uid for r in recorder.rows["enrollments"])


def test_legacy_users_are_not_opted_in(recorder):
    # Name kept for PKG-14b, which retires it (spec §11.2). Build phase: only the
    # loop users carry the staff/QA toggle.
    for row in recorder.rows.get("user_settings", []):
        assert row["user_id"] in {seed.USER_LOOP, seed.USER_CAPPED}


def test_prerequisite_chain(recorder):
    for uid in seed.LOOP_USERS:
        nodes = [r for r in recorder.rows["graph_nodes"] if r["user_id"] == uid]
        assert len(nodes) == seed.SEED_LOOP_CONCEPTS
        assert all(r["mastery_score"] == 0.0 and r["mastery_tier"] == "unexplored" for r in nodes)
        edges = [r for r in recorder.rows["graph_edges"] if r["user_id"] == uid]
        assert len(edges) == seed.SEED_LOOP_CONCEPTS - 1
        assert all(r["relationship_type"] == "prerequisite" for r in edges)
        ids = {r["id"] for r in nodes}
        assert all(r["source_node_id"] in ids and r["target_node_id"] in ids for r in edges)
    # Same concept names for both users → the same concept keys → shared items (A2).
    names = {uid: sorted(r["concept_name"] for r in recorder.rows["graph_nodes"] if r["user_id"] == uid)
             for uid in seed.LOOP_USERS}
    assert names[seed.USER_LOOP] == names[seed.USER_CAPPED]


def test_check_items_are_shared_course_assets_encrypted_and_hashed(recorder):
    items = recorder.rows["check_items"]
    assert seed.SEED_LOOP_ITEMS_PER_CONCEPT == len(seed.SEED_LOOP_FORMATS) * len(CHECK_ITEM_DIFFICULTIES)
    assert seed.SEED_LOOP_ITEMS_PER_CONCEPT >= PROBE_ITEMS_PER_SKILL_MIN + 1  # the probe never serves the A23 reserve
    assert len(items) == seed.SEED_LOOP_CONCEPTS * seed.SEED_LOOP_ITEMS_PER_CONCEPT  # once, not per user
    assert {r["format"] for r in items} == set(seed.SEED_LOOP_FORMATS)
    assert sorted({r["difficulty"] for r in items}) == sorted(CHECK_ITEM_DIFFICULTIES)
    assert len({r["concept_key"] for r in items}) == seed.SEED_LOOP_CONCEPTS
    for r in items:
        assert "node_id" not in r and r["course_id"] == seed.COURSE_CS  # A2: keyed on (course_id, concept_key)
        plain = decrypt_if_present(r["prompt"])
        assert plain != r["prompt"], "prompt stored in plaintext"
        assert plain.startswith("[e2e-loop]")
        assert decrypt_if_present(r["reference_answer"]) != r["reference_answer"]
        assert len(json.loads(decrypt_if_present(r["rubric_json"]))) >= CHECK_ITEM_MIN_RUBRIC
        assert len(json.loads(decrypt_if_present(r["common_wrong_json"]))) >= CHECK_ITEM_MIN_WRONG
        assert r["graded"] is False
        assert len(r["question_hash"]) == 64
    assert len({(r["course_id"], r["concept_key"], r["question_hash"]) for r in items}) == len(items)


def test_capped_user_spend_is_past_the_novice_allowance(recorder):
    rows = recorder.rows["llm_usage"]
    assert rows and all(r["user_id"] == seed.USER_CAPPED for r in rows)
    allowance = config.STUDENT_DAILY_BUDGET_USD * config.BUDGET_NOVICE_MULTIPLIER
    assert sum(float(r["cost_usd"]) for r in rows) > allowance                # hard level in every band
    assert len(rows) < config.LEARN_RATE_LIMIT_PER_MIN                         # the $ cap, not the rate limit
    assert all(r["task"] not in ("grader", "grader_second", "decision") for r in rows)  # grader cap untouched
    assert all("created_at" not in r for r in rows)                            # stamped now() by the column default


def test_capped_user_has_one_due_flashcard(recorder):
    cards = recorder.rows["flashcards"]
    assert len(cards) == 1 and cards[0]["user_id"] == seed.USER_CAPPED
    assert decrypt_if_present(cards[0]["front"]) != cards[0]["front"]  # 🔒 front/back (#518)
    assert cards[0]["due_at"] < datetime.now(timezone.utc).isoformat()


def test_no_learner_state_seeded(recorder):
    assert "learner_state" not in recorder.rows
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_seed_loop_user.py -q`
Expected: ERROR — `AttributeError: module 'db.seed_local_rich' has no attribute 'seed_learning_loop'`.

- [ ] **Step 3: Implement the seed.** Add after the `USER_*` ids (`:63–67`):

```python
# Learning loop (PKG-13): the loop users (staff/QA toggle, build phase; spec
# §13 A14). The loop is dark behind LEARNING_LOOP_ENABLED during the build and
# user_settings.learning_loop_beta is a staff/QA toggle set by SQL or this seed
# (spec §7). Only these users carry it, so every legacy rich-* user stays on the
# pre-series path — the E2E lane runs with LEARNING_LOOP_ENABLED=true and relies
# on that split to keep tutor/quiz specs untouched. PKG-14b rewrites this
# comment: after launch the gate ignores the toggle (spec §11.2).
USER_LOOP = "rich-user-loop"
USER_CAPPED = "rich-user-capped"
LOOP_USERS = (USER_LOOP, USER_CAPPED)
ENR_LOOP_CS_S26 = "rich-enr-loop-cs101-s26"
ENR_CAPPED_CS_S26 = "rich-enr-capped-cs101-s26"
SEED_LOOP_CONCEPTS = 3
SEED_LOOP_FORMATS = ("free", "teachback")  # † free-text formats: a journey answers every item by typing
SEED_LOOP_ITEMS_PER_CONCEPT = 6            # † = len(SEED_LOOP_FORMATS) × len(CHECK_ITEM_DIFFICULTIES); the test pins it
SEED_CAPPED_SPEND_FACTOR = 1.5             # † today's seeded spend = the novice daily allowance × this (spec §13 A26)
# (slug, concept_name) — a prerequisite chain in order. Each loop user gets its
# own graph_nodes rows (loop_node_id); check items are course assets keyed on
# (course_id, concept_key) and written once for both (spec §13 A2). Edges are
# oriented by learning.params.EDGE_PREREQ_SOURCE_IS_PREREQ at write time.
LOOP_NODES = [
    ("binary", "Binary Numbers"),
    ("bitwise", "Bitwise Operators"),
    ("twos", "Two's Complement"),
]
# (card_id, front, back) — the capped user's one due flashcard; the budget-cap
# journey rates it on /study (review keeps working at the hard level, spec §3.5).
CAPPED_FLASHCARD = ("rich-fc-capped-1", "What is a bit?", "A binary digit: 0 or 1.")


def loop_node_id(user_id: str, slug: str) -> str:
    return f"rich-node-{'loop' if user_id == USER_LOOP else 'capped'}-{slug}"
```

Add the user tuples to `_USERS` — `(USER_LOOP, "rich.loop@richlocal.test", True, True, 3, {"name": "Lou Loop", "first_name": "Lou", "last_name": "Loop", "username": "rich-loop", "year": "Sophomore", "majors": ["Computer Science"], "minors": [], "learning_style": "visual"})` and `(USER_CAPPED, "rich.capped@richlocal.test", True, True, 1, {"name": "Casey Cap", "first_name": "Casey", "last_name": "Cap", "username": "rich-capped", "year": "Freshman", "majors": ["Computer Science"], "minors": [], "learning_style": "visual"})` — and the enrollment tuples `(ENR_LOOP_CS_S26, USER_LOOP, OFF_CS_S26, "#4f86f7", "Intro CS (loop)", "raw", None, None)` and `(ENR_CAPPED_CS_S26, USER_CAPPED, OFF_CS_S26, "#4f86f7", "Intro CS (capped)", "raw", None, None)` to `_ENROLLMENTS`. Then add the step (after `seed_sessions`):

```python
def seed_learning_loop() -> None:
    """PKG-13: the loop users — the staff/QA toggle, a prerequisite chain each,
    shared encrypted check items, and the capped user's spend and due card.
    Imports are function-local: `learning.*`, the `config` budget names and the
    function-handler constants are only needed here, and importing
    agents.function_handlers_e2e registers handlers as a harmless side effect
    in this CLI process."""
    from datetime import datetime, timedelta, timezone

    import config
    from agents.function_handlers_e2e import E2E_LOOP_PROBE_PROMPT, GRADER_CORRECT_TOKEN  # names per HANDOFF-05
    from learning.checks import question_hash
    from learning.params import CHECK_ITEM_DIFFICULTIES, EDGE_PREREQ_SOURCE_IS_PREREQ
    from services.graph_service import _normalize_concept

    for uid in LOOP_USERS:
        h.upsert("user_settings", {"user_id": uid, "learning_loop_beta": True}, on_conflict="user_id")
        for slug, concept in LOOP_NODES:
            h.upsert(
                "graph_nodes",
                {
                    "id": loop_node_id(uid, slug), "user_id": uid, "course_id": COURSE_CS,
                    "concept_name": concept, "subject": concept.split()[0],
                    "mastery_score": 0.0, "mastery_tier": get_mastery_tier(0.0),
                },
                on_conflict="user_id,course_id,concept_name",
            )
        for (pre, _), (dep, _) in zip(LOOP_NODES, LOOP_NODES[1:]):
            pre_id, dep_id = loop_node_id(uid, pre), loop_node_id(uid, dep)
            src, tgt = (pre_id, dep_id) if EDGE_PREREQ_SOURCE_IS_PREREQ else (dep_id, pre_id)
            h.upsert(
                "graph_edges",
                {
                    "id": f"{loop_node_id(uid, pre).replace('rich-node-', 'rich-edge-')}-{dep}",
                    "user_id": uid, "source_node_id": src, "target_node_id": tgt,
                    "relationship_type": "prerequisite", "strength": 0.9,
                },
                on_conflict="user_id,source_node_id,target_node_id,relationship_type",
            )

    # Check items are course assets (spec §13 A2): keyed on (course_id,
    # concept_key), written ONCE, served to both loop users through their nodes'
    # concept names.
    for slug, concept in LOOP_NODES:
        concept_key = _normalize_concept(concept)
        for fmt in SEED_LOOP_FORMATS:
            for difficulty in CHECK_ITEM_DIFFICULTIES:
                prompt = f"{E2E_LOOP_PROBE_PROMPT} [{concept}, {fmt}, difficulty {difficulty}]"
                h.upsert(
                    "check_items",
                    {
                        "id": f"rich-check-{slug}-{fmt}-d{difficulty}",
                        "course_id": COURSE_CS, "concept_key": concept_key, "document_id": None,
                        "format": fmt, "difficulty": difficulty,
                        "prompt": encrypt_if_present(prompt),                          # 🔒
                        "reference_answer": encrypt_if_present(GRADER_CORRECT_TOKEN),  # 🔒
                        "rubric_json": encrypt_json([                                  # 🔒
                            {"id": "r1", "text": "States the e2e grader token."},
                            {"id": "r2", "text": f"Names {concept}."},
                        ]),
                        "common_wrong_json": encrypt_json([                            # 🔒
                            {"key": "wrong_token", "text": "Gives a different token."},
                        ]),
                        "source_chunk_ids": [], "question_hash": question_hash(prompt), "graded": False,
                    },
                    on_conflict="course_id,concept_key,question_hash",
                )

    # rich-user-capped (spec §13 A26): today's spend past the novice allowance,
    # so the §3.5 hard level applies in every band. ONE row — far below
    # LEARN_RATE_LIMIT_PER_MIN, so the journey hits the $ cap and not the rate
    # limit — on a tutor slot, so the grader cap is untouched. created_at is
    # the column default now(); the Playwright fixture re-seeds before every
    # test, so the row is always inside today's UTC window.
    h.insert_if_absent(
        "llm_usage",
        "rich-usage-capped-1",
        {
            "user_id": USER_CAPPED, "feature": "learn_loop", "task": "loop_tutor",  # feature per HANDOFF-07
            "model": "gemini-2.5-flash", "provider": "gemini",
            "cost_usd": round(
                config.STUDENT_DAILY_BUDGET_USD * config.BUDGET_NOVICE_MULTIPLIER * SEED_CAPPED_SPEND_FACTOR, 6,
            ),
        },
    )
    card_id, front, back = CAPPED_FLASHCARD
    h.insert_if_absent(
        "flashcards",
        card_id,
        {
            "user_id": USER_CAPPED, "offering_id": OFF_CS_S26, "topic": "Binary Numbers",
            # 🔒 front / back (#518)
            "front": encrypt_if_present(front),
            "back": encrypt_if_present(back),
            "due_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),  # due (PKG-11 column)
        },
    )
```

`GRADER_CORRECT_TOKEN` is the PKG-05 constant (HANDOFF-05 names it; adapt the import). If `learning.checks.question_hash` takes anything other than the plaintext prompt, follow its signature. If PKG-04's `services/check_item_service.py` exposes a create helper that encrypts, hashes and keys on `(course_id, concept_key)`, you may call it instead of the direct upsert — but the test above must still pass unchanged (it reads the recorded rows), so prefer the direct upsert. Seeded items leave `answer_kind`, `stepwise`, `options_json` and the other A22 columns at their defaults (`free`, `false`, null). If HANDOFF-11/12 records that a card with a null `last_reviewed_at` is due regardless of `due_at`, keep the past `due_at` anyway (it is due under either rule). Call `seed_learning_loop()` from `main()` after `seed_sessions()`; add `"user_settings"`, `"check_items"` and `"llm_usage"` to `_SUMMARY_ORDER` (`"flashcards"` is already there); note `user_settings`, `llm_usage` and `flashcards` are truncated and re-seeded per test by the Playwright fixture (none is in either denylist — confirm with `grep -n "llm_usage\|user_settings\|flashcards" frontend/e2e/support/db.ts backend/tests/integration/conftest.py` → no denylist hit), which is what keeps the staff/QA toggle stable across specs and the capped spend inside today's window.

- [ ] **Step 4: Lane env (build phase).** In `scripts/e2e-up.sh`, immediately after the `export QUIZ_GENERATE_RATE_LIMIT=…` line, add:

```bash
# Learning loop series (PKG-13), build phase: the lane boots with the loop flag ON.
# Only the seeded loop users carry the staff/QA toggle; PKG-14b removes this export
# (spec §11.4: the default lane then runs the code default). The loop users are
# rich-user-loop and rich-user-capped (user_settings.learning_loop_beta), so every
# legacy spec keeps the pre-series path; frontend/e2e/learn-loop.spec.ts holds the
# loop's journeys. Exported, so it beats backend/.env.
export LEARNING_LOOP_ENABLED="${LEARNING_LOOP_ENABLED:-true}"
echo "  ℹ LEARNING_LOOP_ENABLED=$LEARNING_LOOP_ENABLED for this stack (PKG-13 build phase; only the seeded loop users carry the staff/QA toggle)"
```

In `.github/workflows/e2e.yml` add `LEARNING_LOOP_ENABLED: "true"` to the "Boot the stack" `env:` block with a one-line comment (`# build phase (PKG-13); PKG-14b replaces this with the default/kill-switch matrix`); in `scripts/explore.sh` add `export LEARNING_LOOP_ENABLED=true` beside the seam exports (`:398–410`); in `backend/.env.local.example` add exactly this commented line:

```
# LEARNING_LOOP_ENABLED — build phase: off unless true; staff/QA toggle is user_settings.learning_loop_beta, set by SQL (spec §7)
```

- [ ] **Step 5: Run tests, lint, and a real seed round-trip against the local database** (the seed runs under the lane later; here prove it is idempotent in isolation, under the lock):

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_seed_loop_user.py -q && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k inv_13b && venv/bin/ruff check . && bash -n ../scripts/e2e-up.sh`
Expected: all passed; `All checks passed!`; no bash syntax error.

Run: `flock /tmp/claude-$(id -u)/sapling-e2e-stack.lock -c 'cd backend && supabase start >/dev/null 2>&1; SUPABASE_DB_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres venv/bin/python -m db.migrate && venv/bin/python -m db.seed_local_rich && venv/bin/python -m db.seed_local_rich | tail -n 4'`
Expected: first run prints `check_items created=18`, `user_settings created=2`, `llm_usage created=1`; second run prints `TOTAL created 0` and `(all rows already present — re-run was a no-op)`.

- [ ] **Step 6: Commit**

```
git add backend/db/seed_local_rich.py backend/tests/test_learning_seed_loop_user.py scripts/e2e-up.sh scripts/explore.sh .github/workflows/e2e.yml backend/.env.local.example
git commit -m "feat(learning-loop): PKG-13 — seed the loop users (staff/QA toggle, capped spend) and enable the flag in the E2E lane

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 4: `GET /api/learn/loop/sessions` — the open sessions LoopLearn resumes

**Files:**
- Modify: `backend/routes/learn_loop.py` (append ONE route and one named constant; nothing else in the file changes)
- Test: `backend/tests/test_learn_loop_sessions.py`

**Interfaces:**
- Consumes: PKG-07's gate check (`learning_loop_active` → 404) and `require_self` pattern, `_phase_for(state)` (the helper behind `GET /status`; HANDOFF-07/08 record how it covers `probe`/`plan`), `services.academics.user_offering_ids_for_course`, `db.connection.table`.
- Produces: `routes.learn_loop.list_open_sessions`, `LOOP_OPEN_SESSIONS_LIMIT = 10 †`; response `{"sessions": [{"session_id", "topic", "started_at", "phase"}]}` (spec §9, §11.3, Behaviour 13).

- [ ] **Step 1: Write the failing tests.** Reuse PKG-07's route-test client and gate fixtures from `tests/test_learn_loop_routes.py` (HANDOFF-07 names them; the `client` fixture and the gate patch below are placeholders for them — adapt, never duplicate the app setup).

```python
"""PKG-13: GET /api/learn/loop/sessions — the open loop sessions a student can
resume (spec §9, §11.3, §13 A26). Read-only; 404 when the gate is false; never
rate-limited (A20: a failure here must not push a student off the loop UI)."""
from __future__ import annotations

import pytest

import routes.learn_loop as ll

LOOP = "/api/learn/loop"
UID = "u1"          # the session user PKG-07's route tests authenticate as; adapt
COURSE = "c1"


class _Sessions:
    """Records the one sessions read and returns canned rows."""

    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def __call__(self, name):
        assert name == "sessions", f"/sessions reads only the sessions table, not {name}"
        outer = self

        class _T:
            def select(self, cols, filters=None, order=None, limit=None):
                outer.calls.append({"cols": cols, "filters": dict(filters or {}), "order": order, "limit": limit})
                return list(outer.rows)

        return _T()


_OPEN_STATE = {"probe": {"skills": ["n1"]}}


def _row(sid, *, state=_OPEN_STATE, close_phase=None, started="2026-09-20T10:00:00Z"):
    return {"id": sid, "topic": f"topic {sid}", "started_at": started, "loop_state": state, "close_phase": close_phase}


@pytest.fixture
def gate_on(monkeypatch):
    monkeypatch.setattr(ll, "learning_loop_active", lambda user_id: True)  # PKG-07's gate symbol; adapt
    monkeypatch.setattr(ll, "user_offering_ids_for_course", lambda user_id, course_id: ["off-1", "off-2"])
    monkeypatch.setattr(ll, "_phase_for", lambda state: state.get("_phase", "teach"))


def test_404_when_gate_false_and_no_read(client, monkeypatch):
    monkeypatch.setattr(ll, "learning_loop_active", lambda user_id: False)
    fake = _Sessions([_row("s1")])
    monkeypatch.setattr(ll, "table", fake)
    r = client.get(f"{LOOP}/sessions?user_id={UID}&course_id={COURSE}")
    assert r.status_code == 404 and r.json() == {"detail": "learning loop not enabled"}
    assert fake.calls == []


def test_lists_open_loop_sessions_newest_first(client, monkeypatch, gate_on):
    fake = _Sessions([_row("s2", started="2026-09-21T10:00:00Z"), _row("s1")])
    monkeypatch.setattr(ll, "table", fake)
    r = client.get(f"{LOOP}/sessions?user_id={UID}&course_id={COURSE}")
    assert r.status_code == 200
    assert [s["session_id"] for s in r.json()["sessions"]] == ["s2", "s1"]
    assert set(r.json()["sessions"][0]) == {"session_id", "topic", "started_at", "phase"}
    (call,) = fake.calls
    assert call["filters"] == {
        "user_id": f"eq.{UID}", "offering_id": "in.(off-1,off-2)",
        "close_json": "is.null", "ended_at": "is.null", "mode": "neq.review",
    }
    assert call["order"] == "started_at.desc" and call["limit"] == ll.LOOP_OPEN_SESSIONS_LIMIT
    assert "close_json" not in call["cols"]  # never read the ciphertext; is.null only (invariant 9)


def test_drops_sessions_with_empty_loop_state(client, monkeypatch, gate_on):
    monkeypatch.setattr(ll, "table", _Sessions([_row("s1", state={}), _row("s2", state=None), _row("s3")]))
    r = client.get(f"{LOOP}/sessions?user_id={UID}&course_id={COURSE}")
    assert [s["session_id"] for s in r.json()["sessions"]] == ["s3"]


def test_phase_prefers_close_phase_then_the_loop_state(client, monkeypatch, gate_on):
    rows = [_row("s1", close_phase="feedback"), _row("s2", state={"_phase": "probe", "probe": {}})]
    monkeypatch.setattr(ll, "table", _Sessions(rows))
    phases = {s["session_id"]: s["phase"] for s in client.get(f"{LOOP}/sessions?user_id={UID}&course_id={COURSE}").json()["sessions"]}
    assert phases == {"s1": "feedback", "s2": "probe"}


def test_no_offering_for_the_course_reads_nothing(client, monkeypatch, gate_on):
    monkeypatch.setattr(ll, "user_offering_ids_for_course", lambda user_id, course_id: [])
    fake = _Sessions([_row("s1")])
    monkeypatch.setattr(ll, "table", fake)
    r = client.get(f"{LOOP}/sessions?user_id={UID}&course_id={COURSE}")
    assert r.status_code == 200 and r.json() == {"sessions": []} and fake.calls == []


def test_never_rate_limited(client, monkeypatch, gate_on):
    """A20: the rate limit applies to model-calling routes only — never GET /sessions."""
    import services.ai_budget as ai_budget
    monkeypatch.setattr(ai_budget, "rate_limited", lambda user_id: True)
    monkeypatch.setattr(ll, "table", _Sessions([_row("s1")]))
    assert client.get(f"{LOOP}/sessions?user_id={UID}&course_id={COURSE}").status_code == 200
    route = next(r for r in client.app.routes if getattr(r, "path", "") == f"{LOOP}/sessions")
    deps = [d.call for d in route.dependant.dependencies]
    assert ai_budget.enforce_rate_limit not in deps
```

Add the `require_self` case (another user's `user_id` → 403) in the shape PKG-07's route tests use.

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && venv/bin/python -m pytest tests/test_learn_loop_sessions.py -q`
Expected: FAIL — `404 Not Found` for the unknown path (or `AttributeError: … 'LOOP_OPEN_SESSIONS_LIMIT'`).

- [ ] **Step 3: Implement.** Append to `routes/learn_loop.py` (import `user_offering_ids_for_course` from `services.academics` at the top if PKG-07 did not):

```python
# ── Open loop sessions (PKG-13; spec §9, §11.3, §13 A26) ────────────────────
# What LoopLearn resumes instead of starting a new probe: the student's loop
# sessions for the course that have loop_state, no close record and no end.
# Read-only — no write, no model, no event — and never rate-limited (A20: a
# failure here must not push a student off the loop UI). mode='review' rows are
# PKG-12's daily review sessions, not resumable loop sessions.
LOOP_OPEN_SESSIONS_LIMIT = 10  # † picker length; mirrors the legacy getSessions(limit=10)


@router.get("/sessions")
def list_open_sessions(user_id: str, course_id: str, request: Request) -> dict:
    require_self(user_id, request)
    if not learning_loop_active(user_id):  # the gate every PKG-07 route uses (spec §7)
        raise HTTPException(404, detail="learning loop not enabled")
    offering_ids = user_offering_ids_for_course(user_id, course_id)
    if not offering_ids:
        return {"sessions": []}
    rows = table("sessions").select(
        "id,topic,started_at,loop_state,close_phase",
        filters={
            "user_id": f"eq.{user_id}",
            "offering_id": f"in.({','.join(offering_ids)})",
            "close_json": "is.null",
            "ended_at": "is.null",
            "mode": "neq.review",
        },
        order="started_at.desc",
        limit=LOOP_OPEN_SESSIONS_LIMIT,
    ) or []
    sessions = []
    for row in rows:
        state = row.get("loop_state") or {}
        if not state:
            continue
        sessions.append({
            "session_id": row["id"],
            "topic": row.get("topic") or "",
            "started_at": row.get("started_at"),
            "phase": row.get("close_phase") or _phase_for(state),
        })
    return {"sessions": sessions}
```

If HANDOFF-07 records a shared gate helper, call it instead of the inline check; adapt `_phase_for` likewise (if it takes more than the state, pass what `GET /status` passes). Attach no `enforce_rate_limit` dependency. Invariants to re-run: 22 (`routes/learn_loop.py` still has no `model_pref`), 26 (this handler calls neither `flush_pending` nor `apply_graph_update`), 9 (no `eq.` filter on `close_json`).

- [ ] **Step 4: Run tests, lint**

Run: `cd backend && venv/bin/python -m pytest tests/test_learn_loop_sessions.py tests/test_learn_loop_routes.py -q && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_09 or inv_22 or inv_26" && venv/bin/ruff check .`
Expected: all passed (every PKG-07 route test unchanged); `3 passed`; `All checks passed!`

- [ ] **Step 5: Commit**

```
git add backend/routes/learn_loop.py backend/tests/test_learn_loop_sessions.py
git commit -m "feat(learning-loop): PKG-13 — GET /api/learn/loop/sessions lists open loop sessions for resume

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 5: API client + stream events + pure phase reducer

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Create: `frontend/src/components/learn/loopState.ts`, `frontend/src/components/learn/useLoopStatus.ts`
- Test: `frontend/src/lib/api.loop.test.ts`, `frontend/src/components/learn/loopState.test.ts`

**Interfaces:**
- Consumes: `fetchJSON`, `consumeChatStream`, `ApiError` (`status`, `body`), PKG-12's `getLoopStatus` (`api.ts`).
- Produces (all exported from `api.ts`): types `LoopPhase`, `LoopBand`, `LoopOption`, `LoopCheckItem`, `LoopProbeItem`, `LoopProbeNext`, `LoopProbeAnswerResult`, `LoopLearnerState`, `LoopPlanConcept`, `LoopOpenSession`, `LoopHintResponse`, `LoopCloseResponse`, `LoopCheckAnswer`, `LoopBudgetPause`; functions `getLoopStatus(userId)` (PKG-12's, extended: 404 → `{active: false}`), `listLoopSessions(userId, courseId)`, `startLoopSession(userId, courseId, topic)`, `nextLoopProbe(sessionId, userId, courseId)`, `answerLoopProbe(sessionId, userId, courseId, questionHash, {answer?, selectedOption?, reason?, idk})`, `getLoopPlan(sessionId, userId, courseId)`, `approveLoopPlan(sessionId, userId, conceptIds)`, `streamLoopChat(sessionId, userId, message, handlers)`, `streamLoopCheckAnswer(sessionId, userId, questionHash, answer: LoopCheckAnswer, handlers)`, `postLoopAttempt(sessionId, userId, questionHash, text)`, `nextLoopCheck(sessionId, userId)` (`POST /check/next`, A27), `requestLoopHint(sessionId, userId, questionHash, text?)`, `closeLoopSession(sessionId, userId, answers?)`, `budgetPauseOf(err): LoopBudgetPause | null`; `StreamChatHandlers` gains `onPhase`, `onCheck`, `onHintOffer`, `onLearnerState`, `onBudget`; the `StreamEvent` type union gains the five loop event names; `ChatResult` gains `leak_redacted?: boolean`. No loop function takes or sends `model_pref` (A15/A26). The review calls stay PKG-12's (`getReviewNext`, `answerReview`, `getReviewSummary`) — no loop duplicate. From `loopState.ts`: `LoopUiState`, `LoopUiEvent`, `initialLoopState()`, `reduceLoopEvent(state, ev)`. From `useLoopStatus.ts`: `useLoopStatus(userId, userReady): boolean | null`.

- [ ] **Step 0: Verify the contract.** Run `grep -n "^@router\.\(get\|post\)" backend/routes/learn_loop.py` and `grep -n "class .*Body\|class .*Response" backend/routes/learn_loop.py backend/models/__init__.py | grep -i loop`. Fill a path → body → response table in your scratch notes from THOSE plus HANDOFF-07/08/09/12 (the `/check/answer` body fields, the `check` event's options key, the `budget` event's data, the first teach turn after `/plan/approve`, the `start-session` body). Every client function below targets that table, not this prompt's "expected" one. Record each difference for the hand-off's Deviations.

- [ ] **Step 1: Write the failing tests**

`frontend/src/components/learn/loopState.test.ts`:
```ts
import { describe, expect, it } from 'vitest';

import { initialLoopState, reduceLoopEvent } from './loopState';

const item = { question_hash: 'qh1', format: 'free' as const, difficulty: 1 as const, prompt: 'p', node_id: 'n1' };

describe('reduceLoopEvent', () => {
  it('starts in probe with no item', () => {
    expect(initialLoopState()).toMatchObject({ phase: 'probe', item: null, hintOffer: null, leakRedacted: false, budgetPause: null });
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
  it('a hard budget event pauses; a soft one changes nothing (spec §3.5)', () => {
    const hard = reduceLoopEvent(initialLoopState(), { type: 'budget', level: 'hard', resetAt: '2026-09-27T00:00:00Z' });
    expect(hard.budgetPause).toEqual({ resetAt: '2026-09-27T00:00:00Z' });
    expect(reduceLoopEvent(initialLoopState(), { type: 'budget', level: 'soft', resetAt: null }).budgetPause).toBeNull();
    expect(hard.phase).toBe('probe');
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

import { ApiError, budgetPauseOf, getLoopStatus, streamLoopChat, streamLoopCheckAnswer } from './api';

function sseBody(blocks: string[]): ReadableStream { /* as api.stream.test.ts */ }
const ev = (name: string, data: unknown) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`;
const done = ev('done', { type: 'done', step: 'reply', message: '', data: { reply: 'ok', graph_update: {}, mastery_changes: [] } });
const bodyOf = (i = 0) =>
  JSON.parse(String(((globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[i][1] as RequestInit).body));
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
  it('dispatches phase/check/hint_offer/learner_state/budget and returns leak_redacted', async () => {
    const check = { question_hash: 'qh', format: 'free', difficulty: 2 };
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(sseBody([
      ev('phase', { type: 'phase', step: 'loop', message: '', data: { phase: 'check' } }),
      ev('token', { type: 'token', step: 'reply', message: '', data: { delta: 'Hi' } }),
      ev('check', { type: 'check', step: 'loop', message: '', data: check }),
      ev('hint_offer', { type: 'hint_offer', step: 'loop', message: '', data: { rung: 1 } }),
      ev('learner_state', { type: 'learner_state', step: 'loop', message: '', data: { node_id: 'n', p_known: 0.5, band: 'develop' } }),
      ev('budget', { type: 'budget', step: 'loop', message: '', data: { level: 'hard', reset_at: '2026-09-27T00:00:00Z' } }),
      ev('done', { type: 'done', step: 'reply', message: '', data: { reply: 'Hi [redacted]', graph_update: {}, mastery_changes: [], leak_redacted: true } }),
    ])));
    const seen: string[] = [];
    const res = await streamLoopChat('s', 'u', 'm', {
      onToken: (d) => seen.push(`token:${d}`),
      onPhase: (p) => seen.push(`phase:${p}`),
      onCheck: (i) => seen.push(`check:${i.question_hash}`),
      onHintOffer: (r) => seen.push(`offer:${r}`),
      onLearnerState: (s) => seen.push(`state:${s.node_id}:${s.p_known}`),
      onBudget: (b) => seen.push(`budget:${b.level}:${b.reset_at}`),
    });
    expect(seen).toEqual(['phase:check', 'token:Hi', 'check:qh', 'offer:1', 'state:n:0.5', 'budget:hard:2026-09-27T00:00:00Z']);
    expect(res.reply).toBe('Hi [redacted]');
    expect(res.leak_redacted).toBe(true);
    const [url] = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(String(url)).toContain('/api/learn/loop/chat/stream');
    expect(bodyOf()).toEqual({ session_id: 's', user_id: 'u', message: 'm' }); // no model_pref (A15/A26)
  });
});

describe('streamLoopCheckAnswer (spec §13 A16: explicit submissions only)', () => {
  it('free text posts the answer to /check/answer/stream, never /chat/stream', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(sseBody([done])));
    await streamLoopCheckAnswer('s', 'u', 'qh', { answer: 'my answer', idk: false });
    const [url] = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(String(url)).toContain('/api/learn/loop/check/answer/stream');
    expect(bodyOf()).toEqual({ session_id: 's', user_id: 'u', question_hash: 'qh', answer: 'my answer', idk: false });
  });
  it('mc_reason posts the option and the reason', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(sseBody([done])));
    await streamLoopCheckAnswer('s', 'u', 'qh', { option: 'B', reason: 'slope is constant', idk: false });
    expect(bodyOf()).toEqual({ session_id: 's', user_id: 'u', question_hash: 'qh', option: 'B', reason: 'slope is constant', idk: false });
  });
  it('idk posts idk: true and no answer text', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(sseBody([done])));
    await streamLoopCheckAnswer('s', 'u', 'qh', { idk: true });
    expect(bodyOf()).toEqual({ session_id: 's', user_id: 'u', question_hash: 'qh', idk: true });
  });
});

describe('budgetPauseOf (spec §3.5 / A20 429 body)', () => {
  const body = { detail: 'ai budget reached', reset_at: '2026-09-27T00:00:00Z' };
  it('reads a JSON route\'s ApiError', () => {
    expect(budgetPauseOf(new ApiError('ai budget reached', 429, { body }))).toEqual({ resetAt: body.reset_at });
  });
  it('reads a stream route\'s Error (sse.ts: message = raw body, .status set)', () => {
    expect(budgetPauseOf(Object.assign(new Error(JSON.stringify(body)), { status: 429 }))).toEqual({ resetAt: body.reset_at });
  });
  it('ignores other statuses and other 429s', () => {
    expect(budgetPauseOf(new ApiError('boom', 503, { body }))).toBeNull();
    expect(budgetPauseOf(new ApiError('slow down', 429, { body: { detail: 'rate limited elsewhere' } }))).toBeNull();
    expect(budgetPauseOf(new Error('network'))).toBeNull();
  });
});
```

(Confirm `ApiError`'s constructor takes the body through its `fields` argument — `api.ts:47–60`; adapt the two test constructions to the real shape, never the assertion.)

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/lib/api.loop.test.ts src/components/learn/loopState.test.ts`
Expected: FAIL — `budgetPauseOf is not exported` / `Cannot find module './loopState'` (the 404 case also fails if PKG-12's `getLoopStatus` throws on 404).

- [ ] **Step 3: Implement.** In `api.ts`, after `startSessionStream` (move PKG-12's `getLoopStatus` into this block; keep its export name and signature so `Study.tsx` is unchanged):

```ts
// ── Learning loop (PKG-13) ──────────────────────────────────────────────────
// Clients for /api/learn/loop/* (backend/routes/learn_loop.py). Every route
// 404s when the gate is false (spec §7); only getLoopStatus swallows that.
// No loop client takes or sends model_pref: the tier is chosen in code
// (spec §13 A15/A26).
export type LoopPhase = 'probe' | 'plan' | 'teach' | 'check' | 'feedback' | 'close';
export type LoopBand = 'novice' | 'develop' | 'profic';
export interface LoopOption { letter: string; text: string }            // served options; never marked correct (A22)
export interface LoopCheckItem {
  question_hash: string; format: 'free' | 'teachback' | 'mc_reason'; difficulty: 1 | 2 | 3;
  prompt?: string; node_id?: string; options?: LoopOption[] | null;
}
export interface LoopProbeItem extends LoopCheckItem { check_item_id: string; node_id: string; prompt: string }
export type LoopProbeNext = ({ done: false } & LoopProbeItem) | { done: true; phase: LoopPhase; no_check_items?: boolean };
export type LoopProbeAnswerResult =
  | { graded: true; correct: boolean; p_known: number; probe_done: boolean; novice_floor: boolean; reference_answer?: string }
  | { graded: false; unavailable: true };
export interface LoopLearnerState { node_id: string; p_known: number; band: LoopBand }
export interface LoopPlanConcept { node_id: string; concept_name: string; kind: string; p_known: number; band?: LoopBand }
export interface LoopOpenSession { session_id: string; topic: string; started_at: string; phase: LoopPhase }
export interface LoopHintResponse { allowed: boolean; reason?: string; rung?: number; reply?: string }
export interface LoopCloseResponse { phase: LoopPhase; summary: string; self_eval_question: string; if_then_prompt: string }
export interface LoopCheckAnswer { answer?: string; option?: string; reason?: string; idk: boolean }  // PKG-07's LoopCheckAnswerBody
export interface LoopBudgetPause { resetAt: string | null }

export const getLoopStatus = async (userId: string): Promise<{ active: boolean }> => {
  try {
    return await fetchJSON<{ active: boolean }>(`/api/learn/loop/status?user_id=${encodeURIComponent(userId)}`);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return { active: false }; // flag off → legacy
    throw err;
  }
};

/** A20/A26: the 429 body `{"detail": "ai budget reached", "reset_at"}` from a JSON
 * route (ApiError.body) or a stream route (sse.ts: Error.message = raw body). */
export const budgetPauseOf = (err: unknown): LoopBudgetPause | null => {
  const status = (err as { status?: number } | null)?.status;
  if (status !== 429) return null;
  let body: unknown = err instanceof ApiError ? err.body : undefined;
  if (body === undefined && err instanceof Error) {
    try { body = JSON.parse(err.message); } catch { return null; }
  }
  const b = body as { detail?: unknown; reset_at?: unknown } | null;
  if (!b || b.detail !== 'ai budget reached') return null;
  return { resetAt: typeof b.reset_at === 'string' ? b.reset_at : null };
};

// … listLoopSessions / startLoopSession / nextLoopProbe / answerLoopProbe /
// getLoopPlan / approveLoopPlan / postLoopAttempt / requestLoopHint /
// closeLoopSession: thin fetchJSON wrappers over the paths in your Step-0 table
// (camelCase params → the snake_case body keys the routes take).
export const streamLoopChat = (sessionId: string, userId: string, message: string, handlers: StreamChatHandlers = {}) =>
  consumeChatStream('/api/learn/loop/chat/stream', { session_id: sessionId, user_id: userId, message }, handlers);

/** The attempt box's ONLY submit path (spec §13 A16): an explicit answer, never a chat message. */
export const streamLoopCheckAnswer = (
  sessionId: string, userId: string, questionHash: string, a: LoopCheckAnswer, handlers: StreamChatHandlers = {},
) =>
  consumeChatStream('/api/learn/loop/check/answer/stream', {
    session_id: sessionId, user_id: userId, question_hash: questionHash,
    ...(a.idk ? {} : a.option !== undefined ? { option: a.option, reason: a.reason ?? '' } : { answer: a.answer ?? '' }),
    idk: a.idk,
  }, handlers);
```

Extend `StreamChatHandlers` (`:355`) with `onPhase?: (phase: LoopPhase) => void; onCheck?: (item: LoopCheckItem) => void; onHintOffer?: (rung: number) => void; onLearnerState?: (s: LoopLearnerState) => void; onBudget?: (b: { level: 'soft' | 'hard'; reset_at: string | null }) => void;`, the `StreamEvent` type union (`:303`) with the five event names, `ChatResult` (`:295`) with `leak_redacted?: boolean;`, and `consumeChatStream` (`:383–392`) with five `else if` branches before `done` (`ev.type === 'phase'` → `onPhase?.(String(ev.data?.phase) as LoopPhase)`, etc.; `budget` → `onBudget?.({level, reset_at})` from `ev.data`). Destructure the new handlers next to `onToken`/`onGraphUpdate`/`signal`. The legacy `streamChat`/`startSessionStream` callers pass none of them, so their behaviour is unchanged (`api.stream.test.ts` stays green untouched). Check `ApiError` exposes `status` and `body` (`:47–60`).

`loopState.ts`: the reducer exactly as the test describes (`phase`, `item`, `hintOffer`, `learnerState: Record<string, LoopLearnerState>`, `leakRedacted`, `budgetPause: LoopBudgetPause | null`); pure, no React import.

`useLoopStatus.ts`:
```ts
import { useEffect, useState } from 'react';
import { getLoopStatus } from '@/lib/api';

/** null = unresolved; false = legacy tree; true = loop tree. Fails closed.
 * Reads nothing but /status — never learning_loop_beta (spec §7). */
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
Expected: all passed; clean; lint clean. (`Study.tsx`'s `getLoopStatus(...).catch(...)` still compiles and now also resolves `{active: false}` on 404.)

- [ ] **Step 5: Commit**

```
git add frontend/src/lib/api.ts frontend/src/lib/api.loop.test.ts frontend/src/components/learn/loopState.ts frontend/src/components/learn/loopState.test.ts frontend/src/components/learn/useLoopStatus.ts
git commit -m "feat(learning-loop): PKG-13 — loop API clients, explicit check submissions, budget pause, phase reducer

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 6: `LoopLearn` + the `Learn` branch + testids

**Files:**
- Modify: `frontend/src/components/learn/LoopLearn.tsx` (replace the stub), `frontend/src/components/screens/Learn.tsx` (`Learn()` only), `frontend/eslint.config.mjs` (`files` array), `docs/frontend-testids.md` (table row + inventory section `### \`loop\``)
- Create: `frontend/src/components/learn/BudgetPausedBanner.tsx` (shared with Task 7's `DueQueue`)
- Test: `frontend/src/components/learn/LoopLearn.test.tsx`, `frontend/src/components/learn/LearnBranch.test.tsx`; `npx tsc --noEmit`, `npm run lint` (the testid rule: every `<button>/<input>/<textarea>` in `LoopLearn.tsx` must carry a testid); plus the Playwright journeys in Task 9.

**Interfaces:**
- Consumes: Task 5's clients, `budgetPauseOf` and reducer; `resumeSession` (`api.ts:511`); `readResumeParam` (`Learn.tsx`); `KnowledgeGraph` (`components/graph/KnowledgeGraph`) + `getGraph` exactly as `Learn.tsx::SidebarKnowledgeGraph` uses them; `ChatPanel` (`components/chat/ChatPanel.tsx:33–53` props: `messages`, `onSend`, `header`, `streamingText`, `onStop`), `useUser`, `useToast` (`../ToastProvider`), `getCourses` (or the course source HANDOFF-08 names), `DisclaimerModal`, `FullHeightScreen`, `TopBar` (same imports `Learn.tsx` uses). NOT `ModelToggle`, NOT `useModelPref`.
- Produces: `export function LoopLearn()`; `export function BudgetPausedBanner({ testId, resetAt, message, children? })`; the testids below.

- [ ] **Step 1: Write the failing vitest tests** (spec §11.3's two required cases plus A26's).

`frontend/src/components/learn/LoopLearn.test.tsx`:
```tsx
// @vitest-environment jsdom
/**
 * LoopLearn launch readiness (spec §11.3, §13 A26): resume instead of a new
 * probe, no model toggle, the budget banner from a 429, the no-check-items
 * state, the knowledge-map link. Every loop client is mocked; the assertions
 * are on which routes were (not) called and on the rendered testids.
 */
import React from "react";
import { cleanup, render, screen, waitFor, fireEvent } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const search = vi.hoisted(() => ({ params: new URLSearchParams() }));
vi.mock("next/navigation", () => ({
  useSearchParams: () => search.params,
  usePathname: () => "/learn",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn(), prefetch: vi.fn() }),
}));
vi.mock("@/context/UserContext", () => ({ useUser: () => ({ userId: "u1", userReady: true }) }));
const toast = vi.hoisted(() => ({ error: vi.fn(), success: vi.fn(), info: vi.fn() }));
vi.mock("../ToastProvider", () => ({ useToast: () => toast }));  // useToast throws outside a provider

const api = vi.hoisted(() => ({
  getCourses: vi.fn(), listLoopSessions: vi.fn(), resumeSession: vi.fn(),
  startLoopSession: vi.fn(), nextLoopProbe: vi.fn(), answerLoopProbe: vi.fn(),
  getLoopPlan: vi.fn(), approveLoopPlan: vi.fn(), streamLoopChat: vi.fn(), streamLoopCheckAnswer: vi.fn(),
  postLoopAttempt: vi.fn(), requestLoopHint: vi.fn(), closeLoopSession: vi.fn(), getGraph: vi.fn(),
  nextLoopCheck: vi.fn(),
}));
vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), ...api }));

import { ApiError } from "@/lib/api";
import { LoopLearn } from "./LoopLearn";

const course = { course_id: "c1", course_name: "Intro CS" };  // the EnrolledCourse fields LoopLearn reads
const open = (id: string, phase: string, started: string) => ({ session_id: id, topic: `t ${id}`, started_at: started, phase });

beforeEach(() => {
  search.params = new URLSearchParams();
  Object.values(api).forEach((f) => f.mockReset());
  Object.values(toast).forEach((f) => f.mockReset());
  api.getCourses.mockResolvedValue({ courses: [course] });
  api.getGraph.mockResolvedValue({ nodes: [], edges: [], stats: {} });
  api.resumeSession.mockResolvedValue({ session: { id: "s2" }, messages: [{ id: "m1", role: "assistant", content: "welcome back", created_at: "" }] });
});
afterEach(cleanup);

describe("LoopLearn — resume (spec §11.3)", () => {
  it("resumes the newest open session and calls no probe route and no start-session", async () => {
    api.listLoopSessions.mockResolvedValue([open("s2", "teach", "2026-09-21"), open("s1", "check", "2026-09-20")]);
    render(<LoopLearn />);
    const root = await screen.findByTestId("loop-phase");
    await waitFor(() => expect(root.getAttribute("data-session-id")).toBe("s2"));
    expect(root.getAttribute("data-phase")).toBe("teach");
    expect(api.resumeSession).toHaveBeenCalledWith("s2");
    expect(await screen.findByText("welcome back")).toBeTruthy();
    expect(screen.getByTestId("loop-session-s1")).toBeTruthy();   // the picker lists every open session
    expect(api.startLoopSession).not.toHaveBeenCalled();
    expect(api.nextLoopProbe).not.toHaveBeenCalled();
    expect(api.answerLoopProbe).not.toHaveBeenCalled();
  });

  it("a session resumed in the probe continues it with the same session id", async () => {
    api.listLoopSessions.mockResolvedValue([open("s2", "probe", "2026-09-21")]);
    api.nextLoopProbe.mockResolvedValue({ done: false, check_item_id: "i1", question_hash: "qh", node_id: "n1", format: "free", difficulty: 1, prompt: "p", options: null });
    render(<LoopLearn />);
    await waitFor(() => expect(api.nextLoopProbe).toHaveBeenCalledWith("s2", "u1", "c1"));
    expect(api.startLoopSession).not.toHaveBeenCalled();
  });

  it("starts a session and the probe only when none is open", async () => {
    api.listLoopSessions.mockResolvedValue([]);
    api.startLoopSession.mockResolvedValue({ session_id: "s9" });
    api.nextLoopProbe.mockResolvedValue({ done: false, check_item_id: "i1", question_hash: "qh", node_id: "n1", format: "free", difficulty: 1, prompt: "p", options: null });
    render(<LoopLearn />);
    await waitFor(() => expect(api.nextLoopProbe).toHaveBeenCalledWith("s9", "u1", "c1"));
    expect(api.startLoopSession).toHaveBeenCalledTimes(1);
  });

  it("'New session' starts one even when a session is open", async () => {
    api.listLoopSessions.mockResolvedValue([open("s2", "teach", "2026-09-21")]);
    api.startLoopSession.mockResolvedValue({ session_id: "s9" });
    api.nextLoopProbe.mockResolvedValue({ done: false, check_item_id: "i1", question_hash: "qh", node_id: "n1", format: "free", difficulty: 1, prompt: "p", options: null });
    render(<LoopLearn />);
    fireEvent.click(await screen.findByTestId("loop-new-session"));
    await waitFor(() => expect(api.startLoopSession).toHaveBeenCalledTimes(1));
  });

  it("a ?resume= id that is not an open loop session opens read-only and never starts a probe", async () => {
    // spec §11.3: Dashboard/Tree resume links carry pre-launch LEGACY session ids.
    search.params = new URLSearchParams("resume=legacy-1");
    api.listLoopSessions.mockResolvedValue([open("s2", "teach", "2026-09-21")]);
    api.resumeSession.mockResolvedValue({ session: { id: "legacy-1" }, messages: [{ id: "m1", role: "assistant", content: "old legacy chat", created_at: "" }] });
    render(<LoopLearn />);
    const transcript = await screen.findByTestId("loop-readonly-transcript");
    expect(transcript.textContent).toContain("old legacy chat");
    expect(api.resumeSession).toHaveBeenCalledWith("legacy-1");
    expect(api.startLoopSession).not.toHaveBeenCalled();
    expect(api.nextLoopProbe).not.toHaveBeenCalled();
    api.startLoopSession.mockResolvedValue({ session_id: "s9" });
    api.nextLoopProbe.mockResolvedValue({ done: false, check_item_id: "i1", question_hash: "qh", node_id: "n1", format: "free", difficulty: 1, prompt: "p", options: null });
    fireEvent.click(screen.getByTestId("loop-readonly-new-session"));
    await waitFor(() => expect(api.startLoopSession).toHaveBeenCalledTimes(1));
  });

  it("a failed /sessions shows a retry and never starts a probe", async () => {
    api.listLoopSessions.mockRejectedValue(new ApiError("boom", 503));
    render(<LoopLearn />);
    expect(await screen.findByTestId("loop-sessions-retry")).toBeTruthy();
    expect(api.startLoopSession).not.toHaveBeenCalled();
    expect(api.nextLoopProbe).not.toHaveBeenCalled();
  });
});

describe("LoopLearn — A26", () => {
  it("shows no model toggle", async () => {
    api.listLoopSessions.mockResolvedValue([open("s2", "teach", "2026-09-21")]);
    render(<LoopLearn />);
    await screen.findByTestId("loop-phase");
    expect(screen.queryByRole("radiogroup", { name: "Tutor model" })).toBeNull();
  });

  it("a capped student still gets a session and the probe; the opener's budget notice shows the banner", async () => {
    // spec §13 A27: at the hard level the opener is a template carrying `budget`, never a 429.
    api.listLoopSessions.mockResolvedValue([]);
    api.startLoopSession.mockResolvedValue({ session_id: "s9", initial_message: "template", budget: { level: "hard", reset_at: "2026-09-27T00:00:00Z" } });
    api.nextLoopProbe.mockResolvedValue({ done: false, check_item_id: "i1", question_hash: "qh", node_id: "n1", format: "free", difficulty: 1, prompt: "p", options: null });
    render(<LoopLearn />);
    const banner = await screen.findByTestId("loop-budget-paused");
    expect(banner.getAttribute("data-reset-at")).toBe("2026-09-27T00:00:00Z");
    expect(banner.textContent).toContain("Practice and review keep working");
    await waitFor(() => expect(api.nextLoopProbe).toHaveBeenCalledWith("s9", "u1", "c1"));
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("renders the budget pause banner from a 429 body (Check me on a paused novice concept)", async () => {
    api.listLoopSessions.mockResolvedValue([open("s2", "teach", "2026-09-21")]);
    api.nextLoopCheck.mockRejectedValue(
      new ApiError("ai budget reached", 429, { body: { detail: "ai budget reached", reset_at: "2026-09-27T00:00:00Z" } }),
    );
    render(<LoopLearn />);
    fireEvent.click(await screen.findByTestId("loop-check-me"));
    const banner = await screen.findByTestId("loop-budget-paused");
    expect(banner.getAttribute("data-reset-at")).toBe("2026-09-27T00:00:00Z");
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("'Check me' renders the returned check object as the pose (A27)", async () => {
    api.listLoopSessions.mockResolvedValue([open("s2", "teach", "2026-09-21")]);
    api.nextLoopCheck.mockResolvedValue({ phase: "check", check: { question_hash: "qh7", format: "free", difficulty: 2, prompt: "Why does it stop?", options: null } });
    render(<LoopLearn />);
    fireEvent.click(await screen.findByTestId("loop-check-me"));
    const prompt = await screen.findByTestId("loop-check-prompt");
    expect(prompt.getAttribute("data-question-hash")).toBe("qh7");
    expect(prompt.textContent).toContain("Why does it stop?");
    expect(api.nextLoopCheck).toHaveBeenCalledWith("s2", "u1");
  });

  it("renders the budget pause banner from a hard `budget` stream event", async () => {
    api.listLoopSessions.mockResolvedValue([open("s2", "teach", "2026-09-21")]);
    // PKG-07 at the hard level: `phase`, then `budget`, then the stream ends with no `done`.
    api.streamLoopChat.mockImplementation(async (_s, _u, _m, h) => {
      h.onBudget?.({ level: "hard", reset_at: "2026-09-27T00:00:00Z" });
      throw new Error("Chat stream ended without a done event.");
    });
    render(<LoopLearn />);
    await screen.findByTestId("loop-phase");
    // ChatPanel's own testids (ChatPanel.tsx:202, :239) — LoopLearn does not rename them.
    fireEvent.change(await screen.findByTestId("tutor-input"), { target: { value: "why?" } });
    fireEvent.click(screen.getByTestId("tutor-send"));
    const banner = await screen.findByTestId("loop-budget-paused");
    expect(banner.getAttribute("data-reset-at")).toBe("2026-09-27T00:00:00Z");
    expect(api.streamLoopChat).toHaveBeenCalledWith("s2", "u1", "why?", expect.any(Object));
    expect(toast.error).not.toHaveBeenCalled();   // the pause is not an error
  });

  it("renders the empty state from no_check_items", async () => {
    api.listLoopSessions.mockResolvedValue([]);
    api.startLoopSession.mockResolvedValue({ session_id: "s9" });
    api.nextLoopProbe.mockResolvedValue({ done: true, phase: "plan", no_check_items: true });
    api.getLoopPlan.mockResolvedValue({ concepts: [], order: [] });
    render(<LoopLearn />);
    expect(await screen.findByTestId("loop-no-check-items")).toBeTruthy();
  });

  it("keeps the knowledge map reachable", async () => {
    api.listLoopSessions.mockResolvedValue([open("s2", "teach", "2026-09-21")]);
    render(<LoopLearn />);
    const link = await screen.findByTestId("loop-tree-link");
    expect(link.getAttribute("href")).toMatch(/^\/tree/);
  });
});
```

Adapt mocked return shapes to the Step-0 table (e.g. whether `listLoopSessions` returns the array or `{sessions}`), never the assertions.

`frontend/src/components/learn/LearnBranch.test.tsx`:
```tsx
// @vitest-environment jsdom
/** Spec §11.3: Learn() renders LoopLearn for /status → {active: true}.
 * /status is the only input: no settings field carries learning_loop_beta
 * (spec §7, §13 A31), so the UI cannot read the staff/QA toggle at all. */
import React from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/learn",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn(), prefetch: vi.fn() }),
}));
// Settings as the API returns them: no learning_loop_beta key (spec §13 A31).
vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1", userReady: true, settings: { theme: "light" } }),
}));
vi.mock("./LoopLearn", () => ({ LoopLearn: () => <div data-testid="loop-phase" data-phase="probe" /> }));
const getLoopStatus = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), getLoopStatus }));

import { Learn } from "../screens/Learn";

afterEach(cleanup);

it("renders LoopLearn for {active: true} with /status as the only input", async () => {
  getLoopStatus.mockResolvedValue({ active: true });
  render(<Learn />);
  expect(await screen.findByTestId("loop-phase")).toBeTruthy();
  expect(screen.queryByTestId("tutor-topic-picker")).toBeNull();
  expect(getLoopStatus).toHaveBeenCalledWith("u1");
});
```

(Adapt the `useUser` mock to `UserContext`'s real shape. Its settings object carries no `learning_loop_beta`, because the settings API never returns it (spec §13 A31).)

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/components/learn`
Expected: FAIL — `LoopLearn` is the `export {};` stub (no `LoopLearn` export) and `Learn()` never calls `getLoopStatus`.

- [ ] **Step 3: Testids.** Add to `docs/frontend-testids.md`: table row `| Learning loop | \`loop\` | \`frontend/src/components/learn/LoopLearn.tsx\` (the loop-path Learn screen; build phase: staff/QA toggle, after launch: every student; PKG-13) |` and an inventory section:

```
### `loop`

| testid | element |
| --- | --- |
| `loop-phase` | root container; `data-phase` = probe / plan / teach / check / feedback / close; `data-session-id` |
| `loop-session-picker` | the open-sessions list (spec §11.3) |
| `loop-session-{sessionId}` | one open session row (topic, start date); `aria-current="true"` on the resumed one |
| `loop-new-session` | start a new session (the only path to a new probe while a session is open) |
| `loop-sessions-error` | `GET /sessions` failed |
| `loop-sessions-retry` | retry `GET /sessions` (never falls through to a new probe) |
| `loop-budget-paused` | the budget pause banner (A20/A26); `data-reset-at`; `role="status"` |
| `loop-budget-study-link` | link to `/study?mode=cards` inside the banner |
| `loop-no-check-items` | "No check items for this course yet" (A23) |
| `loop-tree-link` | link to `/tree` (`?node=<id>` when an item is current) |
| `loop-rail` | the knowledge-map rail container (wide screens) |
| `loop-probe-item` | the current probe card; `data-question-hash` |
| `loop-probe-input` | free/teachback answer textarea |
| `loop-probe-option-{letter}` | one served `mc_reason` option button |
| `loop-probe-reason` | the one-sentence reason input (`mc_reason`) |
| `loop-probe-submit` | submit the probe answer |
| `loop-probe-idk` | "I don't know" (submits idk, no answer) |
| `loop-probe-reference` | the reference answer shown after a wrong answer or idk |
| `loop-plan-concept-{nodeId}` | one planned concept row (name, band, review badge) |
| `loop-plan-approve` | approve the plan |
| `loop-messages` | the teach/check/feedback chat log (LoopLearn wraps `ChatPanel` in a `loop-messages` container; ChatPanel's own ids stay) |
| `loop-check-prompt` | the current check pose (`check.prompt`, A27); `data-question-hash`, `data-format` |
| `loop-check-me` | "Check me": posts /check/next when no item is current (A27) |
| `loop-readonly-transcript` | a `?resume=` session that is not an open loop session, shown read-only (spec §11.3) |
| `loop-readonly-new-session` | "Start a new session" under the read-only transcript |
| `loop-attempt-input` | free/teachback attempt textarea; first keystroke posts /step/attempt |
| `loop-attempt-option-{letter}` | one served `mc_reason` option in the attempt box |
| `loop-attempt-reason` | the one-sentence reason input in the attempt box (`mc_reason`) |
| `loop-attempt-submit` | submit the attempt to /check/answer/stream (never a chat turn) |
| `loop-attempt-idk` | "I don't know" in the attempt box (posts idk: true) |
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

- [ ] **Step 4: Implement `BudgetPausedBanner.tsx` and `LoopLearn.tsx`.** `BudgetPausedBanner` renders `<div role="status" data-testid={testId} data-reset-at={resetAt ?? ""}>{message}{children}</div>` with the existing muted-warning styling (CSS variables only); `resetAt` is formatted with `toLocaleTimeString` inside the caller's message. LoopLearn structure (write the full component; the shape below is the contract, not a code dump):

```tsx
"use client";
// Learning loop (PKG-13): the loop-path Learn screen (build phase: staff/QA
// toggle; after launch: every student — spec §13 A14). Phase is SERVER-DRIVEN
// — reduceLoopEvent never advances it on its own. No model toggle, no
// model_pref (A15/A26). Resume before probe (spec §11.3).
// Spec: docs/superpowers/specs/2026-09-26-learning-loop-design.md §9, §11.3.
export function LoopLearn() {
  const { userId } = useUser();
  const toast = useToast();
  const searchParams = useSearchParams();
  const [state, dispatch] = useReducer(reduceLoopEvent, undefined, initialLoopState);
  const [courseId, setCourseId] = useState<string | null>(null);
  const [openSessions, setOpenSessions] = useState<LoopOpenSession[] | null>(null); // null = loading
  const [sessionsError, setSessionsError] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [probeItem, setProbeItem] = useState<LoopProbeItem | null>(null);
  const [reference, setReference] = useState<string | null>(null);
  const [noCheckItems, setNoCheckItems] = useState(false);
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [streamingText, setStreamingText] = useState<string | null>(null);
  const [plan, setPlan] = useState<LoopPlanConcept[]>([]);
  const [hint, setHint] = useState<LoopHintResponse | null>(null);
  const [close, setClose] = useState<LoopCloseResponse | null>(null);
  const attemptPosted = useRef<Set<string>>(new Set());   // question_hash → /step/attempt sent
  const streamAbort = useRef<AbortController | null>(null);
  // mount: course (getCourses → first course_id) → listLoopSessions(userId, courseId)
  //   → readResumeParam(searchParams) set and NOT in the list: readOnly(id) — resumeSession(id) → transcript
  //     in loop-readonly-transcript + loop-readonly-new-session; never newSession()/probe on its own (§11.3)
  //   → ≥ 1 open: resume(readResumeParam(searchParams) in list ? that : newest)
  //   → none: newSession()
  //   → error: setSessionsError(true) — never newSession()
  // resume(s): setSessionId(s.session_id); dispatch({type:'phase', phase: s.phase});
  //   resumeSession(s.session_id) → setMessages; s.phase === 'probe' → nextLoopProbe(same id);
  //   'plan' → getLoopPlan; teach/check/feedback → wait (send nothing)
  // newSession(): startLoopSession(userId, courseId, courseName) → setSessionId → nextLoopProbe
  // probe next: done → no_check_items ? setNoCheckItems(true) : …; dispatch phase; plan → getLoopPlan
  // probe submit / idk → answerLoopProbe → reference_answer? setReference; unavailable? muted line; → nextLoopProbe
  // plan approve → approveLoopPlan(sessionId, userId, plan.map(c => c.node_id)) → phase
  // send(text) (chat) → streamLoopChat with onToken/onPhase/onCheck/onHintOffer/onLearnerState/onBudget/signal;
  //   on done: settle the bubble with res.leak_redacted ? res.reply : (accumulated || res.reply); dispatch done
  // check object (A27): onCheck event / res.check from a teach done / nextLoopCheck(sessionId, userId) (loop-check-me)
  //   → dispatch({type:'check', check}); 429 → budget banner; check null + plan_done → muted plan-done line
  // attempt input onChange / option click: if (!attemptPosted.current.has(qh)) { postLoopAttempt; add }
  // attempt submit / idk → streamLoopCheckAnswer(sessionId, userId, qh, answer, sameHandlers) — never send()
  // hint click → requestLoopHint(sessionId, userId, qh, draft) → setHint
  // close click → closeLoopSession → setClose; submit → closeLoopSession(..., {self_eval, if_then}) → done
  // every catch: const pause = budgetPauseOf(err); pause ? dispatch({type:'budget', level:'hard', resetAt: pause.resetAt})
  //   : toast.error(…)   (phase unchanged either way)
  return (
    <FullHeightScreen>
      <DisclaimerModal />
      <div data-testid="loop-phase" data-phase={state.phase} data-session-id={sessionId ?? ""}>
        {/* session picker + New session · budget banner · no-check-items · tree link / rail · phase panels */}
      </div>
    </FullHeightScreen>
  );
}
```

Rules: no numeric literal for timing (no client-side timers at all — the gate is server-side, and the budget banner clears only on the next successful tutor turn or a reload); the settled reply after a `leak_redacted` done is `res.reply` and the streamed bubble text is discarded; a `ChatStreamError` surfaces via `toast.error` and leaves the phase unchanged; a 429 `ai budget reached` or a hard `budget` event sets the banner, never a toast (the "ended without a done event" error that follows a hard `budget` event is swallowed); while paused the chat input is disabled and the attempt box, hint and close stay usable; `signal` aborts on unmount (same `streamAbort` pattern as `Learn.tsx:590–593`). The `loop-learner-state` element renders the concept the current item belongs to (`state.learnerState[state.item?.node_id]`) and is present (empty attributes) even before any event, so the spec can wait on its attributes. `loop-check-prompt` shows `check.prompt` from the `check` object (the template pose, A17/A27). No import of `ModelToggle`/`useModelPref`; no `model_pref` anywhere in the file.

- [ ] **Step 5: The branch in `Learn.tsx`.** Replace `Learn()` (`:327–333`) with:

```tsx
export function Learn() {
  const { userId, userReady } = useUser();
  // Learning loop (PKG-13): one GET decides the tree — /status is the only
  // input (never learning_loop_beta; the server gate decides, spec §7). null →
  // the same fallback the legacy Suspense shows; false / 404 / error → legacy.
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

- [ ] **Step 6: Tests, typecheck, lint**

Run: `cd frontend && npx vitest run src/components/learn && npx tsc --noEmit && npm run lint && npm test`
Expected: all passed; clean; lint clean (if lint lists untagged elements in `LoopLearn.tsx`, tag them — never baseline them); all unit tests pass.

- [ ] **Step 7: Commit**

```
git add frontend/src/components/learn/LoopLearn.tsx frontend/src/components/learn/BudgetPausedBanner.tsx frontend/src/components/learn/LoopLearn.test.tsx frontend/src/components/learn/LearnBranch.test.tsx frontend/src/components/screens/Learn.tsx frontend/eslint.config.mjs docs/frontend-testids.md
git commit -m "feat(learning-loop): PKG-13 — LoopLearn launch UI (resume, picker, budget banner, map) and the Learn branch on loop status

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 7: `DueQueue` launch polish (Study surface)

**Files:**
- Modify: `frontend/src/components/learn/DueQueue.tsx` (PKG-12), `frontend/eslint.config.mjs` (`files` array), `docs/frontend-testids.md` (the `### review` block PKG-12 added)
- Test: `frontend/src/components/learn/DueQueue.test.tsx`

**Interfaces:**
- Consumes: PKG-12's `getReviewNext`, `answerReview`, `getReviewSummary` (HANDOFF-12 §Symbols — names and response keys, incl. `paused`), Task 5's `budgetPauseOf`, Task 6's `BudgetPausedBanner`.
- Produces: testids `review-budget-paused` (`data-reset-at`), `review-empty` (kept), and a testid on every interactive element (`review-next`, `review-option-{letter}`, `review-reason` where PKG-12 left one untagged).

- [ ] **Step 1: Write the failing tests** (`frontend/src/components/learn/DueQueue.test.tsx`, `// @vitest-environment jsdom`; mock the three review clients the same way `LoopLearn.test.tsx` mocks the loop clients):
  - `it("shows 'All caught up' when nothing is due")` — `getReviewNext` → `{item: null, remaining_budget_s: 600, session_id: "r1", retention_target: 0.9, due_total: 0}` → `review-empty` contains "All caught up"; no `review-item`.
  - `it("a 429 'ai budget reached' shows the pause banner and review keeps working")` — `answerReview` rejects with `new ApiError("ai budget reached", 429, { body: { detail: "ai budget reached", reset_at: "2026-09-27T00:00:00Z" } })` → `review-budget-paused` with `data-reset-at`; the "Next" control (`review-next`) still re-polls `getReviewNext`.
  - `it("paused novice concepts show the banner with the count")` — `getReviewSummary` → `{…, paused: 2}` → `review-budget-paused` text contains "2 concept".
  - `it("a flashcard is served, flipped and rated")` — `getReviewNext` → a flashcard item → click `review-flip`, then `review-rate-3` → `answerReview` called once with `kind: "flashcard"`, `rating: 3`.

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/components/learn/DueQueue.test.tsx`
Expected: FAIL — no `review-budget-paused`; (the flashcard case may already pass — it pins PKG-12's flow).

- [ ] **Step 3: Implement** (Behaviour 18): call `getReviewSummary` once on mount (failures are ignored — the summary only feeds the banner and the empty state); render `<BudgetPausedBanner testId="review-budget-paused" …>` when a review call's error gives `budgetPauseOf(err)` (message "AI tutor paused until <time>. Flashcards and review keep working.") or the summary's paused count is > 0 (message "<n> concept(s) paused until your daily AI budget resets. Flashcards and other reviews keep working."); make `review-empty` read "All caught up — nothing is due right now." (plus the summary's due counts when present) and never render a stale item after `item: null`; tag every remaining untagged interactive element; add `"src/components/learn/DueQueue.tsx",` to the eslint testid `files` array; in `docs/frontend-testids.md` `### review`, change the owner line to "owner: `frontend/src/components/learn/DueQueue.tsx` (PKG-12; launch polish PKG-13 — the launch Study surface, spec §11.3)" and add the new testids. The serve → answer → next flow and `Study.tsx` are unchanged.

- [ ] **Step 4: Tests, typecheck, lint**

Run: `cd frontend && npx vitest run src/components/learn && npx tsc --noEmit && npm run lint`
Expected: all passed; clean; lint clean.

- [ ] **Step 5: Commit**

```
git add frontend/src/components/learn/DueQueue.tsx frontend/src/components/learn/DueQueue.test.tsx frontend/eslint.config.mjs docs/frontend-testids.md
git commit -m "feat(learning-loop): PKG-13 — DueQueue launch polish (budget banner, all caught up, testids)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 8: `learn_loop` oracle

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

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 9: The journeys + the full E2E cycle

**Files:**
- Create: `frontend/e2e/support/params.ts`
- Modify: `frontend/e2e/learn-loop.spec.ts` (replace the stub), `frontend/e2e/support/stack.ts` (add `USER_LOOP`, `USER_CAPPED`)
- Test: the spec itself, run under the stack lock.

**Interfaces:**
- Consumes: `mintStorageState` (`support/session.ts`), `queryRaw` (`support/db.ts`), `decryptText` (`support/decrypt.ts`), the `E2E_*` constants (mirrored literals with the `Must match` comment — the Task-1 invariant checks them), the seed's `CAPPED_FLASHCARD` (mirrored with a plain `Mirrors` comment — it is not an `E2E_*` constant).
- Produces: `support/params.ts::learningParams(names) → Record<string, number|boolean>` (python shell-out, same venv/env resolution as `decrypt.ts`), `support/stack.ts::USER_LOOP = "rich-user-loop"`, `USER_CAPPED = "rich-user-capped"`; four tests in `learn-loop.spec.ts` (loop journey, resume, budget cap, build-phase legacy-user split).

- [ ] **Step 1: `params.ts`** — copy `decrypt.ts`'s spawn shape with this program: `import json, sys; from learning import params; names = json.load(sys.stdin); sys.stdout.write(json.dumps({n: getattr(params, n) for n in names}))`. Export `learningParams(names: string[]): Promise<Record<string, number | boolean>>`.

- [ ] **Step 2: Write the journeys**

```ts
/**
 * Journeys (learning loop, PKG-13) — the launch UI (spec §11.3, §13 A26):
 *  1. a loop user walks probe → plan → teach/check (explicit submission, gated
 *     hint) → feedback → close, and every belief change lands in the database
 *     through apply_graph_update;
 *  2. a reload mid-session resumes the same session and calls no probe route;
 *  3. a capped user (today's spend past the novice allowance) sees tutor chat
 *     paused on /learn while review still serves and grades on /study;
 *  4. build phase: a user without the staff/QA toggle keeps the legacy Learn
 *     screen (PKG-14b rewrites this test for the launch, spec §11.2/§11.4).
 *
 * Determinism: function mode (SAPLING_MODEL_MODE=function,
 * SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e) plus
 * LEARNING_LOOP_ENABLED=true (scripts/e2e-up.sh, build phase). The seeded loop
 * users are the only ones carrying the staff/QA toggle
 * (db/seed_local_rich.py::seed_learning_loop). The grader is scripted: an answer
 * carrying GRADER_CORRECT_TOKEN grades correct. Learning constants are read
 * from backend/learning/params.py via support/params.ts — never as literals here.
 */
import type { Page } from "@playwright/test";

import { expect, test } from "./support/fixtures";
import { queryRaw } from "./support/db";
import { decryptText } from "./support/decrypt";
import { learningParams } from "./support/params";
import { mintStorageState } from "./support/session";
import { USER_CAPPED, USER_LOOP } from "./support/stack";

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
// Mirrors backend/db/seed_local_rich.py::CAPPED_FLASHCARD (id, front).
const CAPPED_CARD_ID = "rich-fc-capped-1";
const CAPPED_CARD_FRONT = "What is a bit?";

// Harness constants (†, not learning parameters — see PKG-13 §Named constants).
const LOOP_JOURNEY_TIMEOUT_MS = 240_000;
const GATE_POLL_MARGIN_MS = 15_000;
const DB_POLL_TIMEOUT_MS = 5_000;

type Params = Record<string, number | boolean>;

async function signIn(browser: import("@playwright/test").Browser, userId: string, name: string) {
  const context = await browser.newContext({ storageState: await mintStorageState(userId, name) });
  const page = await context.newPage();
  await page.addInitScript(() => { localStorage.setItem("sapling_disclaimer_ack", "true"); });
  return { context, page };
}

/** Probe → plan → approve (shared by the journeys). Returns how many probe items were answered. */
async function walkProbeAndPlan(page: Page, P: Params): Promise<number> {
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

  await expect(phase).toHaveAttribute("data-phase", "plan");
  await expect(page.locator("[data-testid^='loop-plan-concept-']").first()).toBeVisible();
  await page.getByTestId("loop-plan-approve").click();
  return answered;
}

test("loop user completes probe → plan → check (explicit submission) with a gated hint → close, and the loop writes land", async ({ browser }) => {
  test.setTimeout(LOOP_JOURNEY_TIMEOUT_MS);
  const P = await learningParams(["BKT_L0", "PROBE_ITEMS_PER_SKILL_MIN", "PROBE_SESSION_CAP", "GATE_INDEPENDENT_MIN_S"]);
  const { context, page } = await signIn(browser, USER_LOOP, "Lou Loop");

  // ── Probe + plan (no open session after the fixture's re-seed → a new one) ─
  await page.goto("/learn");
  const phase = page.getByTestId("loop-phase");
  const answered = await walkProbeAndPlan(page, P);
  expect(answered).toBeGreaterThanOrEqual(Number(P.PROBE_ITEMS_PER_SKILL_MIN));
  await expect(page.getByTestId("loop-tree-link")).toHaveAttribute("href", /^\/tree/);   // the map stays reachable
  await expect(page.getByRole("radiogroup", { name: "Tutor model" })).toHaveCount(0);   // no model toggle (A26)

  // ── Teach / check ─────────────────────────────────────────────────────────
  await expect(phase).toHaveAttribute("data-phase", /teach|check/);
  const log = page.getByTestId("loop-messages");
  await expect(log).toContainText(LOOP_TUTOR_REPLY);
  // spec §13 A27: PKG-07 activates the concept's next item after LOOP_TEACH_TURNS_BEFORE_CHECK teach
  // turns, or on "Check me" (POST /check/next, no model call). Click it: the journey never waits on a count.
  const check = page.getByTestId("loop-check-prompt");
  if (!(await check.isVisible())) await page.getByTestId("loop-check-me").click();
  await expect(check).toBeVisible();
  // The check pose is a template (spec §13 A17): the seeded item prompt, no model reply.
  await expect(check).toContainText(LOOP_PROBE_PROMPT);
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

  // Correct attempt → the explicit-submission route (spec §13 A16), never a chat turn.
  const chatBodies: string[] = [];
  page.on("request", (r) => { if (r.url().includes("/api/learn/loop/chat/stream")) chatBodies.push(r.postData() ?? ""); });
  const submitted = page.waitForRequest((r) => r.url().includes("/api/learn/loop/check/answer/stream"));
  await page.getByTestId("loop-attempt-input").fill(`working: ${GRADER_CORRECT_TOKEN}`);
  await page.getByTestId("loop-attempt-submit").click();
  const body = JSON.parse((await submitted).postData() ?? "{}");
  expect(body).toMatchObject({ question_hash: checkHash, idk: false });
  expect(body).not.toHaveProperty("model_pref");
  expect(chatBodies.some((b) => b.includes(GRADER_CORRECT_TOKEN))).toBe(false);
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

  // The explicit submission was graded (A16): an evidence row carries the check's hash.
  const graded = (await queryRaw(
    `SELECT count(*)::int AS n FROM node_mastery_events e JOIN graph_nodes g ON g.id = e.node_id
      WHERE g.user_id = $1 AND e.event_type = 'evidence' AND e.question_hash = $2`, [USER_LOOP, checkHash],
  )) as { n: number }[];
  expect(graded[0].n).toBeGreaterThanOrEqual(1);

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

  // A15: the tier is chosen in code and recorded on every step.
  const tiers = (await queryRaw(
    `SELECT DISTINCT payload->>'tier' AS tier FROM events WHERE user_id = $1 AND event_type = 'zpd.step'`, [USER_LOOP],
  )) as { tier: string | null }[];
  expect(tiers.length).toBeGreaterThan(0);
  for (const t of tiers) expect(["lite", "standard", "deep", "none"]).toContain(t.tier);

  await context.close();
});

test("a reload mid-session resumes the same loop session and calls no probe route", async ({ browser }) => {
  test.setTimeout(LOOP_JOURNEY_TIMEOUT_MS);
  const P = await learningParams(["PROBE_SESSION_CAP"]);
  const { context, page } = await signIn(browser, USER_LOOP, "Lou Loop");
  await page.goto("/learn");
  await walkProbeAndPlan(page, P);
  const phase = page.getByTestId("loop-phase");
  await expect(phase).toHaveAttribute("data-phase", /teach|check/);
  await expect(page.getByTestId("loop-messages")).toContainText(LOOP_TUTOR_REPLY);
  const sessionId = await phase.getAttribute("data-session-id");
  expect(sessionId).toBeTruthy();

  // spec §11.3: a reload of /learn mid-session never starts a probe.
  const afterReload: string[] = [];
  page.on("request", (r) => afterReload.push(new URL(r.url()).pathname));
  await page.reload();
  await expect(phase).toHaveAttribute("data-session-id", sessionId!);
  await expect(phase).toHaveAttribute("data-phase", /teach|check/);
  await expect(page.getByTestId("loop-messages")).toContainText(LOOP_TUTOR_REPLY);   // restored via the resume route
  await expect(page.getByTestId(`loop-session-${sessionId}`)).toBeVisible();         // the picker lists it
  expect(afterReload.some((p) => p.endsWith("/api/learn/loop/sessions"))).toBe(true);
  expect(afterReload.filter((p) => p.includes("/api/learn/loop/probe/") || p.includes("/api/learn/loop/start-session"))).toEqual([]);

  await context.close();
});

test("budget cap: tutor chat pauses on /learn; review still serves and grades on /study", async ({ browser }) => {
  test.setTimeout(LOOP_JOURNEY_TIMEOUT_MS);
  const { context, page } = await signIn(browser, USER_CAPPED, "Casey Cap");

  // ── /learn: the tutor pauses (spec §3.5 hard level; §13 A20/A26) ─────────
  await page.goto("/learn");
  await expect(page.getByTestId("loop-phase")).toBeVisible();   // the loop tree, not the legacy one
  const banner = page.getByTestId("loop-budget-paused");
  // spec §13 A27: at the hard level PKG-07's opener is a template (tier none, no model call) that
  // carries the pause notice — never a 429 — so the banner shows AND the probe still runs
  // (spec §3.5: the probe keeps working at the hard level; grading has its own cap).
  await expect(banner).toBeVisible();
  await expect(page.getByTestId("loop-probe-item")).toBeVisible();
  await expect(banner).toContainText("Practice and review keep working");
  expect(await banner.getAttribute("data-reset-at")).toBeTruthy();
  expect(await page.getByText(LOOP_TUTOR_REPLY).count()).toBe(0);   // no tutor turn ran

  // ── /study: review keeps working at the hard level ───────────────────────
  await page.goto("/study?mode=cards");
  await expect(page.getByTestId("review-due-panel")).toBeVisible();
  await expect(page.getByTestId("review-item")).toContainText(CAPPED_CARD_FRONT);
  await page.getByTestId("review-flip").click();
  await page.getByTestId("review-rate-3").click();
  await expect(page.getByTestId("review-hint")).toBeVisible();
  const graded = (await queryRaw(
    `SELECT count(*)::int AS n FROM events WHERE user_id = $1 AND event_type = 'review.graded'`, [USER_CAPPED],
  )) as { n: number }[];
  expect(graded[0].n).toBe(1);
  const card = (await queryRaw(`SELECT reps, due_at FROM flashcards WHERE id = $1`, [CAPPED_CARD_ID])) as
    { reps: number; due_at: string }[];
  expect(Number(card[0].reps)).toBe(1);
  expect(new Date(card[0].due_at).getTime()).toBeGreaterThan(Date.now());

  await context.close();
});

// Build phase only (spec §13 A14): PKG-14b rewrites this test as "every student
// gets the loop by default" plus "kill switch restores the legacy Learn screen"
// (skipped unless support/fixtures.ts::killSwitchLane; spec §11.2, §11.4).
test("build phase: a user without the staff/QA toggle still gets the legacy Learn screen with the flag on", async ({ page }) => {
  await page.addInitScript(() => { localStorage.setItem("sapling_disclaimer_ack", "true"); });
  await page.goto("/learn");
  await expect(page.getByTestId("tutor-topic-picker")).toBeVisible();
  await expect(page.getByTestId("loop-phase")).toHaveCount(0);
});
```

Adapt: the first teach turn after plan approval, the close flow (one call or two), the attempt/check-answer/hint body fields, the `loop_state` key shape (`attempted_at` per spec §4 PKG-06 comment), the name of PKG-09's close constant, and where the cap first bites — all from the hand-offs. If the gate needs a SUBMITTED wrong answer rather than `/step/attempt` to count as genuine (HANDOFF-06 `genuine_attempt`), insert a wrong submit through the attempt box (`"working: not the token"` → `/check/answer/stream`) before the hint poll and expect the feedback phase and the next check item in between; record it as a deviation from this prompt's flow. Do not assert `ai.budget_capped` rows: the emit is de-duplicated per process and (user, scope, level, UTC day), so a retried test would find none. Add `USER_LOOP` and `USER_CAPPED` to `support/stack.ts` with doc comments in the file's style ("the seeded loop users — staff/QA toggle, build phase; spec §13 A14").

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

Expected: `loop=0 all=0 oracles=0`; `learn-loop.spec.ts` reports 4 passed (loop journey, resume, budget cap, legacy-user split); the oracle prints `0 finding(s), 0 suppressed (allowlisted).`; the full suite count is S₀ + 4. A red `learn-loop.spec.ts`: read `.e2e/backend.log` first (a `UnregisteredHandlerError` means a request-path task has no handler — that is a PKG-04/05/07 gap, fix as a reopened package; a byte-match to an `E2E_*` constant in a "wrong" reply is the seam working). A red legacy spec is a regression in `Learn()` — the branch, not the loop. Never edit `logscan.ALLOWLIST`.

- [ ] **Step 4: Commit**

```
git add frontend/e2e/learn-loop.spec.ts frontend/e2e/support/params.ts frontend/e2e/support/stack.ts
git commit -m "test(learning-loop): PKG-13 — learn-loop journeys (loop, resume, budget cap, legacy split) with DB and oracle assertions

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 10: Hand-off + ledger

- [ ] **Step 1:** Write `docs/superpowers/plans/learning-loop/HANDOFF-13.md` from `HANDOFF-template.md`. "Verify commands" must be exactly these five lines:

```
(under the stack lock) make e2e-up && (cd frontend && npx playwright test e2e/learn-loop.spec.ts) && (cd backend && venv/bin/python -m e2e_oracles); make e2e-down → every learn-loop.spec.ts test passed (loop journey, resume, budget cap, legacy-user split), oracles exit 0
cd frontend && npx tsc --noEmit                                                                   → clean
cd frontend && npx vitest run src/components/learn                                                → all passed
grep -c "E2E_LOOP_" backend/agents/function_handlers_e2e.py                                      → ≥ 3
grep -c '"/sessions"' backend/routes/learn_loop.py                                                → ≥ 1
```

Under "Constants chosen" list every † from the Named-constants table (`SEED_LOOP_CONCEPTS`, `SEED_LOOP_FORMATS`, `SEED_LOOP_ITEMS_PER_CONCEPT`, `SEED_CAPPED_SPEND_FACTOR`, `LOOP_OPEN_SESSIONS_LIMIT`, `LOOP_JOURNEY_TIMEOUT_MS`, `GATE_POLL_MARGIN_MS`, `ORACLE_P_TOLERANCE`, and the `GATE_INDEPENDENT_MIN_S` wait the journey pays). Under "Symbols added" list the route → client mapping you verified in Task 5 Step 0 (the table is the series' only frontend-facing record of the loop API), `GET /sessions` and its response, and the new testids. Under "Known gaps": the budget banner clears only on the next successful tutor turn or a reload (no client timer); `GET /sessions` lists one course's sessions; a reload before the first probe item is shown can start afresh (lazy session rows). Under "Open questions": whether the lane should get a gate override to cut the `GATE_INDEPENDENT_MIN_S` wait (PKG-06 owner decides; this package waits honestly); whether `Learn()`'s one extra GET for legacy users should be cached in `UserContext` (PKG-14 decides).

- [ ] **Step 2:** Ledger. Append `| 13 | frontend-e2e | done | feat/learning-loop-13-frontend-e2e | <sha> | 9 modules + 1 route + 1 spec | — | HANDOFF-13.md |`, plus `verified` rows for 06b, 08, 09, 12 (`verified-by: 13, <date>, <command → output>` from the State-of-the-world rows). Add Deviations for every contract difference from Task 5 Step 0 and every † the spec did not name.

- [ ] **Step 3: Commit**

```
git add docs/superpowers/plans/learning-loop/HANDOFF-13.md docs/superpowers/plans/learning-loop/LEDGER.md
git commit -m "docs(learning-loop): PKG-13 — hand-off and ledger

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 11: PR

- [ ] **Step 1:** Run the self-check loop one last time (below), then:

```
gh pr create --title "feat(learning): PKG-13 frontend-e2e" --body-file - <<'EOF'
Learning loop series, package 16 of 17. Spec: docs/superpowers/specs/2026-09-26-learning-loop-design.md §9, §11.3 (launch UI readiness), §13 A26.

- LoopLearn: server-driven probe → plan → teach/check → feedback → close UI; Learn() branches on GET /api/learn/loop/status only (404/false → legacy tree, unchanged)
- Launch UI readiness: GET /api/learn/loop/sessions (new, read-only, never rate-limited) + resume of the newest open session and a session picker — a reload never starts a probe; knowledge-map rail / /tree link; no model toggle, no model_pref
- Attempt box submits explicit answers to /check/answer/stream (A16), never a chat turn; budget-pause banner from the 429 body or the budget stream event; "no check items yet" state
- DueQueue launch polish: budget banner, "All caught up", testids
- api.ts: /api/learn/loop/* clients; consumeChatStream handles phase/check/hint_offer/learner_state/budget + done.leak_redacted
- function-mode seam: phase-aware loop_tutor handler on all three tier slots, E2E_LOOP_* constants pinned to the spec by tests/test_learning_loop_invariants.py::test_inv_13a
- seed: the loop users (staff/QA toggle, build phase) — rich-user-loop with a 3-concept prerequisite chain and 18 shared encrypted check_items, rich-user-capped with today's spend past the novice allowance and one due flashcard; LEARNING_LOOP_ENABLED=true in e2e-up.sh / e2e.yml / explore.sh (build phase; PKG-14b removes it)
- frontend/e2e/learn-loop.spec.ts: loop journey + DB asserts (learner_state, evidence for the submitted check, close_json ciphertext, zpd.step tier / learn.session_closed, no zpd.leak), resume, budget cap, build-phase legacy split
- e2e_oracles learn_loop: single writer, no leaks, zpd.step bounds, mastery_score mirrors p_known

Flag-off behaviour: /status 404s → legacy Learn; no loop client call is made. Legacy specs green on the flag-on stack (only the seeded loop users carry the staff/QA toggle).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
```

## Self-check loop (run after every task, and once more before the PR)

1. `cd backend && venv/bin/ruff check . && venv/bin/ruff format --check learning tests/test_learning_*.py`
2. `venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q`
3. `venv/bin/python -m pytest tests/ -q` (no `SAPLING_MODEL_MODE` exported)
4. Prompts/tool descriptions touched? **No** in this package → skip evals. (`function_handlers_e2e.py` is scripted output, not a prompt. If you find yourself editing `agents/loop_tutor.py`, `agents/grader.py`, or any `tests/evals/*`, stop: that is a reopened package, not this one.)
5. Request-path agent or route touched? **Yes — the frontend consumes them, the seam handler changed, and `GET /sessions` is new** → the E2E cycle is REQUIRED: the Task 9 Step 3 block, verbatim, under ONE `flock` around up → test → down. Run it after Task 9 and again before the PR. Also `cd frontend && npx tsc --noEmit && npm run lint && npm test` after Tasks 5, 6, 7, 9.
6. Scope check: `git diff --stat main...HEAD` — every path must be in this prompt's Files lists. Anything else: `git checkout main -- <path>` or record a Deviation.
7. Sync check: `diff <(git show main:backend/agents/function_handlers_e2e.py | grep -o "E2E_[A-Z_]*" | sort -u) <(grep -o "E2E_[A-Z_]*" backend/agents/function_handlers_e2e.py | sort -u)` — the only lines are `> E2E_LOOP_FEEDBACK_REPLY`, `> E2E_LOOP_HINT_REPLY`, `> E2E_LOOP_PHASE_PATTERNS`, `> E2E_LOOP_PROBE_PROMPT`; nothing removed.

Green = all seven clean. Max 5 iterations per loop; then write a `BLOCKED` row in `LEDGER.md` with hypothesis, commands, outputs, and stop.

## Regression guard

- Backend suite count N₁₂ (from State of the world) unchanged except for the tests this package adds (`test_learning_loop_invariants.py` +2, `test_e2e_function_handlers.py` +9, `test_learning_seed_loop_user.py`, `test_learn_loop_sessions.py`, `test_e2e_oracles_learn_loop.py`). Zero failures, zero new skips.
- Dependency modules stay green and untouched: `tests/test_learning_check_tool.py` (05), `tests/test_learning_ai_budget.py` (06b), `tests/test_learning_zpd_policy.py` (06), `tests/test_learn_loop_routes.py` (07 — the `/sessions` addition leaves every PKG-07 route test unchanged), `tests/test_learning_probe_planner.py` (08), `tests/test_learning_close_brief.py` (09), `tests/test_learning_review.py` (12).
- Pre-series suites touched by this package: `tests/test_e2e_function_handlers.py` (every pre-existing test unchanged), `tests/test_e2e_oracles_cli.py`, `tests/test_e2e_oracles_judges.py`, `tests/test_e2e_oracles_logscan.py`, `tests/test_model_mode_seam.py`, `tests/test_event_capture_seams.py`.
- Frontend: `npm test` count unchanged except the new files (`api.loop.test.ts`, `loopState.test.ts`, `LoopLearn.test.tsx`, `LearnBranch.test.tsx`, `DueQueue.test.tsx`); `api.stream.test.ts` unchanged and green (the five new stream branches must not alter token/graph_update/error/done handling); `Study.test.tsx` and the other Study screen tests unchanged and green (DueQueue renders only for loop users).
- Browser lane: every pre-existing spec passes on the flag-ON stack (`tutor.spec.ts`, `streaming.spec.ts`, `quiz*.spec.ts`, `dashboard.spec.ts`, `study-*.spec.ts` all render Learn/Study or their deep links for legacy users). Full-suite count = S₀ + 4.
- Oracles: `graph`, `counts`, `ciphertext`, `logscan`, `orphans`, `ragstore` produce the same `0 finding(s)` as on `main`; `learn_loop` adds none.
- With `LEARNING_LOOP_ENABLED` unset locally (`python main.py` without the export): `GET /api/learn/loop/status` and `GET /api/learn/loop/sessions` → 404 and `/learn` renders the legacy picker.

## Acceptance criteria (the next session pastes these)

1. `(under the stack lock) make e2e-up && (cd frontend && npx playwright test e2e/learn-loop.spec.ts) && (cd backend && venv/bin/python -m e2e_oracles); make e2e-down` → every learn-loop.spec.ts test passed (loop journey, resume, budget cap, legacy-user split), oracles exit 0
2. `cd frontend && npx tsc --noEmit` → clean
3. `cd frontend && npx vitest run src/components/learn` → all passed (incl. resume without a probe call, `LoopLearn` for `{active: true}` with `/status` as the only input, no model toggle, banner from a 429, the empty state, DueQueue polish)
4. `grep -c "E2E_LOOP_" backend/agents/function_handlers_e2e.py` → ≥ 3
5. `grep -c '"/sessions"' backend/routes/learn_loop.py` → ≥ 1; `cd backend && venv/bin/python -m pytest tests/test_learn_loop_sessions.py -q` → all passed
6. `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_13a or inv_13b"` → `2 passed`
7. `cd backend && venv/bin/python -m pytest tests/ -q` → zero failures; `venv/bin/ruff check .` → `All checks passed!`
8. `cd frontend && npm test && npm run lint` → all passed; lint clean
9. `grep -n "LEARNING_LOOP_ENABLED" scripts/e2e-up.sh .github/workflows/e2e.yml scripts/explore.sh` → ≥ 1 hit each
10. `grep -c '"learn_loop"' backend/e2e_oracles/__main__.py` → 1
11. `grep -cE "ModelToggle|useModelPref|model_pref" frontend/src/components/learn/LoopLearn.tsx` → 0
12. `git diff --stat main...HEAD` lists only: `frontend/src/components/learn/*`, `frontend/src/components/screens/Learn.tsx`, `frontend/src/lib/api.ts`, `frontend/src/lib/api.loop.test.ts`, `frontend/e2e/learn-loop.spec.ts`, `frontend/e2e/support/{params,stack}.ts`, `frontend/eslint.config.mjs`, `docs/frontend-testids.md`, `backend/routes/learn_loop.py`, `backend/agents/function_handlers_e2e.py`, `backend/db/seed_local_rich.py`, `backend/e2e_oracles/*`, `backend/tests/test_learning_loop_invariants.py`, `backend/tests/test_e2e_function_handlers.py`, `backend/tests/test_learning_seed_loop_user.py`, `backend/tests/test_learn_loop_sessions.py`, `backend/tests/test_e2e_oracles_learn_loop.py`, `scripts/e2e-up.sh`, `scripts/explore.sh`, `.github/workflows/e2e.yml`, `backend/.env.local.example`, `docs/superpowers/plans/learning-loop/{HANDOFF-13.md,LEDGER.md}` (plus any reopened-package files, each with its own first commit).
13. `LEDGER.md` has row `13 | frontend-e2e | done | …` and `verified` rows for 06b, 08, 09, 12.

## Hand-off

`docs/superpowers/plans/learning-loop/HANDOFF-13.md` per the template; the Verify commands block is fixed above (Task 10). Headings: What changed · Symbols added · Constants chosen · Deviations from spec · Known gaps · Verify commands · Open questions for the series owner · Post-hoc changes. PKG-14 reads it: half A runs the Verify block as its PKG-13 State-of-the-world rows; half B rewrites the build-phase legacy-user test, `test_inv_13b` (name kept) and the seed/e2e-up.sh comments, retires `test_legacy_users_are_not_opted_in`, and removes the lane's explicit `true` export (spec §11.2, §11.4). Open questions to record: the `GATE_INDEPENDENT_MIN_S` wait in the lane (override or not — PKG-06's call); caching the status GET for legacy users (PKG-14); whether a later follow-up should fold `LoopLearn` into `Learn.tsx` or keep the branch (PKG-14b keeps it: the kill switch needs the legacy tree, spec §11.6).

## Do not

- Do not edit any existing route, body model, `services/chat_stream.py`, `services/agent_events.py`, `services/events_service.py`, `services/graph_service.py`, `agents/loop_tutor.py`, `agents/grader.py`, or any `tests/evals/*` — the one server addition is `GET /sessions` (Task 4); a contract gap is a client adaptation plus a Deviation, or a reopened package with its own first commit.
- Do not attach `enforce_rate_limit`, a model call, a write or an event to `GET /sessions` (A20: it must never push a student off the loop UI).
- Do not advance a phase client-side, add a client-side gate timer, or let the UI skip an attempt; the ZPD gates are server-side (spec §3.3).
- Do not send an attempt as a chat message: the attempt box posts only to `/check/answer(/stream)` (A16; invariant 26 is the server half).
- Do not start a session or a probe while an open loop session exists and the student has not clicked "New session" (spec §11.3); a failed `GET /sessions` shows a retry, never a new probe.
- Do not add a model toggle, import `ModelToggle`/`useModelPref`, or send `model_pref` from any loop client (A15/A26; spec §12).
- Do not render the streamed tokens when `done.data.leak_redacted` is true; render `done.data.reply`.
- Do not set the staff/QA toggle (`learning_loop_beta`) on any legacy seeded user — only `LOOP_USERS` carry it (build phase, spec §13 A14); do not seed `learner_state`; do not put plaintext into `check_items.prompt/reference_answer/rubric_json/common_wrong_json` (spec §4); never filter or `UNIQUE` on those columns; never key check items on `node_id` (A2).
- Do not lower `STUDENT_DAILY_BUDGET_USD` (or any cap) lane-wide to exercise the banner — it would cap every loop journey (A26); `rich-user-capped` is the only cap fixture, and its spend is computed from `config`, never a literal.
- Do not put a learning constant as a literal in TS, the seed, or the oracle: `learningParams()` in the spec, `from learning.params import …` / `import config` in Python. Harness constants (`LOOP_JOURNEY_TIMEOUT_MS`, `GATE_POLL_MARGIN_MS`, `DB_POLL_TIMEOUT_MS`, `ORACLE_P_TOLERANCE`, `LOOP_OPEN_SESSIONS_LIMIT`, `SEED_LOOP_*`, `SEED_CAPPED_SPEND_FACTOR`) are named `const`s in their owning file and † in the hand-off.
- Do not run the stack outside ONE `flock /tmp/claude-$(id -u)/sapling-e2e-stack.lock` wrapping up → test → down; never separate flock calls for up and down; always tear down, even after failures.
- Do not edit `backend/e2e_oracles/logscan.py::ALLOWLIST` (stays `()`); do not `test.fixme` a journey to make the lane green; do not add `waitForTimeout` sleeps — poll.
- Do not anchor selectors on copy or CSS classes; every new interactive element in `LoopLearn.tsx` and `DueQueue.tsx` carries a `data-testid` from the inventory (never baseline them).
- Do not rename any existing `E2E_*` constant or testid; do not change `tierForScore`, `LearnInner`, `ChatPanel` props, or `Study.tsx`.
- All Supabase access in the seed and the new route through `db/connection.py::table()` (via `seed_helpers` in the seed); the oracle's psycopg connection is `gather._db_conn()` only.
- Do not skip, xfail, or delete any pre-existing test. Do not hand-edit eval cassettes or baselines.
- End every commit with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; end the PR body with the Claude Code attribution line.

## If you get stuck

1. Re-read §Spec, the hand-offs 07/08/09/12 (and 06b) §Symbols added, and `routes/learn_loop.py` before guessing a route or field name.
2. Journey red: `.e2e/backend.log` first (tracebacks, `UnregisteredHandlerError`, 404 `learning loop not enabled` = the flag export did not reach uvicorn), then `frontend/e2e/results/last-run.json` and the retained trace; compare any "wrong" reply byte-for-byte against `E2E_*` constants before calling it a bug (`docs/e2e-exploration.md` §7).
3. A 429 `ai budget reached` in the loop journey or the resume journey (not the cap journey): check `SELECT count(*), sum(cost_usd) FROM llm_usage WHERE user_id = 'rich-user-loop' AND created_at > now() - interval '60 seconds'` — the A20 rate limit counts the user's `llm_usage` rows per minute. Record the finding and the counts; do not raise a cap or seed `llm_usage` for the loop user to hide it (that is a PKG-06b/07 question for the series owner).
4. Three failed iterations on one task → append a `BLOCKED` row to `LEDGER.md` (hypothesis, commands run, outputs), commit what is green, open the PR as draft, stop.
5. Never widen scope to unblock. Never disable a test to unblock.
6. Ambiguity → choose the option closest to the spec, mark it `†` in the hand-off, continue.
