"""The pieces ``services/study`` builds the Daily Goal panel from (#118):
timestamps, the local-day window, the bounded paged read, each source's spans,
the buckets and their rounding, and the goal read/write. ``test_study_daily.py`` drives
them together through ``get_daily`` and the routes.
"""
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import httpx
import pytest

from services.study import daily, goal
from services.study.daily import Window

UTC = timezone.utc
NOW = datetime(2026, 11, 8, 18, 0, tzinfo=UTC)


def _paged(rows):
    """A table handle whose paged read (``page_all``) answers ``rows``."""
    handle = MagicMock()
    handle.select_with_count.return_value = (list(rows), len(rows))
    return handle


# ── timestamps ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value,expected", [
    ("2026-11-08T10:00:00Z", datetime(2026, 11, 8, 10, 0, tzinfo=UTC)),
    ("2026-11-08T10:00:00+00:00", datetime(2026, 11, 8, 10, 0, tzinfo=UTC)),
    # PostgREST's own rendering: microseconds and a numeric offset.
    ("2026-11-08T05:00:00.123456-05:00", datetime(2026, 11, 8, 10, 0, 0, 123456, tzinfo=UTC)),
    # No offset at all is read as UTC, never as the server's local time.
    ("2026-11-08T10:00:00", datetime(2026, 11, 8, 10, 0, tzinfo=UTC)),
])
def test_ts_reads_what_postgrest_sends(value, expected):
    parsed = daily._ts(value)
    assert parsed == expected and parsed.tzinfo is not None


@pytest.mark.parametrize("value", [None, "", "yesterday", "2026-13-45T00:00:00Z"])
def test_ts_is_none_for_anything_unreadable(value):
    assert daily._ts(value) is None


@pytest.mark.parametrize("start,end,cap,expected", [
    ("2026-11-08T10:00:00Z", "2026-11-08T10:12:00Z", 30.0, 12.0),
    ("2026-11-08T10:00:00Z", "2026-11-08T10:00:30Z", 30.0, 0.5),
    ("2026-11-08T10:00:00Z", "2026-11-08T13:00:00Z", 30.0, 30.0),   # capped
    ("2026-11-08T10:00:00Z", "2026-11-08T10:00:00Z", 30.0, 0.0),    # no time passed
    ("2026-11-08T10:00:00Z", "2026-11-08T09:00:00Z", 30.0, 0.0),    # ends before it starts
    (None, "2026-11-08T10:00:00Z", 30.0, 0.0),
    ("2026-11-08T10:00:00Z", None, 30.0, 0.0),
    ("garbage", "2026-11-08T10:00:00Z", 30.0, 0.0),
])
def test_span_min(start, end, cap, expected):
    assert daily._span_min(start, end, cap) == expected


# ── the window ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("sent,used", [
    (0, 0), (300, 300), (-540, -540),
    # getTimezoneOffset is minutes BEHIND UTC: UTC+14 is -840, UTC-12 is +720.
    (-840, -840), (720, 720),
    (-841, -840), (721, 720), (-10**9, -840), (10**9, 720),
])
def test_clamp_tz_offset_keeps_real_offsets_and_bounds_junk(sent, used):
    assert daily.clamp_tz_offset(sent) == used


def test_window_in_utc():
    w = daily._window(0, NOW)
    assert w.today == date(2026, 11, 8)
    assert w.since == datetime(2026, 11, 2, 0, 0, tzinfo=UTC)
    assert w.days == ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05",
                      "2026-11-06", "2026-11-07", "2026-11-08"]
    assert len(w.days) == daily.DAYS


@pytest.mark.parametrize("label,tz_offset_min,now,today,since", [
    # New York (UTC-5, offset +300): 03:00 UTC is still yesterday evening.
    ("behind", 300, datetime(2026, 11, 8, 3, 0, tzinfo=UTC),
     date(2026, 11, 7), datetime(2026, 11, 1, 5, 0, tzinfo=UTC)),
    # Tokyo (UTC+9, offset -540): 18:00 UTC is already tomorrow.
    ("ahead", -540, datetime(2026, 11, 8, 18, 0, tzinfo=UTC),
     date(2026, 11, 9), datetime(2026, 11, 2, 15, 0, tzinfo=UTC)),
    # The two ends of the world, one instant: two calendar days apart.
    ("utc+14", -840, datetime(2026, 11, 8, 11, 0, tzinfo=UTC),
     date(2026, 11, 9), datetime(2026, 11, 2, 10, 0, tzinfo=UTC)),
    ("utc-12", 720, datetime(2026, 11, 8, 11, 0, tzinfo=UTC),
     date(2026, 11, 7), datetime(2026, 11, 1, 12, 0, tzinfo=UTC)),
    # A half-hour zone (India, UTC+5:30, offset -330).
    ("half-hour", -330, datetime(2026, 11, 8, 18, 45, tzinfo=UTC),
     date(2026, 11, 9), datetime(2026, 11, 2, 18, 30, tzinfo=UTC)),
])
def test_window_follows_the_client_offset(label, tz_offset_min, now, today, since):
    w = daily._window(tz_offset_min, now)
    assert w.today == today, label
    assert w.since == since, label
    assert w.days[-1] == today.isoformat() and len(w.days) == 7
    # `since` is exactly the first local day's midnight...
    assert w.local_day(since.isoformat()) == w.days[0]
    # ...and the instant before it belongs to the day before the window.
    before = (since - timedelta(seconds=1)).isoformat()
    assert w.local_day(before) not in w.days


def test_window_local_day_at_both_midnights():
    w = daily._window(300, NOW)  # UTC-5
    assert w.local_day("2026-11-08T04:59:59Z") == "2026-11-07"
    assert w.local_day("2026-11-08T05:00:00Z") == "2026-11-08"
    assert w.local_day(None) is None
    assert w.local_day("garbage") is None


# ── the three sources ────────────────────────────────────────────────────────

SINCE = datetime(2026, 11, 2, tzinfo=UTC)


def test_quiz_spans_count_on_the_completion_day():
    handle = _paged([
        {"created_at": "2026-11-07T23:50:00Z", "completed_at": "2026-11-08T00:05:00Z"},
        {"created_at": "2026-11-08T10:00:00Z", "completed_at": "2026-11-08T12:00:00Z"},
    ])
    with patch.object(daily, "table", return_value=handle) as table:
        spans = daily._quiz_spans("u1", SINCE)
    table.assert_called_once_with("quiz_attempts")
    assert spans == [("2026-11-08T00:05:00Z", 15.0), ("2026-11-08T12:00:00Z", daily.QUIZ_CAP_MIN)]


def test_card_spans_are_a_flat_half_minute_each():
    handle = _paged([{"last_reviewed_at": "2026-11-08T09:00:00Z"},
                     {"last_reviewed_at": "2026-11-07T09:00:00Z"}])
    with patch.object(daily, "table", return_value=handle) as table:
        spans = daily._card_spans("u1", SINCE)
    table.assert_called_once_with("flashcards")
    assert spans == [("2026-11-08T09:00:00Z", 0.5), ("2026-11-07T09:00:00Z", 0.5)]


def test_window_rows_is_newest_first_with_a_unique_tiebreaker():
    handle = _paged([{"n": 1}, {"n": 2}])
    with patch.object(daily, "table", return_value=handle) as table:
        rows = daily._window_rows("flashcards", "n", {"user_id": "eq.u1"}, "last_reviewed_at")
    table.assert_called_once_with("flashcards")
    assert rows == [{"n": 1}, {"n": 2}]
    args, kwargs = handle.select_with_count.call_args
    assert args == ("n",)
    assert kwargs["filters"] == {"user_id": "eq.u1"}
    assert kwargs["order"] == "last_reviewed_at.desc,id.desc"


def test_window_rows_keeps_exactly_the_bound(caplog):
    data = [{"n": i} for i in range(25)]
    handle = MagicMock()
    handle.select_with_count.side_effect = (
        lambda *a, limit, offset, **kw: (data[offset:offset + limit], len(data))
    )
    with (
        patch.object(daily, "table", return_value=handle),
        patch.object(daily, "_MAX_SOURCE_ROWS", 10),
        caplog.at_level("WARNING"),
    ):
        rows = daily._window_rows("messages", "n", {}, "created_at")
    assert rows == data[:10]  # the newest ten: the read is newest first
    assert "messages read stopped at 10 rows" in caplog.text


def test_window_rows_at_the_bound_exactly_is_not_a_cut(caplog):
    data = [{"n": i} for i in range(10)]
    with (
        patch.object(daily, "table", return_value=_paged(data)),
        patch.object(daily, "_MAX_SOURCE_ROWS", 10),
        caplog.at_level("WARNING"),
    ):
        assert daily._window_rows("messages", "n", {}, "created_at") == data
    assert "read stopped" not in caplog.text


def test_tutor_messages_reach_the_student_through_the_session():
    handle = _paged([{"session_id": "s1", "created_at": "2026-11-07T09:00:00Z",
                      "sessions": {"user_id": "u1"}}])
    with patch.object(daily, "table", return_value=handle) as table:
        rows = daily._tutor_messages("u1", SINCE)
    table.assert_called_once_with("messages")
    assert [r["session_id"] for r in rows] == ["s1"]
    args, kwargs = handle.select_with_count.call_args
    # `!inner`, or PostgREST would return every student's messages with a
    # null embed instead of filtering by the session's owner.
    assert args == ("session_id,created_at,sessions!inner(user_id)",)
    assert "content" not in args[0]
    assert kwargs["filters"] == {
        "sessions.user_id": "eq.u1", "created_at": "gte.2026-11-02T00:00:00+00:00",
    }


def _m(session_id, created_at):
    return {"session_id": session_id, "created_at": created_at}


def _spans(messages, tz_offset_min=0):
    return sorted(daily._session_day_spans(messages, daily._window(tz_offset_min, NOW)))


def test_session_day_spans_first_to_last_message_per_session_per_day():
    spans = _spans([
        # Newest first, as the read returns them; order must not matter.
        _m("a", "2026-11-08T10:15:00Z"), _m("b", "2026-11-08T09:40:00Z"),
        _m("a", "2026-11-08T10:00:00Z"), _m("b", "2026-11-08T09:30:00Z"),
        _m("a", "2026-11-06T15:30:00Z"), _m("a", "2026-11-06T15:10:00Z"),
        _m("a", "2026-11-06T15:00:00Z"),
    ])
    assert spans == [
        ("2026-11-06T15:00:00+00:00", 30.0),   # a, two days ago
        ("2026-11-08T09:30:00+00:00", 10.0),   # b, today
        ("2026-11-08T10:00:00+00:00", 15.0),   # a, today
    ]


def test_session_day_spans_cap_each_session_day():
    spans = _spans([_m("a", "2026-11-08T08:00:00Z"), _m("a", "2026-11-08T16:00:00Z")])
    assert spans == [("2026-11-08T08:00:00+00:00", daily.SESSION_CAP_MIN)]


def test_session_day_spans_split_at_local_midnight_not_utc_midnight():
    messages = [_m("a", "2026-11-08T04:40:00Z"), _m("a", "2026-11-08T04:55:00Z"),
                _m("a", "2026-11-08T05:05:00Z"), _m("a", "2026-11-08T05:25:00Z")]
    # In UTC it is one stretch of one day...
    assert _spans(messages) == [("2026-11-08T04:40:00+00:00", 45.0)]
    # ...in UTC-5 local midnight (05:00 UTC) cuts it in two.
    assert _spans(messages, tz_offset_min=300) == [
        ("2026-11-08T04:40:00+00:00", 15.0), ("2026-11-08T05:05:00+00:00", 20.0),
    ]


def test_session_day_spans_single_message_and_unreadable_rows():
    spans = _spans([
        _m("a", "2026-11-08T10:00:00Z"),            # alone: counted, no length
        _m(None, "2026-11-08T11:00:00Z"),           # no session
        _m("b", None), _m("b", "not a timestamp"),  # no time
    ])
    assert spans == [("2026-11-08T10:00:00+00:00", 0.0)]
    assert daily._session_day_spans([], daily._window(0, NOW)) == []


def test_tutor_spans_read_messages_since_the_window_start():
    window = daily._window(300, NOW)
    with patch.object(daily, "_tutor_messages", return_value=[
        _m("a", "2026-11-08T15:00:00Z"), _m("a", "2026-11-08T15:12:00Z"),
    ]) as read:
        spans = daily._tutor_spans("u1", window)
    read.assert_called_once_with("u1", window.since)
    assert spans == [("2026-11-08T15:00:00+00:00", 12.0)]


# ── buckets and the wire shape ───────────────────────────────────────────────

def test_tally_adds_minutes_and_counts_to_the_local_day():
    w = daily._window(300, NOW)  # UTC-5
    buckets = daily._empty_buckets(w)
    daily._tally(buckets, w, [
        ("2026-11-08T04:00:00Z", 10.0),   # Nov 7, local
        ("2026-11-08T06:00:00Z", 2.5),    # Nov 8, local
        ("2026-11-08T07:00:00Z", 2.5),
        ("2026-10-01T00:00:00Z", 99.0),   # before the window
        (None, 99.0),
    ], "quiz", "quizzes")
    assert list(buckets) == w.days
    assert buckets["2026-11-07"]["quiz"] == 10.0 and buckets["2026-11-07"]["quizzes"] == 1
    assert buckets["2026-11-08"]["quiz"] == 5.0 and buckets["2026-11-08"]["quizzes"] == 2
    assert sum(b["quizzes"] for b in buckets.values()) == 3
    # Other sources are untouched.
    assert all(b["tutor"] == 0.0 and b["cards"] == 0 for b in buckets.values())


@pytest.mark.parametrize("minutes,whole", [
    (0.0, 0), (-1.0, 0),
    # Anything with time in it shows at least a minute.
    (0.01, 1), (0.49, 1), (0.5, 1), (1.4, 1),
    # Half up, where round() would go to the even neighbour.
    (1.5, 2), (2.5, 3), (3.5, 4), (29.5, 30), (60.0, 60),
])
def test_whole_minutes_rounds_half_up_and_never_hides_activity(minutes, whole):
    assert daily._whole_minutes(minutes) == whole


def test_day_payload_total_is_the_sum_of_the_rounded_parts():
    payload = daily._day_payload({
        "date": "2026-11-08", "quiz": 10.4, "flashcards": 0.0, "tutor": 10.4,
        "quizzes": 1, "cards": 0, "sessions": 1,
    })
    # Not 21 (the rounded 20.8): the rows beside the total read 10 + 0 + 10.
    assert payload == {
        "date": "2026-11-08", "minutes": 20, "quiz": 10, "flashcards": 0, "tutor": 10,
        "quizzes": 1, "cards": 0, "sessions": 1,
    }
    assert list(payload) == ["date", "minutes", "quiz", "flashcards", "tutor",
                             "quizzes", "cards", "sessions"]
    assert all(type(v) is int for k, v in payload.items() if k != "date")


def test_day_payload_shows_every_small_activity():
    payload = daily._day_payload({
        "date": "2026-11-08", "quiz": 0.2, "flashcards": 0.5, "tutor": 0.1,
        "quizzes": 1, "cards": 1, "sessions": 1,
    })
    assert (payload["quiz"], payload["flashcards"], payload["tutor"]) == (1, 1, 1)
    assert payload["minutes"] == 3


# ── the goal ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("stored,goal_minutes", [
    (45, 45), (5, 5), (600, 600),
    # A missing row, and values the column's CHECK (5..600) cannot hold.
    (None, 30), (0, 30), (4, 30), (601, 30), (-10, 30),
    # Not an integer at all: the default, never a 500 or a goal of True.
    ("45", 30), (45.5, 30), (True, 30),
])
def test_goal_or_default(stored, goal_minutes):
    assert goal._goal_or_default(stored) == goal_minutes


def test_goal_bounds_match_the_migration():
    """20261108225631: INT NOT NULL DEFAULT 30, CHECK BETWEEN 5 AND 600."""
    from pathlib import Path

    sql = (Path(__file__).resolve().parents[1] / "db" / "migrations"
           / "20261108225631_user_settings_daily_goal_minutes.sql").read_text()
    assert f"daily_goal_minutes INT NOT NULL DEFAULT {goal.DEFAULT_GOAL_MIN}" in sql
    assert f"daily_goal_minutes BETWEEN {goal.MIN_GOAL_MIN} AND {goal.MAX_GOAL_MIN}" in sql


def test_read_daily_goal_reads_one_column_of_the_students_row():
    handle = MagicMock()
    handle.select.return_value = [{"daily_goal_minutes": 45}]
    with patch.object(goal, "table", return_value=handle) as table:
        assert goal.read_daily_goal("u1") == 45
    table.assert_called_once_with("user_settings")
    handle.select.assert_called_once_with(
        "daily_goal_minutes", filters={"user_id": "eq.u1"}, limit=1
    )


@pytest.mark.parametrize("rows", [[], None])
def test_read_daily_goal_defaults_without_a_row(rows):
    handle = MagicMock()
    handle.select.return_value = rows
    with patch.object(goal, "table", return_value=handle):
        assert goal.read_daily_goal("u1") == goal.DEFAULT_GOAL_MIN


@pytest.mark.parametrize("failure", [
    httpx.ConnectError("postgrest down"),
    httpx.ReadTimeout("slow"),
])
def test_read_daily_goal_degrades_on_a_postgrest_failure(failure, caplog):
    handle = MagicMock()
    handle.select.side_effect = failure
    with patch.object(goal, "table", return_value=handle), caplog.at_level("WARNING"):
        assert goal.read_daily_goal("u1") == goal.DEFAULT_GOAL_MIN
    assert "daily goal read failed" in caplog.text


@pytest.mark.parametrize("failure", [TypeError("bug"), RuntimeError("scope unavailable")])
def test_read_daily_goal_does_not_swallow_anything_else(failure):
    handle = MagicMock()
    handle.select.side_effect = failure
    with patch.object(goal, "table", return_value=handle), pytest.raises(type(failure)):
        goal.read_daily_goal("u1")


def test_set_daily_goal_upserts_only_the_goal_on_the_user_key():
    handle = MagicMock()
    with patch.object(goal, "table", return_value=handle) as table:
        assert goal.set_daily_goal("u1", 45) == {"goal_minutes": 45}
    table.assert_called_once_with("user_settings")
    handle.upsert.assert_called_once_with(
        {"user_id": "u1", "daily_goal_minutes": 45},
        on_conflict="user_id",
        columns="user_id,daily_goal_minutes",
    )


def test_set_daily_goal_lets_a_failed_write_fail():
    """A goal that was not stored must not be answered as stored."""
    handle = MagicMock()
    handle.upsert.side_effect = httpx.ConnectError("postgrest down")
    with patch.object(goal, "table", return_value=handle), pytest.raises(httpx.ConnectError):
        goal.set_daily_goal("u1", 45)


def test_package_exports_its_public_api():
    import services.study as study

    assert sorted(study.__all__) == [
        "DEFAULT_GOAL_MIN", "MAX_GOAL_MIN", "MIN_GOAL_MIN",
        "get_daily", "read_daily_goal", "set_daily_goal",
    ]
    assert study.get_daily is daily.get_daily
    assert study.set_daily_goal is goal.set_daily_goal
    assert Window.__module__ == "services.study.daily"
