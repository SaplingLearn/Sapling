"""Adapter from the syllabus-extraction agent's typed output to the
legacy wire-format dict consumed by `services/calendar_service.py` and
`routes/calendar.py`.

The agent (`agents/syllabus_extraction.py`) emits a typed
`SyllabusAssignments` Pydantic model with `due_date: date | None` and
no `assignment_type` field. The legacy pipeline returned a dict whose
assignments carried `title`, `due_date` (str), `assignment_type`
(string, default "other"), and `notes`. Downstream code
(`insert_new_assignments`, `assignment_dedupe_key`) expects strings for
`due_date` — never `datetime.date` instances. This module is the only
place that translation lives, so calendar-service and documents-route
callers get the same shape.
"""
from __future__ import annotations

from agents.syllabus_extraction import SyllabusAssignments


def syllabus_to_wire_dict(
    output: SyllabusAssignments,
    *,
    raw_text: str = "",
    warnings: list[str] | None = None,
) -> dict:
    """Map agent output to the legacy `extract_assignments_from_file` dict.

    Returns a dict with keys:
        assignments: list[dict] — each {title, due_date, assignment_type,
                     notes, weight_pct}. `due_date` is an ISO-8601 string
                     ("YYYY-MM-DD") or None. `assignment_type` defaults
                     to "other" because the agent schema does not yet
                     extract it (see ADR notes — defaulting in the
                     adapter avoids invalidating the recorded eval
                     cassette by bumping `_PROMPT_HASH`).
        warnings: list[str] — passthrough; defaults to [].
        raw_text: str — passthrough of the OCR text the agent saw.
        course_title: str | None — agent's `course_title`.
        grading_categories: list[dict] — passthrough as
                            [{name, weight}].
    """
    assignments: list[dict] = []
    for a in output.assignments:
        assignments.append({
            "title": a.title,
            "due_date": a.due_date.isoformat() if a.due_date is not None else None,
            "assignment_type": "other",
            "notes": a.description,
            "weight_pct": a.weight_pct,
        })

    grading_categories = [
        {"name": c.name, "weight": float(c.weight)}
        for c in output.grading_categories
    ]

    return {
        "assignments": assignments,
        "warnings": list(warnings) if warnings else [],
        "raw_text": raw_text,
        "course_title": output.course_title,
        "grading_categories": grading_categories,
    }
