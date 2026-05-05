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

## Addendum (2026-05-04, after PR #71 review)

Three post-review fixes landed before merge:

1. **`QuizQuestionType` restricted to `multiple_choice` only.** The
   original Literal also accepted `short_answer`, but the route-side
   wrapper synthesized a single-option grading shim that didn't actually
   work — `submit_quiz` grades by option-label lookup and the frontend
   has no UI for free-text answers. Schema-level rejection (Pydantic
   ValidationError on `type="short_answer"`) is now the contract; pinned
   by `test_short_answer_type_is_rejected_at_schema_layer`. Real
   short-answer support (LLM-judged or fuzzy-match grading) is a future
   ADR when the frontend has the UI to match.

2. **`_agent_question_to_wire` no longer silently rewrites correct
   flags.** Old behavior: if the agent's `correct_answer` didn't match
   any option verbatim, the wrapper marked the FIRST option correct so
   `submit_quiz` could "still grade" the attempt. New behavior: log a
   warning and return None; the caller filters those out. If all
   questions in a generation drift like this, the route raises and
   degrades to legacy fallback rather than serving an empty quiz.
   Pinned by `TestQuizWireFormatContract` (3 tests: well-formed
   passthrough, drift drops, whitespace tolerance).

3. **Eval cases all-MCQ.** The 3 short-answer cases were rewritten as
   MCQ at the same difficulty levels (PHYS 101 definitions, ECON 201,
   theory of computation). `ShortAnswerShapeEvaluator` removed.
   Module-level assertion verifies all 8 cases are MCQ — adding a
   short-answer case will fail to import until short-answer support
   actually exists.

## Addendum (2026-05-04, post-merge with main): per-request fast/smart toggle

After merging main into the branch, a fourth fix landed to close the
asymmetry between the new agentic quiz route and the chat tutor:

- **Main shipped `model_pref: Literal["fast", "smart"]`** on the chat
  body (PR #73), letting users pay for `gemini-2.5-pro` per request.
- **The quiz route originally had only `SAPLING_MODEL_QUIZ`**, an
  env-var-only override.

Resolved by adding the same `model_pref` field to `GenerateQuizBody`
and threading it through both paths:

- Agent path: `_quiz_via_agent` builds an optional model override via
  `_resolve_model_pref(...)` and passes `model=` per call to
  `quiz_agent.run`. None falls through to the agent's
  `model_for("quiz")` default.
- Legacy fallback: `_legacy_generate_quiz` swaps `MODEL_LITE` for
  `MODEL_SMART` when `body.model_pref == "smart"`. The fast/None
  cases stay on `MODEL_LITE`.

Pinned by `TestQuizModelPref` (5 tests): smart → flash-pro override,
fast → flash-flash override, no-pref falls through, unknown pref
falls through, and legacy fallback honors smart.

Decision rationale: keep the env var (`SAPLING_MODEL_QUIZ`) for ops
defaults AND accept `model_pref` for per-request overrides. They are
two independent layers, not multiplicative — the env var sets the
agent's startup baseline (`model_for("quiz")` reads it at process
start); the body field, when present, fully replaces that default
for the current call by passing `model=...` to `quiz_agent.run`.
Same shape as the chat tutor on main, so the two AI-driven routes
are now symmetric.

`fast` and `smart` resolve identically across the agent path AND the
legacy fallback (commit ddd109b initially missed this; it was fixed
in the same iteration so a `fast` request that trips the agent
guardrails still gets `gemini-2.5-flash`, not silently downgraded to
`gemini-2.5-flash-lite`). The route's `_PREF_MODEL_NAMES` table is
the single source of truth; the legacy `else`/`elif` chain mirrors
it exactly.

## Pre-existing test failures (not caused by this refactor)

- `tests/test_documents_routes.py::test_rejects_file_over_15mb` — asserts
  against the OLD 15 MB cap. Cap was bumped to 100 MB in commit 9912a25.
  Worth a separate one-line test fix; not blocking refactor #2.
- `test_graph_service.py::test_skips_self_edges` and
  `test_ocr_pipeline.py::*` — live-Supabase 409 conflicts, pre-existing.
