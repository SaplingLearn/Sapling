"""Syllabus extraction agent.

Parses a syllabus document into structured assignments and schedule
entries. Replaces (in Prompt 11) the duplicated syllabus parsing in
routes/documents.py and services/calendar_service.py.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field
from pydantic_ai import Agent, PromptedOutput

from agents._providers import model_for
from agents.deps import SaplingDeps


class SyllabusAssignment(BaseModel):
    title: str = Field(max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    due_date: date | None = Field(
        default=None,
        description="ONLY a concrete calendar date. Null for relative "
                    "terms ('Week 4', 'before midterm') — do not invent.",
    )
    weight_pct: float | None = Field(default=None, ge=0.0, le=100.0)


class GradingCategory(BaseModel):
    """A grading-weight bucket from the syllabus (e.g. 'Exams: 40%')."""

    name: str = Field(max_length=100)
    weight: float = Field(
        ge=0.0,
        description="Stated weight verbatim from the syllabus — points or "
                    "percent, do NOT normalize.",
    )


class SyllabusAssignments(BaseModel):
    course_title: str | None = Field(default=None, max_length=300)
    instructor: str | None = Field(default=None, max_length=200)
    assignments: list[SyllabusAssignment] = Field(max_length=50)
    grading_categories: list[GradingCategory] = Field(
        default_factory=list,
        max_length=20,
        description="Top-level grading-weight buckets (e.g. Exams 40%, "
                    "Homework 30%). Empty if the syllabus does not state "
                    "a weight breakdown.",
    )


# Gemini's native structured-output API rejects this schema with
# "too many states for serving" because of the date format on
# due_date plus the nested assignment list. PromptedOutput keeps the
# Pydantic types/constraints (date parsing, ge/le on weight_pct) and
# moves schema enforcement into the prompt + local validation.
syllabus_extraction_agent = Agent[SaplingDeps, SyllabusAssignments](
    model=model_for("syllabus"),
    deps_type=SaplingDeps,
    output_type=PromptedOutput(SyllabusAssignments),
    system_prompt=(
        "Parse a course syllabus into structured deliverables.\n\n"
        "Extract every named deliverable with a deadline (homework, "
        "exams, projects, readings, quizzes). title <80 chars. "
        "weight_pct is the stated grade weight (e.g. 'Final 30%' -> "
        "30.0) or null. description: one short sentence of context, "
        "or null.\n\n"
        "due_date: set ONLY when the syllabus gives a concrete "
        "calendar date. For RELATIVE terms ('Week 3', 'before "
        "midterm', 'end of unit 2'), leave null. Do NOT invent dates "
        "— that's a downstream concern.\n\n"
        "grading_categories: extract the top-level grading-weight "
        "buckets stated by the syllabus (e.g. 'Exams 40%', "
        "'Homework 30%', 'Participation 10%'). weight passes through "
        "verbatim — do not normalize percent vs points. Empty list "
        "is valid when the syllabus does not state a breakdown.\n\n"
        "Fill course_title and instructor if shown at the top of the "
        "syllabus, else null. Empty assignments list is valid."
    ),
)
