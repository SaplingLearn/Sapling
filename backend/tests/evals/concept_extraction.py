"""pydantic-evals cases for the concept extraction agent.

Run as evals (default mode = replay; SAPLING_EVAL_MODE=record|live for others):
    python tests/evals/concept_extraction.py

Add cases here when production produces bad concept extractions. Do
NOT edit existing cases to make them pass.

Evaluators check the contracts in agents/concept_extraction.py:
- 1-30 concepts (schema constraint).
- Names are not administrative labels (problem numbers, week labels,
  page numbers, chapter headers) — the system prompt forbids these.
- Names read as Title Case noun phrases (soft signal; partial credit).
- The list is ordered by importance descending.
"""

from __future__ import annotations

import asyncio
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Allow `python tests/evals/concept_extraction.py` from backend/.
# Add backend/ for `agents.*` and tests/evals/ for sibling `_replay`.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext

from agents.concept_extraction import ConceptList, concept_extraction_agent
from _replay import run_with_cassette  # noqa: E402  (sibling, sys.path-injected)


_ADMIN_NAME_PATTERNS = [
    re.compile(r"^Problem\s+\d", re.IGNORECASE),
    re.compile(r"^Week\s+\d", re.IGNORECASE),
    re.compile(r"^Page\s+\d", re.IGNORECASE),
    re.compile(r"^Chapter\s+\d", re.IGNORECASE),
]


@dataclass
class ConceptCountInRangeEvaluator(Evaluator[str, ConceptList]):
    """Pass when the concept count is in [1, 30] (schema constraint)."""

    def evaluate(self, ctx: EvaluatorContext[str, ConceptList]) -> float:
        n = len(ctx.output.concepts)
        return 1.0 if 1 <= n <= 30 else 0.0


@dataclass
class NoAdministrativeNamesEvaluator(Evaluator[str, ConceptList]):
    """Fail when any concept name is an administrative label.

    The system prompt forbids "Problem N", "Week N", "Page N", and
    "Chapter N" style names. They're a common Gemini failure mode on
    documents that physically lay out content under those headers.
    """

    def evaluate(self, ctx: EvaluatorContext[str, ConceptList]) -> float:
        for concept in ctx.output.concepts:
            for pattern in _ADMIN_NAME_PATTERNS:
                if pattern.match(concept.name.strip()):
                    return 0.0
        return 1.0


@dataclass
class AllNamesTitleCaseEvaluator(Evaluator[str, ConceptList]):
    """Soft signal: at least 80% of names should look Title Case.

    A name "looks Title Case" when it differs from its lowercase form —
    i.e. at least one character is uppercase. We grant 0.5 partial
    credit when 80%+ pass and full credit when 100% pass.
    """

    def evaluate(self, ctx: EvaluatorContext[str, ConceptList]) -> float:
        names = [c.name for c in ctx.output.concepts]
        if not names:
            return 0.0
        title_case = sum(1 for n in names if n != n.lower())
        ratio = title_case / len(names)
        if ratio == 1.0:
            return 1.0
        if ratio >= 0.8:
            return 0.5
        return 0.0


@dataclass
class OrderedByImportanceEvaluator(Evaluator[str, ConceptList]):
    """Pass when concepts are sorted by importance descending (allow ties)."""

    def evaluate(self, ctx: EvaluatorContext[str, ConceptList]) -> float:
        importances = [c.importance for c in ctx.output.concepts]
        for prev, cur in zip(importances, importances[1:]):
            if cur > prev:  # strict descending allowing equals
                return 0.0
        return 1.0


CASES: list[Case[str, None]] = [
    # ── 1. LONG LECTURE — expect 4-12 concepts ───────────────────────────
    Case(
        name="long_lecture_neural_networks",
        inputs=(
            "Lecture: Neural Networks Foundations. We cover feedforward "
            "networks, activation functions (ReLU, sigmoid, tanh), the "
            "softmax output for classification, the cross-entropy loss, "
            "stochastic gradient descent with mini-batches, "
            "backpropagation as the chain rule applied layerwise, "
            "regularization techniques (L2 weight decay, dropout), and "
            "vanishing/exploding gradient problems. We close with batch "
            "normalization and its effect on optimization."
        ),
        metadata={"expected_count_range": (4, 12)},
    ),
    # ── 2. NARROW ASSIGNMENT — expect 1-8 ────────────────────────────────
    Case(
        name="narrow_assignment_proofs",
        inputs=(
            "Homework 2: prove the irrationality of sqrt(2), prove the "
            "infinitude of primes, and prove that the sum of two odd "
            "integers is even."
        ),
        metadata={"expected_count_range": (1, 8)},
    ),
    # ── 3. WHOLE-COURSE SYLLABUS — expect up to ~15 ──────────────────────
    Case(
        name="whole_course_syllabus_calc1",
        inputs=(
            "Calculus I — full course outline. Topics: limits and "
            "continuity; derivatives and rules of differentiation; "
            "implicit differentiation; related rates; mean value theorem; "
            "L'Hopital's rule; curve sketching; optimization; Riemann "
            "sums; the fundamental theorem of calculus; techniques of "
            "integration; applications of integration to area and volume; "
            "differential equations basics; sequences and series."
        ),
        metadata={"expected_count_range": (8, 15)},
    ),
    # ── 4. ADVERSARIAL — every paragraph starts "Problem N:" ─────────────
    Case(
        name="adversarial_problem_n_headers",
        inputs=(
            "Problem 1: prove the law of cosines using the dot product. "
            "Problem 2: derive the angle-addition identity for sin(a+b). "
            "Problem 3: show that orthogonal matrices preserve the "
            "Euclidean inner product. Problem 4: prove that the cross "
            "product is anti-commutative. Problem 5: use the Cauchy-Schwarz "
            "inequality to prove the triangle inequality."
        ),
        metadata={
            "expected_count_range": (1, 8),
            "note": "Concepts must NOT be 'Problem 1', 'Problem 2', etc.",
        },
    ),
    # ── 5. ADVERSARIAL — slide bullets are "Week N — ..." ────────────────
    Case(
        name="adversarial_week_n_slides",
        inputs=(
            "Week 1 — Introduction to Statistics. Week 2 — Descriptive "
            "Statistics. Week 3 — Probability Distributions. Week 4 — "
            "Sampling and the Central Limit Theorem. Week 5 — Hypothesis "
            "Testing. Week 6 — Confidence Intervals. Week 7 — Linear "
            "Regression."
        ),
        metadata={
            "expected_count_range": (4, 12),
            "note": "Concepts must NOT be 'Week 1', 'Week 2', etc.",
        },
    ),
    # ── 6. MATH-HEAVY → "Linear Regression", "Big-O Analysis" ────────────
    Case(
        name="math_text_regression_complexity",
        inputs=(
            "Lecture covers linear regression as a least-squares problem, "
            "the normal equations, the QR decomposition, ridge "
            "regularization, and the Big-O analysis of the resulting "
            "matrix solves. We also discuss bias-variance decomposition "
            "and its implications for model selection."
        ),
        metadata={"expected_count_range": (3, 10)},
    ),
    # ── 7. CODE-HEAVY → "Recursion", "Dynamic Programming" ───────────────
    Case(
        name="code_heavy_algorithms",
        inputs=(
            "Algorithms lecture: recursion and divide-and-conquer; merge "
            "sort and quicksort; the master theorem for recurrences; "
            "memoization; bottom-up dynamic programming; classic DP "
            "problems including longest common subsequence, knapsack, "
            "and edit distance; greedy algorithms and the matroid "
            "framework."
        ),
        metadata={"expected_count_range": (4, 12)},
    ),
    # ── 8. BIO TEXT → "Mitochondrial Function" et al. ────────────────────
    Case(
        name="bio_cellular_respiration",
        inputs=(
            "Cellular respiration overview. Glucose enters glycolysis, "
            "yielding pyruvate, ATP, and NADH. Pyruvate enters the "
            "mitochondrion and is oxidized to acetyl-CoA. The citric "
            "acid cycle produces additional NADH and FADH2. The electron "
            "transport chain on the inner mitochondrial membrane drives "
            "oxidative phosphorylation, producing the bulk of ATP via "
            "chemiosmosis."
        ),
        metadata={"expected_count_range": (4, 10)},
    ),
    # ── 9. ECON TEXT → "Supply and Demand" ───────────────────────────────
    Case(
        name="econ_supply_demand",
        inputs=(
            "Microeconomics intro. Supply and demand determine "
            "equilibrium price and quantity in a competitive market. "
            "Price elasticity of demand measures responsiveness to price "
            "changes. Producer and consumer surplus capture welfare. "
            "Government interventions (price floors, ceilings, taxes) "
            "create deadweight loss when they bind."
        ),
        metadata={"expected_count_range": (3, 10)},
    ),
    # ── 10. EXPLORATORY — empty input. The schema requires >=1 concept; ──
    # the agent must either invent one or fail. We tag this case as
    # exploratory so reviewers know not to gate on it.
    Case(
        name="exploratory_empty_input",
        inputs="[document is empty]",
        metadata={
            "exploratory": True,
            "note": (
                "Schema requires min_length=1; the agent must produce >=1 "
                "reasonable concept or raise. Do not gate on this case."
            ),
        },
    ),
    # ── 11. PHYSICS LECTURE ──────────────────────────────────────────────
    Case(
        name="physics_classical_mechanics",
        inputs=(
            "Classical mechanics review. Newton's three laws of motion. "
            "Conservation of energy in conservative force fields. "
            "Conservation of linear momentum. Conservation of angular "
            "momentum. Lagrangian mechanics from the principle of least "
            "action. Hamiltonian mechanics. Simple harmonic motion."
        ),
        metadata={"expected_count_range": (4, 10)},
    ),
    # ── 12. CHEMISTRY READING ────────────────────────────────────────────
    Case(
        name="chemistry_thermodynamics",
        inputs=(
            "Chemical thermodynamics. The first law states that energy is "
            "conserved; we apply it via enthalpy for chemical reactions. "
            "The second law introduces entropy as a measure of "
            "disorder. The Gibbs free energy combines enthalpy and "
            "entropy and predicts spontaneity at constant T and P."
        ),
        metadata={"expected_count_range": (3, 8)},
    ),
    # ── 13. PSYCHOLOGY STUDY GUIDE ───────────────────────────────────────
    Case(
        name="psychology_study_guide",
        inputs=(
            "Cognitive psychology midterm review. Key topics: working "
            "memory and the Baddeley model; long-term memory and the "
            "encoding-storage-retrieval framework; classical and operant "
            "conditioning; theories of attention (spotlight vs. zoom "
            "lens); top-down and bottom-up perception; Kahneman's "
            "System 1 and System 2."
        ),
        metadata={"expected_count_range": (4, 12)},
    ),
    # ── 14. HISTORY READING ──────────────────────────────────────────────
    Case(
        name="history_reading_industrial_rev",
        inputs=(
            "The Industrial Revolution in 18th-century Britain depended "
            "on cheap coal, expensive labor, an open patent regime, and a "
            "navigable transport network. Steam power transformed "
            "manufacturing. Urbanization concentrated workers in factory "
            "towns. Working conditions became a public concern, "
            "eventually producing the Factory Acts."
        ),
        metadata={"expected_count_range": (4, 10)},
    ),
    # ── 15. CS NETWORKING NARROW ─────────────────────────────────────────
    Case(
        name="cs_networking_tcp",
        inputs=(
            "TCP fundamentals. The three-way handshake establishes a "
            "connection. TCP segments are reliable, ordered, and "
            "byte-stream oriented. Congestion control uses slow start, "
            "congestion avoidance, and fast recovery. Flow control uses "
            "the receiver's advertised window."
        ),
        metadata={"expected_count_range": (3, 8)},
    ),
]


_INPUT_TO_NAME: dict[str, str] = {case.inputs: case.name for case in CASES}


async def _run(case_input: str) -> ConceptList:
    """Adapter: route through the cassette layer (record/replay/live)."""
    case_name = _INPUT_TO_NAME.get(case_input, "unknown")
    return await run_with_cassette(
        dataset="concept_extraction",
        case_name=case_name,
        agent=concept_extraction_agent,
        case_input=case_input,
        output_model=ConceptList,
    )


def make_dataset() -> Dataset[str, None]:
    return Dataset(
        name="concept_extraction",
        cases=CASES,
        evaluators=[
            ConceptCountInRangeEvaluator(),
            NoAdministrativeNamesEvaluator(),
            AllNamesTitleCaseEvaluator(),
            OrderedByImportanceEvaluator(),
        ],
    )


if __name__ == "__main__":
    from _replay import cli_main  # noqa: E402

    cli_main(make_dataset, _run)
