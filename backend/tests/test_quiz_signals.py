"""#556 (Workstream H4, epic #537): the cheap signals nobody was reading."""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from services.quiz_signals import (
    CourseScope,
    QuizSignals,
    gather_signals,
    prompt_block,
)


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


def _gather(spec=None, *, offerings=("off-1",), raises=frozenset(), **kw):
    """Run a full gather with the course scope resolved to `offerings`."""
    reads = _Reads(spec, raises)
    with (
        patch("services.quiz_signals.table", side_effect=reads),
        patch(
            "services.quiz_signals.user_offering_ids_for_course",
            return_value=list(offerings),
        ) as resolve,
    ):
        signals = gather_signals(
            "u1", "node1",
            course_id="c1", concept_name="Gradient Descent", **kw,
        )
    return signals, reads, resolve


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
            return gather_signals("u1", "node1", **kw)

    def test_times_studied_is_passed_in_not_re_read(self):
        """generate_quiz already fetches that row to resolve the concept name
        and course. Re-reading it would spend a round-trip to learn something
        we were already told."""
        with patch("services.quiz_signals.table") as t:
            t.return_value.select.return_value = []
            s = gather_signals("u1", "node1", times_studied=7)

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
            s = gather_signals("u1", "node1")

        assert s.in_flight_attempts == 37

    def test_in_flight_applies_the_abandonment_ttl(self):
        """#542's `_attempt_status` calls an in-progress row past the TTL
        abandoned even before the lazy sweep stamps it — and the sweep runs on
        the history reads, not on generation. Checking only the NULL stamps
        would report week-old attempts to the model as active."""
        with patch("services.quiz_signals.table") as t:
            t.return_value.select_with_count.return_value = ([], 0)
            t.return_value.select.return_value = []
            gather_signals("u1", "node1")

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
            s = gather_signals("u1", "node1")

        assert s.in_flight_attempts is None
        assert s.velocity_per_day is None

    def test_never_raises(self):
        with patch("services.quiz_signals.table", side_effect=RuntimeError("boom")):
            assert isinstance(gather_signals("u1", "node1"), QuizSignals)

    def test_velocity_reuses_the_graph_service_computation(self):
        """Not a second copy of the 14-day rule — #557 is what two copies of
        one number costs."""
        with (
            patch("services.quiz_signals.table") as t,
            patch("services.graph_service._compute_velocity", return_value=0.05) as calc,
        ):
            t.return_value.select.return_value = [{"delta": 0.03, "created_at": "x"}]
            s = gather_signals("u1", "node1")

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
        got = gather_signals("u1", "node1").velocity_per_day

    assert got == expected, (
        f"quiz prompt would report {got} where the graph screen shows {expected}"
    )


class TestSharedScope:
    """The quiz route resolves the scope ONCE and hands it in — the same three
    reads (`course_offerings` + `enrollments`, uncached, and the `courses`
    row) are ones its other concurrent legs already make, and concurrent legs
    cannot share by accident."""

    def test_an_injected_scope_costs_no_resolution_reads(self):
        reads = _Reads({
            "flashcards": ([], 0),
            "sessions": ([], 0),
        })
        with (
            patch("services.quiz_signals.table", side_effect=reads),
            patch("services.quiz_signals.user_offering_ids_for_course") as resolve,
        ):
            gather_signals(
                "u1", "node1", course_id="c1", concept_name="Gradient Descent",
                scope=CourseScope(offering_ids=["off-1"], course_name="ML"),
            )

        resolve.assert_not_called()
        assert "courses" not in reads.calls
        # Exactly the three reads that are genuinely new work for these two
        # signals — plus the two the older three signals already made.
        assert sorted(reads.calls) == [
            "flashcards", "node_mastery_events", "quiz_attempts", "sessions",
        ]

    def test_an_omitted_scope_still_resolves_itself(self):
        """Every other caller — and every existing test — passes no scope."""
        _, reads, resolve = _gather({"courses": ([{"course_name": "ML"}], 1)})
        resolve.assert_called_once_with("u1", "c1")
        assert "courses" in reads.calls


class TestCourseScope:
    """Both #556 signals key on the OFFERING (`flashcards.offering_id`,
    `sessions.offering_id`), while the quiz route holds the abstract
    `course_id`. Resolving that once, in one place, is the whole reason the
    misconceptions tool spent months reading a foreign keyspace (#553)."""

    def test_without_a_course_neither_new_signal_is_attempted(self):
        reads = _Reads()
        with (
            patch("services.quiz_signals.table", side_effect=reads),
            patch("services.quiz_signals.user_offering_ids_for_course") as resolve,
        ):
            s = gather_signals("u1", "node1", concept_name="Gradient Descent")

        resolve.assert_not_called()
        assert "flashcards" not in reads.calls
        assert "sessions" not in reads.calls
        assert s.flashcards_course_cards is None
        assert s.tutor_course_sessions_14d is None

    def test_the_offerings_are_resolved_once_for_both_signals(self):
        _, _, resolve = _gather({"courses": ([{"course_name": "ML"}], 1)})
        resolve.assert_called_once_with("u1", "c1")

    def test_a_course_with_no_enrollment_is_reported_as_a_discrepancy(self):
        """F5: the route just read a graph node for this user in this course,
        so they plausibly have data — yet no offering of it resolves, which
        leaves every offering-keyed input dark. That is the #553 keyspace
        shape, not "this student has nothing yet"."""
        reads = _Reads({"courses": ([{"course_name": "ML"}], 1)})
        with (
            patch("services.quiz_signals.table", side_effect=reads),
            patch(
                "services.quiz_signals.user_offering_ids_for_course",
                return_value=[],
            ),
            patch("services.quiz_signals.report_empty_result") as report,
        ):
            s = gather_signals(
                "u1", "node1", course_id="c1", concept_name="Gradient Descent",
            )

        assert report.call_count == 1
        assert report.call_args.kwargs["feature"] == "quiz"
        assert report.call_args.kwargs["count"] == 0
        # The caller already read a graph node for this user and course, so a
        # HAS_GRAPH probe could only return what it just saw. Asserting the
        # fact is passed in keeps that guaranteed-True round trip off the
        # generation path — where it would run once per quiz, forever.
        assert report.call_args.kwargs["plausible"] is True
        # Tutor recency is offering-only, so it goes dark...
        assert s.tutor_course_sessions_14d is None
        # ...but the flashcard read still has the course NAME to match on,
        # which is the only thing that reaches AI-generated cards at all.
        assert s.flashcards_course_cards == 0

    def test_the_ordinary_empty_path_raises_no_alarm(self):
        """Zero flashcards and zero tutor sessions are what a first-week
        student looks like. `tool_signals` exists to catch a silently BROKEN
        input, and firing on ordinary emptiness is the alarm fatigue that
        would train everyone to ignore it — so nothing is reported when the
        scope resolves and the reads are simply empty."""
        spec = {
            "courses": ([{"course_name": "ML"}], 1),
            "flashcards": ([], 0),
            "sessions": ([], 0),
        }
        reads = _Reads(spec)
        with (
            patch("services.quiz_signals.table", side_effect=reads),
            patch(
                "services.quiz_signals.user_offering_ids_for_course",
                return_value=["off-1"],
            ),
            patch("services.quiz_signals.report_empty_result") as report,
        ):
            s = gather_signals(
                "u1", "node1", course_id="c1", concept_name="Gradient Descent",
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
        reads = _Reads({
            "courses": ([{"course_name": "Machine Learning"}], 1),
            "flashcards": ([{"times_reviewed": 4, "last_reviewed_at": None}], 1),
        })
        with (
            patch("services.quiz_signals.table", side_effect=reads),
            patch(
                "services.quiz_signals.user_offering_ids_for_course",
                side_effect=RuntimeError("db down"),
            ),
        ):
            s = gather_signals(
                "u1", "node1", course_id="c1", concept_name="Gradient Descent",
            )

        assert s.flashcards_course_cards is None
        assert s.flashcards_course_reviewed is None
        assert s.tutor_course_sessions_14d is None
        # Not even attempted: there is no honest query to make.
        assert "flashcards" not in reads.calls


class TestFlashcardCourseState:
    """COURSE-scoped by construction, and named so. `flashcards` carries no
    concept link — `topic` is free text that every writer sets to the course
    name — so a concept-level version of this signal would be a permanent
    zero dressed up as a fact about the student."""

    def _spec(self, cards, total=None):
        return {
            "courses": ([{"course_name": "Machine Learning"}], 1),
            "flashcards": (cards, len(cards) if total is None else total),
        }

    def test_the_read_asks_for_this_course_by_offering_AND_by_topic(self):
        """Neither key alone sees the collection. Imported cards carry an
        `offering_id` (`routes/flashcards.py` resolves one); AI-generated
        cards never do, and take the COURSE NAME as their `topic` — which is
        also how the Study screen decides a card belongs to a course. Reading
        only the offering would under-report every generated deck.

        The narrowing happens in PostgREST, not in Python: a `user_id`-only
        scan would carry the student's whole collection across the wire and
        cap a three-card course behind a four-hundred-card one."""
        _, reads, _ = _gather(self._spec([]))
        clause = reads.calls["flashcards"][0]["filters"]["or"]

        assert clause == '(offering_id.in.(off-1),topic.ilike."Machine Learning")'

    def test_a_course_name_with_a_comma_cannot_break_the_logic_tree(self):
        """A bare value ends at the first comma inside `or=(…)`, so
        "Ethics, Law and Society" would parse as two broken operands."""
        spec = {
            "courses": ([{"course_name": 'Ethics, Law and "Society"'}], 1),
            "flashcards": ([], 0),
        }
        _, reads, _ = _gather(spec)
        clause = reads.calls["flashcards"][0]["filters"]["or"]

        assert clause.endswith(r'topic.ilike."Ethics, Law and \"Society\"")')

    def test_like_metacharacters_in_a_course_name_are_not_wildcards(self):
        """`ilike` is a PATTERN match: `_` is any single character and `%` is
        any run of them, so "Math_101" would also match "Math-101" and a name
        with a `%` would match half the student's collection. The LIKE escape
        runs first and `_pg_quote` then doubles its backslashes for PostgREST
        — the other order emits a bare `\\%` that PostgREST unescapes back to
        a live wildcard."""
        spec = {
            "courses": ([{"course_name": "Math_101 100% Theory"}], 1),
            "flashcards": ([], 0),
        }
        _, reads, _ = _gather(spec)
        clause = reads.calls["flashcards"][0]["filters"]["or"]

        assert clause.endswith(r'topic.ilike."Math\\_101 100\\% Theory")')

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
            "courses": ([{"course_name": "Machine Learning"}], 1),
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
        # Offering, not course: `sessions` has no course_id, and passing one
        # is exactly the #553 mismatch.
        assert filters["offering_id"] == "in.(off-1)"
        assert filters["started_at"].startswith("gte.")
        assert reads.calls["sessions"][0]["limit"] is not None

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
