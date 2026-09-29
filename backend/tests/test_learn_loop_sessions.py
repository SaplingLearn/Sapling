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
#: The course's offerings: an earlier term the student is ENROLLED in, and the
#: current term every loop session is stamped with (`resolve_offering(course,
#: create=True)`, routes/learn_loop.py) — the #553/#529 keyspace divergence.
OFF_ENROLLED = "off-s26"
OFF_CURRENT = "off-f26"


class _Db:
    """The two tables GET /sessions may read: `course_offerings` (through the REAL
    services.academics.course_offering_ids) and `sessions`, filtered like PostgREST
    by user and offering. Any write is a test failure."""

    def __init__(
        self,
        rows,
        offerings=(OFF_ENROLLED, OFF_CURRENT),
        offerings_fail=False,
        offering_courses=None,
    ):
        self.rows, self.offerings, self.offerings_fail, self.calls = (
            rows,
            list(offerings),
            offerings_fail,
            [],
        )
        #: offering → abstract course (services.academics.offering_course_id)
        self.offering_courses = offering_courses or {o: COURSE for o in self.offerings}

    def __call__(self, name):
        outer = self

        class _T:
            def select_with_count(self, cols, filters=None, limit=None, **kw):
                assert name == "course_offerings", name
                outer.calls.append({"table": name, "filters": dict(filters or {})})
                if outer.offerings_fail:
                    raise RuntimeError("PostgREST down")
                return [{"id": o} for o in outer.offerings], len(outer.offerings)

            def select(self, cols, filters=None, order=None, limit=None):
                f = dict(filters or {})
                outer.calls.append(
                    {"table": name, "cols": cols, "filters": f, "order": order, "limit": limit}
                )
                if name == "course_offerings":  # offering_course_id
                    course = outer.offering_courses.get(f["id"].removeprefix("eq."))
                    return [{"course_id": course}] if course else []
                assert name == "sessions", f"GET /sessions reads sessions, not {name}"
                open_ = {"close_json": "is.null", "ended_at": "is.null", "mode": "neq.review"}
                assert {k: f.get(k) for k in open_} == open_, f  # every read: open rows only
                wanted = (
                    f["offering_id"].removeprefix("in.(").removesuffix(")").split(",")
                    if "offering_id" in f
                    else None
                )
                return [
                    r
                    for r in outer.rows
                    if f["user_id"] == f"eq.{r.get('user_id', UID)}"
                    and (wanted is None or r.get("offering_id", OFF_CURRENT) in wanted)
                    and ("id" not in f or f["id"] == f"eq.{r['id']}")
                    and not (f.get("loop_state") == "neq.{}" and r.get("loop_state") == {})
                ][: limit or None]

            def __getattr__(self, attr):
                raise AssertionError(f"GET /sessions must not call {name}.{attr}")

        return _T()

    def reads(self, name):
        return [c for c in self.calls if c["table"] == name]


_PROBING = {"phase": "probe", "probe": {"skills": ["n1"], "history": []}}


def _row(sid, *, state=_PROBING, started="2026-09-20T10:00:00Z", offering=OFF_CURRENT):
    return {
        "id": sid,
        "topic": f"topic {sid}",
        "started_at": started,
        "loop_state": state,
        "offering_id": offering,
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
    """The loop gate on, and the student ENROLLED only in the earlier term — so a
    route that looked sessions up by enrollment would find none of them."""
    with (
        patch("routes.learn_loop.learning_loop_for_request", return_value=True) as g,
        patch(
            "routes.learn_loop.user_offering_ids_for_course", return_value=[OFF_ENROLLED]
        ) as enrolled,
    ):
        yield g, enrolled


def _get(db):
    import services.academics as academics

    with patch("routes.learn_loop.table", db), patch.object(academics, "table", db):
        return client.get(URL)


def test_404_when_gate_false_and_no_read():
    db = _Db([_row("s1")])
    with patch("routes.learn_loop.learning_loop_for_request", return_value=False):
        r = _get(db)
    assert r.status_code == 404 and r.json()["detail"] == "learning loop not enabled"
    assert db.calls == []


def test_sessions_are_found_on_the_current_term_offering_they_are_stamped_with(gate_on):
    """The keyspace sessions are WRITTEN in (resolve_offering → the current term), not
    the enrollment's: a student enrolled last term finds this term's loop session."""
    db = _Db([_row("s-now", offering=OFF_CURRENT)])
    r = _get(db)
    assert [s["session_id"] for s in r.json()["sessions"]] == ["s-now"]
    ((offerings,),) = [[c for c in db.reads("course_offerings")]]
    assert offerings["filters"] == {"course_id": f"eq.{COURSE}"}


def test_unknown_offerings_are_a_503_never_an_empty_list(gate_on):
    """course_offering_ids answers None when it cannot tell: an empty list would send
    the client to a NEW session and probe (spec §11.3 forbids that on a reload); a
    503 is the client's retry state."""
    db = _Db([_row("s1")], offerings_fail=True)
    r = _get(db)
    assert r.status_code == 503
    assert db.reads("sessions") == []


def test_a_course_with_no_offering_reads_no_sessions(gate_on):
    db = _Db([_row("s1")], offerings=())
    r = _get(db)
    assert r.status_code == 200 and r.json() == {"sessions": []} and db.reads("sessions") == []


def test_another_students_sessions_are_refused_before_any_read():
    def _refuse(user_id, request):
        raise HTTPException(status_code=403, detail="Forbidden")

    db = _Db([_row("s1")])
    with (
        patch("routes.learn_loop.require_self", _refuse),
        patch("routes.learn_loop.learning_loop_for_request") as gate,
    ):
        r = _get(db)
    assert r.status_code == 403
    assert db.calls == [] and gate.call_count == 0


def test_lists_open_loop_sessions_newest_first_in_one_read(gate_on):
    db = _Db([_row("s2", started="2026-09-21T10:00:00Z"), _row("s1", offering=OFF_ENROLLED)])
    r = _get(db)
    assert r.status_code == 200
    sessions = r.json()["sessions"]
    assert [s["session_id"] for s in sessions] == ["s2", "s1"]
    assert sessions[0] == {
        "session_id": "s2",
        "topic": "topic s2",
        "started_at": "2026-09-21T10:00:00Z",
        "phase": "probe",
    }
    (call,) = db.reads("sessions")  # ONE read of the sessions table
    assert call["filters"] == {
        "user_id": f"eq.{UID}",  # ownership: the offerings are the course's, the rows the student's
        "offering_id": f"in.({OFF_ENROLLED},{OFF_CURRENT})",
        "close_json": "is.null",
        "ended_at": "is.null",
        # a loop session only: a legacy tutor session's loop_state is the column
        # default '{}', filtered BEFORE the limit so it cannot push loop sessions off
        "loop_state": "neq.{}",
        "mode": "neq.review",
    }
    assert call["order"] == "started_at.desc" and call["limit"] == ll.LOOP_OPEN_SESSIONS_LIMIT
    # never reads the ciphertext (is.null only, invariant 9) nor model_pref (invariant 22);
    # close_phase is written WITH close_json (session_close.store_close), so an open row has none
    for col in ("close_json", "close_phase", "model_pref"):
        assert col not in call["cols"]
    gate_on[1].assert_not_called()  # the enrollment keyspace is not the sessions keyspace


def test_drops_a_document_with_no_loop_state_or_a_closed_one(gate_on):
    rows = [
        _row("s1", state={}),  # the server filter's job; the route stays defensive
        _row("s3"),
        _row("s4", state={"phase": "close"}),  # its close is being stored
    ]
    r = _get(_Db(rows))
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
    r = _get(_Db([_row("s1", state=state)]))
    assert r.json()["sessions"] == [
        {
            "session_id": "s1",
            "topic": "topic s1",
            "started_at": "2026-09-20T10:00:00Z",
            "phase": phase,
        }
    ]


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
            assert _get(_Db([_row("s1")])).status_code == 200
    finally:
        app.dependency_overrides.pop(ai_budget.enforce_rate_limit, None)
    (route,) = [r for r in learn_loop.router.routes if r.path == "/sessions"]
    assert ai_budget.enforce_rate_limit not in {d.call for d in route.dependant.dependencies}
    assert route.methods == {"GET"}


# ── ?resume=<id>: the deep-linked session, wherever it lives (PKG-13 fix round) ──
# The Dashboard / Tree deep links (`/learn?resume=<id>`) name ONE session. The
# picker lists one course's newest LOOP_OPEN_SESSIONS_LIMIT, so a deep link to an
# open loop session in another course, or beyond the limit, was opened READ-ONLY
# as if it were a legacy chat. `resume` answers the question with the row itself.


def _get_resume(db, sid):
    import services.academics as academics

    with patch("routes.learn_loop.table", db), patch.object(academics, "table", db):
        return client.get(f"{URL}&resume={sid}")


def test_no_resume_param_keeps_the_response_shape(gate_on):
    r = _get(_Db([_row("s1")]))
    assert set(r.json()) == {"sessions"}


def test_a_listed_resume_is_answered_from_the_list_with_no_second_read(gate_on):
    db = _Db([_row("s2", started="2026-09-21T10:00:00Z"), _row("s1")])
    body = _get_resume(db, "s1").json()
    assert body["resume"] == {
        "session_id": "s1",
        "topic": "topic s1",
        "started_at": "2026-09-20T10:00:00Z",
        "phase": "probe",
        "course_id": COURSE,
    }
    assert len(db.reads("sessions")) == 1


def test_a_resume_in_another_course_names_that_course(gate_on):
    other_off = "off-other"
    db = _Db(
        [_row("s1"), _row("s-other", offering=other_off)],
        offering_courses={OFF_ENROLLED: COURSE, OFF_CURRENT: COURSE, other_off: "c2"},
    )
    body = _get_resume(db, "s-other").json()
    assert [s["session_id"] for s in body["sessions"]] == ["s1"]  # the picker stays per course
    assert body["resume"]["session_id"] == "s-other" and body["resume"]["course_id"] == "c2"
    _, lookup = db.reads("sessions")
    assert lookup["filters"] == {
        "id": "eq.s-other",
        "user_id": f"eq.{UID}",  # never another student's session
        "close_json": "is.null",
        "ended_at": "is.null",
        "loop_state": "neq.{}",
        "mode": "neq.review",
    }
    assert lookup["limit"] == 1 and "close_json" not in lookup["cols"]


def test_a_resume_beyond_the_list_limit_is_found(gate_on):
    rows = [
        _row(f"s{i:02d}", started=f"2026-09-{i + 1:02d}T10:00:00Z")
        for i in range(ll.LOOP_OPEN_SESSIONS_LIMIT + 2)
    ]
    rows.sort(key=lambda r: r["started_at"], reverse=True)
    body = _get_resume(_Db(rows), "s00").json()
    assert len(body["sessions"]) == ll.LOOP_OPEN_SESSIONS_LIMIT
    assert "s00" not in [s["session_id"] for s in body["sessions"]]
    assert body["resume"]["session_id"] == "s00" and body["resume"]["course_id"] == COURSE


@pytest.mark.parametrize(
    "rows",
    [
        [],  # not the student's, closed, ended or a review session (filtered by the read)
        [_row("s1", state={})],  # a legacy tutor chat: no loop state
        [_row("s1", state={"phase": "close"})],  # its close is being stored
    ],
)
def test_a_resume_that_is_not_an_open_loop_session_is_null(gate_on, rows):
    body = _get_resume(_Db(rows), "s1").json()
    assert body["resume"] is None


def test_a_resume_whose_course_cannot_be_resolved_is_null(gate_on):
    db = _Db([_row("s-x", offering="off-gone")])
    assert _get_resume(db, "s-x").json()["resume"] is None
