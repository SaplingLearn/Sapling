# 0016: Refactor #4 (syllabus unification) shipped

- Status: accepted
- Date: 2026-05-04
- Supersedes: refines 0001 (the migration plan), 0005 (refactor sequencing)

## Context

ADR 0001 picked Pydantic AI as the agent framework. ADR 0005 named
syllabus extraction unification as refactor #4 and called it
"low-effort cleanup that fits anywhere." With refactors #1 (PR #67),
#2 (PR #71), #2-iteration (PR #77), and #3 (PR #78) on `main`, this
PR closes out the four-refactor migration plan from ADR 0001.

This refactor is smaller than #2 or #3: the agent
(`backend/agents/syllabus_extraction.py::syllabus_extraction_agent`)
already shipped with refactor #1 and is used by `routes/documents.py`'s
agentic upload path. What remained was the **second consumer** —
`services/calendar_service.py::parse_syllabus` — still calling
`call_gemini_json` against `prompts/syllabus_extraction.txt`. Refactor
#4 migrates that consumer onto the typed agent.

## Decision

`services/calendar_service.py::extract_assignments_from_file` now runs
the agent first and falls back to the legacy `parse_syllabus` path on
`UsageLimitExceeded` / `UnexpectedModelBehavior` / generic `Exception`,
matching the orchestrator-vs-legacy fallback contract from ADR 0001 and
the patterns established by PR #67 (documents), PR #71 (quiz), and
PR #78 (chat). The wire format is unchanged: the new
`syllabus_to_wire_dict` adapter maps the agent's `SyllabusAssignments`
output to the legacy `{"assignments", "warnings", "raw_text"}` dict
shape with two additive keys (`course_title`, `grading_categories`)
that consumers ignore today.

Prompt version: `97946a2b84b2` — **unchanged** from refactor #1. The
adapter defaults `assignment_type="other"` rather than extending the
schema, which would have invalidated the recorded eval cassette. The
existing 15 eval cases continue to apply; three new evaluators
(`WireFormatRequiredKeysEvaluator`, `AssignmentTypeNonNullEvaluator`,
`DueDateIsoStringEvaluator`) run on the same cassettes to pin the
adapter's wire-format contract.

## What shipped

- **`backend/agents/tools/syllabus_adapter.py`** (61 lines, new) —
  `syllabus_to_wire_dict(SyllabusAssignments) -> dict` adapter. Maps
  the agent's `date | None` to ISO-8601 strings, defaults
  `assignment_type="other"`, passes `course_title` and
  `grading_categories` through as additive keys.
- **`backend/services/calendar_service.py`** (+87 / −7) —
  `_extract_via_agent` (new), `parse_syllabus` (preserved as legacy
  fallback per ADR 0001), `extract_assignments_from_file` rewritten
  to dispatch agent-first with fallback. `save_assignments_to_db`,
  `insert_new_assignments`, `load_existing_assignment_keys`,
  `assignment_dedupe_key` untouched (pure dedup helpers, no LLM).
- **`backend/tests/test_syllabus_adapter.py`** (146 lines, new) —
  10 adapter unit tests. Pins the legacy-shape contract, the
  `"other"` default, ISO-8601 date serialization, mutable-default
  isolation, and `assignment_dedupe_key` integration.
- **`backend/tests/test_ocr_pipeline.py`** (+183 / −1) —
  `TestExtractAssignmentsViaAgent` class with 4 tests covering
  agent-success, all three fallback triggers, and the
  empty-text short-circuit. Plus
  `test_agent_and_legacy_paths_share_required_keys` pinning the
  superset-invariant.
- **`backend/tests/test_calendar_routes.py`** (+1 class, 3 tests) —
  `TestImportExtractWireFormat` regression tests confirming
  `routes/calendar.py::extract` tolerates both the new agent-path dict
  shape and the legacy dict shape.
- **`backend/tests/evals/syllabus_extraction.py`** (+~75 lines) —
  three new evaluators wired into `make_dataset()`:
  - `WireFormatRequiredKeysEvaluator` — pins
    `{assignments, warnings, raw_text}` keys.
  - `AssignmentTypeNonNullEvaluator` — pins the adapter's
    `"other"` default.
  - `DueDateIsoStringEvaluator` — pins ISO-8601 string serialization.
  No new cases (the existing 15 cassettes already cover the agent's
  behavior).
- **`backend/prompts/refactor-4-syllabus-unification/`** — the
  sub-agent playbook (8 files) used to dispatch this refactor.
  Committed as a planning artifact for future refactor archeology.

## What surprised us

1. **Sub-agent C wasn't strictly needed for the wire-format audit —
   Sub-agent B already did it.** B's report listed every consumer of
   `extract_assignments_from_file` with their key-access patterns and
   pre-confirmed no breaks. We dispatched C anyway because the *test*
   it adds (`TestImportExtractWireFormat` + the
   `test_agent_and_legacy_paths_share_required_keys` invariant) is
   the regression sentinel for future refactors. **Carry forward**:
   Sub-agent B's audit might be a generalizable phase-2 expectation
   ("audit consumers when refactoring shared helpers") and the
   verification phase becomes test-only rather than re-audit.

2. **No `_PROMPT_HASH` change. No cassette re-record.** Refactor #4
   was the first migration that didn't move the schema or prompt at
   all — the adapter handled the contract translation entirely.
   This is the "lowest-effort" half of "low-effort cleanup that fits
   anywhere" from ADR 0005's framing. **Carry forward**: when the
   agent already exists from a prior refactor, the second-consumer
   migration is essentially adapter + fallback + tests. ~2 hours
   if the playbook is good.

3. **`process_and_save_syllabus` is still not wired to a route.**
   Architecture.md flagged it as "exists for direct OCR→Gemini→DB
   use but is not currently wired." Confirmed during the audit:
   only `tests/test_ocr_pipeline.py` calls it (and those are the
   pre-existing live-Supabase failures). Considered deleting it in
   this PR; deferred to Sub-agent E's cleanup PR per ADR 0001's
   deletion contract.

4. **The wire-format adapter pattern is now visible across all four
   refactors.** Documents had `_save_orchestrator_syllabus`'s inline
   conversion (refactor #1); quiz had `_agent_question_to_wire`
   (refactor #2); chat had `_load_message_history`'s `ModelMessage`
   conversion (refactor #3); syllabus has `syllabus_to_wire_dict`
   (refactor #4). They're all "agent typed output → legacy dict
   shape." The pattern is consistent enough that CLAUDE.md probably
   deserves an entry: "every agent migration ships with a wire-format
   adapter at `agents/tools/<domain>_adapter.py`."

5. **`extract_assignments_from_file` stays sync with internal
   `asyncio.run`.** The route caller in `routes/calendar.py::extract`
   is sync and stays sync. `asyncio.run` inside a request thread is
   safe (we're not inside an event loop). TODO comment flags the
   future async-ification. Same trade-off PR #67 made for the
   document upload path.

## Consequences

- **(+) Single canonical syllabus-extraction path.** Both
  `routes/documents.py`'s agentic upload AND
  `routes/calendar.py`'s import-extract endpoint route through
  `syllabus_extraction_agent`. Logfire spans share the
  `agent="syllabus_extraction"` tag across both consumers.
- **(+) One fewer caller of
  `services/gemini_service.py::call_gemini_json`.** Down from three
  (chat-tutor fallback in PR #78, quiz fallback, syllabus parsing) to
  two. Closer to the eventual `gemini_service.py` deletion.
- **(+) Wire-format-required-keys eval pins the consumer contract
  structurally.** Future refactors that drop `warnings` or
  `assignments` fail loudly in CI.
- **(+) The migration plan from ADR 0001 is COMPLETE.** All four
  named refactors are on `main` (after this PR merges). Remaining
  work is the cleanup PR series: gemini_service deletion,
  start_session/action migration on chat, the legacy parse_syllabus
  removal here.
- **(−) `extract_assignments_from_file` runs `asyncio.run` inside a
  sync function.** Acceptable for now; flagged as a future
  async-ification when the route itself becomes async.
- **(−) `assignment_type` defaults to `"other"`** for syllabus-imported
  assignments until a future iteration extends the agent schema.
  UI bucketing is degraded but not broken — `routes/calendar.py`
  already accepts `"other"` as the canonical default.
- **(=) Eval cassettes are unchanged.** The agent's prompt didn't
  move, so no re-recording is needed. The three new evaluators run
  on the existing recorded cassettes.

## What I'd carry into the next refactor (or follow-ups)

- **Wire-format adapter is the recurring shape.** Document this in
  CLAUDE.md so future agent migrations don't reinvent it. The five
  shipped examples (`_save_orchestrator_syllabus`,
  `_agent_question_to_wire`, `_load_message_history`,
  `syllabus_to_wire_dict`) all live in or near the agent module —
  the convention is `agents/tools/<domain>_adapter.py` or inline in
  the agent file when small enough.
- **The "is the agent already done?" pre-flight check** that helped
  refactor #3 (PR #78) skip Phase 1 also helped here: the agent
  module existed from refactor #1, so phase A was just the *adapter*,
  not the *agent*. Future refactor playbooks should default to
  splitting "agent" and "adapter" into separate sub-agents.
- **Cleanup PRs are queued.** Three small PRs separate from
  refactor #4 itself:
  1. Sub-agent E's cleanup (delete `parse_syllabus`,
     `prompts/syllabus_extraction.txt`, the legacy fallback branch).
     ~½ day, after this PR is on `main` for ~1 week.
  2. PR #78's `start_session` / `action` follow-up (chat tutor's
     remaining unmigrated routes).
  3. Final `services/gemini_service.py` deletion once 1+2 above plus
     the quiz fallback retire complete. One-line cleanup PR.

## Pre-existing test failures (not caused by this refactor)

Backend baseline carries the same three failures as PR #67/#71/#78:

- `test_skips_self_edges` — `graph_service` test hitting live Supabase
  with a 409 conflict.
- `test_save_to_db` — OCR pipeline hitting live Supabase.
- `test_full_pipeline` — same OCR pipeline path.

**596 tests pass on this branch**; 3 fail (the same three above,
unchanged); no regressions caused by the refactor.

## Migration plan complete

This PR is the **LAST named refactor** in ADR 0001's migration plan
(refactors #1-#4). All four agentic conversions are on `main` after
this PR merges. The remaining migration cleanup is the eventual
deletion of `services/gemini_service.py` itself, gated on:

- Refactor #2's quiz fallback being retired (separate small PR).
- Refactor #3's chat fallback being retired (separate small PR;
  also depends on `start_session`/`action` getting migrated, which
  PR #78 explicitly deferred to a follow-up).
- Refactor #4's syllabus fallback being retired (this PR's Sub-agent
  E cleanup).

After all three of those land, `services/gemini_service.py` has zero
callers and can be deleted in a one-line cleanup PR. That closes out
the agentification work entirely.

## Rollback

The legacy path is intact. Single revert of the merge commit drops
the adapter, removes `_extract_via_agent`, reverts
`extract_assignments_from_file` to its pre-refactor body, and the
prompt + agent are unchanged on the documents-upload side (refactor
#1 already shipped them; this PR didn't touch the agent).
