"""Comprehensive study-notes agent.

Generates the full, section-by-section notes that seed a document's
`summary_docs` row (the editable document students study from in the
Library). Deliberately distinct from `agents/summary.py`'s `summary_agent`:
that agent produces a short card-preview abstract for the Library grid and
search, never the thing students actually read — this agent produces notes
thorough enough that a student could learn the material from them alone,
without re-reading the source (e.g. lecture slides).
"""

from __future__ import annotations

import hashlib

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from agents._providers import model_for
from agents.deps import SaplingDeps


class NotesSection(BaseModel):
    """One section of the comprehensive notes. The list of sections is kept
    FLAT (no nested sub-section lists) to stay within Gemini's structured-
    output budget (see tests/test_agent_output_schemas.py) — `heading_level`
    expresses outline depth without adding a nesting level: a 3 immediately
    follows the 2 it belongs under, in document order."""

    heading: str = Field(description="Short section title naming the topic.")
    heading_level: int = Field(
        description=(
            "2 for a top-level topic heading, 3 for a subheading nested "
            "under the most recent level-2 heading. Use 3 to break a large "
            "topic into named sub-parts; use 2 for each new top-level topic."
        ),
    )
    body: str = Field(
        description=(
            "The full notes for this section: one or more paragraphs, "
            "separated by a blank line, in plain prose with no markdown, "
            "math notation, or fenced blocks. Thorough enough to study "
            "from directly — definitions, explanations, examples, and "
            "relationships between ideas, not just a one-line summary."
        ),
    )


class ComprehensiveNotes(BaseModel):
    """Typed output: the full set of study notes for one document."""

    sections: list[NotesSection] = Field(
        min_length=1,
        description="Notes broken into topic sections, in the order the source presents them.",
    )


_SYSTEM_PROMPT = (
    "You are writing comprehensive study notes from a student's uploaded "
    "document (e.g. lecture slides, a reading, a problem set) so the "
    "student can learn everything they need from the notes alone, without "
    "going back to the source.\n\n"
    "This is NOT a summary. Do not compress the material down to a few "
    "sentences or a handful of bullet points. Cover every topic, "
    "definition, explanation, example, formula, and relationship the "
    "source actually presents, in the depth the source presents it. If "
    "the source is long or covers many topics, the notes should be "
    "correspondingly long and cover all of them — do not truncate or pick "
    "only the 'most important' parts.\n\n"
    "Break the material into clearly titled sections, one per topic, in "
    "the order the source presents them. Give each section a heading_level: "
    "2 for a new top-level topic, 3 for a subheading that breaks a large "
    "topic into named sub-parts (a 3 must immediately follow the 2 it "
    "belongs under). Each section's body is plain prose paragraphs (no "
    "markdown, math notation, or fenced blocks), thorough enough that "
    "studying the notes alone would prepare the student to understand "
    "that topic. Stay grounded in the source: do not invent facts it does "
    "not state. If the document is sparse or near-empty, produce a single "
    "level-2 section that says so rather than padding with invented "
    "content."
)
_PROMPT_HASH = hashlib.sha256(_SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12]


document_notes_agent = Agent[SaplingDeps, ComprehensiveNotes](
    model=model_for("document_notes"),
    deps_type=SaplingDeps,
    output_type=ComprehensiveNotes,
    # #153: bounded output-validation retry budget for this idempotent
    # generation task. Tool-less agent, so `retries=` IS the output budget
    # (see the validation-retry policy note in agents/__init__.py).
    retries=2,
    system_prompt=_SYSTEM_PROMPT,
    metadata={"prompt_version": _PROMPT_HASH, "agent": "document_notes"},
)
