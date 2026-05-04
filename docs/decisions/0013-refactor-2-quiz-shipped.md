# 0013: Refactor #2 (quiz_agent) shipped

- Status: accepted
- Date: 2026-05-04
- Supersedes: refines 0005

## Context

ADR 0005 picked `routes/quiz.py::generate_quiz` as refactor #2. This ADR captures
what shipped, what surprised us, and what we learned for refactor #3 (chat tutor).

## Decision

`quiz_agent` lives at `backend/agents/quiz.py` and is wired into the existing
`POST /api/quiz/generate` route via the same orchestrator-vs-legacy fallback
pattern PR #67 established for document upload. Output schema is intentionally
flat (`Quiz.questions: list[QuizQuestion]`) per ADR 0003 convention 4 — Gemini
rejects nested-state structured-output schemas.

Prompt version: `17ab80b30316` (sha256[:12] of the system prompt). Future prompt
changes bump this hash; Logfire traces tag every quiz run with the active
version so we can answer "which prompt produced this quiz three weeks ago?"

## What shipped

- `backend/agents/quiz.py` — typed agent with `Quiz` + `QuizQuestion` outputs,
  registers `read_concepts_for_user_tool` + `read_misconceptions_for_course_tool`.
- `backend/agents/_providers.py` — added `quiz` task; default
  `gemini-2.5-flash-lite`, override via `SAPLING_MODEL_QUIZ`.
- `backend/agents/tools/graph_read.py` — pure-async + tool-wrapped reads of
  concept mastery and class-level misconceptions, per ADR 0004.
- `backend/routes/quiz.py` — `_quiz_via_agent` (new path) and
  `_legacy_generate_quiz` (preserved fallback). Route is now async; falls back
  on `UsageLimitExceeded` / `UnexpectedModelBehavior` / any other exception.
- `backend/tests/evals/quiz_generation.py` — 8 cases × 6 evaluators per ADR 0005
  (3 difficulty × 2 type, all 6 cells covered).
- `backend/tests/test_quiz_routes.py` — 19 tests (was 14; added 3 agent-success
  + 2 agent-fallback).
- `backend/tests/test_quiz_agent_imports.py` — 2 smoke tests.
- `backend/tests/test_graph_read_tools.py` — 5 tests for the new tool surface.

## What surprised us

1. **The "quiz cache" doesn't exist as I'd assumed in ADR 0005.**
   `quiz_context_service.get_quiz_context` is a per-(user, concept) post-quiz
   notes service, NOT a generated-quiz cache. There's no `(user, course,
   settings)` cache key to invalidate on prompt-version bumps. Decision: don't
   add one in this refactor. Cache concerns deferred to "if we ever build a
   real quiz cache."

2. **`GenerateQuizBody` has no `course_id` field.** Course context is derived
   from the target concept's `graph_nodes.course_id`. `_quiz_via_agent` reads
   that row first, then threads `course_id` into `SaplingDeps` so the
   agent's tools scope correctly.

3. **Wire-format mismatch between agent output and persisted shape.** Legacy
   `quizzes_json` rows store `{question, options:[{label,text,correct}],
   explanation, concept_tested, difficulty}` with options as an array of
   labeled objects. `Quiz.questions` is flatter: `options:[str]` plus
   `correct_answer:str`. Built `_agent_question_to_wire` to convert. Frontend
   submission and grading paths are unchanged — wire shape held constant.

4. **`misconceptions` table doesn't exist; data lives in
   `course_concept_stats.common_misconceptions[]`.** ADR 0004's spec called
   for a table that doesn't exist; sub-agent A read the actual aggregated
   shape and flattened it correctly. The function contract
   (`Misconception[]`) holds; only the SELECT changed.

5. **Short-answer grading doesn't exist yet.** `submit_quiz` grades by
   `q["options"][i].correct` lookup. For short-answer questions, the wrapper
   synthesizes a single-option `{label:"A", correct:True}` so existing
   grading code keeps working. Real short-answer grading (e.g. fuzzy-match,
   LLM-judged) is its own future scope.

6. **`HTTPException` had to be re-raised inside the catch.** The route's
   try/except Exception fallback would otherwise swallow legitimate 404s
   ("Concept node not found") and call legacy recursively. Caught
   StarletteHTTPException explicitly and re-raised before the bare except.

## Consequences

- (+) Quiz generation is typed end-to-end. Downstream UI parses structured
  questions instead of regex'ing strings.
- (+) Misconception use is auditable in Logfire — span trees show
  `read_misconceptions_for_course_tool` arguments + return value.
- (+) Per-task model routing means we can A/B `gemini-2.5-flash-lite` vs
  `gemini-2.5-flash` on quiz generation by flipping `SAPLING_MODEL_QUIZ`
  without touching code.
- (+) Eval cassettes (when recorded) gate prompt changes via the existing
  `.github/workflows/evals.yml` workflow.
- (−) Legacy quiz path is now ~150 lines of code we still ship. Can't delete
  until refactor #3 (chat tutor) ships per ADR 0001's migration plan.
- (−) Agent latency may exceed the legacy single-call latency on the cold
  path (tool calls add round-trips). Acceptable since quiz generation is a
  post-study, non-streaming flow — user is willing to wait. Will measure in
  Logfire after ~50 quizzes.
- (−) Test count grew (438 backend, +5 quiz route, +5 graph tools, +2 quiz
  imports, +2 size-limit test fixed downstream) — test runtime up ~3s.
  Fine.

## What I'd carry into refactor #3 (chat tutor)

1. **The "input dict → typed model dict for storage" wrapper pattern.** The
   `_agent_question_to_wire` adapter let us change the agent's internal
   shape without touching the persisted shape or the frontend. Chat tutor's
   message-history shape is the same kind of contract — write the adapter
   first, before touching the storage layer.

2. **`HTTPException` re-raise inside the bare-Exception catch.** Easy to
   forget; bites silently. Pattern stays.

3. **Don't pre-stuff context in the user-message string.** Tools >>>
   prompt-string augmentation. Two reasons: (a) Logfire traces show what
   the agent fetched and decided to use, (b) the model gets to skip irrelevant
   tools when the prompt doesn't need them.

4. **Deps construction is identical across refactors.** Made a mental note
   to extract a `make_deps_from_request(request, user_id, course_id)`
   helper in refactor #3 so SSE error payloads, agent traces, and idempotency
   keys all share one request_id without three lines of boilerplate per route.

5. **The eval set is more valuable than the unit tests at finding prompt
   regressions.** Unit tests mock the agent, so they only catch wiring bugs.
   Eval cases run the real agent (against cassettes) — when refactor #3
   ships, write the eval first, record cassettes, then refactor with
   confidence.

## Pre-existing test failures (not caused by this refactor)

- `tests/test_documents_routes.py::test_rejects_file_over_15mb` — asserts
  against the OLD 15 MB cap. Cap was bumped to 100 MB in commit 9912a25.
  Worth a separate one-line test fix; not blocking refactor #2.
- `test_graph_service.py::test_skips_self_edges` and
  `test_ocr_pipeline.py::*` — live-Supabase 409 conflicts, pre-existing.
