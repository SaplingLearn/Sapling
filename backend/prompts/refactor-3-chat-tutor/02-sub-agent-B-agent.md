# Sub-agent B — Build chat_tutor_agent

Build the new `chat_tutor_agent` that replaces `routes/learn.py::build_system_prompt`'s
single-string approach with a typed Pydantic AI agent. WRITE the changes,
run import tests, report back.

Repo: `/Users/josegaelcruzlopez/Documents/Startup_Projects /Sapling`
Branch: `refactor/3-chat-tutor`

## Why

ADR 0005 explicitly named chat tutor as refactor #3 ("most invasive — do
after quiz refactor lands"). That's now. Three teaching modes (Socratic,
Expository, TeachBack) need to keep working. Multi-turn message history
needs to keep working. Mastery-update tool calls need to keep working.

## What to read first

- `backend/routes/learn.py:152` — current `build_system_prompt`. Read all of it.
  Note what it stuffs into the prompt: course context, recent session
  summaries, graph state, mode-specific guidance. Each piece becomes
  either (a) a tool call from the agent, (b) a lookup the route does
  before passing message history to the agent, or (c) part of the
  agent's static system prompt.
- `backend/agents/quiz.py` — pattern to mirror (typed output, tool registration,
  `_PROMPT_HASH`, `metadata=`).
- `backend/agents/_providers.py` — add `"chat_tutor"` to `AgentTask` Literal
  and `_DEFAULTS` dict.
- `backend/agents/tools/chat_context.py` (sub-agent A's file) — three new tools
  to register on this agent.
- `backend/agents/tools/graph.py` — `apply_graph_update_tool` (already exists;
  register it on chat_tutor too so the tutor can update mastery directly).
- `backend/services/gemini_service.py::call_gemini_multiturn` — what the legacy
  path does today; preserve the same multi-turn semantic.
- Main commits `6f431d6` (`feat(learn): use gemini-2.5-pro for tutor chat`)
  and `e146125` (`fix(learn): allow thinking on gemini-2.5-pro multiturn calls`)
  — chat tutor on main is on `gemini-2.5-pro`. New agent's task default
  should match.

## What to write

### 1. Add `chat_tutor` to `agents/_providers.py`

```python
AgentTask = Literal["classifier", "summary", "concepts", "syllabus", "quiz", "chat_tutor"]

_DEFAULTS: dict[AgentTask, str] = {
    ...,
    "chat_tutor": "gemini-2.5-pro",  # matches main's tutor default after PR #73
}
```

Override env var: `SAPLING_MODEL_CHAT_TUTOR`.

### 2. New file: `backend/agents/chat_tutor.py`

```python
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
    search_course_materials_tool,
    read_session_history_tool,
    read_user_progress_tool,
)
from agents.tools.graph import apply_graph_update_tool


TutorMode = Literal["socratic", "expository", "teachback"]


# ── System prompts (one per mode) ──────────────────────────────────────────

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

# Hash of the SHARED preamble + each mode's body, for span versioning.
_PROMPT_HASHES: dict[TutorMode, str] = {
    mode: hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]
    for mode, prompt in _PROMPTS.items()
}


# ── Agent (one per mode, sharing the same tool surface) ────────────────────

# Output type is plain str — chat tutor produces free-form Markdown that
# the frontend renders via MarkdownChat. No structured output here; that's
# reserved for routes that grade or extract.

_TOOLS = [
    search_course_materials_tool,
    read_session_history_tool,
    read_user_progress_tool,
    apply_graph_update_tool,
]


def _build_agent(mode: TutorMode) -> Agent:
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


def agent_for_mode(mode: str) -> Agent:
    """Return the agent instance for a given mode string. Falls back to
    Socratic if the mode is unrecognized — same default the legacy route
    used."""
    normalized = (mode or "socratic").lower()
    return {
        "socratic": socratic_agent,
        "expository": expository_agent,
        "teachback": teachback_agent,
    }.get(normalized, socratic_agent)
```

### 3. Smoke test

`backend/tests/test_chat_tutor_imports.py`:

```python
"""Import smoke tests for chat_tutor agents. Live-Gemini behavior is
covered by the eval set in tests/evals/chat_tutor.py."""

from agents.chat_tutor import (
    socratic_agent, expository_agent, teachback_agent, agent_for_mode,
    _PROMPT_HASHES,
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
    assert agent_for_mode(None) is socratic_agent  # type: ignore[arg-type]


def test_all_four_tools_registered():
    """Chat tutor needs three context tools + the graph-update tool."""
    expected = {
        "search_course_materials_tool",
        "read_session_history_tool",
        "read_user_progress_tool",
        "apply_graph_update_tool",
    }
    # Pydantic AI 1.89's tool registry is at agent._function_toolset.tools
    # (dict keyed by tool name) — see commit a850d31 for the gotcha.
    tool_names = set(socratic_agent._function_toolset.tools.keys())
    assert expected == tool_names
```

## Verify
```bash
cd "/Users/josegaelcruzlopez/Documents/Startup_Projects /Sapling/backend"
python -m pytest tests/test_chat_tutor_imports.py -q --no-header
```

All tests must pass.

## Constraints

- DO NOT modify `backend/agents/tools/chat_context.py` (sub-agent A's file —
  imports of `*_tool` symbols should just work once A finishes).
- DO NOT modify `backend/routes/learn.py` (sub-agent C will).
- DO NOT modify `backend/tests/evals/chat_tutor.py` (sub-agent D's file).
- DO NOT commit. No ADRs.
- The output type stays `str` — multi-turn chat is text. Don't try to
  introduce structured output here.

## Report

- Files created/modified with line counts.
- The three `_PROMPT_HASH` values (one per mode).
- Test count + pass/fail.
- Anything that didn't fit (Pydantic AI's `Agent` constructor signature
  changed, or the `_function_toolset` attribute moved).
