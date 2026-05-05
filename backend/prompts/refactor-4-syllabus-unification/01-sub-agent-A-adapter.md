# Sub-agent A — Build the syllabus wire-format adapter

Build a small adapter that maps the agent's `SyllabusAssignments` output
to the legacy dict shape `services/calendar_service.py::extract_assignments_from_file`
returns today. WRITE the changes, run tests, report back.

Repo: `/Users/josegaelcruzlopez/Documents/Startup_Projects /Sapling`
Branch: `refactor/4-syllabus-unification` (already checked out)

## Why

`syllabus_extraction_agent` produces a typed `SyllabusAssignments` Pydantic
model:

```python
class SyllabusAssignments(BaseModel):
    course_title: str | None = ...
    instructor: str | None = ...
    assignments: list[SyllabusAssignment] = ...   # title, description, due_date, weight_pct
    grading_categories: list[GradingCategory] = ...
```

`services/calendar_service.py::extract_assignments_from_file` returns a
dict that callers (notably `routes/calendar.py`) consume. Before this
refactor the dict came from `call_gemini_json` with the legacy prompt;
after this refactor it must come from the agent's structured output but
preserve the same wire-format keys so consumers don't break.

Sub-agent B will use this adapter inside the new `_extract_via_agent`
helper; Sub-agent C verifies the consumer wire format is unchanged.

## What to read first

- `backend/agents/syllabus_extraction.py` — full file. Note the
  `SyllabusAssignment` shape: `title`, `description`, `due_date` (as
  `date | None`, NOT `str`), `weight_pct`. There is **no** `assignment_type`
  field on the agent's schema today.
- `backend/services/calendar_service.py` — full file. `parse_syllabus`
  returns whatever `call_gemini_json` produces. Look at how
  `insert_new_assignments` (line 23) consumes it: it expects `title`,
  `due_date`, `course_id`, `assignment_type`, `notes` keys.
- `backend/routes/calendar.py:22-130` — the `extract_assignments_from_file`
  consumer. Note any keys it passes to `insert_new_assignments` or any
  fields it surfaces to the user.
- `backend/services/assignment_dedupe.py::assignment_dedupe_key` — what
  shape `insert_new_assignments` expects from `due_date`. This is the
  hard contract: the adapter's `due_date` output must be a string in the
  format that `assignment_dedupe_key` accepts.
- `backend/routes/documents.py:_save_orchestrator_syllabus` (around
  line 431) — already adapts the same agent output for the documents
  upload path. Read it carefully; the adapter you write should be
  consistent with what `_save_orchestrator_syllabus` does (or this is
  itself an opportunity to extract `_save_orchestrator_syllabus`'s
  conversion logic into a shared helper — see "Where to put it" below).

## What to write

### Where to put it

Two reasonable options. Pick whichever is cleaner once you've read both
`_save_orchestrator_syllabus` and `extract_assignments_from_file`:

**Option 1 — new module `backend/agents/tools/syllabus_adapter.py`:**
Standalone module exposing `to_wire_dict(SyllabusAssignments) -> dict`.
Use this if `routes/documents.py` will also benefit from sharing the
helper (it currently inlines its own conversion).

**Option 2 — inline helper in `agents/syllabus_extraction.py`:**
Add a `to_wire_dict` classmethod or module-level function alongside the
agent. Use this if the conversion logic is tiny enough that a separate
module is overkill.

Either way, tests live at
`backend/tests/test_syllabus_adapter.py` (new file).

### Function shape

```python
def syllabus_to_wire_dict(
    output: SyllabusAssignments,
    *,
    raw_text: str = "",
    warnings: list[str] | None = None,
) -> dict:
    """Map the agent's structured output to the legacy dict shape
    consumed by `services/calendar_service.py::extract_assignments_from_file`
    and `routes/calendar.py`.

    Returns:
        {
            "assignments": list[dict],   # legacy shape per below
            "warnings": list[str],
            "raw_text": str,
            "course_title": str | None,
            "grading_categories": list[dict],  # passthrough
        }

    Each assignment dict has keys: `title`, `due_date` (str|None),
    `assignment_type` (default "other"), `notes` (description from
    the agent), `weight_pct` (passthrough).

    `due_date` conversion: agent's `date | None` -> ISO-8601
    string ("YYYY-MM-DD") or None. Don't pass through a
    `datetime.date` object — `insert_new_assignments` and
    `assignment_dedupe_key` expect strings.
    """
```

### `assignment_type` field

The agent schema does NOT have `assignment_type` today. The legacy
dict carries it (with values like "homework", "exam", "project",
"reading", "quiz", "other") and `routes/calendar.py` displays it.

Two options:
- **Default to `"other"` in the adapter** — simplest, matches how
  `insert_new_assignments` (`calendar_service.py:50`) defaults it
  today. Pick this unless the eval set or routes specifically need
  the extracted type.
- **Add `assignment_type` to `SyllabusAssignment` in
  `agents/syllabus_extraction.py`** — only do this if Sub-agent D's
  evals show the agent can produce reliable types and the user-facing
  UI needs them. Bumping `_PROMPT_HASH` invalidates the recorded
  cassette in `tests/evals/cassettes/syllabus_extraction/` — so
  re-record before merge if you go this route.

Default to option 1 (`"other"`) for this PR. Document the
"why we didn't add it to the schema" choice in your report so the
ADR can capture it.

### Tests

`backend/tests/test_syllabus_adapter.py`. At least these cases:

1. `test_returns_legacy_shape` — agent output with 2 assignments
   produces a dict with `assignments`, `warnings`, `raw_text`,
   `course_title`, `grading_categories` keys. `warnings` is `[]`
   when not specified.
2. `test_assignment_type_defaults_to_other` — every assignment in the
   wire dict has `assignment_type="other"`.
3. `test_due_date_serialized_as_iso_string` — agent's
   `date(2026, 5, 15)` becomes `"2026-05-15"`. None stays None.
4. `test_grading_categories_passthrough` — agent's `[GradingCategory(name="Exams", weight=40.0)]`
   becomes `[{"name": "Exams", "weight": 40.0}]`.
5. `test_empty_assignments_list_round_trips` — agent output with empty
   `assignments` produces `{"assignments": []}` plus the other keys.
6. `test_raw_text_passthrough` — `syllabus_to_wire_dict(out, raw_text="abc")`
   sets `result["raw_text"] == "abc"`.

Use the same `MagicMock` factory pattern from
`backend/tests/test_quiz_routes.py::_make_table` if you need any DB
mocks (you probably won't — the adapter is pure logic).

## Verify

```bash
cd "/Users/josegaelcruzlopez/Documents/Startup_Projects /Sapling/backend"
python -m pytest tests/test_syllabus_adapter.py -q --no-header
python -c "from agents.syllabus_extraction import syllabus_extraction_agent, SyllabusAssignments; print('OK')"
# OR if you put it in agents/tools/syllabus_adapter.py:
python -c "from agents.tools.syllabus_adapter import syllabus_to_wire_dict; print('OK')"
```

All adapter tests must pass.

## Constraints

- DO NOT modify `services/calendar_service.py` (sub-agent B is refactoring it).
- DO NOT modify `routes/calendar.py` (sub-agent C verifies it).
- DO NOT modify `tests/evals/syllabus_extraction.py` (sub-agent D's file).
- DO NOT bump `_PROMPT_HASH` in `agents/syllabus_extraction.py` unless
  you genuinely add a field to the schema (see `assignment_type`
  discussion above) — bumping invalidates the recorded eval cassette.
- DO NOT commit. No ADRs.
- DO NOT delete the legacy `prompts/syllabus_extraction.txt`. Sub-agent
  E's cleanup PR handles that after main is stable.

## Report

- File created/modified with line counts.
- Whether you put the adapter in `agents/tools/syllabus_adapter.py` or
  inlined it in `agents/syllabus_extraction.py`. State the reasoning
  in one sentence.
- Whether you added `assignment_type` to the schema or defaulted in the
  adapter. If schema, the new `_PROMPT_HASH` value.
- Test count + pass/fail.
- Anything that didn't fit (e.g. a wire-format gap the adapter can't
  paper over without an agent schema change).

Aim for under 200 words.
