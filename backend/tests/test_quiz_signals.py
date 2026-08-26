"""#556 (Workstream H4, epic #537): the cheap signals nobody was reading."""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from services.quiz_signals import (
    CourseScope,
    QuizSignals,
    course_offering_ids,
    gather_signals,
    prompt_block,
)

#: What a caller with no course hands in — every field unknown. `scope` is a
#: REQUIRED argument, so "I have nothing" has to be said out loud rather than
#: arrived at by omission.
_NO_SCOPE = CourseScope()


def _iso(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


class _Reads:
    """A per-table fake for `db.connection.table`.

    `spec` maps a table name to ``(rows, total)``; an unnamed table reads
    empty. Every call's arguments are captured because several of the
    assertions below are about the QUERY, not the answer — "never selects the
    encrypted column" and "is owner-scoped" have nothing else to check.
    """

    def __init__(self, spec: dict | None = None, raises=frozenset()):
        self.spec = spec or {}
        self.raises = set(raises)
        self.calls: dict[str, list[dict]] = {}

    def __call__(self, name: str):
        outer = self

        class _T:
            def select(self, columns="*", filters=None, order=None, limit=None, offset=None):
                return outer._answer(name, columns, filters, order, limit)[0]

            def select_with_count(
                self, columns="*", filters=None, order=None, limit=None, offset=None
            ):
                return outer._answer(name, columns, filters, order, limit)

        return _T()

    def _answer(self, name, columns, filters, order, limit):
        self.calls.setdefault(name, []).append(
            {"columns": columns, "filters": filters or {}, "order": order, "limit": limit}
        )
        if name in self.raises:
            raise RuntimeError(f"{name} read failed")
        return self.spec.get(name, ([], 0))


def _gather(
    spec=None,
    *,
    offerings=("off-1",),
    course_name="Machine Learning",
    name_failed=False,
    raises=frozenset(),
    **kw,
):
    """Run a full gather against a scope the caller already resolved.

    `offerings=None` is "we could not tell"; `()` is "this course has no
    offering at all" — the two are different answers and the module treats
    them differently.
    """
    reads = _Reads(spec, raises)
    scope = CourseScope(
        offering_ids=None if offerings is None else list(offerings),
        course_name=course_name,
        name_failed=name_failed,
    )
    with patch("services.quiz_signals.table", side_effect=reads):
        signals = gather_signals(
            "u1", "node1", scope=scope,
            course_id="c1", concept_name="Gradient Descent", **kw,
        )
    return signals, reads, scope


class TestPromptBlock:
    def test_nothing_known_produces_no_block(self):
        """'times studied: unknown' spends tokens to say nothing, and a block
        of unknowns trains the model to ignore the block."""
        assert prompt_block(QuizSignals()) == ""

    def test_only_the_signals_we_have_appear(self):
        block = prompt_block(QuizSignals(times_studied=4))
        assert "studied 4x" in block
        assert "unfinished" not in block
        assert "mastery gain" not in block

    def test_zero_velocity_is_not_reported(self):
        """`_compute_velocity` returns 0.0 both for 'no recent gain' and 'not
        enough data'. Reporting it would assert stagnation we cannot tell
        apart from silence."""
        assert "mastery gain" not in prompt_block(QuizSignals(velocity_per_day=0.0))

    def test_zero_times_studied_IS_reported(self):
        """Unlike velocity, a zero here is a fact: the student has never
        studied this concept, which is exactly what a generator should know."""
        assert "studied 0x" in prompt_block(QuizSignals(times_studied=0))


class TestGatherSignals:
    def _gather(self, tables: dict, **kw):
        def factory(name):
            m = MagicMock()
            m.select.return_value = tables.get(name, [])
            m.select_with_count.return_value = (tables.get(name, []), len(tables.get(name, [])))
            return m

        with patch("services.quiz_signals.table", side_effect=factory):
            return gather_signals("u1", "node1", scope=_NO_SCOPE, **kw)

    def test_times_studied_is_passed_in_not_re_read(self):
        """generate_quiz already fetches that row to resolve the concept name
        and course. Re-reading it would spend a round-trip to learn something
        we were already told."""
        with patch("services.quiz_signals.table") as t:
            t.return_value.select.return_value = []
            s = gather_signals("u1", "node1", scope=_NO_SCOPE, times_studied=7)

        assert s.times_studied == 7
        assert not any(
            c.args and c.args[0] == "graph_nodes" for c in t.call_args_list
        ), "times_studied must not cost a graph_nodes read"

    def test_reports_the_true_count_not_a_saturated_page(self):
        """`select_with_count` — `len(rows)` under a LIMIT would report the cap
        as though it were a fact about the student."""
        with patch("services.quiz_signals.table") as t:
            t.return_value.select_with_count.return_value = ([{"id": "a"}], 37)
            t.return_value.select.return_value = []
            s = gather_signals("u1", "node1", scope=_NO_SCOPE)

        assert s.in_flight_attempts == 37

    def test_in_flight_applies_the_abandonment_ttl(self):
        """#542's `_attempt_status` calls an in-progress row past the TTL
        abandoned even before the lazy sweep stamps it — and the sweep runs on
        the history reads, not on generation. Checking only the NULL stamps
        would report week-old attempts to the model as active."""
        with patch("services.quiz_signals.table") as t:
            t.return_value.select_with_count.return_value = ([], 0)
            t.return_value.select.return_value = []
            gather_signals("u1", "node1", scope=_NO_SCOPE)

        filters = t.return_value.select_with_count.call_args.kwargs["filters"]
        assert filters["created_at"].startswith("gte."), (
            "in-flight must share #542's TTL, not define 'unfinished' again"
        )

    def test_a_failing_read_degrades_to_unknown_not_zero(self):
        """None means 'we could not tell'; 0 is a fact about the student.
        Collapsing them would report 'never studied' for a broken query."""
        def factory(name):
            m = MagicMock()
            m.select.side_effect = RuntimeError("db down")
            m.select_with_count.side_effect = RuntimeError("db down")
            return m

        with patch("services.quiz_signals.table", side_effect=factory):
            s = gather_signals("u1", "node1", scope=_NO_SCOPE)

        assert s.in_flight_attempts is None
        assert s.velocity_per_day is None

    def test_never_raises(self):
        with patch("services.quiz_signals.table", side_effect=RuntimeError("boom")):
            assert isinstance(gather_signals("u1", "node1", scope=_NO_SCOPE), QuizSignals)

    def test_velocity_reuses_the_graph_service_computation(self):
        """Not a second copy of the 14-day rule — #557 is what two copies of
        one number costs."""
        with (
            patch("services.quiz_signals.table") as t,
            patch("services.graph_service._compute_velocity", return_value=0.05) as calc,
        ):
            t.return_value.select.return_value = [{"delta": 0.03, "created_at": "x"}]
            s = gather_signals("u1", "node1", scope=_NO_SCOPE)

        calc.assert_called_once()
        assert s.velocity_per_day == 0.05


def test_dimensions_cover_every_signal():
    """F6: the issue asks for these to land BEHIND the measurement, so each
    signal has to be attributable in `llm_usage.prompt_tokens`."""
    dims = QuizSignals(1, 2.0, 3, 12, 7, 3, 4, 5).as_dimensions()
    assert set(dims) == {
        "signal_times_studied", "signal_velocity", "signal_in_flight",
        "signal_flashcards_course_cards",
        "signal_flashcards_course_reviewed",
        "signal_flashcards_course_last_review_days",
        "signal_tutor_course_sessions_14d",
        "signal_tutor_concept_days_since",
    }
    assert list(dims.values()) == [1, 2.0, 3, 12, 7, 3, 4, 5]
    # Every field, not "the ones someone remembered": a signal that reaches
    # the prompt without a dimension is a signal whose token cost the morning
    # cannot attribute, which is the one thing this issue asked for.
    assert len(dims) == len(QuizSignals._fields)


def test_velocity_matches_what_the_graph_screen_shows():
    """#556 review finding 1, and the exact failure the module set out to
    avoid by importing `_compute_velocity` instead of copying it.

    That function treats `recent[0]` as the OLDEST recent event — it derives
    the window from it — and `graph_service.get_graph` therefore reads
    `created_at.asc`. This module reads `desc` (correctly, so the LIMIT keeps
    the NEWEST events rather than the oldest), which means the rows must be
    reversed before they are handed over. Without that, `days` collapses to 1
    and the velocity inflates by up to 14x, so the Tree and the quiz prompt
    report different numbers for the same concept.
    """
    from datetime import datetime, timedelta, timezone

    from services.graph_service import _compute_velocity

    now = datetime.now(timezone.utc)
    ascending = [
        {"delta": 0.1, "created_at": (now - timedelta(days=d)).isoformat()}
        for d in (10, 7, 4, 1)
    ]
    expected = _compute_velocity(ascending)

    with patch("services.quiz_signals.table") as t:
        # PostgREST hands them back newest-first, as this module asks.
        t.return_value.select.return_value = list(reversed(ascending))
        got = gather_signals("u1", "node1", scope=_NO_SCOPE).velocity_per_day

    assert got == expected, (
        f"quiz prompt would report {got} where the graph screen shows {expected}"
    )


class TestCourseOfferingIds:
    """The keyspace itself (#592 merge gate).

    `sessions.offering_id` and `flashcards.offering_id` are written by
    `resolve_offering(course_id, …)` — the CURRENT term's offering, created if
    missing, and never checked against `enrollments`. Reading them back
    through an enrollment-derived list is a foreign keyspace in the #553/#529
    shape, and it diverges permanently at the first term rollover.
    """

    def test_it_reads_every_offering_of_the_course(self):
        reads = _Reads({
            "course_offerings": ([{"id": "off-fall"}, {"id": "off-spring"}], 2),
        })
        with patch("services.quiz_signals.table", side_effect=reads):
            assert course_offering_ids("c1") == ["off-fall", "off-spring"]

        assert reads.calls["course_offerings"][0]["filters"] == {
            "course_id": "eq.c1"
        }

    def test_it_never_consults_enrollments(self):
        """The divergence, stated as a query shape. Ownership on both signal
        tables comes from `user_id`, so intersecting with enrollments adds no
        safety — it only subtracts the offerings the writers actually use."""
        reads = _Reads({
            "course_offerings": ([{"id": "off-fall"}, {"id": "off-spring"}], 2),
        })
        with patch("services.quiz_signals.table", side_effect=reads):
            course_offering_ids("c1")

        assert "enrollments" not in reads.calls

    def test_no_course_is_unknown(self):
        assert course_offering_ids(None) is None
        assert course_offering_ids("") is None

    def test_a_failing_read_is_unknown_and_LOUD(self, caplog):
        """A transient PostgREST outage must not look like a student with
        nothing. At debug this was invisible in production — the exact bug
        class this module exists to end, one layer up."""
        reads = _Reads(raises={"course_offerings"})
        with (
            patch("services.quiz_signals.table", side_effect=reads),
            caplog.at_level("WARNING", logger="services.quiz_signals"),
        ):
            assert course_offering_ids("c1") is None

        assert any(
            r.levelname == "WARNING" and "offering resolution failed" in r.message
            for r in caplog.records
        ), "a real DB failure must reach the operator, not just a debug line"

    def test_a_truncated_read_is_unknown_not_a_partial_list(self):
        """Every signal keyed on this scope would undercount against a
        truncated offering list — and report the undercount as a fact."""
        reads = _Reads({"course_offerings": ([{"id": "off-1"}], 5000)})
        with patch("services.quiz_signals.table", side_effect=reads):
            assert course_offering_ids("c1") is None


class TestSharedScope:
    """The quiz route resolves the scope ONCE and hands it in — the two reads
    (this course's `course_offerings` and its `courses` row) are ones its
    other concurrent legs already make, and concurrent legs cannot share by
    accident."""

    def test_an_injected_scope_costs_no_resolution_reads(self):
        _, reads, _ = _gather({"flashcards": ([], 0), "sessions": ([], 0)})

        assert "courses" not in reads.calls
        assert "course_offerings" not in reads.calls
        # Exactly the reads that are genuinely new work for these two signals
        # — plus the two the older three signals already made.
        assert sorted(reads.calls) == [
            "flashcards", "node_mastery_events", "quiz_attempts", "sessions",
        ]

    def test_the_scope_is_required_rather_than_defaulted(self):
        """A default would let a caller get silently-unknown course signals by
        forgetting an argument, which is the failure mode this whole module is
        written against. Forgetting it is a TypeError instead."""
        import pytest

        with pytest.raises(TypeError):
            gather_signals("u1", "node1")


class TestCourseScope:
    """Both #556 signals key on the OFFERING (`flashcards.offering_id`,
    `sessions.offering_id`), while the quiz route holds the abstract
    `course_id`. Resolving that once, in one place, is the whole reason the
    misconceptions tool spent months reading a foreign keyspace (#553)."""

    def test_without_a_course_neither_new_signal_is_attempted(self):
        reads = _Reads()
        with patch("services.quiz_signals.table", side_effect=reads):
            s = gather_signals(
                "u1", "node1", scope=_NO_SCOPE, concept_name="Gradient Descent",
            )

        assert "flashcards" not in reads.calls
        assert "sessions" not in reads.calls
        assert s.flashcards_course_cards is None
        assert s.tutor_course_sessions_14d is None

    def test_a_course_with_no_offering_at_all_is_reported_as_a_discrepancy(self):
        """F5: the caller just read a graph node for this user in this course,
        so they plausibly have data — yet the COURSE has no offering, which
        leaves every offering-keyed input dark. That is the #553 keyspace
        shape, not "this student has nothing yet".

        Note this is now a property of the course rather than of the student's
        enrollment, which is what makes it worth an alarm: every path that
        creates graph data for a course (upload, tutoring) resolves an
        offering with `create=True` on the way through."""
        with patch("services.quiz_signals.report_empty_result") as report:
            s, _, _ = _gather(
                {"flashcards": ([], 0)}, offerings=(), has_graph=True,
            )

        assert report.call_count == 1
        assert report.call_args.kwargs["feature"] == "quiz"
        assert report.call_args.kwargs["count"] == 0
        # The probe is narrowed to THIS course: a graph in some other course
        # does not answer the question that was asked.
        assert report.call_args.kwargs["scope"] == {"course_id": "eq.c1"}
        # Tutor recency is offering-only, so it goes dark...
        assert s.tutor_course_sessions_14d is None
        # ...but the flashcard read still has the course NAME to match on,
        # which is the only thing that reaches AI-generated cards at all.
        assert s.flashcards_course_cards == 0

    def test_the_callers_own_knowledge_decides_whether_to_probe(self):
        """#592 review: `plausible=True` was hard-coded here, which made it a
        claim about a caller this module cannot see. `scripts/benchmark_quiz.py`
        drives the same generator with a fixture user that has NO graph_nodes,
        so every benchmark run wrote a false `quiz.tool_empty`. Whatever the
        caller passes is what reaches the reporter — `None` included, which is
        "I did not look, go and check"."""
        for known in (True, None):
            with patch("services.quiz_signals.report_empty_result") as report:
                _gather({"flashcards": ([], 0)}, offerings=(), has_graph=known)
            assert report.call_args.kwargs["plausible"] is known

    def test_the_ordinary_empty_path_raises_no_alarm(self):
        """Zero flashcards and zero tutor sessions are what a first-week
        student looks like. `tool_signals` exists to catch a silently BROKEN
        input, and firing on ordinary emptiness is the alarm fatigue that
        would train everyone to ignore it — so nothing is reported when the
        scope resolves and the reads are simply empty."""
        with patch("services.quiz_signals.report_empty_result") as report:
            s, _, _ = _gather(
                {"flashcards": ([], 0), "sessions": ([], 0)}, has_graph=True,
            )

        report.assert_not_called()
        assert s.flashcards_course_cards == 0
        assert s.tutor_course_sessions_14d == 0

    def test_an_unresolvable_scope_is_unknown_not_zero(self):
        """A failed offering resolution leaves BOTH signals unknown — the
        flashcard one included, even though it could still match on the
        course name.

        The course name and a matching card are deliberately present here:
        with the offerings unknown, a topic-only `or=` tree would omit every
        imported deck and report the remainder as though it were the whole
        collection. A partial count presented as a fact is worse than no
        count, and this is exactly the case the module calls unknown.
        """
        s, reads, _ = _gather(
            {"flashcards": ([{"times_reviewed": 4, "last_reviewed_at": None}], 1)},
            offerings=None,
        )

        assert s.flashcards_course_cards is None
        assert s.flashcards_course_reviewed is None
        assert s.tutor_course_sessions_14d is None
        # Not even attempted: there is no honest query to make.
        assert "flashcards" not in reads.calls

    def test_a_failed_course_read_leaves_the_flashcards_unknown(self):
        """#592 review C3: the guard existed only on the offering side. With
        the `courses` read FAILED the flashcard tree ran offering-only — and
        an offering-only tree cannot see an AI-generated card, which carries
        no `offering_id` at all. So "has 2 flashcard(s)", or a verified zero,
        would be a subset reported as the whole collection.

        The tutor signal needs no name and is unaffected: it still runs."""
        s, reads, _ = _gather(
            {
                "flashcards": ([{"times_reviewed": 4, "last_reviewed_at": None}], 1),
                "sessions": ([], 0),
            },
            course_name=None,
            name_failed=True,
        )

        assert s.flashcards_course_cards is None
        assert s.flashcards_course_reviewed is None
        assert "flashcards" not in reads.calls
        # ...and the half that never needed the name is still a fact.
        assert s.tutor_course_sessions_14d == 0


class TestFlashcardCourseState:
    """COURSE-scoped by construction, and named so. `flashcards` carries no
    concept link at all, so a concept-level version of this signal would be a
    permanent zero dressed up as a fact about the student."""

    def _spec(self, cards, total=None):
        return {"flashcards": (cards, len(cards) if total is None else total)}

    def test_the_read_asks_for_this_course_by_offering_AND_by_topic(self):
        """Neither key alone sees the collection. Imported cards carry an
        `offering_id` (`routes/flashcards.py:419` resolves one); AI-generated
        cards never do — that insert omits the column — and carry only a
        `topic`. Reading only the offering would under-report every generated
        deck.

        The narrowing happens in PostgREST, not in Python: a `user_id`-only
        scan would carry the student's whole collection across the wire and
        cap a three-card course behind a four-hundred-card one."""
        _, reads, _ = _gather(self._spec([]), offerings=("off-fall", "off-spring"))
        clause = reads.calls["flashcards"][0]["filters"]["or"]

        assert clause == (
            '(offering_id.in.(off-fall,off-spring),'
            'topic.ilike."%Machine Learning%")'
        )

    def test_the_topic_match_is_a_substring_the_way_the_study_screen_matches(self):
        """#592 review C2. The module used case-insensitive EQUALITY on the
        theory that every writer sets `topic` to the course name. True of the
        generate path (its only caller passes `course.course_name`); false of
        the import path, where `topic` is a text box the student types into.
        `Study.tsx` files a card under a course with
        `topic.toLowerCase().includes(courseName.toLowerCase())` — so equality
        both missed imported decks and disagreed with the count the student
        can see on their own screen."""
        _, reads, _ = _gather(self._spec([]), course_name="Machine Learning")
        clause = reads.calls["flashcards"][0]["filters"]["or"]

        assert 'topic.ilike."%Machine Learning%"' in clause, (
            "a card topic'd 'Machine Learning midterm' is one the Study "
            "screen counts for this course; exact equality drops it"
        )

    def test_a_course_name_with_a_comma_cannot_break_the_logic_tree(self):
        """A bare value ends at the first comma inside `or=(…)`, so
        "Ethics, Law and Society" would parse as two broken operands."""
        _, reads, _ = _gather(
            self._spec([]), course_name='Ethics, Law and "Society"',
        )
        clause = reads.calls["flashcards"][0]["filters"]["or"]

        assert clause.endswith(r'topic.ilike."%Ethics, Law and \"Society\"%")')

    def test_like_metacharacters_in_a_course_name_are_not_wildcards(self):
        """`ilike` is a PATTERN match: `_` is any single character and `%` is
        any run of them, so "Math_101" would also match "Math-101" and a name
        with a `%` would match half the student's collection. Only the two
        `%` this module adds are live. The LIKE escape runs first and
        `pg_quote_value` then doubles its backslashes for PostgREST — the
        other order emits a bare `\\%` that PostgREST unescapes back to a live
        wildcard."""
        _, reads, _ = _gather(
            self._spec([]), course_name="Math_101 100% Theory",
        )
        clause = reads.calls["flashcards"][0]["filters"]["or"]

        assert clause.endswith(r'topic.ilike."%Math\\_101 100\\% Theory%")')

    def test_the_tally_comes_from_the_rows_the_filter_returned(self):
        cards = [
            {"times_reviewed": 3, "last_reviewed_at": _iso(2)},
            {"times_reviewed": 0, "last_reviewed_at": None},
        ]
        s, _, _ = _gather(self._spec(cards))

        assert s.flashcards_course_cards == 2
        assert s.flashcards_course_reviewed == 1
        assert s.flashcards_course_last_review_days == 2

    def test_no_cards_is_a_zero_not_an_unknown(self):
        s, _, _ = _gather(self._spec([]))
        assert s.flashcards_course_cards == 0
        assert s.flashcards_course_reviewed == 0
        # ...but "never reviewed" has no recency, and 0 days would read as
        # "reviewed today".
        assert s.flashcards_course_last_review_days is None

    def test_a_truncated_read_keeps_the_count_and_drops_only_the_tally(self):
        """The count comes from Content-Range, so the cap cannot corrupt it,
        and the newest-review ordering means the recency answer survives too.
        Only "how many are reviewed" would be capped — and a cap the model
        read as a fact is exactly what must not happen."""
        cards = [{"times_reviewed": 1, "last_reviewed_at": _iso(1)}]
        s, _, _ = _gather(self._spec(cards, total=9999))

        assert s.flashcards_course_cards == 9999
        assert s.flashcards_course_reviewed is None
        assert s.flashcards_course_last_review_days == 1

    def test_the_encrypted_card_text_is_never_selected(self):
        """`front`/`back` are column-encrypted and this signal never needs
        them — selecting them would drag ciphertext across the wire on the
        generation path for nothing."""
        _, reads, _ = _gather(self._spec([]))
        cols = reads.calls["flashcards"][0]["columns"]
        assert "front" not in cols
        assert "back" not in cols

    def test_the_read_is_owner_scoped(self):
        _, reads, _ = _gather(self._spec([]))
        assert reads.calls["flashcards"][0]["filters"]["user_id"] == "eq.u1"

    def test_a_failing_read_degrades_to_unknown(self):
        s, _, _ = _gather(self._spec([]), raises={"flashcards"})
        assert s.flashcards_course_cards is None
        assert s.flashcards_course_reviewed is None


class TestTutorRecency:
    """`messages` has no `user_id` — it is session-scoped — so this is a
    bounded owner-scoped `sessions` read followed by one `messages` read over
    the ids it returned."""

    def _spec(self, sessions, msgs, total=None):
        return {
            "sessions": (sessions, len(sessions) if total is None else total),
            "messages": (msgs, len(msgs)),
        }

    def test_days_since_the_last_turn_that_touched_this_concept(self):
        msgs = [  # newest first, as the read asks for
            {"created_at": _iso(1), "graph_update_json":
                {"updated_nodes": [{"concept_name": "Backpropagation"}]}},
            {"created_at": _iso(4), "graph_update_json":
                {"new_nodes": [{"concept_name": "gradient  DESCENT"}]}},
            {"created_at": _iso(9), "graph_update_json":
                {"updated_nodes": [{"concept_name": "Gradient Descent"}]}},
        ]
        s, _, _ = _gather(self._spec([{"id": "s1", "started_at": _iso(1)}], msgs))

        # 4, not 9 — the newest match wins; and the tutor writes whatever the
        # model spelled, so casing/spacing drift still has to match (the same
        # normalization `apply_graph_update` dedups on).
        assert s.tutor_concept_days_since == 4

    def test_sessions_that_never_touched_it_leave_recency_unknown(self):
        msgs = [{"created_at": _iso(1), "graph_update_json":
                 {"updated_nodes": [{"concept_name": "Backpropagation"}]}}]
        s, _, _ = _gather(self._spec([{"id": "s1", "started_at": _iso(1)}], msgs))

        # Not 0 — "we tutored this concept today" is a very different claim
        # from "we did not find it in the window we looked at".
        assert s.tutor_concept_days_since is None
        assert s.tutor_course_sessions_14d == 1

    def test_the_session_count_is_the_exact_total_not_the_scan_cap(self):
        sessions = [{"id": f"s{i}", "started_at": _iso(i)} for i in range(5)]
        s, _, _ = _gather(self._spec(sessions, [], total=11))
        assert s.tutor_course_sessions_14d == 11

    def test_no_sessions_is_a_zero_not_an_unknown(self):
        s, _, _ = _gather(self._spec([], []))
        assert s.tutor_course_sessions_14d == 0
        assert s.tutor_concept_days_since is None

    def test_a_string_payload_is_parsed(self):
        """`graph_update_json` is JSONB, but `end_session`'s own reader
        tolerates a string shape, so this one does too."""
        msgs = [{"created_at": _iso(3), "graph_update_json": json.dumps(
            {"new_nodes": [{"concept_name": "Gradient Descent"}]})}]
        s, _, _ = _gather(self._spec([{"id": "s1", "started_at": _iso(3)}], msgs))
        assert s.tutor_concept_days_since == 3

    def test_the_encrypted_message_content_is_never_selected(self):
        _, reads, _ = _gather(self._spec([{"id": "s1", "started_at": _iso(1)}], []))
        assert "content" not in reads.calls["messages"][0]["columns"]

    def test_the_session_read_is_owner_scoped_offering_scoped_and_windowed(self):
        _, reads, _ = _gather(self._spec([], []))
        filters = reads.calls["sessions"][0]["filters"]

        assert filters["user_id"] == "eq.u1"
        # Offering, not course: `sessions` has no course_id column at all
        # (0025 recreated it without one), and passing a course id where an
        # offering id belongs is exactly the #553 mismatch.
        assert filters["offering_id"] == "in.(off-1)"
        assert "gte." in filters["or"]
        assert reads.calls["sessions"][0]["limit"] is not None

    def test_a_resumed_session_is_not_excluded_by_the_window(self):
        """#592 review C6. Sessions never auto-end and have no age gate, and
        "Where you left off" on the dashboard resumes one rather than opening
        a new one. Keying the window on `started_at` alone therefore excluded
        the app's own first-class flow: a session opened three weeks ago and
        used yesterday read as no tutoring at all."""
        _, reads, _ = _gather(self._spec([], []))
        clause = reads.calls["sessions"][0]["filters"]["or"]

        assert "ended_at.is.null" in clause, (
            "an unfinished session is evidence of tutoring whatever day it "
            f"was opened; got {clause!r}"
        )
        assert clause.startswith("(") and clause.endswith(")")

    def test_the_prompt_line_does_not_claim_more_than_the_query_checked(self):
        """The flip side of widening it: the count now includes sessions that
        were never ended, whenever they started. Saying only "in the last 14
        days" would assert something the query did not verify."""
        line = prompt_block(QuizSignals(tutor_course_sessions_14d=3))
        assert "still open" in line

    def test_the_message_read_is_bounded_to_the_sessions_just_found(self):
        sessions = [{"id": "s1", "started_at": _iso(1)},
                    {"id": "s2", "started_at": _iso(2)}]
        _, reads, _ = _gather(self._spec(sessions, []))
        filters = reads.calls["messages"][0]["filters"]

        assert filters["session_id"] == "in.(s1,s2)"
        assert reads.calls["messages"][0]["limit"] is not None

    def test_a_failing_session_read_degrades_to_unknown(self):
        s, _, _ = _gather(self._spec([], []), raises={"sessions"})
        assert s.tutor_course_sessions_14d is None
        assert s.tutor_concept_days_since is None

    def test_a_failing_message_read_keeps_the_session_count(self):
        """Two reads, two independent facts: losing the concept scan is no
        reason to throw away the count we already have."""
        s, _, _ = _gather(
            self._spec([{"id": "s1", "started_at": _iso(1)}], []),
            raises={"messages"},
        )
        assert s.tutor_course_sessions_14d == 1
        assert s.tutor_concept_days_since is None


class TestPromptBlockForTheDeferredSignals:
    def test_the_flashcard_line_states_its_course_scope(self):
        block = prompt_block(QuizSignals(
            flashcards_course_cards=12,
            flashcards_course_reviewed=7,
            flashcards_course_last_review_days=3,
        ))
        assert "12" in block and "7" in block and "3" in block
        # Unmistakably course-level. There is no concept-level flashcard data,
        # and a line the model reads as concept-level is a lie about the
        # student — the reason this half of #556 was deferred in the first
        # place.
        assert "course" in block.lower()
        assert "not this concept" in block.lower()

    def test_a_student_with_no_cards_for_this_course_says_nothing(self):
        assert prompt_block(QuizSignals(
            flashcards_course_cards=0, flashcards_course_reviewed=0,
        )) == ""

    def test_tutor_lines_appear_only_when_known(self):
        assert prompt_block(QuizSignals(tutor_course_sessions_14d=None)) == ""
        assert prompt_block(QuizSignals(tutor_course_sessions_14d=0)) == ""
        assert "tutor" in prompt_block(
            QuizSignals(tutor_course_sessions_14d=3)
        ).lower()

    def test_tutored_today_is_reported_even_though_it_is_zero(self):
        """Unlike a zero session count, 0 days is the strongest form of this
        signal, not the absence of it."""
        assert "concept" in prompt_block(
            QuizSignals(tutor_concept_days_since=0)
        ).lower()


class TestCalendarDayArithmetic:
    """#592 review C9: `_days_since` bucketed by elapsed 24-hour periods while
    `prompt_block` renders CALENDAR words ("today"/"yesterday") and the exam
    line one sentence away in the same prompt counts calendar days
    (`(due - today).days`). The two disagreed by a day for most of every day.
    """

    def test_the_module_uses_the_shared_calendar_rule(self):
        from services import quiz_signals
        from services.timestamps import calendar_days_since

        assert quiz_signals._days_since is calendar_days_since

    def test_last_night_is_yesterday_not_today(self):
        from services.timestamps import calendar_days_since

        now = datetime(2026, 8, 26, 9, 0, tzinfo=timezone.utc)
        last_night = datetime(2026, 8, 25, 23, 0, tzinfo=timezone.utc).isoformat()

        assert calendar_days_since(last_night, now=now) == 1, (
            "10 hours ago is 0 elapsed days but yesterday to a reader — and "
            "'last review today' would be a false statement about the student"
        )

    def test_this_morning_is_today(self):
        from services.timestamps import calendar_days_since

        now = datetime(2026, 8, 26, 23, 0, tzinfo=timezone.utc)
        this_morning = datetime(2026, 8, 26, 1, 0, tzinfo=timezone.utc).isoformat()

        assert calendar_days_since(this_morning, now=now) == 0

    def test_a_future_stamp_is_clamped_rather_than_negative(self):
        """Clock skew on a just-written row would otherwise render "-1 days
        ago", which reads as a data bug in a prompt."""
        from services.timestamps import calendar_days_since

        now = datetime(2026, 8, 26, 9, 0, tzinfo=timezone.utc)
        tomorrow = datetime(2026, 8, 27, 9, 0, tzinfo=timezone.utc).isoformat()

        assert calendar_days_since(tomorrow, now=now) == 0

    def test_an_unreadable_stamp_is_unknown(self):
        from services.timestamps import calendar_days_since

        assert calendar_days_since(None) is None
        assert calendar_days_since("not a timestamp") is None

    def test_a_naive_stamp_is_read_as_utc_rather_than_raising(self):
        """An out-of-band write can leave a naive value; comparing one against
        an aware `now()` raises TypeError, which an `except ValueError` around
        the parse does not catch."""
        from services.timestamps import calendar_days_since

        now = datetime(2026, 8, 26, 9, 0, tzinfo=timezone.utc)
        assert calendar_days_since("2026-08-24T09:00:00", now=now) == 2


def test_the_prompt_budget_benchmark_measures_the_real_signal_block():
    """#592 review C8, H4 half. `docs/quiz-prompt-budget.md` publishes token
    counts from `scripts/bench_quiz_prompt_budget.py`; a hand-copied version
    of this block there would price a sentence the prompt does not contain."""
    from scripts.bench_quiz_prompt_budget import signals_line

    line = signals_line()
    assert line == prompt_block(QuizSignals(
        times_studied=6,
        velocity_per_day=0.041,
        in_flight_attempts=2,
        flashcards_course_cards=42,
        flashcards_course_reviewed=17,
        flashcards_course_last_review_days=3,
        tutor_course_sessions_14d=4,
        tutor_concept_days_since=2,
    ))
    # Every signal present: the ceiling is what the benchmark is for.
    assert all(
        token in line
        for token in ("studied 6x", "mastery gain", "unfinished", "flashcard",
                      "tutored on this concept", "tutor session")
    )
