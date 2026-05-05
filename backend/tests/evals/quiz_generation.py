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


# Difficulty ordering for the adaptive evaluator. Higher index = harder.
_DIFF_RANK = {"easy": 0, "medium": 1, "hard": 2}


@dataclass
class AdaptiveDifficultyEvaluator(Evaluator[str, Quiz]):
    """Pin the prompt's adaptive-difficulty bound: the average produced
    difficulty must be within ±1 step of the user-requested difficulty
    (in the metadata's `requested_difficulty`). Cases without
    `requested_difficulty` skip this check.

    The agent is *allowed* to step down (struggling student) or step
    up (consistent high accuracy) by one rank. This evaluator catches
    the regression where it overshoots — e.g. requested medium and
    produced all easy AND all hard. The point is the bound, not the
    direction.
    """

    def evaluate(self, ctx: EvaluatorContext[str, Quiz]) -> float:
        requested = (ctx.metadata or {}).get("requested_difficulty")
        if requested is None or not ctx.output.questions:
            return 1.0
        target_rank = _DIFF_RANK.get(requested)
        if target_rank is None:
            return 1.0
        # Compute average rank across produced questions; the bound
        # is "within 1 step of requested." This permits the prompt's
        # one-step adaptive shift in either direction but rejects
        # anything beyond that.
        ranks = [_DIFF_RANK.get(q.difficulty, target_rank) for q in ctx.output.questions]
        avg = sum(ranks) / len(ranks)
        return 1.0 if abs(avg - target_rank) <= 1.0 else 0.0


@dataclass
class SpacedRepetitionConceptEvaluator(Evaluator[str, Quiz]):
    """Pin the prompt's spaced-repetition rule: when metadata names a
    `stale_concept`, at least one question must target it. Cases
    without `stale_concept` skip this check.

    This is the structural sentinel — it doesn't try to verify that
    the agent reasoned about `last_reviewed_at` correctly, just that
    the stale concept didn't get dropped from the question mix entirely
    in favor of the lowest-mastery one.
    """

    def evaluate(self, ctx: EvaluatorContext[str, Quiz]) -> float:
        stale = (ctx.metadata or {}).get("stale_concept")
        if not stale:
            return 1.0
        return 1.0 if any(q.concept == stale for q in ctx.output.questions) else 0.0


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

    # ── Adaptive difficulty (struggling student, request hard) ─────────────
    # Per ADR 0014: when recent_attempts.accuracy is consistently low,
    # the agent is allowed to drop the difficulty mix one step from what
    # the user asked. AdaptiveDifficultyEvaluator pins the bound: the
    # produced average difficulty must stay within ±1 step of requested.
    # Without this case, a future prompt change that makes the agent
    # produce all easy questions for a hard request would slip through.
    Case(
        name="adaptive_downshift_struggling_student",
        inputs=(
            "Course: CS 201. Generate 3 hard multiple-choice questions "
            "covering Recursion, Dynamic Programming, and Graph Traversal. "
            "The student has been struggling on this material — recent "
            "attempts have averaged < 50% accuracy. Apply the adaptive-"
            "difficulty rule: it's OK to step down to medium where the "
            "evidence supports it."
        ),
        metadata={
            "expected_count": 3,
            # Don't pin a single expected_difficulty — the agent may
            # mix medium/hard under the adaptive rule. The point is
            # the ±1-step bound captured by requested_difficulty.
            "expected_difficulty": None,
            "expected_type": "multiple_choice",
            "concepts": ["Recursion", "Dynamic Programming", "Graph Traversal"],
            "requested_difficulty": "hard",
        },
    ),

    # ── Spaced repetition (stale concept must be revived) ──────────────────
    # Per ADR 0014: concepts whose `last_reviewed_at` is older than ~7
    # days should surface even when their mastery is mid-tier. The case
    # input names a stale concept explicitly; SpacedRepetitionConcept-
    # Evaluator asserts at least one question targets it.
    Case(
        name="spaced_repetition_revives_stale_concept",
        inputs=(
            "Course: BIO 100. Generate 3 medium multiple-choice questions. "
            "The student has been working on Photosynthesis (mastery 0.4) "
            "and Mitosis (mastery 0.5) recently, but Cell Membrane "
            "(mastery 0.65) hasn't been reviewed in 14 days. Per the "
            "spaced-repetition rule, include at least one Cell Membrane "
            "question to revive the stale concept."
        ),
        metadata={
            "expected_count": 3,
            "expected_difficulty": "medium",
            "expected_type": "multiple_choice",
            "concepts": ["Photosynthesis", "Mitosis", "Cell Membrane"],
            "stale_concept": "Cell Membrane",
        },
    ),
]

assert len(CASES) == 10, f"Expected 10 cases (8 original + 2 ADR 0014), got {len(CASES)}"
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
            AdaptiveDifficultyEvaluator(),
            SpacedRepetitionConceptEvaluator(),
        ],
    )


if __name__ == "__main__":
    cli_main(make_dataset, _run)
