"""#866 K60: every loop model call records the course it served on its own
llm_usage row, so deleting its session cannot take its cost off the course.

The admin cost-per-learning-gain report (learning/cost_per_gain.py, spec §13
A137) puts a row on a course by the row's own `course_id`, else by its
session's course, read at report time. The drafting, grading and decision run
sites have recorded the course since A137; the loop tutor's turns and
continuations, the session close and the Jev decision shadows recorded only
the session, so a session deleted later (or wiped with its account) moved all
of their spend to "unattributed" and understated every course's cost per gain.
Each now records the course too — the abstract course id of the session's
offering, the id the report resolves a session to.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from learning.cost_per_gain import cost_per_gain
from services import events_service

# The static pin (every loop run site that records usage passes course_id=)
# is COURSE_SITES in tests/test_learning_llm_usage_course_id.py.


def test_a_loop_turn_records_the_sessions_course(monkeypatch):
    from services.loop import turn as turn_mod

    seen = []
    monkeypatch.setattr(turn_mod, "record_agent_usage", lambda result, **kw: seen.append(kw))
    monkeypatch.setattr(turn_mod, "served_model_name", lambda result, slot: "m")
    monkeypatch.setattr(turn_mod, "_requests_of", lambda result: 1)
    for course, recorded in (("course-1", "course-1"), ("", None)):  # a session with no offering
        fake = SimpleNamespace(run_requests=0, slot="loop_tutor", user_id="u", session_id="s1", course_id=course)
        turn_mod._LoopTurn.record_usage(fake, object())
        assert seen[-1]["course_id"] == recorded and seen[-1]["session_id"] == "s1"


@pytest.fixture
def sink(monkeypatch):
    rows: list = []

    class _T:
        def insert(self, r):
            rows.append(r)
            return r

    monkeypatch.setattr(events_service, "table", lambda name: _T())
    return rows


class _Result:
    output = "x"

    def usage(self):
        return SimpleNamespace(input_tokens=10, output_tokens=5, total_tokens=15, requests=1)

    @property
    def response(self):
        return SimpleNamespace(model_name="gemini-2.5-flash")


@pytest.mark.parametrize("failed", [False, True], ids=["successful-run", "billed-failed-run"])
def test_the_session_close_records_the_course_it_is_given(sink, monkeypatch, failed):
    import agents.session_close as sc
    from tests.test_learning_close_brief import _draft

    class CloseAgent:
        async def run(self, _message, *, deps, usage, usage_limits):
            if failed:
                usage.requests += 1
                usage.input_tokens += 10
                raise RuntimeError("validation exhausted")
            return _Result()

    monkeypatch.setattr(sc, "session_close_agent", CloseAgent())
    monkeypatch.setattr(sc.ai_budget, "check", lambda *a, **k: SimpleNamespace(level="normal"))
    monkeypatch.setattr("agents.usage.model_for", lambda _task: SimpleNamespace(model_name="gemini-2.5-flash"))
    asyncio.run(sc.run_session_close(_draft(), user_id="u", request_id="r", session_id="s1", course_id="course-1"))
    events_service.flush_now()
    rows = [r for batch in sink for r in batch if r.get("task") == "session_close"]
    assert [(r["session_id"], r["course_id"]) for r in rows] == [("s1", "course-1")]


def test_closing_a_session_hands_its_course_to_the_close_run(monkeypatch):
    """The close route reads the session row; its offering's abstract course
    goes to the close run with the session id."""
    from services.loop import closing
    from tests.test_learning_close_brief import EVIDENCE_N1, UID, _close_out, _wire_close, client
    from tests.split_patches import setattr_loop

    tables, _, _ = _wire_close(monkeypatch, evidence=[EVIDENCE_N1], loop_state={"phase": "teach"})
    tables.rows["sessions"][0]["offering_id"] = "off-1"
    monkeypatch.setattr(closing, "offering_course_id", lambda o: {"off-1": "course-1"}.get(o, ""))
    seen = []

    async def run(draft, *, user_id, request_id, session_id=None, course_id=None):
        seen.append((session_id, course_id))
        return _close_out()

    setattr_loop(monkeypatch, "run_session_close", run)
    r = client.post("/api/learn/loop/close", json={"session_id": "s1", "user_id": UID})
    assert r.status_code == 200, r.text
    assert seen == [("s1", "course-1")]


def test_a_course_that_cannot_be_read_never_fails_the_close(monkeypatch):
    """The course is a label on the usage row: a failed read names none, and
    the model close still runs and is stored."""
    from services.loop import closing
    from tests.test_learning_close_brief import EVIDENCE_N1, UID, _close_out, _wire_close, client
    from tests.split_patches import setattr_loop

    tables, _, _ = _wire_close(monkeypatch, evidence=[EVIDENCE_N1], loop_state={"phase": "teach"})
    tables.rows["sessions"][0]["offering_id"] = "off-1"

    def down(offering):
        raise RuntimeError("course_offerings unreachable")

    monkeypatch.setattr(closing, "offering_course_id", down)
    seen = []

    async def run(draft, *, user_id, request_id, session_id=None, course_id=None):
        seen.append((session_id, course_id))
        return _close_out()

    setattr_loop(monkeypatch, "run_session_close", run)
    r = client.post("/api/learn/loop/close", json={"session_id": "s1", "user_id": UID})
    assert r.status_code == 200, r.text
    assert r.json()["model_written"] is True
    assert seen == [("s1", None)]


def test_a_decision_shadow_keeps_the_course(monkeypatch):
    """A Jev shadow outlives its request, so it keeps ids only — the course
    among them, which its billed row records (spec §13 A137)."""
    from services import learning_decisions as ld

    captured = []

    async def run_shadow(decision, state, sdeps, value, confidence):
        captured.append(sdeps)

    monkeypatch.setattr(ld._jev, "privacy_gate_open", lambda: True)
    monkeypatch.setattr(ld, "_run_shadow", run_shadow)
    deps = SimpleNamespace(user_id="u", request_id="r", session_id="s1", feature="loop", course_id="course-1")

    async def go():
        ld._shadow("match_wrong_reason", object(), deps, "none", 0.9)
        await asyncio.gather(*list(ld._SHADOW_TASKS))

    asyncio.run(go())
    (sdeps,) = captured
    assert (sdeps.session_id, sdeps.course_id) == ("s1", "course-1")


def test_a_row_that_records_its_course_stays_on_it_after_its_session_is_gone():
    """The report half (unchanged): the row's own course wins; with the
    session deleted (no session → course mapping) it is still the course's."""
    usage = [
        {"task": "loop_tutor", "cost_usd": 0.02, "user_id": "u", "session_id": "gone", "course_id": "course-1"},
        {"task": "loop_tutor", "cost_usd": 0.01, "user_id": "u", "session_id": "gone-too"},
    ]
    report = cost_per_gain(usage, {}, [], {}, range_days=30)
    assert [c["course_id"] for c in report["courses"]] == ["course-1"]
    assert report["courses"][0]["cost_usd"] == pytest.approx(0.02)
    assert report["unattributed"] == {"cost_usd": pytest.approx(0.01), "rows": 1}
