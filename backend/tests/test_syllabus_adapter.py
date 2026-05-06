"""Tests for `agents.tools.syllabus_adapter.syllabus_to_wire_dict`.

The adapter is pure logic over Pydantic models, so no Supabase or
Gemini mocks are needed.
"""
from __future__ import annotations

from datetime import date

import pytest

from agents.syllabus_extraction import (
    GradingCategory,
    SyllabusAssignment,
    SyllabusAssignments,
)
from agents.tools.syllabus_adapter import syllabus_to_wire_dict


def _make_output(
    *,
    assignments: list[SyllabusAssignment] | None = None,
    grading_categories: list[GradingCategory] | None = None,
    course_title: str | None = "CS 101: Intro",
    instructor: str | None = "Prof. Doe",
) -> SyllabusAssignments:
    return SyllabusAssignments(
        course_title=course_title,
        instructor=instructor,
        assignments=assignments if assignments is not None else [],
        grading_categories=grading_categories if grading_categories is not None else [],
    )


def test_returns_legacy_shape():
    out = _make_output(
        assignments=[
            SyllabusAssignment(
                title="HW 1",
                description="Chapter 1 exercises",
                due_date=date(2026, 5, 15),
                weight_pct=10.0,
            ),
            SyllabusAssignment(
                title="Midterm",
                description=None,
                due_date=date(2026, 6, 1),
                weight_pct=30.0,
            ),
        ],
    )
    result = syllabus_to_wire_dict(out)

    assert set(result.keys()) == {
        "assignments",
        "warnings",
        "raw_text",
        "course_title",
        "grading_categories",
    }
    assert len(result["assignments"]) == 2
    assert result["warnings"] == []
    assert result["raw_text"] == ""
    assert result["course_title"] == "CS 101: Intro"
    assert result["grading_categories"] == []

    first = result["assignments"][0]
    assert first["title"] == "HW 1"
    assert first["due_date"] == "2026-05-15"
    assert first["notes"] == "Chapter 1 exercises"
    assert first["weight_pct"] == 10.0


def test_assignment_type_defaults_to_other():
    out = _make_output(
        assignments=[
            SyllabusAssignment(title="HW 1", due_date=date(2026, 5, 15)),
            SyllabusAssignment(title="Final", due_date=date(2026, 7, 1)),
            SyllabusAssignment(title="Reading 1", due_date=None),
        ],
    )
    result = syllabus_to_wire_dict(out)
    assert all(a["assignment_type"] == "other" for a in result["assignments"])


def test_due_date_serialized_as_iso_string():
    out = _make_output(
        assignments=[
            SyllabusAssignment(title="HW 1", due_date=date(2026, 5, 15)),
            SyllabusAssignment(title="TBD", due_date=None),
        ],
    )
    result = syllabus_to_wire_dict(out)
    assert result["assignments"][0]["due_date"] == "2026-05-15"
    assert isinstance(result["assignments"][0]["due_date"], str)
    assert result["assignments"][1]["due_date"] is None


def test_grading_categories_passthrough():
    out = _make_output(
        grading_categories=[
            GradingCategory(name="Exams", weight=40.0),
            GradingCategory(name="Homework", weight=30.0),
        ],
    )
    result = syllabus_to_wire_dict(out)
    assert result["grading_categories"] == [
        {"name": "Exams", "weight": 40.0},
        {"name": "Homework", "weight": 30.0},
    ]


def test_empty_assignments_list_round_trips():
    out = _make_output(assignments=[])
    result = syllabus_to_wire_dict(out)
    assert result["assignments"] == []
    assert "warnings" in result
    assert "raw_text" in result
    assert "course_title" in result
    assert "grading_categories" in result


def test_raw_text_passthrough():
    out = _make_output()
    result = syllabus_to_wire_dict(out, raw_text="abc")
    assert result["raw_text"] == "abc"


def test_warnings_passthrough():
    out = _make_output()
    result = syllabus_to_wire_dict(out, warnings=["truncated", "low confidence"])
    assert result["warnings"] == ["truncated", "low confidence"]


def test_warnings_default_empty_list():
    out = _make_output()
    result = syllabus_to_wire_dict(out)
    assert result["warnings"] == []
    # Mutating the returned list must not leak into future calls.
    result["warnings"].append("mutated")
    fresh = syllabus_to_wire_dict(out)
    assert fresh["warnings"] == []


def test_course_title_none_is_preserved():
    out = _make_output(course_title=None)
    result = syllabus_to_wire_dict(out)
    assert result["course_title"] is None


def test_due_date_string_is_dedupe_compatible():
    """`assignment_dedupe_key` slices `due_date[:10]` and asserts on the
    YYYY-MM-DD shape — the adapter's output must satisfy that contract."""
    from services.assignment_dedupe import assignment_dedupe_key

    out = _make_output(
        assignments=[
            SyllabusAssignment(title="HW 1", due_date=date(2026, 5, 15)),
        ],
    )
    result = syllabus_to_wire_dict(out)
    a = result["assignments"][0]
    key = assignment_dedupe_key(a["title"], a["due_date"])
    assert key == ("HW 1", "2026-05-15")
