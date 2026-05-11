"""Note-scoped chat agent.

Powers the AI Chat panel inside the notetaker. Distinct from
`chat_tutor.py` because the scope is one note, not a course-wide
tutoring session, and the system prompt nudges the agent to ground
in what the student is actively writing.

Tools:
  - read_active_note (note-specific; from agents/tools/note_context.py)
  - search_course_materials (existing; reuses chat_tutor's grounding)
  - apply_graph_update (existing; lets the agent mark new concepts
    while answering, the same way the course tutor does)
"""
from __future__ import annotations

import hashlib
from typing import Any

from pydantic_ai import Agent, Tool

from agents._providers import model_for
from agents.deps import SaplingDeps
from agents.tools.chat_context import search_course_materials_tool
from agents.tools.graph import apply_graph_update_tool
from agents.tools.note_context import read_active_note_tool


_PROMPT = (
    "You are Sapling's quick-questions assistant inside the notetaker. "
    "The student is actively writing one note. Use `read_active_note` "
    "to ground every answer in the note's title, body, and linked "
    "concepts. Use `search_course_materials` when the question reaches "
    "beyond the note. Use `apply_graph_update_tool` when the student "
    "mentions a concept that isn't yet in their knowledge graph for "
    "this course.\n\n"
    "Tone: warm, concise, no filler. Use math/code blocks where helpful "
    "(LaTeX `$x^2$`, ```mermaid```, ```plot```). Keep replies short — "
    "this is a sidecar chat, not a tutoring session."
)
_PROMPT_HASH = hashlib.sha256(_PROMPT.encode("utf-8")).hexdigest()[:12]


class _NoteChatAgent(Agent[SaplingDeps, str]):
    """Agent subclass that exposes ``_function_tools`` for back-compat tests."""

    @property
    def _function_tools(self) -> dict[str, Any]:  # type: ignore[override]
        return self._function_toolset.tools


note_chat_agent = _NoteChatAgent(
    model=model_for("note_chat"),
    deps_type=SaplingDeps,
    output_type=str,
    system_prompt=_PROMPT,
    metadata={"prompt_version": _PROMPT_HASH, "agent": "note_chat"},
    tools=[
        Tool(read_active_note_tool, name="read_active_note", takes_ctx=True),
        search_course_materials_tool,
        apply_graph_update_tool,
    ],
)
