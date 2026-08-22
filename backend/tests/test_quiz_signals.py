"""#556 (Workstream H4, epic #537): the cheap signals nobody was reading."""
from unittest.mock import MagicMock, patch

from services.quiz_signals import QuizSignals, gather_signals, prompt_block


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
    dims = QuizSignals(1, 2.0, 3).as_dimensions()
    assert set(dims) == {
        "signal_times_studied", "signal_velocity", "signal_in_flight",
    }
    assert list(dims.values()) == [1, 2.0, 3]


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
