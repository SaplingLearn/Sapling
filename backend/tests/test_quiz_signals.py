"""#556 (Workstream H4, epic #537): the cheap signals nobody was reading."""
from unittest.mock import MagicMock, patch

from services.quiz_signals import QuizSignals, gather_signals, prompt_block


class TestPromptBlock:
    def test_nothing_known_produces_no_block(self):
        """'times studied: unknown' spends tokens to say nothing, and a block
        of unknowns trains the model to ignore the block."""
        assert prompt_block(QuizSignals()) == ""

    def test_only_the_signals_we_have_appear(self):
        block = prompt_block(QuizSignals(times_studied=4, flashcards=12))
        assert "studied 4x" in block
        assert "12 flashcard(s)" in block
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
            return m

        with patch("services.quiz_signals.table", side_effect=factory):
            return gather_signals("u1", "node1", concept_name="Recursion", **kw)

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

    def test_counts_only_unfinished_attempts(self):
        s = self._gather({"quiz_attempts": [{"id": "a"}, {"id": "b"}]})
        assert s.in_flight_attempts == 2

    def test_counts_flashcards_without_reading_their_content(self):
        with patch("services.quiz_signals.table") as t:
            t.return_value.select.return_value = [{"id": "f1"}]
            gather_signals("u1", "node1", concept_name="Recursion")

        cols = [c.args[0] for c in t.return_value.select.call_args_list]
        assert all("front" not in c and "back" not in c for c in cols), (
            "flashcard front/back are encrypted (#518) and this is a COUNT"
        )

    def test_a_failing_read_degrades_to_unknown_not_zero(self):
        """None means 'we could not tell'; 0 is a fact about the student.
        Collapsing them would report 'never studied' for a broken query."""
        def factory(name):
            m = MagicMock()
            m.select.side_effect = RuntimeError("db down")
            return m

        with patch("services.quiz_signals.table", side_effect=factory):
            s = gather_signals("u1", "node1", concept_name="Recursion")

        assert s.in_flight_attempts is None
        assert s.flashcards is None
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
    dims = QuizSignals(1, 2.0, 3, 4).as_dimensions()
    assert set(dims) == {
        "signal_times_studied", "signal_velocity",
        "signal_in_flight", "signal_flashcards",
    }
    assert list(dims.values()) == [1, 2.0, 3, 4]
