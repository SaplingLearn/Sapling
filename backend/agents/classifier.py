"""Document classifier agent.

Replaces the classification step previously handled inline in
routes/documents.py via gemini_service.call_gemini_json. Output is a
typed Pydantic model so downstream code branches on .category and
.is_syllabus instead of re-parsing JSON strings.
"""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from agents._providers import model_for
from agents.deps import SaplingDeps


# Mirrors VALID_CATEGORIES in routes/documents.py:33. Keep in sync.
DocumentCategory = Literal[
    "syllabus",
    "lecture_notes",
    "slides",
    "reading",
    "assignment",
    "study_guide",
    "other",
]


class DocumentClassification(BaseModel):
    """Typed output for the classifier agent."""

    category: DocumentCategory = Field(
        description="The document's primary type."
    )
    is_syllabus: bool = Field(
        description=(
            "True if this document defines a course schedule, deliverables, "
            "or grading policy. Often correlates with category='syllabus' "
            "but a course outline embedded in another document also counts."
        )
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Self-reported confidence 0.0-1.0. Used for downstream routing "
            "only; do not use as a hard gate."
        ),
    )
    rationale: str = Field(
        max_length=400,
        description=(
            "One or two sentences explaining the classification. Helps "
            "debugging when the category is wrong."
        ),
    )


# Content-addressed prompt version: a 12-char sha256 prefix of the system
# prompt body. Surfaced on every run via Agent(metadata=...) so a span in
# Logfire can be matched back to the exact prompt body via `git log -S`.
_SYSTEM_PROMPT = (
    "You classify student-uploaded documents into one of seven "
    "categories so the backend can route them correctly: syllabus -> "
    "assignment extraction, assignment/syllabus -> graph concept "
    "population, etc.\n\n"
    "Categories:\n"
    "- syllabus: defines a course's schedule, deliverables, weekly "
    "topics, or grading policy.\n"
    "- lecture_notes: instructor or student notes from a lecture.\n"
    "- slides: presentation slides (deck-style, often sparse text).\n"
    "- reading: textbook chapter, paper, or assigned reading.\n"
    "- assignment: homework, problem set, lab, or project handout.\n"
    "- study_guide: exam-prep or review document organized by topic.\n"
    "- other: anything that does not fit the categories above.\n\n"
    "Set is_syllabus=True whenever the document defines course "
    "structure (schedule, deliverables, grading policy), even if the "
    "primary category is something else. A course outline embedded in "
    "week-1 lecture notes is is_syllabus=True with "
    "category=lecture_notes.\n\n"
    "confidence is your self-reported certainty in [0, 1]. rationale "
    "is one or two sentences naming the signals you used (e.g., "
    "'weekly schedule and grading rubric present', 'numbered problem "
    "sets throughout')."
)
_PROMPT_HASH = hashlib.sha256(_SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12]


classifier_agent = Agent[SaplingDeps, DocumentClassification](
    model=model_for("classifier"),
    deps_type=SaplingDeps,
    output_type=DocumentClassification,
    system_prompt=_SYSTEM_PROMPT,
    metadata={"prompt_version": _PROMPT_HASH, "agent": "classifier"},
)
