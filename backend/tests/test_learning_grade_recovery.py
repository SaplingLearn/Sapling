"""Grade crash boundaries: exact evidence replay and one session continuation."""

import asyncio
from copy import deepcopy
import json
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from learning import grade_checkpoint
from learning.evidence import PlanningPersistenceUnavailable
from learning.evidence_transaction import EvidenceObservationSuperseded
from models import ChatBody, LoopCheckAnswerBody, EndSessionBody
from routes import learn_loop
from tests import test_learn_loop_routes as routes

client = routes.client
gate_on, seams, no_rate_limit = routes.gate_on, routes.seams, routes.no_rate_limit


def submit(answer="The base case returns 1"):
    return asyncio.run(learn_loop._grade_submission(
        LoopCheckAnswerBody(**routes._answer(answer=answer)),
        Request({"type": "http", "headers": []}), loop_on=True,
    ))


def checkpoint(seams):
    entry = seams.store["doc"]["steps"]["qh-1"]
    return grade_checkpoint.open_checkpoint(entry[grade_checkpoint.KEY], kind="check",
        operation_id=entry["grading_claim"], user_id="u1", session_id="s1", course_id="c1",
        question_hash="qh-1")


@pytest.mark.parametrize("failure", [RuntimeError("transport lost"), PlanningPersistenceUnavailable("DB down")])
def test_cold_retry_uses_saved_answer_and_operation_without_regrading(gate_on, seams, failure):
    seams.flush.side_effect = failure
    with pytest.raises((RuntimeError, HTTPException)):
        submit()
    saved = checkpoint(seams)
    assert "base case" not in json.dumps(seams.store["doc"])
    assert grade_checkpoint.KEY in seams.store["doc"]["steps"]["qh-1"]
    learn_loop._FAILED_TURN_ANCHORS.clear()
    seams.flush.side_effect = None
    result = submit("A different answer on retry must not be graded")
    assert result.kind == "feedback" and result.rendered == "The base case returns 1"
    assert result.verdict == "correct"
    seams.grade.assert_awaited_once()
    assert seams.flush.call_args.args[0].pending_evidence == saved.evidence
    entry = seams.store["doc"]["steps"]["qh-1"]
    assert entry["graded"] == 1 and entry["graded_operation_id"] == saved.operation_id
    assert grade_checkpoint.KEY not in entry and "grading_claim" not in entry
    assert seams.store["doc"]["checks_since_rating"] == 1


@pytest.mark.parametrize("after_save", [False, True])
def test_lost_session_ack_never_grades_or_commits_evidence_twice(gate_on, seams, after_save):
    real_update = learn_loop._update_loop_state
    armed = True
    committed = {}

    def flush(deps, course):
        batch = deepcopy(deps.pending_evidence)
        operation = batch[0]["operation_id"]
        if operation in committed:
            assert batch == committed[operation]
        else:
            committed[operation] = batch
        deps.pending_evidence.clear()
        return []

    def lose_ack(sid, mutate, **kw):
        nonlocal armed
        if armed and mutate.__name__ == "record_grade_and_diagnosis":
            armed = False
            if after_save:
                real_update(sid, mutate, **kw)
            raise learn_loop._StateConflict()
        return real_update(sid, mutate, **kw)

    seams.flush.side_effect = flush
    with patch.object(learn_loop, "_update_loop_state", lose_ack):
        with pytest.raises(HTTPException):
            submit()
    if after_save:
        assert grade_checkpoint.KEY not in seams.store["doc"]["steps"]["qh-1"]
        with pytest.raises(HTTPException) as duplicate:
            submit()
        assert duplicate.value.status_code == 409
        assert seams.flush.call_count == 1
    else:
        assert checkpoint(seams).operation_id in committed
        assert submit().kind == "feedback"
        assert seams.flush.call_count == 2  # same atomic receipt, one actual write
    seams.grade.assert_awaited_once()
    assert len(committed) == 1
    assert seams.store["doc"]["steps"]["qh-1"]["graded"] == 1
    assert seams.store["doc"]["checks_since_rating"] == 1


def test_lost_checkpoint_ack_is_recoverable_without_a_second_grader(gate_on, seams):
    real_update = learn_loop._update_loop_state
    armed = True

    def save_then_lose_ack(sid, mutate, **kw):
        nonlocal armed
        doc = real_update(sid, mutate, **kw)
        if armed and mutate.__name__ == "save" and grade_checkpoint.KEY in doc["steps"]["qh-1"]:
            armed = False
            raise RuntimeError("checkpoint acknowledgment lost")
        return doc

    with patch.object(learn_loop, "_update_loop_state", save_then_lose_ack), pytest.raises(RuntimeError):
        submit()
    seams.flush.assert_not_called()
    saved = checkpoint(seams)
    assert submit().kind == "feedback"
    assert seams.store["doc"]["steps"]["qh-1"]["graded_operation_id"] == saved.operation_id
    seams.grade.assert_awaited_once()


def test_saved_checkpoint_cannot_expire_or_disappear_on_withdrawal(gate_on, seams):
    seams.flush.side_effect = PlanningPersistenceUnavailable("DB down")
    with pytest.raises(HTTPException):
        submit()
    seams.store["doc"]["steps"]["qh-1"]["grading_claim_at"] = 1
    before = deepcopy(seams.store["doc"])
    seams.item.side_effect = AssertionError("Saved grade recovery does not re-read withdrawn question")
    response = client.post("/api/learn/loop/check/next", json={"session_id": "s1", "user_id": "u1"})
    assert response.status_code == 200
    assert response.json()["pending_grade"] == {"kind": "check", "question_hash": "qh-1"}
    assert seams.store["doc"] == before
    assert learn_loop._grading_in_flight(before, routes.NOW + 100000)
    seams.flush.side_effect = None
    assert submit().kind == "feedback"
    seams.grade.assert_awaited_once()


def test_corrupt_checkpoint_reports_generic_error_without_regrading(gate_on, seams):
    seams.store["doc"]["steps"]["qh-1"].update({"grading_claim": "invalid", grade_checkpoint.KEY: "private-invalid-data"})
    with pytest.raises(HTTPException) as error:
        submit()
    assert error.value.status_code == 503
    assert "private-invalid-data" not in str(error.value.detail)
    seams.grade.assert_not_awaited()
    seams.flush.assert_not_called()


def test_check_goal_uses_committed_exposure_instead_of_optimistic_checkpoint(gate_on, seams):
    seams.store["doc"]["goal"] = {"target_node_ids": ["node-1"]}
    seams.store["doc"]["steps"]["qh-1"]["rung"] = 0
    original_receipt = seams.receipt.side_effect

    def another_session_was_first(user_id, operation):
        receipt = original_receipt(user_id, operation)
        final = receipt["observations"][0]
        assert final["independent"] is True
        final.update(previously_seen=True, independent=False)
        return receipt

    seams.receipt.side_effect = another_session_was_first
    assert submit().kind == "feedback"
    original = seams.flush.call_args.args[0].pending_evidence[0]
    assert original["planning_provenance"]["previously_seen"] is False
    observed = seams.store["doc"]["steps"]["qh-1"]["goal_observation"]
    assert observed["correct"] is True
    assert observed["previously_seen"] is True and observed["independent"] is False
    seams.grade.assert_awaited_once()


def test_missing_committed_observation_retains_recovery_checkpoint(gate_on, seams):
    original_receipt = seams.receipt.side_effect

    def incomplete(user_id, operation):
        value = deepcopy(original_receipt(user_id, operation))
        value["observations"] = []
        return value

    seams.receipt.side_effect = incomplete
    with pytest.raises(HTTPException) as error:
        submit()
    assert error.value.status_code == 503 and checkpoint(seams)
    assert seams.store["doc"]["steps"]["qh-1"].get("graded_at") is None
    seams.receipt.side_effect = original_receipt
    assert submit().kind == "feedback"
    seams.grade.assert_awaited_once()


def test_older_uncommitted_answer_is_retired_without_fabricating_diagnosis(gate_on, seams):
    seams.flush.side_effect = EvidenceObservationSuperseded("newer evidence exists")
    with pytest.raises(HTTPException) as error:
        submit()
    assert error.value.status_code == 409
    entry = seams.store["doc"]["steps"]["qh-1"]
    assert entry["grading_superseded"] and entry.get("graded", 0) == 0
    assert "graded_at" not in entry
    assert "goal_observation" not in entry and grade_checkpoint.KEY not in entry
    assert seams.store["doc"]["current"] is None
    assert not learn_loop._grading_in_flight(seams.store["doc"], routes.NOW)
    with pytest.raises(HTTPException):
        submit()
    seams.grade.assert_awaited_once()


@pytest.mark.parametrize("changed", ["closed", "new_goal", "lost_claim"])
def test_replay_checks_current_session_fences_before_flushing(gate_on, seams, changed):
    seams.flush.side_effect = PlanningPersistenceUnavailable("DB down")
    with pytest.raises(HTTPException):
        submit()
    saved = checkpoint(seams)
    if changed == "closed":
        seams.store["doc"]["phase"] = "close"
    elif changed == "new_goal":
        seams.store["doc"]["goal_version"] = 1
    else:
        seams.store["doc"]["steps"]["qh-1"]["grading_claim"] = "other"
    seams.flush.reset_mock()
    with pytest.raises(HTTPException):
        learn_loop._finish_check_checkpoint(saved, ("off-1", "c1"), Request({"type": "http", "headers": []}), loop_on=True)
    seams.flush.assert_not_called()


@pytest.mark.parametrize("failure", [HTTPException(409, "a check is being graded; close again in a moment"), RuntimeError("DB unavailable")])
def test_legacy_end_does_not_close_over_an_unacknowledged_grade(gate_on, seams, failure):
    handle = seams.events  # no writes to the real table in this hermetic test

    def fail_close(coro, *args, **kwargs):
        coro.close()  # the fake runner owns the coroutine it refuses to execute
        raise failure

    with patch.object(learn_loop, "table") as table, patch.object(learn_loop, "run_agent_sync", side_effect=fail_close):
        table.return_value.select.return_value = [{"loop_state": routes._state()}]
        with pytest.raises(HTTPException) as error:
            learn_loop.end_session(EndSessionBody(session_id="s1", user_id="u1"), Request({"type": "http", "headers": []}))
    assert error.value.status_code in (409, 503)
    handle.log_event.assert_not_called()


@pytest.mark.parametrize("path", ["/api/learn/loop/chat", "/api/learn/loop/chat/stream"])
def test_chat_cannot_clear_a_withdrawn_saved_grade_or_start_a_model(gate_on, seams, path):
    seams.flush.side_effect = PlanningPersistenceUnavailable("DB down")
    with pytest.raises(HTTPException):
        submit()
    saved = checkpoint(seams)
    before = deepcopy(seams.store["doc"])
    seams.item.side_effect = AssertionError("A pending grade must precede withdrawn-item lookup")
    seams.ai_budget.reset_mock()
    with patch.object(learn_loop, "_LoopTurn") as turn, patch.object(learn_loop, "loop_tutor_agent") as agent:
        response = client.post(path, json={"session_id": "s1", "user_id": "u1", "message": "continue"})
    assert response.status_code == 409
    assert saved.operation_id not in response.text and grade_checkpoint.KEY not in response.text
    assert seams.store["doc"] == before
    assert seams.store["doc"]["current"] == "qh-1"
    turn.assert_not_called()
    agent.run.assert_not_called()
    agent.run_stream_events.assert_not_called()
    seams.ai_budget.check.assert_not_called()
    seams.grade.assert_awaited_once()


def test_stale_withdrawn_turn_cannot_clear_a_new_saved_grade(gate_on, seams):
    # This turn derived withdrawal before another request saved its answer.
    seams.item.return_value = None
    turn = learn_loop._LoopTurn(
        body=ChatBody(session_id="s1", user_id="u1", message="continue"),
        request=Request({"type": "http", "headers": []}), message="continue", loop_on=True,
    )
    assert turn.withdrawn == "qh-1" and turn.active is None
    seams.item.return_value = routes.ITEM
    seams.flush.side_effect = PlanningPersistenceUnavailable("DB down")
    with pytest.raises(HTTPException):
        submit()
    before = deepcopy(seams.store["doc"])
    seams.ai_budget.reset_mock()
    effects = {"stale": "must be cleared"}
    with pytest.raises(HTTPException) as error:
        turn._apply_turn(seams.store["doc"], effects)
    assert error.value.status_code == 409
    assert effects == {}
    assert seams.store["doc"] == before and seams.store["doc"]["current"] == "qh-1"
    assert checkpoint(seams).operation_id == before["steps"]["qh-1"]["grading_claim"]
    seams.ai_budget.check.assert_not_called()
    seams.grade.assert_awaited_once()
