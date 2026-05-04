"""pydantic-evals cases for the document classifier agent.

Run as evals (loads pydantic-evals; hits live Gemini):
    python -m tests.evals.document_classification

Cases cover the seven-category taxonomy in agents/classifier.py and the
is_syllabus boolean. The original 10 hand-picked smoke cases are kept
verbatim; 15 additional cases were added to catch prompt/model
regressions across the long tail (lab handouts, programming projects,
reading lists, slides, math-heavy notes, exams, study guides, rubrics,
required-readings lists, non-English assignments, near-empty docs,
research papers, welcome letters, LaTeX-source noise).

Add cases here when production produces a misclassification. Do NOT
edit existing cases to make them pass.

Note: Sapling's DocumentCategory does not include "textbook_chapter"
or "exam" (see backend/agents/classifier.py:23). The textbook excerpt
maps to expected="reading" and exams map to expected="other"
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
    # ════════════════════════════════════════════════════════════════════
    # ADDITIONS — long-tail regression coverage. Do not edit the cases
    # above to make these pass.
    # ════════════════════════════════════════════════════════════════════
    # ── ASSIGNMENT — LAB HANDOUT ─────────────────────────────────────────
    Case(
        name="lab_handout_chemistry",
        inputs=(
            "CHEM 102 — Lab 5: Acid-Base Titration\n"
            "Objective: Determine the molarity of an unknown HCl solution\n"
            "by titration with standardized NaOH.\n"
            "Pre-lab: Read sections 7.3-7.5. Submit pre-lab questions before\n"
            "entering the lab. Procedure: (1) Calibrate the burette. (2) "
            "Pipette 25.0 mL of unknown into a flask. (3) Titrate to a "
            "phenolphthalein endpoint. Lab report due one week after the "
            "session."
        ),
        expected_output="assignment",
        metadata={"is_syllabus": False},
    ),
    # ── ASSIGNMENT — MATH PROBLEM SET ────────────────────────────────────
    Case(
        name="math_problem_set",
        inputs=(
            "MATH 240 — Homework 6 (due Friday Oct 3)\n\n"
            "1. Diagonalize A = [[2, 1], [1, 2]] and write A^10 in closed form.\n"
            "2. Prove that every real symmetric matrix has an orthonormal "
            "eigenbasis.\n"
            "3. Find the rank, nullity, and a basis for the column space of "
            "the given 4x5 matrix.\n"
            "Show all work. Late policy on syllabus."
        ),
        expected_output="assignment",
        metadata={"is_syllabus": False},
    ),
    # ── ASSIGNMENT — CS PROGRAMMING PROJECT ──────────────────────────────
    Case(
        name="cs_programming_project",
        inputs=(
            "CS 61B Project 2: Gitlet\n\n"
            "You will implement a version-control system modeled after a "
            "subset of git. Your implementation must support init, add, "
            "commit, log, checkout, branch, and merge commands.\n"
            "Starter code is in the proj2 directory. Follow the test "
            "harness in proj2/tests. Deliverables: gitlet/Repository.java "
            "and gitlet/Commit.java. Grading: autograder 70%, style 10%, "
            "design doc 20%. Due Nov 14 at 11:59pm."
        ),
        expected_output="assignment",
        metadata={"is_syllabus": False},
    ),
    # ── READING — READING LIST PDF ───────────────────────────────────────
    Case(
        name="reading_list_pdf",
        inputs=(
            "ENG 305 — Suggested Readings (not graded)\n\n"
            "Background: Said, Orientalism, ch. 1.\n"
            "For week 4: Foucault, Discipline and Punish, pp. 195-228.\n"
            "Optional: Butler, Gender Trouble, intro.\n"
            "These readings supplement the assigned texts; bring questions "
            "to office hours if interested."
        ),
        expected_output="reading",
        metadata={"is_syllabus": False},
    ),
    # ── SLIDES — SPARSE BULLETS ──────────────────────────────────────────
    Case(
        name="slides_sparse_bullets",
        inputs=(
            "Slide 1: Intro to Photosynthesis\n"
            "• Light reactions\n• Calvin cycle\n• ATP / NADPH\n\n"
            "Slide 2: Light reactions\n"
            "• PSII → PSI\n• Water splitting\n• Electron transport\n\n"
            "Slide 3: Calvin cycle\n"
            "• Carbon fixation\n• Reduction\n• Regeneration of RuBP"
        ),
        expected_output="slides",
        metadata={"is_syllabus": False},
    ),
    # ── LECTURE NOTES — HEAVILY MATHEMATICAL ─────────────────────────────
    Case(
        name="math_heavy_lecture_notes",
        inputs=(
            "Lecture 12 — Fourier Series\n\n"
            "For a 2π-periodic function f, the Fourier coefficients are\n"
            "  a_n = (1/π) ∫_{-π}^{π} f(x) cos(nx) dx,\n"
            "  b_n = (1/π) ∫_{-π}^{π} f(x) sin(nx) dx.\n"
            "Parseval's identity gives ∫ f^2 = π(a_0^2/2 + Σ (a_n^2 + b_n^2)).\n"
            "The Dirichlet kernel D_n(x) = sin((n+1/2)x) / sin(x/2) controls "
            "pointwise convergence."
        ),
        expected_output="lecture_notes",
        metadata={"is_syllabus": False},
    ),
    # ── PAST EXAM — DIFFERENT SUBJECT (history) → other ──────────────────
    Case(
        name="past_history_exam",
        inputs=(
            "HIST 110 — Final Examination — 3 hours — closed book\n\n"
            "Section A: Identify and give the historical significance of any "
            "FIVE (5 points each):\n"
            "  Treaty of Westphalia, Glorious Revolution, Tennis Court Oath, "
            "Bismarck's Kulturkampf, Versailles 1919.\n"
            "Section B: Essay (50 points). 'The 19th century was the long "
            "consequence of the French Revolution.' Discuss with reference "
            "to at least three countries."
        ),
        expected_output="other",
        metadata={"is_syllabus": False},
    ),
    # ── STUDY GUIDE THAT OVERLAPS WITH SYLLABUS → study_guide ───────────
    Case(
        name="study_guide_overlapping_syllabus",
        inputs=(
            "MIDTERM 1 STUDY GUIDE — PSYCH 101\n\n"
            "Coverage: chapters 1-5 (matches the syllabus weeks 1-5).\n"
            "Topics to know:\n"
            "1. Methods: experimental vs. observational, IV/DV, "
            "confounding.\n"
            "2. Neurons: action potential, synaptic transmission.\n"
            "3. Sensation & perception: thresholds, signal detection.\n"
            "4. Learning: classical and operant conditioning.\n"
            "Practice questions follow each topic; answer key on p. 8."
        ),
        expected_output="study_guide",
        metadata={"is_syllabus": False},
    ),
    # ── GRADING RUBRIC (NOT a syllabus) → other ──────────────────────────
    Case(
        name="grading_rubric",
        inputs=(
            "Essay Grading Rubric\n\n"
            "Thesis (20 pts): clear, arguable, addresses the prompt.\n"
            "Evidence (30 pts): specific textual citations supporting "
            "each claim.\n"
            "Analysis (30 pts): connects evidence to thesis with reasoning.\n"
            "Style & mechanics (20 pts): clarity, grammar, citation format.\n"
            "Total: 100 pts. A = 90+, B = 80-89, C = 70-79."
        ),
        expected_output="other",
        metadata={"is_syllabus": False},
    ),
    # ── REQUIRED READINGS LIST WITH WEEKS (lean syllabus due to schedule) ─
    Case(
        name="required_readings_with_weeks",
        inputs=(
            "PHIL 220 — Required Readings by Week\n\n"
            "Week 1: Plato, Republic Bk. I.\n"
            "Week 2: Aristotle, Nicomachean Ethics Bk. I-II.\n"
            "Week 3: Augustine, Confessions Bk. VII.\n"
            "Week 4: Aquinas, Summa Theologica Q. 1-3.\n"
            "Week 5: Descartes, Meditations I-III.\n"
            "Bring the printed text to lecture. Reading responses due each "
            "Wednesday."
        ),
        expected_output="syllabus",
        metadata={"is_syllabus": True},
    ),
    # ── NON-ENGLISH ASSIGNMENT (French) ─────────────────────────────────
    Case(
        name="french_assignment",
        inputs=(
            "Devoir 4 — à rendre vendredi\n\n"
            "1. Traduisez les phrases suivantes en français en utilisant le "
            "subjonctif.\n"
            "2. Rédigez un paragraphe de 200 mots sur le thème 'la "
            "francophonie au Québec'.\n"
            "3. Conjuguez les verbes irréguliers donnés au passé composé et "
            "à l'imparfait.\n"
            "Travail individuel. Aucune ressource en ligne."
        ),
        expected_output="assignment",
        metadata={"is_syllabus": False},
    ),
    # ── NEAR-EMPTY DOC (default → lecture_notes) ─────────────────────────
    Case(
        name="near_empty_doc",
        inputs="Lecture 1 notes\n\n[page intentionally left blank]",
        expected_output="lecture_notes",
        metadata={"is_syllabus": False},
    ),
    # ── RESEARCH PAPER PDF → reading ────────────────────────────────────
    Case(
        name="research_paper",
        inputs=(
            "Attention Is All You Need\n"
            "Vaswani et al., NeurIPS 2017\n\n"
            "Abstract. The dominant sequence transduction models are based "
            "on complex recurrent or convolutional neural networks. We "
            "propose a new simple network architecture, the Transformer, "
            "based solely on attention mechanisms, dispensing with "
            "recurrence and convolutions entirely.\n\n"
            "1. Introduction. Recurrent neural networks, long short-term "
            "memory, and gated recurrent neural networks have been firmly "
            "established as state-of-the-art..."
        ),
        expected_output="reading",
        metadata={"is_syllabus": False},
    ),
    # ── COURSE WELCOME LETTER (no schedule → other; not syllabus) ────────
    Case(
        name="course_welcome_letter_no_schedule",
        inputs=(
            "Welcome to BIO 130!\n\n"
            "I'm Prof. Lee and I'm thrilled to have you in class this term. "
            "A few things to know up front: my office hours are by "
            "appointment, please email at least 24 hours ahead. Be kind to "
            "your classmates and the lab TAs. Academic integrity matters — "
            "if you're unsure whether something counts as collaboration, "
            "ask. We'll go over the schedule and grading on the first day."
        ),
        expected_output="other",
        metadata={"is_syllabus": False},
    ),
    # ── LATEX-SOURCE NOISE (content is a problem set) → assignment ──────
    Case(
        name="latex_source_problem_set",
        inputs=(
            "\\documentclass{article}\n"
            "\\title{Problem Set 7}\\author{Math 314}\n"
            "\\begin{document}\\maketitle\n\n"
            "\\textbf{Problem 1.} Let $G$ be a finite group of order $p^2$. "
            "Prove that $G$ is abelian.\n\n"
            "\\textbf{Problem 2.} Show that $\\mathbb{Z}/n\\mathbb{Z}$ is "
            "a field iff $n$ is prime.\n\n"
            "\\textbf{Problem 3.} Find all subgroups of $S_3$.\n"
            "\\end{document}"
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
