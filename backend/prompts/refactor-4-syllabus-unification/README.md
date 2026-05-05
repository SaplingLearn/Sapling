# Refactor #4 — Syllabus extraction unification: prompt pack

Reusable sub-agent prompts for unifying the duplicated syllabus parsing
between `backend/services/calendar_service.py` (legacy `call_gemini_json`
+ `prompts/syllabus_extraction.txt`) and `backend/agents/syllabus_extraction.py`
(typed agent already used by `routes/documents.py`). Per ADR 0005's
sequencing, this is the **last named refactor** in the migration plan.

## Scope

This is a smaller, more contained refactor than #2 or #3. Most of the
work was already done by refactor #1 (the agent + its eval set already
exist and ship in production via `routes/documents.py`'s agentic upload).
What remains is the **second consumer**: `services/calendar_service.py`
and its callers in `routes/calendar.py` and `tests/test_ocr_pipeline.py`.

| Before | After |
|---|---|
| `calendar_service.py::parse_syllabus` calls `call_gemini_json` against `prompts/syllabus_extraction.txt`. Two duplicated parsing paths in the codebase. | `calendar_service.py` calls `syllabus_extraction_agent.run(...)` and adapts the output to the legacy dict wire format. One canonical extraction path. |
| `prompts/syllabus_extraction.txt` is the source of truth for the legacy prompt. | The system prompt on `syllabus_extraction_agent` is the single source of truth (already content-addressed via `_PROMPT_HASH`). |
| `routes/calendar.py` consumes `extract_assignments_from_file`'s legacy dict shape. | Same dict shape, now produced by the agent path with a legacy fallback per ADR 0001. |
| `services/gemini_service.py::call_gemini_json` has three callers (chat fallback, quiz fallback, syllabus). | Two (chat fallback, quiz fallback). Closer to the file's deletion. |

## Files

| File | Purpose |
|---|---|
| `00-orchestrator-overview.md` | Read first. Sequencing, branch setup, constraints, dependencies on prior refactors. |
| `01-sub-agent-A-adapter.md` | Build a wire-format adapter that maps `SyllabusAssignments` → the legacy `{"assignments", "warnings", "raw_text"}` dict. Verify the agent's schema covers every field the existing wire format carries. |
| `02-sub-agent-B-service.md` | Refactor `services/calendar_service.py::extract_assignments_from_file` agent-first with legacy fallback per ADR 0001. Update `test_ocr_pipeline.py` to cover both paths. |
| `03-sub-agent-C-routes.md` | Verify `routes/calendar.py` consumers see no wire-format change. Add a regression test if needed. |
| `04-sub-agent-D-evals.md` | Extend `tests/evals/syllabus_extraction.py` with adapter-shape evaluators. |
| `05-sub-agent-E-cleanup.md` | (Optional, separate PR after main is stable) Delete legacy `parse_syllabus`, `extract_assignments_from_file` shim, `prompts/syllabus_extraction.txt`. |
| `06-adr-template.md` | Skeleton for `docs/decisions/0016-refactor-4-syllabus-unification-shipped.md`. |

## How to dispatch

Phase 1 — run A + D in parallel (non-overlapping files):
- Spawn one `general-purpose` sub-agent per prompt.
- Wait for both to finish.

Phase 2 — run B alone (depends on A's adapter):
- Spawn one sub-agent with the prompt from `02-sub-agent-B-service.md`.

Phase 3 — run C alone (verifies B didn't break consumer wire format):
- Spawn one sub-agent with the prompt from `03-sub-agent-C-routes.md`.

Phase 4 — verify, ADR, commit, open PR.

Phase 5 (separate PR, ~1 week after main is stable) — sub-agent E for the
cleanup deletion.

## When this is done

The migration plan from ADR 0001 is complete. `services/gemini_service.py`
remains alive only as the chat + quiz fallback target — both of those
are dead code on the happy path after refactors #2 and #3, and a
follow-up small PR can delete `gemini_service.py` entirely once the
team is satisfied the agent paths are stable in production.
