"""Study-guide generation agent.

Replaces the inline ``call_gemini_json`` call in routes/study_guide.py. The
typed output mirrors the JSON contract the frontend already consumes
(``exam / due_date / overview / topics[]``), so the route can ``model_dump()``
the result straight into ``study_guides.content`` with no shape change.
"""

from __future__ import annotations

import hashlib

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from agents._providers import model_for
from agents.deps import SaplingDeps


class Topic(BaseModel):
    """One study-guide topic."""

    name: str = Field(description="Topic name.")
    importance: str = Field(
        description="One sentence explaining why this topic matters for the exam.",
    )
    concepts: list[str] = Field(
        description="3-5 surface-level concept bullet points the student should understand.",
    )


class StudyGuide(BaseModel):
    """Typed study guide. Serializes to the legacy JSON contract via model_dump()."""

    exam: str = Field(description="The exam title.")
    due_date: str = Field(description="The exam due date, YYYY-MM-DD.")
    overview: str = Field(
        description="2-3 sentence overview of what this exam covers and how to approach it.",
    )
    topics: list[Topic] = Field(description="The topics that make up the study guide.")


_SYSTEM_PROMPT = (
    "You are a study guide generator for a student exam-prep tool. Given an "
    "exam and the student's course material, break the material into clear "
    "topics. For each topic provide a topic name, 3-5 surface-level concept "
    "bullet points the student should understand, and one sentence explaining "
    "why the topic matters for the exam. Also produce a 2-3 sentence overview "
    "of what the exam covers and how to approach it. Stay grounded in the "
    "provided material; do not invent topics the material does not support. "
    "Echo the exam title and due date you are given."
)
_PROMPT_HASH = hashlib.sha256(_SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12]


study_guide_agent = Agent[SaplingDeps, StudyGuide](
    model=model_for("study_guide"),
    deps_type=SaplingDeps,
    output_type=StudyGuide,
    system_prompt=_SYSTEM_PROMPT,
    metadata={"prompt_version": _PROMPT_HASH, "agent": "study_guide"},
)
