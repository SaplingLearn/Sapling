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


#: Whose document this is, which decides whether it may enter the shared course
#: pool at all (#630). A different question from the uploader's consent: a
#: student can consent to sharing class material and still not be publishing
#: their own answers. Mirrors `services.chunk_visibility.SHAREABILITY_VALUES`,
#: pinned together by tests/test_document_shareability.py.
Shareability = Literal[
    "course_material",
    "personal_notes",
    "completed_work",
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
            "Self-reported confidence 0.0-1.0 in this classification. Below "
            "chunk_visibility.MIN_SHARE_CONFIDENCE the document is not added "
            "to the shared course pool, so this number gates sharing — it is "
            "no longer advisory."
        ),
    )
    shareability: Shareability | None = Field(
        default=None,
        description=(
            "Whose document this is: course_material (produced by or for the "
            "course, fine for any enrolled student to study from), "
            "completed_work (this student's own answers, or anything graded), "
            "or personal_notes (their own private material). Prefer the more "
            "private bucket when a document could be read either way."
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
    "sets throughout').\n\n"
    "shareability says whose document this is, which decides whether "
    "other students in the course may ever see it. Answer it "
    "independently of category — the same category appears in more than "
    "one bucket.\n"
    "- course_material: produced by or for the course, and legitimate "
    "for any enrolled student to study from. Syllabi, lecture notes, "
    "slides, assigned readings, and BLANK assignment handouts (the "
    "questions, not the answers) are all course_material.\n"
    "- completed_work: this student's own attempt or answers. Worked "
    "solutions, filled-in problem sets, submitted essays, anything "
    "carrying a score, a grade or instructor feedback. If the document "
    "shows what a student answered, it is completed_work even when the "
    "questions themselves came from the course.\n"
    "- personal_notes: this student's private material — their own "
    "study notes, plans, reminders, or anything that is neither of the "
    "above.\n"
    "When a document could be read either way, prefer the more private "
    "bucket: sharing a classmate's answers is an academic-integrity "
    "failure, while withholding a handout costs only convenience."
)
_PROMPT_HASH = hashlib.sha256(_SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12]


classifier_agent = Agent[SaplingDeps, DocumentClassification](
    model=model_for("classifier"),
    deps_type=SaplingDeps,
    output_type=DocumentClassification,
    # #153: bounded output-validation retry budget for this idempotent
    # generation task. Tool-less agent, so `retries=` IS the output budget
    # (see the validation-retry policy note in agents/__init__.py).
    retries=2,
    system_prompt=_SYSTEM_PROMPT,
    metadata={"prompt_version": _PROMPT_HASH, "agent": "classifier"},
)
