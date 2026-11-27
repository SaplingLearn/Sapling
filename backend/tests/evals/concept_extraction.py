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
import os
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
from services.prompt_safety import wrap_document_input  # noqa: E402  (as the upload pipeline sends it)


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


# ── #866 Z25: the A118 relations variant (flag `upload_prereq_edges`) ────────
#
# With the flag on for the uploader, extraction also returns prerequisite
# relations (`extraction_run_args(prerequisites=True)`: the course's existing
# concepts in the message, PREREQUISITE_INSTRUCTIONS, the ConceptList schema),
# and code writes the ones `services.concept_prereqs.resolve_prerequisites`
# keeps as graph edges — which steer propagation, prerequisite bands and the
# planner's order. Its own dataset, scored on what would be WRITTEN, replayed
# once recorded (the flag waits on the recording).

RELATIONS_DATASET = "concept_extraction__relations"

RELATION_CASES: list[Case[str, None]] = [
    Case(
        name="relations_calculus_lecture",
        inputs=(
            "Lecture 4: Derivatives. Last week we defined the limit of a function as x "
            "approaches a point. Today we use limits to define the derivative: the "
            "derivative of f at a is the limit of the difference quotient (f(a+h) - f(a))/h "
            "as h approaches 0. From the definition we prove the power rule. Finally we "
            "meet the chain rule, which differentiates a composition f(g(x)) as "
            "f'(g(x)) times g'(x); it only makes sense once derivatives of the inner and "
            "outer functions are understood."
        ),
        metadata={
            "existing": ["Limits", "Functions"],
            "expected_edges": [("Limits", "Derivatives"), ("Derivatives", "Chain Rule")],
        },
    ),
    Case(
        name="relations_spread_of_data",
        inputs=(
            "Measuring spread. The mean is the sum of the values divided by their count. "
            "The variance is the average squared distance of each value from the mean, so "
            "it cannot be computed without the mean. The standard deviation is the square "
            "root of the variance and is in the data's own units."
        ),
        metadata={
            "existing": ["Mean"],
            "expected_edges": [("Mean", "Variance"), ("Variance", "Standard Deviation")],
        },
    ),
]
_RELATIONS_BY_INPUT = {case.inputs: case for case in RELATION_CASES}


def _resolution(ctx):
    """What code would write for this case's output (A118's resolver)."""
    from services.concept_prereqs import resolve_prerequisites

    out = ctx.output
    return resolve_prerequisites(
        [(r.prerequisite, r.dependent) for r in out.prerequisites],
        document_concepts=[(c.name, c.importance) for c in out.concepts],
        course_concepts=[*ctx.metadata["existing"], *(c.name for c in out.concepts)],
    )


def _key(name: str) -> str:
    return " ".join(name.split()).casefold()


@dataclass
class ExpectedEdgesWritten(Evaluator[str, ConceptList]):
    """The share of the document's clear prerequisite links code would write."""

    def evaluate(self, ctx: EvaluatorContext[str, ConceptList]) -> float:
        written = {(_key(a), _key(b)) for a, b in _resolution(ctx).edges}
        want = [(_key(a), _key(b)) for a, b in ctx.metadata["expected_edges"]]
        return sum(edge in written for edge in want) / len(want)


@dataclass
class NoReversedEdge(Evaluator[str, ConceptList]):
    """No written edge runs backwards along a clear link (a reversed edge inverts
    the prerequisite bands and the plan order)."""

    def evaluate(self, ctx: EvaluatorContext[str, ConceptList]) -> float:
        written = {(_key(a), _key(b)) for a, b in _resolution(ctx).edges}
        reversed_ = {(_key(b), _key(a)) for a, b in ctx.metadata["expected_edges"]}
        return 0.0 if written & reversed_ else 1.0


@dataclass
class RelationsKept(Evaluator[str, ConceptList]):
    """The share of the model's relations code keeps (none dropped as unknown,
    a self-loop, off the document, a duplicate, a cycle or redundant)."""

    def evaluate(self, ctx: EvaluatorContext[str, ConceptList]) -> float:
        total = len(ctx.output.prerequisites)
        if not total:
            return 0.0  # every case has a clear dependency
        return 1.0 - len(_resolution(ctx).dropped) / total


def relations_identity(case_input: str) -> dict:
    """What a relations cassette is recorded under: the flag-on prompt (system
    prompt + PREREQUISITE_INSTRUCTIONS), the ConceptList schema, the slot's
    model and the exact message."""
    from _replay import input_identity, prompt_identity, recorded_under, run_settings, schema_hash
    from agents._providers import model_name_for
    from agents.concept_extraction import _PREREQ_PROMPT_HASH

    message = _relations_args(case_input)["user_prompt"]
    return recorded_under(
        prompt_hash=prompt_identity(_PREREQ_PROMPT_HASH, concept_extraction_agent),
        schema_hash=schema_hash(ConceptList),
        model=model_name_for("concepts"),
        input_sha256=input_identity(message, run_settings(concept_extraction_agent)),
    )


def _relations_args(case_input: str) -> dict:
    """The upload route's run arguments (agents/document.py::_step_concepts)."""
    from agents.concept_extraction import extraction_run_args

    case = _RELATIONS_BY_INPUT[case_input]
    return extraction_run_args(
        wrap_document_input(case_input), prerequisites=True,
        existing_concepts=case.metadata["existing"],
    )


async def _run_relations(case_input: str) -> ConceptList:
    from _replay import MODE, _is_transient, load_recording, make_deps, save_recording

    name = _RELATIONS_BY_INPUT[case_input].name
    identity = relations_identity(case_input)
    if MODE == "replay":
        return ConceptList.model_validate(load_recording(RELATIONS_DATASET, name, identity))
    args = _relations_args(case_input)
    message = args.pop("user_prompt")
    for attempt in range(5):
        try:
            result = await concept_extraction_agent.run(message, **args, deps=make_deps())
            break
        except Exception as exc:  # noqa: BLE001 - re-raised unless transient
            if not _is_transient(exc) or attempt == 4:
                raise
            await asyncio.sleep(3.0 * (attempt + 1))
    if MODE == "record":
        save_recording(RELATIONS_DATASET, name, result.output, identity)
    return result.output


def make_relations_dataset() -> Dataset[str, None]:
    return Dataset(
        name=RELATIONS_DATASET,
        cases=RELATION_CASES,
        evaluators=[
            ConceptCountInRangeEvaluator(),
            NoAdministrativeNamesEvaluator(),
            AllNamesTitleCaseEvaluator(),
            OrderedByImportanceEvaluator(),
            ExpectedEdgesWritten(),
            NoReversedEdge(),
            RelationsKept(),
        ],
    )


async def _run(case_input: str) -> ConceptList:
    """Adapter: route through the cassette layer (record/replay/live)."""
    case_name = _INPUT_TO_NAME.get(case_input, "unknown")
    return await run_with_cassette(
        dataset="concept_extraction",
        case_name=case_name,
        agent=concept_extraction_agent,
        case_input=wrap_document_input(case_input),
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


def recorded(name: str) -> bool:
    from _replay import CASSETTE_DIR

    folder = CASSETTE_DIR / name
    return folder.is_dir() and any(folder.glob("*.json"))


def replay_variants(*, recorded=recorded) -> dict:
    """The base dataset always; the A118 relations variant once recorded."""
    out = {"concept_extraction": (make_dataset, _run)}
    if recorded(RELATIONS_DATASET):
        out[RELATIONS_DATASET] = (make_relations_dataset, _run_relations)
    return out


#: run_all.py iterates these.
VARIANTS = replay_variants()


if __name__ == "__main__":
    from _replay import cli_main  # noqa: E402

    if os.getenv("CONCEPT_EVAL_RELATIONS") == "1":  # record or replay the A118 variant
        cli_main(make_relations_dataset, _run_relations)
    else:
        cli_main(make_dataset, _run)
