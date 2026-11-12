"""Study hub: estimated daily study minutes + the daily goal.

``routes/study.py`` is the HTTP surface; the logic is ``services/study/``
(#118). The cases here drive the whole read (``get_daily``) and the two
routes; ``test_study_helpers.py`` covers the pieces ``get_daily`` is built
from.
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes.study import router
from services.study import get_daily
from tests.split_patches import patch_in

# Mounted alone (as main.py mounts it, at /api/study) so the test doesn't
# depend on every other router's import chain.
_app = FastAPI()
_app.include_router(router, prefix="/api/study")
client = TestClient(_app)

NOW = datetime(2026, 11, 8, 18, 0, tzinfo=timezone.utc)

#: Every module that looks up ``table`` since the split (the route itself no
#: longer touches the database). A patch on ``routes.study.table`` would
#: intercept nothing.
STUDY_TABLE_MODULES = ("services.study.daily", "services.study.goal")

#: The three sources ``get_daily`` pages through (``db.connection.page_all``
#: reads ``select_with_count``). Tutor time comes from ``messages`` alone.
PAGED = ("quiz_attempts", "flashcards", "messages")


def _msgs(session_id, *times):
    return [{"session_id": session_id, "created_at": t} for t in times]


def _handles(quiz=(), cards=(), messages=(), settings=({"daily_goal_minutes": 40},)):
    h = {name: MagicMock() for name in
         ("quiz_attempts", "flashcards", "sessions", "messages", "user_settings")}
    for name, rows in zip(PAGED, (quiz, cards, messages)):
        h[name].select_with_count.return_value = (list(rows), len(rows))
    h["user_settings"].select.return_value = list(settings)
    return h


def _patch_table(h):
    return patch_in(STUDY_TABLE_MODULES, "table", side_effect=lambda name: h[name])


def _run(h, tz=0):
    with _patch_table(h):
        return get_daily("u1", tz, now=NOW)


def _postgrest_error(status=400):
    request = httpx.Request("GET", "http://postgrest.test/rest/v1/x")
    return httpx.HTTPStatusError(
        f"{status}", request=request, response=httpx.Response(status, request=request)
    )


def test_buckets_seven_local_days_oldest_first():
    body = _run(_handles())
    assert [d["date"] for d in body["days"]][0] == "2026-11-02"
    assert body["days"][-1]["date"] == "2026-11-08" == body["today"]
    assert all(d["minutes"] == 0 for d in body["days"])
    assert body["goal_minutes"] == 40


def test_sums_quiz_cards_and_tutor_with_caps():
    h = _handles(
        quiz=[
            {"created_at": "2026-11-08T10:00:00Z", "completed_at": "2026-11-08T10:12:00Z"},
            # Left open for 3 hours: capped at 30 minutes.
            {"created_at": "2026-11-08T11:00:00Z", "completed_at": "2026-11-08T14:00:00Z"},
        ],
        cards=[{"last_reviewed_at": "2026-11-08T09:00:00Z"} for _ in range(10)],
        messages=_msgs("s1", "2026-11-07T09:00:00Z", "2026-11-07T09:20:00Z"),
    )
    body = _run(h)
    today, yesterday = body["days"][-1], body["days"][-2]
    assert today["quiz"] == 42 and today["quizzes"] == 2
    assert today["flashcards"] == 5 and today["cards"] == 10
    assert today["minutes"] == 47
    assert yesterday["tutor"] == 20 and yesterday["sessions"] == 1


def test_session_runs_from_its_first_to_its_last_message_of_the_day():
    h = _handles(messages=_msgs(
        "s1", "2026-11-07T09:25:00Z", "2026-11-07T09:05:00Z", "2026-11-07T09:00:00Z",
    ))
    yesterday = _run(h)["days"][-2]
    assert yesterday["tutor"] == 25 and yesterday["sessions"] == 1
    assert yesterday["minutes"] == 25
    # One paged read of the student's messages, through the session that owns
    # them (messages has no user_id), and never the encrypted `content`.
    h["messages"].select_with_count.assert_called_once()
    args, kwargs = h["messages"].select_with_count.call_args
    assert args[0] == "session_id,created_at,sessions!inner(user_id)"
    assert kwargs["filters"] == {
        "sessions.user_id": "eq.u1", "created_at": "gte.2026-11-02T00:00:00+00:00",
    }
    assert kwargs["order"] == "created_at.desc,id.desc"
    assert kwargs["limit"]


def test_session_day_is_capped_at_sixty_minutes():
    # Came back to the same chat three hours later.
    h = _handles(messages=_msgs("s1", "2026-11-07T09:00:00Z", "2026-11-07T12:00:00Z"))
    yesterday = _run(h)["days"][-2]
    assert yesterday["tutor"] == 60 and yesterday["sessions"] == 1


def test_session_without_messages_counts_nothing():
    # s1 was opened and never used: it has no rows at all. Only s2 counts.
    h = _handles(messages=_msgs("s2", "2026-11-07T11:00:00Z", "2026-11-07T11:10:00Z"))
    yesterday = _run(h)["days"][-2]
    assert yesterday["tutor"] == 10 and yesterday["sessions"] == 1


def test_chat_opened_last_week_counts_on_the_days_it_is_used():
    """The old rule counted a session once, on the day it STARTED: a chat
    opened weeks ago and used every day since added nothing."""
    h = _handles(messages=(
        _msgs("old", "2026-11-06T15:00:00Z", "2026-11-06T15:30:00Z")
        + _msgs("old", "2026-11-08T10:00:00Z", "2026-11-08T10:15:00Z")
    ))
    by_date = {d["date"]: d for d in _run(h)["days"]}
    assert by_date["2026-11-06"]["tutor"] == 30 and by_date["2026-11-06"]["sessions"] == 1
    assert by_date["2026-11-07"]["tutor"] == 0 and by_date["2026-11-07"]["sessions"] == 0
    assert by_date["2026-11-08"]["tutor"] == 15 and by_date["2026-11-08"]["sessions"] == 1
    # The sessions table is not consulted: when a session started (or whether
    # "End session" was ever pressed) is not part of the estimate.
    h["sessions"].select.assert_not_called()
    h["sessions"].select_with_count.assert_not_called()


def test_session_across_local_midnight_is_split_between_the_two_days():
    # UTC-5 (offset 300): local midnight is 05:00 UTC. 23:40 -> 00:25 local.
    h = _handles(messages=_msgs(
        "s1", "2026-11-08T04:40:00Z", "2026-11-08T04:55:00Z",
        "2026-11-08T05:05:00Z", "2026-11-08T05:25:00Z",
    ))
    by_date = {d["date"]: d for d in _run(h, tz=300)["days"]}
    assert by_date["2026-11-07"]["tutor"] == 15 and by_date["2026-11-07"]["sessions"] == 1
    assert by_date["2026-11-08"]["tutor"] == 20 and by_date["2026-11-08"]["sessions"] == 1


def test_two_sessions_on_one_day_are_capped_separately():
    h = _handles(messages=(
        _msgs("a", "2026-11-07T08:00:00Z", "2026-11-07T11:00:00Z")      # capped: 60
        + _msgs("b", "2026-11-07T14:00:00Z", "2026-11-07T14:10:00Z")    # 10
    ))
    yesterday = _run(h)["days"][-2]
    assert yesterday["tutor"] == 70 and yesterday["sessions"] == 2


def test_a_single_message_counts_the_session_with_no_minutes():
    h = _handles(messages=_msgs("s1", "2026-11-07T09:00:00Z"))
    yesterday = _run(h)["days"][-2]
    assert yesterday["sessions"] == 1 and yesterday["tutor"] == 0 and yesterday["minutes"] == 0


def test_local_day_follows_the_client_offset():
    # 02:00 UTC on Nov 8 is still Nov 7 in UTC-5 (offset 300).
    h = _handles(quiz=[{"created_at": "2026-11-08T01:50:00Z", "completed_at": "2026-11-08T02:00:00Z"}])
    body = _run(h, tz=300)
    by_date = {d["date"]: d for d in body["days"]}
    assert by_date["2026-11-07"]["quiz"] == 10
    assert by_date["2026-11-08"]["quiz"] == 0


def test_goal_defaults_when_settings_unreadable():
    h = _handles(settings=())
    # What PostgREST answers for a column the database does not have.
    h["user_settings"].select.side_effect = _postgrest_error(400)
    assert _run(h)["goal_minutes"] == 30


def test_goal_defaults_when_the_student_has_no_settings_row():
    assert _run(_handles(settings=()))["goal_minutes"] == 30


def test_a_bug_in_the_goal_read_is_not_swallowed():
    h = _handles()
    h["user_settings"].select.side_effect = TypeError("select() got an unexpected keyword")
    with pytest.raises(TypeError):
        _run(h)


@pytest.mark.parametrize("source", PAGED)
def test_a_failing_source_read_fails_the_request(source):
    """The three source reads ARE the panel: a week of zeros for a student
    whose quiz (or card, or tutor) read failed would be a lie, so nothing
    degrades there. Only the goal does."""
    h = _handles()
    h[source].select_with_count.side_effect = _postgrest_error(503)
    with pytest.raises(httpx.HTTPStatusError):
        _run(h)


# ── the reads themselves ─────────────────────────────────────────────────────

def test_each_source_is_read_by_user_since_the_first_local_midnight():
    h = _handles()
    _run(h, tz=300)  # UTC-5: Nov 2 00:00 local is Nov 2 05:00 UTC
    since = "gte.2026-11-02T05:00:00+00:00"
    expected = {
        "quiz_attempts": ("created_at,completed_at", "user_id", "completed_at"),
        "flashcards": ("last_reviewed_at", "user_id", "last_reviewed_at"),
        "messages": ("session_id,created_at,sessions!inner(user_id)",
                     "sessions.user_id", "created_at"),
    }
    for name, (columns, owner, stamp) in expected.items():
        h[name].select_with_count.assert_called_once()
        args, kwargs = h[name].select_with_count.call_args
        assert args[0] == columns
        assert kwargs["filters"] == {owner: "eq.u1", stamp: since}
        # A total order (unique tiebreaker), or offset paging can skip rows.
        # Newest first, so a read that hits its bound gives up the oldest days.
        assert kwargs["order"] == f"{stamp}.desc,id.desc"


def test_reads_page_past_the_postgrest_cap():
    """PostgREST answers at most 1000 rows and calls it a success. A student
    who reviewed 1500 cards in a week was shown 1000 of them (the old single
    ``limit=2000`` read)."""
    cards = [{"last_reviewed_at": "2026-11-08T09:00:00Z"} for _ in range(1500)]
    h = _handles()
    h["flashcards"].select_with_count.side_effect = (
        lambda *a, limit, offset, **kw: (cards[offset:offset + limit], len(cards))
    )
    today = _run(h)["days"][-1]
    assert today["cards"] == 1500 and today["flashcards"] == 750
    assert [c.kwargs["offset"] for c in h["flashcards"].select_with_count.call_args_list] == [0, 1000]


def test_a_read_stops_at_its_bound_and_says_so(caplog):
    cards = [{"last_reviewed_at": "2026-11-08T09:00:00Z"}] * 2500
    h = _handles()
    h["flashcards"].select_with_count.side_effect = (
        lambda *a, limit, offset, **kw: (cards[offset:offset + limit], len(cards))
    )
    with patch("services.study.daily._MAX_SOURCE_ROWS", 1200), caplog.at_level("WARNING"):
        today = _run(h)["days"][-1]
    assert today["cards"] == 1200
    # It stops paging once the bound is passed (2 pages of 3), and logs it.
    assert h["flashcards"].select_with_count.call_count == 2
    assert "flashcards read stopped at 1200 rows" in caplog.text


def test_one_card_is_a_minute_and_halves_round_up():
    """round() is half-to-even: one card (0.5 min) read as "0 min" and five
    cards (2.5 min) as 2, the same as three."""
    def cards(n):
        h = _handles(cards=[{"last_reviewed_at": "2026-11-08T09:00:00Z"}] * n)
        return _run(h)["days"][-1]

    assert [cards(n)["flashcards"] for n in (0, 1, 2, 3, 4, 5)] == [0, 1, 1, 2, 2, 3]
    assert cards(1)["minutes"] == 1 and cards(5)["minutes"] == 3


def test_a_days_minutes_are_always_the_sum_of_its_parts():
    """Rounding the total on its own let the ring say 21 beside rows that
    added up to 20. Every activity with time in it shows at least 1."""
    h = _handles(
        # 10.4 min, and a 12-second quiz.
        quiz=[{"created_at": "2026-11-08T10:00:00Z", "completed_at": "2026-11-08T10:10:24Z"},
              {"created_at": "2026-11-07T10:00:00Z", "completed_at": "2026-11-07T10:00:12Z"}],
        cards=[{"last_reviewed_at": "2026-11-07T09:00:00Z"}],
        messages=(_msgs("s1", "2026-11-08T12:00:00Z", "2026-11-08T12:10:24Z")
                  + _msgs("s2", "2026-11-07T12:00:00Z", "2026-11-07T12:00:06Z")),
    )
    body = _run(h)
    today, yesterday = body["days"][-1], body["days"][-2]
    assert (today["quiz"], today["flashcards"], today["tutor"], today["minutes"]) == (10, 0, 10, 20)
    assert (yesterday["quiz"], yesterday["flashcards"], yesterday["tutor"]) == (1, 1, 1)
    assert yesterday["minutes"] == 3
    assert all(d["minutes"] == d["quiz"] + d["flashcards"] + d["tutor"] for d in body["days"])


def test_rows_outside_the_window_or_unreadable_are_dropped():
    h = _handles(
        quiz=[
            # Before the window (a clock-skewed row the filter let through).
            {"created_at": "2026-11-01T10:00:00Z", "completed_at": "2026-11-01T10:10:00Z"},
            {"created_at": "2026-11-08T10:00:00Z", "completed_at": "not a timestamp"},
            {"created_at": "2026-11-08T10:00:00Z", "completed_at": None},
        ],
    )
    body = _run(h)
    assert all(d["quizzes"] == 0 and d["minutes"] == 0 for d in body["days"])


def test_response_shape_is_the_wire_contract():
    """Key names AND order, as frontend/src/lib/studyApi.ts reads them."""
    h = _handles(
        quiz=[{"created_at": "2026-11-08T10:00:00Z", "completed_at": "2026-11-08T10:12:00Z"}],
        cards=[{"last_reviewed_at": "2026-11-08T09:00:00Z"}] * 4,
        messages=_msgs("s1", "2026-11-08T09:00:00Z", "2026-11-08T09:20:00Z"),
    )
    body = _run(h)
    assert list(body) == ["goal_minutes", "today", "days"]
    assert len(body["days"]) == 7
    assert list(body["days"][-1].items()) == [
        ("date", "2026-11-08"), ("minutes", 34), ("quiz", 12), ("flashcards", 2),
        ("tutor", 20), ("quizzes", 1), ("cards", 4), ("sessions", 1),
    ]
    assert list(body["days"][0].items()) == [
        ("date", "2026-11-02"), ("minutes", 0), ("quiz", 0), ("flashcards", 0),
        ("tutor", 0), ("quizzes", 0), ("cards", 0), ("sessions", 0),
    ]


# ── the routes ───────────────────────────────────────────────────────────────

def test_daily_route_and_goal_patch():
    h = _handles()
    with (
        _patch_table(h),
        patch("routes.study.require_self", return_value=None),
    ):
        r = client.get("/api/study/u1/daily?tz_offset_min=0")
        assert r.status_code == 200
        assert len(r.json()["days"]) == 7

        bad = client.patch("/api/study/u1/daily-goal", json={"minutes": 2})
        assert bad.status_code == 422

        ok = client.patch("/api/study/u1/daily-goal", json={"minutes": 45})
        assert ok.status_code == 200 and ok.json() == {"goal_minutes": 45}
    args, kwargs = h["user_settings"].upsert.call_args
    assert args[0]["daily_goal_minutes"] == 45
    assert kwargs["on_conflict"] == "user_id"


def test_goal_patch_writes_only_the_goal():
    """An upsert merges the columns it is sent: sending just the key and the
    goal leaves every other setting alone (and, for a student with no row
    yet, at its column default)."""
    h = _handles()
    with _patch_table(h), patch("routes.study.require_self", return_value=None):
        client.patch("/api/study/u1/daily-goal", json={"minutes": 45})
    h["user_settings"].upsert.assert_called_once()
    assert h["user_settings"].upsert.call_args.args[0] == {
        "user_id": "u1", "daily_goal_minutes": 45,
    }


@pytest.mark.parametrize("minutes,status", [
    (4, 422), (5, 200), (600, 200), (601, 422), (0, 422), (-30, 422), ("soon", 422),
])
def test_goal_patch_accepts_exactly_the_columns_range(minutes, status):
    """5..600, the CHECK on user_settings.daily_goal_minutes: anything else is
    refused here, before it can come back as a raw constraint violation."""
    h = _handles()
    with _patch_table(h), patch("routes.study.require_self", return_value=None):
        r = client.patch("/api/study/u1/daily-goal", json={"minutes": minutes})
    assert r.status_code == status
    assert h["user_settings"].upsert.called is (status == 200)


def test_goal_patch_requires_the_account_owner():
    from fastapi import HTTPException

    h = _handles()
    refuse = HTTPException(status_code=403, detail="Forbidden: not your account")
    with _patch_table(h), patch("routes.study.require_self", side_effect=refuse):
        assert client.patch("/api/study/u1/daily-goal", json={"minutes": 45}).status_code == 403
        assert client.get("/api/study/u1/daily").status_code == 403
    h["user_settings"].upsert.assert_not_called()
    h["quiz_attempts"].select_with_count.assert_not_called()


@pytest.mark.parametrize("sent,used", [
    ("300", 300), ("-840", -840), ("720", 720),
    # Junk past the ends of the real world is clamped, not refused.
    ("-100000", -840), ("100000", 720),
])
def test_daily_route_hands_the_service_a_clamped_offset(sent, used):
    with (
        patch("services.study.daily._window", wraps=_real_window()) as window,
        _patch_table(_handles()),
        patch("routes.study.require_self", return_value=None),
    ):
        r = client.get(f"/api/study/u1/daily?tz_offset_min={sent}")
    assert r.status_code == 200
    assert window.call_args.args[0] == used


def test_daily_route_refuses_an_offset_that_is_not_a_number():
    with patch("routes.study.require_self", return_value=None):
        assert client.get("/api/study/u1/daily?tz_offset_min=est").status_code == 422


def test_the_route_module_holds_no_logic():
    """The route is the HTTP surface only (#118): it has no database handle
    of its own, so a patch on ``routes.study.table`` would intercept nothing."""
    import routes.study as route

    assert not hasattr(route, "table")
    assert route.get_daily is not get_daily  # the wrapper, not the service


def _real_window():
    from services.study import daily

    return daily._window
