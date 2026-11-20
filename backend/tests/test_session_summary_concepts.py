"""#866 K47: the legacy tutor's End-session summary and the quiz's "last
tutored" signal count the concept a session was opened on.

Both read the concepts a session covered off its messages' graph_update_json:
`updated_nodes` (main's update_mastery_tool, the tutor's mastery judgement)
and `new_nodes`. PKG-14b (spec §11.2) removed that tool for every student, so
only concepts the tutor newly created were left: a loop-off student's "Concepts
covered" came back empty for the usual session, one opened on a concept from
the picker or the map, and the quiz's tutor recency went quiet. The session's
own concept is structured data the session already holds: its topic, when that
is the name of one of the student's graph nodes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from services.quiz.signals import CourseScope, gather_signals
from services.tutor.sessions import _session_summary, _stored_session_summary
from tests.split_patches import patch_tutor

STARTED = "2026-11-01T10:00:00+00:00"
ENDED = "2026-11-01T10:20:00+00:00"
SESSION = {"user_id": "u1", "topic": "Recursion", "offering_id": "off-1", "started_at": STARTED}


def _tables(*, msgs, nodes, sessions=None):
    """sessions / messages / graph_nodes, recording reads."""
    reads: dict[str, list[dict]] = {}

    def factory(name):
        m = MagicMock()

        def select(columns="*", filters=None, limit=None, **kw):
            reads.setdefault(name, []).append({"columns": columns, "filters": filters or {}, "limit": limit})
            return {
                "messages": msgs,
                "graph_nodes": nodes,
                "sessions": sessions or [],
            }.get(name, [])

        m.select.side_effect = select
        return m

    return factory, reads


def _summary(session, msgs, nodes):
    factory, reads = _tables(msgs=msgs, nodes=nodes)
    with patch_tutor("table", side_effect=factory), patch_tutor("offering_course_id", return_value="c1"):
        summary = _session_summary("s1", STARTED, ENDED, session=session)
    return summary, reads


def test_a_session_opened_on_a_concept_covers_it():
    msgs = [{"role": "assistant", "graph_update_json": None}, {"role": "user", "graph_update_json": None}]
    summary, reads = _summary(SESSION, msgs, [{"concept_name": "Recursion"}])
    assert summary == {"concepts_covered": ["Recursion"], "time_spent_minutes": 20}
    # the student's own node, in the session's course, by its stored name
    lookup = reads["graph_nodes"][0]
    assert lookup["filters"] == {"user_id": "eq.u1", "concept_name": "eq.Recursion", "course_id": "eq.c1"}
    assert lookup["columns"] == "concept_name" and lookup["limit"] == 1


def test_it_comes_first_and_the_tutors_new_concepts_follow():
    msgs = [
        {"role": "user", "graph_update_json": None},
        {"role": "assistant", "graph_update_json": {"new_nodes": [{"concept_name": "Base case"}]}},
        # a row written before PKG-14b still counts
        {"role": "assistant", "graph_update_json": {"updated_nodes": [{"concept_name": "Call stack"}]}},
        {"role": "assistant", "graph_update_json": {"new_nodes": [{"concept_name": "Recursion"}]}},
    ]
    summary, _ = _summary(SESSION, msgs, [{"concept_name": "Recursion"}])
    assert summary["concepts_covered"] == ["Recursion", "Base case", "Call stack"]


def test_a_session_the_student_never_wrote_in_covers_nothing_of_its_own():
    msgs = [{"role": "assistant", "graph_update_json": None}]  # the greeting only
    summary, reads = _summary(SESSION, msgs, [{"concept_name": "Recursion"}])
    assert summary["concepts_covered"] == []
    assert "graph_nodes" not in reads  # nothing to look up


def test_a_free_topic_a_course_or_a_note_title_is_no_concept():
    msgs = [{"role": "user", "graph_update_json": None}]
    summary, reads = _summary({**SESSION, "topic": "Week 3 notes"}, msgs, [])
    assert summary["concepts_covered"] == []
    assert reads["graph_nodes"][0]["filters"]["concept_name"] == "eq.Week 3 notes"


def test_no_session_row_or_topic_reads_nothing_more():
    msgs = [{"role": "user", "graph_update_json": {"new_nodes": [{"concept_name": "Base case"}]}}]
    for session in (None, {**SESSION, "topic": ""}):
        summary, reads = _summary(session, msgs, [{"concept_name": "Recursion"}])
        assert summary["concepts_covered"] == ["Base case"]
        assert "graph_nodes" not in reads


def test_a_failed_concept_read_never_fails_the_end():
    factory, _ = _tables(msgs=[{"role": "user", "graph_update_json": None}], nodes=[])

    def failing(name):
        handle = factory(name)
        if name == "graph_nodes":
            handle.select.side_effect = RuntimeError("down")
        return handle

    with patch_tutor("table", side_effect=failing), patch_tutor("offering_course_id", return_value="c1"):
        summary = _session_summary("s1", STARTED, ENDED, session=SESSION)
    assert summary["concepts_covered"] == []


def test_a_repeat_end_recomputes_with_the_session_row():
    """#761: with no stored summary yet, a repeat end recomputes it from the
    row — topic included."""
    row = {**SESSION, "ended_at": ENDED, "summary_json": None}
    factory, reads = _tables(
        msgs=[{"role": "user", "graph_update_json": None}], nodes=[{"concept_name": "Recursion"}], sessions=[row],
    )
    with patch_tutor("table", side_effect=factory), patch_tutor("offering_course_id", return_value="c1"):
        summary = _stored_session_summary("s1")
    assert summary["concepts_covered"] == ["Recursion"]
    assert {"topic", "offering_id", "user_id"} <= set(reads["sessions"][0]["columns"].split(","))


# ── the quiz's "last tutored on this concept" (services/quiz/signals.py) ───


def _iso(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


class _Reads:
    def __init__(self, sessions, msgs):
        self.sessions, self.msgs, self.calls = sessions, msgs, {}

    def __call__(self, name):
        outer = self

        class _T:
            def select(self, columns="*", filters=None, order=None, limit=None, offset=None):
                outer.calls.setdefault(name, []).append({"columns": columns, "filters": filters or {}})
                return outer.msgs if name == "messages" else []

            def select_with_count(self, columns="*", filters=None, order=None, limit=None, offset=None):
                outer.calls.setdefault(name, []).append({"columns": columns, "filters": filters or {}})
                rows = outer.sessions if name == "sessions" else []
                return rows, len(rows)

        return _T()


def _recency(sessions, msgs):
    from unittest.mock import patch

    reads = _Reads(sessions, msgs)
    scope = CourseScope(offering_ids=["off-1"], course_name="CS 101", name_failed=False)
    with patch("services.quiz.signals.table", side_effect=reads):
        signals = gather_signals("u1", "node1", scope=scope, course_id="c1", concept_name="Recursion")
    return signals, reads


def test_a_student_turn_in_a_session_opened_on_the_concept_is_tutoring_on_it():
    sessions = [{"id": "s-rec", "started_at": _iso(9), "topic": "recursion "}, {"id": "s-other", "started_at": _iso(1), "topic": "Trees"}]
    msgs = [  # newest first, as the read asks
        {"created_at": _iso(1), "session_id": "s-other", "role": "user", "graph_update_json": None},
        {"created_at": _iso(2), "session_id": "s-rec", "role": "user", "graph_update_json": None},
    ]
    signals, reads = _recency(sessions, msgs)
    assert signals.tutor_concept_days_since == 2
    # one bounded read: the graph-update rows, or the student's own turns in the
    # sessions opened on this concept — never the encrypted content
    read = reads.calls["messages"][0]
    assert read["filters"]["or"] == "(graph_update_json.not.is.null,and(role.eq.user,session_id.in.(s-rec)))"
    assert "graph_update_json" not in read["filters"]
    assert "content" not in read["columns"]


def test_a_session_on_another_topic_says_nothing_about_this_concept():
    sessions = [{"id": "s-other", "started_at": _iso(1), "topic": "Trees"}]
    msgs = [{"created_at": _iso(1), "session_id": "s-other", "role": "user", "graph_update_json": None}]
    signals, reads = _recency(sessions, msgs)
    assert signals.tutor_concept_days_since is None
    # with no session on the concept the read is the graph-update scan it was
    assert reads.calls["messages"][0]["filters"]["graph_update_json"] == "not.is.null"
    assert "or" not in reads.calls["messages"][0]["filters"]
