"""Concept extraction agent.

Extracts the key concepts from document text into a typed list.
Downstream consumers: graph_service.apply_graph_update (Prompt 11
registers this as a tool) and the achievements pipeline.
"""

from __future__ import annotations

import hashlib

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from agents._providers import model_for
from agents.deps import SaplingDeps


class Concept(BaseModel):
    name: str = Field(max_length=120, description="Title Case noun phrase.")
    description: str = Field(
        max_length=400,
        description="1-2 sentences in the document's context.",
    )
    importance: float = Field(
        ge=0.0, le=1.0,
        description="Centrality to the document; for ranking, not a gate.",
    )


class ConceptList(BaseModel):
    concepts: list[Concept] = Field(
        min_length=1, max_length=30,
        description="Extracted concepts, ordered by importance descending.",
    )


# Content-addressed prompt version: a 12-char sha256 prefix of the system
# prompt body. Surfaced on every run via Agent(metadata=...).
_SYSTEM_PROMPT = (
    "You extract key concepts from a student document. Each concept "
    "becomes a node in the student's knowledge graph and must read "
    "as a standalone topic.\n\n"
    "- name: short Title Case noun phrase ('Linear Regression', "
    "'Big-O Analysis'). Never a problem number, week label, or "
    "administrative item.\n"
    "- description: 1-2 sentences in the document's context.\n"
    "- importance in [0, 1]; order the list by importance desc.\n"
    "- 1-30 concepts. Prefer 4-12 for lectures/readings/study "
    "guides, up to ~15 for whole-course syllabi, 1-8 for narrow "
    "assignments."
)
_PROMPT_HASH = hashlib.sha256(_SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12]


concept_extraction_agent = Agent[SaplingDeps, ConceptList](
    model=model_for("concepts"),
    deps_type=SaplingDeps,
    output_type=ConceptList,
    system_prompt=_SYSTEM_PROMPT,
    metadata={"prompt_version": _PROMPT_HASH, "agent": "concept_extraction"},
)
