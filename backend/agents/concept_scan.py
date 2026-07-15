"""Concept-scan agent.

Replaces routes/documents.py::_extend_course_concepts' call_gemini_json
call. Given a course label, the concepts already in the student's graph,
and optionally a document's summary/notes, it returns the NEW concepts to
add — names only, deduplicated against the existing set, possibly empty.

Names-only output (list[str]) matches what the /scan-concepts graph write
consumes; descriptions/importance would be discarded (see the design spec).
Tool-less: the existing-concepts set is a deterministic query the route
already runs and passes in the message — the model has nothing to decide
about fetching it.
"""

from __future__ import annotations

import hashlib

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from agents._providers import model_for
from agents.deps import SaplingDeps


class NewConcepts(BaseModel):
    """Typed output: new concept names to add to the course graph."""

    concepts: list[str] = Field(
        default_factory=list,
        max_length=15,
        description=(
            "New concept names not already in the course graph. Empty when "
            "the existing set already covers the material."
        ),
    )


_SYSTEM_PROMPT = (
    "You curate the concept set for a student's course knowledge graph. "
    "You are given the course label, the concepts already in the graph, "
    "and optionally a document's title, summary, and already-extracted "
    "concepts.\n\n"
    "Return between 0 and 15 NEW concepts that belong in this course's "
    "graph but are not already in the existing list.\n"
    "- If the existing set already covers the relevant material, return an "
    "empty list.\n"
    "- Each concept is a short Title Case noun phrase (e.g. 'Linear "
    "Regression', 'Big-O Analysis').\n"
    "- Do NOT repeat or paraphrase any existing concept.\n"
    "- No assignment titles, week labels, page numbers, problem numbers, "
    "or administrative items."
)
_PROMPT_HASH = hashlib.sha256(_SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12]


concept_scan_agent = Agent[SaplingDeps, NewConcepts](
    model=model_for("concept_scan"),
    deps_type=SaplingDeps,
    output_type=NewConcepts,
    system_prompt=_SYSTEM_PROMPT,
    metadata={"prompt_version": _PROMPT_HASH, "agent": "concept_scan"},
)
