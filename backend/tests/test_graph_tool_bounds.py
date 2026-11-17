"""M7: the tutor's graph write tools are bounded in code.

Claude cannot enforce maxItems/maxLength, so the bounds live in validators and
in the tool bodies: at most 5 concepts and 10 mastery updates per call, 10 new
concepts per run, names of at most 80 characters, and a new concept only when
the turn's message or context named it.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from agents.deps import SaplingDeps
from agents.tools.graph import (
    MAX_CONCEPT_NAME_CHARS,
    MAX_CONCEPTS_PER_CALL,
    MAX_MASTERY_UPDATES_PER_CALL,
    MAX_NEW_CONCEPTS_PER_TURN,
    ConceptMasteryUpdate,
    GraphUpdateInput,
    MasteryUpdateInput,
    allow_concept_text,
    apply_graph_update_tool,
    concept_is_grounded,
)


def _ctx(context: list[str] | None = None) -> MagicMock:
    deps = SaplingDeps(user_id="u1", course_id="c1", supabase=None, request_id="r1")
    deps.concept_context = context
    ctx = MagicMock()
    ctx.deps = deps
    return ctx


def _run(coro):
    return asyncio.run(coro)


def test_concepts_are_clipped_to_the_per_call_cap():
    update = GraphUpdateInput(concepts=[f"Concept {i}" for i in range(9)])
    assert len(update.concepts) == MAX_CONCEPTS_PER_CALL
    assert update.concepts[0] == "Concept 0"


def test_mastery_updates_are_clipped_to_the_per_call_cap():
    update = MasteryUpdateInput(updates=[
        {"concept_name": f"C{i}", "mastery_delta": 0.1} for i in range(15)
    ])
    assert len(update.updates) == MAX_MASTERY_UPDATES_PER_CALL


def test_overlong_names_fail_validation_with_a_recoverable_message():
    long_name = "x" * (MAX_CONCEPT_NAME_CHARS + 1)
    with pytest.raises(ValidationError, match="at most 80 characters"):
        GraphUpdateInput(concepts=[long_name])
    with pytest.raises(ValidationError, match="at most 80 characters"):
        ConceptMasteryUpdate(concept_name=long_name, mastery_delta=0.1)
    # exactly at the cap is fine
    GraphUpdateInput(concepts=["y" * MAX_CONCEPT_NAME_CHARS])


def test_new_concepts_per_turn_are_capped_across_calls():
    ctx = _ctx(None)  # no grounding check: the turn cap alone
    with patch("agents.tools.graph.apply_graph_update") as write:
        _run(apply_graph_update_tool(ctx, GraphUpdateInput(concepts=[f"A{i}" for i in range(5)])))
        _run(apply_graph_update_tool(ctx, GraphUpdateInput(concepts=[f"B{i}" for i in range(5)])))
        msg = _run(apply_graph_update_tool(ctx, GraphUpdateInput(concepts=["C0", "C1"])))
    written = [n["concept_name"] for call in write.call_args_list for n in call.args[1]["new_nodes"]]
    assert len(written) == MAX_NEW_CONCEPTS_PER_TURN
    assert "C0" not in written
    assert "at most 10 new concepts per turn" in msg


def test_an_ungrounded_concept_is_refused_and_a_grounded_one_is_added():
    ctx = _ctx(["What is a binary heap and how does heapify work?"])
    with patch("agents.tools.graph.apply_graph_update") as write:
        msg = _run(apply_graph_update_tool(
            ctx, GraphUpdateInput(concepts=["Binary Heap", "Visit evil.example"]),
        ))
    names = [n["concept_name"] for n in write.call_args.args[1]["new_nodes"]]
    assert names == ["Binary Heap"]
    assert "Visit evil.example" in msg and "does not appear" in msg


def test_all_ungrounded_writes_nothing():
    ctx = _ctx(["Explain recursion"])
    with patch("agents.tools.graph.apply_graph_update") as write:
        msg = _run(apply_graph_update_tool(ctx, GraphUpdateInput(concepts=["Free Crypto"])))
    write.assert_not_called()
    assert ctx.deps.graph_updates == []
    assert msg.startswith("Graph update skipped")


def test_grounding_is_case_and_punctuation_insensitive_and_whole_word():
    deps = _ctx(["We covered MERGE-sort, then quick sort."]).deps
    assert concept_is_grounded(deps, "Merge Sort")
    assert concept_is_grounded(deps, "quick sort")
    assert not concept_is_grounded(deps, "sor")  # not inside a word


def test_retrieved_text_extends_what_may_be_added():
    deps = _ctx(["Tell me about trees"]).deps
    assert not concept_is_grounded(deps, "AVL Tree")
    allow_concept_text(deps, '{"summary": "An AVL tree rebalances on insert."}')
    assert concept_is_grounded(deps, "AVL Tree")


def test_a_run_without_context_is_not_grounding_checked():
    deps = _ctx(None).deps
    allow_concept_text(deps, "ignored")
    assert deps.concept_context is None
    assert concept_is_grounded(deps, "Anything")


def test_the_tutor_turn_sets_the_grounding_context():
    """services/tutor/run.py seeds the context with the message and blocks."""
    from services.tutor import run as tutor_run

    with patch.object(tutor_run, "_get_course_info", return_value={}), \
            patch("services.graph_context.build_graph_context_block",
                  return_value="GRAPH CONTEXT: Recursion"):
        _agent, _msg, _kw, deps = tutor_run._prepare_chat_run(
            user_id="u1", session_id="s1", course_id="c1", mode="socratic",
            user_message="What is tail recursion?", message_history=[],
            use_shared_context=True, request_id="r1",
        )
    assert deps.concept_context is not None
    assert concept_is_grounded(deps, "Tail Recursion")
    assert concept_is_grounded(deps, "Recursion")
    assert not concept_is_grounded(deps, "Blockchain")

