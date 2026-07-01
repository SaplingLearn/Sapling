# Spec: Migrate remaining one-shot LLM calls to Pydantic AI agents (#147)

## Context

Part of the Agent-migration epic (#152), milestone "Agent migration surfaces + staging + performance".
The backend is mid-migration from the legacy `services/gemini_service.py` helper (`call_gemini*`)
onto typed Pydantic AI agents in `backend/agents/`. Three one-shot production call sites remain
outside the intentional legacy chat fallback:

- `backend/routes/study_guide.py:109` — `call_gemini_json(prompt)` (study-guide generation)
- `backend/routes/social.py:127` — `call_gemini(...)` (study-group AI summary)
- `backend/main.py:220` — `call_gemini('Reply with exactly the text: Gemini OK', retries=0)` (admin health probe)

All three route handlers are **sync** `def`s; Pydantic AI agents are invoked with `await agent.run(...)`.
Established agent conventions live in `backend/agents/` (see `note_summary.py`, `summary.py`,
`_providers.py`, `deps.py`): each agent is an `Agent[SaplingDeps, OutputModel]` with a task default
in `_providers._DEFAULTS`, a content-addressed `prompt_version` in `metadata`, and typed Pydantic output.

## Goal

Remove all three direct `call_gemini*` call sites, replacing each with a Pydantic AI agent, so that the
only remaining `gemini_service` callers in the backend are the intentional legacy chat fallback
(`routes/learn.py`, retired later in #151) and tests.

## Requirements

### R1 — Study-guide agent
- Add `backend/agents/study_guide.py` defining `study_guide_agent = Agent[SaplingDeps, StudyGuide]`.
- `StudyGuide` (Pydantic model) mirrors the existing JSON contract the frontend already consumes:
  `exam: str`, `due_date: str`, `overview: str`, and `topics: list[Topic]` where
  `Topic` = `{ name: str, importance: str, concepts: list[str] }`.
- Register a `"study_guide"` task in `agents/_providers.py` (`AgentTask` literal + `_DEFAULTS`),
  defaulting to `gemini-2.5-flash` (this is a quality-sensitive multi-topic generation).
- `routes/study_guide.py::_generate_and_insert` calls the agent instead of `call_gemini_json`.
  The value inserted into `study_guides.content` and returned as `{"content": ...}` MUST remain the
  same JSON shape as today (a dict with `exam/due_date/overview/topics`), so cached-guide reads and the
  frontend keep working unchanged. Serialize the agent's `StudyGuide` output back to that dict via
  `.model_dump()`.
- On agent failure, the route raises `HTTPException(status_code=502, ...)` (per the issue's audit note)
  rather than surfacing a raw 500.
- Remove the `from services.gemini_service import call_gemini_json` import from `study_guide.py`.

### R2 — Study-group summary agent
- Add `backend/agents/social_summary.py` defining `social_summary_agent = Agent[SaplingDeps, SocialSummary]`
  (or a single-field model with a `summary: str`). Output is a 2–3 sentence plain-text summary of a study
  group's collective knowledge, focused on complementary strengths and shared goals (preserve the intent
  of the existing prompt).
- Register a `"social_summary"` task in `_providers.py`, default `gemini-2.5-flash-lite` (short-form prose).
- `routes/social.py::room_overview` calls the agent instead of `call_gemini`.
- Preserve existing behavior: the cache check (`get_cached_summary`) runs first; on a cache miss the agent
  runs and the result is persisted via `save_summary`; on agent failure the same graceful fallback string
  ("This study group has complementary strengths across multiple subjects.") is used and the request still
  returns 200. The member-summary input string is unchanged.
- Remove the now-unused `from services.gemini_service import call_gemini` import from `social.py`.

### R3 — Health probe off `call_gemini`
- `backend/main.py::gemini_test` no longer imports or calls `call_gemini`.
- Replace with a minimal provider-level probe that exercises the same Gemini seam the agents use
  (the shared `GoogleProvider`/model from `agents/_providers.py`), e.g. a tiny `await <probe_agent>.run(...)`
  or a direct model round-trip. Keep the response contract identical: `{"ok": True, "reply": "<text>"}`
  on success and `{"ok": False, "error": "<msg>"}` on failure.
- Keep the existing `require_admin(request)` gate and its ordering (admin check BEFORE any LLM spend).

### R4 — Sync/async bridge
- The three handlers stay sync `def` (their surrounding DB access is sync `table()` and must not block an
  event loop). Introduce ONE small shared helper to run an agent coroutine from sync code
  (e.g. `agents/_run.py::run_agent_sync(coro)` using `asyncio.run`, or reuse an existing bridge if one
  already exists in the codebase). Do not convert the handlers to `async def` (that would run sync httpx
  `table()` calls on the event loop). All three sites use the same helper.

### R5 — No behavior/contract regressions
- Existing tests continue to pass: `tests/test_study_guide_routes.py`, `tests/test_social_students.py`,
  `tests/test_social_messages.py`, `tests/test_gemini_test_auth.py`, and the broader suite.
- The `study_guides.content` JSON contract, the `/api/social/rooms/{room_id}/overview` response shape
  (`{room, members, ai_summary}`), and the `/api/gemini-test` contract (`{ok, reply}` / `{ok, error}`)
  are unchanged.

## Acceptance criteria (verifiable)

1. `grep -rn "call_gemini" backend/routes/study_guide.py backend/routes/social.py backend/main.py`
   returns **no matches** (imports and calls both gone).
2. The only backend `call_gemini*` importers remaining are `routes/learn.py` (legacy chat fallback),
   `services/gemini_service.py` itself, and other not-in-scope surfaces — but specifically study_guide,
   social, and main are clean. (Quiz/documents/calendar/flashcards are OUT of scope for #147.)
3. New agents exist: `agents/study_guide.py`, `agents/social_summary.py`, each an
   `Agent[SaplingDeps, <Model>]` with `metadata` carrying `prompt_version` + `agent` name, following the
   `note_summary.py`/`summary.py` pattern.
4. `_providers.py` `AgentTask` + `_DEFAULTS` include `study_guide` and `social_summary`.
5. New/updated unit tests cover: study-guide agent output serializes to the legacy dict shape; social
   summary cache-miss path calls the agent and cache-hit path does not; social agent-failure path returns
   the fallback string with 200; study-guide agent-failure path returns 502; gemini-test success/failure
   contracts and the admin gate. Agents are mocked (no live Gemini calls in tests), consistent with
   `tests/conftest.py`.
6. `python -m pytest tests/ -q` passes.
7. `ruff check .` passes for changed files.

## Out of scope
- Quiz (`routes/quiz.py`), documents (`routes/documents.py`), calendar (`services/calendar_service.py`),
  flashcards, and `course_context_service.py` — separate migration issues.
- The legacy multi-turn chat fallback in `routes/learn.py` (retired in the #151 final cutover).
- Deleting `services/gemini_service.py` (final cutover, #151).
