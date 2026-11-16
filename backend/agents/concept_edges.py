"""Concept-edges agent: how the concepts of ONE course connect.

Given a course label and the concept names already in a student's graph for
that course, it proposes concept-to-concept edges. The knowledge graph's
course-centred radial layout (frontend `lib/graph/radialLayout.ts`, #803)
puts a concept one ring further out per directed edge leading into it, so
these edges are what give a course its shape: without them every concept
sits on the inner circle.

Only `prerequisite` / `builds_on` (directed, source = the foundation, target =
the concept that needs it) and `related` (undirected, drawn dashed) are asked
for. `part_of` is deliberately left out: the seed packs write it part→whole,
which the layout would draw with the whole OUTSIDE its parts.

The model's answer is a proposal. `services/concept_edges.py::sanitize_edges`
is what makes it safe to write — exact-name matching, no self-loops, no
cycles, an in-degree cap, transitive reduction — because Claude's JSON mode
enforces none of that (CLAUDE.md "Structured-output bounds are local").
Tool-less: the concept set is passed in the message.
"""

from __future__ import annotations

import hashlib
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_ai import Agent

from agents._bounded import clip_list
from agents._providers import model_for
from agents.deps import SaplingDeps

MAX_EDGES = 400


class ConceptEdge(BaseModel):
    source: str = Field(description="Exact concept name from the list: the foundation.")
    target: str = Field(description="Exact concept name from the list: the concept that needs the source.")
    relationship_type: Literal["prerequisite", "builds_on", "related"] = Field(
        description=(
            "prerequisite: source must be understood before target. "
            "builds_on: target extends or applies source. "
            "related: closely tied, neither depends on the other."
        ),
    )
    strength: float = Field(
        default=0.6,
        description="0.0-1.0: how direct and essential the link is.",
    )

    @field_validator("strength", mode="before")
    @classmethod
    def _clamp_strength(cls, v):
        # Claude's strict JSON mode cannot enforce minimum/maximum (CLAUDE.md),
        # so clamp locally instead of burning an output retry.
        try:
            return max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            return 0.6


class ConceptEdges(BaseModel):
    edges: Annotated[list[ConceptEdge], clip_list(MAX_EDGES, "concept_edges.edges")] = Field(
        default_factory=list,
        max_length=MAX_EDGES,
        description="Edges between concepts of this course. Empty if none are justified.",
    )


_SYSTEM_PROMPT = (
    "You map how the concepts of one university course depend on each other, "
    "for a student's knowledge graph. You get the course and the exact list of "
    "concepts in the student's graph for it.\n\n"
    "Return edges between those concepts:\n"
    "- prerequisite: the source must be understood before the target makes sense.\n"
    "- builds_on: the target extends, generalises or applies the source.\n"
    "- related: the two are closely tied but neither depends on the other. Use "
    "sparingly.\n\n"
    "Rules:\n"
    "- Directed edges always point from the more foundational concept (source) "
    "to the more advanced one (target).\n"
    "- Use concept names EXACTLY as given. Never invent a concept.\n"
    "- Only DIRECT dependencies: if A leads to B and B leads to C, do not also "
    "add A to C.\n"
    "- Give each concept at most two incoming prerequisite/builds_on edges: the "
    "most direct foundations.\n"
    "- Foundational and introductory concepts get no incoming edges; a course "
    "usually has several of them. Most other concepts have one or two.\n"
    "- No cycles.\n"
    "- A concept that is unrelated to the rest (an administrative item, a "
    "stray label) gets no edges.\n"
    "- strength: 0.9 for an essential, direct dependency; 0.5 for a useful but "
    "looser one."
)
_PROMPT_HASH = hashlib.sha256(_SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12]


concept_edges_agent = Agent[SaplingDeps, ConceptEdges](
    model=model_for("concept_edges"),
    deps_type=SaplingDeps,
    output_type=ConceptEdges,
    # Tool-less structured agent: `retries=` is the output-validation budget
    # (agents/__init__.py validation-retry policy).
    retries=2,
    system_prompt=_SYSTEM_PROMPT,
    metadata={"prompt_version": _PROMPT_HASH, "agent": "concept_edges"},
)
