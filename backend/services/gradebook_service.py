"""
backend/services/gradebook_service.py — re-export shim (#118).

The grade math moved to ``services/gradebook/grades.py``. This path stays so
existing imports (``from services import gradebook_service``) keep working;
new code imports ``services.gradebook.grades``.
"""
from services.gradebook.grades import (  # noqa: F401  (re-export, #118)
    DEFAULT_LETTER_SCALE,
    LETTER_GRADE_POINTS,
    AssignmentRow,
    CategoryRow,
    _class_stats_from_assignments,
    _coerce_drop,
    all_dropped_ids,
    apply_curve,
    category_grade,
    current_grade,
    dropped_assignment_ids,
    gpa_points,
    letter_for,
    weighted_gpa,
)
