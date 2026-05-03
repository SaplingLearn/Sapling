"""Syllabus extraction agent.

Parses a syllabus document into structured assignments and schedule
entries. Replaces (in Prompt 11) the duplicated syllabus parsing in
routes/documents.py and services/calendar_service.py.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field
from pydantic_ai import Agent, PromptedOutput
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider

from agents.deps import SaplingDeps
from config import GEMINI_API_KEY


class SyllabusAssignment(BaseModel):
    title: str = Field(max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    due_date: date | None = Field(
        default=None,
        description="ONLY a concrete calendar date. Null for relative "
                    "terms ('Week 4', 'before midterm') — do not invent.",
    )
    weight_pct: float | None = Field(default=None, ge=0.0, le=100.0)


class SyllabusAssignments(BaseModel):
    course_title: str | None = Field(default=None, max_length=300)
    instructor: str | None = Field(default=None, max_length=200)
    assignments: list[SyllabusAssignment] = Field(max_length=50)


_provider = GoogleProvider(api_key=GEMINI_API_KEY or "dummy-key-for-import")

# Gemini's native structured-output API rejects this schema with
# "too many states for serving" because of the date format on
# due_date plus the nested assignment list. PromptedOutput keeps the
# Pydantic types/constraints (date parsing, ge/le on weight_pct) and
# moves schema enforcement into the prompt + local validation.
syllabus_extraction_agent = Agent[SaplingDeps, SyllabusAssignments](
    model=GoogleModel("gemini-2.5-flash", provider=_provider),
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
        "Fill course_title and instructor if shown at the top of the "
        "syllabus, else null. Empty assignments list is valid."
    ),
)
