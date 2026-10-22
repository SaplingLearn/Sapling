# Rich Notes Content Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Widen a summary doc's content beyond plain paragraphs — structured tables, inline/block math (KaTeX), and lists — generated comprehensively (not as a summary) and shared by both the initial-seed and suggestion/Keep paths through one server-side converter, with the token budget that was silently bottlenecking comprehensiveness fixed.

**Architecture:** `document_notes_agent`'s `NotesSection` gains two flat `list[str]` fields for tables (no nested sub-model — this codebase's CI-enforced output-schema budget forbids that) and its `body` field is now allowed to contain `- `/`N. ` list lines and `$...$`/`$$...$$` math spans. One new Python converter (`body_to_prosemirror_nodes` + `table_to_prosemirror_node`) turns that into ProseMirror JSON, used both when a document is first seeded and when a suggestion is built (`create_suggestion`'s response carries a computed `proposed_content` field, never persisted). `plaintext_from_prosemirror` is extended to serialize rich nodes back to text so the agent can read existing content. The frontend gets matching TipTap extensions (Table, Underline, Highlight, a custom math node) and switches `keepSuggestion` to insert structured content instead of a raw string.

**Tech Stack:** Pydantic AI (Gemini 2.5 Flash), FastAPI, Next.js/React, TipTap 2.27, KaTeX.

**Spec:** `docs/superpowers/specs/2026-10-21-rich-notes-content-model-design.md`

**Deviations from the approved spec (if any emerge during execution) go here, with the task number and reasoning** — none yet; the spec itself was already corrected once (table schema) before this plan was written — see the spec's own §3 correction note.

---

## Backend

### Task 1: `NOTES_LIMITS` — a dedicated usage budget for `document_notes_agent`

**Files:**
- Modify: `backend/agents/__init__.py` (add `NOTES_LIMITS`, export it)
- Modify: `backend/agents/document.py:119` (`_step_notes` uses it instead of `WORKER_LIMITS`)
- Test: `backend/tests/test_document_notes_limits.py` (new file)

**Why this is first:** independent of every other task, smallest possible change, and fixes a real bug (comprehensive notes silently bottlenecked by a 50k-token budget shared with one-paragraph tasks — Gemini 2.5 Flash's own single-response output ceiling is 65,536 tokens alone, larger than that entire shared budget).

- [ ] **Step 1: Write the failing test**

```python
"""Confirms document_notes_agent runs under its own usage budget, not the
shared WORKER_LIMITS every cheap classification/summary task uses."""
from __future__ import annotations

from agents import NOTES_LIMITS, WORKER_LIMITS
from agents.document import _step_notes


def test_notes_limits_is_not_worker_limits():
    assert NOTES_LIMITS is not WORKER_LIMITS


def test_notes_limits_total_tokens_is_generously_larger_than_worker_limits():
    assert NOTES_LIMITS.total_tokens_limit == 300_000
    assert NOTES_LIMITS.total_tokens_limit > WORKER_LIMITS.total_tokens_limit


def test_step_notes_source_uses_notes_limits():
    import inspect

    src = inspect.getsource(_step_notes)
    assert "NOTES_LIMITS" in src
    assert "usage_limits=WORKER_LIMITS" not in src
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && python -m pytest tests/test_document_notes_limits.py -v`
Expected: FAIL — `ImportError: cannot import name 'NOTES_LIMITS' from 'agents'`

- [ ] **Step 3: Implement**

In `backend/agents/__init__.py`, add after the existing `WORKER_LIMITS` block (after its closing `)` at line 58):

```python
# Comprehensive study notes (#document_notes) are deliberately long-form —
# the whole point is "not a summary" — so they cannot share WORKER_LIMITS'
# 50k-token budget with one-paragraph tasks (classification, the card-
# preview summary): Gemini 2.5 Flash's own single-response output ceiling
# is 65,536 tokens, LARGER than that entire shared budget, meaning any real
# lecture-length source could have its input alone consume most of it,
# silently truncating output regardless of how thorough the prompt asks for
# it to be. 300k comfortably covers a long source's input plus genuinely
# thorough output while staying well short of unbounded cost/latency.
NOTES_LIMITS = UsageLimits(
    request_limit=3,
    tool_calls_limit=0,
    total_tokens_limit=300_000,
)
```

Add `"NOTES_LIMITS"` to the `__all__` list at the bottom of the file (alongside the existing `"WORKER_LIMITS"`, `"ORCHESTRATOR_LIMITS"`, `"TUTOR_LIMITS"`, `"CONTINUATION_LIMITS"`).

In `backend/agents/document.py`, change line 119 inside `_step_notes`:

```python
        await document_notes_agent.run(text, deps=deps, usage_limits=NOTES_LIMITS),
```

Add `NOTES_LIMITS` to the existing `from agents import WORKER_LIMITS` import line (around line 55) — it becomes:

```python
from agents import NOTES_LIMITS, WORKER_LIMITS
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && python -m pytest tests/test_document_notes_limits.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Run the full backend suite to confirm no regression**

Run: `cd backend && python -m pytest tests/test_agent_output_schemas.py tests/test_document.py -v`
Expected: PASS — the output-schema budget test doesn't check usage limits, only output types, so this change shouldn't affect it; included as a sanity check since `agents/document.py` was touched.

- [ ] **Step 6: Commit**

```bash
git add backend/agents/__init__.py backend/agents/document.py backend/tests/test_document_notes_limits.py
git commit -m "fix(summary-docs): give document_notes_agent its own token budget (NOTES_LIMITS)"
```

---

### Task 2: `NotesSection` gains flat table fields; prompt extended for tables/math/lists

**Files:**
- Modify: `backend/agents/document_notes.py`
- Test: `backend/tests/test_document_notes_schema.py` (new file)

**Files:**
- Modify: `backend/agents/document_notes.py`
- Test: `backend/tests/test_agent_output_schemas.py` (confirm the existing budget-walking test still passes against the widened schema — no new test needed there, just a verification run)
- Test: `backend/tests/test_document_notes_schema.py` (new file)

- [ ] **Step 1: Write the failing test**

```python
"""Confirms NotesSection's table fields are flat (no sub-model) and default
to empty, and that the system prompt covers the new capabilities."""
from __future__ import annotations

from agents.document_notes import NotesSection, _SYSTEM_PROMPT


def test_notes_section_table_fields_default_to_empty_lists():
    section = NotesSection(heading="Topic", heading_level=2, body="Some notes.")
    assert section.table_headers == []
    assert section.table_rows == []


def test_notes_section_accepts_a_table():
    section = NotesSection(
        heading="Comparison", heading_level=3, body="",
        table_headers=["Claim", "Description"],
        table_rows=["All things are cells\tAll living things are composed of cells"],
    )
    assert section.table_headers == ["Claim", "Description"]
    assert section.table_rows == ["All things are cells\tAll living things are composed of cells"]


def test_notes_section_has_no_nested_submodel_fields():
    # The schema-budget guard (tests/test_agent_output_schemas.py) forbids
    # optional nested models -- this is a direct, local check of the same
    # invariant on this specific model, so a regression fails fast here too.
    for field in NotesSection.model_fields.values():
        annotation = field.annotation
        origin = getattr(annotation, "__origin__", None)
        args = getattr(annotation, "__args__", ())
        # list[str] is fine (flat scalars); a bare pydantic BaseModel
        # subclass, or a list[SomeModel], is what's forbidden.
        if origin is list:
            (inner,) = args
            assert inner in (str, int), f"{field} is a list of a non-scalar type"


def test_system_prompt_covers_tables_math_lists_and_currency():
    assert "table" in _SYSTEM_PROMPT.lower()
    assert "$" in _SYSTEM_PROMPT
    assert "dollars" in _SYSTEM_PROMPT.lower() or "currency" in _SYSTEM_PROMPT.lower()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && python -m pytest tests/test_document_notes_schema.py -v`
Expected: FAIL — `NotesSection() got an unexpected keyword argument 'table_headers'`

- [ ] **Step 3: Implement**

In `backend/agents/document_notes.py`, replace the `NotesSection` class (currently lines 23-46) with:

```python
class NotesSection(BaseModel):
    """One section of the comprehensive notes. The list of sections is kept
    FLAT (no nested sub-section lists) to stay within Gemini's structured-
    output budget (see tests/test_agent_output_schemas.py) — `heading_level`
    expresses outline depth without adding a nesting level: a 3 immediately
    follows the 2 it belongs under, in document order. `table_headers`/
    `table_rows` follow the same flatten-instead-of-nest pattern for tabular
    content: a `TableBlock` sub-model would add a second level of object
    nesting (ComprehensiveNotes -> list[NotesSection] -> TableBlock), which
    the same budget test forbids (`MAX_OBJECT_DEPTH = 2`, "no optional
    nested models")."""

    heading: str = Field(description="Short section title naming the topic.")
    heading_level: int = Field(
        description=(
            "2 for a top-level topic heading, 3 for a subheading nested "
            "under the most recent level-2 heading. Use 3 to break a large "
            "topic into named sub-parts; use 2 for each new top-level topic."
        ),
    )
    body: str = Field(
        description=(
            "The full notes for this section: one or more paragraphs, "
            "separated by a blank line, in plain prose. Thorough enough to "
            "study from directly — definitions, explanations, examples, and "
            "relationships between ideas, not just a one-line summary. May "
            "contain \"- \" (bullet) or \"1. \" (numbered) list lines, and "
            "inline ($...$) or block ($$...$$) math notation for any "
            "mathematical expression. No other markdown syntax, no HTML, "
            "no fenced code blocks."
        ),
    )
    table_headers: list[str] = Field(
        default_factory=list,
        description=(
            "Column headers for this section's table, when the material is "
            "naturally tabular (a comparison, a list of named facts). Empty "
            "list means this section has no table. When a section is "
            "primarily a table, give it a dedicated heading and do not "
            "also restate the table's content as prose in body."
        ),
    )
    table_rows: list[str] = Field(
        default_factory=list,
        description=(
            "Each entry is one table row: its cells, in the same order as "
            "table_headers, joined with a single tab character. Must be "
            "empty when table_headers is empty."
        ),
    )
```

Replace `_SYSTEM_PROMPT` (currently lines 58-81) with:

```python
_SYSTEM_PROMPT = (
    "You are writing comprehensive study notes from a student's uploaded "
    "document (e.g. lecture slides, a reading, a problem set) so the "
    "student can learn everything they need from the notes alone, without "
    "going back to the source.\n\n"
    "This is NOT a summary. Do not compress the material down to a few "
    "sentences or a handful of bullet points. Cover every topic, "
    "definition, explanation, example, formula, and relationship the "
    "source actually presents, in the depth the source presents it. If "
    "the source is long or covers many topics, the notes should be "
    "correspondingly long and cover all of them — do not truncate or pick "
    "only the 'most important' parts.\n\n"
    "Break the material into clearly titled sections, one per topic, in "
    "the order the source presents them. Give each section a heading_level: "
    "2 for a new top-level topic, 3 for a subheading that breaks a large "
    "topic into named sub-parts (a 3 must immediately follow the 2 it "
    "belongs under). Each section's body is plain prose paragraphs, "
    "thorough enough that studying the notes alone would prepare the "
    "student to understand that topic.\n\n"
    "Use the structure that makes the notes most useful to actually study "
    "from, not uniformly for its own sake: use \"- \" or \"1. \" list lines "
    "in body for enumerable steps or criteria; use $...$ (inline) or "
    "$$...$$ (block) math notation for any mathematical expression rather "
    "than describing it in prose; use table_headers/table_rows when "
    "comparing multiple items or listing structured facts side by side, "
    "giving that section its own heading rather than also restating the "
    "table as prose. Write currency and plain numeric amounts in words "
    "(e.g. \"25 dollars\") rather than a bare $ sign, so $ only ever "
    "appears as a math delimiter.\n\n"
    "Stay grounded in the source: do not invent facts it does not state. "
    "If the document is sparse or near-empty, produce a single level-2 "
    "section that says so rather than padding with invented content."
)
```

(`_PROMPT_HASH` below it recomputes automatically since it hashes `_SYSTEM_PROMPT` at import time — no separate change needed, but the hash value itself changes.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_document_notes_schema.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the existing schema-budget guard**

Run: `cd backend && python -m pytest tests/test_agent_output_schemas.py -v`
Expected: PASS — confirms the widened `NotesSection` (now 5 fields: `heading`, `heading_level`, `body`, `table_headers`, `table_rows` — still under the 8-field/depth-2 budget) doesn't trip the CI-enforced guard this task's design specifically had to route around once already (see the spec's §3 correction).

- [ ] **Step 6: Run the full document_notes test suite**

Run: `cd backend && python -m pytest tests/test_document_notes.py -v` (if this file exists — check with `ls tests/ | grep document_notes` first; if the existing document_notes tests live in a differently-named file, run that one instead)
Expected: PASS, including every pre-existing test (the new fields are additive with defaults, so existing test fixtures that don't set them should be unaffected).

- [ ] **Step 7: Commit**

```bash
git add backend/agents/document_notes.py backend/tests/test_document_notes_schema.py
git commit -m "feat(summary-docs): NotesSection carries flat table fields; prompt covers tables/math/lists"
```

---

### Task 3: `body_to_prosemirror_nodes` — the markdown-lite body converter

**Files:**
- Modify: `backend/services/summary_docs_service.py`
- Test: `backend/tests/test_summary_docs_service.py`

- [ ] **Step 1: Write the failing tests**

Add a new test class to `backend/tests/test_summary_docs_service.py` (add `body_to_prosemirror_nodes` to the existing `from services.summary_docs_service import (...)` block at the top of the file):

```python
class TestBodyToProsemirrorNodes:
    def test_single_paragraph(self):
        nodes = body_to_prosemirror_nodes("Just one paragraph.")
        assert nodes == [
            {"type": "paragraph", "content": [{"type": "text", "text": "Just one paragraph."}]},
        ]

    def test_multiple_paragraphs_blank_line_separated(self):
        nodes = body_to_prosemirror_nodes("First.\n\nSecond.")
        assert nodes == [
            {"type": "paragraph", "content": [{"type": "text", "text": "First."}]},
            {"type": "paragraph", "content": [{"type": "text", "text": "Second."}]},
        ]

    def test_bullet_list_lines(self):
        nodes = body_to_prosemirror_nodes("- First law\n- Second law\n- Third law")
        assert nodes == [{
            "type": "bulletList",
            "content": [
                {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "First law"}]}]},
                {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Second law"}]}]},
                {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Third law"}]}]},
            ],
        }]

    def test_numbered_list_lines(self):
        nodes = body_to_prosemirror_nodes("1. Step one\n2. Step two")
        assert nodes == [{
            "type": "orderedList",
            "content": [
                {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Step one"}]}]},
                {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Step two"}]}]},
            ],
        }]

    def test_inline_math_span(self):
        nodes = body_to_prosemirror_nodes("The formula is $F = ma$ for force.")
        assert nodes == [{
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "The formula is "},
                {"type": "math", "attrs": {"latex": "F = ma", "block": False}},
                {"type": "text", "text": " for force."},
            ],
        }]

    def test_block_math_span(self):
        nodes = body_to_prosemirror_nodes("$$\\lim_{x \\to a} f(x) = L$$")
        assert nodes == [{
            "type": "paragraph",
            "content": [{"type": "math", "attrs": {"latex": "\\lim_{x \\to a} f(x) = L", "block": True}}],
        }]

    def test_unclosed_math_delimiter_falls_back_to_literal_text(self):
        nodes = body_to_prosemirror_nodes("The price was $5 and that's it.")
        assert nodes == [{
            "type": "paragraph",
            "content": [{"type": "text", "text": "The price was $5 and that's it."}],
        }]

    def test_empty_body_returns_empty_list(self):
        assert body_to_prosemirror_nodes("") == []
        assert body_to_prosemirror_nodes("   \n\n  ") == []

    def test_mixed_paragraph_and_list_blocks(self):
        nodes = body_to_prosemirror_nodes("Intro paragraph.\n\n- Item one\n- Item two\n\nClosing paragraph.")
        assert len(nodes) == 3
        assert nodes[0]["type"] == "paragraph"
        assert nodes[1]["type"] == "bulletList"
        assert nodes[2]["type"] == "paragraph"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_summary_docs_service.py::TestBodyToProsemirrorNodes -v`
Expected: FAIL — `ImportError: cannot import name 'body_to_prosemirror_nodes'`

- [ ] **Step 3: Implement**

In `backend/services/summary_docs_service.py`, add `import re` to the top-level imports if not already present (check first — this file may already import `re` for other purposes; if so, don't duplicate the import).

Add these functions after the existing `_bullet_list_node` helper (around line 87, right before `def prosemirror_doc_from_sections`):

```python
_LIST_LINE_RE = re.compile(r"^(?:-\s+|\d+\.\s+)")
_BULLET_LINE_RE = re.compile(r"^-\s+(.*)$")
_NUMBERED_LINE_RE = re.compile(r"^\d+\.\s+(.*)$")
_MATH_SPAN_RE = re.compile(r"\$\$(.+?)\$\$|\$(.+?)\$")


def _parse_inline_spans(text: str) -> list[dict]:
    """Split text into text/math inline nodes on $...$/$$...$$ spans. An
    unclosed delimiter (no matching close) never matches the regex at all,
    so it's left as literal text by construction — not a special case to
    handle, just what "no match" means here."""
    nodes: list[dict] = []
    pos = 0
    for m in _MATH_SPAN_RE.finditer(text):
        if m.start() > pos:
            nodes.append({"type": "text", "text": text[pos:m.start()]})
        if m.group(1) is not None:
            nodes.append({"type": "math", "attrs": {"latex": m.group(1), "block": True}})
        else:
            nodes.append({"type": "math", "attrs": {"latex": m.group(2), "block": False}})
        pos = m.end()
    if pos < len(text):
        nodes.append({"type": "text", "text": text[pos:]})
    return nodes


def _list_node_from_lines(lines: list[str]) -> dict:
    is_numbered = all(_NUMBERED_LINE_RE.match(ln) for ln in lines)
    pattern = _NUMBERED_LINE_RE if is_numbered else _BULLET_LINE_RE
    items = []
    for ln in lines:
        m = pattern.match(ln)
        item_text = m.group(1) if m else ln
        items.append({
            "type": "listItem",
            "content": [{"type": "paragraph", "content": _parse_inline_spans(item_text)}],
        })
    return {"type": "orderedList" if is_numbered else "bulletList", "content": items}


def body_to_prosemirror_nodes(body: str) -> list[dict]:
    """Convert a NotesSection.body string into ProseMirror paragraph/list
    nodes. Recognizes exactly three things: blank-line-separated blocks,
    "- "/"N. " list lines (every non-empty line in the block starts with
    one of those markers), and $...$/$$...$$ inline math spans within any
    text. Nothing else — no headings, links, emphasis, or HTML; those
    don't belong in body text (headings come from the section's own
    heading/heading_level fields instead). Used both at seed time
    (prosemirror_doc_from_sections) and for a suggestion's proposed_content
    (create_suggestion) — the one implementation this dialect has."""
    blocks = [b for b in re.split(r"\n\s*\n", body or "") if b.strip()]
    nodes: list[dict] = []
    for block in blocks:
        lines = [ln.strip() for ln in block.split("\n") if ln.strip()]
        if lines and all(_LIST_LINE_RE.match(ln) for ln in lines):
            nodes.append(_list_node_from_lines(lines))
        else:
            text = " ".join(lines)
            nodes.append({"type": "paragraph", "content": _parse_inline_spans(text)})
    return nodes
```

Add `body_to_prosemirror_nodes` to the existing `from services.summary_docs_service import (...)` block in `backend/tests/test_summary_docs_service.py`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_summary_docs_service.py::TestBodyToProsemirrorNodes -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/services/summary_docs_service.py backend/tests/test_summary_docs_service.py
git commit -m "feat(summary-docs): add body_to_prosemirror_nodes, the markdown-lite body converter"
```

---

### Task 4: `table_to_prosemirror_node` — structured table conversion

**Files:**
- Modify: `backend/services/summary_docs_service.py`
- Test: `backend/tests/test_summary_docs_service.py`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_summary_docs_service.py` (add `table_to_prosemirror_node` to the existing import block):

```python
class TestTableToProsemirrorNode:
    def test_builds_header_and_body_rows(self):
        node = table_to_prosemirror_node(["Claim", "Description"], ["Cells\tAll living things are cells"])
        assert node["type"] == "table"
        header_row, body_row = node["content"]
        assert header_row["type"] == "tableRow"
        assert [c["type"] for c in header_row["content"]] == ["tableHeader", "tableHeader"]
        assert body_row["type"] == "tableRow"
        assert [c["type"] for c in body_row["content"]] == ["tableCell", "tableCell"]
        assert body_row["content"][0]["content"] == [{"type": "text", "text": "Cells"}]
        assert body_row["content"][1]["content"] == [{"type": "text", "text": "All living things are cells"}]

    def test_pads_short_rows(self):
        node = table_to_prosemirror_node(["A", "B", "C"], ["only one cell"])
        body_row = node["content"][1]
        assert len(body_row["content"]) == 3
        assert body_row["content"][1]["content"] == []
        assert body_row["content"][2]["content"] == []

    def test_truncates_long_rows(self):
        node = table_to_prosemirror_node(["A", "B"], ["one\ttwo\tthree\tfour"])
        body_row = node["content"][1]
        assert len(body_row["content"]) == 2
        assert body_row["content"][0]["content"] == [{"type": "text", "text": "one"}]
        assert body_row["content"][1]["content"] == [{"type": "text", "text": "two"}]

    def test_empty_rows_still_renders_header_only(self):
        node = table_to_prosemirror_node(["Only", "Headers"], [])
        assert len(node["content"]) == 1
        assert node["content"][0]["type"] == "tableRow"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_summary_docs_service.py::TestTableToProsemirrorNode -v`
Expected: FAIL — `ImportError: cannot import name 'table_to_prosemirror_node'`

- [ ] **Step 3: Implement**

Add to `backend/services/summary_docs_service.py`, right after `body_to_prosemirror_nodes`:

```python
def _table_cell(text: str, *, header: bool) -> dict:
    return {
        "type": "tableHeader" if header else "tableCell",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}] if text else [{"type": "paragraph", "content": []}],
    }


def table_to_prosemirror_node(headers: list[str], rows: list[str]) -> dict:
    """Direct structural conversion from NotesSection.table_headers/
    table_rows — no parsing of ambiguous free text, since the data already
    arrived structured. Each row string's cells are tab-separated; a row
    with fewer cells than len(headers) is padded with empty cells, a row
    with more is truncated — never raises."""
    width = len(headers)
    header_row = {"type": "tableRow", "content": [_table_cell(h, header=True) for h in headers]}
    body_rows = []
    for row in rows:
        cells = row.split("\t")[:width]
        cells += [""] * (width - len(cells))
        body_rows.append({"type": "tableRow", "content": [_table_cell(c, header=False) for c in cells]})
    return {"type": "table", "content": [header_row, *body_rows]}
```

Add `table_to_prosemirror_node` to the existing import block in the test file.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_summary_docs_service.py::TestTableToProsemirrorNode -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/services/summary_docs_service.py backend/tests/test_summary_docs_service.py
git commit -m "feat(summary-docs): add table_to_prosemirror_node, structured table conversion"
```

---

### Task 5: Wire both converters into `prosemirror_doc_from_sections`

**Files:**
- Modify: `backend/services/summary_docs_service.py:90-130` (`prosemirror_doc_from_sections`)
- Test: `backend/tests/test_summary_docs_service.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_summary_docs_service.py` (find the existing `TestProsemirrorDocFromSections` class if one exists — `grep -n "class TestProsemirrorDocFromSections" tests/test_summary_docs_service.py`; if it doesn't exist, add a new one):

```python
class TestProsemirrorDocFromSectionsRichContent:
    def test_section_with_list_body_produces_a_list_node(self):
        doc = prosemirror_doc_from_sections([
            {"heading": "Steps", "heading_level": 2, "body": "- First\n- Second", "table_headers": [], "table_rows": []},
        ])
        types = [n["type"] for n in doc["content"]]
        assert "bulletList" in types

    def test_section_with_table_appends_a_table_node_after_the_body(self):
        doc = prosemirror_doc_from_sections([
            {
                "heading": "Comparison", "heading_level": 2, "body": "See below.",
                "table_headers": ["A", "B"], "table_rows": ["x\ty"],
            },
        ])
        types = [n["type"] for n in doc["content"]]
        assert types.index("table") > types.index("paragraph")
        table_node = next(n for n in doc["content"] if n["type"] == "table")
        assert len(table_node["content"]) == 2  # header row + one body row

    def test_section_with_no_table_fields_emits_no_table_node(self):
        doc = prosemirror_doc_from_sections([
            {"heading": "Plain", "heading_level": 2, "body": "Just prose.", "table_headers": [], "table_rows": []},
        ])
        assert "table" not in [n["type"] for n in doc["content"]]

    def test_section_missing_table_keys_entirely_does_not_error(self):
        # Sections built before this task's change have no table_headers/
        # table_rows keys at all -- .get(...) must degrade gracefully.
        doc = prosemirror_doc_from_sections([
            {"heading": "Old shape", "heading_level": 2, "body": "Still works."},
        ])
        assert "table" not in [n["type"] for n in doc["content"]]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && python -m pytest tests/test_summary_docs_service.py::TestProsemirrorDocFromSectionsRichContent -v`
Expected: FAIL — the list-body test fails because bodies are still split as plain paragraphs (`"- First\n- Second"` becomes one literal paragraph, not a `bulletList`); the table test fails because no table node is ever emitted.

- [ ] **Step 3: Implement**

In `backend/services/summary_docs_service.py`, find the loop body inside `prosemirror_doc_from_sections` (currently around lines 115-129):

```python
    for i, section in enumerate(sections):
        level = section.get("heading_level")
        level = level if level in (2, 3) else 2
        if level == 2 and i > 0:
            content.append(_divider_node())
        heading = (section.get("heading") or "").strip()
        if heading:
            content.append(_heading_node(heading, level))
        paragraphs = [p.strip() for p in (section.get("body") or "").split("\n\n")]
        for p in paragraphs:
            if p:
                content.append({
                    "type": "paragraph",
                    "content": [{"type": "text", "text": p}],
                })
    return {"type": "doc", "content": content}
```

Replace the body-splitting block (from `paragraphs = [...]` through the `return`) with:

```python
    for i, section in enumerate(sections):
        level = section.get("heading_level")
        level = level if level in (2, 3) else 2
        if level == 2 and i > 0:
            content.append(_divider_node())
        heading = (section.get("heading") or "").strip()
        if heading:
            content.append(_heading_node(heading, level))
        content.extend(body_to_prosemirror_nodes(section.get("body") or ""))
        table_headers = section.get("table_headers") or []
        if table_headers:
            content.append(table_to_prosemirror_node(table_headers, section.get("table_rows") or []))
    return {"type": "doc", "content": content}
```

Update the function's docstring (currently ending "...Matches StarterKit's default schema, which the editor (SummaryEditor.tsx) already loads.") to:

```
    Matches the editor's schema (SummaryEditor.tsx) — StarterKit plus the
    table/underline/highlight/math extensions this plan's frontend tasks
    add.
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_summary_docs_service.py -v`
Expected: PASS, including every pre-existing test in the file (the plain-paragraph case is still produced identically by `body_to_prosemirror_nodes` for prose with no lists/math/tables — confirm this by checking that any existing `TestProsemirrorDocFromSections`-style test with plain-prose fixtures still passes unchanged).

- [ ] **Step 5: Commit**

```bash
git add backend/services/summary_docs_service.py backend/tests/test_summary_docs_service.py
git commit -m "feat(summary-docs): prosemirror_doc_from_sections emits lists/math/tables"
```

---

### Task 6: `plaintext_from_prosemirror` round-trips tables and math back to text

**Files:**
- Modify: `backend/services/summary_docs_service.py:133-156` (`plaintext_from_prosemirror`)
- Test: `backend/tests/test_summary_docs_service.py`

**Why this matters:** when a student asks the AI to edit a section that already contains a table or math, `create_suggestion` feeds the CURRENT document back into the prompt via this function — without this task, an existing table/math would simply vanish from what the agent can see and reason about.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_summary_docs_service.py`'s `TestPlaintextFromProsemirror` class:

```python
    def test_renders_a_table_node_back_to_tab_separated_text(self):
        doc = {
            "type": "doc",
            "content": [
                table_to_prosemirror_node(["Claim", "Description"], ["Cells\tLiving things are cells"]),
            ],
        }
        text = plaintext_from_prosemirror(doc)
        assert "Claim\tDescription" in text
        assert "Cells\tLiving things are cells" in text

    def test_renders_an_inline_math_node_back_to_dollar_wrapped_latex(self):
        doc = {
            "type": "doc",
            "content": [{
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "The formula is "},
                    {"type": "math", "attrs": {"latex": "F = ma", "block": False}},
                ],
            }],
        }
        assert plaintext_from_prosemirror(doc) == "The formula is $F = ma$"

    def test_renders_a_block_math_node_back_to_double_dollar_wrapped_latex(self):
        doc = {
            "type": "doc",
            "content": [{
                "type": "paragraph",
                "content": [{"type": "math", "attrs": {"latex": "x^2", "block": True}}],
            }],
        }
        assert plaintext_from_prosemirror(doc) == "$$x^2$$"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_summary_docs_service.py::TestPlaintextFromProsemirror -v`
Expected: FAIL — table nodes are skipped entirely (not `"paragraph"`/`"heading"`), and math nodes inside a paragraph's `content` render as empty string (the current walk only reads `child.get("text", "")` for `type == "text"` children, silently dropping math children).

- [ ] **Step 3: Implement**

Replace `plaintext_from_prosemirror` (currently lines 133-156) with:

```python
def _inline_content_to_text(content: list[dict]) -> str:
    parts = []
    for child in content:
        if child.get("type") == "text":
            parts.append(child.get("text", ""))
        elif child.get("type") == "math":
            attrs = child.get("attrs") or {}
            latex = attrs.get("latex", "")
            parts.append(f"$${latex}$$" if attrs.get("block") else f"${latex}$")
    return "".join(parts)


def _table_node_to_text(node: dict) -> str:
    rows = []
    for row in node.get("content") or []:
        cells = []
        for cell in row.get("content") or []:
            cell_text = "".join(
                _inline_content_to_text(p.get("content") or [])
                for p in (cell.get("content") or [])
                if p.get("type") == "paragraph"
            )
            cells.append(cell_text)
        rows.append("\t".join(cells))
    return "\n".join(rows)


def plaintext_from_prosemirror(doc: dict, max_chars: int | None = None) -> str:
    """Walk a ProseMirror doc and render it back to legible text — paragraphs
    AND headings (comprehensive notes seed section headings via
    `prosemirror_doc_from_sections`, and dropping them would silently strip
    every topic title out of search/preview/agent-context text) joined by a
    blank line, text nodes within a block concatenated with no separator
    (mirroring how ProseMirror itself renders marks as adjacent text runs).
    A math node renders back to its $...$/$$...$$ source; a table node
    renders as tab-separated rows, one per line, so the agent reading this
    for an "ask" prompt can coherently reason about and extend rich content
    it didn't just generate. Used for search/preview text and as agent
    context, never for re-rendering: exact formatting (list markers, etc.)
    is intentionally lost — this is prose-legible text, not the dialect
    body_to_prosemirror_nodes parses."""
    block_texts: list[str] = []
    for node in doc.get("content") or []:
        node_type = node.get("type")
        if node_type in ("paragraph", "heading"):
            text = _inline_content_to_text(node.get("content") or [])
            if text:
                block_texts.append(text)
        elif node_type == "table":
            text = _table_node_to_text(node)
            if text:
                block_texts.append(text)
    joined = "\n\n".join(block_texts)
    if max_chars is not None:
        return joined[:max_chars]
    return joined
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_summary_docs_service.py -v`
Expected: PASS, including every pre-existing `TestPlaintextFromProsemirror` test (plain paragraph/heading walking is unchanged behavior, just refactored into `_inline_content_to_text`).

- [ ] **Step 5: Run the full backend suite as a regression check**

Run: `cd backend && python -m pytest tests/test_summary_docs_service.py tests/test_summary_docs_routes.py tests/test_documents_routes.py -v`
Expected: PASS — `plaintext_from_prosemirror` is called from several places (concept-scan context, `create_suggestion`'s prompt building); this confirms none of those call sites broke.

- [ ] **Step 6: Commit**

```bash
git add backend/services/summary_docs_service.py backend/tests/test_summary_docs_service.py
git commit -m "feat(summary-docs): plaintext_from_prosemirror round-trips tables and math"
```

---

### Task 7: `create_suggestion` and `get_summary_doc` compute `proposed_content` on read

**Files:**
- Modify: `backend/services/summary_docs_service.py:602-667` (`create_suggestion`), `:242-256` (`get_summary_doc`'s `pending_suggestions` block)
- Test: `backend/tests/test_summary_docs_service.py`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_summary_docs_service.py`'s `TestCreateSuggestion` class:

```python
    def test_response_includes_proposed_content(self, monkeypatch):
        from pydantic_ai.messages import ModelResponse, ToolCallPart, ModelRequest
        from services.encryption import encrypt_json

        def _handler(messages, info):
            return ModelResponse(parts=[
                ToolCallPart(tool_name="final_result", args={"proposed_text": "- Point one\n- Point two"}),
            ])

        monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
        register_function_handler("summary_edit", _handler)
        doc_row = {
            "id": "sd1", "owner_user_id": "u1", "primary_document_id": "doc1",
            "content": encrypt_json({"type": "doc", "content": []}),
            "created_at": "t0", "updated_at": "t0",
        }

        def _select(name):
            m = MagicMock()
            if name == "summary_docs":
                m.select.return_value = [doc_row]
            elif name == "summary_doc_sources":
                m.select.return_value = []
            elif name in ("documents", "summary_doc_suggestions"):
                m.select.return_value = []
                m.insert.return_value = [{
                    "id": "sg1", "summary_doc_id": "sd1", "anchor_from": None, "anchor_to": None,
                    "instruction": "ciphertext", "original_text": None,
                    "proposed_text": "ciphertext", "status": "pending",
                    "created_at": "t0", "resolved_at": None,
                }]
            return m

        with patch("services.summary_docs_service.table", side_effect=_select) as mock_table, \
             summary_edit_agent.override(model=model_for("summary_edit")):
            result = create_suggestion(
                "sd1", "u1", anchor_from=None, anchor_to=None,
                instruction="list the key points", original_text=None,
            )

        assert result["proposed_content"] == [{
            "type": "bulletList",
            "content": [
                {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Point one"}]}]},
                {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Point two"}]}]},
            ],
        }]
        # Never persisted -- the insert() call to summary_doc_suggestions
        # must not carry a proposed_content key.
        insert_calls = [c for c in mock_table.call_args_list if c.args == ("summary_doc_suggestions",)]
        suggestions_mock = _select("summary_doc_suggestions")
        for call in suggestions_mock.insert.call_args_list:
            assert "proposed_content" not in call.args[0]
```

Add to `backend/tests/test_summary_docs_service.py`'s existing `get_summary_doc` test class (find it via `grep -n "test_attaches_sources_and_pending_suggestions"`):

```python
    def test_pending_suggestions_include_computed_proposed_content(self):
        doc_row = {
            "id": "sd1", "owner_user_id": "u1", "primary_document_id": "doc1",
            "content": encrypt_json({"type": "doc", "content": []}),
            "created_at": "t0", "updated_at": "t0",
        }

        def _select(name):
            m = MagicMock()
            if name == "summary_docs":
                m.select.return_value = [doc_row]
            elif name == "summary_doc_sources":
                m.select.return_value = []
            elif name == "documents":
                m.select.return_value = []
            elif name == "summary_doc_suggestions":
                m.select.return_value = [{
                    "id": "sg1", "anchor_from": None, "anchor_to": None,
                    "instruction": encrypt_if_present("add this"),
                    "original_text": None,
                    "proposed_text": encrypt_if_present("A new point."),
                    "status": "pending", "created_at": "t0", "resolved_at": None,
                }]
            return m

        with patch("services.summary_docs_service.table", side_effect=_select):
            doc = get_summary_doc("sd1", "u1")

        assert doc["pending_suggestions"][0]["proposed_content"] == [
            {"type": "paragraph", "content": [{"type": "text", "text": "A new point."}]},
        ]
```

(`encrypt_if_present` must already be imported in this test file — check first; if not, add it to the existing `services.encryption` import.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_summary_docs_service.py -k proposed_content -v`
Expected: FAIL — `KeyError: 'proposed_content'`

- [ ] **Step 3: Implement**

In `backend/services/summary_docs_service.py`, in `create_suggestion`, change the end of the function (currently lines 662-666):

```python
    row = dict(inserted[0])
    row["instruction"] = instruction
    row["original_text"] = original_text
    row["proposed_text"] = proposed_text
    return row
```

to:

```python
    row = dict(inserted[0])
    row["instruction"] = instruction
    row["original_text"] = original_text
    row["proposed_text"] = proposed_text
    # Computed fresh from the already-decrypted proposed_text above, never
    # passed to the insert() call -- summary_doc_suggestions.proposed_text
    # stays the sole encrypted-at-rest source of this content (no new
    # plaintext-at-rest column). The frontend's Keep flow inserts this
    # structured fragment instead of the raw string (SummaryEditor.tsx).
    row["proposed_content"] = body_to_prosemirror_nodes(proposed_text)
    return row
```

In `get_summary_doc`, change the `pending_suggestions` block (currently lines 247-255):

```python
    doc["pending_suggestions"] = [
        {
            **s,
            "instruction": decrypt_if_present(s.get("instruction")) or "",
            "original_text": decrypt_if_present(s.get("original_text")),
            "proposed_text": decrypt_if_present(s.get("proposed_text")) or "",
        }
        for s in suggestion_rows
    ]
```

to:

```python
    def _with_decrypted_fields(s: dict) -> dict:
        proposed_text = decrypt_if_present(s.get("proposed_text")) or ""
        return {
            **s,
            "instruction": decrypt_if_present(s.get("instruction")) or "",
            "original_text": decrypt_if_present(s.get("original_text")),
            "proposed_text": proposed_text,
            # Same "computed on every read, never persisted" rule as
            # create_suggestion -- the Keep flow works identically whether
            # the suggestion was just created or fetched on a later load.
            "proposed_content": body_to_prosemirror_nodes(proposed_text),
        }

    doc["pending_suggestions"] = [_with_decrypted_fields(s) for s in suggestion_rows]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_summary_docs_service.py -v`
Expected: PASS, including every pre-existing test in the file.

- [ ] **Step 5: Run the summary_docs routes suite as a regression check**

Run: `cd backend && python -m pytest tests/test_summary_docs_routes.py -v`
Expected: PASS — `routes/summary_docs.py`'s `post_ask` returns `create_suggestion`'s result dict verbatim, so `proposed_content` flows through automatically; no route change needed, but confirm nothing there asserts an exact response-dict shape that would now fail on the extra key (if any test does `assert r.json() == {...}` with an exact dict, it needs the new key added — check and fix if so).

- [ ] **Step 6: Commit**

```bash
git add backend/services/summary_docs_service.py backend/tests/test_summary_docs_service.py
git commit -m "feat(summary-docs): create_suggestion/get_summary_doc compute proposed_content on read"
```

---

## Frontend

### Task 8: Add TipTap table/underline/highlight extensions and KaTeX

**Files:**
- Modify: `frontend/package.json`

- [ ] **Step 1: Install the dependencies**

Run (from `frontend/`):
```bash
npm install @tiptap/extension-table@^2.27.3 @tiptap/extension-table-row@^2.27.3 @tiptap/extension-table-cell@^2.27.3 @tiptap/extension-table-header@^2.27.3 @tiptap/extension-underline@^2.27.3 @tiptap/extension-highlight@^2.27.3 katex
```
Expected: all seven packages appear under `dependencies` in `package.json`; `package-lock.json` updates. The `@tiptap/*` versions are pinned to match the existing `@tiptap/core`/`@tiptap/react`/`@tiptap/starter-kit` versions already in `package.json` (`^2.27.3`) — mismatched TipTap extension versions can break at runtime.

- [ ] **Step 2: Verify the frontend still typechecks**

Run (from `frontend/`): `npx tsc --noEmit`
Expected: no new errors (nothing imports these packages yet).

- [ ] **Step 3: Commit**

```bash
git add frontend/package.json frontend/package-lock.json
git commit -m "feat(summary-docs): add TipTap table/underline/highlight extensions and katex"
```

---

### Task 9: `MathNode` — inline KaTeX-rendered math node

**Files:**
- Create: `frontend/src/lib/summaryEditor/mathNode.ts`
- Test: `frontend/src/lib/summaryEditor/mathNode.test.ts`

**Scope note:** a TipTap NodeView's full DOM lifecycle (mount/update/destroy against a real ProseMirror EditorView) is not meaningfully unit-testable without a real editor instance — this task's unit test instead exercises the extension's own logic directly: that the node registers correctly in a real (headless, no React rendering needed) `@tiptap/core` `Editor` instance, that inserting math JSON round-trips through `getJSON()`, and that the KaTeX-rendering helper function produces the expected HTML for valid and invalid LaTeX. This mirrors the same scope-limiting approach the source-reference-viewer plan's `SourceViewer` task took for `pdfjs-dist`.

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/src/lib/summaryEditor/mathNode.test.ts
import { describe, it, expect } from "vitest";
import { Editor } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";

import { MathNode, renderMathHTML } from "./mathNode";

describe("renderMathHTML", () => {
  it("renders valid LaTeX to a KaTeX HTML string", () => {
    const html = renderMathHTML("F = ma", false);
    expect(html).toContain("katex");
  });

  it("renders block math in display mode", () => {
    const html = renderMathHTML("x^2", true);
    expect(html).toContain("katex-display");
  });

  it("does not throw on malformed LaTeX, and includes an error indicator", () => {
    const html = renderMathHTML("\\notarealcommand{", false);
    expect(html).toContain("katex-error");
  });
});

describe("MathNode (editor integration)", () => {
  it("registers a math node in the schema", () => {
    const editor = new Editor({ extensions: [StarterKit, MathNode] });
    expect(editor.schema.nodes.math).toBeDefined();
    editor.destroy();
  });

  it("round-trips a math node through insertContent/getJSON", () => {
    const editor = new Editor({
      extensions: [StarterKit, MathNode],
      content: { type: "doc", content: [{ type: "paragraph", content: [] }] },
    });
    editor.commands.insertContentAt(1, { type: "math", attrs: { latex: "a^2 + b^2 = c^2", block: false } });
    const json = editor.getJSON();
    const mathNode = json.content?.[0]?.content?.find((n: { type?: string }) => n.type === "math");
    expect(mathNode?.attrs).toEqual({ latex: "a^2 + b^2 = c^2", block: false });
    editor.destroy();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from `frontend/`): `npx vitest run src/lib/summaryEditor/mathNode.test.ts`
Expected: FAIL — `Cannot find module './mathNode'`

- [ ] **Step 3: Implement**

```typescript
// frontend/src/lib/summaryEditor/mathNode.ts
import { Node, mergeAttributes } from "@tiptap/core";
import katex from "katex";

export interface MathNodeOptions {
  HTMLAttributes: Record<string, unknown>;
}

declare module "@tiptap/core" {
  interface Commands<ReturnType> {
    mathNode: {
      setMathLatex: (latex: string) => ReturnType;
    };
  }
}

/** Renders LaTeX to a KaTeX HTML string. Never throws (`throwOnError:
 * false`) -- malformed LaTeX (whether AI-generated or student-edited)
 * degrades to KaTeX's own inline error markup instead of crashing the
 * editor's render path. */
export function renderMathHTML(latex: string, block: boolean): string {
  return katex.renderToString(latex, { throwOnError: false, displayMode: block });
}

/** An inline atom node storing raw LaTeX source, rendered via KaTeX. Real
 * glyph rendering needs a NodeView -- a mark can only restyle existing
 * text, it can't replace what's displayed. Editing is click-to-open-a-
 * popup on the raw LaTeX source, not WYSIWYG math editing. */
export const MathNode = Node.create<MathNodeOptions>({
  name: "math",
  group: "inline",
  inline: true,
  atom: true,
  addOptions() {
    return { HTMLAttributes: {} };
  },
  addAttributes() {
    return {
      latex: { default: "" },
      block: { default: false },
    };
  },
  parseHTML() {
    return [{ tag: "span[data-math-latex]" }];
  },
  renderHTML({ HTMLAttributes, node }) {
    return [
      "span",
      mergeAttributes(this.options.HTMLAttributes, HTMLAttributes, {
        "data-math-latex": node.attrs.latex,
        "data-math-block": node.attrs.block ? "true" : "false",
      }),
    ];
  },
  addNodeView() {
    return ({ node, getPos, editor }) => {
      const dom = document.createElement("span");
      dom.className = "summary-math-node";
      dom.innerHTML = renderMathHTML(node.attrs.latex, node.attrs.block);
      dom.addEventListener("click", () => {
        const next = window.prompt("Edit LaTeX:", node.attrs.latex);
        if (next === null || typeof getPos !== "function") return;
        const pos = getPos();
        editor.chain().setNodeSelection(pos).updateAttributes("math", { latex: next }).run();
      });
      return {
        dom,
        update: (updatedNode) => {
          if (updatedNode.type.name !== "math") return false;
          dom.innerHTML = renderMathHTML(updatedNode.attrs.latex, updatedNode.attrs.block);
          return true;
        },
      };
    };
  },
  addCommands() {
    return {
      setMathLatex:
        (latex: string) =>
        ({ commands }) =>
          commands.insertContent({ type: this.name, attrs: { latex, block: false } }),
    };
  },
});
```

(The edit interaction uses `window.prompt` as the "small popup" from the spec — the simplest possible implementation that satisfies "editing the raw LaTeX source, not WYSIWYG." If this reads as too crude once seen in the running app, a follow-up can replace it with a small positioned `<input>` without changing the node's public shape — `latex`/`block` attrs and the `setMathLatex` command stay the same either way.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `npx vitest run src/lib/summaryEditor/mathNode.test.ts`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/summaryEditor/mathNode.ts frontend/src/lib/summaryEditor/mathNode.test.ts
git commit -m "feat(summary-docs): add MathNode, inline KaTeX-rendered math"
```

---

### Task 10: Wire Table/Underline/Highlight/MathNode into `SummaryEditor`'s schema

**Files:**
- Modify: `frontend/src/components/screens/SummaryEditor/SummaryEditor.tsx:71`
- Test: `frontend/src/lib/summaryEditor/richSchema.test.ts` (new file)

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/src/lib/summaryEditor/richSchema.test.ts
import { describe, it, expect } from "vitest";
import { Editor } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";
import Table from "@tiptap/extension-table";
import TableRow from "@tiptap/extension-table-row";
import TableCell from "@tiptap/extension-table-cell";
import TableHeader from "@tiptap/extension-table-header";
import Underline from "@tiptap/extension-underline";
import Highlight from "@tiptap/extension-highlight";

import { MathNode } from "./mathNode";

const extensions = [
  StarterKit, Table.configure({ resizable: false }), TableRow, TableCell, TableHeader,
  Underline, Highlight, MathNode,
];

describe("SummaryEditor's rich schema", () => {
  it("registers table, underline, highlight, and math nodes/marks", () => {
    const editor = new Editor({ extensions });
    expect(editor.schema.nodes.table).toBeDefined();
    expect(editor.schema.nodes.tableRow).toBeDefined();
    expect(editor.schema.nodes.tableCell).toBeDefined();
    expect(editor.schema.nodes.tableHeader).toBeDefined();
    expect(editor.schema.marks.underline).toBeDefined();
    expect(editor.schema.marks.highlight).toBeDefined();
    expect(editor.schema.nodes.math).toBeDefined();
    editor.destroy();
  });

  it("can insert a table via the Table extension's own command", () => {
    const editor = new Editor({
      extensions,
      content: { type: "doc", content: [{ type: "paragraph", content: [] }] },
    });
    const inserted = editor.commands.insertTable({ rows: 2, cols: 2, withHeaderRow: true });
    expect(inserted).toBe(true);
    const json = editor.getJSON();
    expect(json.content?.some((n) => n.type === "table")).toBe(true);
    editor.destroy();
  });

  it("round-trips a backend-built table node unchanged", () => {
    const editor = new Editor({ extensions, content: { type: "doc", content: [] } });
    const tableJSON = {
      type: "table",
      content: [
        { type: "tableRow", content: [{ type: "tableHeader", content: [{ type: "paragraph", content: [{ type: "text", text: "A" }] }] }] },
        { type: "tableRow", content: [{ type: "tableCell", content: [{ type: "paragraph", content: [{ type: "text", text: "1" }] }] }] },
      ],
    };
    editor.commands.setContent({ type: "doc", content: [tableJSON] });
    expect(editor.getJSON().content?.[0]).toEqual(tableJSON);
    editor.destroy();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from `frontend/`): `npx vitest run src/lib/summaryEditor/richSchema.test.ts`
Expected: FAIL — `Cannot find module '@tiptap/extension-table'` (not yet imported anywhere, though installed in Task 8 — this test is what first exercises it) and `editor.schema.nodes.table` is `undefined`.

- [ ] **Step 3: Implement**

In `frontend/src/components/screens/SummaryEditor/SummaryEditor.tsx`, add imports after the existing `SuggestionDecorations` import (around line 19):

```typescript
import Table from "@tiptap/extension-table";
import TableRow from "@tiptap/extension-table-row";
import TableCell from "@tiptap/extension-table-cell";
import TableHeader from "@tiptap/extension-table-header";
import Underline from "@tiptap/extension-underline";
import Highlight from "@tiptap/extension-highlight";
import { MathNode } from "@/lib/summaryEditor/mathNode";
```

Change the `useEditor` extensions list (currently line 71):

```typescript
    extensions: [StarterKit, SuggestionMark, SuggestionDecorations],
```

to:

```typescript
    extensions: [
      StarterKit, SuggestionMark, SuggestionDecorations,
      Table.configure({ resizable: false }), TableRow, TableCell, TableHeader,
      Underline, Highlight, MathNode,
    ],
```

(`resizable: false` — no toolbar/drag-handle UI exists yet to drive column resizing in this sub-project; this stays a plain, non-interactively-resizable table until the toolbar sub-project adds the affordance, if it ever needs one.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `npx vitest run src/lib/summaryEditor/richSchema.test.ts`
Expected: PASS (3 tests)

- [ ] **Step 5: Run the full SummaryEditor test suite and typecheck**

Run: `npx vitest run src/components/screens/SummaryEditor/` and `npx tsc --noEmit`
Expected: both clean — widening the extensions list shouldn't change any existing `SummaryEditor.test.tsx` behavior (none of those tests exercise tables/underline/highlight/math).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/screens/SummaryEditor/SummaryEditor.tsx frontend/src/lib/summaryEditor/richSchema.test.ts
git commit -m "feat(summary-docs): wire table/underline/highlight/math extensions into SummaryEditor"
```

---

### Task 11: `keepSuggestion` inserts structured `proposed_content`, not raw text

**Files:**
- Modify: `frontend/src/lib/types.ts` (`SummaryDocSuggestion`)
- Modify: `frontend/src/components/screens/SummaryEditor/SummaryEditor.tsx:25-34` (`prosemirrorDocFromText`), `:129-170` (`keepSuggestion`)
- Test: `frontend/src/components/screens/SummaryEditor/SummaryEditor.test.tsx`

- [ ] **Step 1: Write the failing tests**

Add to `frontend/src/components/screens/SummaryEditor/SummaryEditor.test.tsx`'s `BASE_DOC.pending_suggestions` fixture entry, and to any suggestion object a test constructs inline, a `proposed_content` field — check the existing fixture shape first (`grep -n "pending_suggestions" SummaryEditor.test.tsx`) and add `proposed_content: [{ type: "paragraph", content: [{ type: "text", text: <same text as proposed_text> }] }]` to each one so existing tests keep passing once `keepSuggestion` starts reading it.

Add a new test to the file's existing `describe` block for Keep behavior (find it via `grep -n "describe(" SummaryEditor.test.tsx` and place this alongside the other Keep-related tests):

```typescript
  it("inserts proposed_content (structured JSON), not proposed_text, when keeping an anchored suggestion", async () => {
    const suggestion = {
      id: "sg-math", anchor_from: 1, anchor_to: 6,
      instruction: "add the formula", original_text: "Hello",
      proposed_text: "$F = ma$",
      proposed_content: [{
        type: "paragraph",
        content: [{ type: "math", attrs: { latex: "F = ma", block: false } }],
      }],
      status: "pending", created_at: "t0",
    };
    mockGetSummaryDoc.mockResolvedValue({ ...BASE_DOC, pending_suggestions: [suggestion] });
    render(<SummaryEditor summaryDocId="sd1" />);
    await waitFor(() => expect(screen.getByText("Hi")).toBeInTheDocument());

    await userEvent.click(screen.getByRole("button", { name: "Keep it" }));

    await waitFor(() => expect(mockUpdateSummaryDocContent).toHaveBeenCalled());
    const [, , content] = mockUpdateSummaryDocContent.mock.calls[0];
    const serialized = JSON.stringify(content);
    expect(serialized).toContain('"type":"math"');
    expect(serialized).toContain('"latex":"F = ma"');
  });
```

(Adapt the mock/assertion details — exact mock names like `mockUpdateSummaryDocContent`, and how autosave-after-Keep is asserted — to match whatever the real existing Keep tests in this file already do; this is illustrative of the intent — "kept content contains the math node, not the literal string `$F = ma$`" — not a literal transcript to paste blindly. Read the file's existing Keep/autosave tests first.)

- [ ] **Step 2: Run the test to verify it fails**

Run (from `frontend/`): `npx vitest run src/components/screens/SummaryEditor/SummaryEditor.test.tsx`
Expected: FAIL — the kept content contains the literal text `$F = ma$`, not a `math` node, because `keepSuggestion` still inserts `proposed_text` as a plain string.

- [ ] **Step 3: Implement**

In `frontend/src/lib/types.ts`, add to `SummaryDocSuggestion` (after `proposed_text: string;`):

```typescript
  proposed_content: Record<string, unknown>[];
```

In `frontend/src/components/screens/SummaryEditor/SummaryEditor.tsx`, add an import for `Fragment` from `@tiptap/pm/model` (alongside the existing TipTap imports near the top):

```typescript
import { Fragment } from "@tiptap/pm/model";
```

Replace the anchored-Keep branch inside `keepSuggestion` (currently lines 148-157):

```typescript
        // insertContentAt inherits the stored marks active at the insertion
        // point — since the replaced range carries suggestionMark, the
        // inserted text would otherwise keep the "pending" highlight
        // forever. Select exactly what was inserted and strip the mark.
        editor
          .chain()
          .insertContentAt({ from: s.anchor_from, to: s.anchor_to }, s.proposed_text)
          .setTextSelection({ from: s.anchor_from, to: s.anchor_from + s.proposed_text.length })
          .unsetSuggestionMark()
          .run();
```

with:

```typescript
        // insertContentAt inherits the stored marks active at the insertion
        // point — since the replaced range carries suggestionMark, the
        // inserted content would otherwise keep the "pending" highlight
        // forever. Select exactly what was inserted and strip the mark.
        // proposed_content is structured ProseMirror JSON (may contain a
        // math/table/list node, not just plain text) -- its on-document
        // size doesn't equal s.proposed_text.length once it does, so the
        // selection end is computed from the actual inserted fragment via
        // Fragment.fromJSON, not the raw string's character count.
        const insertedSize = Fragment.fromJSON(editor.schema, s.proposed_content).size;
        editor
          .chain()
          .insertContentAt({ from: s.anchor_from, to: s.anchor_to }, s.proposed_content)
          .setTextSelection({ from: s.anchor_from, to: s.anchor_from + insertedSize })
          .unsetSuggestionMark()
          .run();
```

Replace the whole-doc Keep branch (currently line 166):

```typescript
        editor.commands.setContent(prosemirrorDocFromText(s.proposed_text));
```

with:

```typescript
        editor.commands.setContent({ type: "doc", content: s.proposed_content });
```

`prosemirrorDocFromText` (currently lines 25-34) is now unused by `keepSuggestion` — check with `grep -n "prosemirrorDocFromText" SummaryEditor.tsx` whether anything else in the file still calls it. If nothing else does, delete the function; if something else still uses it (e.g. an initial-load fallback), leave it in place.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npx vitest run src/components/screens/SummaryEditor/SummaryEditor.test.tsx`
Expected: PASS, including every pre-existing test (the anchored/whole-doc Keep tests that use plain-text-only suggestions still pass, since `Fragment.fromJSON` on a single-text-node paragraph fragment produces the same size as the old `.length`-based calculation for plain text).

- [ ] **Step 5: Run the full frontend suite and typecheck**

Run: `npx vitest run` and `npx tsc --noEmit`
Expected: both clean.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/types.ts frontend/src/components/screens/SummaryEditor/SummaryEditor.tsx frontend/src/components/screens/SummaryEditor/SummaryEditor.test.tsx
git commit -m "feat(summary-docs): keepSuggestion inserts structured proposed_content"
```

---

## Self-review notes (writing-plans skill)

- **Spec coverage:** §3 data model (flat `table_headers`/`table_rows`, corrected per the spec's own in-document correction note) → Task 2. §4 backend (`NOTES_LIMITS`, both converters, `prosemirror_doc_from_sections` wiring, `plaintext_from_prosemirror` round trip, `proposed_content` on both read paths) → Tasks 1, 3, 4, 5, 6, 7. §5 frontend (new deps, `MathNode`, extensions wiring, `keepSuggestion`) → Tasks 8, 9, 10, 11. §6 security (narrow hand-rolled converter, no general markdown/HTML, `proposed_content` never persisted) → enforced by Task 3's exact regex/line-marker set and Task 7's "never passed to insert()" comment + test. §7 error handling (unclosed math → literal text, mismatched table rows → pad/truncate) → Task 3's `test_unclosed_math_delimiter_falls_back_to_literal_text`, Task 4's padding/truncation tests. §8 out-of-scope items (toolbar, ToC, comments, Study Guide merge, WYSIWYG math, backfill) → no task in this plan touches any of them, confirming nothing here over-built.
- **Type consistency checked:** `body_to_prosemirror_nodes(body: str) -> list[dict]` (Task 3) is called with that exact signature in Task 5 (`prosemirror_doc_from_sections`) and Task 7 (`create_suggestion`/`get_summary_doc`) — same name, same return shape, everywhere. `table_to_prosemirror_node(headers: list[str], rows: list[str]) -> dict` (Task 4) likewise matches its Task 5 call site exactly (`section.get("table_headers")`/`section.get("table_rows")`, matching Task 2's field names). The `math` node's attrs (`latex: str`, `block: bool`) are spelled identically across Task 3's Python dict construction, Task 6's Python round-trip reader, Task 9's TypeScript `MathNode` attribute definitions, and Task 10's round-trip test — no renamed fields across the Python/TypeScript boundary.
- **Deviation from the approved spec, found while writing this plan (already folded back into the spec itself, see its §3 correction):** the original spec draft put a `TableBlock` sub-model on `NotesSection` and gave `summary_edit_agent`'s output type a matching optional table field "for symmetry." Both violate `agents/__init__.py`'s CI-enforced output-schema budget (`tests/test_agent_output_schemas.py`'s `MAX_OBJECT_DEPTH = 2` / "no optional nested models") — the first because `ComprehensiveNotes -> list[NotesSection] -> TableBlock` is a second level of nesting past the ceiling, the second because `SummaryEdit` is explicitly documented as kept to one field for the identical reason. This plan's Task 2 uses two flat `list[str]` fields instead (following the exact pattern `heading_level` already established on this same model), and Task 7 gives suggestions `proposed_content` built only from `body_to_prosemirror_nodes` (lists + math, no AI-proposed tables) — both corrections are already reflected in the committed spec file, not just this plan.
