"""F5: silent-empty detection for agent tool results.

Three personalization inputs returned zero rows for months with nobody
noticing — #529's swallowed 42P10, the misconceptions tool filtering
`offering_concept_stats.offering_id` with an abstract course id, and the
digest coercer looking for keys the writer never wrote. Each was invisible
for the same reason: an empty list is what "nothing to say" looks like, and
nothing distinguished that from "the query is wrong".

`report_empty_result` is that distinction. Zero rows for a user who
plausibly SHOULD have data is a warning plus a countable event; zero rows
for a user who genuinely has none is silence.
"""

from unittest.mock import MagicMock, patch

import pytest

from services import events_service
from services.tool_signals import Expect, report_empty_result

# The `sink` fixture (collect enqueued events instead of writing them) lives in
# tests/conftest.py — it was duplicated here and in
# test_quiz_tool_instrumentation.py, and the copies had already drifted apart.


def _probe(has_rows: bool, *, raises: bool = False):
    """Patch tool_signals' table() so the expectation probe finds (or does
    not find) prior data for the user."""
    def factory(name):
        m = MagicMock()
        if raises:
            m.select.side_effect = RuntimeError("postgrest exploded")
        else:
            m.select.return_value = [{"id": "x"}] if has_rows else []
        return m
    return patch("services.tool_signals.table", side_effect=factory)


# ── The signal fires ────────────────────────────────────────────────────────


def test_empty_result_for_a_user_with_data_warns_and_emits(sink, caplog):
    with _probe(True):
        flagged = report_empty_result(
            "read_misconceptions_for_course",
            user_id="u1",
            count=0,
            expect=Expect.ENROLLED,
            payload={"concept_node_id": "n1"},
        )
    assert flagged is True
    events_service.flush_now()

    assert len(sink) == 1
    row = sink[0]
    assert row["event_type"] == "quiz.tool_empty"
    # category="usage", NOT "error": this fires once per generation for every
    # student in a class whose aggregates exist, and /api/admin/analytics/
    # errors scans `category = error` newest-first — filing it there buries
    # quiz.context_write_failed and rag.retrieval_failed under routine
    # traffic. Same call quiz.rag_uncovered already makes.
    assert row["category"] == "usage"
    assert row["user_id"] == "u1"
    # The tool name is the whole point — an operator has to know WHICH input
    # went quiet, not just that one did.
    assert row["payload"]["tool"] == "read_misconceptions_for_course"
    assert row["payload"]["expect"] == "enrolled"
    assert row["payload"]["concept_node_id"] == "n1"
    assert "read_misconceptions_for_course" in caplog.text
    # The user id rides the event's own field, never the log message
    # (Engineering Style Guide forbids logging user ids).
    assert "u1" not in caplog.text


def test_feature_dimension_lets_the_tutor_share_the_seam(sink):
    """The pinned event name is quiz-prefixed, so a non-quiz caller has to be
    separable by payload — otherwise tutor noise pollutes quiz rollups."""
    with _probe(True):
        report_empty_result(
            "read_concepts_for_user",
            user_id="u1",
            count=0,
            expect=Expect.HAS_GRAPH,
            feature="tutor",
        )
    events_service.flush_now()
    assert sink[0]["payload"]["feature"] == "tutor"


# ── The signal stays quiet ──────────────────────────────────────────────────


def test_non_empty_result_emits_nothing_and_never_probes(sink):
    """The probe is a DB read on the request path; a tool that returned rows
    must not pay for it."""
    with _probe(True) as probe:
        flagged = report_empty_result(
            "read_recent_quiz_attempts", user_id="u1", count=3,
            expect=Expect.HAS_ATTEMPTS,
        )
    assert flagged is False
    probe.assert_not_called()
    events_service.flush_now()
    assert sink == []


def test_empty_result_for_a_user_with_no_history_is_silence(sink):
    """A first-week student legitimately has no attempts. Warning on that
    would train everyone to ignore the warning."""
    with _probe(False):
        flagged = report_empty_result(
            "read_recent_quiz_attempts", user_id="u1", count=0,
            expect=Expect.HAS_ATTEMPTS,
        )
    assert flagged is False
    events_service.flush_now()
    assert sink == []


def test_missing_user_id_is_silence(sink):
    with _probe(True):
        assert report_empty_result(
            "t", user_id=None, count=0, expect=Expect.HAS_GRAPH,
        ) is False
    events_service.flush_now()
    assert sink == []


# ── It can never break the tool it observes ─────────────────────────────────


def test_probe_failure_degrades_to_silence(sink):
    """Can't-tell is not evidence of a bug. A failed probe must not raise
    into the tool and must not manufacture a finding either."""
    with _probe(False, raises=True):
        assert report_empty_result(
            "t", user_id="u1", count=0, expect=Expect.HAS_ATTEMPTS,
        ) is False
    events_service.flush_now()
    assert sink == []


def test_probe_failure_is_logged_loudly(sink, caplog):
    """Silence toward the CALLER, not toward the operator. At debug level a
    permanently broken probe makes this whole seam inert while looking exactly
    like "no discrepancies found" — the F5 bug class, one layer up. The line
    has to name which probe and which table, and carry the traceback."""
    import logging

    with caplog.at_level(logging.WARNING, logger="services.tool_signals"):
        with _probe(False, raises=True):
            report_empty_result(
                "t", user_id="u1", count=0, expect=Expect.HAS_ATTEMPTS,
            )
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 1
    msg = warnings[0].getMessage()
    assert "has_attempts" in msg
    assert "quiz_attempts" in msg
    assert warnings[0].exc_info is not None
    # Never the user id (Engineering Style Guide).
    assert "u1" not in msg


def test_event_emission_failure_never_raises(sink):
    with _probe(True), patch(
        "services.tool_signals.log_event", side_effect=RuntimeError("boom")
    ):
        assert report_empty_result(
            "t", user_id="u1", count=0, expect=Expect.HAS_GRAPH,
        ) is False


def test_unknown_expectation_degrades_to_silence(sink):
    with _probe(True):
        assert report_empty_result(
            "t", user_id="u1", count=0, expect="not-an-expectation",
        ) is False
    events_service.flush_now()
    assert sink == []


# ── Probe targeting ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "expect,table_name",
    [
        (Expect.ENROLLED, "enrollments"),
        (Expect.HAS_ATTEMPTS, "quiz_attempts"),
        (Expect.HAS_GRAPH, "graph_nodes"),
    ],
)
def test_each_expectation_probes_its_own_table(sink, expect, table_name):
    """Wrong-table probes were the original bug class; pin the mapping."""
    seen: list[str] = []

    def factory(name):
        seen.append(name)
        m = MagicMock()
        m.select.return_value = []
        return m

    with patch("services.tool_signals.table", side_effect=factory):
        report_empty_result("t", user_id="u1", count=0, expect=expect)
    assert seen == [table_name]


def test_scope_narrows_the_probe_to_the_slice_the_tool_read(sink):
    """The probe must ask the SAME question the tool asked.

    Regression: an unscoped HAS_ATTEMPTS probe answers "has this student
    ever completed a quiz", while the tool asked "on THIS concept". A
    student who has quizzed on Recursion and is starting their first quiz
    on Graphs would be flagged as a silently-broken input on every single
    generation — which is what ordinary progress through a course looks
    like, and enough false alarms to make the signal worthless.
    """
    captured = {}

    def factory(name):
        m = MagicMock()

        def _select(cols, **kw):
            captured.update(kw)
            return []

        m.select.side_effect = _select
        return m

    with patch("services.tool_signals.table", side_effect=factory):
        report_empty_result(
            "read_recent_quiz_attempts", user_id="u1", count=0,
            expect=Expect.HAS_ATTEMPTS,
            scope={"concept_node_id": "eq.n1"},
        )
    assert captured["filters"]["concept_node_id"] == "eq.n1"
    assert captured["filters"]["user_id"] == "eq.u1"
    assert captured["filters"]["completed_at"] == "not.is.null"


def test_scoped_probe_finding_nothing_is_silence(sink):
    """First quiz on a new concept, for a student with plenty of history
    elsewhere: the scoped probe finds nothing, so nothing is reported."""
    with _probe(False):
        flagged = report_empty_result(
            "read_recent_quiz_attempts", user_id="u1", count=0,
            expect=Expect.HAS_ATTEMPTS, scope={"concept_node_id": "eq.n1"},
        )
    assert flagged is False
    events_service.flush_now()
    assert sink == []


def test_feature_defaults_to_unknown_not_to_a_real_feature(sink):
    """A tool registered on several agents can't name its caller. Guessing
    'quiz' would file every tutor empty under the quiz's rollups."""
    with _probe(True):
        report_empty_result("t", user_id="u1", count=0, expect=Expect.HAS_GRAPH)
    events_service.flush_now()
    assert sink[0]["payload"]["feature"] == "unknown"


def test_async_form_does_not_block_the_event_loop(sink):
    """Agent tool bodies are async and the probe is a blocking Supabase
    read; called inline it would stall every other in-flight request on the
    worker. The async form must run it off-loop."""
    import asyncio
    import threading

    from services.tool_signals import report_empty_result_async

    caller_thread = threading.get_ident()
    probe_thread = {}

    def factory(name):
        m = MagicMock()

        def _select(cols, **kw):
            probe_thread["id"] = threading.get_ident()
            return [{"id": "x"}]

        m.select.side_effect = _select
        return m

    async def scenario():
        with patch("services.tool_signals.table", side_effect=factory):
            return await report_empty_result_async(
                "t", user_id="u1", count=0, expect=Expect.HAS_GRAPH,
            )

    assert asyncio.run(scenario()) is True
    assert probe_thread["id"] != caller_thread


def test_probe_is_owner_scoped_and_bounded(sink):
    """It must read only this user's rows, and must never pull a table."""
    captured = {}

    def factory(name):
        m = MagicMock()

        def _select(cols, **kw):
            captured.update(kw)
            captured["cols"] = cols
            return []

        m.select.side_effect = _select
        return m

    with patch("services.tool_signals.table", side_effect=factory):
        report_empty_result(
            "t", user_id="u1", count=0, expect=Expect.HAS_ATTEMPTS,
        )
    assert captured["filters"]["user_id"] == "eq.u1"
    assert captured["limit"] == 1
    # Completed attempts only: an in-flight row is not evidence the student
    # has history worth digesting.
    assert captured["filters"]["completed_at"] == "not.is.null"


def test_a_caller_that_already_knows_skips_the_probe(sink):
    """#556 review: some callers hold the answer before they get here. The
    quiz route reads a `graph_nodes` row for this user and course on its way
    in, so a HAS_GRAPH probe scoped to that course could only return what it
    just saw — a guaranteed-True round trip on the request path, once per
    generation, forever. The expectation still ships in the event: it names
    WHY the caller expected data, which is what a rollup reads."""
    with patch("services.tool_signals.table") as t:
        reported = report_empty_result(
            "quiz_signals.offerings_for_course",
            user_id="u1", count=0, expect=Expect.HAS_GRAPH,
            feature="quiz", plausible=True,
        )

    assert reported is True
    t.assert_not_called()
    events_service.flush_now()
    assert len(sink) == 1
    assert sink[0]["event_type"] == "quiz.tool_empty"
    assert sink[0]["payload"]["expect"] == "has_graph"


def test_a_caller_that_knows_there_is_nothing_reports_nothing(sink):
    """The flip side, and the reason this is a fact and not a flag: passing
    False must stay silent rather than fall back to probing."""
    with patch("services.tool_signals.table") as t:
        reported = report_empty_result(
            "t", user_id="u1", count=0, expect=Expect.HAS_GRAPH, plausible=False,
        )

    assert reported is False
    t.assert_not_called()
    events_service.flush_now()
    assert sink == []


def test_no_assertion_from_the_caller_still_probes(sink):
    """#592 review C4: `plausible` is an override for a caller that HOLDS the
    fact, never a way to turn the probe off. A caller that passes nothing —
    `scripts/benchmark_quiz.py`, whose fixture user has no graph_nodes — must
    still be checked, or the seam manufactures discrepancies for it."""
    with patch("services.tool_signals.table") as t:
        t.return_value.select.return_value = []   # this user has no graph
        reported = report_empty_result(
            "quiz_signals.offerings_for_course",
            user_id="quizfix-user-0001", count=0, expect=Expect.HAS_GRAPH,
            feature="quiz", plausible=None,
        )

    assert reported is False
    t.assert_called_once_with("graph_nodes")
    events_service.flush_now()
    assert sink == []


def test_the_probe_is_narrowed_to_the_scope_the_caller_supplied(sink):
    """A student with a graph in some OTHER course does not answer "should
    this course have had data?" — the mismatch would fire the alarm on the
    routine case of starting work in a second course."""
    captured = {}

    def factory(name):
        m = MagicMock()

        def select(columns="*", filters=None, **kw):
            captured.update(filters or {})
            return [{"id": "n1"}]

        m.select.side_effect = select
        return m

    with patch("services.tool_signals.table", side_effect=factory):
        report_empty_result(
            "quiz_signals.offerings_for_course",
            user_id="u1", count=0, expect=Expect.HAS_GRAPH, feature="quiz",
            scope={"course_id": "eq.c1"},
        )

    assert captured["course_id"] == "eq.c1"
    assert captured["user_id"] == "eq.u1"
