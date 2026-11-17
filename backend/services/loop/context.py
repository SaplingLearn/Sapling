"""A planned turn's context (spec §3.4): the course, catalog, retrieval and
graph blocks, the A128 materials notice, and `_prepare_loop_run`.
"""
from __future__ import annotations

from agents import LOOP_LIMITS
from agents.deps import SaplingDeps
from agents.loop_tutor import (
    assemble_turn_message,
    loop_tutor_agent,
    new_nonce,
    tier_run_kwargs,
    variant_run_args,
)
from services.tutor import _get_catalog_chunk, _get_course_info
from services.graph_context import build_graph_context_block
from services.prompt_safety import wrap_untrusted
from services.rag_service import chunks_for_ids, format_rag_context, retrieve_chunks_detailed

from services.loop.constants import _CATALOG_HEADER, _SOURCE_HEADER, _SOURCE_LABEL


# ── Context and run assembly ───────────────────────────────────────────────


def _context_blocks(
    *, user_id: str, course_id: str, user_message: str, context, item, out: dict | None = None
) -> list[str]:
    """Only the blocks `context` (policy.context_policy) asks for, in the legacy
    order, with the legacy builders (routes/learn.py::_prepare_chat_run).

    Spec §13 A128: the course-material retrieval tells a FAILURE from an empty
    result (`retrieve_chunks_detailed`); a failed one sets `out["retrieval"] =
    "failed"` for the turn, and the turn still runs (with no RAG block, as an
    empty result would) — the outage is reported, never blocking."""
    blocks: list[str] = []
    bu_code = _get_course_info(course_id).get("course_code") if course_id else None
    if context.catalog and bu_code:
        catalog = _get_catalog_chunk(bu_code)
        if catalog:
            blocks.append(_CATALOG_HEADER + catalog)
    if context.rag_k and bu_code:
        got = retrieve_chunks_detailed(
            user_message, course_id=bu_code, k=context.rag_k, user_id=user_id
        )
        if got.failed and out is not None:
            out["retrieval"] = "failed"
        rag = format_rag_context(got.chunks)
        if rag:
            blocks.append(rag)
    if context.source_chunks and item is not None:
        ids = list(item.source_chunk_ids or [])[: context.source_chunks]
        rows = chunks_for_ids(ids, user_id=user_id) if ids else []
        text = "\n\n".join(r["chunk_text"] for r in rows if r.get("chunk_text"))
        wrapped = wrap_untrusted(text, source=_SOURCE_LABEL)
        if wrapped:
            blocks.append(_SOURCE_HEADER + wrapped)
    if context.graph_block and course_id:
        graph = build_graph_context_block(user_id, course_id, user_message)
        if graph:
            blocks.append(graph)
    return blocks


# ── A failed course-material retrieval (spec §13 A128) ─────────────────────
#
# Two loop_state keys. `materials_notice`: the session's ONE calm note that
# its course materials are unavailable has been served (`materials_unavailable`
# in the turn's response; the UI renders it — never a prompt change).
# `retrieval_failed`: the concept nodes whose teach turns ran with a failed
# retrieval since their last check activation; `_activate_next_item` moves a
# concept's mark onto the step it opens (`retrieval: "failed"`), so that
# step's zpd.step says its teaching lacked the course's material.
_MATERIALS_NOTICE = "materials_notice"


_RETRIEVAL_FAILED = "retrieval_failed"


#: The step entry's key (and zpd.step's payload value) for such a step.
_RETRIEVAL_KEY, _RETRIEVAL_FAILED_VALUE = "retrieval", "failed"


def _note_retrieval_failure(state: dict, concept_node: str | None) -> bool:
    """Record a turn whose course-material retrieval failed, on the loop
    document (a compare-and-set mutate's business: no side effects): the
    concept's mark, and the session's note. True when THIS turn serves the
    note — the first failure of the session, never again after it."""
    if concept_node:
        marked = [n for n in state.get(_RETRIEVAL_FAILED) or [] if isinstance(n, str)]
        if concept_node not in marked:
            state[_RETRIEVAL_FAILED] = [*marked, concept_node]
    if state.get(_MATERIALS_NOTICE) is True:
        return False
    state[_MATERIALS_NOTICE] = True
    return True


def _materials_notice(out: dict) -> dict:
    """The turn response's A128 key: `materials_unavailable: true` on the ONE
    turn that serves the session's note, absent on every other (never false)."""
    return {"materials_unavailable": True} if out.get("materials_notice") else {}


def _take_retrieval_mark(state: dict, concept_node: str) -> bool:
    """Whether the concept's teaching since its last check ran with a failed
    retrieval — the mark is consumed, so the NEXT check of the concept starts
    clean (its own teach turns decide it)."""
    marked = [n for n in state.get(_RETRIEVAL_FAILED) or [] if isinstance(n, str)]
    if concept_node not in marked:
        return False
    rest = [n for n in marked if n != concept_node]
    if rest:
        state[_RETRIEVAL_FAILED] = rest
    else:
        state.pop(_RETRIEVAL_FAILED, None)
    return True


def _prepare_loop_run(
    *,
    user_id: str,
    session_id: str,
    course_id: str,
    user_message: str,
    message_history: list,
    request_id: str,
    prefix: str,
    state: dict,
    tier: str,
    context,
    item,
    learning_loop: bool,
    loop_turn,
    trusted: bool = False,
    instruction: str | None = None,
    nonce: str | None = None,
    v2: bool = False,
    focus_block: str | None = None,
    extra_blocks: list[str] | None = None,
    out: dict | None = None,
) -> tuple:
    """One loop run's agent, user message, run kwargs and deps. `user_message`
    is the retrieval query and — unless `trusted` (server text: an [ACTION: ...]
    line) — the student's words, which reach the model only inside the nonce
    envelope (review round 3, C1(a)); `instruction` is server text placed
    verbatim before it. The history's user rows are the student's words too
    (enveloped by the caller, `_guard_history`). `v2` adds the
    v2 variant's run arguments (spec §13 A121, `variant_run_args`):
    none when off. `focus_block` (v2 teach turns only) is the plan concept's
    untrusted block (`plan_focus_block`), first among the context blocks.
    `extra_blocks` (spec §13 A138: the prequestion's answer block) follow the
    context blocks. `out` receives what the context assembly found (A128:
    `retrieval: "failed"`)."""
    deps = SaplingDeps(
        user_id=user_id,
        course_id=course_id or None,
        supabase=None,
        request_id=request_id,
        session_id=session_id,
        feature="loop_tutor",
        learning_loop=learning_loop,
        loop_state=state,
        loop_turn=loop_turn,
    )
    blocks = _context_blocks(
        user_id=user_id,
        course_id=course_id,
        user_message=user_message,
        context=context,
        item=item,
        out=out,
    )
    if focus_block:
        blocks = [focus_block, *blocks]
    if extra_blocks:
        # spec §13 A138: the prequestion's answer, as data, after the context
        blocks = [*blocks, *extra_blocks]
    assembled = assemble_turn_message(
        prefix=prefix,
        blocks=blocks,
        nonce=nonce or new_nonce(),
        student_text=None if trusted else user_message,
        instruction=user_message if trusted else instruction,
    )
    run_kwargs = {
        "deps": deps,
        "message_history": message_history,
        "usage_limits": LOOP_LIMITS,
        **tier_run_kwargs(tier, tool_choice=context.tool_choice),
        **variant_run_args(v2),
    }
    return loop_tutor_agent, assembled, run_kwargs, deps
