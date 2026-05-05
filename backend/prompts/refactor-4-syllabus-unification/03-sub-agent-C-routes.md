# Sub-agent C — Verify `routes/calendar.py` consumers + pin with tests

Sub-agents A and B have refactored `services/calendar_service.py`.
The wire format is supposed to be unchanged. This sub-agent's job is
to **verify** that — read every consumer of `extract_assignments_from_file`
and `parse_syllabus`, confirm none of them broke, and pin the
verification with tests if any consumer was relying on a key the new
adapter doesn't preserve. WRITE the changes, run tests, report back.

Repo: `/Users/josegaelcruzlopez/Documents/Startup_Projects /Sapling`
Branch: `refactor/4-syllabus-unification` (already checked out)

## Context already in place

- Sub-agent A: `syllabus_to_wire_dict` adapter shipped + tested.
- Sub-agent B: `services/calendar_service.py::extract_assignments_from_file`
  now agent-first with legacy fallback. New tests in `test_ocr_pipeline.py`
  cover both paths.

## Why

Refactor #1 already migrated `routes/documents.py::upload_document` to
the agent path; that's not what this PR touches. The remaining consumer
of `extract_assignments_from_file` is `routes/calendar.py` (the
import-extract endpoint) and the integration tests in
`tests/test_ocr_pipeline.py`.

The promise of refactor #4 is "wire format unchanged." Verify it by
reading the consumer, running the suite, and adding a regression test
that pins the contract.

## What to read first

- `backend/routes/calendar.py` — entire file. The `extract_assignments_from_file`
  call is around line 99 (an `/import-extract`-style route). Note:
  - Every key the route reads off the result dict (`assignments`,
    `warnings`, `raw_text`, etc.).
  - Whether the route surfaces `course_title` or `grading_categories`
    to the user, or just discards them.
  - Whether the route does a strict shape check (e.g. `if set(result.keys()) == {...}`)
    or a forgiving one (`result.get("assignments", [])`).
- `backend/services/calendar_service.py` — read the post-Sub-agent-B
  state. Confirm `extract_assignments_from_file` returns the legacy
  shape on both the agent and legacy paths.
- `backend/tests/test_ocr_pipeline.py` — Sub-agent B added the new
  agent-path tests here. Re-read the test signatures for any gaps.
- `backend/tests/test_documents_routes.py` — exercises `routes/documents.py`'s
  agentic path which already uses the agent. If anything here breaks,
  it's a regression Sub-agent B introduced via the adapter; flag it.

## What to verify

### 1. Consumer-key audit

For every consumer of `extract_assignments_from_file` and every consumer
of the dict it returns, list the keys that consumer reads. Compare
against the adapter's output shape. Any consumer that reads a key the
adapter doesn't produce is a real break. Fix it by:

- **Adding the missing key to the adapter** if it's a legitimate
  field the agent can produce (loop back to Sub-agent A; this is rare).
- **Updating the consumer to default the key** if the field is now
  absent on the agent path but the consumer should still work
  (e.g. `result.get("warnings", [])`).

Document the audit in your report (one line per consumer).

### 2. Add a regression test in `tests/test_calendar_routes.py`

If the file doesn't exist, create it. Test names like:

- `test_import_extract_returns_assignments_from_agent` — mock
  `extract_assignments_from_file` to return the new agent-path dict
  shape (with `course_title`, `grading_categories` extras), POST to
  `/api/calendar/import-extract` (or whatever the actual route path
  is), assert the route's response has the expected keys.
- `test_import_extract_handles_legacy_path_dict` — same but with the
  legacy path's smaller dict (no `course_title` / `grading_categories`).
  Confirms backward compat: the route works whether the agent fired
  or fell back.
- `test_import_extract_warnings_passthrough` — assert `warnings` from
  either path makes it to the response.

Use the `MagicMock` factory pattern from `test_quiz_routes.py`. Mock
`services.calendar_service.extract_assignments_from_file` (or the
imported reference inside `routes/calendar.py`).

### 3. Wire-format invariant test

Add to `tests/test_ocr_pipeline.py`:

```python
def test_agent_and_legacy_paths_share_required_keys():
    """The agent path's wire format must be a SUPERSET of the legacy path.
    Any consumer that worked under the legacy `{assignments, warnings,
    raw_text}` keys MUST work under the agent path too. Extra keys
    (`course_title`, `grading_categories`) are additive — they're new
    fields, not replacements.
    """
    LEGACY_REQUIRED = {"assignments", "warnings", "raw_text"}
    # Mock the agent path to return a known SyllabusAssignments
    # ... (assert LEGACY_REQUIRED.issubset(set(result.keys())))
```

This pins the wire-format contract so future refactors can't drop a
key and break consumers silently.

## Verify

```bash
cd "/Users/josegaelcruzlopez/Documents/Startup_Projects /Sapling/backend"
python -m pytest tests/test_calendar_routes.py tests/test_ocr_pipeline.py tests/test_documents_routes.py tests/test_syllabus_adapter.py -q --no-header
python -m pytest tests/ -q --no-header --ignore=tests/evals
```

Baseline: ~578+ pass, 3 pre-existing live-Supabase failures, no other
red. After your additions: count up.

## Constraints

- DO NOT modify `services/calendar_service.py`, the adapter, or the
  agent (sub-agents A and B). Verification only.
- DO NOT modify `tests/evals/syllabus_extraction.py` (sub-agent D).
- DO NOT delete legacy code. Sub-agent E.
- DO NOT commit. No ADRs.
- If the consumer audit turns up a real break (a route that reads a
  key the new adapter doesn't produce), DO NOT silently paper over it
  by mutating the route — flag it loudly so we can decide whether to
  loop back to Sub-agent A's adapter or update the consumer.

## Report

- Consumer-by-consumer audit table:
  - File:line of consumer
  - Keys it reads
  - Pass / Fail under the new adapter shape
- Number of new tests added (where they live).
- Pytest summary line.
- Any consumer that needed updating, with rationale.

Aim for under 200 words.
