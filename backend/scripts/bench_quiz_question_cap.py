"""Offline benchmark behind the #540 A2 question-cap decision.

Measures wall-clock latency + token usage of quiz generation on
gemini-2.5-flash-lite at schema caps 10 / 15 / 20, using structurally
identical copies of agents/quiz.py's Quiz schema (same QuizQuestion
fields, no tools). Two questions it answers:

1. Does a >10 cap even SERVE? agents/quiz.py:77-80 records that the
   original 20-cap schema tripped Gemini's constrained-decoding
   "too many states for serving" on flash-lite and had to be cut to 10.
2. If it serves, what do 15- and 20-question generations cost in
   latency and tokens versus 10?

Run from backend/ with GEMINI_API_KEY in .env:

    venv/bin/python -m scripts.bench_quiz_question_cap

Offline benchmark only — never import from application code (same rule
as scripts/_raw_gemini.py). Results are recorded in the RESULTS block
below and referenced by services/quiz_config.py's cap comment.

RESULTS (2026-08-12, gemini-2.5-flash-lite, 2 runs per cap):
    cap=10: 4.6s / 5.6s (median 5.1s), in=260 out=1445-1557 tokens,
            delivered 10/10 both runs.
    cap=15: BOTH runs rejected before generation — HTTP 400
            INVALID_ARGUMENT "schema produces a constraint that has too
            many states for serving".
    cap=20: same 400 rejection, both runs.

Conclusion: 10 is the hard ceiling for a single structured call on
flash-lite — 15+ is not slower, it is unservable. Raising the cap means
a model-tier change or batched generation, which is #537 revamp scope.
"""

import asyncio
import statistics
import sys
import time
from typing import Literal

from dotenv import load_dotenv

load_dotenv()

from pydantic import BaseModel, Field  # noqa: E402
from pydantic_ai import Agent  # noqa: E402


class BenchQuizQuestion(BaseModel):
    """Structural copy of agents/quiz.py::QuizQuestion (kept in sync by hand;
    this is a bench, not a contract)."""

    question: str
    type: Literal["multiple_choice"]
    difficulty: Literal["easy", "medium", "hard"]
    options: list[str] = Field(min_length=4, max_length=4)
    correct_answer: str
    explanation: str
    concept: str


PROMPT = (
    "You generate multiple-choice quizzes. 4 options each, exactly one "
    "correct; correct_answer must appear verbatim in options; explanation "
    "is 1-3 sentences."
)

CONCEPT_MSG = (
    "Generate {n} medium questions on the concept 'gradient descent' for an "
    "undergraduate machine-learning student. The concept field of every "
    "question must be 'gradient descent'."
)

RUNS_PER_CAP = 2
CAPS = (10, 15, 20)
MODEL = "gemini-2.5-flash-lite"


def _agent_for_cap(cap: int) -> Agent:
    class BenchQuiz(BaseModel):
        questions: list[BenchQuizQuestion] = Field(min_length=1, max_length=cap)

    return Agent(
        model=f"google-gla:{MODEL}",
        output_type=BenchQuiz,
        system_prompt=PROMPT,
    )


async def bench_cap(cap: int) -> None:
    agent = _agent_for_cap(cap)
    latencies, in_tokens, out_tokens, counts = [], [], [], []
    for run in range(RUNS_PER_CAP):
        t0 = time.perf_counter()
        try:
            result = await agent.run(CONCEPT_MSG.format(n=cap))
        except Exception as e:  # serving rejection is a *result* here, not a bug
            print(f"cap={cap} run={run + 1}: FAILED — {type(e).__name__}: {e}")
            continue
        dt = time.perf_counter() - t0
        usage = result.usage()
        latencies.append(dt)
        in_tokens.append(usage.input_tokens or 0)
        out_tokens.append(usage.output_tokens or 0)
        counts.append(len(result.output.questions))
        print(
            f"cap={cap} run={run + 1}: {dt:.1f}s, "
            f"in={usage.input_tokens} out={usage.output_tokens} "
            f"questions={len(result.output.questions)}"
        )
    if latencies:
        print(
            f"cap={cap} SUMMARY: median {statistics.median(latencies):.1f}s, "
            f"mean in={statistics.mean(in_tokens):.0f} "
            f"out={statistics.mean(out_tokens):.0f} "
            f"delivered={counts}"
        )
    else:
        print(f"cap={cap} SUMMARY: no successful runs (schema likely rejected)")


async def main() -> None:
    for cap in CAPS:
        await bench_cap(cap)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
