"""The class's exams and assignments, due on days counted from today."""
from __future__ import annotations

from db.local_study_data import clock
from db.local_study_data.placement import Placement
from db.local_study_data.spec import Assessment

#: The ``assignment_type`` values that read as an exam everywhere the app
#: asks (the Study hub's tabs, a guide's scope, the course outline).
EXAM_KINDS = ("exam", "quiz")


def is_exam(assessment: Assessment) -> bool:
    return assessment.kind in EXAM_KINDS


def assignments(place: Placement) -> list[dict]:
    return [{
        "id": place.assessment_id(assessment.key),
        "enrollment_id": place.enrolled.enrollment_id,
        "title": assessment.title,
        "due_date": clock.due_day(place.now, assessment.in_days),
        "assignment_type": assessment.kind,
        "source": "manual",
        # 🔒 points carry numeric semantics, stored as text.
        "points_possible": str(assessment.points),
        "points_earned": None if assessment.earned is None else str(assessment.earned),
    } for assessment in place.data.assessments]
