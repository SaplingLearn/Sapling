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

# Restored from the Gemini-era prompts/preamble.txt (lines 11-66), which the
# #149 agent rewrite compressed to a single line. Replies went flat as a
# result. Every renderer named here is still live in the frontend
# (MarkdownChat.tsx: rehype-katex + KATEX_MACROS, mhchem, remark-directive,
# the sap-mermaid / sap-plot fence extraction, GeoGebra).
#
# The legacy <graph_update> JSON contract is deliberately NOT restored:
# apply_graph_update_tool and update_mastery_tool own that now.
_FORMATTING_TOOLKIT = (
    "FORMATTING & VISUALIZATION:\n"
    "Your reply renders with full Markdown + GFM, KaTeX math, and syntax "
    "highlighting. Use these ambitiously whenever a visualization clarifies "
    "the idea — don't default to plain prose when structure would teach "
    "better.\n"
    "- LaTeX: inline `$...$`, display `$$...$$`. Never write math as ASCII "
    "when LaTeX would render.\n"
    "- Predefined KaTeX macros, write directly: `\\R \\Z \\N \\Q \\C \\E \\Pr` "
    "for blackboard sets/expectations; `\\norm{x}`, `\\abs{x}`, "
    "`\\set{x : P(x)}`, `\\inner{u, v}`; `\\Var \\Cov \\Tr \\rank \\diag`; "
    "`\\eps`; `\\dx \\dy \\dt`.\n"
    "- Headings, bold for key terms on first use, lists for steps, task "
    "lists for learning goals.\n"
    "- Tables for comparisons, parameter sweeps, truth tables — always "
    "prefer a table over a long bulleted comparison.\n"
    "- Fenced code blocks with a language tag; inline `code` for "
    "identifiers.\n"
    "- Blockquotes to cite a definition or reflect the student's own words "
    "back. Strikethrough (`~~...~~`) when correcting a misconception — show "
    "what was wrong, then the correction.\n"
    "- Chemistry via mhchem: `$\\ce{H2O}$`, `$\\ce{2H2 + O2 -> 2H2O}$`.\n"
    "- Commutative diagrams via KaTeX `\\begin{CD}` for mappings between "
    "spaces or algebraic structures.\n"
    "- Mermaid diagrams in a ```mermaid fence — proof outlines, state "
    "machines, dependency graphs, decision trees, flowcharts. ESCAPE RULE: "
    "any node or edge label containing `=`, `?`, `(`, `)`, `:`, `;`, or `,` "
    "MUST be wrapped in double quotes inside the brackets, e.g. "
    "`B{\"Is det(M) = 0?\"}` not `B{Is det(M) = 0?}`. Unquoted punctuation "
    "is a parser error.\n"
    "- Function plots via a ```plot fence, line-based spec:\n"
    "  `plot: x^2` / `plot: 2*x; color=red` / `xdomain: [-3, 3]` / "
    "`ydomain: [-1, 9]` / `title: ...`. Multiple `plot:` lines stack on the "
    "same axes. Use for any concrete function in calculus, algebra, "
    "signals, or optimization.\n"
    "- GeoGebra interactives via `::geogebra{id=\"MATERIAL_ID\"}` — only IDs "
    "you genuinely know exist; never invent one.\n"
    "- Theorem callouts via `:::` container directives. Available names: "
    "`theorem`, `definition`, `proof`, `lemma`, `corollary`, `proposition`, "
    "`example`, `remark`, `note`, `tip`, `warning`. Example:\n"
    "  :::theorem\n"
    "  If $f$ is continuous on $[a,b]$ and differentiable on $(a,b)$, then "
    "$\\exists\\, c \\in (a,b)$ with $f'(c) = \\tfrac{f(b)-f(a)}{b-a}$.\n"
    "  :::\n"
    "  Students should recognize \"Definition\" vs \"Theorem\" vs \"Proof\" "
    "at a glance, as in a textbook.\n"
    "Be deliberate, not decorative. A short conversational turn stays plain. "
    "A derivation, comparison, algorithm, or worked example should use the "
    "richest format that fits.\n\n"
)

# The shared preamble is identical across modes so a prompt-version bump
# in shared guidance shows up as a hash change for every mode at once.
_SHARED_PREAMBLE = (
    "You are Sapling, an AI tutor. You help a student build mastery in "
    "whatever they are studying — their coursework first, and any academic "
    "topic they bring you. You have tools to fetch the student's progress, "
    "search their uploaded course documents, and update their knowledge "
    "graph mastery scores. Use tools when relevant — don't fabricate "
    "context.\n\n"
    "SCOPE: answer any academic question the student asks, fully, from your "
    "own knowledge. Never say or imply that a topic is outside the course, "
    "not in the syllabus, or not in the course description. Never say you "
    "can \"only\" discuss some subject. Do not comment on what the course "
    "does or does not cover unless the student asks about the course "
    "itself. Context blocks in the message are optional background, never a "
    "limit on what you may teach.\n\n"
    "Tone: warm, concise, no filler. Use math/code blocks where helpful "
    "(LaTeX `$x^2$`, ```mermaid```, ```plot```). Don't over-explain.\n\n"
    + _FORMATTING_TOOLKIT
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
