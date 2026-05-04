"""pydantic-evals cases for the quiz_agent.

Run via tests.evals._replay (record/replay/live):
    cd backend
    SAPLING_EVAL_MODE=record python tests/evals/quiz_generation.py
    SAPLING_EVAL_MODE=replay python tests/evals/quiz_generation.py
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

# `python tests/evals/quiz_generation.py` from backend/ — import path setup.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).parent))  # for _replay sibling import

from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext

from agents.quiz import quiz_agent, Quiz, QuizQuestion
from _replay import run_with_cassette, cli_main


# ── Evaluators ──────────────────────────────────────────────────────────────

@dataclass
class QuestionCountEvaluator(Evaluator[str, Quiz]):
    """Exact match on the requested number of questions (in metadata)."""

    def evaluate(self, ctx: EvaluatorContext[str, Quiz]) -> float:
        expected = (ctx.metadata or {}).get("expected_count")
        if expected is None:
            return 1.0  # no constraint
        return 1.0 if len(ctx.output.questions) == expected else 0.0


@dataclass
class DifficultyMixEvaluator(Evaluator[str, Quiz]):
    """All questions land at the requested difficulty (single-difficulty
    cases only). Cases with `expected_difficulty=None` skip this check."""

    def evaluate(self, ctx: EvaluatorContext[str, Quiz]) -> float:
        target = (ctx.metadata or {}).get("expected_difficulty")
        if target is None:
            return 1.0
        matches = sum(1 for q in ctx.output.questions if q.difficulty == target)
        total = max(1, len(ctx.output.questions))
        return matches / total


@dataclass
class TypeMixEvaluator(Evaluator[str, Quiz]):
    """All questions are the requested type (single-type cases only)."""

    def evaluate(self, ctx: EvaluatorContext[str, Quiz]) -> float:
        target = (ctx.metadata or {}).get("expected_type")
        if target is None:
            return 1.0
        matches = sum(1 for q in ctx.output.questions if q.type == target)
        total = max(1, len(ctx.output.questions))
        return matches / total


@dataclass
class MultipleChoiceShapeEvaluator(Evaluator[str, Quiz]):
    """Every multiple_choice question has 3-6 options AND the
    correct_answer appears verbatim in those options."""

    def evaluate(self, ctx: EvaluatorContext[str, Quiz]) -> float:
        mc = [q for q in ctx.output.questions if q.type == "multiple_choice"]
        if not mc:
            return 1.0
        ok = sum(
            1 for q in mc
            if 3 <= len(q.options) <= 6 and q.correct_answer in q.options
        )
        return ok / len(mc)


@dataclass
class ShortAnswerShapeEvaluator(Evaluator[str, Quiz]):
    """Every short_answer question has options=[] and a non-empty
    correct_answer."""

    def evaluate(self, ctx: EvaluatorContext[str, Quiz]) -> float:
        sa = [q for q in ctx.output.questions if q.type == "short_answer"]
        if not sa:
            return 1.0
        ok = sum(
            1 for q in sa
            if not q.options and q.correct_answer.strip()
        )
        return ok / len(sa)


@dataclass
class ConceptCoverageEvaluator(Evaluator[str, Quiz]):
    """Every question's `concept` field is one of the concepts the
    case's prompt named (declared in metadata)."""

    def evaluate(self, ctx: EvaluatorContext[str, Quiz]) -> float:
        allowed = set((ctx.metadata or {}).get("concepts", []))
        if not allowed:
            return 1.0
        ok = sum(1 for q in ctx.output.questions if q.concept in allowed)
        return ok / max(1, len(ctx.output.questions))


# ── Cases ───────────────────────────────────────────────────────────────────

# Inputs are deliberately small — Gemini reads the prompt + tool results
# (mocked via cassette in CI), so keeping inputs short keeps cassette
# diffs readable.

CASES: list[Case[str, Quiz]] = [
    # ── Easy × MCQ ─────────────────────────────────────────────────────────
    Case(
        name="easy_mcq_intro_calculus",
        inputs=(
            "Course: MATH 101. Generate 3 easy multiple-choice questions "
            "covering Limits, Derivatives, and Continuity. The student "
            "is new to the material; favor definitional questions."
        ),
        metadata={
            "expected_count": 3,
            "expected_difficulty": "easy",
            "expected_type": "multiple_choice",
            "concepts": ["Limits", "Derivatives", "Continuity"],
        },
    ),
    Case(
        name="easy_mcq_basic_biology",
        inputs=(
            "Course: BIO 100. Generate 4 easy multiple-choice questions "
            "covering Cell Membrane, Photosynthesis, Mitosis, Diffusion."
        ),
        metadata={
            "expected_count": 4,
            "expected_difficulty": "easy",
            "expected_type": "multiple_choice",
            "concepts": ["Cell Membrane", "Photosynthesis", "Mitosis", "Diffusion"],
        },
    ),

    # ── Medium × MCQ ───────────────────────────────────────────────────────
    Case(
        name="medium_mcq_data_structures",
        inputs=(
            "Course: CS 201. Generate 3 medium multiple-choice questions "
            "covering Hash Tables, Binary Search Trees, and Big-O Analysis. "
            "Use distractors that reflect common student misconceptions."
        ),
        metadata={
            "expected_count": 3,
            "expected_difficulty": "medium",
            "expected_type": "multiple_choice",
            "concepts": ["Hash Tables", "Binary Search Trees", "Big-O Analysis"],
        },
    ),
    Case(
        name="medium_mcq_organic_chem",
        inputs=(
            "Course: CHEM 230. Generate 3 medium multiple-choice questions "
            "covering Stereochemistry, SN1 vs SN2, and Resonance Structures."
        ),
        metadata={
            "expected_count": 3,
            "expected_difficulty": "medium",
            "expected_type": "multiple_choice",
            "concepts": ["Stereochemistry", "SN1 vs SN2", "Resonance Structures"],
        },
    ),

    # ── Hard × MCQ ─────────────────────────────────────────────────────────
    Case(
        name="hard_mcq_real_analysis",
        inputs=(
            "Course: MATH 411. Generate 2 hard multiple-choice questions "
            "covering Cauchy Sequences and Uniform Convergence. Expect "
            "questions that combine multiple definitions."
        ),
        metadata={
            "expected_count": 2,
            "expected_difficulty": "hard",
            "expected_type": "multiple_choice",
            "concepts": ["Cauchy Sequences", "Uniform Convergence"],
        },
    ),

    # ── Easy × Short Answer ────────────────────────────────────────────────
    Case(
        name="easy_short_answer_definitions",
        inputs=(
            "Course: PHYS 101. Generate 3 easy short-answer questions "
            "covering Newton's First Law, Kinetic Energy, and Momentum. "
            "Each should have a one-sentence canonical answer."
        ),
        metadata={
            "expected_count": 3,
            "expected_difficulty": "easy",
            "expected_type": "short_answer",
            "concepts": ["Newton's First Law", "Kinetic Energy", "Momentum"],
        },
    ),

    # ── Medium × Short Answer ──────────────────────────────────────────────
    Case(
        name="medium_short_answer_econ",
        inputs=(
            "Course: ECON 201. Generate 3 medium short-answer questions "
            "covering Marginal Cost, Price Elasticity of Demand, and "
            "Comparative Advantage."
        ),
        metadata={
            "expected_count": 3,
            "expected_difficulty": "medium",
            "expected_type": "short_answer",
            "concepts": ["Marginal Cost", "Price Elasticity of Demand", "Comparative Advantage"],
        },
    ),

    # ── Hard × Short Answer ────────────────────────────────────────────────
    Case(
        name="hard_short_answer_proofs",
        inputs=(
            "Course: MATH 320. Generate 2 hard short-answer questions "
            "covering the Pumping Lemma and Decidability. Each answer "
            "should require a brief proof sketch."
        ),
        metadata={
            "expected_count": 2,
            "expected_difficulty": "hard",
            "expected_type": "short_answer",
            "concepts": ["Pumping Lemma", "Decidability"],
        },
    ),
]

assert len(CASES) == 8, f"Expected 8 cases per ADR 0005, got {len(CASES)}"


# ── Adapter (replay layer) ──────────────────────────────────────────────────

# Lookup map for case_name from input (input strings are unique).
_INPUT_TO_NAME: dict[str, str] = {c.inputs: c.name for c in CASES}


async def _run(case_input: str) -> Quiz:
    case_name = _INPUT_TO_NAME.get(case_input, "unknown")
    return await run_with_cassette(
        dataset="quiz_generation",
        case_name=case_name,
        agent=quiz_agent,
        case_input=case_input,
        output_model=Quiz,
    )


def make_dataset() -> Dataset[str, Quiz]:
    return Dataset(
        name="quiz_generation",
        cases=CASES,
        evaluators=[
            QuestionCountEvaluator(),
            DifficultyMixEvaluator(),
            TypeMixEvaluator(),
            MultipleChoiceShapeEvaluator(),
            ShortAnswerShapeEvaluator(),
            ConceptCoverageEvaluator(),
        ],
    )


if __name__ == "__main__":
    cli_main(make_dataset, _run)
