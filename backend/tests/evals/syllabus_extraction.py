"""pydantic-evals cases for the syllabus extraction agent.

Run as evals (default mode = replay; SAPLING_EVAL_MODE=record|live for others):
    python tests/evals/syllabus_extraction.py

Add cases here when production produces a bad extraction. Do NOT edit
existing cases to make them pass.

The evaluators check the contracts in agents/syllabus_extraction.py:
- 0-50 assignments (schema cap).
- due_date is set ONLY when a concrete calendar date appears in the
  input. Relative terms ("Week 4", "before midterm") must yield null.
- grading_categories presence matches what the syllabus actually
  states (case metadata declares the expectation).
- weight values are finite, non-negative numbers (belt-and-suspenders;
  the schema enforces ge=0.0).
"""

from __future__ import annotations

import asyncio
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Allow `python tests/evals/syllabus_extraction.py` from backend/.
# Add backend/ for `agents.*` and tests/evals/ for sibling `_replay`.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext

from agents.syllabus_extraction import (
    SyllabusAssignments,
    syllabus_extraction_agent,
)
from _replay import run_with_cassette  # noqa: E402  (sibling, sys.path-injected)


# Loose patterns that recognize concrete calendar dates in plain English,
# numeric, or ISO formats. We deliberately keep these forgiving — the
# evaluator only fires when due_date IS set, so we want to confirm SOMETHING
# date-shaped exists in the input, not that the agent picked the "right" one.
_DATE_PATTERNS = [
    # 2026-04-01, 2026/04/01
    re.compile(r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b"),
    # 4/1/2026, 4-1-26, 04/01
    re.compile(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b"),
    # April 1, 2026 / April 1 / Apr 1
    re.compile(
        r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
        r"[a-z]*\.?\s+\d{1,2}(?:,?\s*\d{4})?\b",
        re.IGNORECASE,
    ),
    # 1 April 2026 / 1 Apr
    re.compile(
        r"\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
        r"[a-z]*\.?\b",
        re.IGNORECASE,
    ),
]


def _input_has_concrete_date(text: str) -> bool:
    return any(p.search(text) for p in _DATE_PATTERNS)


@dataclass
class AssignmentCountEvaluator(Evaluator[str, SyllabusAssignments]):
    """Pass when the assignment list respects the schema cap of 50."""

    def evaluate(
        self, ctx: EvaluatorContext[str, SyllabusAssignments]
    ) -> float:
        return 1.0 if len(ctx.output.assignments) <= 50 else 0.0


@dataclass
class NoInventedDatesEvaluator(Evaluator[str, SyllabusAssignments]):
    """Fail when due_date is set but the input contains no concrete date.

    The system prompt forbids inventing dates from relative terms. If
    ANY assignment has a non-null due_date AND the input has no
    recognizable date string, the agent invented something.
    """

    def evaluate(
        self, ctx: EvaluatorContext[str, SyllabusAssignments]
    ) -> float:
        any_due = any(a.due_date is not None for a in ctx.output.assignments)
        if not any_due:
            return 1.0  # vacuously fine
        return 1.0 if _input_has_concrete_date(ctx.inputs) else 0.0


@dataclass
class GradingCategoriesPresenceEvaluator(Evaluator[str, SyllabusAssignments]):
    """Match grading_categories presence to case metadata.

    Cases with metadata={"has_grading_breakdown": True} expect a
    non-empty grading_categories list; cases without it expect an
    empty list (the schema default).
    """

    def evaluate(
        self, ctx: EvaluatorContext[str, SyllabusAssignments]
    ) -> float:
        expected = bool(
            ctx.metadata.get("has_grading_breakdown", False)
            if ctx.metadata
            else False
        )
        actual = len(ctx.output.grading_categories) > 0
        return 1.0 if expected == actual else 0.0


@dataclass
class WeightsAreNumericEvaluator(Evaluator[str, SyllabusAssignments]):
    """Pass when every grading_category weight is finite and non-negative."""

    def evaluate(
        self, ctx: EvaluatorContext[str, SyllabusAssignments]
    ) -> float:
        for cat in ctx.output.grading_categories:
            if cat.weight is None:
                return 0.0
            try:
                w = float(cat.weight)
            except (TypeError, ValueError):
                return 0.0
            if not math.isfinite(w) or w < 0:
                return 0.0
        return 1.0


CASES: list[Case[str, None]] = [
    # ── 1. TYPICAL SYLLABUS — concrete dates + grading breakdown ─────────
    Case(
        name="typical_syllabus_with_dates",
        inputs=(
            "CS 188 — Spring 2026 — Instructor: Smith.\n"
            "Schedule:\n"
            "  Problem Set 1 — due February 5, 2026\n"
            "  Problem Set 2 — due February 19, 2026\n"
            "  Midterm — March 12, 2026\n"
            "  Final Project — May 1, 2026\n"
            "Grading: Problem sets 40%, Midterm 25%, Final Project 35%."
        ),
        metadata={"has_grading_breakdown": True},
    ),
    # ── 2. RELATIVE DATES ONLY → all due_dates null ──────────────────────
    Case(
        name="relative_dates_only",
        inputs=(
            "MATH 220 — Tentative Plan.\n"
            "  Quiz 1 — Week 3\n"
            "  Quiz 2 — Week 6\n"
            "  Midterm — before Spring break\n"
            "  Final — end of term\n"
            "Grading: Quizzes 20%, Midterm 30%, Final 50%."
        ),
        metadata={"has_grading_breakdown": True},
    ),
    # ── 3. MIXED DATES — only concrete ones get due_date ─────────────────
    Case(
        name="mixed_concrete_and_relative_dates",
        inputs=(
            "BIO 201 — Schedule.\n"
            "  Lab Report 1 — due September 12, 2026\n"
            "  Lab Report 2 — due Week 8\n"
            "  Midterm — October 17, 2026\n"
            "  Final — last week of class\n"
            "Grading: Labs 30%, Midterm 30%, Final 40%."
        ),
        metadata={"has_grading_breakdown": True},
    ),
    # ── 4. POINTS-BASED RUBRIC (sums to 200) — pass weights verbatim ────
    Case(
        name="points_based_rubric",
        inputs=(
            "PHIL 101 — Grading.\n"
            "  Reading responses: 40 points\n"
            "  Midterm essay: 60 points\n"
            "  Final essay: 100 points\n"
            "Total: 200 points. Letter grades follow a standard scale.\n"
            "No fixed assignment dates — see weekly schedule online."
        ),
        metadata={"has_grading_breakdown": True},
    ),
    # ── 5. NO GRADING BREAKDOWN ──────────────────────────────────────────
    Case(
        name="no_grading_breakdown",
        inputs=(
            "ART 110 — Course outline. Studio sessions Mon/Wed; critiques "
            "Fridays. Sketchbook required at every session. Final "
            "portfolio due at the end of term. Grading is holistic and "
            "discussed individually with the instructor."
        ),
        metadata={"has_grading_breakdown": False},
    ),
    # ── 6. NON-ENGLISH (Spanish) WITH CONCRETE DATES ─────────────────────
    Case(
        name="spanish_syllabus_concrete_dates",
        inputs=(
            "Cálculo I — Semestre primavera 2026.\n"
            "  Tarea 1 — entrega 10 de febrero de 2026\n"
            "  Parcial — 15 de marzo de 2026\n"
            "  Examen final — 5 de mayo de 2026\n"
            "Evaluación: Tareas 20%, Parcial 30%, Final 50%."
        ),
        metadata={"has_grading_breakdown": True},
    ),
    # ── 7. COURSE HANDBOOK DISGUISED AS A SYLLABUS ───────────────────────
    Case(
        name="course_handbook_disguised",
        inputs=(
            "BIO 130 Course Handbook. Section 1: academic integrity "
            "policies. Section 2: late work — 10% per day, max 3 days. "
            "Section 3: accommodations process. The handbook references "
            "graded items but does not list them with dates."
        ),
        metadata={"has_grading_breakdown": False},
    ),
    # ── 8. MINIMAL SYLLABUS — just topics, no deliverables ───────────────
    Case(
        name="minimal_topics_only",
        inputs=(
            "Intro to Linguistics — topics by week. Phonetics, "
            "phonology, morphology, syntax, semantics, pragmatics, "
            "sociolinguistics, historical linguistics."
        ),
        metadata={"has_grading_breakdown": False},
    ),
    # ── 9. OVERLAPPING DEADLINES — same date, two assignments ────────────
    Case(
        name="overlapping_deadlines",
        inputs=(
            "ENG 305 — Spring 2026.\n"
            "  Reading response 1 — due March 5, 2026\n"
            "  Peer review — due March 5, 2026\n"
            "  Essay 1 — due April 2, 2026\n"
            "Grading: Responses 20%, Peer review 10%, Essays 70%."
        ),
        metadata={"has_grading_breakdown": True},
    ),
    # ── 10. WEIGHTS STATED TWICE (header + table) — no duplicates ────────
    Case(
        name="weights_stated_twice",
        inputs=(
            "ECON 101 — Grading at a glance: Quizzes 20%, Midterm 30%, "
            "Final 50%.\n\n"
            "Detailed grading table:\n"
            "  Quizzes — 20%\n"
            "  Midterm — 30%\n"
            "  Final — 50%\n\n"
            "Quiz 1 due February 1, 2026. Midterm March 14, 2026. "
            "Final May 7, 2026."
        ),
        metadata={"has_grading_breakdown": True},
    ),
    # ── 11. FOREIGN-SCRIPT EXCERPT — graceful, doesn't crash ─────────────
    # Mandarin excerpt with no concrete date. No grading breakdown stated.
    Case(
        name="mandarin_syllabus_excerpt",
        inputs=(
            "课程大纲：高等数学 I。本课程涵盖极限、导数、积分与级数的基本"
            "概念。每周一次作业。学期末有期末考试。请按时上课，认真听讲。"
        ),
        metadata={"has_grading_breakdown": False},
    ),
    # ── 12. GRADING SECTION SAYS "TBD" — empty grading_categories ────────
    Case(
        name="grading_tbd",
        inputs=(
            "PHYS 101 — Spring 2026.\n"
            "  Lab 1 — due February 7, 2026\n"
            "  Lab 2 — due February 21, 2026\n"
            "  Final exam — May 4, 2026\n"
            "Grading breakdown: TBD. Will be announced in week 1."
        ),
        metadata={"has_grading_breakdown": False},
    ),
    # ── 13. WEEKLY TOPICS WITH NO NAMED DELIVERABLES ─────────────────────
    Case(
        name="weekly_topics_no_deliverables",
        inputs=(
            "PSY 240 — Weekly schedule.\n"
            "Week 1: Topic A. Week 2: Topic B. Week 3: Topic C. "
            "Week 4: Topic D. Week 5: Topic E.\n"
            "No graded items listed in this section; see the assignments "
            "page on the LMS."
        ),
        metadata={"has_grading_breakdown": False},
    ),
    # ── 14. EXAM-ONLY SCHEDULE → only the two exams extracted ────────────
    Case(
        name="exam_only_schedule",
        inputs=(
            "HIST 110 — Examinations.\n"
            "  Midterm — October 15, 2026\n"
            "  Final — December 12, 2026\n"
            "No other graded items. Grading: Midterm 40%, Final 60%."
        ),
        metadata={"has_grading_breakdown": True},
    ),
    # ── 15. POLICIES ONLY (late policy + office hours, no graded items) ──
    Case(
        name="policies_only_no_graded_items",
        inputs=(
            "MATH 102 — Course Policies. Office hours: Tuesdays 2-4pm. "
            "Late policy: 10% per day for up to three days, then zero. "
            "Academic integrity: collaboration is encouraged on study, "
            "but submitted work must be your own. Email is the primary "
            "channel for questions outside class."
        ),
        metadata={"has_grading_breakdown": False},
    ),
]


_INPUT_TO_NAME: dict[str, str] = {case.inputs: case.name for case in CASES}


async def _run(case_input: str) -> SyllabusAssignments:
    """Adapter: route through the cassette layer (record/replay/live)."""
    case_name = _INPUT_TO_NAME.get(case_input, "unknown")
    return await run_with_cassette(
        dataset="syllabus_extraction",
        case_name=case_name,
        agent=syllabus_extraction_agent,
        case_input=case_input,
        output_model=SyllabusAssignments,
    )


def make_dataset() -> Dataset[str, None]:
    return Dataset(
        name="syllabus_extraction",
        cases=CASES,
        evaluators=[
            AssignmentCountEvaluator(),
            NoInventedDatesEvaluator(),
            GradingCategoriesPresenceEvaluator(),
            WeightsAreNumericEvaluator(),
        ],
    )


if __name__ == "__main__":
    from _replay import cli_main  # noqa: E402

    cli_main(make_dataset, _run)
