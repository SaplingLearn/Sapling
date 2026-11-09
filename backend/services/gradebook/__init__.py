"""
backend/services/gradebook/ — the gradebook domain (#118).

- ``grades``: pure grade math (curve, drop-lowest, letter scale, GPA); was
  ``services/gradebook_service.py``, which stays as a re-export shim.
- ``enrollments``: (user, course, semester) → enrollment resolution, the
  category/assignment loaders and the ownership checks.
- ``syllabus``: apply a confirmed syllabus extraction to an enrollment.
- ``errors``: domain errors ``routes/gradebook.py`` maps to HTTP statuses.
"""
from __future__ import annotations

# ``grades`` first: ``enrollments`` imports it back off this package.
from services.gradebook import grades  # noqa: F401
from services.gradebook.enrollments import (
    course_meta,
    enrollment_grade,
    load_assignments,
    load_categories,
    owned_assignment,
    owned_category,
    resolve_enrollment,
)
from services.gradebook.errors import (
    DocumentNotOwned,
    GradebookError,
    InvalidCategoryWeights,
)
from services.gradebook.syllabus import apply_syllabus_to_enrollment

__all__ = [
    "DocumentNotOwned",
    "GradebookError",
    "InvalidCategoryWeights",
    "apply_syllabus_to_enrollment",
    "course_meta",
    "enrollment_grade",
    "grades",
    "load_assignments",
    "load_categories",
    "owned_assignment",
    "owned_category",
    "resolve_enrollment",
]
