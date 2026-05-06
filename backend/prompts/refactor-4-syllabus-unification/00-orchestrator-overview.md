# Refactor #4 — Syllabus extraction unification: orchestration plan

This folder contains the prompts for unifying the duplicated syllabus
parsing in `backend/services/calendar_service.py` onto the existing
`backend/agents/syllabus_extraction.py::syllabus_extraction_agent`,
per ADR 0001's migration plan and ADR 0005's prioritization (the
last refactor named in the plan).

## Sequencing

```
Phase 1 (parallel):
  Sub-agent A   → backend/agents/tools/syllabus_adapter.py (new)
                 OR helper inline in agents/syllabus_extraction.py
  Sub-agent D   → backend/tests/evals/syllabus_extraction.py (extend)

Phase 2 (sequential):
  Sub-agent B   → backend/services/calendar_service.py refactor +
                  backend/tests/test_ocr_pipeline.py updates

Phase 3 (sequential):
  Sub-agent C   → routes/calendar.py + routes/documents.py verification
                  (no behavior change expected; pin with a test)

Phase 4 (separate PR, after this PR is on main and stable for ~1 week):
  Sub-agent E   → delete legacy parse_syllabus, the prompt file, and
                  any shim wrappers that became no-ops.
```

## Branch + ADR

Before dispatching, create a fresh branch off `main`:
```bash
git fetch origin
git checkout -b refactor/4-syllabus-unification origin/main
```

After Phase 3 lands, write `docs/decisions/0016-refactor-4-syllabus-unification-shipped.md`
using the template in `06-adr-template.md`.

NOTE on numbering: ADR 0014 is `adaptive-quiz-iteration` (PR #77),
ADR 0015 is `refactor-3-chat-tutor-shipped` (PR #78). The next
available slot is **0016**. If anything else lands first, number at
write time against the current state of `docs/decisions/`.

## What this refactor delivers

- One canonical syllabus-extraction path (`syllabus_extraction_agent`),
  used by both `routes/documents.py::upload_document` (already wired
  in refactor #1) and `services/calendar_service.py::extract_assignments_from_file`
  (the migration this PR delivers).
- The legacy `call_gemini_json` + `prompts/syllabus_extraction.txt` path
  remains as the fallback target per ADR 0001's contract — Sub-agent E
  deletes it in a separate small PR after the agent path proves stable.
- One fewer caller of `services/gemini_service.py` (down from three to
  two: chat fallback + quiz fallback). Closer to the eventual deletion
  of `gemini_service.py` itself.

## Constraints (apply to every sub-agent)

- **Wire format unchanged.** `routes/calendar.py` reads
  `{"assignments": [{title, due_date, assignment_type, notes, course_id}], "warnings": [...], "raw_text": ...}`
  from `extract_assignments_from_file`. The adapter must produce
  exactly that shape; if a field is genuinely not in the agent's
  schema (`assignment_type` is the only one to watch), the adapter
  fills a sensible default (`"other"`) rather than dropping the field.
- **Legacy fallback per ADR 0001.** Refactor `extract_assignments_from_file`
  to try the agent first; on `UsageLimitExceeded` /
  `UnexpectedModelBehavior` / generic `Exception`, fall back to the
  legacy `parse_syllabus` path. Pin this with a test like the ones in
  `routes/quiz.py` and `routes/learn.py`.
- **Don't delete `parse_syllabus` in this PR.** It stays as the
  fallback target. Sub-agent E's cleanup PR removes it after main is
  stable. Same pattern as refactor #2 (PR #71) and #3 (PR #78).
- **Don't change `prompts/syllabus_extraction.txt` in this PR.** It's
  the legacy fallback's prompt source. Sub-agent E deletes it.
- **Don't touch the agent's system prompt or schema unless Sub-agent A
  finds a wire-format gap that genuinely cannot be papered over by the
  adapter.** Bumping `_PROMPT_HASH` invalidates eval cassettes; only
  do it if there's no alternative.
- **`routes/documents.py` already uses the agent.** Don't refactor it
  again — the relevant change there happened in refactor #1
  (`_save_orchestrator_syllabus` at line 431). Touching it would
  conflict with the eval set's recorded behavior.
- **`save_assignments_to_db`, `insert_new_assignments`,
  `load_existing_assignment_keys`, `assignment_dedupe_key`** are pure
  DB / dedup helpers (no LLM). They stay exactly as they are. The
  refactor does not touch the dedup boundary.
- **Encryption boundary preserved.** No `messages.content` /
  `documents.summary` reads happen in this code path; nothing to
  decrypt. Just don't introduce new reads of encrypted columns
  without `decrypt_if_present` at the boundary.

## What's already in place from prior refactors

- `backend/agents/syllabus_extraction.py` — `syllabus_extraction_agent`
  with `SyllabusAssignments` output (course_title, instructor,
  assignments, grading_categories). Uses `PromptedOutput` because
  Gemini's structured-output API rejects the schema (date format on
  `due_date` plus nested assignment list — see the docstring).
  Default model is `model_for("syllabus")` from `agents/_providers.py`.
- `backend/agents/_providers.py` — `syllabus` task slot already exists.
  No additions needed.
- `backend/tests/evals/syllabus_extraction.py` — eval set already
  exists with a recorded cassette. Sub-agent D extends it; do not
  rewrite it.
- `agents/deps.py::SaplingDeps` — same shape, threads through.
- Tool wrapper pattern, eval replay infra, Logfire scrubber + prompt
  versioning — all reusable.
- The `_extract_via_agent` / `_legacy_extract` orchestrator-vs-legacy
  fallback pattern from PR #71 (`routes/quiz.py`) and PR #78
  (`routes/learn.py`) is the template.

## Read before dispatching

- `docs/decisions/0001-adopt-pydantic-ai.md` — fallback contract.
- `docs/decisions/0005-refactor-2-quiz-generation.md` — explicitly
  defers syllabus unification to refactor #4.
- `docs/decisions/0013-refactor-2-quiz-shipped.md` — the addenda
  capture every gotcha that hit during refactor #2; expect similar
  shape (fallback symmetry, model-pref alignment if applicable here).
- `docs/decisions/0015-refactor-3-chat-tutor-shipped.md` — the most
  recent comparable refactor. The "what surprised us" section's
  scope-split lesson applies here too: keep this PR small.
- `backend/services/calendar_service.py` — current legacy path.
  All 89 lines.
- `backend/agents/syllabus_extraction.py` — current agent. All 90 lines.
- `backend/routes/calendar.py` — the route that consumes
  `extract_assignments_from_file`. Around line 22 + line 122.
- `backend/tests/test_ocr_pipeline.py` — exercises the legacy path
  today. The 3 pre-existing live-Supabase failures
  (`test_skips_self_edges`, `test_save_to_db`, `test_full_pipeline`)
  are unrelated to this refactor; don't try to fix them.

## Estimated effort

Roughly **half a day** of focused work, modeled on PR #78's iteration
cadence. The agent already exists; the work is plumbing + adapter +
tests + ADR. Smaller than #2 or #3.
