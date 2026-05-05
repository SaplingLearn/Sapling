"""Chat tutor agent for the Learn route's three teaching modes.

Replaces routes/learn.py:152's build_system_prompt + call_gemini_multiturn
with a typed Pydantic AI agent. Tools handle the data lookups that used
to be string-stuffed: search_course_materials, read_session_history,
read_user_progress, apply_graph_update_tool.

Modes (Socratic, Expository, TeachBack) are gated by selecting different
system prompts at construction time. The route picks the right agent
instance per request based on body.mode.
"""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic_ai import Agent

from agents._providers import model_for
from agents.deps import SaplingDeps
from agents.tools.chat_context import (
    read_session_history_tool,
    read_user_progress_tool,
    search_course_materials_tool,
)
from agents.tools.graph import apply_graph_update_tool


TutorMode = Literal["socratic", "expository", "teachback"]


# ── System prompts (one per mode) ──────────────────────────────────────────

# The shared preamble is identical across modes so a prompt-version bump
# in shared guidance shows up as a hash change for every mode at once.
_SHARED_PREAMBLE = (
    "You are Sapling, an AI tutor that helps a student build mastery in "
    "their course material. You have tools to fetch the student's "
    "progress, search their uploaded course documents, and update their "
    "knowledge graph mastery scores. Use tools when relevant — don't "
    "fabricate context.\n\n"
    "Tone: warm, concise, no filler. Use math/code blocks where helpful "
    "(LaTeX `$x^2$`, ```mermaid```, ```plot```). Don't over-explain.\n\n"
)

_SOCRATIC_PROMPT = _SHARED_PREAMBLE + (
    "MODE: Socratic. Lead the student to the answer through questions, "
    "not lectures. Each turn: ask one focused question that reveals what "
    "they already know or where they're confused. Avoid giving the answer "
    "directly; provide hints only after they've made an attempt. End "
    "every response with a question."
)

_EXPOSITORY_PROMPT = _SHARED_PREAMBLE + (
    "MODE: Expository. Explain the concept directly and thoroughly. "
    "Structure your response: brief overview → detailed explanation → "
    "concrete example or worked problem. Don't ask questions back unless "
    "the student's prompt is genuinely ambiguous."
)

_TEACHBACK_PROMPT = _SHARED_PREAMBLE + (
    "MODE: TeachBack. The student is teaching you a concept. Listen to "
    "their explanation, then identify what's correct, what's missing, "
    "and any specific misconceptions. Praise accuracy where it exists. "
    "End with one targeted question that probes the weakest spot in "
    "their understanding."
)

_PROMPTS: dict[TutorMode, str] = {
    "socratic": _SOCRATIC_PROMPT,
    "expository": _EXPOSITORY_PROMPT,
    "teachback": _TEACHBACK_PROMPT,
}

# Hash of each mode's full prompt (preamble + body), for span versioning.
# Logfire spans on chat-tutor runs include this so a prompt revision
# shows up as a clean delta when comparing run metadata across deploys.
_PROMPT_HASHES: dict[TutorMode, str] = {
    mode: hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]
    for mode, prompt in _PROMPTS.items()
}


# ── Agent (one per mode, sharing the same tool surface) ────────────────────

# Output type is plain str — chat tutor produces free-form Markdown that
# the frontend renders via MarkdownChat. No structured output here; that
# is reserved for routes that grade or extract.

# All four tools are registered on every mode. The system prompt steers
# WHEN to call them; the surface stays uniform so a Pro-tier model can
# decide for itself which lookups are worth the round trip.
_TOOLS = [
    search_course_materials_tool,
    read_session_history_tool,
    read_user_progress_tool,
    apply_graph_update_tool,
]


def _build_agent(mode: TutorMode) -> Agent[SaplingDeps, str]:
    return Agent[SaplingDeps, str](
        model=model_for("chat_tutor"),
        deps_type=SaplingDeps,
        output_type=str,
        system_prompt=_PROMPTS[mode],
        metadata={
            "prompt_version": _PROMPT_HASHES[mode],
            "agent": "chat_tutor",
            "mode": mode,
        },
        tools=_TOOLS,
    )


socratic_agent = _build_agent("socratic")
expository_agent = _build_agent("expository")
teachback_agent = _build_agent("teachback")


def agent_for_mode(mode: str | None) -> Agent[SaplingDeps, str]:
    """Return the agent instance for a given mode string.

    Falls back to Socratic if the mode is unrecognized (or missing) —
    same default the legacy `build_system_prompt` used when no mode
    matched the MODE_PROMPTS dict.
    """
    normalized = (mode or "socratic").lower()
    return {
        "socratic": socratic_agent,
        "expository": expository_agent,
        "teachback": teachback_agent,
    }.get(normalized, socratic_agent)
