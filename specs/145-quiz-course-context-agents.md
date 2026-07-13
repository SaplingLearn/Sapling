# Spec: Quiz generation + course-context regen → agents (#145)

## Context

Agent-migration epic (#152), milestone #2. Three raw `call_gemini*` seams remain across the quiz surface:

- `routes/quiz.py:292` — `call_gemini_json` inside `_legacy_generate_quiz`, the ADR-0001 legacy
  **fallback** for quiz generation (the primary path, `_quiz_via_agent` → `quiz_agent`, already exists).
- `routes/quiz.py:478` — `call_gemini_json(prompt, model=MODEL_LITE)` inside `_update_context`, a
  **background task** that regenerates per-concept quiz context after a submission.
- `services/course_context_service.py:58` — `call_gemini(prompt, retries=1)` inside
  `_generate_summary_with_gemini`, generating the instructor-facing class summary.

The `run_agent_sync` bridge (`agents/_run.py`, from #147/#296) is on `main` for the two sync call sites.
`MODEL_LITE`/`MODEL_SMART` are used only by the legacy quiz path and `_update_context`; the agent path
uses `_PREF_MODEL_NAMES` + `google_model`.

**Coordination:** the quiz submit/generate handlers overlap with #128/#129 (quiz graph-write + scoring);
this PR must not touch the scoring/`apply_graph_update` logic — only the LLM seams.

## Goal

No `call_gemini*` remains in `quiz.py` or `course_context_service.py`. Quiz-context regeneration and the
class summary run through typed Pydantic AI agents; the removed quiz-generation legacy fallback degrades
gracefully (HTTP 502) instead of a second LLM call.

## Requirements

### R1 — Course-summary agent
- Add `agents/course_summary.py`: `course_summary_agent = Agent[..., CourseSummary]`, `CourseSummary`
  = `{ summary: str }` (2–3 paragraph instructor summary). Register `course_summary` in `_providers`
  (`gemini-2.5-flash`). Persona lives in the system prompt; the metrics go in the user message.
- `course_context_service._generate_summary_with_gemini` calls the agent via `run_agent_sync`, returns
  `result.output.summary`, and keeps the existing `except` → deterministic template fallback string.
- Remove `from services.gemini_service import call_gemini` from `course_context_service.py`.

### R2 — Quiz-context agent
- Add `agents/quiz_context.py`: `quiz_context_agent = Agent[..., QuizContext]` where `QuizContext`
  mirrors the `quiz_context_update.txt` schema exactly: `weak_areas: list[str]`,
  `common_mistakes: list[str]`, `questions_seen_summary: str`,
  `recommended_difficulty: Literal["easy","medium","hard"]`, `notes: str`. Register `quiz_context` in
  `_providers` (`gemini-2.5-flash-lite`).
- `routes/quiz.py::_update_context` runs the agent via `run_agent_sync`, converts output with
  `.model_dump()`, and passes that dict to `save_quiz_context` (unchanged storage shape). Keep the
  existing `try/except: pass` so a context-update failure never breaks submission.

### R3 — Remove the quiz-generation legacy fallback
- Delete `_legacy_generate_quiz` and the `from services.gemini_service import MODEL_LITE, MODEL_SMART,
  call_gemini_json` import.
- In `generate_quiz`, the agent-failure branches (`UsageLimitExceeded`/`UnexpectedModelBehavior` and
  bare `Exception`) no longer call the legacy path; they raise
  `HTTPException(status_code=502, detail=<clear message>)`. The `except HTTPException: raise` stays
  (404 for unknown concept node is raised BEFORE the agent call and is unaffected).
- `body.model_pref` "fast"/"smart" still works on the agent path via `_resolve_model_pref` (unchanged).

### R4 — No scoring/graph changes (coordination guard)
- `submit_quiz` scoring, `apply_graph_update`, and the `quiz_attempts` writes are unchanged (only the
  `_update_context` LLM seam inside it changes). Don't touch #128/#129 territory.

### R5 — Tests
- `tests/test_quiz_routes.py`:
  - The 4 submit tests that `patch("routes.quiz.call_gemini_json", return_value={})` (to no-op the
    background context update) → repoint to `patch("routes.quiz._update_context")` (no-op the whole
    background task), since `call_gemini_json` no longer exists in the module.
  - `TestGenerateQuizLegacyFallback` → rewrite as degrade tests: agent `UsageLimitExceeded`, bare
    `Exception`, and all-questions-drift now yield **HTTP 502** (not a legacy quiz). Remove
    `_patch_legacy_dependencies` and the `call_gemini_json`/`MODEL_LITE`/`MODEL_SMART` legacy-model
    tests (`test_legacy_fallback_uses_smart_when_pref_smart` etc.).
  - Keep the agent-path happy-path + wire-shape tests unchanged.
- Add `tests/test_oneshot_agents.py` (or a new file) coverage: `_update_context` runs the quiz-context
  agent and calls `save_quiz_context` with the `model_dump()` dict; `_generate_summary_with_gemini`
  returns the agent summary on success and the template on agent failure.
- All agent runs mocked; no live Gemini in the default run.

## Acceptance criteria (verifiable)
1. `grep -rn "call_gemini" backend/routes/quiz.py backend/services/course_context_service.py` → no matches.
2. New agents exist: `agents/course_summary.py`, `agents/quiz_context.py`, each `Agent[..., <Model>]`
   with `metadata` (`prompt_version` + `agent`); `_providers` `AgentTask`+`_DEFAULTS` include
   `course_summary` + `quiz_context`.
3. `QuizContext` fields exactly match `quiz_context_update.txt`; `_update_context` saves `.model_dump()`.
4. Agent-generation failure in `generate_quiz` returns **502** (no legacy quiz served), and a
   pre-agent unknown-node still returns **404**.
5. `_generate_summary_with_gemini` returns the agent summary on success and the deterministic template
   on agent failure (test).
6. `submit_quiz` scoring/`apply_graph_update`/`quiz_attempts` writes unchanged (existing scoring tests pass).
7. `python -m pytest tests/test_quiz_routes.py tests/test_shared_course_context.py -q` passes; full
   `python -m pytest tests/ -q` shows no new failures vs `main`.
8. `ruff check .` passes for changed files.

## Out of scope
- Flashcards (#146), documents, the study-guide/social one-shots (#147, merged).
- `quiz_agent` itself and the wire-format mapping (`_agent_question_to_wire`) — unchanged.
- Scoring/graph-write logic (#128/#129).
- Deleting `services/gemini_service.py` (#151).
