# Sub-agent E — Cleanup PR (separate, after main is stable)

DO NOT run this sub-agent as part of the refactor #4 PR. It belongs
to a separate, smaller cleanup PR that ships **after the agent path
has been on `main` for ~1 week and proves stable in production**.
Same pattern as the planned `services/gemini_service.py` deletion PR
(see ADR 0015's "consequences" section).

Repo: `/Users/josegaelcruzlopez/Documents/Startup_Projects /Sapling`
Branch: `chore/4-cleanup-syllabus-legacy` (new)

## Pre-flight checklist

Before dispatching this sub-agent, confirm ALL of these:

1. The refactor #4 PR has merged to `main`.
2. At least one production rollout has happened on the agent path,
   and Logfire shows no recurring exceptions on
   `agent="syllabus_extraction"` spans.
3. The legacy fallback path's exception count in Logfire is "low"
   (define low however the team likes — the proxy is "we're not
   leaning on it"). If the legacy path is firing more than ~1% of
   syllabus uploads, fix the agent before deleting the legacy.
4. `assignment_type="other"` defaulting is acceptable to the team
   (or the schema was extended in refactor #4 to carry the type).
5. No open PRs touch `services/calendar_service.py::parse_syllabus`
   or `prompts/syllabus_extraction.txt`.

If any of those is false, do NOT run this sub-agent yet.

## Why

ADR 0001 set the deletion contract: legacy fallback stays alive
during migration, then gets removed in a separate small PR after
the agent path proves stable. Refactor #2 left
`gemini_service.call_gemini_json` alive for the same reason; refactor
#3 left `gemini_service.call_gemini_multiturn` alive; this PR
follows the same playbook for the syllabus prompt.

## What to delete

### 1. Legacy syllabus parsing in `backend/services/calendar_service.py`

- `parse_syllabus(extracted_text)` — the `call_gemini_json` wrapper.
- `extract_assignments_from_file`'s legacy fallback branch (the
  `try/except → parse_syllabus` block added by Sub-agent B). Replace
  with a direct agent call; on agent failure, raise `HTTPException`
  or propagate the exception. The fallback was a migration safety net
  — once the agent is proven, we don't need it.
- `process_and_save_syllabus` — only called from `tests/test_ocr_pipeline.py`,
  which itself uses live Supabase and is currently in the pre-existing
  failures list. Either delete the function entirely (and the tests
  that depend on it) OR convert the function to a thin wrapper around
  the agent path. Pick whichever leaves the smallest API surface.

### 2. Legacy prompt file

- `backend/prompts/syllabus_extraction.txt` — only used by `parse_syllabus`.
  Delete after the function is gone.

### 3. Imports + tests

- `backend/services/calendar_service.py` — drop the `from services.gemini_service import call_gemini_json`
  import and the `PROMPT_PATH` constant.
- `backend/tests/test_ocr_pipeline.py` — drop or rewrite the tests that
  exercised `parse_syllabus` or `process_and_save_syllabus` directly.
  The agent-path tests (added by Sub-agent B) remain.
- `backend/routes/calendar.py` — verify imports of
  `extract_assignments_from_file` still resolve. They should — the
  function name is unchanged.

### 4. Watch for `call_gemini_json` callers

After this PR, `services/gemini_service.py::call_gemini_json` has
exactly one remaining caller: the quiz fallback (`routes/quiz.py::_legacy_generate_quiz`).
Don't delete `call_gemini_json` itself in this PR — that belongs to
the eventual `gemini_service.py` deletion PR (after BOTH the chat
and quiz fallbacks are removed too).

## Verify

```bash
cd "/Users/josegaelcruzlopez/Documents/Startup_Projects /Sapling/backend"
python -m pytest tests/ -q --no-header --ignore=tests/evals
grep -rn "parse_syllabus\|process_and_save_syllabus\|prompts/syllabus_extraction.txt" backend/ --include="*.py" --include="*.txt"
```

The pytest run should still report ~578 passing (same baseline as
PR #78), with 3 pre-existing live-Supabase failures unchanged. The
`grep` should return nothing — every reference to the deleted
symbols should be gone.

## ADR addendum

After this PR merges, add an addendum to
`docs/decisions/0016-refactor-4-syllabus-unification-shipped.md`:

```markdown
## Addendum (cleanup PR shipped <YYYY-MM-DD>)

The legacy `parse_syllabus` path and `prompts/syllabus_extraction.txt`
were deleted on <date>, after ~<N> days on `main` with no agent-path
incidents in Logfire. `services/gemini_service.py::call_gemini_json`
remains alive only as the quiz fallback target (refactor #2 contract);
the eventual `gemini_service.py` deletion PR removes it after the
quiz fallback is also retired.
```

## Constraints

- DO NOT delete `services/gemini_service.py` itself — quiz fallback
  still depends on it.
- DO NOT delete `routes/calendar.py` — only imports change.
- DO NOT bundle this with the refactor #4 main PR. Separate, small,
  reviewable.
- DO NOT delete the agent or its eval set.

## Report

- Files deleted (with line counts before deletion).
- Lines removed from `services/calendar_service.py`.
- Pytest summary line.
- Output of the `grep` verification.
- Confirmation that `call_gemini_json` is now down to 1 caller
  (the quiz fallback).

Aim for under 150 words.
