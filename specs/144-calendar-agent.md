# Spec: Calendar assignment extraction → agent (#144)

## Context

Part of the Agent-migration epic (#152), milestone #2. `backend/services/calendar_service.py`
already extracts syllabus assignments primarily through `syllabus_extraction_agent`
(`_extract_via_agent`). The remaining raw-Gemini seam is the **legacy fallback** `parse_syllabus`
(`calendar_service.py:80`, `call_gemini_json`), which `extract_assignments_from_file` degrades to when
the agent trips guardrails (`UsageLimitExceeded`/`UnexpectedModelBehavior`) or raises unexpectedly.

`parse_syllabus` is referenced across `tests/test_ocr_pipeline.py` (live-gated tests + mocked
fallback tests). `notes` is already encrypted at the write boundary in `insert_new_assignments`
(`calendar_service.py:61`, `encrypt_if_present`) per #126.

## Goal

Make `syllabus_extraction_agent` the sole extraction mechanism in `calendar_service`: remove the
`call_gemini_json` legacy fallback entirely, degrading gracefully (no second LLM call) when the agent
fails, without regressing the response contract or the `notes` encryption.

## Requirements

### R1 — Remove the raw-Gemini seam from `calendar_service`
- Delete the `parse_syllabus` function and the `from services.gemini_service import call_gemini_json`
  import. Remove the now-unused `PROMPT_PATH` module constant (only `parse_syllabus` used it).
- `grep -n "call_gemini" backend/services/calendar_service.py` returns no matches.

### R2 — Graceful degrade on agent failure (no second LLM call)
- In `extract_assignments_from_file`, the two failure branches (`UsageLimitExceeded`/
  `UnexpectedModelBehavior`, and bare `Exception`) no longer call `parse_syllabus`. Instead they log
  (as today) and return a degrade result:
  `{"assignments": [], "warnings": [<one clear user-facing message>], "raw_text": text,
    "course_title": None, "grading_categories": []}`.
- The happy path (agent succeeds) is unchanged: returns `syllabus_to_wire_dict(result.output, raw_text=text)`.
- The empty-text shortcut (no extractable text) is unchanged.

### R3 — Preserve the response contract
- `extract_assignments_from_file` still returns a dict containing at least the legacy-required keys
  `{"assignments", "warnings", "raw_text"}` on every path (success, degrade, empty-text). Downstream
  consumers (`routes/calendar.py::extract`, `process_and_save_syllabus`) keep working unchanged.

### R4 — Preserve `notes` encryption at write (#126)
- `insert_new_assignments` continues to write `notes` via `encrypt_if_present` — no plaintext `notes`
  reintroduced. (No functional change expected; this is a guard.)

### R5 — Tests
- Update `tests/test_ocr_pipeline.py`:
  - Remove `parse_syllabus`-dependent legacy paths: drop `test_gemini_parse` and repoint the
    `parsed_assignments` fixture + the `__main__` block off `parse_syllabus` (use the agent path or
    remove), since the function no longer exists.
  - Rewrite the two `test_falls_back_to_legacy_*` tests to assert the **graceful degrade**: on agent
    `UsageLimitExceeded` and on a bare `Exception`, the result has `assignments == []`, a non-empty
    `warnings`, `raw_text == <text>`, and `parse_syllabus` is never referenced.
  - `test_returns_agent_assignments` and `test_agent_and_legacy_paths_share_required_keys`: drop the
    `patch.object(calendar_service, "parse_syllabus", ...)`; keep the agent-path and required-keys
    assertions (the required-keys check now covers success + degrade paths).
  - `test_legacy_path_still_works_when_text_empty`: drop the `parse_syllabus` patch; keep the
    empty-text-shortcut assertions.
- Add a regression test that `insert_new_assignments` encrypts `notes` at write (asserts the inserted
  row's `notes` is the `encrypt_if_present` output, not plaintext) — locks in R4 / #126.
- All agent runs are mocked (`AsyncMock`); no live Gemini/Supabase in the default run, consistent with
  the existing `TestExtractAssignmentsViaAgent` mocking and `_requires_gemini` gating.

## Acceptance criteria (verifiable)
1. `grep -rn "call_gemini\|parse_syllabus\|PROMPT_PATH" backend/services/calendar_service.py` → no matches.
2. No test in `tests/test_ocr_pipeline.py` references `parse_syllabus`.
3. `extract_assignments_from_file` returns `{assignments, warnings, raw_text}` (superset ok) on all
   three paths — success, agent-failure degrade, empty-text — verified by tests.
4. Agent-failure degrade returns `assignments == []` + a warning + `raw_text`, with no second LLM call.
5. `insert_new_assignments` encrypts `notes` at write (regression test passes).
6. `python -m pytest tests/test_ocr_pipeline.py tests/test_calendar_routes.py -q` passes; the broader
   `python -m pytest tests/ -q` shows no new failures vs. `main`.
7. `ruff check .` passes for changed files.

## Out of scope
- Other `gemini_service` call sites (quiz #145, flashcards #146, documents, course_context).
- The `syllabus_extraction_agent` itself (unchanged), and `prompts/syllabus_extraction.txt`
  (may remain on disk; just no longer read by `calendar_service`).
- Deleting `services/gemini_service.py` (#151 final cutover).
