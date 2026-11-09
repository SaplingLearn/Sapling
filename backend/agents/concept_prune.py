"""Concept-prune agent: which graph "concepts" are not concepts of the course.

Syllabus uploads put course logistics into students' graphs ("October 4
Homework Deadline", "Makeup Exam Policy", "Office Hours"), and a document
filed under the wrong course brings in concepts from another subject. Both
sit unlinked on the course's inner ring. Given one course's concept names,
this returns the ones to remove, each with a kind and a short reason.

Conservative by design: a borderline subject concept stays. The caller
(`scripts/prune_junk_concepts.py`) only acts on exact names from the list,
and only DELETES `logistics`: `off_topic` is reported for a human, because a
whole set of "off-topic" concepts usually means the course is mapped wrong,
not that the student's work is junk.
Tool-less: the concept set is passed in the message.
"""

from __future__ import annotations

import hashlib
from typing import Annotated, Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from agents._bounded import clip_list, clip_prose
from agents._providers import model_for
from agents.deps import SaplingDeps


class JunkConcept(BaseModel):
    name: str = Field(description="Exact concept name from the list.")
    kind: Literal["logistics", "off_topic"] = Field(
        description=(
            "logistics: course administration, not subject matter. "
            "off_topic: real subject matter from a different discipline than this course."
        ),
    )
    reason: Annotated[str, clip_prose(120, "concept_prune.reason")] = Field(
        max_length=120, description="A few words on why.",
    )


class JunkConcepts(BaseModel):
    junk: Annotated[list[JunkConcept], clip_list(200, "concept_prune.junk")] = Field(
        default_factory=list, max_length=200,
        description="Entries to remove. Empty when every entry is a real concept of the course.",
    )


_SYSTEM_PROMPT = (
    "You clean a student's knowledge graph for one university course. Every "
    "entry should be a concept the student learns in that course. You get the "
    "course and the exact list of entries.\n\n"
    "Return the entries to remove:\n"
    "- logistics: course administration rather than subject matter: the course's "
    "own title, deadlines, due dates, exam events and exam rules, grading, "
    "schedules, sections, office hours, staff, textbooks and required materials, "
    "policies (academic integrity, makeup, attendance), accommodations, support "
    "services, learning-outcome boilerplate.\n"
    "- off_topic: real subject matter that clearly belongs to a different "
    "discipline than this course (for example molecular biology in a physics "
    "course).\n\n"
    "Keep everything else, including:\n"
    "- a specific work the course studies (a book, essay, film or case that is "
    "read and analysed); only a generic materials list or textbook entry is "
    "logistics;\n"
    "- a genre, method or skill an assignment teaches (e.g. 'Literacy Narrative'); "
    "only the assignment's administration (a due date, a submission, a "
    "portfolio requirement) is logistics.\n"
    "When unsure, keep it: a broad or introductory "
    "subject concept (e.g. 'Scarcity' in economics, 'Thesis Statement' in "
    "writing) is a real concept. Skills and topics a course teaches are "
    "concepts even when they sound general. Use names exactly as given."
)
_PROMPT_HASH = hashlib.sha256(_SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12]


concept_prune_agent = Agent[SaplingDeps, JunkConcepts](
    model=model_for("concept_prune"),
    deps_type=SaplingDeps,
    output_type=JunkConcepts,
    retries=2,
    system_prompt=_SYSTEM_PROMPT,
    metadata={"prompt_version": _PROMPT_HASH, "agent": "concept_prune"},
)
