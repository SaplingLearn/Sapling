"""Study domain (#118): the Study hub's Daily Goal panel. ``routes/study.py``
is the HTTP layer over these.

- ``daily``: ``get_daily``, the estimated study minutes of the last seven
  local days (the estimate's definition is that module's docstring).
- ``goal``: the student's daily goal on ``user_settings.daily_goal_minutes``
  (``read_daily_goal`` / ``set_daily_goal``) and its bounds.

There is no ``errors.py``: neither handler has a failure of its own to
report. The goal's range is the route's body validation, and both routes are
behind ``require_self``.

The rest of the Study page lives in its own packages and routes
(``services/flashcards/``, ``routes/study_guide.py``,
``routes/topic_checklist.py``).
"""
from services.study.daily import get_daily
from services.study.goal import (
    DEFAULT_GOAL_MIN,
    MAX_GOAL_MIN,
    MIN_GOAL_MIN,
    read_daily_goal,
    set_daily_goal,
)

__all__ = [
    "DEFAULT_GOAL_MIN",
    "MAX_GOAL_MIN",
    "MIN_GOAL_MIN",
    "get_daily",
    "read_daily_goal",
    "set_daily_goal",
]
