"""pydantic-evals cases for chat_tutor_agent (Socratic / Expository / TeachBack).

Run via tests.evals._replay (record/replay/live):
    cd backend
    SAPLING_EVAL_MODE=record python tests/evals/chat_tutor.py
    SAPLING_EVAL_MODE=replay python tests/evals/chat_tutor.py

Each case input is a (mode, user_message) tuple. The adapter dispatches to
the right mode-specific agent via `agent_for_mode(mode)`. Cassette key is
the case name (NOT the input), so cassettes capture per-mode behavior even
when two modes happen to share the same user message.

Why ChatReply wraps the str output: the shared `run_with_cassette` helper
calls `output_model.model_validate(body)` on replayed JSON. `str` has no
such method, so we either (a) wrap the agent's str reply in a tiny
Pydantic model for the eval layer, or (b) bypass the helper. We chose (a)
plus a local adapter so cassettes round-trip cleanly without modifying
any file outside `backend/tests/evals/chat_tutor.py`.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

# `python tests/evals/chat_tutor.py` from backend/ — import path setup.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).parent))  # for _replay sibling import

from pydantic import BaseModel
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext

from agents.chat_tutor import agent_for_mode
from _replay import MODE, cli_main, load_cassette, make_deps, save_cassette


# Input tuple: (mode, user_message). Output is the agent's string reply
# wrapped in ChatReply so cassettes round-trip via model_validate.
ChatInput = tuple[str, str]


class ChatReply(BaseModel):
    """Thin wrapper so model_validate-based cassette hydration works for
    plain-text chat output."""

    text: str


# ── Evaluators ──────────────────────────────────────────────────────────────


@dataclass
class NonEmptyEvaluator(Evaluator[ChatInput, ChatReply]):
    """Reply must be at least 20 chars. Empty/near-empty replies fail."""

    def evaluate(self, ctx: EvaluatorContext[ChatInput, ChatReply]) -> float:
        text = (ctx.output.text if ctx.output else "") or ""
        return 1.0 if len(text.strip()) >= 20 else 0.0


@dataclass
class SocraticEndsWithQuestionEvaluator(Evaluator[ChatInput, ChatReply]):
    """Socratic mode prompt requires every reply to end with a question."""

    def evaluate(self, ctx: EvaluatorContext[ChatInput, ChatReply]) -> float:
        mode = ctx.inputs[0]
        if mode != "socratic":
            return 1.0
        reply = (ctx.output.text if ctx.output else "").rstrip()
        return 1.0 if reply.endswith("?") else 0.0


@dataclass
class ExpositoryHasStructureEvaluator(Evaluator[ChatInput, ChatReply]):
    """Expository replies should be substantive (>= 200 chars) AND not
    end with a question (the prompt says don't ask questions back unless
    the user's prompt was ambiguous)."""

    def evaluate(self, ctx: EvaluatorContext[ChatInput, ChatReply]) -> float:
        mode = ctx.inputs[0]
        if mode != "expository":
            return 1.0
        reply = (ctx.output.text if ctx.output else "").strip()
        long_enough = len(reply) >= 200
        not_question_loop = not reply.rstrip().endswith("?")
        return 1.0 if (long_enough and not_question_loop) else 0.0


@dataclass
class TeachBackProbesEvaluator(Evaluator[ChatInput, ChatReply]):
    """TeachBack mode should both validate parts of the student's
    explanation AND end with a probing question. We check the
    end-with-? half here (the validate half is qualitative and judged
    in the live record session)."""

    def evaluate(self, ctx: EvaluatorContext[ChatInput, ChatReply]) -> float:
        mode = ctx.inputs[0]
        if mode != "teachback":
            return 1.0
        reply = (ctx.output.text if ctx.output else "").rstrip()
        return 1.0 if reply.endswith("?") else 0.0


@dataclass
class NoToolMisuseEvaluator(Evaluator[ChatInput, ChatReply]):
    """The agent should NOT mention raw tool names in its reply
    (`read_user_progress`, `apply_graph_update`, etc.). Tools are
    invisible to the student."""

    BANNED_SUBSTRINGS = (
        "read_user_progress",
        "search_course_materials",
        "read_session_history",
        "apply_graph_update_tool",
        "apply_concepts_to_graph",
        "function_tool",
    )

    def evaluate(self, ctx: EvaluatorContext[ChatInput, ChatReply]) -> float:
        reply = (ctx.output.text if ctx.output else "").lower()
        for banned in self.BANNED_SUBSTRINGS:
            if banned.lower() in reply:
                return 0.0
        return 1.0


# ── Cases (5 per mode = 15 total) ───────────────────────────────────────────

CASES: list[Case[ChatInput, ChatReply]] = [
    # ── SOCRATIC ────────────────────────────────────────────────────────────
    Case(
        name="socratic_intro_calculus",
        inputs=(
            "socratic",
            "I keep getting derivatives mixed up with integrals. Can you help?",
        ),
        metadata={"mode": "socratic"},
    ),
    Case(
        name="socratic_python_recursion",
        inputs=(
            "socratic",
            "I don't get how recursion works in Python.",
        ),
        metadata={"mode": "socratic"},
    ),
    Case(
        name="socratic_chemistry_balancing",
        inputs=(
            "socratic",
            "How do you balance a redox equation?",
        ),
        metadata={"mode": "socratic"},
    ),
    Case(
        name="socratic_history_themes",
        inputs=(
            "socratic",
            "Why did the Roman Empire fall?",
        ),
        metadata={"mode": "socratic"},
    ),
    Case(
        name="socratic_open_followup",
        inputs=(
            "socratic",
            "I think I get it now — derivatives are just slope.",
        ),
        metadata={"mode": "socratic"},
    ),

    # ── EXPOSITORY ──────────────────────────────────────────────────────────
    Case(
        name="expository_explain_big_o",
        inputs=(
            "expository",
            "Explain Big-O notation.",
        ),
        metadata={"mode": "expository"},
    ),
    Case(
        name="expository_explain_photosynthesis",
        inputs=(
            "expository",
            "Explain photosynthesis at the cellular level.",
        ),
        metadata={"mode": "expository"},
    ),
    Case(
        name="expository_explain_dependency_injection",
        inputs=(
            "expository",
            "What is dependency injection?",
        ),
        metadata={"mode": "expository"},
    ),
    Case(
        name="expository_explain_supply_demand",
        inputs=(
            "expository",
            "Explain how supply and demand determine price.",
        ),
        metadata={"mode": "expository"},
    ),
    Case(
        name="expository_explain_kantian_ethics",
        inputs=(
            "expository",
            "What is Kantian ethics?",
        ),
        metadata={"mode": "expository"},
    ),

    # ── TEACHBACK ──────────────────────────────────────────────────────────
    Case(
        name="teachback_correct_concept",
        inputs=(
            "teachback",
            "Let me explain mitosis: a cell duplicates its DNA, then "
            "splits into two identical daughter cells. Each one has the "
            "same chromosomes as the original.",
        ),
        metadata={"mode": "teachback"},
    ),
    Case(
        name="teachback_partial_correct",
        inputs=(
            "teachback",
            "OK so a closure is a function that has variables. Like, "
            "you can use them inside it.",
        ),
        metadata={"mode": "teachback"},
    ),
    Case(
        name="teachback_misconception",
        inputs=(
            "teachback",
            "Newton's first law says objects in motion stay in motion "
            "unless you push them. Force makes things keep moving.",
        ),
        metadata={"mode": "teachback"},
    ),
    Case(
        name="teachback_advanced",
        inputs=(
            "teachback",
            "The Pumping Lemma proves a language isn't regular by "
            "showing that strings of length p can be split such that "
            "the middle can be repeated and stay in the language.",
        ),
        metadata={"mode": "teachback"},
    ),
    Case(
        name="teachback_minimal",
        inputs=(
            "teachback",
            "Recursion is when a function calls itself.",
        ),
        metadata={"mode": "teachback"},
    ),
]

assert len(CASES) == 15, f"Expected 15 cases (5 per mode x 3 modes), got {len(CASES)}"

# Per-mode breakdown sanity check (5 / 5 / 5).
_MODE_COUNTS: dict[str, int] = {"socratic": 0, "expository": 0, "teachback": 0}
for _c in CASES:
    _MODE_COUNTS[_c.inputs[0]] = _MODE_COUNTS.get(_c.inputs[0], 0) + 1
assert _MODE_COUNTS == {"socratic": 5, "expository": 5, "teachback": 5}, (
    f"Expected 5 cases per mode, got {_MODE_COUNTS}"
)


# ── Adapter (replay layer) ──────────────────────────────────────────────────

# Lookup: (mode, user_message) -> case_name. The case name keys the
# cassette so two modes can share a user message without colliding.
_INPUT_TO_NAME: dict[ChatInput, str] = {c.inputs: c.name for c in CASES}


async def _run(case_input: ChatInput) -> ChatReply:
    """Local adapter that mirrors `_replay.run_with_cassette` but wraps
    the agent's plain-text reply in `ChatReply` so cassettes round-trip
    via Pydantic's `model_validate`. Inlined here (rather than reusing
    the shared helper) because the shared helper assumes the agent's
    output is already a Pydantic model."""

    mode, user_message = case_input
    case_name = _INPUT_TO_NAME.get(case_input, "unknown")
    dataset = "chat_tutor"

    if MODE == "replay":
        body = load_cassette(dataset, case_name)
        if body is None:
            raise RuntimeError(
                f"No cassette for {dataset}/{case_name}. "
                f"Run with SAPLING_EVAL_MODE=record to capture it."
            )
        # Cassettes recorded as plain strings (legacy) or as the
        # ChatReply dict (new) both round-trip cleanly.
        if isinstance(body, str):
            return ChatReply(text=body)
        return ChatReply.model_validate(body)

    deps = make_deps()
    agent = agent_for_mode(mode)
    result = await agent.run(user_message, deps=deps)
    reply_text = result.output if isinstance(result.output, str) else str(result.output)
    output = ChatReply(text=reply_text)

    if MODE == "record":
        save_cassette(dataset, case_name, output)

    return output


def make_dataset() -> Dataset[ChatInput, ChatReply]:
    return Dataset(
        name="chat_tutor",
        cases=CASES,
        evaluators=[
            NonEmptyEvaluator(),
            SocraticEndsWithQuestionEvaluator(),
            ExpositoryHasStructureEvaluator(),
            TeachBackProbesEvaluator(),
            NoToolMisuseEvaluator(),
        ],
    )


if __name__ == "__main__":
    cli_main(make_dataset, _run)
