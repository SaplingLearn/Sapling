"""Chat tutor agent for the Learn route's three teaching modes.

Replaces routes/learn.py:152's build_system_prompt + call_gemini_multiturn
with a typed Pydantic AI agent. Tools handle the data lookups that used
to be string-stuffed — wire names: search_course_materials (registered
under that prompt-facing name via Tool(..., name=...), #135),
read_session_history_tool, read_user_progress_tool,
apply_graph_update_tool, update_mastery_tool.

Modes (Socratic, Expository, TeachBack) are gated by selecting different
system prompts at construction time. The route picks the right agent
instance per request based on body.mode.

Per-call thinking budget: the Pro thinking cap is applied at the route
layer (`routes.learn._build_pro_model_settings`), not on the agent
itself, because the same agent instance also serves Lite runs (via the
"fast" model_pref override) where thinking_config is wasted at best.
Direct callers of `chat_tutor_agent.run(...)` that bypass the route
will get unbounded Pro thinking — pin a `model_settings=` kwarg there
if that matters.
"""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic_ai import Agent, Tool

from agents._providers import model_for
from agents.deps import SaplingDeps
from services.prompt_safety import INJECTION_GUARD_PROMPT
from agents.tools.chat_context import (
    read_session_history_tool,
    read_user_progress_tool,
    search_course_materials_tool,
)
from agents.tools.graph import apply_graph_update_tool, update_mastery_tool
from agents.tools.graph_read import (
    read_concepts_for_user_tool,
    read_graph_neighborhood_tool,
)


TutorMode = Literal["socratic", "expository", "teachback"]


# ── System prompts (one per mode) ──────────────────────────────────────────

# #150: academic-integrity parity with the legacy prompt
# (prompts/preamble.txt) — held out of #149 for this issue. Compact form
# of the same non-negotiable: guide, never do the graded work.
_ACADEMIC_INTEGRITY = (
    "ACADEMIC INTEGRITY (non-negotiable): your job is to build "
    "understanding, never to do the student's graded work. Do not hand "
    "over the final answer, essay, code, or numeric result for homework, "
    "problem sets, labs, or take-home quizzes/exams, and never reproduce "
    "verbatim solution text from uploaded materials as \"the answer\". "
    "Teach instead: hints, leading questions, step breakdowns, checking "
    "their reasoning, and ANALOGOUS worked examples (different numbers or "
    "wording). Fully explaining concepts, definitions, theorems, and "
    "general worked examples is encouraged — the restriction covers only "
    "the student's own graded deliverables. If the student pushes for the "
    "answer, or you are unsure whether it's graded, guide rather than "
    "solve."
)

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
    # #150: injection resistance — single source of truth in
    # services/prompt_safety.py, shared with the legacy preamble.
    + INJECTION_GUARD_PROMPT
    + "\n\n"
    + _ACADEMIC_INTEGRITY
    + "\n\n"
    "Knowledge graph tools:\n"
    "- apply_graph_update_tool: register NEW concepts the student hasn't seen before.\n"
    "- update_mastery_tool: adjust mastery on EXISTING concepts this turn. "
    "Use +0.1 to +0.3 when they answer correctly; −0.05 to −0.1 for gaps. "
    "Call this in EVERY turn where the student demonstrated understanding "
    "or revealed a misconception. After your tool calls complete, ALWAYS "
    "write your reply to the student — never end the turn on a tool call "
    "or with an empty message.\n\n"
    "Graph tools (read):\n"
    "- read_graph_neighborhood: expand around named concepts — their "
    "mastery, tier, and how they connect (prerequisite/builds_on/related).\n"
    "- read_concepts_for_user: list the student's tracked concepts, "
    "weakest mastery first.\n"
    "The GRAPH CONTEXT block in the message already lists the student's "
    "tracked concepts for this course — use these read tools only to "
    "expand beyond it (e.g. relationships of a concept the block didn't "
    "include). Hard cap: at most TWO graph reads per turn.\n\n"
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

# All seven tools are registered on every mode. The system prompt steers
# WHEN to call them; the surface stays uniform so a Pro-tier model can
# decide for itself which lookups are worth the round trip.


def _build_tools() -> list:
    # Fresh Tool instances per agent (rather than one shared module-level
    # list) so no Tool object is registered on multiple agents.
    return [
        # #135: register under the prompt-facing name — the bare callable
        # would derive the wire name "search_course_materials_tool".
        Tool(search_course_materials_tool, name="search_course_materials", takes_ctx=True),
        read_session_history_tool,
        read_user_progress_tool,
        apply_graph_update_tool,
        update_mastery_tool,
        # #149: read-only graph tools, registered under the prompt-facing
        # names the _SHARED_PREAMBLE "Graph tools (read)" paragraph uses.
        Tool(read_graph_neighborhood_tool, name="read_graph_neighborhood", takes_ctx=True),
        Tool(read_concepts_for_user_tool, name="read_concepts_for_user", takes_ctx=True),
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
        tools=_build_tools(),
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
