"""Import smoke tests for chat_tutor agents. Live-Gemini behavior is
covered by the eval set in tests/evals/chat_tutor.py."""

from agents.chat_tutor import (
    _PROMPT_HASHES,
    agent_for_mode,
    expository_agent,
    socratic_agent,
    teachback_agent,
)


def test_three_mode_agents_exist():
    assert socratic_agent is not None
    assert expository_agent is not None
    assert teachback_agent is not None


def test_each_mode_has_distinct_prompt_hash():
    """Mode prompts differ; their hashes must too."""
    hashes = list(_PROMPT_HASHES.values())
    assert len(set(hashes)) == 3


def test_agent_for_mode_dispatches_correctly():
    assert agent_for_mode("socratic") is socratic_agent
    assert agent_for_mode("expository") is expository_agent
    assert agent_for_mode("teachback") is teachback_agent


def test_unknown_mode_falls_back_to_socratic():
    assert agent_for_mode("nonsense") is socratic_agent
    assert agent_for_mode("") is socratic_agent
    assert agent_for_mode(None) is socratic_agent


def test_all_tools_registered():
    """Chat tutor needs three context tools + two graph tools (add and update mastery)."""
    expected = {
        "search_course_materials_tool",
        "read_session_history_tool",
        "read_user_progress_tool",
        "apply_graph_update_tool",
        "update_mastery_tool",
    }
    # Pydantic AI 1.89's tool registry is at agent._function_toolset.tools
    # (dict keyed by tool name) — see commit a850d31 for the gotcha.
    tool_names = set(socratic_agent._function_toolset.tools.keys())
    assert expected == tool_names
