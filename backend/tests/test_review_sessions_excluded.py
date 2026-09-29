"""PKG-12 fix round (MAJOR 1): daily review sessions (`sessions.mode = 'review'`,
learning/review.py) are not tutor sessions. Every reader that treats a `sessions`
row as a tutor session excludes them — the Learn session list / Dashboard "Where
you left off" and its resume, the quiz personalization's tutor count, the profile
session count and the achievement stats — and a review session announces itself
with `review.session_started`, never `session.started` (canopy_metrics'
`tutor_sessions` counts that event)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from services.session_modes import NOT_REVIEW, REVIEW_MODE

USER = "u1"


class _Spy:
    """table() stand-in recording every sessions read's filters."""

    def __init__(self, rows=None):
        self.filters: list[dict] = []
        self.rows = rows or []

    def __call__(self, name):
        handle = MagicMock(name=name)

        def select(columns="*", filters=None, **kw):
            if name == "sessions":
                self.filters.append(dict(filters or {}))
            return list(self.rows) if name == "sessions" else []

        def select_with_count(columns="*", filters=None, **kw):
            return select(columns, filters, **kw), len(self.rows)

        handle.select.side_effect = select
        handle.select_with_count.side_effect = select_with_count
        return handle


def test_the_mode_constant_and_filter():
    assert REVIEW_MODE == "review"
    assert NOT_REVIEW == {"mode": "neq.review"}  # sessions.mode is NOT NULL (0025)


def test_review_module_uses_the_shared_mode():
    from learning import review

    assert review._REVIEW_MODE == REVIEW_MODE


def test_list_sessions_excludes_review_sessions(monkeypatch):
    from routes import learn

    spy = _Spy()
    monkeypatch.setattr(learn, "table", spy)
    monkeypatch.setattr(learn, "require_self", lambda *a, **k: None)
    learn.list_sessions(USER, MagicMock())
    assert spy.filters and all(f.get("mode") == "neq.review" for f in spy.filters)


def test_resume_never_reopens_a_review_session(monkeypatch):
    from fastapi import HTTPException

    from routes import learn

    spy = _Spy()
    monkeypatch.setattr(learn, "table", spy)
    monkeypatch.setattr(learn, "get_session_user_id", lambda request: USER)
    with pytest.raises(HTTPException) as exc:
        learn.resume_session("sess-review", MagicMock())
    assert exc.value.status_code == 404
    assert spy.filters[-1].get("mode") == "neq.review"


def test_quiz_tutor_signal_excludes_review_sessions(monkeypatch):
    from services import quiz_signals

    spy = _Spy()
    monkeypatch.setattr(quiz_signals, "table", spy)
    quiz_signals._tutor_recency(USER, quiz_signals.CourseScope(offering_ids=["off-1"]), "Recursion")
    assert spy.filters and spy.filters[0].get("mode") == "neq.review"


def test_profile_session_count_excludes_review_sessions(monkeypatch):
    from routes import profile

    spy = _Spy()
    monkeypatch.setattr(profile, "table", spy)
    profile._get_user_stats(USER)
    assert spy.filters and all(f.get("mode") == "neq.review" for f in spy.filters)


@pytest.mark.parametrize("trigger", ["session_count", "session_minutes", "session_before_hour"])
def test_achievement_session_stats_exclude_review_sessions(monkeypatch, trigger):
    from services import achievement_service

    spy = _Spy()
    monkeypatch.setattr(achievement_service, "table", spy)
    achievement_service._get_user_stat(USER, trigger)
    assert spy.filters and all(f.get("mode") == "neq.review" for f in spy.filters)


def test_review_session_emits_its_own_start_event(monkeypatch):
    from learning import review

    handle = MagicMock()
    handle.select.return_value = []
    monkeypatch.setattr(review, "table", lambda name: handle)
    events = []
    monkeypatch.setattr(review, "log_event", lambda et, **kw: events.append((et, kw)))
    review.load_or_create_review_session(USER, None, datetime(2026, 9, 26, tzinfo=timezone.utc))
    assert [e[0] for e in events] == ["review.session_started"]
    assert "session.started" not in [e[0] for e in events]
    assert handle.insert.call_args.args[0]["mode"] == REVIEW_MODE


def test_review_session_started_is_in_the_taxonomy():
    from services.events_service import EVENT_TAXONOMY

    assert "review.session_started" in EVENT_TAXONOMY
