"""Crash/cold-worker timing and late-completion protection, without AI calls."""

import asyncio
import copy
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from starlette.requests import Request

from learning import turn_activity
from learning.ladder import Rung
from tests import test_learn_loop_routes as routes
from tests.test_learning_teach_attempt import CLAIM

client = routes.client
gate_on, seams, no_rate_limit = routes.gate_on, routes.seams, routes.no_rate_limit
NOW = routes.NOW


@pytest.fixture(autouse=True)
def clear_worker_memory():
    from routes import learn_loop

    learn_loop._FAILED_TURN_ANCHORS.clear()
    yield
    learn_loop._FAILED_TURN_ANCHORS.clear()


@pytest.mark.parametrize("value", [None, {}, [], {"id": "old", "state": "complete", "at": True}, {"id": "old", "state": "unknown", "at": NOW}, {"id": "old", "state": "complete", "at": float("nan")}])
def test_malformed_activity_never_earns_independent_time(value):
    assert turn_activity.timing({turn_activity.KEY: value})[1] is True


def test_legacy_absence_keeps_existing_served_time_contract():
    assert turn_activity.timing({}) == (None, False)


def test_new_operation_fences_both_old_completion_and_old_cancellation():
    doc = {}
    turn_activity.begin(doc, "old", NOW - 10)
    turn_activity.begin(doc, "new", NOW)
    expected = copy.deepcopy(doc)
    with pytest.raises(turn_activity.StaleTurnActivity):
        turn_activity.complete(doc, "old", NOW + 1)
    turn_activity.interrupt(doc, "old", NOW + 2)
    assert doc == expected
    turn_activity.complete(doc, "new", NOW + 3)
    with pytest.raises(turn_activity.StaleTurnActivity):
        turn_activity.complete(doc, "new", NOW + 4)
    assert turn_activity.timing(doc) == (NOW + 3, False)


@pytest.mark.parametrize("state", ["pending", "interrupted"])
def test_cold_worker_reads_durable_interruption_instead_of_old_served_time(state, gate_on, seams):
    from routes import learn_loop

    seams.store["doc"] = routes._plan_state(served_at=NOW - 600)
    seams.store["doc"][turn_activity.KEY] = {"id": "old-worker", "state": state, "at": NOW - 5}
    seams.p_known["node-1"] = 0.99
    learn_loop._FAILED_TURN_ANCHORS.clear()  # no warm-worker fallback is available
    agent, _ = routes._json_agent("Think about the input.")
    with patch("routes.learn_loop.loop_tutor_agent", agent), patch("routes.learn_loop.record_agent_usage", side_effect=lambda r, **k: r):
        response = client.post("/api/learn/loop/chat", json={"session_id": "s1", "user_id": "u1", "message": CLAIM})
    assert response.status_code == 200
    assert response.json()["ceiling"] == int(Rung.H1)
    assert seams.store["doc"][turn_activity.KEY]["state"] == "complete"
    seams.flush.assert_not_called()
    seams.grade.assert_not_awaited()


def test_failed_json_turn_persists_timing_and_survives_worker_cache_loss(gate_on, seams):
    from routes import learn_loop

    seams.store["doc"] = routes._plan_state(served_at=NOW - 600)
    original = copy.deepcopy(seams.store["doc"])
    broken = MagicMock()

    async def fail(*args, **kwargs):
        assert seams.store["doc"][turn_activity.KEY]["state"] == "pending"
        raise RuntimeError("provider unavailable")

    broken.run = fail
    with patch("routes.learn_loop.loop_tutor_agent", broken):
        response = client.post("/api/learn/loop/chat", json={"session_id": "s1", "user_id": "u1", "message": CLAIM})
    assert response.status_code >= 500
    assert seams.store["doc"][turn_activity.KEY]["state"] == "interrupted"
    assert seams.store["doc"][turn_activity.KEY]["at"] == NOW
    learn_loop._FAILED_TURN_ANCHORS.clear()
    assert learn_loop._load_loop_state("s1")[turn_activity.KEY]["state"] == "interrupted"
    for key, value in original.items():
        assert seams.store["doc"][key] == value
    seams.save_msg.assert_not_called()
    seams.flush.assert_not_called()


def test_failed_initial_activity_write_never_dispatches_or_serves(gate_on, seams):
    seams.store["doc"] = routes._plan_state()
    seams.save.side_effect = RuntimeError("storage unavailable")
    model = MagicMock(side_effect=AssertionError("No AI before durable activity acknowledgment"))
    with patch("routes.learn_loop.stream_structured_turn", model):
        response = client.post("/api/learn/loop/chat/stream", json={"session_id": "s1", "user_id": "u1", "message": "hello"})
    events = routes._sse_events(response.text)
    assert [e["type"] for e in events] == ["error"]
    assert events[0]["data"]["retryable"] is True
    model.assert_not_called()
    seams.save_msg.assert_not_called()
    seams.flush.assert_not_called()


def test_late_turn_cannot_deliver_feedback_after_newer_operation(gate_on, seams):
    from routes import learn_loop

    doc = routes._graded("correct")
    turn_activity.begin(doc, "newer", NOW)
    before = copy.deepcopy(doc)
    turn = SimpleNamespace(activity_id="older", _now=NOW, phase="feedback", active="qh-1")
    with pytest.raises(learn_loop._StateConflict):
        learn_loop._LoopTurn._apply_turn(turn, doc, {})
    assert doc == before
    assert doc["steps"]["qh-1"]["feedback_given"] is False


def test_late_turn_cannot_change_a_closed_session(gate_on, seams):
    from routes import learn_loop

    doc = {"phase": "close"}
    turn_activity.begin(doc, "older", NOW)
    before = copy.deepcopy(doc)
    turn = SimpleNamespace(activity_id="older", _now=NOW, phase="teach")
    with pytest.raises(learn_loop.HTTPException) as error:
        learn_loop._LoopTurn._apply_turn(turn, doc, {})
    assert error.value.status_code == 409
    assert doc == before


def test_late_interruption_after_legitimate_close_is_info_only_without_reopening(
    gate_on, seams, caplog
):
    from learning.loop_state_store import LoopSessionClosed
    from routes import learn_loop

    seams.store["doc"] = {"phase": "close", "served_at": NOW - 10}
    before = copy.deepcopy(seams.store)
    turn = SimpleNamespace(session_id="s1", activity_id="cancelled-worker")
    with (
        patch("routes.learn_loop.update_loop_state", side_effect=LoopSessionClosed("s1")) as update,
        caplog.at_level(logging.INFO, logger="routes.learn_loop"),
    ):
        learn_loop._LoopTurn.touch_served_at(turn)
    assert update.call_count == 1 and update.call_args.kwargs == {"require_open": True}
    assert seams.store == before
    assert learn_loop._FAILED_TURN_ANCHORS["s1"] == NOW
    records = [r for r in caplog.records if "Tutor interruption timing" in r.getMessage()]
    assert len(records) == 1 and records[0].levelno == logging.INFO
    assert records[0].getMessage() == "Tutor interruption timing skipped: session already closed"
    assert records[0].exc_info is None
    seams.save_msg.assert_not_called()
    seams.flush.assert_not_called()


@pytest.mark.parametrize("failure", [
    (503, "this session is closed"),
    (409, "loop state changed, retry"),
    None,
], ids=["503-is-not-expected-close", "other-409", "database-error"])
def test_unexpected_interruption_write_failures_still_warn_with_traceback(
    gate_on, seams, caplog, failure
):
    from routes import learn_loop

    error = (learn_loop.HTTPException(status_code=failure[0], detail=failure[1])
             if failure is not None else RuntimeError("Synthetic database failure"))
    before = copy.deepcopy(seams.store)
    turn = SimpleNamespace(session_id="s1", activity_id="cancelled-worker")
    with (
        patch("routes.learn_loop._update_loop_state", side_effect=error) as update,
        caplog.at_level(logging.INFO, logger="routes.learn_loop"),
    ):
        learn_loop._LoopTurn.touch_served_at(turn)
    assert update.call_count == 1
    assert update.call_args.kwargs == {"require_open": True, "require_existing": True}
    assert seams.store == before and learn_loop._FAILED_TURN_ANCHORS["s1"] == NOW
    records = [r for r in caplog.records if "Tutor interruption timing" in r.getMessage()]
    assert len(records) == 1 and records[0].levelno == logging.WARNING
    assert records[0].getMessage() == "Tutor interruption timing could not be stored"
    assert records[0].exc_info is not None and records[0].exc_info[1] is error


def test_cancelled_real_route_turn_keeps_durable_interruption(gate_on, seams):
    from models import ChatBody
    from routes import learn_loop

    seams.store["doc"] = routes._plan_state(served_at=NOW - 600)

    async def run():
        waiting = asyncio.Event()

        async def streaming(**kwargs):
            assert seams.store["doc"][turn_activity.KEY]["state"] == "pending"
            waiting.set()
            await asyncio.Event().wait()
            yield  # pragma: no cover - asynchronous generator with no output

        with patch("routes.learn_loop._arm_for", return_value=None), patch("routes.learn_loop.stream_structured_turn", streaming):
            turn = learn_loop._LoopTurn(
                body=ChatBody(session_id="s1", user_id="u1", message="hello"),
                request=Request({"type": "http", "headers": []}),
                message="hello", loop_on=True,
            )

            async def consume():
                return [event async for event in learn_loop._stream_turn(turn)]

            task = asyncio.create_task(consume())
            await asyncio.wait_for(waiting.wait(), timeout=2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(run())
    assert seams.store["doc"][turn_activity.KEY]["state"] == "interrupted"
    assert seams.store["doc"][turn_activity.KEY]["at"] == NOW
    learn_loop._FAILED_TURN_ANCHORS.clear()
    assert learn_loop._load_loop_state("s1")[turn_activity.KEY]["state"] == "interrupted"
    seams.save_msg.assert_not_called()
    seams.flush.assert_not_called()
