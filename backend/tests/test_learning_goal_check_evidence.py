"""Actual check-submission provenance used to continue confirmed goals."""

import asyncio
from copy import deepcopy
from unittest.mock import patch

import pytest
from starlette.requests import Request
from fastapi import HTTPException

from learning import grade_checkpoint
from learning.evidence import Evidence, PlanningPersistenceUnavailable, planning_observation
from learning.goals import encode_goal
from models import LoopCheckAnswerBody, LoopGoal
from test_learn_loop_routes import ITEM, seams as seams
import routes.learn_loop as rl
from test_learning_probe_planner import _grader


@pytest.mark.parametrize(
    "rung,recheck,seen,late_floor,expected",
    [
        (0, False, False, 0, True),
        (1, False, False, 1, False),
        (0, True, False, 0, False),
        (0, False, True, 0, False),
        (0, False, False, 3, False),
    ],
)
def test_actual_grade_carries_final_help_exposure_and_recheck_provenance(
    seams, rung, recheck, seen, late_floor, expected
):
    seams.store["doc"]["steps"]["qh-1"]["rung"] = rung
    seams.store["doc"]["goal"] = encode_goal(LoopGoal(target_node_ids=["node-1"]))
    seams.seen_hashes.return_value = {"qh-1"} if seen else set()
    body = LoopCheckAnswerBody(
        session_id="s1", user_id="u1", question_hash="qh-1", answer="n == 0 returns1"
    )
    request = Request(
        {"type": "http", "method": "POST", "path": "/api/learn/loop/check/answer", "headers": []}
    )
    with (
        patch.object(rl, "recheck_after_release", return_value=recheck),
        patch.object(rl, "_reveal_floor", side_effect=[rung, late_floor]),
    ):
        submission = asyncio.run(rl._grade_submission(body, request, loop_on=True))
    assert submission.kind == "feedback"
    observation = seams.store["doc"]["steps"]["qh-1"]["goal_observation"]
    assert observation["independent"] is expected
    assert observation["max_rung"] == max(rung, late_floor)
    assert observation["same_session_recheck"] is recheck
    assert observation["previously_seen"] is seen
    assert observation["difficulty"] == ITEM.difficulty
    assert observation["channel"] == "free_response"
    assert body.answer not in repr(observation)
    seams.flush.assert_called_once()  # metadata never adds a second evidence write


@pytest.mark.parametrize("goal,synthetic", [(False, False), (True, False), (False, True)])
def test_actual_check_tags_durable_provenance_in_goal_and_coursewide_sessions(
    seams, goal, synthetic
):
    seams.store["doc"]["steps"]["qh-1"]["rung"] = 0
    if goal:
        seams.store["doc"]["goal"] = encode_goal(LoopGoal(target_node_ids=["node-1"]))
    if synthetic:
        seams.store["doc"]["steps"]["qh-1"]["refusals"] = rl.CHECK_REFUSALS_AS_IDK - 1
    seams.grade.side_effect = _grader(
        correct=False, refused="grading_directive" if synthetic else None
    )
    captured = []
    seams.flush.side_effect = lambda deps, _course: captured.extend(deepcopy(deps.pending_evidence))
    body = LoopCheckAnswerBody(
        session_id="s1", user_id="u1", question_hash="qh-1", answer="A real attempt"
    )
    request = Request({"type": "http", "method": "POST", "path": "/check/answer", "headers": []})
    with patch.object(rl, "_reveal_floor", return_value=0):
        submission = asyncio.run(rl._grade_submission(body, request, loop_on=True))
    assert submission.kind == "feedback"
    assert len(captured) == 1
    observation = planning_observation(Evidence.model_validate(captured[0]))
    assert observation["synthetic_idk"] is synthetic
    assert observation["independent"] is not synthetic
    assert observation["difficulty"] == ITEM.difficulty
    assert body.answer not in repr(observation)


def test_strict_check_write_failure_retains_saved_grade_and_retries_one_operation(seams):
    seams.grade.side_effect = _grader(correct=False)
    seams.flush.side_effect = PlanningPersistenceUnavailable("append failed before scalar writes")
    body = LoopCheckAnswerBody(
        session_id="s1", user_id="u1", question_hash="qh-1", answer="A real attempt"
    )
    request = Request({"type": "http", "method": "POST", "path": "/check/answer", "headers": []})
    with patch.object(rl, "_reveal_floor", return_value=0):
        with pytest.raises(HTTPException) as failure:
            asyncio.run(rl._grade_submission(body, request, loop_on=True))
    assert failure.value.status_code == 503
    step = seams.store["doc"]["steps"]["qh-1"]
    assert "graded_at" not in step and step["grading_claim"]
    saved = grade_checkpoint.open_checkpoint(
        step[grade_checkpoint.KEY], kind="check", operation_id=step["grading_claim"],
        user_id="u1", session_id="s1", course_id="c1", question_hash="qh-1",
    )
    assert body.answer not in repr(seams.store["doc"])
    assert not seams.receipts  # The failed atomic append acknowledges no operation.
    committed = {}

    def flush(deps, _course):
        batch = deepcopy(deps.pending_evidence)
        operation = batch[0]["operation_id"]
        if operation in committed:
            assert committed[operation] == batch
        else:
            committed[operation] = batch
        deps.pending_evidence.clear()
        return []

    seams.flush.side_effect = flush
    changed = body.model_copy(update={"answer": "A changed retry must not replace the original"})
    result = asyncio.run(rl._grade_submission(changed, request, loop_on=True))
    assert result.kind == "feedback" and result.rendered == body.answer
    assert result.verdict == "not_yet"
    assert list(committed) == list(seams.receipts) == [saved.operation_id]
    assert committed[saved.operation_id] == saved.evidence
    step = seams.store["doc"]["steps"]["qh-1"]
    assert step["graded"] == 1 and step["graded_operation_id"] == saved.operation_id
    assert "grading_claim" not in step and grade_checkpoint.KEY not in step
    assert seams.store["doc"]["checks_since_rating"] == 1
    seams.grade.assert_awaited_once()
    assert seams.flush.call_count == 2  # Failed append, then one successful atomic operation.
    with pytest.raises(HTTPException) as duplicate:
        asyncio.run(rl._grade_submission(body, request, loop_on=True))
    assert duplicate.value.status_code == 409
    assert len(committed) == 1 and seams.flush.call_count == 2
