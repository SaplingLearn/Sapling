# Sub-agent D — Build chat_tutor eval set

Build a `pydantic-evals` dataset for the new `chat_tutor_agent`. WRITE the
file, verify it imports, report back. Do NOT run against live Gemini —
cassettes get recorded later.

Repo: `/Users/josegaelcruzlopez/Documents/Startup_Projects /Sapling`
Branch: `refactor/3-chat-tutor`

## Why

Refactor #3 needs eval coverage equivalent to refactor #1 (document
classification, 25 cases) and refactor #2 (quiz generation, 8 cases). For
chat tutor, expected scope is **15 cases × 3 modes** with mode-specific
evaluators — though the mode dimension means we can keep the case count
sensible (5 cases × 3 modes = 15).

## What to read first

- `backend/tests/evals/quiz_generation.py` — closest pattern. Mirror its
  shape (cases, evaluators, `run_with_cassette` adapter, `cli_main`).
- `backend/tests/evals/_replay.py` — replay/record/live driver. Use as-is.
- `backend/agents/chat_tutor.py` — when sub-agent B finishes, you'll
  import `agent_for_mode` and the three mode-specific agents from here.

## What to write

### `backend/tests/evals/chat_tutor.py`

15 cases — 5 per mode. Each case input is a tuple of (mode, user_message).
The adapter dispatches to the right mode's agent.

```python
"""pydantic-evals cases for chat_tutor_agent (Socratic / Expository / TeachBack)."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).parent))

from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext

from agents.chat_tutor import agent_for_mode
from _replay import run_with_cassette, cli_main


# Input tuple: (mode, user_message). Output is the agent's str reply.
ChatInput = tuple[str, str]


# ── Evaluators ──────────────────────────────────────────────────────────────

@dataclass
class NonEmptyEvaluator(Evaluator[ChatInput, str]):
    """Reply must be at least 20 chars. Empty/near-empty replies fail."""

    def evaluate(self, ctx: EvaluatorContext[ChatInput, str]) -> float:
        return 1.0 if len((ctx.output or "").strip()) >= 20 else 0.0


@dataclass
class SocraticEndsWithQuestionEvaluator(Evaluator[ChatInput, str]):
    """Socratic mode prompt requires every reply to end with a question."""

    def evaluate(self, ctx: EvaluatorContext[ChatInput, str]) -> float:
        mode = ctx.inputs[0]
        if mode != "socratic":
            return 1.0
        reply = (ctx.output or "").rstrip()
        return 1.0 if reply.endswith("?") else 0.0


@dataclass
class ExpositoryHasStructureEvaluator(Evaluator[ChatInput, str]):
    """Expository replies should be substantive — at least 200 chars
    AND not end with a question (the prompt says don't ask questions
    back unless the user's prompt was ambiguous)."""

    def evaluate(self, ctx: EvaluatorContext[ChatInput, str]) -> float:
        mode = ctx.inputs[0]
        if mode != "expository":
            return 1.0
        reply = (ctx.output or "").strip()
        long_enough = len(reply) >= 200
        not_question_loop = not reply.rstrip().endswith("?")
        return 1.0 if (long_enough and not_question_loop) else 0.0


@dataclass
class TeachBackProbesEvaluator(Evaluator[ChatInput, str]):
    """TeachBack mode should both validate parts of the student's
    explanation AND end with a probing question. We check the
    end-with-? half here (the validate half is qualitative and judged
    in the live record session)."""

    def evaluate(self, ctx: EvaluatorContext[ChatInput, str]) -> float:
        mode = ctx.inputs[0]
        if mode != "teachback":
            return 1.0
        reply = (ctx.output or "").rstrip()
        return 1.0 if reply.endswith("?") else 0.0


@dataclass
class NoToolMisuseEvaluator(Evaluator[ChatInput, str]):
    """The agent should NOT mention raw tool names in its reply
    (`read_user_progress`, `apply_graph_update`, etc.). Tools are
    invisible to the student."""

    BANNED_SUBSTRINGS = (
        "read_user_progress", "search_course_materials",
        "read_session_history", "apply_graph_update_tool",
        "apply_concepts_to_graph", "function_tool",
    )

    def evaluate(self, ctx: EvaluatorContext[ChatInput, str]) -> float:
        reply = (ctx.output or "").lower()
        for banned in self.BANNED_SUBSTRINGS:
            if banned.lower() in reply:
                return 0.0
        return 1.0


# ── Cases (5 per mode = 15 total) ───────────────────────────────────────────

CASES: list[Case[ChatInput, str]] = [
    # ── SOCRATIC ────────────────────────────────────────────────────────────
    Case(
        name="socratic_intro_calculus",
        inputs=("socratic",
                "I keep getting derivatives mixed up with integrals. Can you help?"),
        metadata={"mode": "socratic"},
    ),
    Case(
        name="socratic_python_recursion",
        inputs=("socratic",
                "I don't get how recursion works in Python."),
        metadata={"mode": "socratic"},
    ),
    Case(
        name="socratic_chemistry_balancing",
        inputs=("socratic",
                "How do you balance a redox equation?"),
        metadata={"mode": "socratic"},
    ),
    Case(
        name="socratic_history_themes",
        inputs=("socratic",
                "Why did the Roman Empire fall?"),
        metadata={"mode": "socratic"},
    ),
    Case(
        name="socratic_open_followup",
        inputs=("socratic",
                "I think I get it now — derivatives are just slope."),
        metadata={"mode": "socratic"},
    ),

    # ── EXPOSITORY ──────────────────────────────────────────────────────────
    Case(
        name="expository_explain_big_o",
        inputs=("expository",
                "Explain Big-O notation."),
        metadata={"mode": "expository"},
    ),
    Case(
        name="expository_explain_photosynthesis",
        inputs=("expository",
                "Explain photosynthesis at the cellular level."),
        metadata={"mode": "expository"},
    ),
    Case(
        name="expository_explain_dependency_injection",
        inputs=("expository",
                "What is dependency injection?"),
        metadata={"mode": "expository"},
    ),
    Case(
        name="expository_explain_supply_demand",
        inputs=("expository",
                "Explain how supply and demand determine price."),
        metadata={"mode": "expository"},
    ),
    Case(
        name="expository_explain_kantian_ethics",
        inputs=("expository",
                "What is Kantian ethics?"),
        metadata={"mode": "expository"},
    ),

    # ── TEACHBACK ──────────────────────────────────────────────────────────
    Case(
        name="teachback_correct_concept",
        inputs=("teachback",
                "Let me explain mitosis: a cell duplicates its DNA, then "
                "splits into two identical daughter cells. Each one has the "
                "same chromosomes as the original."),
        metadata={"mode": "teachback"},
    ),
    Case(
        name="teachback_partial_correct",
        inputs=("teachback",
                "OK so a closure is a function that has variables. Like, "
                "you can use them inside it."),
        metadata={"mode": "teachback"},
    ),
    Case(
        name="teachback_misconception",
        inputs=("teachback",
                "Newton's first law says objects in motion stay in motion "
                "unless you push them. Force makes things keep moving."),
        metadata={"mode": "teachback"},
    ),
    Case(
        name="teachback_advanced",
        inputs=("teachback",
                "The Pumping Lemma proves a language isn't regular by "
                "showing that strings of length p can be split such that "
                "the middle can be repeated and stay in the language."),
        metadata={"mode": "teachback"},
    ),
    Case(
        name="teachback_minimal",
        inputs=("teachback",
                "Recursion is when a function calls itself."),
        metadata={"mode": "teachback"},
    ),
]

assert len(CASES) == 15, f"Expected 15 cases (5 per mode × 3 modes), got {len(CASES)}"


# ── Adapter ─────────────────────────────────────────────────────────────────

# The agent's input is a string (the user message); the adapter picks the
# right mode-specific agent based on the case input tuple. Cassette key is
# the case name, NOT the input — we want the cassette to capture per-mode
# behavior even when two modes share the same user message.

async def _run(case_input: ChatInput) -> str:
    mode, user_message = case_input
    case_name = next(c.name for c in CASES if c.inputs == case_input)
    agent = agent_for_mode(mode)

    return await run_with_cassette(
        dataset="chat_tutor",
        case_name=case_name,
        agent=agent,
        case_input=user_message,   # what the agent sees
        output_model=str,           # plain str output for chat
    )


def make_dataset() -> Dataset[ChatInput, str]:
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
```

NOTE: `run_with_cassette` accepts an `output_model` (Pydantic model class)
to hydrate replayed JSON back into a typed object. For str output we'd
need the helper to handle the no-model case. Read `tests/evals/_replay.py`
first — if `output_model=str` doesn't work, either:
- Wrap chat replies in `class ChatReply(BaseModel): text: str` for the eval
  layer only (slight indirection, but lets cassettes round-trip cleanly),
- Or update `_replay.run_with_cassette` to short-circuit on `output_model=str`.

Pick whichever fits the existing helper's contract.

## Verify

After writing the file:
```bash
cd "/Users/josegaelcruzlopez/Documents/Startup_Projects /Sapling/backend"
python -c "import ast; ast.parse(open('tests/evals/chat_tutor.py').read()); print('parses OK')"
grep -c '^    Case(' tests/evals/chat_tutor.py
```

Once sub-agent B finishes:
```bash
python -c "
import sys, importlib.util
sys.path.insert(0, '.')
sys.path.insert(0, 'tests/evals')
spec = importlib.util.spec_from_file_location('chat_eval', 'tests/evals/chat_tutor.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print(f'cases: {len(m.make_dataset().cases)}')
"
```

DO NOT actually run against live Gemini — replay infra exists; cassettes
get recorded by the user once the agent path is on main.

## Constraints

- DO NOT modify `backend/agents/chat_tutor.py` (sub-agent B's file).
- DO NOT modify `backend/agents/tools/chat_context.py` (sub-agent A).
- DO NOT modify `backend/routes/learn.py`.
- DO NOT commit. No ADRs.

## Report

- File created with line count.
- Case count (must be exactly 15).
- Per-mode breakdown (5 socratic / 5 expository / 5 teachback — assert
  this in the file too).
- Whether `output_model=str` works in `run_with_cassette` or you needed
  a wrapper.
- All 5 evaluators wired into `make_dataset()`.
