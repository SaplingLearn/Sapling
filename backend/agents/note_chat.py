"""Note-scoped chat agent.

Powers the AI Chat panel inside the notetaker. Distinct from
`chat_tutor.py` because the scope is one note, not a course-wide
tutoring session, and the system prompt nudges the agent to ground
in what the student is actively writing.

Tools (wire names — what the model sees):
  - read_active_note (note-specific; from agents/tools/note_context.py)
  - search_course_materials (chat_tutor's grounding; registered under the
    prompt-facing name via Tool(..., name=...) — #135)
  - apply_graph_update_tool (lets the agent mark new concepts while
    answering, the same way the course tutor does)

Academic integrity (spec §13 A125): for a learning-loop student the run's
instructions tell the model never to answer, solve or confirm a graded check
question — defence in depth only (`integrity_run_args`). The guarantee is
structural and lives in the route (routes/notes.py, through
services/integrity_guard.py): a message or note quoting one of the student's
posed checks never reaches this agent, and a reply stating one's key is never
served. With the loop off the guard is off (A125 (i)) and so is the rule: the
request is the pre-loop app's, system prompt and all (#866 Z26).
"""
from __future__ import annotations

import hashlib

from pydantic_ai import Agent, Tool

from agents._providers import model_for
from agents.deps import SaplingDeps
from agents.tools.chat_context import search_course_materials_tool
from agents.tools.graph import apply_graph_update_tool
from agents.tools.note_context import read_active_note_tool
from services.crisis_support_copy import MODEL_SAFETY_PROMPT
from services.prompt_safety import INJECTION_GUARD_PROMPT


_PROMPT = (
    "You are Sapling's quick-questions assistant inside the notetaker. "
    "The student is actively writing one note. Use `read_active_note` "
    "to ground every answer in the note's title, body, and linked "
    "concepts. Use `search_course_materials` when the question reaches "
    "beyond the note. Use `apply_graph_update_tool` when the student "
    "mentions a concept that isn't yet in their knowledge graph for "
    "this course.\n\n"
    # #150: this agent's tools return student-authored note/document text.
    + INJECTION_GUARD_PROMPT
    + "\n\n"
    # sec2 M11: the model-side crisis backstop, flag or no flag.
    + MODEL_SAFETY_PROMPT
    + "\n\n"
    "Tone: warm, concise, no filler. Use math/code blocks where helpful "
    "(LaTeX `$x^2$`, ```mermaid```, ```plot```). Keep replies short — "
    "this is a sidecar chat, not a tutoring session."
)
_PROMPT_HASH = hashlib.sha256(_PROMPT.encode("utf-8")).hexdigest()[:12]

#: Spec §13 A125 (g): defence in depth for the route's integrity guard, which is
#: the guarantee. Part of the loop like the guard (A125 (i)), so it rides a run
#: only when the route's gate is on (`integrity_run_args`): a loop-off student
#: gets the pre-loop prompt, and is never sent to a learning-session card they
#: do not have (#866 Z26).
INTEGRITY_INSTRUCTIONS = (
    "ACADEMIC INTEGRITY (non-negotiable): Sapling's learning sessions pose "
    "graded check questions. When the student asks you to answer, solve or "
    "check their answer to a quiz, check, test or homework question — pasted "
    "into the chat or written in the note — do not give its answer, a worked "
    "solution, or a yes/no on their answer. Say you can't answer graded "
    "questions here and point them to that question's card in their learning "
    "session, whose hints go one step at a time. You may explain the "
    "underlying idea in general terms, without solving that question."
)
_INTEGRITY_PROMPT_HASH = hashlib.sha256(
    f"{_PROMPT}\n\n{INTEGRITY_INSTRUCTIONS}".encode("utf-8")
).hexdigest()[:12]


def integrity_run_args(learning_loop: bool) -> dict:
    """`note_chat_agent.run(..., **integrity_run_args(on))`, `on` being the
    route-entry gate's answer for this student (learning/gate.py, read once).
    Off: nothing — the agent's own system prompt and prompt version, the
    request the pre-loop app sent. On: the integrity rule as the run's
    instructions (after the unchanged system prompt) and that prompt's version
    for the run's metadata (agents.loop_tutor.variant_run_args' pattern)."""
    if not learning_loop:
        return {}
    return {
        "instructions": INTEGRITY_INSTRUCTIONS,
        "metadata": {"prompt_version": _INTEGRITY_PROMPT_HASH},
    }


note_chat_agent = Agent[SaplingDeps, str](
    model=model_for("note_chat"),
    deps_type=SaplingDeps,
    output_type=str,
    system_prompt=_PROMPT,
    metadata={"prompt_version": _PROMPT_HASH, "agent": "note_chat"},
    tools=[
        Tool(read_active_note_tool, name="read_active_note", takes_ctx=True),
        # #135: register under the prompt-facing name — the bare callable would
        # derive the wire name "search_course_materials_tool", which the system
        # prompt never mentions.
        Tool(search_course_materials_tool, name="search_course_materials", takes_ctx=True),
        apply_graph_update_tool,
    ],
)
