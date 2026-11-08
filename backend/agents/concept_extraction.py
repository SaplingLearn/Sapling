"""Concept extraction agent.

Extracts the key concepts from document text into a typed list, plus the
direct prerequisite relations between them (spec §13 A118). Downstream
consumers: graph_service.apply_graph_update (the upload routes merge the
concepts as nodes; services/concept_prereqs.py validates the relations and,
behind the `upload_prereq_edges` flag, writes them as prerequisite edges) and
the achievements pipeline.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Annotated

from pydantic import BaseModel, Field, field_validator
from pydantic_ai import Agent

from agents._bounded import clip_list, clip_prose
from agents._providers import model_for
from agents.deps import SaplingDeps

#: A118: how many raw relations the model may send — a payload bound, clipped
#: locally like every list cap (CLAUDE.md "Structured-output bounds are local
#: on Claude"). What one document may WRITE is the smaller
#: services/concept_prereqs.py::MAX_PREREQ_EDGES_PER_DOCUMENT, applied after
#: the relations are validated.
MAX_PREREQUISITE_RELATIONS = 60

#: A118: how many of the course's existing concept names the user message
#: lists as possible prerequisite endpoints — a prompt-size bound. The reader
#: (services/concept_prereqs.py::course_concept_names) supplies the most
#: recently created ones.
EXISTING_CONCEPTS_PROMPT_MAX = 60

_NAME_MAX = 120  # Concept.name's cap; a listed existing name is clipped to it


class Concept(BaseModel):
    name: str = Field(max_length=_NAME_MAX, description="Title Case noun phrase.")
    description: Annotated[str, clip_prose(400, "concept.description")] = Field(
        max_length=400,
        description="1-2 sentences in the document's context.",
    )
    importance: float = Field(
        ge=0.0, le=1.0,
        description="Centrality to the document; for ranking, not a gate.",
    )


class PrerequisiteRelation(BaseModel):
    """One direct prerequisite relation, by concept NAME (A118).

    Deliberately unconstrained: an endpoint is resolved, validated and bounded
    in code (services/concept_prereqs.py::resolve_prerequisites), where an
    unknown or over-long name is dropped and logged. A length or membership
    constraint here would turn a bad relation — optional enrichment — into an
    output retry, or a failed upload."""

    prerequisite: str = Field(
        description="Exact name of the concept a student must understand first.",
    )
    dependent: str = Field(
        description="Exact name of the concept that builds on it.",
    )


class ConceptList(BaseModel):
    concepts: Annotated[list[Concept], clip_list(30, "concepts")] = Field(
        min_length=1, max_length=30,
        description="Extracted concepts, ordered by importance descending.",
    )
    # A118. A default, not required: a narrow document can have no dependency
    # worth naming, and every recorded eval cassette predates the field.
    prerequisites: Annotated[
        list[PrerequisiteRelation],
        clip_list(MAX_PREREQUISITE_RELATIONS, "concepts.prerequisites"),
    ] = Field(
        default_factory=list,
        max_length=MAX_PREREQUISITE_RELATIONS,
        description=(
            "Direct prerequisite relations, by exact concept name. Empty when "
            "no dependency is clear."
        ),
    )

    # The order is a contract (callers take the head of the list), so it is
    # made true here rather than trusted to the model: Gemini happened to
    # emit importance-descending lists, Claude Haiku 5.5 does not (the first
    # Claude eval recording ordered 7 of 15 cases differently, ADR 0030).
    # Stable, so equal-importance concepts keep the model's order.
    @field_validator("concepts", mode="after")
    @classmethod
    def _order_by_importance(cls, concepts: list[Concept]) -> list[Concept]:
        return sorted(concepts, key=lambda c: c.importance, reverse=True)


def build_message(text: str, existing_concepts: Sequence[str] = ()) -> str:
    """The agent's user message (A118).

    With no existing course concepts it is the document text alone —
    byte-identical to the pre-A118 input. Otherwise the course's concept names
    come first, so a prerequisite relation can attach this document to
    earlier material: whitespace-collapsed, clipped to a concept name's
    length, deduplicated case-insensitively, the first
    EXISTING_CONCEPTS_PROMPT_MAX in the caller's order (most recent first),
    then listed alphabetically.
    """
    names: dict[str, str] = {}
    for raw in existing_concepts:
        name = " ".join(str(raw or "").split())[:_NAME_MAX]
        if name:
            names.setdefault(name.casefold(), name)
        if len(names) >= EXISTING_CONCEPTS_PROMPT_MAX:
            break
    if not names:
        return text
    listing = "\n".join(f"- {name}" for name in sorted(names.values(), key=str.casefold))
    return (
        "Concepts already in this course's graph. A prerequisite relation may "
        "name one of these exactly; still extract this document's own key "
        "concepts as usual, whether or not they appear here:\n"
        f"{listing}\n\nDocument:\n{text}"
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
    "assignments.\n"
    "- prerequisites: direct links {prerequisite, dependent} where a "
    "student must understand the prerequisite before the dependent "
    "makes sense. Use exact names from your concept list, or from the "
    "course's existing concepts when the message lists them; at least "
    "one side must be one of your concepts. Direct links only (given "
    "A->B and B->C, omit A->C); never a cycle; [] when no dependency "
    "is clear."
)
_PROMPT_HASH = hashlib.sha256(_SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12]


concept_extraction_agent = Agent[SaplingDeps, ConceptList](
    model=model_for("concepts"),
    deps_type=SaplingDeps,
    output_type=ConceptList,
    # #153: bounded output-validation retry budget for this idempotent
    # generation task. Tool-less agent, so `retries=` IS the output budget
    # (see the validation-retry policy note in agents/__init__.py).
    retries=2,
    system_prompt=_SYSTEM_PROMPT,
    metadata={"prompt_version": _PROMPT_HASH, "agent": "concept_extraction"},
)
