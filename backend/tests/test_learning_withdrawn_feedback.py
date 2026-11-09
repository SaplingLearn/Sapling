"""A withdrawn graded check finishes from metadata, never removed content/AI.

The shared route fixtures retain actual loop-state CAS/policy and use hermetic
DB/model seams. Real checkpoint/receipt/browser coverage runs in the DB lane.
"""

from copy import deepcopy
import json
from unittest.mock import MagicMock, patch

import pytest

from learning.evidence import PlanningPersistenceUnavailable
from learning.grade_checkpoint import KEY
from tests import test_learn_loop_routes as routes

gate_on, no_rate_limit, seams = routes.gate_on, routes.no_rate_limit, routes.seams


def _response(response, streamed):
    assert response.status_code == 200, response.text
    if not streamed:
        return response.json()
    events = routes._sse_events(response.text)
    assert [event for event in events if event["type"] == "error"] == []
    done = [event for event in events if event["type"] == "done"]
    assert len(done) == 1 and events[-1]["type"] == "done"
    assert done[0]["data"]["reply"].strip()
    return done[0]["data"]


def _assert_no_removed_content(value):
    text = json.dumps(value)
    for removed in (routes.ITEM.prompt, routes.ITEM.reference_answer, routes.ITEM.final_answer):
        assert removed not in text


@pytest.mark.parametrize("streamed", [False, True], ids=["json", "sse"])
@pytest.mark.parametrize("verdict", ["correct", "not_yet", "idk"])
def test_reload_pending_withdrawn_feedback_serves_only_recorded_result_once(
    gate_on, seams, streamed, verdict
):
    seams.store["doc"] = routes._graded(verdict)
    seams.store["doc"].update(concept_checks=0, teach_turns=0, checks_since_rating=1)
    original_grade = deepcopy(seams.store["doc"]["steps"]["qh-1"])
    seams.item.return_value = None
    with (
        patch("routes.learn_loop._prepare_loop_run", side_effect=AssertionError("No model/context for withdrawal")) as prepare,
        patch("routes.learn_loop.stream_structured_turn", side_effect=AssertionError("No model stream for withdrawal")) as stream,
        patch("routes.learn_loop.record_agent_usage") as usage,
    ):
        # A fresh status request must retain the outstanding feedback phase,
        # while returning no withdrawn prompt/reference or open check.
        resumed = routes.client.get("/api/learn/loop/status", params={"user_id": "u1", "session_id": "s1"})
        assert resumed.status_code == 200
        assert resumed.json()["phase"] == "feedback" and resumed.json()["check"] is None
        _assert_no_removed_content(resumed.json())
        response = routes.client.post(
            "/api/learn/loop/chat" + ("/stream" if streamed else ""),
            json={"session_id": "s1", "user_id": "u1", "message": "Continue"},
        )
        data = _response(response, streamed)
        assert data["phase"] == "feedback" and data["tier"] == "none"
        assert "withdrawn" in data["reply"] and "recorded" in data["reply"]
        assert data["hint_offer"] is None and data["check"] is None
        _assert_no_removed_content(data)
        prepare.assert_not_called()
        stream.assert_not_called()
        usage.assert_not_called()

    doc = seams.store["doc"]
    entry = doc["steps"]["qh-1"]
    assert entry["feedback_given"] is True and entry["feedback_withdrawn"] is True
    assert doc["current"] is None and doc["concept_checks"] == 1
    assert doc["teach_turns"] == 0 and doc["checks_since_rating"] == 1
    assert {key: entry[key] for key in original_grade} == {
        **original_grade, "feedback_given": True,
    }
    seams.grade.assert_not_awaited()
    seams.flush.assert_not_called()
    seams.ai_budget.count_tutor_call.assert_not_called()
    seams.zpd.emit_zpd_step.assert_not_called()  # missing difficulty is not invented
    before_reload = deepcopy(doc)
    resumed = routes.client.get("/api/learn/loop/status", params={"user_id": "u1", "session_id": "s1"})
    assert resumed.status_code == 200 and resumed.json()["phase"] == "teach"
    assert seams.store["doc"] == before_reload


@pytest.mark.parametrize("streamed", [False, True], ids=["json", "sse"])
def test_saved_check_grade_recovers_after_item_withdrawal_without_second_grade_or_model(
    gate_on, seams, streamed
):
    seams.flush.side_effect = PlanningPersistenceUnavailable("Synthetic precommit interruption")
    failed = routes.client.post("/api/learn/loop/check/answer", json=routes._answer(answer="Original saved answer"))
    assert failed.status_code == 503
    held = seams.store["doc"]["steps"]["qh-1"]
    operation, ciphertext = held["grading_claim"], held[KEY]
    assert isinstance(ciphertext, str) and "Original saved answer" not in ciphertext
    seams.grade.assert_awaited_once()
    assert "graded_at" not in held and held["feedback_given"] is False

    seams.item.return_value = None
    seams.flush.side_effect = None
    resumed = routes.client.get("/api/learn/loop/status", params={"user_id": "u1", "session_id": "s1"})
    assert resumed.status_code == 200
    assert resumed.json()["pending_grade"] == {"kind": "check", "question_hash": "qh-1"}
    assert resumed.json()["check"] is None
    with (
        patch("routes.learn_loop._prepare_loop_run", side_effect=AssertionError("No model/context for withdrawal")) as prepare,
        patch("routes.learn_loop.stream_structured_turn", side_effect=AssertionError("No model stream for withdrawal")) as stream,
        patch("routes.learn_loop.record_agent_usage") as usage,
    ):
        response = routes.client.post(
            "/api/learn/loop/check/answer" + ("/stream" if streamed else ""),
            json=routes._answer(answer="Changed retry cannot replace the grade"),
        )
        data = _response(response, streamed)
        assert data["graded"] is True and data["verdict"] == "correct"
        assert data["phase"] == "feedback" and data["tier"] == "none"
        assert data["answer_released"] is False
        assert "withdrawn" in data["reply"] and "recorded as correct" in data["reply"]
        _assert_no_removed_content(data)
        prepare.assert_not_called()
        stream.assert_not_called()
        usage.assert_not_called()
    final = seams.store["doc"]
    entry = final["steps"]["qh-1"]
    assert entry["graded"] == 1 and entry["graded_operation_id"] == operation
    assert entry["feedback_given"] is True and entry["feedback_withdrawn"] is True
    assert KEY not in entry and "grading_claim" not in entry
    assert final["current"] is None and final["concept_checks"] == 1
    assert final["checks_since_rating"] == 1 and len(seams.receipts) == 1
    assert seams.flush.call_count == 2
    seams.grade.assert_awaited_once()
    seams.ai_budget.count_tutor_call.assert_not_called()
    reloaded = routes.client.get("/api/learn/loop/status", params={"user_id": "u1", "session_id": "s1"})
    assert reloaded.status_code == 200 and reloaded.json()["phase"] == "teach"
    assert reloaded.json()["pending_grade"] is None


def test_stale_withdrawal_completion_cannot_count_feedback_twice(gate_on, seams):
    from fastapi import HTTPException
    from models import ChatBody
    from routes.learn_loop import _LoopTurn

    seams.store["doc"] = routes._graded("idk")
    seams.item.return_value = None
    turn = _LoopTurn(
        body=ChatBody(session_id="s1", user_id="u1", message="Continue"),
        request=MagicMock(), message="Continue", loop_on=True,
    )
    turn.plan(routes.NORMAL)
    assert turn.tier == "none"
    turn.complete(turn.text, {}, [])
    delivered = deepcopy(seams.store["doc"])
    with pytest.raises(HTTPException) as failed:
        turn.complete(turn.text, {}, [])
    assert failed.value.status_code == 409
    assert seams.store["doc"] == delivered and delivered["concept_checks"] == 1
    seams.grade.assert_not_awaited()
    seams.flush.assert_not_called()
