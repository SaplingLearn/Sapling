"""Graph-update helpers and Pydantic AI tool wrappers.

Two tools are exposed:
- apply_graph_update_tool  — registers new concepts (new_nodes, initial_mastery 0.0)
- update_mastery_tool      — adjusts mastery on existing concepts (updated_nodes + delta)

Both append their payload to ctx.deps.graph_updates so the route can
persist graph_update_json on the assistant message, enabling end_session
to derive concepts_covered correctly for agent-path chats.

What injected text can and cannot do through these tools
--------------------------------------------------------
The tutor's prompt carries text other people wrote: retrieved chunks from
classmates' uploads (class-shared RAG rows), document summaries, note bodies.
Every one of those arrives inside the untrusted envelope, and the system
prompt says a passage is never a reason to call a tool. That is a request to
a model, so the limits that matter are enforced here, in code:

- Whose graph: `user_id` and `course_id` come from `ctx.deps`, never from a
  tool argument (pinned by tests/test_prompt_injection.py), so no passage can
  point a write at another student.
- New concepts: `apply_graph_update_tool` always writes `initial_mastery`
  0.0. Adding a concept never raises anyone's mastery.
- Per call: `ConceptMasteryUpdate.mastery_delta` is bounded to
  [MASTERY_DELTA_MIN, MASTERY_DELTA_MAX] = [-0.1, +0.3]. Out of band fails
  validation (the #153 retry loop hands the error back to the model).
- Per turn: the same band caps the NET delta per concept across every
  `update_mastery_tool` call in one run (and repeats of a concept inside one
  call). Without it a model talked into "set mastery to 1.0" could reach 1.0
  in four +0.3 calls, all individually valid. The excess is dropped, not
  raised: the turn still completes.
- Sizes (M7): at most MAX_CONCEPTS_PER_CALL concepts and
  MAX_MASTERY_UPDATES_PER_CALL mastery updates per call (clipped in model
  order), MAX_NEW_CONCEPTS_PER_TURN new concepts per run, and names of at
  most MAX_CONCEPT_NAME_CHARS characters (longer fails validation, which the
  model sees as a retryable tool error).
- Where a new concept may come from (M7): it must appear, as whole words,
  in the student's message or the turn's assembled/retrieved context
  (`deps.concept_context`, extended by the read tools via
  `allow_concept_text`). Otherwise it is refused with a message the model
  can act on. A run that never sets the context (evals, scripts) is not
  checked.
- Storage: `apply_graph_update` clamps the stored score to [0, 1] in SQL
  (`apply_mastery_delta`, 20261106055333_state_machines_audit.sql).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Literal

import re
import unicodedata

from pydantic import BaseModel, Field, field_validator
from pydantic_ai import RunContext

from agents.deps import SaplingDeps
from services.graph_service import _normalize_concept, apply_graph_update

logger = logging.getLogger(__name__)

# Wire vocabulary (what the model may emit) -> the value that lands in
# `node_mastery_events.event_type`.
#
# Namespaced by PRODUCER because the column has two independent writers and
# no CHECK constraint: this tool, and `routes/quiz.py::submit_quiz` (which
# writes quiz_correct / quiz_partial / quiz_confusion). Both classify "how
# much confidence does this mastery move carry", and a bare `quiz` from the
# tutor — meaning "I quizzed the student mid-conversation" — would be
# indistinguishable in the column from a graded quiz submission, which is a
# different event with a different provenance. Prefixing makes every stored
# value say who wrote it, so the two vocabularies can never be read as one.
#: The per-call AND per-turn mastery band (see the module docstring). Matches
#: the eval band in tests/evals/chat_tutor.py (MASTERY_DELTA_MIN/MAX).
MASTERY_DELTA_MIN = -0.1
MASTERY_DELTA_MAX = 0.3

TUTOR_EVENT_TYPES: dict[str, str] = {
    "interaction": "tutor_interaction",
    "correction": "tutor_correction",
    "quiz": "tutor_quiz",
}


#: M7: the size bounds on the two write tools. Claude's strict JSON mode cannot
#: enforce maxItems/maxLength at decode time (CLAUDE.md "Structured-output
#: bounds are local on Claude"), so they are enforced here: lists are clipped
#: in model order by a before-validator (`_clip`, logged), and an over-long
#: name fails validation, which pydantic-ai hands back to the model as a
#: retryable tool error.
MAX_CONCEPTS_PER_CALL = 5
MAX_NEW_CONCEPTS_PER_TURN = 10
MAX_MASTERY_UPDATES_PER_CALL = 10
MAX_CONCEPT_NAME_CHARS = 80


def _clip(value, limit: int, field_name: str):
    """Keep the first `limit` entries of a raw list input, in model order,
    logging the clip. Anything that is not a list is left for normal
    validation to reject (same pattern as agents/quiz.py)."""
    if isinstance(value, list) and len(value) > limit:
        logger.warning("[graph tools] clipped %s from %d to %d", field_name, len(value), limit)
        return value[:limit]
    return value


def _bounded_name(name: str) -> str:
    if len(" ".join((name or "").split())) > MAX_CONCEPT_NAME_CHARS:
        raise ValueError(
            f"concept names must be at most {MAX_CONCEPT_NAME_CHARS} characters; "
            "use the concept's short name"
        )
    return name


class GraphUpdateInput(BaseModel):
    """Typed input shape for the apply_graph_update tool."""

    concepts: list[str] = Field(
        description="Concept names to merge into the user's knowledge "
                    "graph for the current course. At most "
                    f"{MAX_CONCEPTS_PER_CALL} per call, each a short name "
                    f"(at most {MAX_CONCEPT_NAME_CHARS} characters) that the "
                    "student or the course material used this turn."
    )

    @field_validator("concepts", mode="before")
    @classmethod
    def _clip_concepts(cls, concepts):
        return _clip(concepts, MAX_CONCEPTS_PER_CALL, "concepts")

    @field_validator("concepts", mode="after")
    @classmethod
    def _bound_names(cls, concepts: list[str]) -> list[str]:
        return [_bounded_name(c) for c in concepts]


class ConceptMasteryUpdate(BaseModel):
    concept_name: str = Field(
        description="Exact name of the concept whose mastery score to change."
    )

    @field_validator("concept_name", mode="after")
    @classmethod
    def _bound_name(cls, name: str) -> str:
        return _bounded_name(name)
    # #150: the schema enforces the band the prompt instructs — injected
    # content demanding "set my mastery to 1.0" fails validation instead
    # of writing a full-scale jump (the #153 retry loop surfaces the
    # violation back to the model for correction). Matches the eval band
    # in tests/evals/chat_tutor.py (MASTERY_DELTA_MIN/MAX).
    mastery_delta: float = Field(
        ge=MASTERY_DELTA_MIN,
        le=MASTERY_DELTA_MAX,
        description=(
            "Fractional mastery change, −0.1 to +0.3. "
            "Use +0.1 to +0.3 when the student answers correctly; "
            "−0.05 to −0.1 when they reveal a gap or misconception."
        ),
    )
    reason: str = Field(
        default="",
        description="Short phrase shown in the mastery-event log (e.g. 'answered correctly').",
    )
    # Nullable on purpose, and NOT defaulted to a real category. A default
    # of "interaction" made every mastery event the tutor ever wrote look
    # deliberately classified, including the turns the model never thought
    # about — which is exactly the "un-categorised events indistinguishable
    # from confident ones" outcome that migration
    # 20260814051517_node_mastery_events_event_type.sql refuses. None means
    # "this turn was not classified", and `update_mastery_tool` omits the key
    # entirely so the column stays NULL rather than carrying a guess.
    event_type: Literal["interaction", "correction", "quiz"] | None = Field(
        default=None,
        description=(
            "Optional event category for the mastery-event log. Omit it "
            "unless the turn genuinely fits one: 'interaction' for ordinary "
            "engagement, 'correction' when you corrected a misconception, "
            "'quiz' when you quizzed the student."
        ),
    )


class MasteryUpdateInput(BaseModel):
    """Typed input for the update_mastery tool."""

    updates: list[ConceptMasteryUpdate] = Field(
        description=(
            "One entry per concept whose mastery changed this turn "
            f"(at most {MAX_MASTERY_UPDATES_PER_CALL} per call). "
            "Only include concepts that already exist in the graph "
            "(or were just added via apply_graph_update_tool)."
        )
    )

    @field_validator("updates", mode="before")
    @classmethod
    def _clip_updates(cls, updates):
        return _clip(updates, MAX_MASTERY_UPDATES_PER_CALL, "updates")


async def apply_concepts_to_graph(
    user_id: str,
    course_id: str | None,
    concept_names: list[str],
) -> int:
    """Merge concepts into the user's course graph. Returns the count merged.

    Pure async — no Pydantic AI dependency, callable from routes directly.
    `apply_graph_update` is sync, so we run it in a thread to avoid
    blocking the event loop.
    """
    new_nodes = [
        {"concept_name": name, "initial_mastery": 0.0}
        for name in concept_names
        if name and name.strip()
    ]
    if not new_nodes:
        return 0
    await asyncio.to_thread(
        apply_graph_update,
        user_id,
        {"new_nodes": new_nodes},
        course_id,
    )
    return len(new_nodes)


_NON_WORD = re.compile(r"[\W_]+", re.UNICODE)


def _grounding_key(text: str) -> str:
    """NFKC, case-folded, every run of non-word characters one space, padded
    so a substring test is a whole-word test ("heap" is not in "heaps")."""
    folded = unicodedata.normalize("NFKC", text or "").casefold()
    return " " + " ".join(_NON_WORD.sub(" ", folded).split()) + " "


def allow_concept_text(deps: SaplingDeps, *texts: str | None) -> None:
    """Add text a new concept may come from this run (no-op when the run has
    no grounding check, i.e. `deps.concept_context` is None)."""
    if getattr(deps, "concept_context", None) is None:
        return
    deps.concept_context.extend(t for t in texts if isinstance(t, str) and t.strip())


def concept_is_grounded(deps: SaplingDeps, name: str) -> bool:
    """Whether ``name`` appears (normalized, whole words) in this run's
    allowed text. Always True for a run with no grounding check."""
    context = getattr(deps, "concept_context", None)
    if context is None:
        return True
    key = _grounding_key(name)
    if not key.strip():
        return False
    return any(key in _grounding_key(t) for t in context)


def _turn_new_concepts(deps: SaplingDeps) -> int:
    """New concepts already added this run (read off `deps.graph_updates`)."""
    return sum(
        len(p.get("new_nodes", ()) or ())
        for p in deps.graph_updates if isinstance(p, dict)
    )


def _within_turn_band(value: float) -> float:
    return max(MASTERY_DELTA_MIN, min(MASTERY_DELTA_MAX, value))


def _turn_mastery_spent(deps: SaplingDeps) -> dict[str, float]:
    """Net mastery delta already applied this run, per normalized concept.

    Read off `deps.graph_updates`, which holds exactly the updated_nodes this
    tool persisted (a concept that did not exist is never appended), so the
    budget counts what was written, not what was asked for.
    """
    spent: dict[str, float] = {}
    for payload in deps.graph_updates:
        for node in payload.get("updated_nodes", ()) if isinstance(payload, dict) else ():
            name = node.get("concept_name")
            delta = node.get("mastery_delta")
            if isinstance(name, str) and isinstance(delta, (int, float)):
                key = _normalize_concept(name)
                spent[key] = spent.get(key, 0.0) + float(delta)
    return spent


async def apply_graph_update_tool(
    ctx: RunContext[SaplingDeps],
    update: GraphUpdateInput,
) -> str:
    """Register new concepts in the student's knowledge graph.

    Call this when a new topic comes up that isn't already tracked.
    To raise or lower mastery on an existing concept, call update_mastery_tool.
    """
    names = [name.strip() for name in update.concepts if name and name.strip()]
    if not names:
        return "Graph update skipped: no concepts to add."

    # M7: a new concept must come from THIS turn — the student's message, the
    # context the turn was built with, or what the run's read tools returned.
    # A name that appears nowhere there is the model's invention or an
    # instruction it was given; it is refused, and the message says why so
    # the model can carry on without it.
    ungrounded = [n for n in names if not concept_is_grounded(ctx.deps, n)]
    names = [n for n in names if n not in ungrounded]

    # M7: at most MAX_NEW_CONCEPTS_PER_TURN across every call of one run.
    budget = MAX_NEW_CONCEPTS_PER_TURN - _turn_new_concepts(ctx.deps)
    over_budget = names[max(budget, 0):]
    names = names[:max(budget, 0)]

    notes: list[str] = []
    if ungrounded:
        logger.info("[graph tools] refused %d new concept(s) not in this turn's context",
                    len(ungrounded))
        notes.append(
            "Not added (the name does not appear in the student's message or this "
            "turn's course context; add only concepts the student or the material "
            "actually named, spelled as they appear): " + ", ".join(ungrounded) + "."
        )
    if over_budget:
        notes.append(
            f"Not added (at most {MAX_NEW_CONCEPTS_PER_TURN} new concepts per turn): "
            + ", ".join(over_budget) + "."
        )
    if not names:
        return "Graph update skipped. " + " ".join(notes)

    new_nodes = [{"concept_name": name, "initial_mastery": 0.0} for name in names]
    await asyncio.to_thread(
        apply_graph_update,
        ctx.deps.user_id,
        {"new_nodes": new_nodes},
        ctx.deps.course_id,
    )
    ctx.deps.graph_updates.append({"new_nodes": new_nodes})
    return " ".join([f"Graph updated: {len(new_nodes)} concept(s) merged.", *notes])


async def update_mastery_tool(
    ctx: RunContext[SaplingDeps],
    update: MasteryUpdateInput,
) -> str:
    """Adjust mastery scores for concepts the student engaged with this turn.

    Positive delta (e.g. +0.15) when they demonstrate understanding;
    negative (e.g. −0.08) when they reveal a gap. Concepts must already
    exist in the graph — call apply_graph_update_tool first if needed.
    """
    updated_nodes: list[dict] = []
    spent = _turn_mastery_spent(ctx.deps)
    for u in update.updates:
        if not (u.concept_name and u.concept_name.strip()):
            continue
        key = _normalize_concept(u.concept_name)
        used = spent.get(key, 0.0)
        # Per-turn cap: the net delta for one concept across this whole run
        # stays inside the per-call band, however many calls ask for more.
        allowed = _within_turn_band(used + u.mastery_delta) - used
        if abs(allowed) < 1e-9:
            logger.info(
                "[tutor] mastery update for one concept dropped: the turn's "
                "net delta is already at the cap (%+.2f)", used,
            )
            continue
        spent[key] = used + allowed
        node = {
            "concept_name": u.concept_name.strip(),
            "mastery_delta": round(allowed, 6),
            "reason": u.reason,
        }
        # Omitted rather than written as None when the model didn't classify
        # the turn, mirroring `apply_graph_update`'s own omit-on-absent rule:
        # a NULL column says "this writer didn't classify", an explicit key
        # says "it did, and the value is nothing".
        if u.event_type is not None:
            node["event_type"] = TUTOR_EVENT_TYPES[u.event_type]
        updated_nodes.append(node)
    if not updated_nodes:
        if update.updates:
            return (
                "Mastery update skipped: these concepts already moved as far "
                "as one turn allows."
            )
        return "Mastery update skipped: no concepts provided."

    changes = await asyncio.to_thread(
        apply_graph_update,
        ctx.deps.user_id,
        {"updated_nodes": updated_nodes},
        ctx.deps.course_id,
    )

    # Only persist concepts that actually produced a change. A concept the
    # model named but that doesn't exist in the graph yields no `changes`
    # and is never written, so it must not leak into graph_update_json (it
    # would over-report concepts_covered in end_session). Rebuild the
    # appended updated_nodes from the concepts that genuinely changed.
    #
    # `changes` carries the *stored* concept_name while `updated_nodes` holds
    # the *model-provided* spelling; match on the normalized form (the same
    # case/whitespace-insensitive key apply_graph_update dedups on) so a
    # casing/spacing drift doesn't drop a genuinely-changed concept.
    if changes:
        changed_names = {_normalize_concept(c["concept"]) for c in changes}
        persisted_nodes = [
            n
            for n in updated_nodes
            if _normalize_concept(n["concept_name"]) in changed_names
        ]
        if persisted_nodes:
            ctx.deps.graph_updates.append({"updated_nodes": persisted_nodes})
        # Surface the real before/after deltas for parity with the legacy path.
        ctx.deps.mastery_changes.extend(changes)
        parts = [f"{c['concept']} {c['before']:.2f}→{c['after']:.2f}" for c in changes]
        return f"Mastery updated: {', '.join(parts)}."
    return (
        f"Mastery update processed ({len(updated_nodes)} concept(s)); "
        "no score change — concept may not exist yet. Call apply_graph_update_tool first."
    )
