"""PKG-13: GET /api/learn/loop/sessions — the open loop sessions a student can
resume (spec §9, §11.3, §13 A26). Read-only; 404 when the gate is false; never
rate-limited (A20: a failure here must not push a student off the loop UI).

The phase each row reports is the one `GET /status` reports for the same
document: PKG-08's `_loop_phase` (probe | plan | teach | close), refined in
teach by PKG-07's `_phase_for` (teach | check | feedback) — both run for real
here, on real loop-state documents."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import routes.learn_loop as ll
from main import app
from services import ai_budget

client = TestClient(app)

LOOP = "/api/learn/loop"
UID = "u1"
COURSE = "c1"
URL = f"{LOOP}/sessions?user_id={UID}&course_id={COURSE}"


class _Sessions:
    """Records every table read and returns canned `sessions` rows."""

    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def __call__(self, name):
        outer = self

        class _T:
            def select(self, cols, filters=None, order=None, limit=None):
                outer.calls.append(
                    {
                        "table": name,
                        "cols": cols,
                        "filters": dict(filters or {}),
                        "order": order,
                        "limit": limit,
                    }
                )
                return list(outer.rows) if name == "sessions" else []

            def __getattr__(self, attr):  # any write is a test failure
                raise AssertionError(f"GET /sessions must not call {name}.{attr}")

        return _T()


_PROBING = {"phase": "probe", "probe": {"skills": ["n1"], "history": []}}


def _row(sid, *, state=_PROBING, close_phase=None, started="2026-09-20T10:00:00Z"):
    return {
        "id": sid,
        "topic": f"topic {sid}",
        "started_at": started,
        "loop_state": state,
        "close_phase": close_phase,
    }


def _step(**fields) -> dict:
    step = {
        "rung": 0,
        "attempts": 0,
        "first_shown_at": 1_790_000_000.0,
        "attempted_at": [],
        "check_item_id": "item-1",
        "node_id": "n1",
    }
    step.update(fields)
    return step


@pytest.fixture
def gate_on():
    with (
        patch("routes.learn_loop.learning_loop_for_request", return_value=True) as g,
        patch(
            "routes.learn_loop.user_offering_ids_for_course",
            return_value=["off-1", "off-2"],
        ) as offerings,
    ):
        yield g, offerings


def _get(fake):
    with patch("routes.learn_loop.table", fake):
        return client.get(URL)


def test_404_when_gate_false_and_no_read():
    fake = _Sessions([_row("s1")])
    with (
        patch("routes.learn_loop.learning_loop_for_request", return_value=False),
        patch("routes.learn_loop.user_offering_ids_for_course") as offerings,
    ):
        r = _get(fake)
    assert r.status_code == 404 and r.json()["detail"] == "learning loop not enabled"
    assert fake.calls == [] and offerings.call_count == 0


def test_another_students_sessions_are_refused_before_any_read():
    def _refuse(user_id, request):
        raise HTTPException(status_code=403, detail="Forbidden")

    fake = _Sessions([_row("s1")])
    with (
        patch("routes.learn_loop.require_self", _refuse),
        patch("routes.learn_loop.learning_loop_for_request") as gate,
        patch("routes.learn_loop.user_offering_ids_for_course") as offerings,
    ):
        r = _get(fake)
    assert r.status_code == 403
    assert fake.calls == [] and gate.call_count == 0 and offerings.call_count == 0


def test_lists_open_loop_sessions_newest_first_in_one_read(gate_on):
    fake = _Sessions([_row("s2", started="2026-09-21T10:00:00Z"), _row("s1")])
    r = _get(fake)
    assert r.status_code == 200
    sessions = r.json()["sessions"]
    assert [s["session_id"] for s in sessions] == ["s2", "s1"]
    assert sessions[0] == {
        "session_id": "s2",
        "topic": "topic s2",
        "started_at": "2026-09-21T10:00:00Z",
        "phase": "probe",
    }
    (call,) = fake.calls  # ONE read, of the sessions table
    assert call["table"] == "sessions"
    assert call["filters"] == {
        "user_id": f"eq.{UID}",
        "offering_id": "in.(off-1,off-2)",
        "close_json": "is.null",
        "ended_at": "is.null",
        "mode": "neq.review",
    }
    assert call["order"] == "started_at.desc" and call["limit"] == ll.LOOP_OPEN_SESSIONS_LIMIT
    # never reads the ciphertext (is.null only, invariant 9) nor model_pref (invariant 22)
    assert "close_json" not in call["cols"] and "model_pref" not in call["cols"]
    gate_on[1].assert_called_once_with(UID, COURSE)


def test_drops_sessions_with_no_loop_state_or_a_closed_one(gate_on):
    rows = [
        _row("s1", state={}),
        _row("s2", state=None),
        _row("s3"),
        _row("s4", state={"phase": "close"}),  # its close is being stored
    ]
    r = _get(_Sessions(rows))
    assert [s["session_id"] for s in r.json()["sessions"]] == ["s3"]


@pytest.mark.parametrize(
    "state,phase",
    [
        ({"phase": "probe", "probe": {}}, "probe"),
        ({"phase": "plan", "plan": {"proposed": ["n1"]}}, "plan"),
        # a document /plan/approve wrote before PKG-08's `phase` key existed
        ({"plan": {"approved": ["n1"], "cursor": 0}}, "teach"),
        ({"phase": "teach", "concept": "n1"}, "teach"),
        ({"phase": "teach", "current": "qh", "steps": {"qh": _step()}}, "check"),
        (
            {"phase": "teach", "current": "qh", "steps": {"qh": _step(graded_at=1.0)}},
            "feedback",
        ),
        (
            {
                "phase": "teach",
                "current": "qh",
                "steps": {"qh": _step(graded_at=1.0, feedback_given=True)},
            },
            "teach",
        ),
    ],
)
def test_phase_is_the_status_routes_phase_for_the_document(gate_on, state, phase):
    r = _get(_Sessions([_row("s1", state=state)]))
    assert r.json()["sessions"] == [
        {
            "session_id": "s1",
            "topic": "topic s1",
            "started_at": "2026-09-20T10:00:00Z",
            "phase": phase,
        }
    ]


def test_a_stored_close_phase_wins(gate_on):
    r = _get(_Sessions([_row("s1", close_phase="feedback")]))
    assert r.json()["sessions"][0]["phase"] == "feedback"


def test_no_offering_for_the_course_reads_nothing(gate_on):
    gate_on[1].return_value = []
    fake = _Sessions([_row("s1")])
    r = _get(fake)
    assert r.status_code == 200 and r.json() == {"sessions": []} and fake.calls == []


def test_course_id_is_required():
    with patch("routes.learn_loop.learning_loop_for_request", return_value=True):
        assert client.get(f"{LOOP}/sessions?user_id={UID}").status_code == 422


def test_never_rate_limited(gate_on):
    """A20: the rate limit applies to model-calling routes only — never GET /sessions."""
    from routes import learn_loop

    def _limited():
        raise HTTPException(status_code=429, detail="ai budget reached")

    app.dependency_overrides[ai_budget.enforce_rate_limit] = _limited
    try:
        with (
            patch("services.ai_budget.rate_limited", return_value=True),
            patch("services.ai_budget.enforce_rate_limit_for", side_effect=_limited),
        ):
            assert _get(_Sessions([_row("s1")])).status_code == 200
    finally:
        app.dependency_overrides.pop(ai_budget.enforce_rate_limit, None)
    (route,) = [r for r in learn_loop.router.routes if r.path == "/sessions"]
    assert ai_budget.enforce_rate_limit not in {d.call for d in route.dependant.dependencies}
    assert route.methods == {"GET"}
