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

    # NOTE: ADR 0005 originally specified 3 difficulty × 2 question type
    # (MCQ + short answer). Short answer was dropped during refactor #2
    # because the frontend grade path has no UI for free-text answers
    # and `submit_quiz` grades by option-label lookup. The 3 cases below
    # replace the original short-answer cases with additional MCQ
    # coverage at the same difficulty levels — total stays at 8.
    # Revisit when real short-answer grading exists (LLM-judged or
    # fuzzy-match).

    # ── Easy × MCQ (extra coverage) ───────────────────────────────────────
    Case(
        name="easy_mcq_physics_definitions",
        inputs=(
            "Course: PHYS 101. Generate 3 easy multiple-choice questions "
            "covering Newton's First Law, Kinetic Energy, and Momentum. "
            "Each question should test a definitional understanding."
        ),
        metadata={
            "expected_count": 3,
            "expected_difficulty": "easy",
            "expected_type": "multiple_choice",
            "concepts": ["Newton's First Law", "Kinetic Energy", "Momentum"],
        },
    ),

    # ── Medium × MCQ (extra coverage — econ) ───────────────────────────────
    Case(
        name="medium_mcq_econ",
        inputs=(
            "Course: ECON 201. Generate 3 medium multiple-choice questions "
            "covering Marginal Cost, Price Elasticity of Demand, and "
            "Comparative Advantage. Use distractors that reflect common "
            "confusions between these concepts."
        ),
        metadata={
            "expected_count": 3,
            "expected_difficulty": "medium",
            "expected_type": "multiple_choice",
            "concepts": ["Marginal Cost", "Price Elasticity of Demand", "Comparative Advantage"],
        },
    ),

    # ── Hard × MCQ (extra coverage — theory of computation) ────────────────
    Case(
        name="hard_mcq_theory_of_computation",
        inputs=(
            "Course: MATH 320. Generate 2 hard multiple-choice questions "
            "covering the Pumping Lemma and Decidability. Distractors "
            "should target the most common misapplications of these "
            "results."
        ),
        metadata={
            "expected_count": 2,
            "expected_difficulty": "hard",
            "expected_type": "multiple_choice",
            "concepts": ["Pumping Lemma", "Decidability"],
        },
    ),
]

assert len(CASES) == 8, f"Expected 8 cases per ADR 0005, got {len(CASES)}"
# All cases are MCQ today — short_answer dropped pending frontend support.
assert all(
    c.metadata and c.metadata.get("expected_type") == "multiple_choice"
    for c in CASES
), "All quiz_agent eval cases must be multiple_choice (see refactor #2 fixes)"


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
            ConceptCoverageEvaluator(),
        ],
    )


if __name__ == "__main__":
    cli_main(make_dataset, _run)
