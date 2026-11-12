"""Study hub: estimated daily study minutes + the daily goal (routes/study.py)."""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes.study import daily_minutes, router

# Mounted alone (as main.py mounts it, at /api/study) so the test doesn't
# depend on every other router's import chain.
_app = FastAPI()
_app.include_router(router, prefix="/api/study")
client = TestClient(_app)

NOW = datetime(2026, 11, 8, 18, 0, tzinfo=timezone.utc)


def _handles(quiz=(), cards=(), sessions=(), messages=(), settings=({"daily_goal_minutes": 40},)):
    h = {name: MagicMock() for name in
         ("quiz_attempts", "flashcards", "sessions", "messages", "user_settings")}
    h["quiz_attempts"].select.return_value = list(quiz)
    h["flashcards"].select.return_value = list(cards)
    h["sessions"].select.return_value = list(sessions)
    # Newest first, as the route asks for them (order=created_at.desc).
    h["messages"].select.return_value = list(messages)
    h["user_settings"].select.return_value = list(settings)
    return h


def _run(h, tz=0):
    with patch("routes.study.table", side_effect=lambda name: h[name]):
        return daily_minutes("u1", tz, now=NOW)


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
        sessions=[
            {"started_at": "2026-11-07T09:00:00Z", "ended_at": "2026-11-07T09:20:00Z"},
            # Never ended and no messages: not counted.
            {"id": "s2", "started_at": "2026-11-07T10:00:00Z", "ended_at": None},
        ],
    )
    body = _run(h)
    today, yesterday = body["days"][-1], body["days"][-2]
    assert today["quiz"] == 42 and today["quizzes"] == 2
    assert today["flashcards"] == 5 and today["cards"] == 10
    assert today["minutes"] == 47
    assert yesterday["tutor"] == 20 and yesterday["sessions"] == 1


def test_unended_session_runs_to_its_last_message():
    h = _handles(
        sessions=[{"id": "s1", "started_at": "2026-11-07T09:00:00Z", "ended_at": None}],
        messages=[
            {"session_id": "s1", "created_at": "2026-11-07T09:25:00Z"},
            {"session_id": "s1", "created_at": "2026-11-07T09:05:00Z"},
        ],
    )
    yesterday = _run(h)["days"][-2]
    assert yesterday["tutor"] == 25 and yesterday["sessions"] == 1
    assert yesterday["minutes"] == 25
    # One batched read, newest first, and never the encrypted `content`.
    h["messages"].select.assert_called_once()
    args, kwargs = h["messages"].select.call_args
    assert args[0] == "session_id,created_at"
    assert kwargs["filters"] == {"session_id": 'in.("s1")'}
    assert kwargs["order"] == "created_at.desc"
    assert kwargs["limit"]


def test_unended_session_is_capped_at_sixty_minutes():
    h = _handles(
        sessions=[{"id": "s1", "started_at": "2026-11-07T09:00:00Z", "ended_at": None}],
        # Came back to the same chat three hours later.
        messages=[{"session_id": "s1", "created_at": "2026-11-07T12:00:00Z"}],
    )
    yesterday = _run(h)["days"][-2]
    assert yesterday["tutor"] == 60 and yesterday["sessions"] == 1


def test_unended_session_without_messages_counts_nothing():
    h = _handles(
        sessions=[
            {"id": "s1", "started_at": "2026-11-07T09:00:00Z", "ended_at": None},
            {"id": "s2", "started_at": "2026-11-07T11:00:00Z", "ended_at": None},
        ],
        # Only s2 has messages.
        messages=[{"session_id": "s2", "created_at": "2026-11-07T11:10:00Z"}],
    )
    yesterday = _run(h)["days"][-2]
    assert yesterday["tutor"] == 10 and yesterday["sessions"] == 1
    assert h["messages"].select.call_args.kwargs["filters"] == {"session_id": 'in.("s1","s2")'}


def test_ended_session_is_unchanged_and_reads_no_messages():
    h = _handles(
        sessions=[{"id": "s1", "started_at": "2026-11-07T09:00:00Z",
                   "ended_at": "2026-11-07T09:20:00Z"}],
        # Would give 45 minutes if it were (wrongly) consulted.
        messages=[{"session_id": "s1", "created_at": "2026-11-07T09:45:00Z"}],
    )
    yesterday = _run(h)["days"][-2]
    assert yesterday["tutor"] == 20 and yesterday["sessions"] == 1
    h["messages"].select.assert_not_called()


def test_failing_messages_read_degrades_to_zero():
    h = _handles(
        quiz=[{"created_at": "2026-11-07T10:00:00Z", "completed_at": "2026-11-07T10:12:00Z"}],
        sessions=[
            {"id": "s1", "started_at": "2026-11-07T09:00:00Z", "ended_at": None},
            {"id": "s2", "started_at": "2026-11-07T13:00:00Z", "ended_at": "2026-11-07T13:20:00Z"},
        ],
    )
    h["messages"].select.side_effect = RuntimeError("postgrest down")
    yesterday = _run(h)["days"][-2]
    # The un-ended session is lost; the ended one and the quiz still count.
    assert yesterday["tutor"] == 20 and yesterday["sessions"] == 1
    assert yesterday["quiz"] == 12 and yesterday["minutes"] == 32


def test_unended_sessions_are_looked_up_in_chunks():
    ids = [f"s{i}" for i in range(150)]
    h = _handles(sessions=[
        {"id": i, "started_at": "2026-11-07T09:00:00Z", "ended_at": None} for i in ids
    ])
    h["messages"].select.side_effect = lambda *a, **kw: [
        {"session_id": i, "created_at": "2026-11-07T09:01:00Z"}
        for i in ids if f'"{i}"' in kw["filters"]["session_id"]
    ]
    yesterday = _run(h)["days"][-2]
    assert h["messages"].select.call_count == 2
    assert yesterday["sessions"] == 150 and yesterday["tutor"] == 150


def test_full_messages_page_asks_again_for_sessions_it_did_not_reach():
    h = _handles(sessions=[
        {"id": "s1", "started_at": "2026-11-07T09:00:00Z", "ended_at": None},
        {"id": "s2", "started_at": "2026-11-07T08:00:00Z", "ended_at": None},
    ])
    # s1 alone fills the first (2-row) page; s2's last message is older.
    h["messages"].select.side_effect = [
        [{"session_id": "s1", "created_at": "2026-11-07T09:30:00Z"},
         {"session_id": "s1", "created_at": "2026-11-07T09:20:00Z"}],
        [{"session_id": "s2", "created_at": "2026-11-07T08:10:00Z"}],
    ]
    with patch("routes.study._MESSAGE_PAGE", 2):
        yesterday = _run(h)["days"][-2]
    assert yesterday["tutor"] == 40 and yesterday["sessions"] == 2
    assert h["messages"].select.call_args.kwargs["filters"] == {"session_id": 'in.("s2")'}


def test_local_day_follows_the_client_offset():
    # 02:00 UTC on Nov 8 is still Nov 7 in UTC-5 (offset 300).
    h = _handles(quiz=[{"created_at": "2026-11-08T01:50:00Z", "completed_at": "2026-11-08T02:00:00Z"}])
    body = _run(h, tz=300)
    by_date = {d["date"]: d for d in body["days"]}
    assert by_date["2026-11-07"]["quiz"] == 10
    assert by_date["2026-11-08"]["quiz"] == 0


def test_goal_defaults_when_settings_unreadable():
    h = _handles(settings=())
    h["user_settings"].select.side_effect = RuntimeError("column missing")
    assert _run(h)["goal_minutes"] == 30


def test_daily_route_and_goal_patch():
    h = _handles()
    with (
        patch("routes.study.table", side_effect=lambda name: h[name]),
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
