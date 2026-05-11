"""Note-concept-extraction agent — pulls Title-Case concept names from
a single student note for merge into the user's knowledge graph.

Output is one field (a list of names) so the structured-output schema
stays well under Gemini's complexity threshold (see
docs/attempts/2026-05-03-orchestrator-schema-complexity.md).
"""
from __future__ import annotations

import hashlib

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from agents._providers import model_for
from agents.deps import SaplingDeps


class NoteConcepts(BaseModel):
    concepts: list[str] = Field(
        default_factory=list,
        description=(
            "Title-Case noun phrases naming the distinct concepts the "
            "note covers. 0–15 entries. No assignment titles, page "
            "numbers, or administrative items."
        ),
    )


_PROMPT = (
    "You are extracting concept labels from a single student's note. "
    "Return up to 15 distinct Title-Case noun phrases (e.g. 'Linear "
    "Regression', 'Calvin Cycle'). Exclude assignment titles, week "
    "labels, problem numbers, and administrative items. If the note is "
    "empty or has no clear concepts, return an empty list."
)
_PROMPT_HASH = hashlib.sha256(_PROMPT.encode("utf-8")).hexdigest()[:12]


note_concepts_agent = Agent[SaplingDeps, NoteConcepts](
    model=model_for("note_concepts"),
    deps_type=SaplingDeps,
    output_type=NoteConcepts,
    system_prompt=_PROMPT,
    metadata={"prompt_version": _PROMPT_HASH, "agent": "note_concepts"},
)
