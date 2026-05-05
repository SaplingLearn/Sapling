# Sub-agent B — Refactor `services/calendar_service.py` to use the agent

Replace the `call_gemini_json` syllabus parsing with an agent-first path
that falls back to the legacy parser per ADR 0001. WRITE the changes,
run tests, report back.

Repo: `/Users/josegaelcruzlopez/Documents/Startup_Projects /Sapling`
Branch: `refactor/4-syllabus-unification` (already checked out)

## Context already in place — VERIFIED, do not modify

- `backend/agents/syllabus_extraction.py` — `syllabus_extraction_agent`
  with `SyllabusAssignments` output. Used today by
  `routes/documents.py::upload_document` (refactor #1).
- `backend/agents/tools/syllabus_adapter.py` (or inline in
  `agents/syllabus_extraction.py`) — `syllabus_to_wire_dict` adapter
  built by sub-agent A. Maps `SyllabusAssignments` to the legacy
  dict shape `{assignments, warnings, raw_text, course_title, grading_categories}`.
  Tests in `tests/test_syllabus_adapter.py` are green.
- `backend/services/extraction_service.py::extract_text_from_file` —
  text extraction that runs BEFORE the LLM call. Stays as-is.
- `backend/services/assignment_dedupe.py` — pure helpers, untouched.

## Why

`services/calendar_service.py::parse_syllabus` (lines 54-58) is the
last caller of the legacy syllabus prompt. ADR 0005 carved out
"syllabus extraction unification" as refactor #4. Migrating this caller
onto `syllabus_extraction_agent` removes the duplication: same prompt
source-of-truth, same eval cassette, same Logfire span shape across
both consumers (`routes/documents.py` and `routes/calendar.py`).

## What to read first

- `backend/services/calendar_service.py` — entire file (89 lines).
  Pay attention to:
  - `parse_syllabus` (line 54) — the legacy LLM call.
  - `extract_assignments_from_file` (line 67) — the public entry point
    that's wired into `routes/calendar.py`.
  - `process_and_save_syllabus` (line 77) — full pipeline used by
    `tests/test_ocr_pipeline.py` only. Architecture.md notes it is
    "exists for direct OCR→Gemini→DB use but is not currently wired
    to a route."
- `backend/routes/quiz.py:_quiz_via_agent` + `_legacy_generate_quiz` —
  the orchestrator-vs-legacy fallback pattern from PR #71. Mirror it
  here.
- `backend/routes/learn.py:_chat_via_agent` + `_legacy_chat` — same
  pattern from PR #78. Read both — the symmetry decisions
  (model defaults, fallback exception classes, comment style) carry
  over here.
- `backend/agents/deps.py::SaplingDeps` — what to pass for `deps`.
  `course_id` and `session_id` don't apply here; user_id may not
  apply either (syllabus extraction in `process_and_save_syllabus` is
  user-scoped because of the dedup-write step, but the *extraction*
  itself isn't). Pass placeholder `user_id` if needed — the agent
  doesn't use it for this output type.
- `backend/services/request_context.py::current_request_id` — for
  the request-id correlation, mirror the routes' usage.

## What to change

### 1. Add imports to `services/calendar_service.py`

```python
import asyncio

from pydantic_ai.exceptions import UsageLimitExceeded, UnexpectedModelBehavior

from agents.syllabus_extraction import syllabus_extraction_agent
from agents.deps import SaplingDeps
# Pick whichever path sub-agent A chose for the adapter:
from agents.tools.syllabus_adapter import syllabus_to_wire_dict
# OR
from agents.syllabus_extraction import syllabus_to_wire_dict
```

### 2. Add `_extract_via_agent` helper

```python
async def _extract_via_agent(
    extracted_text: str,
    *,
    user_id: str = "",
    request_id: str = "",
) -> dict:
    """Run syllabus_extraction_agent on `extracted_text` and convert
    its output to the legacy wire-format dict.

    Returns the same shape as the legacy `parse_syllabus`:
    {"assignments": [...], "warnings": [...], "raw_text": str,
     "course_title": str | None, "grading_categories": [...]}.
    """
    deps = SaplingDeps(
        user_id=user_id or "anonymous",
        course_id=None,
        supabase=None,
        request_id=request_id or "",
    )
    result = await syllabus_extraction_agent.run(extracted_text, deps=deps)
    return syllabus_to_wire_dict(result.output, raw_text=extracted_text)
```

### 3. Refactor `extract_assignments_from_file`

Two flavors of caller exist:
- `routes/calendar.py:122` calls `insert_new_assignments` directly,
  not through `extract_assignments_from_file`.
- `routes/calendar.py` *does* call `extract_assignments_from_file` from
  the `/import-extract` route at line ~99 (verify the exact line).
- `tests/test_ocr_pipeline.py` calls `extract_assignments_from_file`
  and `process_and_save_syllabus` directly.

Make `extract_assignments_from_file` the orchestrator-vs-legacy
fallback:

```python
def extract_assignments_from_file(
    file_bytes: bytes, filename: str, content_type: str,
    *, user_id: str = "", request_id: str = "",
) -> dict:
    """Extract text from file then parse assignments via the agent
    (legacy fallback per ADR 0001).
    """
    text = extract_text_from_file(file_bytes, filename, content_type)
    if not text.strip():
        return {"assignments": [], "warnings":
                ["No text could be extracted from the file."], "raw_text": ""}

    try:
        result = asyncio.run(
            _extract_via_agent(text, user_id=user_id, request_id=request_id)
        )
    except (UsageLimitExceeded, UnexpectedModelBehavior) as e:
        logger.warning(
            "Syllabus agent guardrails tripped; falling back to legacy",
            exc_info=e,
        )
        result = parse_syllabus(text)
        result.setdefault("raw_text", text)
    except Exception:
        logger.exception(
            "Unexpected syllabus-agent failure; falling back to legacy"
        )
        result = parse_syllabus(text)
        result.setdefault("raw_text", text)

    return result
```

NOTE: `extract_assignments_from_file` is **synchronous** today (called
from a sync route in `routes/calendar.py`). Wrapping the agent call in
`asyncio.run` inside a sync function is acceptable here — the function
is called from a request thread, not an event loop. If the route
becomes async later, switch this to `await`. Add a TODO comment.

ALTERNATIVELY: keep `extract_assignments_from_file` as a thin sync
wrapper and create an async sibling `extract_assignments_from_file_async`
for any new async callsites. Pick whichever fits the existing code
style. Document the choice in your report.

### 4. Backwards compat for new keys

`syllabus_to_wire_dict` adds `course_title` and `grading_categories`
keys to the result dict. The legacy `parse_syllabus` did NOT include
these. Confirm consumers (esp. `routes/calendar.py`) tolerate the new
extra keys — they should, since dict consumers usually `.get()` known
keys. If a consumer does strict shape matching, file a follow-up;
DO NOT remove the new keys.

Also confirm the LEGACY fallback dict gains the same keys (or callers
fall back gracefully when the legacy path runs and they're missing).
The cleanest move: have the legacy `parse_syllabus` wrapper call site
also pass through any extra keys the LLM returned, and have the
legacy fallback's missing keys be `.get()`-safe on the consumer side.

### 5. Tests

Update `backend/tests/test_ocr_pipeline.py`:

- The 3 pre-existing failures (`test_skips_self_edges`,
  `test_save_to_db`, `test_full_pipeline`) are pre-existing live-DB
  failures unrelated to this refactor. DON'T try to fix them in
  this PR.
- Add a new class `TestExtractAssignmentsViaAgent` with:
  - `test_returns_agent_assignments` — mock `syllabus_extraction_agent.run`
    to return a known `SyllabusAssignments`. Assert the dict shape +
    that the values came from the agent.
  - `test_falls_back_to_legacy_on_usage_limit` — agent raises
    `UsageLimitExceeded`; legacy `parse_syllabus` is invoked.
  - `test_falls_back_to_legacy_on_unexpected_exception` — bare
    `Exception` triggers fallback.
  - `test_legacy_path_still_works_when_text_empty` — `extract_text_from_file`
    returns "" → returns the empty-text placeholder dict without ever
    calling either path.

- Add an autouse fixture if needed to force the agent path or the
  legacy path per test class (mirror PR #71/#78's `_force_legacy_pipeline`
  pattern). NOTE: existing tests in `test_ocr_pipeline.py` directly
  test `parse_syllabus` itself — those continue to test the legacy
  function in isolation. They don't need to change.

## Verify

```bash
cd "/Users/josegaelcruzlopez/Documents/Startup_Projects /Sapling/backend"
python -m pytest tests/test_ocr_pipeline.py -q --no-header
python -m pytest tests/test_syllabus_adapter.py tests/test_ocr_pipeline.py -q --no-header
python -m pytest tests/ -q --no-header --ignore=tests/evals
```

Backend baseline today: ~578 passing with **3 pre-existing live-Supabase
failures** (`test_skips_self_edges`, `test_save_to_db`, `test_full_pipeline`).
Those should stay failing; nothing else should regress. Add at least
4 new tests.

## Constraints

- DO NOT delete `parse_syllabus`, `prompts/syllabus_extraction.txt`,
  or `process_and_save_syllabus` in this PR. ADR 0001 contract;
  Sub-agent E's cleanup PR handles deletion after main is stable.
- DO NOT modify `agents/syllabus_extraction.py` (sub-agent A's file
  if they put the adapter there; otherwise it's the agent's home and
  out of scope). DO NOT bump `_PROMPT_HASH`.
- DO NOT modify `routes/calendar.py` (sub-agent C verifies it).
- DO NOT modify `tests/evals/syllabus_extraction.py` (sub-agent D).
- DO NOT change `save_assignments_to_db`, `insert_new_assignments`,
  `load_existing_assignment_keys`, or `assignment_dedupe_key`. Pure
  dedup helpers; untouched.
- DO NOT commit. No ADRs.

## Report

- Files changed with line counts.
- Whether `extract_assignments_from_file` stays sync (with internal
  `asyncio.run`) or you split into a sync + async pair.
- Number of new tests added.
- Pytest summary line (pass / fail / which test names if anything red).
- Anything that didn't fit (e.g. a consumer in `routes/calendar.py`
  did strict-key matching and broke — flag for sub-agent C).

Aim for under 250 words.
