"""Concept-describe agent.

Given a concept name and its course context, returns ONE concise,
student-facing sentence explaining what the concept is. Backs the knowledge-
map rail's "Focused concept" blurb for concepts that don't already carry a
stored description (e.g. ones the student just added by hand).

Tool-less: the concept name and course label are handed in via the message,
so the model has nothing to fetch — it only writes from what it knows.
"""

from __future__ import annotations

import hashlib

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from agents._providers import model_for
from agents.deps import SaplingDeps


class ConceptDescription(BaseModel):
    """Typed output: a single short description sentence."""

    description: str = Field(
        max_length=240,
        description=(
            "One concise, plain-language sentence explaining what the concept "
            "is. No preamble, no markdown, no trailing whitespace."
        ),
    )


_SYSTEM_PROMPT = (
    "You explain academic concepts to students in one sentence. You are given "
    "a concept name and, when available, the course it belongs to.\n\n"
    "Write exactly ONE concise, plain-language sentence (roughly 12-28 words) "
    "describing what the concept is and why it matters.\n"
    "- Write for a student who is about to study it — clear, concrete, no "
    "jargon they wouldn't already know.\n"
    "- No preamble ('This concept is…'), no markdown, no lists, no quotes.\n"
    "- If the concept name is ambiguous, interpret it in the context of the "
    "given course."
)
_PROMPT_HASH = hashlib.sha256(_SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12]


concept_describe_agent = Agent[SaplingDeps, ConceptDescription](
    model=model_for("concept_describe"),
    deps_type=SaplingDeps,
    output_type=ConceptDescription,
    system_prompt=_SYSTEM_PROMPT,
    metadata={"prompt_version": _PROMPT_HASH, "agent": "concept_describe"},
)


def build_message(concept: str, course_label: str | None) -> str:
    """Compose the single user message handed to the agent."""
    concept = concept.strip()
    if course_label:
        return f"Concept: {concept}\nCourse: {course_label.strip()}"
    return f"Concept: {concept}"
