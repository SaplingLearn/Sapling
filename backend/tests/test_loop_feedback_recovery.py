"""A committed check grade cannot lose its pending feedback to Check me.

The failure/retry case runs the real structured agent and stream producer with
FunctionModel output. The existing route fixture isolates storage/providers.
"""

from __future__ import annotations

import copy
import json
from unittest.mock import patch

import pytest
from pydantic_ai.models.function import FunctionModel

from agents.loop_tutor import loop_tutor_agent
from tests import test_learn_loop_routes as routes

gate_on, no_rate_limit, seams = routes.gate_on, routes.no_rate_limit, routes.seams
DETAIL = "feedback pending; retry feedback before another check"
NEXT = routes.ITEM.model_copy(update={"id": "item-next", "question_hash": "qh-next"})


@pytest.mark.parametrize("flag", [None, False, 0, 1, "true"])
def test_pending_feedback_blocks_activation_without_mutating_grade_or_counters(
    gate_on, seams, flag
):
    from routes.learn_loop import _phase_for

    state = routes._plan_state(teach_turns=2, concept_checks=1)
    state.update(routes._graded("not_yet", feedback_given=flag))
    seams.store["doc"] = state
    before = copy.deepcopy(state)
    assert _phase_for(before) == "feedback"  # status/retry uses the same strict completion flag
    seams.list_items.return_value = [NEXT]

    response = routes.client.post(
        "/api/learn/loop/check/next", json={"session_id": "s1", "user_id": "u1"}
    )

    assert response.status_code == 409 and response.json()["detail"] == DETAIL
    assert seams.store["doc"] == before
    seams.save.assert_not_called()
    seams.select_item.assert_not_called()
    seams.save_msg.assert_not_called()
    seams.grade.assert_not_awaited()
    seams.flush.assert_not_called()


def test_feedback_pending_is_rechecked_after_a_cas_race(gate_on, seams):
    seams.store["doc"] = routes._plan_state()
    seams.list_items.return_value = [NEXT]
    pending = routes._plan_state(concept_checks=1, teach_turns=0)
    pending.update(routes._graded("correct"))
    seams.store["conflicts"] = 1

    def grade_wins(doc):
        doc.clear()
        doc.update(copy.deepcopy(pending))

    seams.store["racer"] = grade_wins
    response = routes.client.post(
        "/api/learn/loop/check/next", json={"session_id": "s1", "user_id": "u1"}
    )

    assert response.status_code == 409 and response.json()["detail"] == DETAIL
    assert seams.store["doc"] == pending  # do not overwrite the concurrent committed grade
    assert "qh-next" not in seams.store["doc"]["steps"]
    seams.save_msg.assert_not_called()
    seams.grade.assert_not_awaited()
    seams.flush.assert_not_called()


def test_real_shape_failure_retries_saved_feedback_once_then_allows_next_check(gate_on, seams):
    good = {
        "key_idea": "The base case stops recursion.",
        "body": "It provides a stopping condition for the function.",
        "question": "Which input should stop the function?",
    }
    bad = {**good, "question": "Review the stopping condition. Which input should stop it?"}
    calls = []

    async def stream(messages, info):
        calls.append(1)
        text = json.dumps(bad if len(calls) <= 3 else good)
        for index in range(0, len(text), 6):
            yield text[index : index + 6]

    def nonstream(messages, info):
        raise AssertionError("a feedback stream with tokens must not auto-rerun")

    model = FunctionModel(nonstream, stream_function=stream)
    state = routes._plan_state()
    state.update(routes._state())
    seams.store["doc"] = state
    seams.grade.return_value = routes.WRONG
    seams.list_items.return_value = [routes.ITEM, NEXT]
    seams.item.side_effect = lambda item_id: NEXT if item_id == NEXT.id else routes.ITEM

    with (
        patch("routes.learn_loop.loop_tutor_agent", loop_tutor_agent),
        patch("routes.learn_loop.tier_run_kwargs", return_value={"model": model}),
        patch("routes.learn_loop.record_agent_usage", side_effect=lambda result, **kwargs: result),
    ):
        failed = routes.client.post(
            "/api/learn/loop/check/answer/stream", json=routes._answer(answer="it never stops")
        )
        events = routes._sse_events(failed.text)
        assert events[-1]["type"] == "error" and not any(e["type"] == "done" for e in events)
        assert len(calls) == 3
        pending = copy.deepcopy(seams.store["doc"])
        grade = pending["steps"]["qh-1"]
        assert grade["graded"] == 1 and grade["feedback_given"] is False
        assert pending["current"] == "qh-1" and pending["concept_checks"] == 0

        blocked = routes.client.post(
            "/api/learn/loop/check/next", json={"session_id": "s1", "user_id": "u1"}
        )
        assert blocked.status_code == 409 and blocked.json()["detail"] == DETAIL
        assert seams.store["doc"] == pending

        # Retrying the original answer is prohibited. The recovery is CHAT,
        # which derives feedback from the saved verdict and never grades again.
        duplicate = routes.client.post(
            "/api/learn/loop/check/answer/stream", json=routes._answer(answer="it never stops")
        )
        assert duplicate.status_code == 409 and duplicate.json()["detail"] == "already graded"
        recovered = routes.client.post(
            "/api/learn/loop/chat/stream",
            json={"session_id": "s1", "user_id": "u1", "message": "Let's continue."},
        )
        done = routes._sse_events(recovered.text)[-1]
        assert done["type"] == "done" and done["data"]["phase"] == "feedback"
        assert len(calls) == 4
        after = seams.store["doc"]
        assert after["current"] is None and after["steps"]["qh-1"]["feedback_given"] is True
        assert after["steps"]["qh-1"]["graded"] == 1 and after["concept_checks"] == 1
        seams.grade.assert_awaited_once()
        seams.flush.assert_called_once()
        seams.zpd.emit_zpd_step.assert_called_once()

        following = routes.client.post(
            "/api/learn/loop/check/next", json={"session_id": "s1", "user_id": "u1"}
        )
        assert following.status_code == 200
        assert following.json()["check"]["question_hash"] == NEXT.question_hash
        seams.grade.assert_awaited_once()
        seams.flush.assert_called_once()
