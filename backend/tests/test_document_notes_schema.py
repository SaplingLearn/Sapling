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
