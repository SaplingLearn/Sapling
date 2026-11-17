"""Graph-update helpers and Pydantic AI tool wrappers.

One tool is exposed:
- apply_graph_update_tool  — registers new concepts (new_nodes, initial_mastery 0.0)

It appends its payload to ctx.deps.graph_updates so the route can persist
graph_update_json on the assistant message, enabling end_session to derive
concepts_covered correctly for agent-path chats.

PKG-14b (spec §11.2): the legacy tutor's mastery-write tool is gone. After
the cutover only graded evidence through `apply_graph_update` moves a mastery
score (spec §1, §5); the legacy tutor — the kill-switch path — records none.

What injected text can and cannot do through this tool
------------------------------------------------------
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
- Mastery: no tool moves it at all (PKG-14b, above), so no passage can talk
  the model into raising a score.
- Sizes (M7): at most MAX_CONCEPTS_PER_CALL concepts per call (clipped in
  model order), MAX_NEW_CONCEPTS_PER_TURN new concepts per run, and names of
  at most MAX_CONCEPT_NAME_CHARS characters (longer fails validation, which
  the model sees as a retryable tool error).
- Where a new concept may come from (M7): it must appear, as whole words,
  in the student's message or the turn's assembled/retrieved context
  (`deps.concept_context`, extended by the read tools via
  `allow_concept_text`). Otherwise it is refused with a message the model
  can act on. A run that never sets the context (evals, scripts) is not
  checked.
"""

from __future__ import annotations

import asyncio
import logging
import re
import unicodedata

from pydantic import BaseModel, Field, field_validator
from pydantic_ai import RunContext

from agents.deps import SaplingDeps
from services.graph_service import apply_graph_update

logger = logging.getLogger(__name__)


#: M7: the size bounds on the write tool. Claude's strict JSON mode cannot
#: enforce maxItems/maxLength at decode time (CLAUDE.md "Structured-output
#: bounds are local on Claude"), so they are enforced here: the list is clipped
#: in model order by a before-validator (`_clip`, logged), and an over-long
#: name fails validation, which pydantic-ai hands back to the model as a
#: retryable tool error.
MAX_CONCEPTS_PER_CALL = 5
MAX_NEW_CONCEPTS_PER_TURN = 10
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


async def apply_graph_update_tool(
    ctx: RunContext[SaplingDeps],
    update: GraphUpdateInput,
) -> str:
    """Register new concepts in the student's knowledge graph.

    Call this when a new topic comes up that isn't already tracked.
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

    guard = getattr(ctx.deps, "integrity", None)
    if guard is not None and names:
        # spec §13 A125: a surface outside the loop (the notes chat) never files
        # a concept name stating one of the student's posed checks' keys — the
        # student would read it in their graph; their own words pass unscanned
        keep = await asyncio.to_thread(guard.screen_each, names, own=guard.own_text)
        names = [name for name, ok in zip(names, keep) if ok]

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
        return " ".join(["Graph update skipped: no concepts to add.", *notes])

    new_nodes = [{"concept_name": name, "initial_mastery": 0.0} for name in names]
    await asyncio.to_thread(
        apply_graph_update,
        ctx.deps.user_id,
        {"new_nodes": new_nodes},
        ctx.deps.course_id,
    )
    ctx.deps.graph_updates.append({"new_nodes": new_nodes})
    return " ".join([f"Graph updated: {len(new_nodes)} concept(s) merged.", *notes])
