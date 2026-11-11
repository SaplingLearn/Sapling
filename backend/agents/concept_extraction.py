"""Concept extraction agent.

Extracts the key concepts from document text into a typed list.
Downstream consumers: graph_service.apply_graph_update (Prompt 11
registers this as a tool) and the achievements pipeline.

Two variants (spec §13 A118), picked per upload by the `upload_prereq_edges`
flag — resolved ONCE by the upload route
(services/concept_prereqs.py::upload_prereqs_on) and passed down to
`extraction_run_args`:

- off (the default, and wherever no student is known): the agent exactly as
  it was before A118 — the same system prompt, the same output schema
  (`BaseConceptList`, the pre-A118 `ConceptList` field for field) and the bare
  document text. No recorded eval covers anything else, so a flag-off upload
  must send the model byte-identical requests (pinned in
  tests/test_upload_prereq_edges.py).
- on: the same system prompt plus PREREQUISITE_INSTRUCTIONS, the `ConceptList`
  schema with `prerequisites`, and the course's existing concept names in the
  message (`build_message`). services/concept_prereqs.py validates the
  relations and writes them as prerequisite edges.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator
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

#: A118: how many of the course's existing concept names the flag-on message
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


# The flag-off output type: the pre-A118 `ConceptList`, field for field, under
# the same schema title. No docstring on purpose — pydantic-ai sends a model's
# docstring as its schema description, and this schema must stay byte-identical
# to the pre-A118 one (A118; the hash is pinned in
# tests/test_upload_prereq_edges.py). The flag-on `ConceptList` extends it, so
# every consumer reads `.concepts` the same way.
class BaseConceptList(BaseModel):
    model_config = ConfigDict(title="ConceptList")

    concepts: Annotated[list[Concept], clip_list(30, "concepts")] = Field(
        min_length=1, max_length=30,
        description="Extracted concepts, ordered by importance descending.",
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


# One direct prerequisite relation, by concept NAME (A118). Deliberately
# unconstrained: an endpoint is resolved, validated and bounded in code
# (services/concept_prereqs.py::resolve_prerequisites), where an unknown or
# over-long name is dropped and logged. A length or membership constraint here
# would turn a bad relation — optional enrichment — into an output retry, or a
# failed upload. (Comments, not a docstring: the schema carries no internals.)
class PrerequisiteRelation(BaseModel):
    prerequisite: str = Field(
        description="Exact name of the concept a student must understand first.",
    )
    dependent: str = Field(
        description="Exact name of the concept that builds on it.",
    )


# The flag-on output type (A118), and the type the rest of the code names.
# `prerequisites` defaults to [] so both variants' results validate as one, and
# a narrow document can name no dependency.
class ConceptList(BaseConceptList):
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


def build_message(text: str, existing_concepts: Sequence[str] = ()) -> str:
    """The flag-on variant's user message (A118).

    With no existing course concepts it is the document text alone. Otherwise
    the course's concept names come first, so a prerequisite relation can
    attach this document to earlier material: whitespace-collapsed, clipped to
    a concept name's length, deduplicated case-insensitively, the first
    EXISTING_CONCEPTS_PROMPT_MAX in the caller's order (most recent first),
    then listed alphabetically. The flag-off variant never calls this.
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
# prompt body. Surfaced on every run via Agent(metadata=...). Unchanged by
# A118: it is the flag-off variant's prompt, byte for byte.
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

#: A118, flag-on only: sent as run instructions after the system prompt.
PREREQUISITE_INSTRUCTIONS = (
    "Also return prerequisites: direct links {prerequisite, dependent} where "
    "a student must understand the prerequisite before the dependent makes "
    "sense. Use exact names from your concept list, or from the course's "
    "existing concepts when the message lists them; at least one side must "
    "be one of your concepts. Direct links only (given A->B and B->C, omit "
    "A->C); never a cycle; [] when no dependency is clear."
)
_PREREQ_PROMPT_HASH = hashlib.sha256(
    f"{_SYSTEM_PROMPT}\n\n{PREREQUISITE_INSTRUCTIONS}".encode("utf-8")
).hexdigest()[:12]


concept_extraction_agent = Agent[SaplingDeps, BaseConceptList](
    model=model_for("concepts"),
    deps_type=SaplingDeps,
    output_type=BaseConceptList,
    # #153: bounded output-validation retry budget for this idempotent
    # generation task. Tool-less agent, so `retries=` IS the output budget
    # (see the validation-retry policy note in agents/__init__.py).
    retries=2,
    system_prompt=_SYSTEM_PROMPT,
    metadata={"prompt_version": _PROMPT_HASH, "agent": "concept_extraction"},
)


def extraction_run_args(
    text: str, *, prerequisites: bool, existing_concepts: Sequence[str] = (),
) -> dict:
    """`concept_extraction_agent.run(**extraction_run_args(...), deps=...,
    usage_limits=...)`: the per-run arguments of the A118 variant
    `prerequisites` picks — the upload's single resolution of the
    upload_prereq_edges flag, never re-read here. The run's `.output` is a
    `BaseConceptList` off and a `ConceptList` on.

    Off: the document text alone, so the run is exactly the pre-A118 call —
    the agent's own system prompt and output schema, a byte-identical
    request; `existing_concepts` is ignored (callers do not read them). On:
    `build_message`'s course-concepts context, the `ConceptList` schema,
    PREREQUISITE_INSTRUCTIONS after the system prompt, and that prompt's
    version for the run's metadata."""
    if not prerequisites:
        return {"user_prompt": text}
    return {
        "user_prompt": build_message(text, existing_concepts),
        "output_type": ConceptList,
        "instructions": PREREQUISITE_INSTRUCTIONS,
        "metadata": {"prompt_version": _PREREQ_PROMPT_HASH},
    }
