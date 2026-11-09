"""Characterization of `achievement_service._get_user_stat` over EVERY trigger key.

Pins the value AND the exact PostgREST reads (table, columns, filters, order)
each trigger type produces, against one populated and one empty fake database,
so the #118 dispatch-table refactor of `_get_user_stat` (McCabe 26 -> under
the 25 ceiling) is provably byte-identical. Trigger types whose value comes
from a dedicated helper (`_session_stat`, `_best_day_xp`, `_goal_streak`,
`_course_grade_a_count`) are pinned on the delegation (helper + arguments);
those helpers have their own tests.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from services import achievement_service

_NOW = datetime.now(timezone.utc)
_CREATED = (_NOW - timedelta(days=10, hours=1)).isoformat().replace("+00:00", "Z")


def _populated(name, cols, filters):
    """A small, deliberately messy dataset (None values, missing keys, dupes)."""
    if name == "users":
        return [{"streak_count": 7, "created_at": _CREATED, "level": 4}]
    if name == "room_members" and "room_id" in filters:
        return [{"user_id": "x"}] * {"eq.r1": 5, "eq.r2": 3}.get(filters["room_id"], 0)
    if name == "rooms":
        return [{"id": "r1"}, {"id": "r2"}]
    if name == "flashcards" and cols == "times_reviewed":
        return [{"times_reviewed": 3}, {"times_reviewed": None}, {"times_reviewed": "4"}]
    if name == "room_messages" and cols == "room_id":
        return [{"room_id": "r1"}, {"room_id": "r9"}, {"room_id": "r9"},
                {"room_id": None}, {}]
    if name == "graph_nodes" and cols == "course_id":
        return [{"course_id": "c1"}, {"course_id": "c1"}, {"course_id": "c2"},
                {"course_id": None}]
    if name == "graph_nodes" and "mastery_tier" in filters:
        return [{"user_id": "u1"}] * 2
    counts = {"sessions": 3, "documents": 2, "quiz_attempts": 4, "room_members": 6,
              "flashcards": 6, "room_messages": 8, "graph_nodes": 9, "friendships": 1}
    return [{"user_id": "u1"}] * counts.get(name, 0)


def _empty(name, cols, filters):
    return None


def _run(trigger_type, data):
    calls = []

    def _table(name):
        handle = MagicMock()

        def _select(cols, filters=None):
            calls.append((name, cols, dict(filters or {})))
            return data(name, cols, filters or {})

        handle.select.side_effect = _select
        return handle

    with patch("services.achievement_service.table", side_effect=_table):
        value = achievement_service._get_user_stat("u1", trigger_type)
    return value, calls


_U = {"user_id": "eq.u1"}
_ID = {"id": "eq.u1"}
_MASTERED = {"user_id": "eq.u1", "mastery_tier": "eq.mastered"}

# trigger_type -> (populated value, empty value, reads in order)
DIRECT = {
    "login_streak": (7, 0, [("users", "streak_count", _ID)]),
    "session_count": (3, 0, [("sessions", "user_id", _U)]),
    "documents_uploaded": (2, 0, [("documents", "user_id", _U)]),
    "quizzes_completed": (4, 0, [("quiz_attempts", "user_id", {
        "user_id": "eq.u1", "completed_at": "not.is.null", "score": "not.is.null",
    })]),
    "rooms_joined": (6, 0, [("room_members", "user_id", _U)]),
    "flashcards_created": (6, 0, [("flashcards", "user_id", _U)]),
    "post_count": (8, 0, [("room_messages", "user_id", _U)]),
    "account_age_days": (10, 0, [("users", "created_at", _ID)]),
    "manual_admin_grant": (0, 0, []),
    "flashcards_reviewed": (7, 0, [("flashcards", "times_reviewed", _U)]),
    "concepts_mastered": (2, 0, [("graph_nodes", "user_id", _MASTERED)]),
    "courses_with_mastery": (2, 0, [("graph_nodes", "course_id", _MASTERED)]),
    "graph_nodes_count": (9, 0, [("graph_nodes", "user_id", _U)]),
    "friends_count": (1, 0, [("friendships", "user_id", _U)]),
    "level": (4, 1, [("users", "level", _ID)]),
    "owned_room_members": (5, 0, [
        ("rooms", "id", {"created_by": "eq.u1"}),
        ("room_members", "user_id", {"room_id": "eq.r1"}),
        ("room_members", "user_id", {"room_id": "eq.r2"}),
    ]),
    "rooms_active": (2, 0, [("room_messages", "room_id", _U)]),
    "room_replies": (4, 0, [
        ("rooms", "id", {"created_by": "eq.u1"}),
        ("room_messages", "room_id", _U),
    ]),
    "unknown_type": (0, 0, []),
    "": (0, 0, []),
}

# On the empty database the multi-read stats stop after the first read.
EMPTY_READS = {
    "owned_room_members": [("rooms", "id", {"created_by": "eq.u1"})],
}

# trigger_type -> (helper name, positional args after user_id)
DELEGATED = {
    "session_minutes": ("_session_stat", ("session_minutes",)),
    "session_before_hour": ("_session_stat", ("session_before_hour",)),
    "session_after_midnight": ("_session_stat", ("session_after_midnight",)),
    "xp_in_day": ("_best_day_xp", ()),
    "goal_streak": ("_goal_streak", ()),
    "course_grade_a": ("_course_grade_a_count", ()),
}


@pytest.mark.parametrize("trigger_type", sorted(DIRECT))
def test_direct_stat_populated(trigger_type):
    value, empty_value, reads = DIRECT[trigger_type]
    assert _run(trigger_type, _populated) == (value, reads)


@pytest.mark.parametrize("trigger_type", sorted(DIRECT))
def test_direct_stat_empty(trigger_type):
    _, empty_value, reads = DIRECT[trigger_type]
    assert _run(trigger_type, _empty) == (empty_value, EMPTY_READS.get(trigger_type, reads))


@pytest.mark.parametrize("trigger_type", sorted(DELEGATED))
def test_delegated_stat(trigger_type):
    helper, extra = DELEGATED[trigger_type]
    with patch(f"services.achievement_service.{helper}", return_value=41) as h:
        value, reads = _run(trigger_type, _populated)
    assert value == 41
    h.assert_called_once_with("u1", *extra)
    assert reads == []


def test_every_dispatched_trigger_type_is_characterized():
    """A trigger type added to the dispatch table must be pinned here too."""
    known = (set(DIRECT) | set(DELEGATED)) - {"unknown_type", ""}
    assert set(achievement_service._STAT_READERS) == known


#: DIRECT trigger types -> the module helper their reader resolves at call
#: time (`_count_rows` for the `_count_own` readers). `manual_admin_grant` is
#: a constant 0 and reads nothing.
NAMED_READERS = {
    "login_streak": "_stat_login_streak",
    "quizzes_completed": "_stat_quizzes_completed",
    "account_age_days": "_stat_account_age_days",
    "flashcards_reviewed": "_stat_flashcards_reviewed",
    "courses_with_mastery": "_stat_courses_with_mastery",
    "level": "_stat_level",
    "owned_room_members": "_stat_owned_room_members",
    "rooms_active": "_stat_rooms_active",
    "room_replies": "_stat_room_replies",
    **{t: "_count_rows" for t in (
        "session_count", "documents_uploaded", "rooms_joined", "flashcards_created",
        "post_count", "concepts_mastered", "graph_nodes_count", "friends_count",
    )},
}


@pytest.mark.parametrize("trigger_type", sorted(NAMED_READERS))
def test_a_patched_reader_is_honoured(trigger_type):
    """The dispatch looks every helper up at call time (PR #851 review): a
    `patch.object` on the module reaches `_get_user_stat`."""
    with patch.object(achievement_service, NAMED_READERS[trigger_type], return_value=42) as h:
        assert achievement_service._get_user_stat("u1", trigger_type) == 42
    h.assert_called_once()


def test_named_readers_cover_every_direct_trigger():
    assert set(NAMED_READERS) == set(DIRECT) - {"manual_admin_grant", "unknown_type", ""}
