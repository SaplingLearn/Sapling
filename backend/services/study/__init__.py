"""Study domain (#118): the Study hub's Daily Goal panel. ``routes/study.py``
is the HTTP layer over these.

- ``daily``: ``get_daily``, the estimated study minutes of the last seven
  local days (the estimate's definition is that module's docstring), and
  ``local_date``, the student's day from the client's ``tz_offset_min`` —
  the day Study's review queue keeps too (#866 K17).
- ``goal``: the student's daily goal on ``user_settings.daily_goal_minutes``
  (``read_daily_goal`` / ``set_daily_goal``) and its bounds.
- ``next``: ``get_next``, the learner-next buckets for Focus / Quick Reviews
  (W8.3; gated on ``learning_loop`` + ``quiz_concept_plan``).

There is no ``errors.py``: the daily/goal handlers have no failure of their
own to report (the goal's range is the route's body validation). ``get_next``
raises FastAPI ``HTTPException`` (404 off, 503 on a failed state read). All
routes are behind ``require_self``.

The rest of the Study page lives in its own packages and routes
(``services/flashcards/``, ``routes/study_guide.py``,
``routes/topic_checklist.py``).
"""
from services.study.daily import clamp_tz_offset, get_daily, local_date
from services.study.goal import (
    DEFAULT_GOAL_MIN,
    MAX_GOAL_MIN,
    MIN_GOAL_MIN,
    read_daily_goal,
    set_daily_goal,
)
from services.study.next import get_next

__all__ = [
    "DEFAULT_GOAL_MIN",
    "MAX_GOAL_MIN",
    "MIN_GOAL_MIN",
    "clamp_tz_offset",
    "get_daily",
    "get_next",
    "local_date",
    "read_daily_goal",
    "set_daily_goal",
]
