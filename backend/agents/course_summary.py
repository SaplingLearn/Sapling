"""Course (class) summary agent.

Replaces the inline `call_gemini` in `services/course_context_service.py`.
Produces the instructor-facing 2-3 paragraph summary of a class's mastery
picture. Toolless and user-agnostic: the caller passes the aggregated metrics
in the user message.
"""

from __future__ import annotations

import hashlib

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from agents._providers import model_for


class CourseSummary(BaseModel):
    summary: str = Field(
        description="2-3 paragraph instructor-facing summary of class performance.",
    )


_SYSTEM_PROMPT = (
    "You are an expert education analyst summarizing a course for instructors. "
    "Given the class's average mastery, top struggling concepts, and top "
    "mastered concepts, write a concise 2-3 paragraph summary that: describes "
    "overall class performance; highlights specific areas where students are "
    "struggling and may need intervention; notes areas where students excel; "
    "and gives actionable recommendations for the instructor. Write in a "
    "professional but approachable tone — specific and data-driven. Do not "
    "invent concepts or numbers beyond what you are given."
)
_PROMPT_HASH = hashlib.sha256(_SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12]


course_summary_agent = Agent[None, CourseSummary](
    model=model_for("course_summary"),
    output_type=CourseSummary,
    system_prompt=_SYSTEM_PROMPT,
    metadata={"prompt_version": _PROMPT_HASH, "agent": "course_summary"},
)
