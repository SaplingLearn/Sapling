"""pydantic-evals cases for the summary agent.

Run as evals (loads pydantic-evals; hits live Gemini):
    python -m tests.evals.document_summary

Add cases here when production produces a bad summary. Do NOT edit
existing cases to make them pass.

The evaluators are shape contracts on the Summary model
(agents/summary.py): the abstract is 3-5 sentences, key_points is
3-8 items, the headline fits the card view, and no markdown leaks
through. The agent prompt forbids markdown; we belt-and-suspender it
here because Gemini occasionally still emits ** bold ** or fenced
code despite the system prompt.
"""

from __future__ import annotations

import asyncio
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Allow `python -m tests.evals.document_summary` from backend/.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext

from agents.deps import SaplingDeps
from agents.summary import Summary, summary_agent


@dataclass
class AbstractLengthEvaluator(Evaluator[str, Summary]):
    """Pass when the abstract reads as 3-5 sentences (allow 3-6 for slack)."""

    def evaluate(self, ctx: EvaluatorContext[str, Summary]) -> float:
        # Approximate sentence count by splitting on sentence-end punctuation
        # plus space. Keep it permissive — Gemini sometimes ends with "."
        # (no trailing space) which the original "split('. ')" would miss.
        sentences = [s for s in re.split(r"[.!?]\s+", ctx.output.abstract.strip()) if s]
        return 1.0 if 3 <= len(sentences) <= 6 else 0.0


@dataclass
class KeyPointsCountEvaluator(Evaluator[str, Summary]):
    """Pass when key_points has 3-8 items (matches the schema constraint)."""

    def evaluate(self, ctx: EvaluatorContext[str, Summary]) -> float:
        return 1.0 if 3 <= len(ctx.output.key_points) <= 8 else 0.0


@dataclass
class HeadlineLengthEvaluator(Evaluator[str, Summary]):
    """Pass when the headline is <= 140 chars (matches the schema)."""

    def evaluate(self, ctx: EvaluatorContext[str, Summary]) -> float:
        return 1.0 if len(ctx.output.headline) <= 140 else 0.0


@dataclass
class NoMarkdownLeakEvaluator(Evaluator[str, Summary]):
    """Fail when the abstract contains markdown bold, fenced code, or $."""

    def evaluate(self, ctx: EvaluatorContext[str, Summary]) -> float:
        text = ctx.output.abstract
        if "**" in text:
            return 0.0
        if "```" in text:
            return 0.0
        if "$" in text:
            return 0.0
        return 1.0


# Inputs are short representative excerpts (3-8 sentences). Real
# production summaries run on multi-page extracted text; small inputs
# keep the eval fast while still exercising the prompt.
CASES: list[Case[str, None]] = [
    # ── 1. SYLLABUS EXCERPT — names course + grading ─────────────────────
    Case(
        name="short_syllabus_excerpt",
        inputs=(
            "PSY 240 Cognitive Psychology — Fall 2026.\n"
            "Grading: weekly quizzes 20%, midterm 30%, final paper 50%.\n"
            "We meet MWF 9-9:50am in Room 214."
        ),
    ),
    # ── 2. LECTURE ON BACKPROPAGATION ────────────────────────────────────
    Case(
        name="lecture_backpropagation",
        inputs=(
            "Lecture 7: Backpropagation. The forward pass computes a loss "
            "L given inputs and weights. Backprop applies the chain rule "
            "layer-by-layer to compute partial derivatives of L with "
            "respect to every parameter. The gradient at layer k depends "
            "on activations from layer k-1 and the upstream gradient from "
            "layer k+1. We then take a gradient-descent step to update "
            "weights."
        ),
    ),
    # ── 3. EMPTY/SPARSE DOCUMENT — headline should say so ────────────────
    Case(
        name="empty_document",
        inputs="[page intentionally left blank]",
        metadata={"expected_headline_keyword": "empty"},
    ),
    # ── 4. MATH-HEAVY NOTES — no markdown leakage despite $ in source ────
    Case(
        name="math_heavy_notes_with_dollar_signs",
        inputs=(
            "Notes on Fourier analysis. The Fourier coefficients are "
            "$a_n = (1/\\pi) \\int f(x) \\cos(nx) dx$ and similarly for "
            "$b_n$. Parseval's identity relates the integral of $f^2$ to "
            "the sum of squared coefficients. Convergence is governed by "
            "the Dirichlet kernel."
        ),
    ),
    # ── 5. TEXTBOOK CHAPTER — abstract restates main thesis ──────────────
    Case(
        name="textbook_chapter_thesis",
        inputs=(
            "Chapter 3: The Industrial Revolution. The thesis of this "
            "chapter is that mechanization in 18th-century Britain "
            "depended less on heroic invention than on a coalition of "
            "cheap coal, expensive labor, and an unusually open patent "
            "regime. The author argues that without this combination, "
            "the same engineering ideas would have remained curiosities. "
            "Subsequent sections examine each factor in turn."
        ),
    ),
    # ── 6. PROBLEM SET — headline names topic, key_points mention items ──
    Case(
        name="linear_algebra_problem_set",
        inputs=(
            "Problem Set 6 — Linear Algebra. Problem 1: diagonalize a 2x2 "
            "matrix and compute its 10th power in closed form. Problem 2: "
            "prove that every real symmetric matrix has an orthonormal "
            "eigenbasis. Problem 3: find the rank, nullity, and a basis "
            "for the column space of a given 4x5 matrix. Show all work."
        ),
    ),
    # ── 7. NON-ENGLISH (Spanish) — output adapts; just check shape ───────
    Case(
        name="spanish_syllabus",
        inputs=(
            "Programa del curso — Cálculo I. Profesor: García. La "
            "evaluación incluye un parcial (30%), tareas semanales (20%) "
            "y un examen final (50%). El curso dura 16 semanas y cubre "
            "límites, derivadas, integrales y series. Se requiere "
            "asistencia regular."
        ),
    ),
    # ── 8. VERBOSE TWO-PAGE DOC — abstract stays under 1500 chars ────────
    Case(
        name="verbose_redundant_topic",
        inputs=(
            "These notes cover binary search trees in considerable detail. "
            "A binary search tree (BST) is a binary tree in which every "
            "node's key is greater than all keys in its left subtree and "
            "less than all keys in its right subtree. Insertion proceeds "
            "by descending from the root, comparing keys, and attaching a "
            "new leaf at the appropriate empty slot. Lookup is symmetric. "
            "Deletion is the trickiest operation because the deleted "
            "node may have two children; the standard fix is to replace "
            "the deleted node with its in-order successor. Worst-case "
            "performance degenerates to O(n) when the tree becomes "
            "unbalanced, which motivates self-balancing variants such as "
            "AVL and red-black trees."
        ),
    ),
    # ── 9. MULTI-TOPIC STUDY GUIDE — key_points span topics ──────────────
    Case(
        name="multi_topic_study_guide",
        inputs=(
            "Midterm 1 study guide: covers (a) experimental methods — "
            "independent vs. dependent variables, confounding; (b) "
            "neurons — action potentials and synaptic transmission; "
            "(c) sensation and perception — absolute vs. difference "
            "thresholds; (d) classical and operant conditioning."
        ),
    ),
    # ── 10. GLOSSARY-STYLE READING — key_points are single concepts ──────
    Case(
        name="glossary_style_reading",
        inputs=(
            "Glossary of statistics terms. Mean: the arithmetic average "
            "of a set of numbers. Median: the middle value when ordered. "
            "Mode: the most frequent value. Variance: the average of "
            "squared deviations from the mean. Standard deviation: the "
            "square root of the variance. p-value: probability of a "
            "result at least as extreme under the null hypothesis."
        ),
    ),
    # ── 11. LITERATURE REVIEW — abstract names the synthesis ─────────────
    Case(
        name="literature_review",
        inputs=(
            "This review surveys 30 years of research on bilingual "
            "advantage in executive function. Early studies reported a "
            "consistent advantage on inhibition tasks, but recent "
            "pre-registered replications find effects that are smaller, "
            "context-dependent, and often null in adults. The current "
            "synthesis is that bilingualism shapes attention selectively, "
            "primarily in switching tasks, and primarily in children and "
            "older adults. The review concludes by proposing a unified "
            "model and naming three open questions."
        ),
    ),
    # ── 12. COURSE HANDBOOK / POLICIES — headline reflects nature ────────
    Case(
        name="course_handbook_policies",
        inputs=(
            "BIO 130 Course Handbook. Section 1: academic integrity. "
            "Plagiarism, unauthorized collaboration, and AI-generated "
            "submissions without disclosure result in a zero on the "
            "assignment and a referral. Section 2: late work. 10% per "
            "day, max three days. Section 3: accommodations. Notify the "
            "instructor and the Office of Disability Services in week 1."
        ),
    ),
    # ── 13. SHORT BULLET-ONLY PRESENTATION — abstract reconstructs flow ──
    Case(
        name="bullet_only_presentation",
        inputs=(
            "Slide 1: Photosynthesis overview. Slide 2: Light reactions: "
            "PSII to PSI; water splitting; electron transport. Slide 3: "
            "Calvin cycle: carbon fixation; reduction; regeneration of "
            "RuBP. Slide 4: Net products: ATP, NADPH, glucose. Slide 5: "
            "Limiting factors: light, CO2, temperature."
        ),
    ),
    # ── 14. LAB PROCEDURE — key_points enumerate steps ───────────────────
    Case(
        name="lab_procedure",
        inputs=(
            "Acid-base titration procedure. (1) Calibrate the burette "
            "with deionized water. (2) Pipette 25.0 mL of unknown HCl "
            "into a clean Erlenmeyer flask. (3) Add three drops of "
            "phenolphthalein. (4) Titrate slowly with standardized NaOH "
            "until the first persistent pink color. (5) Record the "
            "volume of NaOH used. (6) Repeat for two more trials and "
            "average the results."
        ),
    ),
    # ── 15. STATEMENT OF WORK — headline names the deliverable ───────────
    Case(
        name="statement_of_work",
        inputs=(
            "Project Brief: Sapling onboarding redesign. The deliverable "
            "is a redesigned signup-to-first-document flow that reduces "
            "median time-to-first-upload to under 90 seconds. Scope "
            "includes the marketing-to-app handoff, signup form, and "
            "upload screen. Out of scope: chat, library, settings. "
            "Timeline: 4 weeks. Owner: design team."
        ),
    ),
]


async def _run(case_input: str) -> Summary:
    """Adapter: run the agent and unwrap the typed output for evaluation."""
    deps = SaplingDeps(
        user_id="eval-user",
        course_id="eval-course",
        supabase=None,
        request_id="eval",
    )
    result = await summary_agent.run(case_input, deps=deps)
    return result.output


def make_dataset() -> Dataset[str, None]:
    return Dataset(
        name="document_summary",
        cases=CASES,
        evaluators=[
            AbstractLengthEvaluator(),
            KeyPointsCountEvaluator(),
            HeadlineLengthEvaluator(),
            NoMarkdownLeakEvaluator(),
        ],
    )


if __name__ == "__main__":
    dataset = make_dataset()
    report = asyncio.run(dataset.evaluate(_run))
    report.print(include_input=False, include_output=True)
