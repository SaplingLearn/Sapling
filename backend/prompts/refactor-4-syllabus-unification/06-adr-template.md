# 0016 — Template for ADR after refactor #4 ships

After sub-agents A-D land on `main`, write
`docs/decisions/0016-refactor-4-syllabus-unification-shipped.md` using
this skeleton. Mirror the shape of `docs/decisions/0015-refactor-3-chat-tutor-shipped.md`
(what shipped, what surprised us, consequences, what to carry forward).

```markdown
# 0016: Refactor #4 (syllabus unification) shipped

- Status: accepted
- Date: <YYYY-MM-DD>
- Supersedes: refines 0001 (the migration plan), 0005 (refactor sequencing)

## Context

ADR 0001 picked Pydantic AI as the agent framework. ADR 0005 named
syllabus extraction unification as refactor #4 and called it
"low-effort cleanup that fits anywhere." With refactors #1-#3 on
`main`, the four-refactor migration plan is now complete with this PR.

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

Prompt version: <fill in `_PROMPT_HASH` from `agents/syllabus_extraction.py`
— unchanged from refactor #1 unless Sub-agent A added `assignment_type`
to the schema, in which case bump and re-record the cassette>.

## What shipped

- `backend/agents/tools/syllabus_adapter.py` (or inline in
  `agents/syllabus_extraction.py`) — `syllabus_to_wire_dict(SyllabusAssignments)`
  adapter. Maps `date | None` → ISO-8601 string, defaults
  `assignment_type="other"`, passes `course_title` and
  `grading_categories` through.
- `backend/services/calendar_service.py` — `_extract_via_agent` (new),
  `parse_syllabus` (preserved as legacy fallback per ADR 0001),
  `extract_assignments_from_file` rewritten to dispatch agent-first
  with fallback. `save_assignments_to_db`, `insert_new_assignments`,
  `load_existing_assignment_keys` untouched (pure dedup helpers, no LLM).
- `backend/tests/test_syllabus_adapter.py` (new) — adapter unit tests.
- `backend/tests/test_ocr_pipeline.py` — extended with
  `TestExtractAssignmentsViaAgent` covering the new agent path and
  all three fallback triggers.
- `backend/tests/test_calendar_routes.py` — added regression tests
  pinning the `routes/calendar.py` consumer's expected wire format.
- `backend/tests/evals/syllabus_extraction.py` — extended with
  `WireFormatRequiredKeysEvaluator`, `AssignmentTypeNonNullEvaluator`,
  and `DueDateIsoStringEvaluator` to pin the adapter's contract
  structurally. No new cases (existing recorded cassettes cover the
  agent's behavior).

## What surprised us

<Fill in during/after the refactor — typical categories:>

- **`assignment_type` was missing from the agent schema**. The legacy
  prompt extracted it explicitly; the agent's Pydantic model didn't.
  Decided to default to `"other"` in the adapter rather than bump
  `_PROMPT_HASH` (which would invalidate the existing cassette). UX
  impact: assignments imported from a syllabus all get bucketed as
  "Other" until a follow-up adds the field. <Adjust based on actual
  decision>.

- **`extract_assignments_from_file` is sync**. Wrapping
  `agent.run` in `asyncio.run` inside a sync function is acceptable
  here (called from a request thread, not an event loop). Future
  refactors should consider making the route async; until then, the
  pattern is documented inline. <Adjust if you split into sync + async
  pair>.

- **`process_and_save_syllabus` is not wired to a route**. Architecture
  doc flags it as "exists for direct OCR→Gemini→DB use but not currently
  wired" — the only callers are the live-Supabase tests in
  `test_ocr_pipeline.py`. Considered deleting it in this PR; deferred
  to Sub-agent E's cleanup PR per ADR 0001's deletion contract.

- **Wire-format additive keys**. `course_title` and
  `grading_categories` are new keys the agent produces. The legacy
  path didn't carry them. Verified consumers tolerate the additions
  via Sub-agent C's audit; both keys flow through as ignored extras
  on consumers that read `.get("assignments", [])` only.

- <Add anything else you actually hit. The "every refactor surprises
  us with one wire-format gotcha" pattern from #2 / #3 should appear
  here too.>

## Consequences

- (+) Single canonical syllabus-extraction path. Both `routes/documents.py`'s
  agentic upload AND `routes/calendar.py`'s import-extract endpoint
  now route through `syllabus_extraction_agent`. Logfire spans share
  the `agent="syllabus_extraction"` tag across both consumers.
- (+) One fewer caller of `services/gemini_service.py::call_gemini_json`.
  Down from three (chat-tutor fallback in the now-merged PR #78,
  quiz fallback, syllabus parsing) to two. Closer to the eventual
  `gemini_service.py` deletion.
- (+) Wire-format-required-keys eval pins the consumer contract
  structurally. Future refactors that drop `warnings` or `assignments`
  fail loudly in CI.
- (−) `extract_assignments_from_file` runs an `asyncio.run` inside a
  sync function. Acceptable for now; flagged as a future async-ification.
- (−) `assignment_type` defaults to `"other"` for syllabus-imported
  assignments until a future iteration extends the agent schema.
  UI bucketing is degraded but not broken.
- (=) Eval cassettes are unchanged. The agent's prompt didn't move,
  so no re-recording is needed.

## What I'd carry into the next refactor (or follow-ups)

<Fill in based on actual experience. Likely items:>

- **The wire-format adapter is a recurring shape across all four
  refactors.** Documents had `_save_orchestrator_syllabus`'s inline
  conversion; quiz had `_agent_question_to_wire`; chat had
  `_load_message_history`'s `ModelMessage` conversion; syllabus has
  `syllabus_to_wire_dict`. They're all "agent typed output → legacy
  dict shape." A future refactor (or a CLAUDE.md convention update)
  should call this out as the standard pattern: typed agent → adapter
  module → wire format unchanged.

- **`assignment_type` schema gap is real**. A follow-up PR should add
  `assignment_type: Literal["homework", "exam", "project", "reading",
  "quiz", "other"]` to `SyllabusAssignment` and re-record the cassette.
  Sized as ~half-day; out of scope for this refactor.

- **Cleanup PR (Sub-agent E)** is queued: deletes `parse_syllabus`,
  `prompts/syllabus_extraction.txt`, the legacy fallback branch in
  `extract_assignments_from_file`, and `process_and_save_syllabus` if
  no consumers remain. Ships ~1 week after this PR is on `main`,
  matching the `gemini_service.py` deletion playbook.

## Pre-existing test failures (not caused by this refactor)

Backend baseline carries the same three failures as PR #67/#71/#78:

- `test_skips_self_edges` — `graph_service` test hitting live Supabase
  with a 409 conflict.
- `test_save_to_db` — OCR pipeline hitting live Supabase.
- `test_full_pipeline` — same OCR pipeline path.

<Total tests passing on this branch>; 3 fail; no regressions caused
by the refactor.

## Migration plan complete

This PR is the LAST named refactor in ADR 0001's migration plan
(refactors #1-#4). All four agentic conversions are on `main`. The
remaining migration cleanup is the eventual deletion of
`services/gemini_service.py` itself, gated on:

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
```
