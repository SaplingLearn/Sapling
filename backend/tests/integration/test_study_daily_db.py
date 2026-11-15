"""Real-DB half of the Study hub's Daily Goal panel (``services/study/``).

The hermetic suite hands ``get_daily`` MagicMock tables, which accept any
column, filter or ``order`` (the #265 schema/code-drift class) and answer an
upsert without a database behind it. This runs the four reads and the goal
write against real PostgREST: the columns exist, the paged reads' orders
parse, the tutor read's embedded ``sessions!inner`` filter really scopes
``messages`` to one student, and the goal upsert neither needs a
pre-existing ``user_settings`` row nor disturbs the other settings on one.
#397 seam: writes through the app layer, raw reads via psycopg.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from tests.integration.conftest import _client_for

pytestmark = pytest.mark.integration


def _noon_utc_today() -> datetime:
    return datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)


def _seed_a_week(uid: str) -> None:
    """Today (UTC): a quiz, four reviewed cards, a tutor session, and more
    chat in a session opened ten days ago. Yesterday: a second session. Plus a
    quiz from before the window."""
    from db.connection import table
    from services.encryption import encrypt_if_present

    noon = _noon_utc_today()
    yesterday = noon - timedelta(days=1)
    long_ago = noon - timedelta(days=10)

    def at(base: datetime, minutes: int = 0) -> str:
        return (base + timedelta(minutes=minutes)).isoformat()

    table("quiz_attempts").insert([
        {"id": str(uuid.uuid4()), "user_id": uid, "score": 1, "total": 1,
         "created_at": at(noon), "completed_at": at(noon, 12)},
        {"id": str(uuid.uuid4()), "user_id": uid, "score": 1, "total": 1,
         "created_at": at(long_ago), "completed_at": at(long_ago, 12)},
    ])
    table("flashcards").insert([
        {"id": str(uuid.uuid4()), "user_id": uid, "topic": "Limits",
         "front": encrypt_if_present(f"front {i}"), "back": encrypt_if_present(f"back {i}"),
         "last_reviewed_at": at(noon, i)}
        for i in range(4)
    ])
    today_id, yesterday_id, old_id = (str(uuid.uuid4()) for _ in range(3))
    table("sessions").insert([
        {"id": sid, "user_id": uid, "mode": "socratic", "topic": topic, "started_at": started}
        for sid, topic, started in (
            (today_id, "Limits", at(noon)),
            (yesterday_id, "Series", at(yesterday)),
            (old_id, "Integrals", at(long_ago)),
        )
    ])

    def message(session_id: str, when: str, role: str) -> dict:
        return {"session_id": session_id, "role": role,
                "content": encrypt_if_present("..."), "created_at": when}

    table("messages").insert([
        message(today_id, at(noon), "user"),
        message(today_id, at(noon, 20), "assistant"),
        message(yesterday_id, at(yesterday, 2), "user"),
        message(yesterday_id, at(yesterday, 7), "assistant"),
        # Opened ten days ago (that day's chat is outside the window), and
        # used again today.
        message(old_id, at(long_ago), "user"),
        message(old_id, at(long_ago, 30), "assistant"),
        message(old_id, at(noon, 30), "user"),
        message(old_id, at(noon, 40), "assistant"),
    ])


def test_daily_estimates_from_real_rows(seeded_user):
    uid = seeded_user(name="Study Daily")
    bystander = seeded_user(name="Study Bystander")
    _seed_a_week(uid)
    _seed_a_week(bystander)  # another student's week must not leak in

    response = _client_for(uid).get(f"/api/study/{uid}/daily", params={"tz_offset_min": 0})
    assert response.status_code == 200, response.text
    body = response.json()

    today = _noon_utc_today().date()
    assert body["today"] == today.isoformat()
    assert [d["date"] for d in body["days"]] == [
        (today - timedelta(days=6 - i)).isoformat() for i in range(7)
    ]
    # No user_settings row yet: the column default.
    assert body["goal_minutes"] == 30

    # Tutor: 20 minutes in today's session + 10 in the one opened ten days ago.
    assert body["days"][-1] == {
        "date": today.isoformat(), "minutes": 44,
        "quiz": 12, "flashcards": 2, "tutor": 30,
        "quizzes": 1, "cards": 4, "sessions": 2,
    }
    # Yesterday's session: first message to last (2 -> 7 minutes in).
    assert body["days"][-2]["tutor"] == 5 and body["days"][-2]["sessions"] == 1
    assert body["days"][-2]["minutes"] == 5
    # Nothing else in the window; the ten-day-old quiz and chat are outside it.
    assert all(d["minutes"] == 0 for d in body["days"][:-2])
    assert sum(d["quizzes"] for d in body["days"]) == 1


def test_goal_patch_creates_the_settings_row_and_leaves_other_settings_alone(db_conn, seeded_user):
    uid = seeded_user(name="Study Goal")
    client = _client_for(uid)

    def settings_row():
        return db_conn.execute(
            "SELECT daily_goal_minutes, theme, profile_visibility, notification_email "
            "FROM user_settings WHERE user_id = %s", (uid,),
        ).fetchone()

    assert settings_row() is None

    # No row yet: the upsert inserts it, every other column at its default.
    first = client.patch(f"/api/study/{uid}/daily-goal", json={"minutes": 45})
    assert first.status_code == 200, first.text
    assert first.json() == {"goal_minutes": 45}
    assert settings_row() == {
        "daily_goal_minutes": 45, "theme": "light",
        "profile_visibility": "public", "notification_email": True,
    }

    # A setting changed through its own route survives a later goal change.
    changed = client.patch(f"/api/profile/{uid}/settings", json={"theme": "dark"})
    assert changed.status_code == 200, changed.text
    second = client.patch(f"/api/study/{uid}/daily-goal", json={"minutes": 60})
    assert second.status_code == 200, second.text
    row = settings_row()
    assert row["daily_goal_minutes"] == 60 and row["theme"] == "dark"

    # ...and the settings change did not reset the goal.
    assert client.get(f"/api/study/{uid}/daily").json()["goal_minutes"] == 60

    # Outside the column's CHECK: refused before the database sees it.
    assert client.patch(f"/api/study/{uid}/daily-goal", json={"minutes": 601}).status_code == 422
    assert settings_row()["daily_goal_minutes"] == 60


def test_study_routes_are_owner_only(db_conn, seeded_user, other_user_client):
    uid = seeded_user(name="Study Owner")
    assert other_user_client.get(f"/api/study/{uid}/daily").status_code == 403
    refused = other_user_client.patch(f"/api/study/{uid}/daily-goal", json={"minutes": 45})
    assert refused.status_code == 403
    assert db_conn.execute(
        "SELECT 1 FROM user_settings WHERE user_id = %s", (uid,)
    ).fetchone() is None
