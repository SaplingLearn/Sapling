"""PKG-14b: the mastery tool is gone; the legacy chat_tutor agents stay for the kill switch (spec §11.2, §11.6)."""

import pytest


def test_mastery_tool_symbols_are_gone():
    import agents.tools.graph as g

    for name in ("update_mastery_tool", "MasteryUpdateInput", "ConceptMasteryUpdate", "TUTOR_EVENT_TYPES"):
        assert not hasattr(g, name), name


def test_preamble_no_longer_instructs_mastery_writes():
    import agents.chat_tutor as ct

    assert "update_mastery_tool" not in ct._SHARED_PREAMBLE
    assert "+0.1 to +0.3" not in ct._SHARED_PREAMBLE
    # The legacy tutor records no mastery at all after launch (spec §11.6), so
    # the preamble must not tell the model it can move mastery scores.
    assert "mastery scores" not in ct._SHARED_PREAMBLE
    # The reply-after-tools instruction that lived in the deleted paragraph is
    # kept: a turn must never end on a tool call (tests/test_textless_turn_continuation.py).
    assert "ALWAYS write your reply to the student" in ct._SHARED_PREAMBLE


def _names(tools) -> set:
    return {getattr(t, "name", None) or getattr(t, "__name__", None) for t in tools}


def test_legacy_tool_set_drops_only_the_mastery_tool():
    from agents.chat_tutor import _build_tools

    names = _names(_build_tools(learning_loop=False))
    assert "update_mastery_tool" not in names
    assert names == {
        "search_course_materials",
        "read_session_history_tool",
        "read_user_progress_tool",
        "apply_graph_update_tool",
        "read_graph_neighborhood",
        "read_concepts_for_user",
    }  # spec §7: the seven legacy tools minus the mastery tool


def test_registered_legacy_agents_carry_no_mastery_tool():
    from agents.chat_tutor import expository_agent, socratic_agent, teachback_agent

    for agent in (socratic_agent, expository_agent, teachback_agent):
        names = set(agent._function_toolset.tools.keys())
        assert "update_mastery_tool" not in names
        assert len(names) == 6, names


def test_legacy_agents_are_kept_for_the_kill_switch():
    from agents.chat_tutor import expository_agent, socratic_agent, teachback_agent
    from agents.loop_tutor import loop_tutor_agent

    legacy = (socratic_agent, expository_agent, teachback_agent)
    assert len({id(a) for a in legacy}) == 3
    assert all(a is not loop_tutor_agent for a in legacy)


def test_apply_graph_update_rejects_updated_nodes():
    from services.graph_service import apply_graph_update

    with pytest.raises(ValueError, match="updated_nodes"):
        apply_graph_update("u", {"updated_nodes": [{"concept_name": "X"}]}, "c")


def test_apply_graph_update_rejects_updated_nodes_before_any_io(monkeypatch):
    """Loud and early: the rejection happens before any read or write."""
    import services.graph_service as gs

    calls = []
    monkeypatch.setattr(gs, "table", lambda name: calls.append(name))
    with pytest.raises(ValueError):
        gs.apply_graph_update("u", {"new_nodes": [{"concept_name": "Y"}], "updated_nodes": []}, "c")
    assert calls == []


def test_chat_tutor_eval_has_no_mastery_evaluator():
    import pathlib

    src = (pathlib.Path(__file__).resolve().parent / "evals" / "chat_tutor.py").read_text()
    for gone in ("MasteryUpdateEmittedEvaluator", "_mastery_updates", "MASTERY_DELTA_MIN", "expects_mastery_update"):
        assert gone not in src, gone
    # NoToolMisuseEvaluator keeps banning the retired tool name in replies.
    assert '"update_mastery_tool"' in src
