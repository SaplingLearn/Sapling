"""services/tutor/course.py::_get_course_id_for_topic (and its sync twin, the
loop opener's): enrollments first (best effort), then the graph by concept
name, then by the legacy subject."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from services.tutor import course


def _tables(by_name):
    """table(name) -> a fake whose select/aselect answer `by_name[name]`
    (a list of row lists, one per call, or an exception to raise)."""
    calls = {name: iter(answers) for name, answers in by_name.items()}

    def table(name):
        def answer(*_a, **_k):
            value = next(calls[name])
            if isinstance(value, BaseException):
                raise value
            return value
        t = MagicMock()
        t.select.side_effect = answer
        t.aselect = AsyncMock(side_effect=answer)
        return t
    return table


def _run(topic, by_name):
    with patch.object(course, "table", side_effect=_tables(by_name)):
        sync = course._get_course_id_for_topic_sync(topic, "u1")
    with patch.object(course, "table", side_effect=_tables(by_name)):
        async_ = asyncio.run(course._get_course_id_for_topic(topic, "u1"))
    assert sync == async_, (sync, async_)
    return sync


def test_an_enrolled_course_code_matches_first():
    enrolled = [{"course_offerings": {"course_id": "c-cs", "courses": {
        "course_code": "CS101", "course_name": "Intro CS"}}}]
    assert _run("cs101", {"enrollments": [enrolled]}) == "c-cs"


def test_a_malformed_enrollment_row_is_a_failed_best_effort_read_and_the_graph_still_answers():
    """A non-string course_code makes the matcher raise; that is the enrollment
    read failing (logged), not the request: the graph fallbacks still run."""
    enrolled = [{"course_offerings": {"course_id": "c-x", "courses": {
        "course_code": 101, "course_name": "Intro"}}}]
    assert _run("Recursion", {
        "enrollments": [enrolled],
        "graph_nodes": [[{"course_id": "c-graph"}], []],
    }) == "c-graph"


def test_a_failed_enrollment_read_falls_back_and_a_failed_graph_read_propagates():
    import pytest

    assert _run("Recursion", {
        "enrollments": [RuntimeError("enrollments down")],
        "graph_nodes": [[], [{"course_id": "c-subject"}]],
    }) == "c-subject"
    with patch.object(course, "table", side_effect=_tables({
        "enrollments": [[]], "graph_nodes": [RuntimeError("graph down")],
    })):
        with pytest.raises(RuntimeError, match="graph down"):
            course._get_course_id_for_topic_sync("Recursion", "u1")


def test_a_blank_topic_reads_nothing():
    table = MagicMock()
    with patch.object(course, "table", table):
        assert course._get_course_id_for_topic_sync("   ", "u1") == ""
        assert asyncio.run(course._get_course_id_for_topic("", "u1")) == ""
    table.assert_not_called()
