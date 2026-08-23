"""How close is the student's next exam in this course? (#555, H3)

`assignments.due_date` is plaintext and indexed, and nothing anywhere computed
"exam in N days" — so a quiz taken the night before a midterm was generated
exactly like one taken in week two. This module answers that one question.

**Dates only.** No grade VALUES enter any prompt from here. The audit flags
that the current ToS and privacy policy don't clearly cover feeding grades to
a model, and this feature does not need them: proximity is a property of the
calendar, not of performance. `points_earned`/`points_possible` are encrypted
anyway (#521) and are neither read nor decrypted here.

The exam heuristic is EXTRACTED from `routes/study_guide.py` rather than
re-implemented — `is_exam` is now the single definition and the study-guide
picker calls it. A second copy would drift, which is exactly the failure #557
spent a workstream undoing one issue earlier.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from typing import Any

from db.connection import table
from services.academics import user_enrollment_ids, user_offering_ids_for_course

logger = logging.getLogger(__name__)

#: Titles that mean "exam" even when `assignment_type` says otherwise —
#: instructors type these into the title far more reliably than they set the
#: type field.
_EXAM_KEYWORDS = ("exam", "midterm", "final", "quiz")

#: The SAME words, but anchored, for the decision path. See `is_exam_strict`.
_STRICT_EXAM_PATTERN = re.compile(
    r"\b(exam|midterm|final(?!\s+draft)|finals)\b", re.IGNORECASE
)

#: Only say something about an exam that is actually near. Beyond this, the
#: sentence carries no proximity signal — see `days_until_next_exam`.
PROMPT_HORIZON_DAYS = 14


def is_exam(assignment: dict[str, Any]) -> bool:
    """Whether one assignment row reads as an exam, LOOSELY.

    THE definition for the study-guide picker, which is a user-visible list
    where a false positive costs the student one extra row to look at.
    `routes/study_guide.py` calls this; do not re-derive it.
    """
    atype = (assignment.get("assignment_type") or "").lower()
    title = (assignment.get("title") or "").lower()
    return atype == "exam" or any(kw in title for kw in _EXAM_KEYWORDS)


def is_exam_strict(assignment: dict[str, Any]) -> bool:
    """Whether one row is an exam, for a DECISION rather than a list.

    Deliberately tighter than `is_exam`, because the cost of a false positive
    is different here. The picker shows an extra row; this drives a prompt and
    writes `quiz_attempts.exam_days_away`, which exists to answer "do
    deadline-aware quizzes perform differently?". Loose matching poisons that
    question at the source: a course with weekly "Quiz 3"/"Quiz 4" rows has an
    "exam" within a week all semester, so the treatment group silently becomes
    "any course with weekly quizzes".

    Two changes from the loose form:
      * "quiz" is not a keyword. A graded weekly quiz is not the deadline this
        feature is about, and `assignment_type == "exam"` still catches one
        that genuinely is.
      * word-anchored, so "Final draft - essay 2" is no longer a final.
    """
    if (assignment.get("assignment_type") or "").lower() == "exam":
        return True
    return bool(_STRICT_EXAM_PATTERN.search(assignment.get("title") or ""))


def _today() -> date:
    """Seam so tests can pin "now" without freezing the process clock.

    UTC, matching every other date boundary in the codebase
    (`routes/study_guide.py`, `routes/calendar.py`). A naive local date would
    put this module a day out from the study-guide filter on any deployment
    whose process TZ is not UTC — the same exam "today" in one surface and
    "tomorrow" in the other, and `exam_days_away` off by one for the very
    analytics the column exists to enable.
    """
    return datetime.now(timezone.utc).date()


def _enrollment_ids(offering_ids: list[str], user_id: str) -> list[str]:
    """Enrollment resolution via `services/academics.py`, which CLAUDE.md
    names as its single home — and which has already read this user's
    enrollments inside `user_offering_ids_for_course`. Intersecting in memory
    costs nothing and keeps the resolution in one place."""
    wanted = set(offering_ids)
    return [
        r["id"]
        for r in user_enrollment_ids(user_id)
        if r.get("id") and r.get("offering_id") in wanted
    ]


def days_until_next_exam(
    user_id: str,
    course_id: str | None,
    *,
    offering_ids: list[str] | None = None,
) -> int | None:
    """Whole days until this student's soonest UPCOMING exam in the course.

    `0` means "today" and is the most actionable value this produces — it is
    deliberately distinct from `None`, which means "no upcoming exam, or we
    could not tell". Collapsing the two would drop the exact case the feature
    exists for.

    `offering_ids` injects a resolution the caller already paid for.
    `user_offering_ids_for_course` is two UNCACHED reads, and the quiz
    generation path now needs the same answer in a concurrent leg — passing it
    in is the difference between asking once and asking twice. `None` means
    "not supplied, resolve it yourself", so existing callers are unaffected;
    it also covers "the caller's own resolution failed", where re-resolving
    costs one read in an already-degraded request and keeps this honest.

    Never raises: this runs inline on the quiz generation path, and one
    optional prompt line is not worth failing a generation over.
    """
    if not course_id:
        return None
    try:
        return _resolve(user_id, course_id, offering_ids)
    except Exception:
        logger.warning(
            "exam proximity lookup failed; generating without it", exc_info=True
        )
        return None


def _resolve(
    user_id: str, course_id: str, offering_ids: list[str] | None = None
) -> int | None:
    if offering_ids is None:
        offering_ids = user_offering_ids_for_course(user_id, course_id)
    if not offering_ids:
        return None
    # `assignments` is enrollment-keyed — the gradebook table carries no
    # user_id/course_id — so course -> the user's offerings -> their
    # enrollments, the same path routes/study_guide.py and routes/calendar.py
    # take.
    enrollment_ids = _enrollment_ids(offering_ids, user_id)
    if not enrollment_ids:
        return None

    rows = table("assignments").select(
        # Titles and types only. Nothing here selects a points column.
        "title,assignment_type,due_date",
        filters={
            "enrollment_id": f"in.({','.join(enrollment_ids)})",
            "due_date": "not.is.null",
        },
        order="due_date.asc",
    ) or []

    today = _today()
    # `min` rather than "take the first row": the query asks for due_date.asc,
    # but relying on that makes the answer wrong-and-silent if the ordering is
    # ever dropped from the query or degraded by the transport. The soonest
    # exam is computable here for nothing, so compute it.
    upcoming = [
        (due - today).days
        for row in rows
        if is_exam_strict(row)
        and (due := _parse_date(row.get("due_date"))) is not None
        and due >= today
    ]
    return min(upcoming) if upcoming else None


def _parse_date(raw: Any) -> date | None:
    """`due_date` is DATE in 0021 but TEXT in the 0001 baseline, so rows in the
    wild can be either. An unparseable one is skipped, never fatal."""
    # datetime BEFORE date: datetime subclasses date, so the obvious order
    # returns a datetime unconverted and the later `due - today` raises
    # TypeError into the outer catch — degrading the whole lookup to None for
    # that student, silently.
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return date.fromisoformat(raw.strip()[:10])
    except ValueError:
        return None
