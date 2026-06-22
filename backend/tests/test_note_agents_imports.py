"""Import-level smoke tests for the three notetaker agents.

Pins: each agent exists, has a stable prompt hash, declares the right
output type, and (for note_chat) registers its tools.
"""
from __future__ import annotations


def test_note_summary_agent_exists():
    from agents.note_summary import note_summary_agent, NoteSummary
    assert note_summary_agent is not None
    # Output type is the NoteSummary BaseModel with one `summary` field.
    fields = set(NoteSummary.model_fields.keys())
    assert fields == {"summary"}


def test_note_summary_prompt_hash_stable():
    from agents.note_summary import _PROMPT_HASH
    # Hash is 12 lowercase hex chars (sha256[:12]) — pin the shape so a
    # future refactor that drops the hash gets flagged.
    assert isinstance(_PROMPT_HASH, str) and len(_PROMPT_HASH) == 12


def test_note_concepts_agent_exists():
    from agents.note_concepts import note_concepts_agent, NoteConcepts
    assert note_concepts_agent is not None
    fields = set(NoteConcepts.model_fields.keys())
    assert fields == {"concepts"}


def test_note_chat_agent_exists_with_tools():
    from agents.note_chat import note_chat_agent
    # Pydantic AI 1.89's tool registry is at agent._function_toolset.tools
    # (keys are tool names) — matches the pattern in test_chat_tutor_imports
    # and test_quiz_agent_imports.
    tool_names = set(note_chat_agent._function_toolset.tools.keys())
    # read_active_note must be registered; existing course-material and
    # graph-update tools come along for grounding.
    assert "read_active_note" in tool_names
    assert "apply_graph_update_tool" in tool_names or "apply_graph_update" in tool_names
