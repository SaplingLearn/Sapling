"""#866 K40: a submit names why no question could move the mastery.

The results screen said "Your mastery didn't change this time: a question
counts toward it once a day, and only when it passed its checks" whenever the
shown whole percent stood still: a guess from the number. The percent can
stand still with evidence written (a mastery at 99.5 % reads 100 %; right and
wrong answers that net out), and the write can fail (#760), and then that
reason is false. Submit knows what each gate kept, so it says why, and says
nothing when a question could have moved the mastery.

The fixture quiz has two questions; the payload answers the first right ("A")
and the second wrong ("C") (tests/test_quiz_scoring_e.py LOOP_QUESTIONS).
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from learning import params
from services.quiz.unmoved import mastery_unmoved
from tests.test_quiz_evidence_only import _Claims, _farm_tables, _hashes, _submit_with


def _claimed(*hashes):
    now = datetime.now(timezone.utc)
    return _Claims(dict.fromkeys(hashes, now))


def test_every_question_already_counted_says_so():
    r = _submit_with(_farm_tables(_claimed(*_hashes())), MagicMock(return_value=[]))
    assert r.status_code == 200, r.text
    assert r.json()["mastery_unmoved"] == ["already_counted"]


def test_every_question_held_by_its_checks_says_so():
    with patch("learning.quiz_evidence.evidence_exclusion", return_value=["ambiguous_key"]):
        r = _submit_with(_farm_tables(_Claims()), apply := MagicMock(return_value=[]))
    assert r.status_code == 200, r.text
    apply.assert_not_called()
    assert r.json()["mastery_unmoved"] == ["not_verified"]


def test_a_right_answer_with_help_and_a_counted_one_name_both():
    asked, counted = _hashes()
    r = _submit_with(
        _farm_tables(_claimed(counted)), MagicMock(return_value=[{"before": 0.5, "after": 0.5}]),
        help_floors={asked: params.RUNG_NO_CREDIT_MIN},
    )
    assert r.status_code == 200, r.text
    assert r.json()["mastery_unmoved"] == ["already_counted", "helped"]


def test_a_failed_claim_is_a_failed_write():
    r = _submit_with(_farm_tables(_Claims(fail=True)), MagicMock(return_value=[]))
    assert r.status_code == 200, r.text
    assert r.json()["mastery_unmoved"] == ["write_failed"]


def test_a_graph_write_that_raises_is_a_failed_write():
    r = _submit_with(_farm_tables(_Claims()), MagicMock(side_effect=RuntimeError("graph down")))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mastery_unmoved"] == ["write_failed"]
    assert body["mastery_after"] == body["mastery_before"]


@pytest.mark.parametrize("applied", [
    pytest.param([{"before": 0.5, "after": 0.5}, {"before": 0.5, "after": 0.5}], id="evidence that nets out"),
    pytest.param([{"before": 0.5, "after": 0.6}, {"before": 0.6, "after": 0.55}], id="evidence that moved it"),
])
def test_written_evidence_names_no_reason_whatever_the_percent_shows(applied):
    """The wrong answer is a standard observation: it could move the mastery,
    so no reason is true even when the number stands still."""
    r = _submit_with(_farm_tables(_Claims()), MagicMock(return_value=applied))
    assert r.status_code == 200, r.text
    assert "mastery_unmoved" not in r.json()


def test_one_wrong_answer_that_counted_names_no_reason():
    right, wrong = _hashes()
    r = _submit_with(_farm_tables(_claimed(right)), MagicMock(return_value=[{"before": 0.5, "after": 0.45}]))
    assert r.status_code == 200, r.text
    assert "mastery_unmoved" not in r.json()


def test_the_reasons_rule():
    right_helped = {"correct": True, "max_rung": params.RUNG_NO_CREDIT_MIN}
    assisted = {"correct": True, "max_rung": params.RUNG_ASSISTED_MIN}
    assert mastery_unmoved(graded=0, checked=0, counted=0, written=[], stored=True) is None
    assert mastery_unmoved(graded=2, checked=1, counted=0, written=[], stored=True) == [
        "not_verified", "already_counted"]
    assert mastery_unmoved(graded=1, checked=1, counted=1, written=[right_helped], stored=True) == ["helped"]
    assert mastery_unmoved(graded=1, checked=1, counted=1, written=[assisted], stored=True) is None
    assert mastery_unmoved(graded=1, checked=1, counted=1, written=[{**right_helped, "correct": False}],
                           stored=True) is None
    assert mastery_unmoved(graded=1, checked=1, counted=1, written=[right_helped], stored=False) == [
        "write_failed"]
