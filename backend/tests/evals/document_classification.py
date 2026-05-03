"""pydantic-evals cases for the document classifier agent.

Run as evals (loads pydantic-evals; hits live Gemini):
    python -m tests.evals.document_classification

Cases are intentionally small — 10 examples covering:
- 4 syllabus variants (typical, minimal, embedded-in-handbook, non-English)
- 4 non-syllabus (lecture, textbook excerpt, assignment, exam)
- 2 ambiguous (course handbook with embedded schedule; assignment list
  that looks like a syllabus)

Add cases here when production produces a misclassification. Do NOT
edit existing cases to make them pass.

Note: Sapling's DocumentCategory does not include "textbook_chapter"
or "exam" (see backend/agents/classifier.py:23). The textbook excerpt
maps to expected="reading" and the exam maps to expected="other"
(no closer match in the live taxonomy). If the taxonomy expands, the
expected_output strings update with it.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

# Allow `python -m tests.evals.document_classification` from backend/.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext

from agents.classifier import classifier_agent, DocumentClassification
from agents.deps import SaplingDeps


@dataclass
class CategoryEvaluator(Evaluator[str, DocumentClassification]):
    """Pass when the predicted category matches the labeled category."""

    def evaluate(self, ctx: EvaluatorContext[str, DocumentClassification]) -> float:
        return 1.0 if ctx.output.category == ctx.expected_output else 0.0


@dataclass
class SyllabusFlagEvaluator(Evaluator[str, DocumentClassification]):
    """Pass when is_syllabus matches the labeled flag (from case metadata)."""

    def evaluate(self, ctx: EvaluatorContext[str, DocumentClassification]) -> float:
        expected_is_syllabus = ctx.metadata.get("is_syllabus", False) if ctx.metadata else False
        return 1.0 if ctx.output.is_syllabus == expected_is_syllabus else 0.0


# Inputs are tiny representative excerpts. Real production cases would
# be longer; we use minimal text that's still classifiable.
CASES: list[Case[str, str]] = [
    # ── SYLLABUS — TYPICAL ───────────────────────────────────────────────
    Case(
        name="typical_university_syllabus",
        inputs=(
            "CS 188 Introduction to AI — Spring 2026\n"
            "Instructor: Dr. Smith\n"
            "Schedule: Lectures TTh 10-11:30am.\n"
            "Grading: 4 problem sets (40%), midterm (25%), final project (35%).\n"
            "Late policy: 10% per day, max 3 days."
        ),
        expected_output="syllabus",
        metadata={"is_syllabus": True},
    ),
    # ── SYLLABUS — MINIMAL ───────────────────────────────────────────────
    Case(
        name="minimal_syllabus",
        inputs=(
            "Course outline\nWeek 1: Intro\nWeek 2: Vectors\n"
            "Week 3: Matrices\nFinal exam: Week 14"
        ),
        expected_output="syllabus",
        metadata={"is_syllabus": True},
    ),
    # ── SYLLABUS — EMBEDDED IN HANDBOOK ──────────────────────────────────
    Case(
        name="syllabus_embedded_in_handbook",
        inputs=(
            "Department Handbook 2026\n\n"
            "Chapter 3: BIO 201 Course Information\n"
            "Required textbook: Campbell Biology 12e.\n"
            "Assessments: 3 lab reports, weekly quizzes, cumulative final.\n"
            "Schedule of topics:\n  Module 1 (Weeks 1-3): Cell biology\n  Module 2 (Weeks 4-6): Genetics\n"
        ),
        expected_output="syllabus",
        metadata={"is_syllabus": True},
    ),
    # ── SYLLABUS — NON-ENGLISH (Spanish) ─────────────────────────────────
    Case(
        name="spanish_syllabus",
        inputs=(
            "Programa del curso — Cálculo I\n"
            "Profesor: García\n"
            "Evaluación: parcial (30%), tareas (20%), examen final (50%).\n"
            "Calendario: 16 semanas de clase."
        ),
        expected_output="syllabus",
        metadata={"is_syllabus": True},
    ),
    # ── NON-SYLLABUS — LECTURE NOTES ─────────────────────────────────────
    Case(
        name="lecture_notes",
        inputs=(
            "Lecture 7: Backpropagation\n\n"
            "Recall: forward pass computes loss L. Backprop computes ∂L/∂w "
            "via chain rule. The gradient at layer k depends on activations "
            "at layer k-1 and the gradient at layer k+1."
        ),
        expected_output="lecture_notes",
        metadata={"is_syllabus": False},
    ),
    # ── NON-SYLLABUS — TEXTBOOK CHAPTER (-> reading in our taxonomy) ─────
    Case(
        name="textbook_chapter",
        inputs=(
            "Chapter 4: Recurrence Relations\n\n"
            "A recurrence relation defines a sequence by relating later "
            "terms to earlier ones. The Fibonacci recurrence F(n) = F(n-1) "
            "+ F(n-2) is the canonical example..."
        ),
        expected_output="reading",
        metadata={"is_syllabus": False},
    ),
    # ── NON-SYLLABUS — ASSIGNMENT ────────────────────────────────────────
    Case(
        name="assignment",
        inputs=(
            "Problem Set 3 — due Friday\n\n"
            "1. Prove that the sum of two odd integers is even.\n"
            "2. Show that √2 is irrational.\n"
            "3. ..."
        ),
        expected_output="assignment",
        metadata={"is_syllabus": False},
    ),
    # ── NON-SYLLABUS — EXAM (-> other; our taxonomy has no 'exam') ──────
    Case(
        name="exam",
        inputs=(
            "Midterm Examination — 90 minutes — closed book\n\n"
            "Question 1 (20 points): Define a Markov chain.\n"
            "Question 2 (30 points): ..."
        ),
        expected_output="other",
        metadata={"is_syllabus": False},
    ),
    # ── AMBIGUOUS — HANDBOOK WITH SCHEDULE (treat as syllabus) ──────────
    Case(
        name="course_handbook_with_schedule",
        inputs=(
            "Welcome to MATH 220. This handbook contains policies and the "
            "term schedule. Office hours: Mondays 2-4pm. Schedule: "
            "Week 1 vectors, Week 2 derivatives, Week 3 integration..."
        ),
        expected_output="syllabus",
        metadata={"is_syllabus": True},
    ),
    # ── AMBIGUOUS — ASSIGNMENT LIST (NOT a syllabus) ────────────────────
    Case(
        name="assignment_list_with_weights",
        inputs=(
            "Graded items for ECON 101:\n"
            "- Quiz 1: 10%\n- Quiz 2: 10%\n- Midterm: 30%\n- Final: 50%\n"
            "Submit through the LMS by the listed deadline."
        ),
        expected_output="assignment",
        metadata={"is_syllabus": False},
    ),
]


async def _run(case_input: str) -> DocumentClassification:
    """Adapter: run the agent and unwrap the typed output for evaluation."""
    deps = SaplingDeps(
        user_id="eval-user",
        course_id="eval-course",
        supabase=None,
        request_id="eval",
    )
    result = await classifier_agent.run(case_input, deps=deps)
    return result.output


def make_dataset() -> Dataset[str, str]:
    return Dataset(
        name="document_classification",
        cases=CASES,
        evaluators=[CategoryEvaluator(), SyllabusFlagEvaluator()],
    )


if __name__ == "__main__":
    dataset = make_dataset()
    report = asyncio.run(dataset.evaluate(_run))
    report.print(include_input=False, include_output=True)
