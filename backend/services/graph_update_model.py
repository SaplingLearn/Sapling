"""The typed input of ``graph_service.apply_graph_update`` (#118).

``apply_graph_update`` is the knowledge-graph mutation chokepoint, and its
callers (the document pipeline, the concept scan, quiz submit, the tutor's
graph tools, ``add_node``, the learning loop's graders) all hand it a loosely
shaped dict::

    {"new_nodes":     [{"concept_name", "course_id"?, "initial_mastery"?}, ...],
     "new_edges":     [{"source", "target", "strength"?, "relationship_type"?}, ...],
     "evidence":      [learning.evidence.Evidence | its dict, ...]}

Graded evidence is the only thing that moves a belief (learning-loop PKG-14b,
spec §11.2): the flat ``updated_nodes`` delta is gone, and
``apply_graph_update`` refuses a dict that still names it. The evidence items
are validated by ``apply_graph_update`` itself (each re-validated as an
``Evidence``, before any read or write), so here they ride as given.

:class:`GraphUpdate` is that shape, validated once at the top of the function.
It is deliberately exactly as lenient as the dict-walking code it replaced, so
no caller changes and no write changes:

* unknown keys are ignored (``extra="ignore"``) at every level;
* a missing list is an empty list;
* every per-field normalisation is the expression the old loop applied
  (whitespace-collapsed node/edge names, ``_coerce_unit`` for
  ``initial_mastery``, the ``float(x or default)`` with a TypeError/ValueError
  fallback for ``strength``), so an entry the old code skipped (blank name) is
  still skipped by the consumer, and a value it defaulted is defaulted
  identically;
* ``course_id`` and ``relationship_type`` are written to the DB verbatim,
  exactly as before — the old code never checked them, so neither does the
  model (``Any``: a value the old code would have written is still written,
  rather than becoming a new validation failure).

Input the old code crashed on (a list that is ``None``, an entry that is not a
mapping, a truthy non-string name) still raises — but now while validating,
i.e. BEFORE the first write, instead of part-way through the batch. A truthy
non-string name raises the same ``AttributeError`` it always did (pydantic
lets non-``ValueError`` exceptions from a validator propagate); the structural
cases raise ``pydantic.ValidationError``.

The agent tools in ``agents/tools/graph.py`` keep their OWN input models: their
JSON schema (field descriptions included) is what the model sees, and the eval
cassettes depend on it. This model is internal and never shown to an LLM.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


def _coerce_unit(value, default: float = 0.0) -> float:
    """Coerce an LLM-emitted scalar into a [0,1] float, tolerant of None/strings."""
    try:
        f = float(value if value is not None else default)
    except (TypeError, ValueError):
        f = default
    return max(0.0, min(1.0, f))


def _collapse_ws(value) -> str:
    """``" ".join((value or "").split())`` — the node/edge-name normalisation."""
    return " ".join((value or "").split())


def _float_or(value, default: float) -> float:
    """``float(value or default)``, falling back to ``default`` on junk."""
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return default


class _Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore")


class NewNode(_Lenient):
    """A concept to create (or merge into its existing row)."""

    #: Whitespace-collapsed; "" means "skip this entry".
    concept_name: str = ""
    #: Used only when the call has no ``course_id`` of its own. Written verbatim.
    course_id: Any = None
    #: Clamped to [0, 1]; None/junk → 0.0.
    initial_mastery: float = 0.0

    @field_validator("concept_name", mode="before")
    @classmethod
    def _name(cls, v):
        return _collapse_ws(v)

    @field_validator("initial_mastery", mode="before")
    @classmethod
    def _mastery(cls, v):
        return _coerce_unit(v, 0.0)


class NewEdge(_Lenient):
    """A relationship between two concepts, resolved by name."""

    #: Whitespace-collapsed; either blank means "skip".
    source: str = ""
    target: str = ""
    #: ``float(x or 0.5)`` (so 0 → 0.5, as before), junk → 0.5, clamped to [0, 1].
    strength: float = 0.5
    #: Written verbatim.
    relationship_type: Any = "related"

    @field_validator("source", "target", mode="before")
    @classmethod
    def _endpoint(cls, v):
        return _collapse_ws(v)

    @field_validator("strength", mode="before")
    @classmethod
    def _strength(cls, v):
        return max(0.0, min(1.0, _float_or(v, 0.5)))


class GraphUpdate(_Lenient):
    """One batch of knowledge-graph changes for :func:`apply_graph_update`."""

    new_nodes: list[NewNode] = []
    new_edges: list[NewEdge] = []
    #: Graded evidence (learning-loop PKG-03): ``Evidence`` instances or their
    #: dicts, validated by ``apply_graph_update`` before any read or write.
    #: None/absent is none (``graph_update.get("evidence") or []``, as before).
    evidence: list[Any] = []

    @field_validator("evidence", mode="before")
    @classmethod
    def _evidence(cls, v):
        return v or []

    @classmethod
    def coerce(cls, value: GraphUpdate | dict) -> GraphUpdate:
        """Accept either the model or the legacy dict shape."""
        if isinstance(value, cls):
            return value
        return cls.model_validate(value)
