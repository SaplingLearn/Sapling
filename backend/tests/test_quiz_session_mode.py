"""W7.8: Practice vs Exam Twin evidence rules.

Pure rules live in learning/quiz_session_mode.py. Submit skips mastery (and
the farm claim) for Exam Twin; quiz-ask refuses tools. No flag enable.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from learning import quiz_session_mode as mode
from services.quiz.unmoved import mastery_unmoved
from tests.test_quiz_evidence_only import _Claims, _farm_tables, _submit_with


def test_modes_and_defaults():
    assert mode.MODES == ("practice", "exam_twin")
    assert mode.parse(None) == mode.PRACTICE
    assert mode.parse("exam_twin") == mode.EXAM_TWIN
    assert mode.parse("nope") == mode.PRACTICE
    assert mode.LABELS[mode.PRACTICE] == "Practice"
    assert mode.LABELS[mode.EXAM_TWIN] == "Exam Twin"


@pytest.mark.parametrize(
    "session, mastery, tools, misc, farm",
    [
        (mode.PRACTICE, True, True, True, True),
        (mode.EXAM_TWIN, False, False, False, False),
    ],
)
def test_evidence_rules_table(session, mastery, tools, misc, farm):
    assert mode.writes_mastery(session) is mastery
    assert mode.allows_tools(session) is tools
    assert mode.allows_misconceptions(session) is misc
    assert mode.claims_farm_window(session) is farm


def test_unmoved_names_exam_twin_alone():
    assert mastery_unmoved(
        graded=2, checked=2, counted=2, written=[{"correct": False}], stored=True,
        exam_twin=True,
    ) == ["exam_twin"]


def _tables_with_mode(session_mode: str):
    """`_farm_tables` whose quiz_attempts row carries `session_mode`."""
    base = _farm_tables(_Claims())

    def factory(name):
        handle = base(name)
        if name == "quiz_attempts":
            rows = handle.select.return_value
            if rows:
                handle.select.return_value = [{**rows[0], "session_mode": session_mode}]
        return handle

    return factory


def test_exam_twin_submit_writes_no_mastery_and_claims_no_farm():
    """Dress rehearsal: score path runs; graph and farm stay untouched."""
    apply = MagicMock(return_value=[{"before": 0.4, "after": 0.9}])
    claim = MagicMock(side_effect=AssertionError("Exam Twin must not claim the farm"))
    with patch("services.quiz.submission._claim_quiz_evidence", claim):
        r = _submit_with(_tables_with_mode("exam_twin"), apply)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mastery_unmoved"] == ["exam_twin"]
    assert body["mastery_after"] == body["mastery_before"]
    apply.assert_not_called()
    claim.assert_not_called()


def test_practice_submit_still_writes_mastery():
    apply = MagicMock(return_value=[{"before": 0.5, "after": 0.55}, {"before": 0.55, "after": 0.5}])
    r = _submit_with(_tables_with_mode("practice"), apply)
    assert r.status_code == 200, r.text
    assert "mastery_unmoved" not in r.json()
    apply.assert_called_once()


def test_quiz_ask_refuses_exam_twin():
    from services import quiz_ask

    row = {
        "user_id": "u1",
        "concept_node_id": "n1",
        "questions_json": "[]",
        "session_mode": "exam_twin",
    }
    with patch.object(quiz_ask, "table") as table:
        table.return_value.select.return_value = [row]
        with pytest.raises(HTTPException) as exc:
            quiz_ask.resolve_quiz_ask("u1", "attempt1", 0)
    assert exc.value.status_code == 409
    assert "Exam Twin" in str(exc.value.detail)


def test_quiz_ask_allows_practice():
    from services import quiz_ask

    attempt = {
        "user_id": "u1",
        "concept_node_id": "n1",
        "questions_json": [{"id": 1, "question": "Q?", "options": []}],
        "session_mode": "practice",
    }
    node = {"id": "n1", "course_id": "c1"}

    def _select(cols, filters=None, limit=None, **_):
        if "concept_node_id" in (cols or "") or "questions_json" in (cols or ""):
            return [attempt]
        return [node]

    with patch.object(quiz_ask, "table") as table:
        table.return_value.select.side_effect = _select
        with patch.object(quiz_ask, "decrypt_json_column", return_value=attempt["questions_json"]):
            with patch.object(quiz_ask, "wire_question_hash", return_value="h1"):
                target = quiz_ask.resolve_quiz_ask("u1", "attempt1", 0)
    assert target.question_hash == "h1"
    assert target.course_id == "c1"
