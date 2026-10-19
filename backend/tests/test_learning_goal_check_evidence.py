"""Actual check-submission provenance used to continue confirmed goals."""

import asyncio
from unittest.mock import patch

import pytest
from starlette.requests import Request

from learning.goals import encode_goal
from models import LoopCheckAnswerBody, LoopGoal
from test_learn_loop_routes import ITEM, seams as seams
import routes.learn_loop as rl


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
