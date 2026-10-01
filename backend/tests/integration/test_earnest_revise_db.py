"""Spec §13 A109, real-SQL half of the earnest-revise gate (spec §10, ≤ 5%).

Two things a MagicMock suite cannot see:
- the /hint mark is a compare-and-set write of a key PKG-06 does not own; it
  must survive the real `sessions.loop_state` JSONB round trip and PKG-06's
  typed parse (StepState.extra), or the feedback turn's zpd.step never sees it;
- the KPI and the nightly script read the bool back out of `events.payload`
  JSONB through PostgREST's `in.(…)` event filter and the window bounds.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from psycopg.types.json import Jsonb

pytestmark = pytest.mark.integration

USER = "rich-user-active"
# a window before any seeded event, so the rich baseline's rows never count
FROM, TO = "2026-01-01T00:00:00+00:00", "2026-02-01T00:00:00+00:00"


def test_the_hint_mark_survives_the_real_loop_state_round_trip(db_conn):
    from db.connection import table
    from routes import learn_loop

    sid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).timestamp()
    entry = {
        "rung": 3,
        "attempts": 0,
        "first_shown_at": now - 600,
        "attempted_at": [now - 500],
        "check_item_id": "it-item-e",
        "node_id": "it-node-e",
    }
    table("sessions").insert(
        {
            "id": sid,
            "user_id": USER,
            "mode": "socratic",
            "topic": "t",
            "loop_state": {"phase": "teach", "current": "qh-e", "steps": {"qh-e": entry}},
        }
    )
    doc = learn_loop._load_loop_state(sid)
    learn_loop._mark_earnest_blocked(sid, "qh-e", learn_loop._step_state(doc, "qh-e"), entry)

    row = db_conn.execute("SELECT loop_state FROM sessions WHERE id = %s", (sid,)).fetchone()
    stored = row["loop_state"]["steps"]["qh-e"]
    assert stored["earnest_blocked"] is True
    assert stored["attempted_at"] == [now - 500], "the CAS write kept the step's own keys"
    # PKG-06's typed parse carries it (StepState.extra), so the feedback turn sees it
    reread = learn_loop._load_loop_state(sid)["steps"]["qh-e"]
    assert reread["earnest_blocked"] is True


def _step_event(db_conn, minute, payload, event_type="zpd.step"):
    db_conn.execute(
        "INSERT INTO events (event_type, category, user_id, request_id, payload, created_at) "
        "VALUES (%s, 'usage', %s, %s, %s, %s)",
        (
            event_type,
            USER,
            f"it-er-{minute}",
            Jsonb(payload),
            f"2026-01-15T00:{minute:02d}:00+00:00",
        ),
    )


def _seed_steps(db_conn):
    for i in range(10):  # 2 blocked of 10 measured check steps
        _step_event(db_conn, i, {"phase": "check", "earnest_blocked": i < 2})
    _step_event(db_conn, 20, {"phase": "check"})  # pre-A109: unmeasured
    _step_event(db_conn, 21, {"phase": "posttest", "earnest_blocked": False})  # never /hint
    _step_event(db_conn, 22, {"phase": "check", "earnest_blocked": True}, "quiz.completed")
    db_conn.execute(  # outside the window
        "INSERT INTO events (event_type, category, user_id, payload, created_at) "
        "VALUES ('zpd.step', 'usage', %s, %s, '2026-02-02T00:00:00+00:00')",
        (USER, Jsonb({"phase": "check", "earnest_blocked": True})),
    )


EXPECTED = {
    "graded_steps": 10,
    "earnest_blocked": 2,
    "unmeasured_steps": 1,
    "rate": pytest.approx(0.2),
    "gate": "fail",
}


def test_the_metrics_script_reads_earnest_revise_from_real_events(db_conn):
    from scripts import derive_zpd_metrics

    _seed_steps(db_conn)
    out, _ = derive_zpd_metrics._report_line(FROM, TO)
    assert out["earnest_revise"] == EXPECTED


def test_the_admin_kpi_reads_earnest_revise_from_real_events(db_conn, client):
    _seed_steps(db_conn)
    with patch("routes.admin_analytics.require_admin", return_value=None):
        r = client.get("/api/admin/analytics/learning-loop", params={"from": FROM, "to": TO})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["earnest_revise"] == EXPECTED
    assert body["gates"]["earnest_revise_ok"] is False


def test_an_empty_window_is_inconclusive_against_real_sql(client):
    with patch("routes.admin_analytics.require_admin", return_value=None):
        body = client.get(
            "/api/admin/analytics/learning-loop", params={"from": FROM, "to": TO}
        ).json()
    assert body["earnest_revise"]["gate"] == "inconclusive"
    assert body["gates"]["earnest_revise_ok"] is None
